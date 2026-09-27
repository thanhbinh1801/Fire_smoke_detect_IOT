# config.py
"""
Cấu hình hệ thống nhận diện khói & lửa
Hỗ trợ cả môi trường Laptop (để test) và Raspberry Pi 4 (thực tế).
"""

# Đường dẫn tới model weights (ONNX tối ưu cho Raspberry Pi)
MODEL_PATH = "models/fire_smoke_yolov8n.onnx"

# Ngưỡng độ tin cậy để kích hoạt cảnh báo (0.0 - 1.0)
# Đặt 0.3 giúp phát hiện nhạy hơn khi quay qua màn hình điện thoại hoặc điều kiện ánh sáng yếu
CONFIDENCE_THRESHOLD = 0.3
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
# Tự động lấy nét liên tục (Continuous Autofocus cho Arducam IMX519)
CAMERA_AUTOFOCUS = True

# Sửa lỗi đảo màu của Picamera2 (False: giữ nguyên RGB888 của Picamera2 chuẩn xác)
CAMERA_SWAP_RB = False

# Tốc độ khung hình mong muốn cho camera
CAMERA_FPS = 30

# Chế độ chạy AI: False = Đồng bộ tuyệt đối (Zero-Latency).
# Di chuyển ngọn lửa đến đâu, hộp bounding box dính chặt 100% đến đó, không bao giờ bị delay vẽ lại vị trí cũ!
ASYNC_DETECTION = False

# --- CẤU HÌNH ĐÈN CẢNH BÁO LỬA (LED) ---
# Chân BCM GPIO nối đèn LED cảnh báo lửa (BCM 27 = Physical Pin 13)
# Đèn chỉ sáng khi nhận diện được lửa trong khung hình, hết lửa tắt ngay lập tức
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
