# web_server.py
"""
Flask Web Server cho hệ thống nhận diện lửa/khói IoT.
Chạy trong luồng nền riêng biệt, không ảnh hưởng đến vòng lặp AI chính.

Endpoints:
  GET /            → Dashboard HTML
  GET /stream      → MJPEG video stream
  GET /api/status  → JSON trạng thái hệ thống
  GET /api/history → JSON lịch sử cảnh báo
  GET /events      → SSE stream cho realtime alerts
"""

import time
import json
import threading
import logging

import web_state

# Tắt log verbose của Flask/Werkzeug
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

_flask_app = None
_server_thread = None
WEB_PORT = 5000


def _create_app():
    from flask import Flask, Response, stream_with_context
    app = Flask(__name__, template_folder="templates")
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    # ── Dashboard ────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        from flask import render_template
        return render_template("index.html")

    # ── MJPEG Stream ─────────────────────────────────────────────────────────
    @app.route("/stream")
    def stream():
        def generate():
            while True:
                jpg = web_state.get_frame()
                if jpg:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                    )
                time.sleep(0.033)  # ~30 FPS cap

        return Response(
            stream_with_context(generate()),
            mimetype="multipart/x-mixed-replace; boundary=frame"
        )

    # ── API: Trạng thái hiện tại ──────────────────────────────────────────────
    @app.route("/api/status")
    def api_status():
        status = web_state.get_status()
        return Response(
            json.dumps(status),
            mimetype="application/json",
            headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"}
        )

    # ── API: Lịch sử cảnh báo ─────────────────────────────────────────────────
    @app.route("/api/history")
    def api_history():
        history = web_state.get_alert_history()
        return Response(
            json.dumps(history),
            mimetype="application/json",
            headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"}
        )

    # ── SSE: Realtime events ──────────────────────────────────────────────────
    @app.route("/events")
    def events():
        def generate():
            last_is_fire = None
            while True:
                status = web_state.get_status()
                is_fire = status["is_fire"]
                # Chỉ gửi khi trạng thái thay đổi
                if is_fire != last_is_fire:
                    data = json.dumps({
                        "is_fire": is_fire,
                        "label": status["label"],
                        "confidence": status["confidence"],
                        "time_str": time.strftime("%H:%M:%S"),
                    })
                    yield f"data: {data}\n\n"
                    last_is_fire = is_fire
                # Heartbeat mỗi 3 giây để giữ kết nối
                else:
                    yield ": heartbeat\n\n"
                time.sleep(1.0)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            }
        )

    return app


def start(port: int = WEB_PORT):
    """Khởi động Flask web server trong daemon thread."""
    global _flask_app, _server_thread

    _flask_app = _create_app()

    def _run():
        _flask_app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    _server_thread = threading.Thread(target=_run, daemon=True, name="WebServer")
    _server_thread.start()
    print(f"[Web] Dashboard dang chay tai: http://0.0.0.0:{port}")
    print(f"[Web] Truy cap tu trinh duyet: http://<IP_cua_Pi>:{port}")
