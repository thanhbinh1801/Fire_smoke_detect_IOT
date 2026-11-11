# config.py
"""
Cấu hình hệ thống nhận diện khói & lửa
Hỗ trợ cả môi trường Laptop (để test) và Raspberry Pi 4 (thực tế).
"""

# Đường dẫn tới model weights (ONNX tối ưu cho Raspberry Pi)
MODEL_PATH = "models/fire_smoke_yolov8n.onnx"

# Ngưỡng độ tin cậy để kích hoạt cảnh báo (0.0 - 1.0)
CONFIDENCE_THRESHOLD = 0.40
IOU_THRESHOLD = 0.45
ORT_INTRA_OP_THREADS = 3

ROI_ZOOM_ENABLED = True
ROI_CANDIDATE_THRESHOLD = 0.22
ROI_MAX_BOX_RATIO = 0.45

# Độ phân giải camera dùng cho inference (640x480 giúp cân bằng giữa độ chính xác và tốc độ trên Pi 4)
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# Nền tảng đang chạy: 
# "laptop" (webcam qua OpenCV, buzzer & led giả lập qua console)
# "pi" (GPIO thật; camera chọn qua CAMERA_SOURCE)
PLATFORM = "pi"

# Nguồn camera: "usb" (webcam USB qua OpenCV) hoặc "csi" (Picamera2).
# Chạy trên Pi với webcam USB thì giữ PLATFORM = "pi" và CAMERA_SOURCE = "usb".
CAMERA_SOURCE = "usb"

# Webcam index khi chạy test trên laptop (0 = webcam mặc định)
WEBCAM_INDEX = 0

# Định dạng ưu tiên cho webcam USB. MJPG cần thiết để đạt 30 FPS ở 640x480
# trên Raspberry Pi; nếu camera không hỗ trợ, OpenCV sẽ tự fallback.
WEBCAM_FOURCC = "MJPG"
USB_LOCK_EXPOSURE = False
USB_EXPOSURE_TIME = 300
USB_BACKLIGHT_COMPENSATION = 1

# --- CẤU HÌNH CAMERA (TỐI ƯU CHO ARDUCAM IMX519) ---
# Bật lấy nét tự động liên tục (Continuous AF: AfMode=2)
# LƯU Ý: IMX519 trên Pi OS cần IPA algorithm riêng.
# Nếu log báo "Could not set AF_MODE - no AF algorithm" thì đặt False
# và dùng CAMERA_LENS_POSITION để lấy nét thủ công.
CAMERA_AUTOFOCUS = False

# Vị trí tiêu cự thủ công dự phòng khi tắt AF (dioptres)
# Công thức: LensPosition = 1 / khoảng_cách_mét
#   0.0 = vô cực (xa > 3m)
#   0.5 = ~2m
#   1.0 = ~1m
#   2.0 = ~50cm  ← thử nếu vật ở ~50cm
#   2.5 = ~40cm  ← thử nếu vật ở ~40cm (đang dùng)
#   4.0 = ~25cm
#   8.0 = ~12cm (rất gần)
CAMERA_LENS_POSITION = 2.5

# Bù trừ phơi sáng (Exposure Value) cho IMX519 (-0.5 giúp giảm chói lóa từ ngọn lửa/màn hình điện thoại)
CAMERA_EXPOSURE_COMP = -0.5

# Tốc độ khung hình mong muốn cho camera (30 FPS)
CAMERA_FPS = 30
CAMERA_STALE_TIMEOUT = 2.0

# --- CẤU HÌNH TỐI ƯU HIỆU NĂNG & ĐỘ CHÍNH XÁC (ASYNC WORKER & VOTING) ---
# Tỷ lệ Frame-Skip dùng cho luồng đồng bộ dự phòng (khi không chạy async)
FRAME_SKIP = 2

# Thời gian duy trì đèn LED sáng (giây) sau khi ngọn lửa bị chớp tắt (tránh đèn bị nhấp nháy gián đoạn)
HOLD_FIRE_TIME = 1.5

