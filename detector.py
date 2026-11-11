"""
Module nhận diện lửa và khói sử dụng ONNX Runtime (YOLOv8n 320x320, letterbox + blobFromImage).
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
        opts.intra_op_num_threads = max(
            1, int(getattr(config, "ORT_INTRA_OP_THREADS", 3))
        )
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
        self.roi_zoom_enabled = bool(getattr(config, "ROI_ZOOM_ENABLED", True))
        self.roi_candidate_threshold = float(
            getattr(config, "ROI_CANDIDATE_THRESHOLD", 0.22)
        )
        self.roi_max_box_ratio = float(getattr(config, "ROI_MAX_BOX_RATIO", 0.45))

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

    def preprocess(self, frame):
        orig_h, orig_w = frame.shape[:2]
        scale = min(self.input_w / orig_w, self.input_h / orig_h)
        resized_w = max(1, int(round(orig_w * scale)))
        resized_h = max(1, int(round(orig_h * scale)))
        pad_x = (self.input_w - resized_w) // 2
        pad_y = (self.input_h - resized_h) // 2
        if (
            resized_w == orig_w
            and resized_h == orig_h
            and orig_w == self.input_w
            and orig_h == self.input_h
        ):
            model_frame = frame
        else:
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            resized = cv2.resize(frame, (resized_w, resized_h), interpolation=interp)
            model_frame = np.full((self.input_h, self.input_w, 3), 114, dtype=np.uint8)
            model_frame[pad_y:pad_y + resized_h, pad_x:pad_x + resized_w] = resized
        blob = cv2.dnn.blobFromImage(
            model_frame,
            scalefactor=1.0 / 255.0,
            size=(self.input_w, self.input_h),
            swapRB=True,
            crop=False,
        )
        return blob, (orig_h, orig_w, scale, pad_x, pad_y)

    def infer(self, blob):
        return self.session.run([self.output_name], {self.input_name: blob})

    def postprocess(self, outputs, meta, conf_threshold=None):
        threshold = (
            self.conf_threshold if conf_threshold is None else float(conf_threshold)
        )
        orig_h, orig_w, scale, pad_x, pad_y = meta
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

        scores_matrix = preds[:, 4:]
        class_ids = np.argmax(scores_matrix, axis=1)
        confidences = np.max(scores_matrix, axis=1)

        mask = confidences >= threshold
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
                threshold,
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

    @staticmethod
    def _box_iou(box_a, box_b):
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h
        if inter_area <= 0:
            return 0.0
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter_area / float(area_a + area_b - inter_area)

    def _detect_roi_zoom(self, frame, outputs, meta, primary_detections):
        orig_h, orig_w = frame.shape[:2]
        if orig_w <= self.input_w and orig_h <= self.input_h:
            return primary_detections
        if self.roi_candidate_threshold >= self.conf_threshold:
            return primary_detections

        candidates = self.postprocess(
            outputs, meta, conf_threshold=self.roi_candidate_threshold
        )
        max_w = orig_w * self.roi_max_box_ratio
        max_h = orig_h * self.roi_max_box_ratio
        weak_candidates = [
            det
            for det in candidates
            if det["conf"] < self.conf_threshold
            and (det["box"][2] - det["box"][0]) <= max_w
            and (det["box"][3] - det["box"][1]) <= max_h
        ]
        if not weak_candidates:
            return primary_detections

        best = weak_candidates[0]
        bx1, by1, bx2, by2 = best["box"]
        cx = (bx1 + bx2) // 2
        cy = (by1 + by2) // 2
        crop_w = min(orig_w, self.input_w)
        crop_h = min(orig_h, self.input_h)
        crop_x1 = max(0, min(orig_w - crop_w, cx - crop_w // 2))
        crop_y1 = max(0, min(orig_h - crop_h, cy - crop_h // 2))
        roi_frame = frame[crop_y1:crop_y1 + crop_h, crop_x1:crop_x1 + crop_w]

        roi_blob, roi_meta = self.preprocess(roi_frame)
        roi_outputs = self.infer(roi_blob)
        roi_detections = self.postprocess(roi_outputs, roi_meta)
        if not roi_detections:
            return primary_detections

        merged = list(primary_detections)
        for det in roi_detections:
            rx1, ry1, rx2, ry2 = det["box"]
            mapped_box = (
                max(0, min(orig_w - 1, rx1 + crop_x1)),
                max(0, min(orig_h - 1, ry1 + crop_y1)),
                max(0, min(orig_w - 1, rx2 + crop_x1)),
                max(0, min(orig_h - 1, ry2 + crop_y1)),
            )
            mapped_det = {
                "label": det["label"],
                "conf": det["conf"],
                "box": mapped_box,
            }
            replaced = False
            for idx, existing in enumerate(merged):
                if (
                    existing["label"] == mapped_det["label"]
                    and self._box_iou(existing["box"], mapped_box) >= self.iou_threshold
                ):
                    if mapped_det["conf"] > existing["conf"]:
                        merged[idx] = mapped_det
                    replaced = True
                    break
            if not replaced:
                merged.append(mapped_det)

        return sorted(merged, key=lambda item: item["conf"], reverse=True)

    def detect(self, frame):
        blob, meta = self.preprocess(frame)
        outputs = self.infer(blob)
        detections = self.postprocess(outputs, meta)
        has_confident_fire = any(det.get("label") == "fire" for det in detections)
        if self.roi_zoom_enabled and not has_confident_fire:
            detections = self._detect_roi_zoom(frame, outputs, meta, detections)
        return detections


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
