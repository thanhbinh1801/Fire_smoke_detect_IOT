# camera.py
"""
Module thu thập hình ảnh camera.

Nguồn camera được chọn độc lập với nền tảng qua config.CAMERA_SOURCE:
- "usb": webcam USB đọc bằng OpenCV. Trên Raspberry Pi nên dùng USB 3.0 và
  định dạng MJPG để giữ 30 FPS ở 640x480.
- "csi": Picamera2 dành cho camera CSI (Arducam IMX519) trên Raspberry Pi.

Mọi frame trả về đều ở định dạng BGR để detector.py không phải đổi preprocessing.
"""

import sys
import threading
import time

import cv2

import config


class FireCamera:
    def __init__(self):
        self.platform = config.PLATFORM
        default_source = "csi" if self.platform == "pi" else "usb"
        self.source = str(getattr(config, "CAMERA_SOURCE", default_source)).strip().lower()
        self.running = True
        self.frame = None
        self.frame_updated_at = 0.0
        self.lock = threading.Lock()
        self.lens_position = getattr(config, "CAMERA_LENS_POSITION", 2.0)
        self.swap_rb = getattr(config, "CAMERA_SWAP_RB", False)

        if self.source == "csi":
            if self.platform != "pi":
                raise ValueError("CAMERA_SOURCE='csi' chỉ chạy được trên Raspberry Pi.")
            self._open_csi()
        elif self.source == "usb":
            self._open_webcam()
        else:
            raise ValueError(
                f"CAMERA_SOURCE không hợp lệ: {self.source}. Chọn 'usb' hoặc 'csi'."
            )

        self.thread = threading.Thread(target=self._capture_worker, daemon=True)
        self.thread.start()

        start_wait = time.time()
        while self.frame is None and (time.time() - start_wait < 5.0):
            time.sleep(0.05)

        if self.frame is None:
            self.close()
            raise RuntimeError(
                "Camera không trả về hình ảnh sau 5 giây. "
                "Kiểm tra kết nối camera, WEBCAM_INDEX và CAMERA_SOURCE trong config.py."
            )

    def _open_csi(self):
        try:
            from picamera2 import Picamera2
        except ImportError:
            raise ImportError(
                "Không tìm thấy thư viện picamera2! "
                "Hãy chắc chắn đã cài: sudo apt install python3-picamera2 "
                "và tạo venv với cờ --system-site-packages"
            )

        self.picam2 = Picamera2()
        target_fps = getattr(config, "CAMERA_FPS", 30)
        camera_config = self.picam2.create_video_configuration(
            main={
                "size": (config.FRAME_WIDTH, config.FRAME_HEIGHT),
                "format": "BGR888",
            },
            controls={"FrameRate": target_fps},
        )
        self.picam2.configure(camera_config)
        self.picam2.start()
        print(
            f"[Camera] CSI Picamera2 {config.FRAME_WIDTH}x{config.FRAME_HEIGHT} "
            f"@{target_fps}fps"
        )

        time.sleep(0.3)
        try:
            exp_comp = getattr(config, "CAMERA_EXPOSURE_COMP", -0.5)
            auto_focus = getattr(config, "CAMERA_AUTOFOCUS", True)
            ctrls = {"Sharpness": 1.5, "ExposureValue": float(exp_comp)}
            if auto_focus:
                ctrls["AfMode"] = 2
                print("[Camera] Bật lấy nét tự động liên tục (AfMode=2).")
            else:
                ctrls["AfMode"] = 0
                ctrls["LensPosition"] = float(self.lens_position)
                print(
                    f"[Camera] Khóa nét tại LensPosition = {self.lens_position} dioptres."
                )
            self.picam2.set_controls(ctrls)
        except Exception as error:
            print(f"[Camera] Cảnh báo cấu hình controls: {error}")

    def _open_webcam(self):
        index = int(getattr(config, "WEBCAM_INDEX", 0))
        fourcc_text = str(getattr(config, "WEBCAM_FOURCC", "MJPG")).strip().upper()

        if sys.platform.startswith("linux"):
            self.cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        else:
            self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened() and sys.platform.startswith("linux"):
            self.cap.release()
            self.cap = cv2.VideoCapture(index)

        if not self.cap.isOpened():
            raise RuntimeError(
                f"Không mở được webcam index {index}. "
                "Kiểm tra WEBCAM_INDEX và quyền truy cập /dev/video*."
            )

        if fourcc_text and len(fourcc_text) == 4:
            self.cap.set(
                cv2.CAP_PROP_FOURCC,
                cv2.VideoWriter_fourcc(*fourcc_text),
            )

        target_fps = int(getattr(config, "CAMERA_FPS", 30))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config.FRAME_WIDTH))
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config.FRAME_HEIGHT))
        self.cap.set(cv2.CAP_PROP_FPS, target_fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS) or 0.0
        print(
            f"[Camera] USB webcam index {index} ({fourcc_text or 'default'}) "
            f"{actual_w}x{actual_h} @ {actual_fps:.0f}fps"
        )

    def trigger_autofocus(self):
        """Kích hoạt chu kỳ lấy nét tự động (chỉ có tác dụng với camera CSI)."""
        if self.source != "csi":
            return "Webcam USB tự xử lý lấy nét; không có điều khiển AF từ xa."
        try:
            self.picam2.set_controls({"AfMode": 1, "AfTrigger": 0})
            time.sleep(0.05)
            self.picam2.set_controls({"AfMode": 1, "AfTrigger": 1})
            print("\n[Camera] Đã kích hoạt chu kỳ lấy nét tự động.")
            return "Đã kích hoạt lấy nét tự động."
        except Exception as error:
            print(f"[Camera] Lỗi Autofocus: {error}")
            return f"Không điều khiển được lấy nét: {error}"

    def adjust_focus(self, step):
        """Vi chỉnh tiêu cự thủ công (chỉ có tác dụng với camera CSI)."""
        if self.source != "csi":
            return "Webcam USB không hỗ trợ chỉnh tiêu cự từ xa."
        try:
            self.lens_position = max(
                0.0, min(10.0, round(self.lens_position + step, 2))
            )
            self.picam2.set_controls(
                {"AfMode": 0, "LensPosition": float(self.lens_position)}
            )
            print(f"\n[Camera] Tiêu cự hiện tại: {self.lens_position:.2f} dioptres.")
            return f"Tiêu cự: {self.lens_position:.2f} dioptres."
        except Exception as error:
            print(f"[Camera] Lỗi Focus: {error}")
            return f"Không chỉnh được tiêu cự: {error}"

    def toggle_color_swap(self):
        """Đảo kênh màu R-B trực tiếp khi đang chạy."""
        self.swap_rb = not self.swap_rb
        mode = "ĐẢO KÊNH R-B" if self.swap_rb else "MẶC ĐỊNH"
        print(f"\n[Camera] Đã chuyển chế độ màu: {mode}.")
        return self.swap_rb

    def _capture_worker(self):
        """Luồng đọc liên tục khung hình từ camera ở background."""
        while self.running:
            try:
                if self.source == "csi":
                    raw = self.picam2.capture_array()
                    base_bgr = cv2.cvtColor(raw, cv2.COLOR_RGB2BGR)
                else:
                    ok, raw = self.cap.read()
                    if not ok:
                        time.sleep(0.01)
                        continue
                    base_bgr = raw

                if self.swap_rb:
                    current_frame = cv2.cvtColor(base_bgr, cv2.COLOR_BGR2RGB)
                else:
                    current_frame = base_bgr

                with self.lock:
                    self.frame = current_frame
                    self.frame_updated_at = time.monotonic()

            except Exception:
                time.sleep(0.01)

    def get_frame(self):
        """Trả về 1 frame dạng numpy array (BGR)."""
        frame, _ = self.get_frame_with_timestamp()
        return frame

    def get_frame_with_timestamp(self):
        """Trả về bản sao frame mới nhất cùng thời điểm capture monotonic."""
        with self.lock:
            if self.frame is not None:
                return self.frame.copy(), self.frame_updated_at

        time.sleep(0.02)
        with self.lock:
            if self.frame is not None:
                return self.frame.copy(), self.frame_updated_at
            return None, 0.0

    def close(self):
        """Giải phóng camera."""
        self.running = False
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=1.0)

        if self.source == "csi":
            if hasattr(self, "picam2"):
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except Exception:
                    pass
        else:
            if hasattr(self, "cap"):
                self.cap.release()