# --- CẤU HÌNH ĐÈN CẢNH BÁO LỬA (LED) ---
# Chân BCM GPIO nối đèn LED cảnh báo lửa (BCM 27 = Physical Pin 13)
LED_PIN = 27

# --- CẤU HÌNH CÒI BUZZER ---
# Chân BCM GPIO nối còi buzzer trên Pi (BCM 17 = Physical Pin 11)
BUZZER_PIN = 17

# Loại còi: "passive" (cần xung PWM) hoặc "active" (cấp mức HIGH tự kêu)
BUZZER_TYPE = "passive"

# Tần số phát âm cho Passive Buzzer (Hz) - 2000Hz đến 2500Hz là dải còi kêu to và đanh nhất
BUZZER_FREQUENCY = 2000

# Thời gian còi kêu mỗi lần cảnh báo (giây)
ALERT_DURATION = 2.0

# Thời gian tối thiểu giữa 2 lần cảnh báo liên tiếp (cooldown, giây)
ALERT_COOLDOWN = 5.0

# --- LƯU ẢNH SNAPSHOT ---
# Có lưu ảnh lúc phát hiện không
SAVE_SNAPSHOT = False
SNAPSHOT_DIR = "data/snapshots"

# --- HIỂN THỊ MÀN HÌNH ---
# Hiện cửa sổ video (cv2.imshow). Đặt True để hiện màn hình camera, đặt False nếu chạy headless (không màn hình)
# Hiển thị trực tiếp trên màn hình Raspberry Pi, không dùng web server/Flask.
SHOW_DISPLAY = True
DISPLAY_FPS = 15
WINDOW_NAME = "Hệ thống nhận diện lửa - IoT"

WEB_HOST = "0.0.0.0"
WEB_PORT = 5000
WEB_STREAM_FPS = 12

FIRE_CONFIRM_WINDOW_SECONDS = 1.5
FIRE_CONFIRM_MIN_RATIO = 0.6
FIRE_CONFIRM_MIN_SAMPLES = 4

SERVO_PIN = 18
SERVO_MIN_ANGLE = 30.0
SERVO_MAX_ANGLE = 150.0
SERVO_CENTER_ANGLE = 90.0
SERVO_STEP_ANGLE = 15.0
SERVO_MIN_PULSE_WIDTH = 0.0005
SERVO_MAX_PULSE_WIDTH = 0.0024
SERVO_SETTLE_SECONDS = 0.8

PUMP_PIN = 23
PUMP_ACTIVE_HIGH = True

PUMP_CONFIDENCE_THRESHOLD = 0.60
PUMP_CONFIRM_WINDOW_SECONDS = 3.0
PUMP_CONFIRM_MIN_RATIO = 0.7
PUMP_CONFIRM_MIN_SAMPLES = 8
PUMP_MAX_SECONDS = 5.0
PUMP_COOLDOWN = 15.0
PUMP_MAX_PER_MINUTE = 4

ACTUATOR_WATCHDOG_SECONDS = 600.0

# Chỉ bật cảnh báo sau số lần suy luận liên tiếp có phát hiện lửa / khói.
FIRE_CONFIRMATION_FRAMES = 2
SMOKE_CONFIRMATION_FRAMES = 2

# --- CẤU HÌNH THÔNG BÁO TELEGRAM ---
# Có thể điền trực tiếp bên dưới hoặc đặt qua biến môi trường TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = "9161312599:AAGqYxyHsiSVrW8bX-4nF6Kyy3Cx5z56ZGs"  # Ví dụ: "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
TELEGRAM_CHAT_ID = "5698274871"    # Ví dụ: "987654321" hoặc "-100123456789" (nhóm)

# Thời gian giãn cách tối thiểu (giây) giữa 2 lần gửi thông báo Telegram cho từng loại
TELEGRAM_FIRE_COOLDOWN = 30.0
TELEGRAM_SMOKE_COOLDOWN = 60.0
TELEGRAM_TIMEOUT = 10.0
