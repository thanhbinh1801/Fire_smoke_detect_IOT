"""Flask dashboard and shared camera/inference/alarm runtime."""

from collections import deque
import logging
import os
import threading
import time

import cv2
from flask import Flask, Response, jsonify, render_template, request

import config
import display
from actuators import CameraServo, WaterPump
from notifier import TelegramNotifier
from preprocessing import FramePreprocessor

logger = logging.getLogger(__name__)


class FireMonitor:
    def __init__(self):
        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._thread = None
        self._camera = None
        self._detector = None
        self._alarm_confirmer = None
        self._smoke_confirmer = None
        self._servo = None
        self._pump = None
        self._history = deque(maxlen=30)
        self._last_history_at = {"fire": 0.0, "smoke": 0.0}
        self._last_control_at = time.monotonic()
        self._notifier = TelegramNotifier()
        self._state = {
            "status": "starting",
            "error": None,
            "platform": config.PLATFORM,
            "camera_source": getattr(config, "CAMERA_SOURCE", "usb"),
            "model": config.MODEL_PATH,
            "camera_fps": 0.0,
            "ai_fps": 0.0,
            "fire_detected": False,
            "detections": [],
            "telegram": self._notifier.get_status(),
            "updated_at": None,
        }
        self._jpeg = None
        self._frame_sequence = 0
        self.start()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._state.update(status="starting", error=None)
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="FireMonitor"
            )
            self._thread.start()

    def stop(self):
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    def _update_state(self, notify_stream: bool = False, **updates):
        with self._frame_ready:
            self._state.update(updates)
            if notify_stream or "status" in updates:
                self._frame_ready.notify_all()

    @staticmethod
    def _cleanup(name, resource, method):
        if resource is None:
            return None
        try:
            getattr(resource, method)()
        except Exception as error:
            logger.exception("Lỗi khi giải phóng %s", name)
            return f"{name}: {error}"
        return None

    def _run(self):
        camera = detector = alert = servo = pump = None
        async_detector = None
        try:
            from alert import AlertSystem
            from camera import FireCamera
            from confirmation import (
                AsyncSnapshotSaver,
                build_alarm_confirmer,
                build_pump_confirmer,
                build_smoke_confirmer,
            )
            from detector import AsyncFireDetector, FireSmokeDetector

            camera = FireCamera()
            detector = FireSmokeDetector()
            async_detector = AsyncFireDetector(detector)
            alert = AlertSystem()
            servo = CameraServo()
            pump = WaterPump()
            alarm_confirmer = build_alarm_confirmer()
            smoke_confirmer = build_smoke_confirmer()
            pump_confirmer = build_pump_confirmer()
            snapshot_saver = AsyncSnapshotSaver()
            with self._lock:
                self._camera = camera
                self._detector = detector
                self._alarm_confirmer = alarm_confirmer
                self._smoke_confirmer = smoke_confirmer
                self._servo = servo
                self._pump = pump
                self._last_control_at = time.monotonic()
            if config.SAVE_SNAPSHOT:
                os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)

            self._update_state(status="running")
            logger.info("Web monitor đang chạy trên nền tảng %s", config.PLATFORM)

            frame = None
            frame_count = 0
            fps_started = time.monotonic()
            camera_fps = 0.0
            last_result_time = 0.0
            last_camera_frame_time = 0.0
            last_fire_time = 0.0
            confirmed_fire = False
            smoke_votes = 0
            cached_detections = []
            watchdog_seconds = float(
                getattr(config, "ACTUATOR_WATCHDOG_SECONDS", 600.0)
            )
            stream_interval = 1.0 / max(1, int(getattr(config, "WEB_STREAM_FPS", 12)))
            next_stream_at = 0.0
            loop_interval = 1.0 / max(1, int(getattr(config, "CAMERA_FPS", 30)))
            stale_timeout = float(getattr(config, "CAMERA_STALE_TIMEOUT", 2.0))
            jpeg_quality = max(
                30, min(95, int(getattr(config, "WEB_JPEG_QUALITY", 80)))
            )
            required_smoke_votes = max(
                1, int(getattr(config, "SMOKE_CONFIRMATION_FRAMES", 2))
            )

            while not self._stop_event.is_set():
                loop_started = time.monotonic()
                new_frame, frame_time = camera.wait_for_new_frame(
                    last_camera_frame_time, timeout=0.004, copy=False
                )
                if frame_time <= 0.0:
                    self._stop_event.wait(0.005)
                    continue
                if time.monotonic() - frame_time > stale_timeout:
                    raise RuntimeError("Camera không cung cấp frame mới quá thời gian cho phép.")

                servo_moving = servo.is_moving()
                has_new_frame = new_frame is not None
                if has_new_frame:
                    frame = new_frame
                    last_camera_frame_time = frame_time
                    if not servo_moving:
                        async_detector.update_frame(frame, frame_timestamp=frame_time)
                    frame_count += 1
                if frame is None:
                    self._stop_event.wait(0.005)
                    continue

                detections, ai_fps, result_time, inference_error = async_detector.get_result()
                now = time.time()
                fire_detections = [
                    detection for detection in detections
                    if detection.get("label") == "fire"
                ]
                smoke_detections = [
                    detection for detection in detections
                    if detection.get("label") == "smoke"
                ]

                has_new_result = bool(result_time and result_time != last_result_time)
                if has_new_result:
                    last_result_time = result_time
                    if not servo_moving:
                        if fire_detections:
                            last_fire_time = now
                            cached_detections = detections
                        elif detections:
                            cached_detections = detections

                if not servo_moving:
                    confirmed_fire = alarm_confirmer.update(
                        detections, now=now, result_time=result_time
                    )
                    confirmed_smoke = smoke_confirmer.update(
                        detections, now=now, result_time=result_time
                    )
                    if has_new_result:
                        if confirmed_fire and fire_detections:
                            self._record_history_event("fire", fire_detections, now)
                            self._notifier.notify(
                                "fire",
                                frame,
                                detections,
                                fps=camera_fps,
                                ai_fps=ai_fps,
                            )
                            snapshot_saver.save_if_due(frame, now=now)
                        if smoke_detections:
                            smoke_votes += 1
                            if (
                                smoke_votes >= required_smoke_votes or confirmed_smoke
                            ) and not confirmed_fire:
                                self._record_history_event("smoke", smoke_detections, now)
                                self._notifier.notify(
                                    "smoke",
                                    frame,
                                    detections,
                                    fps=camera_fps,
                                    ai_fps=ai_fps,
                                )
                        else:
                            smoke_votes = 0

                    if not confirmed_fire and not detections:
                        cached_detections = []

                    if has_new_result and pump_confirmer.update(
                        detections, now=now, result_time=result_time
                    ):
                        ok, message = pump.spray("auto", automatic=True)
                        if ok:
                            pump_confirmer.reset()
                            logger.warning("Phun tự động: %s", message)

                alert.set_fire_led(confirmed_fire)
                alert.set_buzzer(confirmed_fire)

                if (
                    pump.is_armed()
                    and time.monotonic() - self._last_control_at > watchdog_seconds
                ):
                    pump.arm(False)
                    logger.warning(
                        "Không có điều khiển từ web trong %.0fs - tự disarm phun tự động.",
                        watchdog_seconds,
                    )

                elapsed = time.monotonic() - fps_started
                if elapsed >= 1.0:
                    camera_fps = frame_count / elapsed
                    frame_count = 0
                    fps_started = time.monotonic()

                if detections:
                    display_detections = detections
                elif confirmed_fire and now - last_fire_time < max(
                    0.0, float(getattr(config, "HOLD_FIRE_TIME", 1.5))
                ):
                    display_detections = cached_detections
                else:
                    display_detections = []

                self._notifier.update_runtime_context(
                    frame,
                    display_detections,
                    fps=camera_fps,
                    ai_fps=ai_fps,
                    confirmed_fire=confirmed_fire,
                )
                self._update_state(
                    camera_fps=round(camera_fps, 1),
                    ai_fps=round(ai_fps, 1),
                    fire_detected=confirmed_fire,
                    detections=[
                        {
                            "label": item.get("label", "unknown"),
                            "confidence": round(float(item.get("conf", 0.0)), 3),
                            "box": list(item.get("box", ())),
                        }
                        for item in detections
                    ],
                    inference_error=inference_error,
                    servo=servo.get_state(),
                    pump=pump.get_state(),
                    auto_armed=pump.is_armed(),
                    telegram=self._notifier.get_status(),
                    updated_at=now,
                )

                if not servo_moving and time.monotonic() >= next_stream_at:
                    overlay = display.draw_overlay(
                        frame, display_detections, fps=camera_fps, ai_fps=ai_fps
                    )
                    encoded, jpeg = cv2.imencode(
                        ".jpg", overlay, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
                    )
                    if encoded:
                        with self._frame_ready:
                            self._jpeg = jpeg.tobytes()
                            self._frame_sequence += 1
                            self._frame_ready.notify_all()
                    else:
                        logger.warning("OpenCV không mã hóa được frame thành JPEG")
                    next_stream_at = time.monotonic() + stream_interval

                self._stop_event.wait(max(0.0, loop_interval - (time.monotonic() - loop_started)))

        except Exception as error:
            logger.exception("Web monitor gặp lỗi")
            self._update_state(status="error", error=str(error), fire_detected=False)
        finally:
            cleanup_errors = []
            for name, resource, method in (
                ("Pump", pump, "cleanup"),
                ("Servo", servo, "cleanup"),
                ("AI worker", async_detector, "stop"),
                ("camera", camera, "close"),
                ("alert", alert, "cleanup"),
            ):
                cleanup_error = self._cleanup(name, resource, method)
                if cleanup_error:
                    cleanup_errors.append(cleanup_error)
            with self._lock:
                self._camera = None
                self._servo = None
                self._pump = None
            with self._frame_ready:
                if cleanup_errors and not self._state["error"]:
                    self._state.update(status="error", error="; ".join(cleanup_errors))
                elif self._state["status"] != "error":
                    self._state.update(status="stopped", fire_detected=False)
                self._frame_ready.notify_all()

    def _touch_control(self):
        self._last_control_at = time.monotonic()

    def _record_history_event(self, event_type: str, items: list, now: float):
        with self._lock:
            if now - self._last_history_at.get(event_type, 0.0) < 5.0:
                return
            self._last_history_at[event_type] = now
            max_conf = max((float(d.get("conf", 0.0)) for d in items), default=0.0)
            self._history.appendleft(
                {
                    "id": f"{int(now * 1000)}",
                    "type": event_type,
                    "count": len(items),
                    "max_conf": round(max_conf, 3),
                    "timestamp": now,
                    "time_str": time.strftime("%H:%M:%S - %d/%m", time.localtime(now)),
                }
            )

    def get_settings(self):
        with self._lock:
            det = self._detector
        if det is None:
            return {
                "confidence_threshold": getattr(config, "CONFIDENCE_THRESHOLD", 0.40),
                "fire_confidence_threshold": getattr(config, "FIRE_CONFIDENCE_THRESHOLD", 0.40),
                "smoke_confidence_threshold": getattr(config, "SMOKE_CONFIDENCE_THRESHOLD", 0.38),
                "roi_zoom_enabled": getattr(config, "ROI_ZOOM_ENABLED", True),
                "enable_clahe": getattr(config, "PREPROCESS_ENABLE_CLAHE", False),
                "gamma": getattr(config, "PREPROCESS_GAMMA", 1.0),
                "auto_wb": getattr(config, "PREPROCESS_AUTO_WB", False),
                "sharpen": getattr(config, "PREPROCESS_SHARPEN", False),
            }
        prep = det.preprocessor
        return {
            "confidence_threshold": round(float(det.conf_threshold), 2),
            "fire_confidence_threshold": round(float(det.fire_conf_threshold), 2),
            "smoke_confidence_threshold": round(float(det.smoke_conf_threshold), 2),
            "roi_zoom_enabled": bool(det.roi_zoom_enabled),
            "enable_clahe": bool(prep.enable_clahe),
            "gamma": round(float(prep.gamma), 2),
            "auto_wb": bool(prep.auto_wb),
            "sharpen": bool(prep.sharpen),
        }

    def update_settings(self, payload: dict):
        with self._lock:
            det = self._detector
            alarm_c = self._alarm_confirmer
            smoke_c = self._smoke_confirmer
        if det is None:
            return False, "Detector chưa sẵn sàng."
        self._touch_control()
        prep = det.preprocessor
        if "fire_confidence_threshold" in payload:
            val = max(0.10, min(0.95, float(payload["fire_confidence_threshold"])))
            det.fire_conf_threshold = val
            det.conf_threshold = val
            config.FIRE_CONFIDENCE_THRESHOLD = val
            config.CONFIDENCE_THRESHOLD = val
            if alarm_c is not None:
                alarm_c.threshold = val
        if "smoke_confidence_threshold" in payload:
            val = max(0.10, min(0.95, float(payload["smoke_confidence_threshold"])))
            det.smoke_conf_threshold = val
            config.SMOKE_CONFIDENCE_THRESHOLD = val
            if smoke_c is not None:
                smoke_c.threshold = val
        if "roi_zoom_enabled" in payload:
            det.roi_zoom_enabled = bool(payload["roi_zoom_enabled"])
            config.ROI_ZOOM_ENABLED = det.roi_zoom_enabled
        if "enable_clahe" in payload:
            prep.enable_clahe = bool(payload["enable_clahe"])
            config.PREPROCESS_ENABLE_CLAHE = prep.enable_clahe
        if "auto_wb" in payload:
            prep.auto_wb = bool(payload["auto_wb"])
            config.PREPROCESS_AUTO_WB = prep.auto_wb
        if "sharpen" in payload:
            prep.sharpen = bool(payload["sharpen"])
            config.PREPROCESS_SHARPEN = prep.sharpen
        if "gamma" in payload:
            g_val = max(0.4, min(2.5, float(payload["gamma"])))
            prep.gamma = g_val
            prep._gamma_lut = FramePreprocessor._build_gamma_lut(g_val)
            config.PREPROCESS_GAMMA = g_val
        return True, "Đã cập nhật cấu hình AI & Tiền xử lý trực tiếp!"

    def clear_history(self):
        with self._lock:
            self._history.clear()
        return True, "Đã xóa nhật ký cảnh báo."

    def get_status(self):
        with self._lock:
            state = dict(self._state)
            servo = self._servo
            pump = self._pump
            history = list(self._history)
        state["camera_source"] = getattr(config, "CAMERA_SOURCE", "usb")
        state["servo"] = (
            servo.get_state()
            if servo is not None
            else {"angle": None, "available": False}
        )
        state["pump"] = (
            pump.get_state()
            if pump is not None
            else {
                "state": "off",
                "armed": False,
                "available": False,
                "seconds_remaining": 0.0,
                "cooldown_remaining": 0.0,
                "runs_last_minute": 0,
                "max_per_minute": 0,
            }
        )
        state["auto_armed"] = bool(pump.is_armed()) if pump is not None else False
        state["telegram"] = self._notifier.get_status()
        state["history"] = history
        state["settings"] = self.get_settings()
        return state

    def test_telegram(self):
        with self._lock:
            camera = self._camera
            fps = self._state.get("camera_fps")
            ai_fps = self._state.get("ai_fps")
        frame = camera.get_frame() if camera is not None else None
        return self._notifier.send_test(frame=frame, fps=fps, ai_fps=ai_fps)

    def servo_action(self, payload):
        action = str((payload or {}).get("action", "")).strip().lower()
        with self._lock:
            servo = self._servo
        if servo is None:
            return False, "Servo chưa sẵn sàng."

        self._touch_control()
        try:
            if action == "left":
                angle = servo.step(-1)
            elif action == "right":
                angle = servo.step(+1)
            elif action == "center":
                angle = servo.center()
            elif action == "set":
                angle = servo.set_angle(float((payload or {}).get("angle")))
            else:
                return False, "Thao tác servo không hợp lệ."
        except (TypeError, ValueError):
            return False, "Góc servo không hợp lệ."

        if angle is None:
            return False, "Không điều khiển được servo."
        return True, f"Servo ở {angle:.0f}°."

    def pump_action(self, action):
        action = str(action or "").strip().lower()
        with self._lock:
            pump = self._pump
        if pump is None:
            return False, "Bơm chưa sẵn sàng."

        self._touch_control()
        if action == "on":
            return pump.spray("manual", automatic=False)
        if action in ("off", "stop"):
            return pump.stop()
        return False, "Thao tác bơm không hợp lệ."

    def set_auto_arm(self, enabled):
        with self._lock:
            pump = self._pump
        if pump is None:
            return False, "Bơm chưa sẵn sàng."
        self._touch_control()
        armed = pump.arm(enabled)
        if armed:
            return True, "Đã bật phun tự động khi xác nhận có lửa."
        return True, "Đã tắt phun tự động."

    def camera_action(self, action):
        actions = {
            "autofocus": lambda camera: camera.trigger_autofocus(),
            "focus_near": lambda camera: camera.adjust_focus(+0.2),
            "focus_far": lambda camera: camera.adjust_focus(-0.2),
        }
        if action not in actions:
            return False, "Thao tác camera không hợp lệ."
        with self._lock:
            camera = self._camera
        if camera is None:
            return False, "Camera chưa sẵn sàng."
        self._touch_control()
        try:
            result = actions[action](camera)
        except Exception as error:
            logger.exception("Không thực hiện được thao tác camera %s", action)
            return False, str(error)
        return True, result if result is not None else "Đã gửi lệnh."

    def get_latest_jpeg(self):
        with self._frame_ready:
            return self._jpeg

    def stream(self):
        sequence = 0
        while True:
            with self._frame_ready:
                self._frame_ready.wait_for(
                    lambda: self._frame_sequence != sequence
                    or (self._thread is None or not self._thread.is_alive()),
                    timeout=10,
                )
                if self._frame_sequence == sequence:
                    return
                sequence = self._frame_sequence
                jpeg = self._jpeg
            if jpeg:
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )


