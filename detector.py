# detector.py
"""
Module nhận diện ngọn lửa sử dụng ONNX Runtime.
Tối ưu hóa:
- Zero-copy color pipeline: Nhận diện trực tiếp mảng RGB từ Picamera2 (không đảo ngược màu).
- Model 480x640 chuẩn tỷ lệ: Giữ nguyên vẹn hình thái ngọn lửa, độ chính xác cao nhất.
- Vectorized post-processing siêu nhanh.
"""

import ast
import os
import threading
import time
import cv2
import numpy as np
import onnxruntime as ort
import config

class FireSmokeDetector:
    def __init__(self, model_path=None):
        self.model_path = model_path or config.MODEL_PATH
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Không tìm thấy file model ONNX tại: {self.model_path}\n"
                f"Hãy đảm bảo file .onnx đã có trong thư mục models/."
            )

        print(f"[Detector] Dang nap model ONNX: {self.model_path} ...")
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 3  # Dùng 3 cores cho AI, để 1 core cho Camera, GUI và OS
        self.session = ort.InferenceSession(
            self.model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"]
        )

        self.input_info = self.session.get_inputs()[0]
        self.input_name = self.input_info.name
        self.output_name = self.session.get_outputs()[0].name

        self.input_shape = self.input_info.shape
        self.input_h = (
            self.input_shape[2]
            if len(self.input_shape) >= 4 and isinstance(self.input_shape[2], int)
            else config.FRAME_HEIGHT
        )
        self.input_w = (
            self.input_shape[3]
            if len(self.input_shape) >= 4 and isinstance(self.input_shape[3], int)
            else config.FRAME_WIDTH
        )

        self.names = self._load_class_names()
        self.conf_threshold = getattr(config, "CONFIDENCE_THRESHOLD", 0.35)
        self.iou_threshold = getattr(config, "IOU_THRESHOLD", 0.45)

        print(f"[Detector] Nap thanh cong ONNX model. Kich thuoc input: ({self.input_w}x{self.input_h})")
        print(f"[Detector] Nhan ho tro: {self.names} | Nguong confidence: {self.conf_threshold}")

    def _load_class_names(self):
        """Đọc danh sách nhãn lớp từ metadata của file ONNX nếu có"""
        default_names = {0: "fire", 1: "smoke"}
        metadata = self.session.get_modelmeta().custom_metadata_map
        if "names" not in metadata:
            print("[Detector] Model không có metadata names; dùng nhãn mặc định fire/smoke.")
            return default_names
        try:
            parsed = ast.literal_eval(metadata["names"])
            if isinstance(parsed, dict):
                names = {int(key): str(value) for key, value in parsed.items()}
            elif isinstance(parsed, (list, tuple)):
                names = {index: str(value) for index, value in enumerate(parsed)}
            else:
                raise ValueError("metadata names phải là dict hoặc list")
            if names:
                return names
            raise ValueError("metadata names rỗng")
        except (SyntaxError, TypeError, ValueError) as error:
            print(f"[Detector] Metadata names không hợp lệ ({error}); dùng nhãn mặc định fire/smoke.")
            return default_names

    def detect(self, frame):
        """
        Chạy nhận diện trên 1 frame ảnh.
        Trả về list các dict:
        [
            {"label": "fire", "conf": float, "box": (x1, y1, x2, y2)},
            ...
        ]
        """
        orig_h, orig_w = frame.shape[:2]

        # Letterbox giữ tỷ lệ ảnh, tránh kéo méo đối tượng khi model dùng input vuông.
        scale = min(self.input_w / orig_w, self.input_h / orig_h)
        resized_w = max(1, int(round(orig_w * scale)))
        resized_h = max(1, int(round(orig_h * scale)))
        resized = cv2.resize(frame, (resized_w, resized_h))
        pad_x = (self.input_w - resized_w) // 2
        pad_y = (self.input_h - resized_h) // 2
        model_frame = np.full((self.input_h, self.input_w, 3), 114, dtype=np.uint8)
        model_frame[pad_y:pad_y + resized_h, pad_x:pad_x + resized_w] = resized

        # 2. Chuẩn hóa kênh màu: Chuyển BGR sang RGB cho mạng nơ-ron YOLOv8
        rgb_tensor = cv2.cvtColor(model_frame, cv2.COLOR_BGR2RGB)

        tensor = rgb_tensor.transpose((2, 0, 1)).astype(np.float32) / 255.0
        blob = np.expand_dims(tensor, axis=0)

        # 3. Chạy Inference qua ONNX Runtime
        outputs = self.session.run([self.output_name], {self.input_name: blob})
        preds = np.asarray(outputs[0])
        if preds.ndim == 3:
            preds = preds[0]
        if preds.ndim != 2:
            raise ValueError(f"Output ONNX không hợp lệ: shape={preds.shape}")
        feature_count = 4 + len(self.names)
        if preds.shape[0] == feature_count and preds.shape[1] != feature_count:
            preds = preds.transpose()
        elif preds.shape[1] != feature_count and preds.shape[0] < preds.shape[1]:
            preds = preds.transpose()
        if preds.shape[1] < 5:
            raise ValueError(f"Output ONNX thiếu dữ liệu class/box: shape={preds.shape}")

        # 4. Trích xuất xác suất các lớp
        scores_matrix = preds[:, 4:]  # (num_anchors, num_classes)
        class_ids = np.argmax(scores_matrix, axis=1)
        confidences = np.max(scores_matrix, axis=1)

        # Lọc theo ngưỡng tin cậy
        mask = confidences >= self.conf_threshold
        if not np.any(mask):
            return []

        filtered_preds = preds[mask]
        filtered_conf = confidences[mask]
        filtered_cls = class_ids[mask]

        cx = filtered_preds[:, 0]
        cy = filtered_preds[:, 1]
        w = filtered_preds[:, 2]
        h = filtered_preds[:, 3]

        x1 = ((cx - w / 2.0 - pad_x) / scale)
        y1 = ((cy - h / 2.0 - pad_y) / scale)
        w_scaled = w / scale
        h_scaled = h / scale

        boxes_for_nms = np.column_stack([x1, y1, w_scaled, h_scaled]).astype(int).tolist()
        conf_list = filtered_conf.astype(float).tolist()
        cls_list = filtered_cls.astype(int).tolist()
        detections = []
        for cls_id in set(cls_list):
            class_indices = [i for i, value in enumerate(cls_list) if value == cls_id]
            indices = cv2.dnn.NMSBoxes(
                [boxes_for_nms[i] for i in class_indices],
                [conf_list[i] for i in class_indices],
                self.conf_threshold,
                self.iou_threshold,
            )
            for class_index in np.asarray(indices).flatten():
                idx = class_indices[int(class_index)]
                label = self.names.get(cls_id, f"class_{cls_id}")
                conf = conf_list[idx]
                normalized_label = str(label).strip().lower()
                is_fire = "fire" in normalized_label or "flame" in normalized_label
                is_smoke = "smoke" in normalized_label
                if not is_fire and not is_smoke:
                    continue
                bx, by, bw, bh = boxes_for_nms[idx]
                xmin = max(0, min(orig_w - 1, bx))
                ymin = max(0, min(orig_h - 1, by))
                xmax = max(0, min(orig_w - 1, bx + bw))
                ymax = max(0, min(orig_h - 1, by + bh))

                detections.append({
                    "label": "fire" if is_fire else "smoke",
                    "conf": float(conf),
                    "box": (int(xmin), int(ymin), int(xmax), int(ymax))
                })

        return sorted(detections, key=lambda detection: detection["conf"], reverse=True)


