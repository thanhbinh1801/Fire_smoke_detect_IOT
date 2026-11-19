# preprocessing.py
"""
Module tiền xử lý hình ảnh (Preprocessing Pipeline) cho hệ thống nhận diện Lửa & Khói.

Bao gồm các bước:
1. Chuẩn hóa đầu vào (Validate & Normalize): đảm bảo ảnh BGR uint8 3 kênh hợp lệ, cắt ROI (nếu cấu hình).
2. Tăng cường chất lượng ảnh (Image Enhancement - cấu hình qua .env):
   - Khử nhiễu cảm biến (Gaussian Denoise) giảm báo giả khói trong điều kiện thiếu sáng.
   - Cân bằng trắng tự động (Gray-World Auto White Balance) ổn định màu lửa/khói dưới ánh đèn màu.
   - Hiệu chỉnh sáng Gamma tốc độ cao bằng bảng tra cứu LUT O(1) (cv2.LUT).
   - Cân bằng tương phản cục bộ thích nghi (CLAHE trên kênh L của hệ màu LAB) làm nổi rõ đám khói mờ.
   - Làm sắc nét biên (Unsharp Mask / Sharpening).
3. Letterbox Resize & Tạo Blob NCHW (Tối ưu bộ nhớ):
   - Giữ nguyên tỷ lệ khung hình (Aspect Ratio), đệm viền xám (114).
   - Tái sử dụng bộ đệm Letterbox cấp phát sẵn (Pre-allocated Buffer) để tránh cấp phát RAM lặp lại.
   - Chuyển đổi BGR -> RGB, chuẩn hóa [0, 1] float32 NCHW bằng SIMD C++ (cv2.dnn.blobFromImage).
"""

import cv2
import numpy as np

import config


def parse_roi(roi_spec, frame_w: int, frame_h: int):
    """
    Phân tích cấu hình ROI từ chuỗi "x1,y1,x2,y2" (tỷ lệ 0.0-1.0 hoặc tọa độ pixel).
    Trả về (x1, y1, x2, y2) theo pixel hoặc None nếu dùng toàn khung hình.
    """
    if not roi_spec:
        return None
    if isinstance(roi_spec, str):
        parts = [p.strip() for p in roi_spec.split(",") if p.strip()]
        if len(parts) != 4:
            return None
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            return None
    elif isinstance(roi_spec, (list, tuple)) and len(roi_spec) == 4:
        vals = [float(v) for v in roi_spec]
    else:
        return None

    if all(0.0 <= v <= 1.0 for v in vals):
        x1 = int(round(vals[0] * frame_w))
        y1 = int(round(vals[1] * frame_h))
        x2 = int(round(vals[2] * frame_w))
        y2 = int(round(vals[3] * frame_h))
    else:
        x1, y1, x2, y2 = (int(round(v)) for v in vals)

    x1 = max(0, min(frame_w - 2, x1))
    y1 = max(0, min(frame_h - 2, y1))
    x2 = max(x1 + 1, min(frame_w, x2))
    y2 = max(y1 + 1, min(frame_h, y2))

    if x1 == 0 and y1 == 0 and x2 == frame_w and y2 == frame_h:
        return None
    return (x1, y1, x2, y2)