def create_app(monitor=None):
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    app.monitor = monitor if monitor is not None else FireMonitor()

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/video_feed")
    def video_feed():
        return Response(
            app.monitor.stream(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/api/snapshot")
    def snapshot():
        jpeg = app.monitor.get_latest_jpeg()
        if not jpeg:
            return jsonify({"ok": False, "message": "Chưa có khung hình camera."}), 503
        return Response(
            jpeg,
            mimetype="image/jpeg",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/api/status")
    def status():
        return jsonify(app.monitor.get_status())

    @app.post("/api/camera/<action>")
    def camera_action(action):
        ok, message = app.monitor.camera_action(action)
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    @app.post("/api/servo")
    def servo_control():
        payload = request.get_json(silent=True) or {}
        ok, message = app.monitor.servo_action(payload)
        status = app.monitor.get_status()
        return (
            jsonify({"ok": ok, "message": message, "servo": status["servo"]}),
            (200 if ok else 400),
        )

    @app.post("/api/pump")
    def pump_control():
        payload = request.get_json(silent=True) or {}
        ok, message = app.monitor.pump_action(payload.get("action"))
        status = app.monitor.get_status()
        return (
            jsonify(
                {
                    "ok": ok,
                    "message": message,
                    "pump": status["pump"],
                    "auto_armed": status["auto_armed"],
                }
            ),
            (200 if ok else 400),
        )

    @app.post("/api/pump/arm")
    def pump_arm():
        payload = request.get_json(silent=True) or {}
        if "armed" not in payload:
            return jsonify({"ok": False, "message": "Thiếu trường 'armed'."}), 400
        value = payload.get("armed")
        if isinstance(value, str):
            enabled = value.strip().lower() in ("1", "true", "yes", "on")
        else:
            enabled = bool(value)
        ok, message = app.monitor.set_auto_arm(enabled)
        return (
            jsonify({"ok": ok, "message": message, "auto_armed": enabled}),
            (200 if ok else 400),
        )

    @app.post("/api/telegram/test")
    def telegram_test():
        ok, message = app.monitor.test_telegram()
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    @app.get("/api/settings")
    def get_settings():
        return jsonify({"ok": True, "settings": app.monitor.get_settings()})

    @app.post("/api/settings")
    def update_settings():
        payload = request.get_json(silent=True) or {}
        ok, message = app.monitor.update_settings(payload)
        return (
            jsonify(
                {
                    "ok": ok,
                    "message": message,
                    "settings": app.monitor.get_settings(),
                }
            ),
            (200 if ok else 400),
        )

    @app.post("/api/history/clear")
    def clear_history():
        ok, message = app.monitor.clear_history()
        return jsonify({"ok": ok, "message": message})

    @app.post("/api/restart")
    def restart():
        app.monitor.start()
        return jsonify({"ok": True, "status": app.monitor.get_status()["status"]})

    return app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = create_app()
    try:
        app.run(
            host=getattr(config, "WEB_HOST", "127.0.0.1"),
            port=int(getattr(config, "WEB_PORT", 5000)),
            threaded=True,
            debug=False,
            use_reloader=False,
        )
    except KeyboardInterrupt:
        pass
    finally:
        app.monitor.stop()


if __name__ == "__main__":
    main()
