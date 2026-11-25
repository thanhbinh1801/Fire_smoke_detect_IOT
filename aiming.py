"""Floor calibration, inverse pointing geometry and non-blocking aim/spray cycle.

Coordinates are cm: x along the 43 cm edge, y along the 31 cm edge, z up.
Image corners are normalized, ordered (0,0), (L,0), (L,W), (0,W).
"""

import copy
import json
import math
import os
import tempfile
import time

import cv2
import numpy as np

import config
from confirmation import build_pump_confirmer


def number(value):
    if isinstance(value, bool):
        raise ValueError("Cần nhập số hữu hạn")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Cần nhập số hữu hạn") from exc
    if not math.isfinite(value):
        raise ValueError("Cần nhập số hữu hạn")
    return value


class FloorCalibration:
    def __init__(self, values=None):
        self.values = {
            "length_cm": 43.0, "width_cm": 31.0,
            "nozzle_x_cm": config.NOZZLE_X_CM, "nozzle_y_cm": config.NOZZLE_Y_CM,
            "nozzle_height_cm": config.NOZZLE_HEIGHT_CM,
            "camera_x_cm": config.NOZZLE_X_CM + config.NOZZLE_CAMERA_OFFSET_X_CM,
            "camera_y_cm": config.NOZZLE_Y_CM + config.NOZZLE_CAMERA_OFFSET_Y_CM,
            "camera_height_cm": config.NOZZLE_CAMERA_HEIGHT_CM,
            "target_height_cm": config.NOZZLE_TARGET_HEIGHT_CM,
            "corners": [], "image_aspect": 4 / 3,
            "mechanism": "yaw_pitch", "pan_sign": 1, "tilt_sign": 1,
            "rotation_deg": 0.0, "anchor_y": 0.5, "water_samples": [],
        }
        if values is not None:
            if not isinstance(values, dict) or set(values) - set(self.values):
                raise ValueError("Trường hiệu chuẩn không hợp lệ")
            self.values.update(copy.deepcopy(values))
        v = self.values
        for key in set(v) - {"corners", "mechanism", "water_samples"}:
            v[key] = number(v[key])
        if not all(0 < v[key] <= 1000 for key in ("length_cm", "width_cm", "nozzle_height_cm", "camera_height_cm")):
            raise ValueError("Kích thước/chiều cao phải dương, tối đa 1000 cm")
        if not 0 <= v["target_height_cm"] < min(v["nozzle_height_cm"], v["camera_height_cm"]):
            raise ValueError("Mục tiêu phải thấp hơn camera và đầu vòi")
        if v["mechanism"] not in ("yaw_pitch", "tilt_xy"):
            raise ValueError("Chọn yaw_pitch hoặc tilt_xy")
        if v["pan_sign"] not in (-1, 1) or v["tilt_sign"] not in (-1, 1):
            raise ValueError("Chiều quay phải là 1 hoặc -1")
        if not 0 <= v["anchor_y"] <= 1 or not 0.1 <= v["image_aspect"] <= 10:
            raise ValueError("Tỉ lệ ảnh/điểm ngắm không hợp lệ")
        if not isinstance(v["water_samples"], list) or len(v["water_samples"]) > 50:
            raise ValueError("Tối đa 50 mẫu nước")
        for sample in v["water_samples"]:
            if not isinstance(sample, dict) or set(sample) != {"x", "y", "dx", "dy"}:
                raise ValueError("Mẫu nước gồm x,y,dx,dy (cm)")
            for key in sample:
                sample[key] = number(sample[key])
            if not 0 <= sample["x"] <= v["length_cm"] or not 0 <= sample["y"] <= v["width_cm"]:
                raise ValueError("Mẫu nước ngoài sàn")
        self.matrix = None
        corners = np.asarray(v["corners"], dtype=np.float32)
        if corners.size:
            if corners.shape != (4, 2) or not np.isfinite(corners).all() or (corners < 0).any() or (corners > 1).any():
                raise ValueError("Cần đúng bốn góc ảnh chuẩn hóa trong [0,1]")
            contour = corners.reshape(-1, 1, 2)
            if not cv2.isContourConvex(contour) or abs(cv2.contourArea(contour)) < 0.01:
                raise ValueError("Bốn góc phải tạo tứ giác lồi, đúng thứ tự, không trùng")
            dest = np.float32([[0, 0], [v["length_cm"], 0],
                               [v["length_cm"], v["width_cm"]], [0, v["width_cm"]]])
            self.matrix = cv2.getPerspectiveTransform(corners, dest)
            if not np.isfinite(self.matrix).all() or np.linalg.cond(self.matrix) > 1e8:
                raise ValueError("Hiệu chuẩn suy biến")
            v["corners"] = corners.tolist()

    @property
    def ready(self):
        return self.matrix is not None

    def image_to_floor(self, u, v, aspect=None):
        if not self.ready:
            raise ValueError("Chưa hiệu chuẩn bốn góc sàn")
        u, v = number(u), number(v)
        if not 0 <= u <= 1 or not 0 <= v <= 1:
            raise ValueError("Điểm ảnh ngoài khung hình")
        if aspect is not None and abs(number(aspect) / self.values["image_aspect"] - 1) > 0.01:
            raise ValueError("Tỉ lệ ảnh thay đổi; cần hiệu chuẩn lại")
        if cv2.pointPolygonTest(np.float32(self.values["corners"]), (u, v), False) < 0:
            raise ValueError("Điểm nằm ngoài vùng sàn đã hiệu chuẩn")
        point = cv2.perspectiveTransform(np.float32([[[u, v]]]), self.matrix)[0, 0]
        # Ray/target-plane intersection; requires measured camera XY on the floor.
        c = self.values
        ratio = (c["camera_height_cm"] - c["target_height_cm"]) / c["camera_height_cm"]
        x = c["camera_x_cm"] + (float(point[0]) - c["camera_x_cm"]) * ratio
        y = c["camera_y_cm"] + (float(point[1]) - c["camera_y_cm"]) * ratio
        self.check_floor(x, y)
        return x, y

    def check_floor(self, x, y):
        if not (-1e-4 <= x <= self.values["length_cm"] + 1e-4 and
                -1e-4 <= y <= self.values["width_cm"] + 1e-4):
            raise ValueError("Mục tiêu ngoài sàn")

    def angles(self, x, y):
        x, y = number(x), number(y)
        self.check_floor(x, y)
        c = self.values
        # Samples store required command offsets, not observed landing errors.
        samples = c["water_samples"]
        if samples:
            weights = [1 / max(1e-8, (x-s["x"])**2 + (y-s["y"])**2) for s in samples]
            x += sum(w*s["dx"] for w, s in zip(weights, samples)) / sum(weights)
            y += sum(w*s["dy"] for w, s in zip(weights, samples)) / sum(weights)
        dx, dy = x - c["nozzle_x_cm"], y - c["nozzle_y_cm"]
        rotation = math.radians(c["rotation_deg"])
        dx, dy = (math.cos(rotation)*dx + math.sin(rotation)*dy,
                  -math.sin(rotation)*dx + math.cos(rotation)*dy)
        h = c["nozzle_height_cm"] - c["target_height_cm"]
        if c["mechanism"] == "yaw_pitch":
            pan = math.degrees(math.atan2(dy, dx)) if math.hypot(dx, dy) > 1e-6 else 0
            tilt = math.degrees(math.atan2(math.hypot(dx, dy), h))
            # Fold yaw into +/-90 degrees; pitch must cross the downward direction.
            if pan > 90:
                pan, tilt = pan - 180, -tilt
            elif pan < -90:
                pan, tilt = pan + 180, -tilt
        else:
            # Nested orthogonal tilt axes: R_y(-pan) R_x(tilt) (0,0,-1).
            pan = math.degrees(math.atan2(dx, h))
            tilt = math.degrees(math.atan2(dy, math.hypot(dx, h)))
        pan = config.NOZZLE_PAN_ZERO + c["pan_sign"] * pan
        tilt = config.NOZZLE_TILT_ZERO + c["tilt_sign"] * tilt
        if not (config.NOZZLE_PAN_MIN <= pan <= config.NOZZLE_PAN_MAX and
                config.NOZZLE_TILT_MIN <= tilt <= config.NOZZLE_TILT_MAX):
            raise ValueError("Mục tiêu vượt hành trình servo; không tự kẹp góc để phun")
        return pan, tilt


