# AGENTS.md

## Commands

On Windows, `requirements-dev.txt` (`pytest`, `gpiozero`) is installed in the system Python (`python`); `venv/` only has runtime packages unless `.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt` is run. On Raspberry Pi, use `./venv/bin/python`.

- **Install dev/test dependencies:** `pip install -r requirements-dev.txt`
- **Run all tests:** `python -m pytest -v`
- **Run a single test:** `python -m pytest tests/test_confirmation.py -k test_sustained_fire_confirmed_and_holds_then_expires -v`
- **Run inference benchmark (no camera needed):** `python benchmark.py --source synthetic --frames 100 --threads 3`
- **Start web dashboard + runtime (primary entrypoint):** `python web_server.py` (serves on `http://0.0.0.0:5000`)
- **Start local OpenCV window mode (legacy, no servo/pump):** `python main.py`
- **Test/auto-bind Telegram bot:** `python notifier.py`

## Environment & Platform Quirks

- **`config.PLATFORM` defaults to `"pi"`:** For laptop execution or unit tests that instantiate `AlertSystem`, `CameraServo`, `WaterPump`, or `FireMonitor`, set or monkeypatch `config.PLATFORM = "laptop"` (or mock `gpiozero.Device.pin_factory = MockFactory(pin_class=MockPWMPin)` when testing Pi-specific servo logic).
- **Raspberry Pi `venv` requirement:** On Raspberry Pi OS, `python3-picamera2`, `python3-gpiozero`, and `python3-opencv` are installed via `apt`. Create the Pi virtualenv with `python3 -m venv venv --system-site-packages`.
- **Camera source independence:** `config.CAMERA_SOURCE` (`"usb"` or `"csi"`) is separate from `config.PLATFORM`. `FireCamera` always returns frames in BGR format regardless of source.
- **Unicode overlay fonts (`display.py`):** Vietnamese text overlays require Pillow + TrueType fonts (`DejaVuSans` on Linux, `arial` on Windows) because OpenCV Hershey fonts lack Unicode support.

## Architecture & Critical Invariants

- **Single shared pipeline (`web_server.py`):** `FireMonitor` runs one background capture + `AsyncFireDetector` loop and broadcasts pre-encoded JPEG bytes via `self._frame_ready` (`threading.Condition`) to all `/video_feed` clients. Never run ONNX inference or JPEG encoding per HTTP client.
- **Two-stage ROI zoom detection (`detector.py`):** `FireSmokeDetector` preprocesses frames with letterbox (`cv2.INTER_AREA` when downscaling) and `cv2.dnn.blobFromImage(..., swapRB=True)` into `320x320`. When `ROI_ZOOM_ENABLED = True` and no primary fire detection meets `CONFIDENCE_THRESHOLD` (`0.40`), weak candidates (`ROI_CANDIDATE_THRESHOLD = 0.22` to `0.40`, box dimensions `<= ROI_MAX_BOX_RATIO`) trigger a 1:1 `320x320` crop re-inference mapped back to full-frame coordinates.
- **Dual confirmation windows (`confirmation.py`):**
  - `FireConfirmer.update()` deduplicates by `result_time` so faster camera loops do not double-count the same async AI inference result.
  - `build_alarm_confirmer()` (1.5s window, `conf >= 0.40`, `min_samples = 4`, `hold_s = 1.5`) drives LED/buzzer/Telegram.
  - `build_pump_confirmer()` (3.0s window, `conf >= 0.60`, `min_samples = 8`, `hold_s = 0.0`) drives automatic water spraying and is intentionally stricter.
- **Servo motion suppression & `lgpio` PWM patch (`actuators.py`, `web_server.py`):**
  - While `servo.is_moving()` is true (`SERVO_SETTLE_SECONDS`), `FireMonitor` skips feeding frames to `AsyncFireDetector` and skips confirmation updates to prevent motion-blur false positives.
  - `_patch_lgpio_pwm_pin()` patches `gpiozero`/`lgpio` `LGPIOPin._set_state` to preserve float duty cycles (`round(float(value) * 100.0, 4)`) instead of truncating to `int`, and `CameraServo` detaches PWM after `SERVO_SETTLE_SECONDS` (`0.8s`) to eliminate SG90 jitter. Do not remove this patch.
- **Actuator watchdog & pump safety (`web_server.py`, `actuators.py`):**
  - `GET /api/status` must **never** call `_touch_control()`. Only explicit user control actions (`servo_action`, `pump_action`, `set_auto_arm`, `camera_action`) update `_last_control_at`, ensuring unattended browser tabs still trigger auto-disarm after `ACTUATOR_WATCHDOG_SECONDS` (`600s`).
  - `WaterPump.spray(automatic=True)` requires `_armed == True`, enforces `PUMP_COOLDOWN` (`15s`) and `PUMP_MAX_PER_MINUTE` (`4`), and always auto-stops via timer after `PUMP_MAX_SECONDS` (`5s`).
- **Telegram config mutation (`notifier.py`, `config.py`):** `TelegramNotifier` prefers `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars over `config.py`. If `TELEGRAM_CHAT_ID` is empty in `config.py`, `_save_chat_id_to_config()` rewrites `config.py` in-place when `/start` is received—check `git diff config.py` before committing.
