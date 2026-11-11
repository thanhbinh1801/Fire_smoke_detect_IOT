"""Flask dashboard and shared camera/inference/alarm runtime."""

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

logger = logging.getLogger(__name__)


class FireMonitor:
    def __init__(self):
        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._thread = None
        self._camera = None
        self._servo = None
        self._pump = None
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

    def _update_state(self, **updates):
        with self._frame_ready:
            self._state.update(updates)
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
            from confirmation import build_alarm_confirmer, build_pump_confirmer
            from detector import AsyncFireDetector, FireSmokeDetector

            camera = FireCamera()
            detector = FireSmokeDetector()
            async_detector = AsyncFireDetector(detector)
            alert = AlertSystem()
            servo = CameraServo()
            pump = WaterPump()
            alarm_confirmer = build_alarm_confirmer()
            pump_confirmer = build_pump_confirmer()
            with self._lock:
                self._camera = camera
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

            while not self._stop_event.is_set():
                loop_started = time.monotonic()
                new_frame, frame_time = camera.get_frame_if_new(last_camera_frame_time)
                if frame_time <= 0.0:
                    self._stop_event.wait(0.01)
                    continue
                if time.monotonic() - frame_time > float(
                    getattr(config, "CAMERA_STALE_TIMEOUT", 2.0)
                ):
                    raise RuntimeError("Camera không cung cấp frame mới quá thời gian cho phép.")

                servo_moving = servo.is_moving()
                has_new_frame = new_frame is not None
                if has_new_frame:
                    frame = new_frame
                    last_camera_frame_time = frame_time
                    if not servo_moving:
                        async_detector.update_frame(frame)
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
                    if has_new_result:
                        if confirmed_fire and fire_detections:
                            self._notifier.notify(
                                "fire",
                                frame,
                                detections,
                                fps=camera_fps,
                                ai_fps=ai_fps,
                            )
                        if smoke_detections:
                            smoke_votes += 1
                            required_smoke_votes = max(
                                1, int(getattr(config, "SMOKE_CONFIRMATION_FRAMES", 2))
                            )
                            if smoke_votes >= required_smoke_votes and not confirmed_fire:
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

                if config.SAVE_SNAPSHOT and confirmed_fire and fire_detections:
                    last_snap = getattr(self, "_last_snapshot_time", 0.0)
                    if now - last_snap >= 2.0:
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        filename = os.path.join(
                            config.SNAPSHOT_DIR,
                            f"alert_{timestamp}_{int(now * 1000) % 1000}.jpg",
                        )
                        if not cv2.imwrite(filename, frame):
                            logger.error("Không lưu được ảnh cảnh báo: %s", filename)
                        self._last_snapshot_time = now

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

                if time.monotonic() >= next_stream_at:
                    overlay = display.draw_overlay(
                        frame, display_detections, fps=camera_fps, ai_fps=ai_fps
                    )
                    encoded, jpeg = cv2.imencode(
                        ".jpg", overlay, [int(cv2.IMWRITE_JPEG_QUALITY), 80]
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

    def get_status(self):
        with self._lock:
            state = dict(self._state)
            servo = self._servo
            pump = self._pump
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
            "color": lambda camera: camera.toggle_color_swap(),
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
        if action == "color":
            return True, f"Đảo kênh màu {'bật' if result else 'tắt'}."
        return True, result if result is not None else "Đã gửi lệnh."

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
    app.run(
        host=getattr(config, "WEB_HOST", "127.0.0.1"),
        port=int(getattr(config, "WEB_PORT", 5000)),
        threaded=True,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