class AsyncFireDetector:
    """
    Bộ chạy nhận diện bất đồng bộ (Asynchronous Worker):
    - Đưa việc suy luận ONNX vào 1 luồng ngầm chuyên biệt.
    - Giúp luồng chính của Camera/Display luôn đạt 25 - 30 FPS mượt mà.
    - Không bao giờ làm đứng hình hoặc giật camera khi AI đang tính toán.
    """
    def __init__(self, detector):
        self.detector = detector
        self.latest_frame = None
        self.latest_detections = []
        self.lock = threading.Lock()
        self.running = True
        self.has_new_frame = threading.Event()
        self.ai_fps = 0.0
        self.last_update_time = 0.0
        self.last_error = None

        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        self.last_update_time = time.time()
        print("[AsyncDetector] Da khoi chay luong AI suy luan ngam (Async Thread).")

    def update_frame(self, frame):
        """Cung cấp khung hình mới nhất từ camera cho AI suy luận (không chờ)"""
        with self.lock:
            self.latest_frame = frame
        self.has_new_frame.set()

    def _worker(self):
        count = 0
        t0 = time.time()
        while self.running:
            # Chờ có frame mới cần xử lý (timeout 0.05s)
            if not self.has_new_frame.wait(timeout=0.05):
                continue
            self.has_new_frame.clear()

            with self.lock:
                frame_to_process = self.latest_frame

            if frame_to_process is None:
                continue

            try:
                # Chạy suy luận ONNX
                dets = self.detector.detect(frame_to_process)
                with self.lock:
                    self.latest_detections = dets
                    self.last_update_time = time.time()
                    self.last_error = None
            except Exception as e:
                with self.lock:
                    self.last_error = str(e)
                print(f"[AsyncDetector] Loi suy luan AI: {e}")

            count += 1
            now = time.time()
            if now - t0 >= 1.0:
                self.ai_fps = count / (now - t0)
                count = 0
                t0 = now

    def get_detections(self):
        """Lấy kết quả nhận diện mới nhất (không chặn, O(1)) kèm AI FPS"""
        with self.lock:
            return list(self.latest_detections), self.ai_fps

    def get_result(self):
        """Lấy kết quả, FPS, thời điểm suy luận gần nhất và lỗi nếu có."""
        with self.lock:
            return (
                list(self.latest_detections),
                self.ai_fps,
                self.last_update_time,
                self.last_error,
            )

    def stop(self):
        """Dừng luồng AI an toàn"""
        self.running = False
        self.has_new_frame.set()
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=1.0)
