# detector.py
"""
Module nhận diện lửa và khói sử dụng ONNX Runtime (YOLOv8n 320x320, letterbox + blobFromImage).
Tích hợp pipeline tiền xử lý (FramePreprocessor), suy luận 2 giai đoạn ROI Zoom
và luồng suy luận bất đồng bộ độ trễ thấp (AsyncFireDetector).
"""

import ast
import os
import threading
import time

import cv2
import numpy as np
import onnxruntime as ort

import config
from preprocessing import FramePreprocessor


class FireSmokeDetector:
    def __init__(self, model_path=None, preprocessor=None):
        self.model_path = model_path or config.MODEL_PATH
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Không tìm thấy file model ONNX tại: {self.model_path}\n"
                f"Hãy đảm bảo file .onnx đã có trong thư mục models/."
            )

        print(f"[Detector] Dang nap model ONNX: {self.model_path} ...")
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        intra_threads = max(
            1,
            int(
                getattr(
                    config,
                    "ORT_INTRA_OP_THREADS",
                    getattr(config, "ORT_INTRA_THREADS", 3),
                )
            ),
        )
        opts.intra_op_num_threads = intra_threads
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            self.model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
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
        self.conf_threshold = float(getattr(config, "CONFIDENCE_THRESHOLD", 0.40))
        self.fire_conf_threshold = float(
            getattr(config, "FIRE_CONFIDENCE_THRESHOLD", self.conf_threshold)
        )
        self.smoke_conf_threshold = float(
            getattr(config, "SMOKE_CONFIDENCE_THRESHOLD", self.conf_threshold)
        )
        self.iou_threshold = float(getattr(config, "IOU_THRESHOLD", 0.45))
        self.min_box_area = max(0, int(getattr(config, "MIN_BOX_AREA", 36)))
        self.roi_zoom_enabled = bool(getattr(config, "ROI_ZOOM_ENABLED", True))
        self.roi_candidate_threshold = float(
            getattr(config, "ROI_CANDIDATE_THRESHOLD", 0.22)
        )
        self.roi_max_box_ratio = float(getattr(config, "ROI_MAX_BOX_RATIO", 0.45))

        self.preprocessor = preprocessor or FramePreprocessor(
            input_w=self.input_w,
            input_h=self.input_h,
        )

        print(
            f"[Detector] Nap thanh cong ONNX model. Kich thuoc input: ({self.input_w}x{self.input_h}) "
            f"| Threads: {intra_threads}"
        )
        print(
            f"[Detector] Nhan ho tro: {self.names} | "
            f"Nguong conf (chung/lua/khoi): {self.conf_threshold:.2f}/{self.fire_conf_threshold:.2f}/{self.smoke_conf_threshold:.2f}"
        )

    def _load_class_names(self):
        """Đọc danh sách nhãn lớp từ metadata của file ONNX nếu có."""
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
            print(
                f"[Detector] Metadata names không hợp lệ ({error}); dùng nhãn mặc định fire/smoke."
            )
            return default_names

    def preprocess(self, frame):
        """Tiền xử lý khung hình qua FramePreprocessor (Letterbox + Enhance + NCHW Blob)."""
        return self.preprocessor.preprocess(frame)

    def infer(self, blob):
        return self.session.run([self.output_name], {self.input_name: blob})

    def _get_class_threshold(self, is_fire: bool, is_smoke: bool, override_threshold=None) -> float:
        if override_threshold is not None:
            return float(override_threshold)
        base = float(self.conf_threshold)
        if is_fire:
            return float(getattr(self, "fire_conf_threshold", base))
        if is_smoke:
            return float(getattr(self, "smoke_conf_threshold", base))
        return base

    def postprocess(self, outputs, meta, conf_threshold=None):
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

        if conf_threshold is not None:
            min_threshold = float(conf_threshold)
        else:
            min_threshold = min(
                float(self.conf_threshold),
                float(getattr(self, "fire_conf_threshold", self.conf_threshold)),
                float(getattr(self, "smoke_conf_threshold", self.conf_threshold)),
            )

        mask = confidences >= min_threshold
        if not np.any(mask):
            return []

        filtered_preds = preds[mask]
        filtered_conf = confidences[mask]
        filtered_cls = class_ids[mask]

        cx = filtered_preds[:, 0]
        cy = filtered_preds[:, 1]
        w = filtered_preds[:, 2]
        h = filtered_preds[:, 3]

        x1 = (cx - w / 2.0 - pad_x) / scale
        y1 = (cy - h / 2.0 - pad_y) / scale
        w_scaled = w / scale
        h_scaled = h / scale

        boxes_for_nms = np.column_stack([x1, y1, w_scaled, h_scaled]).astype(int).tolist()
        conf_list = filtered_conf.astype(float).tolist()
        cls_list = filtered_cls.astype(int).tolist()
        detections = []

        for cls_id in set(cls_list):
            label = self.names.get(cls_id, f"class_{cls_id}")
            normalized_label = str(label).strip().lower()
            is_fire = "fire" in normalized_label or "flame" in normalized_label
            is_smoke = "smoke" in normalized_label
            if not is_fire and not is_smoke:
                continue

            cls_threshold = self._get_class_threshold(
                is_fire, is_smoke, override_threshold=conf_threshold
            )
            class_indices = [
                i
                for i, value in enumerate(cls_list)
                if value == cls_id and conf_list[i] >= cls_threshold
            ]
            if not class_indices:
                continue

            indices = cv2.dnn.NMSBoxes(
                [boxes_for_nms[i] for i in class_indices],
                [conf_list[i] for i in class_indices],
                cls_threshold,
                self.iou_threshold,
            )
            for class_index in np.asarray(indices).flatten():
                idx = class_indices[int(class_index)]
                conf = conf_list[idx]
                bx, by, bw, bh = boxes_for_nms[idx]
                xmin = max(0, min(orig_w - 1, bx))
                ymin = max(0, min(orig_h - 1, by))
                xmax = max(0, min(orig_w - 1, bx + bw))
                ymax = max(0, min(orig_h - 1, by + bh))

                box_w = xmax - xmin
                box_h = ymax - ymin
                if box_w <= 0 or box_h <= 0:
                    continue
                if (
                    conf_threshold is None
                    and self.min_box_area > 0
                    and (box_w * box_h) < self.min_box_area
                ):
                    continue

                detections.append(
                    {
                        "label": "fire" if is_fire else "smoke",
                        "conf": float(conf),
                        "box": (int(xmin), int(ymin), int(xmax), int(ymax)),
                    }
                )

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
        roi_frame = frame[crop_y1 : crop_y1 + crop_h, crop_x1 : crop_x1 + crop_w]

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
    Bộ chạy nhận diện bất đồng bộ (Asynchronous Worker) tối ưu độ trễ thấp:
    - Cơ chế Latest-Frame-Only (Drop-Oldest): luôn lấy đúng frame mới nhất từ camera,
      không tạo hàng đợi gây trễ hình (zero queue backlog).
    - Chống suy luận trùng lặp trên cùng một frame_timestamp.
    - Hỗ trợ callback `on_result` giúp kích hoạt luồng xác nhận & cảnh báo ngay tức khắc.
    """

    def __init__(self, detector, on_result=None):
        self.detector = detector
        self.on_result = on_result
        self.latest_frame = None
        self.latest_frame_timestamp = 0.0
        self._processed_frame_timestamp = -1.0
        self.latest_detections = []
        self.lock = threading.Lock()
        self._result_cond = threading.Condition(self.lock)
        self.running = True
        self.has_new_frame = threading.Event()
        self.ai_fps = 0.0
        self.last_inference_ms = 0.0
        self.last_update_time = 0.0
        self.last_error = None

        self.thread = threading.Thread(
            target=self._worker, daemon=True, name="AsyncAIWorker"
        )
        self.thread.start()
        self.last_update_time = time.time()
        print("[AsyncDetector] Da khoi chay luong AI suy luan ngam (Async Thread).")

    def update_frame(self, frame, frame_timestamp: float = None):
        """Cung cấp khung hình mới nhất từ camera cho AI suy luận (Zero-Copy, O(1))."""
        if frame is None:
            return
        with self.lock:
            if (
                frame_timestamp is not None
                and frame_timestamp == self.latest_frame_timestamp
            ):
                return
            self.latest_frame = frame
            self.latest_frame_timestamp = (
                float(frame_timestamp)
                if frame_timestamp is not None
                else time.monotonic()
            )
        self.has_new_frame.set()

    def _worker(self):
        count = 0
        t0 = time.monotonic()
        while self.running:
            if not self.has_new_frame.wait(timeout=0.05):
                continue
            self.has_new_frame.clear()

            with self.lock:
                frame_to_process = self.latest_frame
                frame_ts = self.latest_frame_timestamp
                if (
                    frame_to_process is None
                    or frame_ts == self._processed_frame_timestamp
                ):
                    continue
                self._processed_frame_timestamp = frame_ts

            try:
                infer_start = time.perf_counter()
                dets = self.detector.detect(frame_to_process)
                infer_ms = (time.perf_counter() - infer_start) * 1000.0
                result_wall_time = time.time()

                count += 1
                now_mono = time.monotonic()
                elapsed = now_mono - t0
                if elapsed >= 1.0:
                    current_ai_fps = count / elapsed
                    count = 0
                    t0 = now_mono
                else:
                    current_ai_fps = (
                        self.ai_fps if self.ai_fps > 0 else (1000.0 / max(1.0, infer_ms))
                    )

                with self._result_cond:
                    self.latest_detections = dets
                    self.result_frame_timestamp = frame_ts
                    self.last_inference_ms = infer_ms
                    self.ai_fps = current_ai_fps
                    self.last_update_time = result_wall_time
                    self.last_error = None
                    self._result_cond.notify_all()

                if self.on_result is not None:
                    try:
                        self.on_result(
                            dets,
                            frame_to_process,
                            current_ai_fps,
                            result_wall_time,
                            infer_ms,
                        )
                    except Exception as cb_err:
                        print(f"[AsyncDetector] Loi trong callback on_result: {cb_err}")

            except Exception as e:
                with self._result_cond:
                    self.last_error = str(e)
                    self._result_cond.notify_all()
                print(f"[AsyncDetector] Loi suy luan AI: {e}")

    def get_detections(self):
        """Lấy kết quả nhận diện mới nhất (không chặn, O(1)) kèm AI FPS."""
        with self.lock:
            return list(self.latest_detections), self.ai_fps

    def get_result(self, include_frame_time=False):
        """Lấy kết quả, FPS, thời điểm suy luận gần nhất và lỗi nếu có."""
        with self.lock:
            result = (
                list(self.latest_detections),
                self.ai_fps,
                self.last_update_time,
                self.last_error,
            )
            if include_frame_time:
                return result + (getattr(self, "result_frame_timestamp", 0.0),)
            return result

    def stop(self):
        """Dừng luồng AI an toàn."""
        self.running = False
        self.has_new_frame.set()
        with self._result_cond:
            self._result_cond.notify_all()
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=1.0)
