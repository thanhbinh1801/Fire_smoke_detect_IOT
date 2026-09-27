# detector.py
"""
Module nhận diện khói & lửa sử dụng ONNX Runtime.
Tối ưu hóa tài nguyên cho Raspberry Pi 4:
- Không cần cài đặt PyTorch hay Ultralytics.
- Chạy inference trực tiếp qua onnxruntime (CPU tối ưu).
- Post-processing vectorized kết hợp OpenCV NMS siêu nhanh (~2ms).
- Tự động thích ứng không gian màu (Auto Color Adaptation).
"""

import ast
import os
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
        opts.intra_op_num_threads = 4  # Tận dụng 4 cores của Pi 4
        self.session = ort.InferenceSession(
            self.model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"]
        )

        self.input_info = self.session.get_inputs()[0]
        self.input_name = self.input_info.name
        self.output_name = self.session.get_outputs()[0].name

        self.input_shape = self.input_info.shape
        self.input_h = self.input_shape[2] if len(self.input_shape) >= 4 else 480
        self.input_w = self.input_shape[3] if len(self.input_shape) >= 4 else 640

        self.names = self._load_class_names()
        self.conf_threshold = getattr(config, "CONFIDENCE_THRESHOLD", 0.3)
        self.iou_threshold = getattr(config, "IOU_THRESHOLD", 0.45)
        self._last_debug_time = 0.0

        print(f"[Detector] Nap thanh cong ONNX model. Kich thuoc input: ({self.input_w}x{self.input_h})")
        print(f"[Detector] Danh sach nhan: {self.names} | Nguong confidence: {self.conf_threshold}")

    def _load_class_names(self):
        """Đọc danh sách nhãn lớp từ metadata của file ONNX nếu có"""
        default_names = {0: "fire", 1: "smoke"}
        try:
            meta = self.session.get_modelmeta().custom_metadata_map
            if "names" in meta:
                parsed = ast.literal_eval(meta["names"])
                return {int(k): v for k, v in parsed.items()}
        except Exception:
            pass
        return default_names

    def _forward(self, img_bgr_or_rgb):
        """Chạy 1 lần inference qua ONNX Runtime"""
        tensor = img_bgr_or_rgb.transpose((2, 0, 1)).astype(np.float32) / 255.0
        blob = np.expand_dims(tensor, axis=0)
        outputs = self.session.run([self.output_name], {self.input_name: blob})
        preds = outputs[0][0]  # shape: (6, 6300)
        return np.transpose(preds)  # shape: (6300, 6)

    def detect(self, frame):
        """
        Chạy nhận diện trên 1 frame ảnh.
        Trả về list các dict:
        [
            {"label": "fire"|"smoke", "conf": float, "box": (x1, y1, x2, y2)},
            ...
        ]
        """
        orig_h, orig_w = frame.shape[:2]

        # 1. Resize về kích thước input
        if orig_h != self.input_h or orig_w != self.input_w:
            resized = cv2.resize(frame, (self.input_w, self.input_h))
        else:
            resized = frame

        # Thử nghiệm với kênh màu RGB chuẩn
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        preds = self._forward(rgb)

        scores_matrix = preds[:, 4:]
        confidences = np.max(scores_matrix, axis=1)
        max_score = float(np.max(confidences))

        # Nếu độ tin cậy < 0.2, thử chạy trên ảnh gốc resized (phòng trường hợp frame vốn đã là RGB)
        if max_score < 0.2:
            preds_alt = self._forward(resized)
            scores_alt = preds_alt[:, 4:]
            conf_alt = np.max(scores_alt, axis=1)
            max_score_alt = float(np.max(conf_alt))
            if max_score_alt > max_score:
                preds = preds_alt
                confidences = conf_alt
                max_score = max_score_alt

        # Debug log định kỳ nếu phát hiện có tín hiệu lửa/khói nhưng điểm chưa vượt ngưỡng
        now = time.time()
        if (0.15 <= max_score < self.conf_threshold) and (now - self._last_debug_time > 1.2):
            self._last_debug_time = now
            cls_id = int(np.argmax(preds[:, 4:], axis=1)[np.argmax(confidences)])
            label = self.names.get(cls_id, f"class_{cls_id}")
            print(f"[AI Debug] Tin hieu {label} tiem nang: Conf = {max_score:.2f} (Nguong: {self.conf_threshold}). Hay lay net ro hon hoac giu khoang cach 40-50cm.")

        # Lọc theo ngưỡng tin cậy
        mask = confidences >= self.conf_threshold
        if not np.any(mask):
            return []

        filtered_preds = preds[mask]
        filtered_conf = confidences[mask]
        filtered_cls = np.argmax(filtered_preds[:, 4:], axis=1)

        cx = filtered_preds[:, 0]
        cy = filtered_preds[:, 1]
        w = filtered_preds[:, 2]
        h = filtered_preds[:, 3]

        scale_x = orig_w / float(self.input_w)
        scale_y = orig_h / float(self.input_h)

        x1 = ((cx - w / 2.0) * scale_x)
        y1 = ((cy - h / 2.0) * scale_y)
        w_scaled = (w * scale_x)
        h_scaled = (h * scale_y)

        boxes_for_nms = np.column_stack([x1, y1, w_scaled, h_scaled]).astype(int).tolist()
        conf_list = filtered_conf.astype(float).tolist()
        cls_list = filtered_cls.astype(int).tolist()

        indices = cv2.dnn.NMSBoxes(
            boxes_for_nms,
            conf_list,
            self.conf_threshold,
            self.iou_threshold
        )

        detections = []
        if len(indices) > 0:
            for idx in np.array(indices).flatten():
                bx, by, bw, bh = boxes_for_nms[idx]
                cls_id = cls_list[idx]
                label = self.names.get(cls_id, f"class_{cls_id}")
                conf = conf_list[idx]

                xmin = max(0, min(orig_w - 1, bx))
                ymin = max(0, min(orig_h - 1, by))
                xmax = max(0, min(orig_w - 1, bx + bw))
                ymax = max(0, min(orig_h - 1, by + bh))

                detections.append({
                    "label": label,
                    "conf": float(conf),
                    "box": (int(xmin), int(ymin), int(xmax), int(ymax))
                })

        return detections