class FramePreprocessor:
    """
    Bộ tiền xử lý khung hình trước khi đưa vào ONNX Runtime.
    Thiết kế tối ưu cho CPU Raspberry Pi và Laptop.
    """

    def __init__(
        self,
        input_w: int = 320,
        input_h: int = 320,
        pad_value: int = 114,
        enable_clahe: bool = None,
        clahe_clip_limit: float = None,
        clahe_grid_size: int = None,
        gamma: float = None,
        denoise_kernel: int = None,
        auto_wb: bool = None,
        sharpen: bool = None,
        roi_spec: str = None,
    ):
        self.input_w = max(1, int(input_w))
        self.input_h = max(1, int(input_h))
        self.pad_value = int(pad_value)

        self.enable_clahe = (
            bool(getattr(config, "PREPROCESS_ENABLE_CLAHE", False))
            if enable_clahe is None
            else bool(enable_clahe)
        )
        self.clahe_clip_limit = float(
            getattr(config, "PREPROCESS_CLAHE_CLIP_LIMIT", 2.0)
            if clahe_clip_limit is None
            else clahe_clip_limit
        )
        self.clahe_grid_size = max(
            2,
            int(
                getattr(config, "PREPROCESS_CLAHE_GRID_SIZE", 8)
                if clahe_grid_size is None
                else clahe_grid_size
            ),
        )
        self.gamma = float(
            getattr(config, "PREPROCESS_GAMMA", 1.0)
            if gamma is None
            else gamma
        )
        raw_kernel = int(
            getattr(config, "PREPROCESS_DENOISE_KERNEL", 0)
            if denoise_kernel is None
            else denoise_kernel
        )
        if raw_kernel > 1 and raw_kernel % 2 == 0:
            raw_kernel += 1
        self.denoise_kernel = raw_kernel if raw_kernel >= 3 else 0

        self.auto_wb = (
            bool(getattr(config, "PREPROCESS_AUTO_WB", False))
            if auto_wb is None
            else bool(auto_wb)
        )
        self.sharpen = (
            bool(getattr(config, "PREPROCESS_SHARPEN", False))
            if sharpen is None
            else bool(sharpen)
        )
        self.roi_spec = (
            getattr(config, "PREPROCESS_ROI", "")
            if roi_spec is None
            else roi_spec
        )

        # Khởi tạo sẵn đối tượng CLAHE và bảng LUT Gamma (O(1) khi chạy thực tế)
        self._clahe = (
            cv2.createCLAHE(
                clipLimit=self.clahe_clip_limit,
                tileGridSize=(self.clahe_grid_size, self.clahe_grid_size),
            )
            if self.enable_clahe
            else None
        )
        self._gamma_lut = self._build_gamma_lut(self.gamma)
        self._sharpen_kernel = np.array(
            [[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32
        )

        # Bộ đệm Letterbox cấp phát sẵn để tái sử dụng qua từng frame
        self._letterbox_buffer = np.full(
            (self.input_h, self.input_w, 3), self.pad_value, dtype=np.uint8
        )
        self._last_geometry = None

    @staticmethod
    def _build_gamma_lut(gamma: float):
        if gamma <= 0.0 or abs(gamma - 1.0) < 1e-3:
            return None
        inv_gamma = 1.0 / float(gamma)
        table = np.array(
            [((i / 255.0) ** inv_gamma) * 255.0 for i in range(256)],
            dtype=np.uint8,
        )
        return table

    @property
    def has_enhancements(self) -> bool:
        return bool(
            self.denoise_kernel >= 3
            or self.auto_wb
            or self._gamma_lut is not None
            or self.enable_clahe
            or self.sharpen
        )

    @staticmethod
    def validate_frame(frame: np.ndarray) -> np.ndarray:
        """Đảm bảo frame là mảng numpy 3 kênh BGR kiểu uint8."""
        if frame is None:
            raise ValueError("Frame đầu vào là None.")
        if not isinstance(frame, np.ndarray):
            frame = np.asarray(frame)
        if frame.size == 0:
            raise ValueError("Frame đầu vào rỗng.")

        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)

        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.ndim == 3:
            channels = frame.shape[2]
            if channels == 1:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            elif channels == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            elif channels != 3:
                raise ValueError(f"Số kênh màu không hỗ trợ: {channels}")
        else:
            raise ValueError(f"Số chiều mảng frame không hợp lệ: ndim={frame.ndim}")

        return frame

    @staticmethod
    def apply_auto_white_balance(frame: np.ndarray) -> np.ndarray:
        """Cân bằng trắng tự động theo thuật toán Gray-World."""
        b, g, r = cv2.split(frame)
        b_avg = float(np.mean(b))
        g_avg = float(np.mean(g))
        r_avg = float(np.mean(r))
        if b_avg < 1e-3 or g_avg < 1e-3 or r_avg < 1e-3:
            return frame
        gray_avg = (b_avg + g_avg + r_avg) / 3.0
        b_scale = min(2.5, max(0.4, gray_avg / b_avg))
        g_scale = min(2.5, max(0.4, gray_avg / g_avg))
        r_scale = min(2.5, max(0.4, gray_avg / r_avg))
        b_lut = np.clip(np.arange(256, dtype=np.float32) * b_scale, 0, 255).astype(np.uint8)
        g_lut = np.clip(np.arange(256, dtype=np.float32) * g_scale, 0, 255).astype(np.uint8)
        r_lut = np.clip(np.arange(256, dtype=np.float32) * r_scale, 0, 255).astype(np.uint8)
        return cv2.merge((cv2.LUT(b, b_lut), cv2.LUT(g, g_lut), cv2.LUT(r, r_lut)))

    def enhance(self, frame: np.ndarray) -> np.ndarray:
        """
        Thực hiện chuỗi lọc tăng cường chất lượng ảnh (nếu được bật trong cấu hình).
        Khi các cờ đều tắt (mặc định), trả về nguyên bản trong thời gian O(1).
        """
        if not self.has_enhancements:
            return frame

        out = frame
        if self.denoise_kernel >= 3:
            out = cv2.GaussianBlur(out, (self.denoise_kernel, self.denoise_kernel), 0)

        if self.auto_wb:
            out = self.apply_auto_white_balance(out)

        if self._gamma_lut is not None:
            out = cv2.LUT(out, self._gamma_lut)

        if self.enable_clahe:
            if self._clahe is None:
                self._clahe = cv2.createCLAHE(
                    clipLimit=self.clahe_clip_limit,
                    tileGridSize=(self.clahe_grid_size, self.clahe_grid_size),
                )
            lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
            l_chan, a_chan, b_chan = cv2.split(lab)
            l_enhanced = self._clahe.apply(l_chan)
            out = cv2.cvtColor(
                cv2.merge((l_enhanced, a_chan, b_chan)), cv2.COLOR_LAB2BGR
            )

        if self.sharpen:
            out = cv2.filter2D(out, -1, self._sharpen_kernel)

        return out

    def letterbox(self, frame: np.ndarray):
        """
        Co giãn khung hình giữ nguyên tỷ lệ (letterbox) về (input_w, input_h).
        Tái sử dụng buffer đệm để giảm cấp phát vùng nhớ mới trên mỗi khung hình.
        Trả về: (model_frame, scale, pad_x, pad_y)
        """
        orig_h, orig_w = frame.shape[:2]
        scale = min(self.input_w / orig_w, self.input_h / orig_h)
        resized_w = max(1, int(round(orig_w * scale)))
        resized_h = max(1, int(round(orig_h * scale)))

        if resized_w == orig_w and resized_h == orig_h:
            resized = frame
        else:
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            resized = cv2.resize(frame, (resized_w, resized_h), interpolation=interp)

        pad_x = (self.input_w - resized_w) // 2
        pad_y = (self.input_h - resized_h) // 2

        # Nếu ảnh đã vừa khít kích thước đích, không cần chép qua buffer đệm
        if resized_w == self.input_w and resized_h == self.input_h:
            return resized, scale, 0, 0

        geometry = (resized_w, resized_h, pad_x, pad_y)
        if geometry != self._last_geometry:
            self._letterbox_buffer.fill(self.pad_value)
            self._last_geometry = geometry

        self._letterbox_buffer[
            pad_y : pad_y + resized_h, pad_x : pad_x + resized_w
        ] = resized
        return self._letterbox_buffer, scale, pad_x, pad_y

    def preprocess(self, frame: np.ndarray):
        """
        Thực thi toàn bộ pipeline tiền xử lý:
        Validate -> (Cắt ROI nếu có) -> Resize Letterbox -> Enhance -> Tạo Blob NCHW float32.
        """
        valid_frame = self.validate_frame(frame)
        orig_h, orig_w = valid_frame.shape[:2]

        roi_box = parse_roi(self.roi_spec, orig_w, orig_h)
        if roi_box is not None:
            rx1, ry1, rx2, ry2 = roi_box
            working_frame = valid_frame[ry1:ry2, rx1:rx2]
            work_h, work_w = working_frame.shape[:2]
        else:
            working_frame = valid_frame
            work_h, work_w = orig_h, orig_w

        # Chạy tăng cường ảnh sau hoặc trước resize:
        # Chạy enhance trên kích thước nhỏ (sau khi resize) nhanh hơn gấp 4 lần trên Pi 4!
        scale = min(self.input_w / work_w, self.input_h / work_h)
        resized_w = max(1, int(round(work_w * scale)))
        resized_h = max(1, int(round(work_h * scale)))

        if resized_w == work_w and resized_h == work_h:
            resized = working_frame
        else:
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            resized = cv2.resize(working_frame, (resized_w, resized_h), interpolation=interp)

        if self.has_enhancements:
            resized = self.enhance(resized)

        pad_x = (self.input_w - resized_w) // 2
        pad_y = (self.input_h - resized_h) // 2

        if resized_w == self.input_w and resized_h == self.input_h:
            model_frame = resized
        else:
            geometry = (resized_w, resized_h, pad_x, pad_y)
            if geometry != self._last_geometry:
                self._letterbox_buffer.fill(self.pad_value)
                self._last_geometry = geometry
            self._letterbox_buffer[
                pad_y : pad_y + resized_h, pad_x : pad_x + resized_w
            ] = resized
            model_frame = self._letterbox_buffer

        blob = cv2.dnn.blobFromImage(
            model_frame,
            scalefactor=1.0 / 255.0,
            size=(self.input_w, self.input_h),
            swapRB=True,
            crop=False,
        )

        if roi_box is not None:
            rx1, ry1, _, _ = roi_box
            # Dịch bù pad_x, pad_y để postprocess tự động ánh xạ đúng về tọa độ frame gốc
            effective_pad_x = pad_x - rx1 * scale
            effective_pad_y = pad_y - ry1 * scale
            return blob, (orig_h, orig_w, scale, effective_pad_x, effective_pad_y)

        return blob, (orig_h, orig_w, scale, pad_x, pad_y)
