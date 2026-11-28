# config.py
"""
Cấu hình hệ thống nhận diện khói & lửa IoT.
Tự động nạp thông số từ file .env (hoặc biến môi trường hệ thống),
hỗ trợ cả môi trường Laptop (để test) và Raspberry Pi 4 (thực tế).
"""

import os
import json
import platform as host_platform

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE_PATH = os.path.join(_BASE_DIR, ".env")


def load_env_file(dotenv_path: str = ENV_FILE_PATH, override: bool = False) -> bool:
    """
    Nạp biến môi trường từ file .env.
    Ưu tiên dùng python-dotenv nếu có, đồng thời có bộ parser tích hợp sẵn
    để hệ thống luôn chạy được ngay cả khi chưa cài python-dotenv.
    """
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        if os.path.exists(dotenv_path):
            load_dotenv(dotenv_path=dotenv_path, override=override, encoding="utf-8")
            return True
    except ImportError:
        pass

    if not os.path.exists(dotenv_path):
        return False

    try:
        with open(dotenv_path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key:
                    continue
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                elif "#" in value:
                    for idx, ch in enumerate(value):
                        if ch == "#" and (idx == 0 or value[idx - 1].isspace()):
                            value = value[:idx].strip()
                            break
                if override or key not in os.environ:
                    os.environ[key] = value
        return True
    except Exception as error:
        print(f"[Config] Cảnh báo: Không thể đọc file .env ({error})")
        return False


ENV_FILE_LOADED = load_env_file()


def _env_str(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    if val is None:
        return default
    return str(val).strip()


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is None or not str(val).strip():
        return int(default)
    try:
        return int(float(str(val).strip()))
    except (TypeError, ValueError):
        return int(default)


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    if val is None or not str(val).strip():
        return float(default)
    try:
        return float(str(val).strip())
    except (TypeError, ValueError):
        return float(default)


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None or not str(val).strip():
        return bool(default)
    normalized = str(val).strip().lower()
    if normalized in ("1", "true", "yes", "on", "y"):
        return True
    if normalized in ("0", "false", "no", "off", "n"):
        return False
    return bool(default)


def _detect_platform() -> str:
    """Detect Raspberry Pi from its device-tree model; use laptop otherwise."""
    try:
        with open("/proc/device-tree/model", "rb") as model_file:
            model_bytes = model_file.read().replace(b"\x00", b"")
        model = model_bytes.decode("utf-8", errors="ignore")
        if "raspberry pi" in model.lower():
            return "pi"
    except OSError:
        pass

    if host_platform.system() == "Linux" and host_platform.machine().lower() in {
        "aarch64", "armv7l", "armv6l"
    }:
        return "pi"
    return "laptop"


def _resolve_platform(value: str) -> str:
    normalized = str(value or "auto").strip().lower()
    if normalized in ("", "auto"):
        return _detect_platform()
    if normalized in ("pi", "laptop"):
        return normalized
    return _detect_platform()


# ==============================================================================
# 1. MODEL AI & SUY LUẬN (ONNX RUNTIME + ROI ZOOM 2 GIAI ĐOẠN)
# ==============================================================================
MODEL_PATH = _env_str("MODEL_PATH", "models/fire_smoke_yolov8n.onnx")

CONFIDENCE_THRESHOLD = _env_float("CONFIDENCE_THRESHOLD", 0.35)
FIRE_CONFIDENCE_THRESHOLD = _env_float("FIRE_CONFIDENCE_THRESHOLD", CONFIDENCE_THRESHOLD)
SMOKE_CONFIDENCE_THRESHOLD = _env_float("SMOKE_CONFIDENCE_THRESHOLD", CONFIDENCE_THRESHOLD)
IOU_THRESHOLD = _env_float("IOU_THRESHOLD", 0.45)

MIN_BOX_AREA = _env_int("MIN_BOX_AREA", 36)
ORT_INTRA_OP_THREADS = _env_int(
    "ORT_INTRA_OP_THREADS", _env_int("ORT_INTRA_THREADS", 3)
)
ORT_INTRA_THREADS = ORT_INTRA_OP_THREADS

ROI_ZOOM_ENABLED = _env_bool("ROI_ZOOM_ENABLED", True)
ROI_CANDIDATE_THRESHOLD = _env_float("ROI_CANDIDATE_THRESHOLD", 0.22)
ROI_MAX_BOX_RATIO = _env_float("ROI_MAX_BOX_RATIO", 0.45)

# ==============================================================================
# 2. TIỀN XỬ LÝ ẢNH (PREPROCESSING)
# ==============================================================================
PREPROCESS_ENABLE_CLAHE = _env_bool("PREPROCESS_ENABLE_CLAHE", False)
PREPROCESS_CLAHE_CLIP_LIMIT = _env_float("PREPROCESS_CLAHE_CLIP_LIMIT", 2.0)
PREPROCESS_CLAHE_GRID_SIZE = _env_int("PREPROCESS_CLAHE_GRID_SIZE", 8)
PREPROCESS_GAMMA = _env_float("PREPROCESS_GAMMA", 1.0)
PREPROCESS_DENOISE_KERNEL = _env_int("PREPROCESS_DENOISE_KERNEL", 0)
PREPROCESS_AUTO_WB = _env_bool("PREPROCESS_AUTO_WB", False)
PREPROCESS_SHARPEN = _env_bool("PREPROCESS_SHARPEN", False)
PREPROCESS_ROI = _env_str("PREPROCESS_ROI", "")

# ==============================================================================
# 3. NỀN TẢNG & CAMERA
# ==============================================================================
FRAME_WIDTH = _env_int("FRAME_WIDTH", 640)
FRAME_HEIGHT = _env_int("FRAME_HEIGHT", 480)

PLATFORM = _resolve_platform(_env_str("PLATFORM", "auto"))
CAMERA_SOURCE = _env_str("CAMERA_SOURCE", "usb").lower()
WEBCAM_INDEX = _env_int("WEBCAM_INDEX", 0)
WEBCAM_FOURCC = _env_str("WEBCAM_FOURCC", "MJPG").upper()

USB_LOCK_EXPOSURE = _env_bool("USB_LOCK_EXPOSURE", False)
USB_EXPOSURE_TIME = _env_int("USB_EXPOSURE_TIME", 313)
USB_GAIN = _env_int("USB_GAIN", 32)
USB_GAMMA = _env_int("USB_GAMMA", 120)
USB_BACKLIGHT_COMPENSATION = _env_int("USB_BACKLIGHT_COMPENSATION", 1)

CAMERA_AUTOFOCUS = _env_bool("CAMERA_AUTOFOCUS", False)
CAMERA_LENS_POSITION = _env_float("CAMERA_LENS_POSITION", 2.5)
CAMERA_EXPOSURE_COMP = _env_float("CAMERA_EXPOSURE_COMP", -0.5)

CAMERA_FPS = _env_int("CAMERA_FPS", 30)
CAMERA_STALE_TIMEOUT = _env_float("CAMERA_STALE_TIMEOUT", 2.0)
FRAME_SKIP = _env_int("FRAME_SKIP", 2)

# ==============================================================================
# 4. XÁC NHẬN CẢNH BÁO & CHỐNG BÁO ĐỘNG GIẢ (CONFIRMATION & VOTING)
# ==============================================================================
HOLD_FIRE_TIME = _env_float("HOLD_FIRE_TIME", 1.5)

FIRE_CONFIRM_WINDOW_SECONDS = _env_float("FIRE_CONFIRM_WINDOW_SECONDS", 1.5)
FIRE_CONFIRM_MIN_RATIO = _env_float("FIRE_CONFIRM_MIN_RATIO", 0.6)
FIRE_CONFIRM_MIN_SAMPLES = _env_int("FIRE_CONFIRM_MIN_SAMPLES", 3)
FIRE_CONFIRMATION_FRAMES = _env_int("FIRE_CONFIRMATION_FRAMES", 2)

SMOKE_CONFIRMATION_FRAMES = _env_int("SMOKE_CONFIRMATION_FRAMES", 2)
SMOKE_CONFIRM_WINDOW_SECONDS = _env_float("SMOKE_CONFIRM_WINDOW_SECONDS", 2.0)
SMOKE_CONFIRM_MIN_RATIO = _env_float("SMOKE_CONFIRM_MIN_RATIO", 0.5)
SMOKE_CONFIRM_MIN_SAMPLES = _env_int("SMOKE_CONFIRM_MIN_SAMPLES", 2)

# ==============================================================================
# 5. ĐÈN CẢNH BÁO (LED) & CÒI BÁO ĐỘNG (BUZZER)
# ==============================================================================
LED_PIN = _env_int("LED_PIN", 27)
BUZZER_PIN = _env_int("BUZZER_PIN", 17)
BUZZER_TYPE = _env_str("BUZZER_TYPE", "passive").lower()
BUZZER_FREQUENCY = _env_int("BUZZER_FREQUENCY", 2000)
ALERT_DURATION = _env_float("ALERT_DURATION", 2.0)
ALERT_COOLDOWN = _env_float("ALERT_COOLDOWN", 5.0)

# ==============================================================================
# 6. LƯU ẢNH SNAPSHOT, HIỂN THỊ & WEB SERVER
# ==============================================================================
SAVE_SNAPSHOT = _env_bool("SAVE_SNAPSHOT", False)
SNAPSHOT_DIR = _env_str("SNAPSHOT_DIR", "data/snapshots")
SNAPSHOT_COOLDOWN = _env_float("SNAPSHOT_COOLDOWN", 2.0)

SHOW_DISPLAY = _env_bool("SHOW_DISPLAY", True)
DISPLAY_FPS = _env_int("DISPLAY_FPS", 15)
WINDOW_NAME = _env_str("WINDOW_NAME", "Hệ thống nhận diện lửa - IoT")

WEB_HOST = _env_str("WEB_HOST", "0.0.0.0")
WEB_PORT = _env_int("WEB_PORT", 5000)
WEB_STREAM_FPS = _env_int("WEB_STREAM_FPS", 12)
WEB_JPEG_QUALITY = _env_int("WEB_JPEG_QUALITY", 80)
CORS_ALLOWED_ORIGINS = _env_str("CORS_ALLOWED_ORIGINS", "")

# ==============================================================================
# 7. CƠ CẤU CHẤP HÀNH: SERVO & BƠM NƯỚC (ACTUATORS)
# ==============================================================================
SERVO_PIN = _env_int("SERVO_PIN", 18)
SERVO_MIN_ANGLE = _env_float("SERVO_MIN_ANGLE", 30.0)
SERVO_MAX_ANGLE = _env_float("SERVO_MAX_ANGLE", 150.0)
SERVO_CENTER_ANGLE = _env_float("SERVO_CENTER_ANGLE", 90.0)
SERVO_STEP_ANGLE = _env_float("SERVO_STEP_ANGLE", 15.0)
SERVO_MIN_PULSE_WIDTH = _env_float("SERVO_MIN_PULSE_WIDTH", 0.0005)
SERVO_MAX_PULSE_WIDTH = _env_float("SERVO_MAX_PULSE_WIDTH", 0.0024)
SERVO_SETTLE_SECONDS = _env_float("SERVO_SETTLE_SECONDS", 0.8)
SERVO_HOLD_POSITION = _env_bool("SERVO_HOLD_POSITION", True)
SERVO_PWM_BACKEND = _env_str("SERVO_PWM_BACKEND", "auto")

# Fixed webcam + two-axis nozzle. BCM18 = header pin12; BCM19 = header pin35.
NOZZLE_PAN_PIN = _env_int("NOZZLE_PAN_PIN", SERVO_PIN)
NOZZLE_TILT_PIN = _env_int("NOZZLE_TILT_PIN", 19)
NOZZLE_FLOOR_LENGTH_CM = _env_float("NOZZLE_FLOOR_LENGTH_CM", 43.0)
NOZZLE_FLOOR_WIDTH_CM = _env_float("NOZZLE_FLOOR_WIDTH_CM", 31.0)
NOZZLE_MECHANISM = _env_str("NOZZLE_MECHANISM", "yaw_pitch")
NOZZLE_ROTATION_DEG = _env_float("NOZZLE_ROTATION_DEG", 0.0)
NOZZLE_PAN_SIGN = _env_int("NOZZLE_PAN_SIGN", 1)
NOZZLE_TILT_SIGN = _env_int("NOZZLE_TILT_SIGN", 1)
NOZZLE_IMAGE_ASPECT = _env_float("NOZZLE_IMAGE_ASPECT", 4 / 3)
NOZZLE_IMAGE_CORNERS = json.loads(_env_str("NOZZLE_IMAGE_CORNERS", "[]"))
NOZZLE_ANCHOR_Y = _env_float("NOZZLE_ANCHOR_Y", 0.5)
NOZZLE_WATER_SAMPLES = json.loads(_env_str("NOZZLE_WATER_SAMPLES", "[]"))
NOZZLE_X_CM = _env_float("NOZZLE_X_CM", 21.5)
NOZZLE_Y_CM = _env_float("NOZZLE_Y_CM", 15.5)
NOZZLE_HEIGHT_CM = _env_float("NOZZLE_HEIGHT_CM", 29.0)
NOZZLE_CAMERA_OFFSET_X_CM = _env_float("NOZZLE_CAMERA_OFFSET_X_CM", 0.0)
NOZZLE_CAMERA_OFFSET_Y_CM = _env_float("NOZZLE_CAMERA_OFFSET_Y_CM", 0.0)
NOZZLE_CAMERA_HEIGHT_CM = _env_float("NOZZLE_CAMERA_HEIGHT_CM", 36.0)
NOZZLE_TARGET_HEIGHT_CM = _env_float("NOZZLE_TARGET_HEIGHT_CM", 0.0)
NOZZLE_PAN_MIN = _env_float("NOZZLE_PAN_MIN", 30.0)
NOZZLE_PAN_MAX = _env_float("NOZZLE_PAN_MAX", 150.0)
NOZZLE_PAN_ZERO = _env_float("NOZZLE_PAN_ZERO", 90.0)
NOZZLE_TILT_MIN = _env_float("NOZZLE_TILT_MIN", 30.0)
NOZZLE_TILT_MAX = _env_float("NOZZLE_TILT_MAX", 150.0)
NOZZLE_TILT_ZERO = _env_float("NOZZLE_TILT_ZERO", 90.0)
NOZZLE_HOLD_POSITION = _env_bool("NOZZLE_HOLD_POSITION", False)
NOZZLE_CALIBRATION_PATH = _env_str("NOZZLE_CALIBRATION_PATH", "data/nozzle_calibration.json")
NOZZLE_DRY_RUN = _env_bool("NOZZLE_DRY_RUN", True)
NOZZLE_BURST_SECONDS = _env_float("NOZZLE_BURST_SECONDS", 1.0)
NOZZLE_TARGET_TOLERANCE_CM = _env_float("NOZZLE_TARGET_TOLERANCE_CM", 3.0)
NOZZLE_RESULT_MAX_AGE = _env_float("NOZZLE_RESULT_MAX_AGE", 1.0)

PUMP_PIN = _env_int("PUMP_PIN", 23)
PUMP_ACTIVE_HIGH = _env_bool("PUMP_ACTIVE_HIGH", True)
PUMP_CONFIDENCE_THRESHOLD = _env_float("PUMP_CONFIDENCE_THRESHOLD", 0.35)
PUMP_CONFIRM_WINDOW_SECONDS = _env_float("PUMP_CONFIRM_WINDOW_SECONDS", 3.0)
PUMP_CONFIRM_MIN_RATIO = _env_float("PUMP_CONFIRM_MIN_RATIO", 0.7)
PUMP_CONFIRM_MIN_SAMPLES = _env_int("PUMP_CONFIRM_MIN_SAMPLES", 3)
PUMP_MAX_SECONDS = _env_float("PUMP_MAX_SECONDS", 5.0)
PUMP_COOLDOWN = _env_float("PUMP_COOLDOWN", 15.0)
PUMP_MAX_PER_MINUTE = _env_int("PUMP_MAX_PER_MINUTE", 4)

ACTUATOR_WATCHDOG_SECONDS = _env_float("ACTUATOR_WATCHDOG_SECONDS", 600.0)

# ==============================================================================
# 8. THÔNG BÁO TELEGRAM BOT
# ==============================================================================
TELEGRAM_ENABLED = _env_bool("TELEGRAM_ENABLED", True)
TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env_str("TELEGRAM_CHAT_ID", "")

TELEGRAM_FIRE_COOLDOWN = _env_float("TELEGRAM_FIRE_COOLDOWN", 30.0)
TELEGRAM_SMOKE_COOLDOWN = _env_float("TELEGRAM_SMOKE_COOLDOWN", 60.0)
TELEGRAM_TIMEOUT = _env_float("TELEGRAM_TIMEOUT", 10.0)
