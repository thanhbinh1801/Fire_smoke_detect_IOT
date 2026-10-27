"""Flask dashboard and shared camera/inference/alarm runtime."""

import logging
import os
import threading
import time

import cv2
from flask import Flask, Response, jsonify, render_template

import config
import display

logger = logging.getLogger(__name__)


class FireMonitor:
    def __init__(self):
        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._thread = None
        self._camera = None
        self._state = {
            "status": "starting",
            "error": None,
            "platform": config.PLATFORM,
            "model": config.MODEL_PATH,
            "camera_fps": 0.0,
            "ai_fps": 0.0,
            "fire_detected": False,
            "detections": [],
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
        camera = detector = alert = None
        async_detector = None
        try:
            from alert import AlertSystem
            from camera import FireCamera
            from detector import AsyncFireDetector, FireSmokeDetector

            camera = FireCamera()
            self._camera = camera
            detector = FireSmokeDetector()
            async_detector = AsyncFireDetector(detector)
            alert = AlertSystem()
            if config.SAVE_SNAPSHOT:
                os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)

            self._update_state(status="running")
            logger.info("Web monitor đang chạy trên nền tảng %s", config.PLATFORM)

            frame_count = 0
            fps_started = time.monotonic()
            camera_fps = 0.0
            last_result_time = 0.0
            last_camera_frame_time = 0.0
            last_fire_time = 0.0
            confirmed_fire = False
            fire_votes = 0
            cached_detections = []
            stream_interval = 1.0 / max(1, int(getattr(config, "WEB_STREAM_FPS", 12)))
            next_stream_at = 0.0
            loop_interval = 1.0 / max(1, int(getattr(config, "CAMERA_FPS", 30)))

            while not self._stop_event.is_set():
                loop_started = time.monotonic()
                frame, frame_time = camera.get_frame_with_timestamp()
                if frame is None:
                    self._stop_event.wait(0.01)
                    continue
                if time.monotonic() - frame_time > float(
                    getattr(config, "CAMERA_STALE_TIMEOUT", 2.0)
                ):
                    raise RuntimeError("Camera không cung cấp frame mới quá thời gian cho phép.")

                has_new_frame = frame_time != last_camera_frame_time
                if has_new_frame:
                    last_camera_frame_time = frame_time
                    async_detector.update_frame(frame)
                detections, ai_fps, result_time, inference_error = async_detector.get_result()
                now = time.time()
                fire_detections = [
                    detection for detection in detections
                    if detection.get("label") == "fire"
                ]

                if result_time and result_time != last_result_time:
                    last_result_time = result_time
                    if fire_detections:
                        fire_votes += 1
                        last_fire_time = now
                        cached_detections = detections
                        required_votes = max(
                            1, int(getattr(config, "FIRE_CONFIRMATION_FRAMES", 2))
                        )
                        if fire_votes >= required_votes:
                            confirmed_fire = True
                    else:
                        fire_votes = 0
                        if detections:
                            cached_detections = detections

                if confirmed_fire and now - last_fire_time >= max(
                    0.0, float(getattr(config, "HOLD_FIRE_TIME", 1.5))
                ):
                    confirmed_fire = False
                    fire_votes = 0

                alert.set_fire_led(confirmed_fire)
                alert.set_buzzer(confirmed_fire)

                if config.SAVE_SNAPSHOT and fire_detections and result_time == last_result_time:
                    if result_time > 0 and result_time != getattr(self, "_snapshot_result_time", 0):
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        filename = os.path.join(
                            config.SNAPSHOT_DIR,
                            f"alert_{timestamp}_{int(now * 1000) % 1000}.jpg",
                        )
                        if not cv2.imwrite(filename, frame):
                            logger.error("Không lưu được ảnh cảnh báo: %s", filename)
                        self._snapshot_result_time = result_time

                if has_new_frame:
                    frame_count += 1
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
                ("AI worker", async_detector, "stop"),
                ("camera", camera, "close"),
                ("alert", alert, "cleanup"),
            ):
                cleanup_error = self._cleanup(name, resource, method)
                if cleanup_error:
                    cleanup_errors.append(cleanup_error)
            self._camera = None
            with self._frame_ready:
                if cleanup_errors and not self._state["error"]:
                    self._state.update(status="error", error="; ".join(cleanup_errors))
                elif self._state["status"] != "error":
                    self._state.update(status="stopped", fire_detected=False)
                self._frame_ready.notify_all()

    def get_status(self):
        with self._lock:
            return dict(self._state)

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
