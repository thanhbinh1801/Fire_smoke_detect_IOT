# config.py
"""
Cấu hình hệ thống nhận diện khói & lửa
Hỗ trợ cả môi trường Laptop (để test) và Raspberry Pi 4 (thực tế).
"""

# Đường dẫn tới model weights (ONNX tối ưu cho Raspberry Pi)
MODEL_PATH = "models/fire_smoke_yolov8n.onnx"

# Ngưỡng độ tin cậy để kích hoạt cảnh báo (0.0 - 1.0)
CONFIDENCE_THRESHOLD = 0.45
IOU_THRESHOLD = 0.45

# Độ phân giải camera dùng cho inference (640x480 giúp cân bằng giữa độ chính xác và tốc độ trên Pi 4)
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# Nền tảng đang chạy: 
# "laptop" (webcam qua OpenCV, buzzer & led giả lập qua console)
# "pi" (camera CSI qua Picamera2, passive buzzer & đèn LED thật qua GPIO)
# PLATFORM = "laptop"
PLATFORM = "pi"

# Webcam index khi chạy test trên laptop (0 = webcam mặc định)
WEBCAM_INDEX = 0

# --- CẤU HÌNH CAMERA (TỐI ƯU CHO ARDUCAM IMX519) ---
# Tắt Continuous AF và KHÓA NÉT CỐ ĐỊNH (tránh săn nét làm mờ vân lửa khi nhìn vào điện thoại)
CAMERA_AUTOFOCUS = False

# Vị trí tiêu cự khóa cứng cho IMX519 (dioptres):
# 2.0 dioptres tương đương cự ly lấy nét ~50cm (khoảng cách vàng để nhận diện ngọn lửa rõ nét)
CAMERA_LENS_POSITION = 2.0

# Bù trừ phơi sáng (Exposure Value) cho IMX519 (-0.5 giúp giảm chói lóa từ ngọn lửa/màn hình điện thoại)
CAMERA_EXPOSURE_COMP = -0.5

# Đảo kênh màu R-B (False = giữ nguyên khung hình gốc hiển thị đỏ chuẩn, True = đảo R-B). Có thể bấm 'c' khi đang chạy.
CAMERA_SWAP_RB = False

# Tốc độ khung hình mong muốn cho camera (30 FPS)
CAMERA_FPS = 30

# --- CẤU HÌNH TỐI ƯU HIỆU NĂNG & ĐỘ CHÍNH XÁC (FRAME-SKIPPING & VOTING) ---
# Tỷ lệ Frame-Skip: 2 = Chạy AI ở các frame chẵn (0, 2, 4,...), frame lẻ dùng lại box trước
# Giúp màn hình camera đạt 20 - 25 FPS mượt mà và giảm 50% tải CPU cho Raspberry Pi 4!
FRAME_SKIP = 2

# Số frame phát hiện lửa liên tiếp trước khi kích hoạt còi và đèn (lọc 100% báo động giả)
CONSECUTIVE_FIRE_FRAMES = 2

# Số frame duy trì đèn sáng sau khi ngọn lửa bị chớp tắt (tránh đèn bị nhấp nháy gián đoạn)
HOLD_FIRE_FRAMES = 5

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
SHOW_DISPLAY = True
WINDOW_NAME = "Fire & Smoke Detector - IoT System"