class NozzleController:
    """Caller serializes with FireMonitor._lock; no sleeping or per-client work."""

    def __init__(self, path=None):
        self.path = path or config.NOZZLE_CALIBRATION_PATH
        self.calibration = FloorCalibration()
        self.dry_run = config.NOZZLE_DRY_RUN
        self.phase = "idle"
        self.message = "Chưa hiệu chuẩn bốn góc sàn"
        self.target = None
        self.settled_after = 0.0
        self.last_result = 0.0
        self.confirmer = build_pump_confirmer()
        try:
            with open(self.path, encoding="utf-8") as f:
                self.calibration = FloorCalibration(json.load(f))
            self.message = "Đã nạp hiệu chuẩn"
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, OSError) as error:
            self.message = f"Không nạp được hiệu chuẩn: {error}"

    def save(self, values, *, require_corners=True):
        candidate = FloorCalibration(values)
        if require_corners and not candidate.ready:
            raise ValueError("Cần chọn bốn góc trước khi lưu")
        path = os.path.abspath(self.path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(candidate.values, f, ensure_ascii=False, indent=2, allow_nan=False)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.calibration = candidate
        self.cancel("Đã lưu hiệu chuẩn" if candidate.ready else
                    "Đã lưu thông số; cần chọn và lưu bốn góc để click ngắm")

    def cancel(self, message="Đã hủy chu trình tự động"):
        self.target = None
        self.phase = "idle"
        self.message = message
        self.confirmer.reset()

    def aim(self, x, y, servo):
        pan, tilt = self.calibration.angles(x, y)
        servo.move(pan, tilt)
        return {"x": x, "y": y, "pan": pan, "tilt": tilt}

    def update(self, detections, result_time, frame_time, shape, servo, pump, error=None):
        mono, wall = time.monotonic(), time.time()
        if error or not frame_time or mono-frame_time > config.NOZZLE_RESULT_MAX_AGE:
            if pump.get_state()["state"] == "on":
                pump.stop()
            self.cancel("Kết quả AI lỗi hoặc quá cũ")
            return
        if not pump.is_armed() or not self.calibration.ready:
            self.cancel("Chưa arm hoặc chưa hiệu chuẩn")
            return
        if self.phase == "spraying":
            if pump.get_state()["state"] == "on":
                return
            self.cancel("Đã phun; chờ cooldown và xác nhận lại")
        if pump.get_state()["state"] == "on" or servo.is_moving():
            return
        if result_time <= self.last_result:
            return
        self.last_result = result_time
        if self.phase == "aiming" and frame_time <= self.settled_after:
            return
        h, w = shape[:2]
        candidates = []
        for detection in detections:
            if detection.get("label") != "fire" or detection.get("conf", 0) < config.PUMP_CONFIDENCE_THRESHOLD:
                continue
            try:
                x1, y1, x2, y2 = detection["box"]
                x, y = self.calibration.image_to_floor(
                    (x1+x2)/2/w, (y1+(y2-y1)*self.calibration.values["anchor_y"])/h, w/h)
                self.calibration.angles(x, y)
                candidates.append((float(detection["conf"]), x, y, detection))
            except (KeyError, TypeError, ValueError):
                continue
        if self.target is not None:
            candidates = [c for c in candidates if math.hypot(c[1]-self.target[0], c[2]-self.target[1]) <= config.NOZZLE_TARGET_TOLERANCE_CM]
        if not candidates:
            self.cancel("Mất mục tiêu hoặc mục tiêu ngoài vùng với tới")
            return
        if self.phase == "dry_complete":
            return
        _, x, y, detection = max(candidates, key=lambda c: c[0])
        if self.target is None:
            self.target = (x, y)
            self.phase = "confirming"
        confirmed = self.confirmer.update([detection], now=wall, result_time=result_time)
        if not confirmed:
            return
        if self.phase == "confirming":
            if pump.get_state()["cooldown_remaining"] > 0:
                self.message = "Chờ cooldown"
                return
            try:
                self.aim(*self.target, servo)
            except ValueError as exc:
                self.cancel(str(exc))
                return
            self.phase = "aiming"
            self.settled_after = mono + config.SERVO_SETTLE_SECONDS
            self.message = "Đang ngắm; chờ ảnh mới sau khi ổn định"
        elif self.phase == "aiming":
            if self.dry_run:
                self.phase = "dry_complete"
                self.message = "Ngắm khô hoàn tất; bơm bị khóa. Chờ mục tiêu rời vị trí."
            else:
                ok, self.message = pump.spray("auto-aim", automatic=True,
                                               duration=config.NOZZLE_BURST_SECONDS)
                self.phase = "spraying" if ok else "confirming"
                self.confirmer.reset()

    def state(self):
        return {"phase": self.phase, "message": self.message, "dry_run": self.dry_run,
                "calibrated": self.calibration.ready, "target": self.target,
                "calibration": copy.deepcopy(self.calibration.values)}
