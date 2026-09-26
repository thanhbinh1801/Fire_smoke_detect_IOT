# detector.py
"""
Module nhận diện khói & lửa sử dụng YOLOv8
"""

import os
from ultralytics import YOLO
import config

class FireSmokeDetector:
    def __init__(self, model_path=None):
        self.model_path = model_path or config.MODEL_PATH
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Không tìm thấy file trọng số model tại: {self.model_path}\n"
                f"Hãy đảm bảo file đã được tải về thư mục models/."
            )

        print(f"[Detector] Dang nap model YOLOv8: {self.model_path} ...")
        self.model = YOLO(self.model_path)
        print(f"[Detector] Da nap xong model. Danh sach nhan: {self.model.names}")

    def detect(self, frame):
        """
        Chạy nhận diện trên 1 frame ảnh (BGR).
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
        # verbose=False để tránh in spam log ra console mỗi frame
        results = self.model.predict(
            source=frame,
            conf=config.CONFIDENCE_THRESHOLD,
            imgsz=(config.FRAME_HEIGHT, config.FRAME_WIDTH),
            verbose=False
        )[0]

        detections = []
        for box in results.boxes:
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            label = self.model.names.get(cls_id, f"class_{cls_id}")
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            detections.append({
                "label": label,
                "conf": conf,
                "box": (x1, y1, x2, y2)
            })

        return detections
