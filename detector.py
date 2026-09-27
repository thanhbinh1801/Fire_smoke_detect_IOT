# detector.py
"""
Module nhận diện khói & lửa sử dụng ONNX Runtime.
Tối ưu hóa tài nguyên cho Raspberry Pi 4:
- Không cần cài đặt PyTorch hay Ultralytics (tiết kiệm hàng GB RAM/thẻ nhớ).
- Chạy inference trực tiếp qua onnxruntime (CPU tối ưu).
- Post-processing vectorized kết hợp OpenCV NMS siêu nhanh (~2ms).
"""

import ast
import os
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
        # Khởi tạo ONNX Runtime Session với CPUExecutionProvider
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 4  # Tận dụng 4 cores của Pi 4
        self.session = ort.InferenceSession(
            self.model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"]
        )

        # Lấy thông tin Input/Output
        self.input_info = self.session.get_inputs()[0]
        self.input_name = self.input_info.name
        self.output_name = self.session.get_outputs()[0].name

        # Shape input: [1, 3, height, width]
        self.input_shape = self.input_info.shape
        self.input_h = self.input_shape[2] if len(self.input_shape) >= 4 else 480
        self.input_w = self.input_shape[3] if len(self.input_shape) >= 4 else 640

        # Lấy tên các nhãn từ metadata của file ONNX (nếu có) hoặc dùng nhãn mặc định
        self.names = self._load_class_names()
        self.conf_threshold = getattr(config, "CONFIDENCE_THRESHOLD", 0.5)
        self.iou_threshold = getattr(config, "IOU_THRESHOLD", 0.45)

        print(f"[Detector] Nap thanh cong ONNX model. Kich thuoc input: ({self.input_w}x{self.input_h})")
        print(f"[Detector] Danh sach nhan: {self.names}")

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

    def detect(self, frame):
        """
        Chạy nhận diện trên 1 frame ảnh (BGR từ OpenCV).
        Trả về list các dict:
        [
            {
                "label": "fire" | "smoke",
                "conf": float (0.0 -> 1.0),
                "box": (x1, y1, x2, y2)
            },
            ...
        ]
        """
        orig_h, orig_w = frame.shape[:2]

        # 1. Preprocess
        # Resize về kích thước input của model nếu khác kích thước
        if orig_h != self.input_h or orig_w != self.input_w:
            resized_img = cv2.resize(frame, (self.input_w, self.input_h))
        else:
            resized_img = frame

        # Chuyển BGR -> RGB, chuyển chiều (H, W, C) -> (C, H, W), chuẩn hóa về [0.0, 1.0]
        rgb = cv2.cvtColor(resized_img, cv2.COLOR_BGR2RGB)
        tensor = rgb.transpose((2, 0, 1)).astype(np.float32) / 255.0
        blob = np.expand_dims(tensor, axis=0)

        # 2. Inference với ONNX Runtime
        outputs = self.session.run([self.output_name], {self.input_name: blob})
        # YOLOv8 output tensor: [1, 4 + num_classes, num_anchors] -> ví dụ: [1, 6, 6300]
        preds = outputs[0][0]  # shape: (6, 6300)
        preds = np.transpose(preds)  # shape: (6300, 6)

        # 3. Post-process (Vectorized nhanh gấp hàng chục lần vòng lặp python)
        scores_matrix = preds[:, 4:]  # (6300, num_classes)
        class_ids = np.argmax(scores_matrix, axis=1)
        confidences = np.max(scores_matrix, axis=1)

        # Lọc theo ngưỡng tin cậy
        mask = confidences >= self.conf_threshold
        if not np.any(mask):
            return []

        filtered_preds = preds[mask]
        filtered_conf = confidences[mask]
        filtered_cls = class_ids[mask]

        # Tọa độ bounding box (cx, cy, w, h) trên không gian model input
        cx = filtered_preds[:, 0]
        cy = filtered_preds[:, 1]
        w = filtered_preds[:, 2]
        h = filtered_preds[:, 3]

        scale_x = orig_w / float(self.input_w)
        scale_y = orig_h / float(self.input_h)

        # Chuyển từ (cx, cy, w, h) sang (x, y, w, h) trên không gian frame gốc
        x1 = ((cx - w / 2.0) * scale_x)
        y1 = ((cy - h / 2.0) * scale_y)
        w_scaled = (w * scale_x)
        h_scaled = (h * scale_y)

        # OpenCV NMSBoxes yêu cầu định dạng [x, y, width, height]
        boxes_for_nms = np.column_stack([x1, y1, w_scaled, h_scaled]).astype(int).tolist()
        conf_list = filtered_conf.astype(float).tolist()
        cls_list = filtered_cls.astype(int).tolist()

        # Áp dụng NMS (Non-Maximum Suppression) bằng OpenCV C++ core
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

                # Clip bounding box không vượt ra ngoài khung hình
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
