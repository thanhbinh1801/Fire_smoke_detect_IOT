# config.py
"""
Cấu hình hệ thống nhận diện khói & lửa
Hỗ trợ cả môi trường Laptop (để test) và Raspberry Pi 4 (thực tế).
"""

# Đường dẫn tới model weights (ONNX tối ưu cho Raspberry Pi)
MODEL_PATH = "models/fire_smoke_yolov8n.onnx"

# Ngưỡng độ tin cậy để kích hoạt cảnh báo (0.0 - 1.0)
CONFIDENCE_THRESHOLD = 0.30
IOU_THRESHOLD = 0.45

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

# Đảo kênh màu R-B (False = mặc định BGR chuẩn OpenCV). Có thể bấm 'c' khi đang chạy.
CAMERA_SWAP_RB = False

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
WINDOW_NAME = "Hệ thống nhận diện lửa - IoT"

# --- WEB DASHBOARD ---
# Chỉ mở ra mạng LAN tin cậy; không forward cổng này trực tiếp ra Internet.
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000
WEB_STREAM_FPS = 12

# Chỉ bật cảnh báo sau số lần suy luận liên tiếp có phát hiện lửa.
FIRE_CONFIRMATION_FRAMES = 2

# --- SERVO PAN CAMERA (SG90) ---
# Chân BCM nối dây signal của servo (GPIO 18 hỗ trợ hardware PWM).
# Servo PHẢI được cấp nguồn 5V riêng, chỉ nối signal và GND chung về Pi.
SERVO_PIN = 18
SERVO_MIN_ANGLE = 30.0
SERVO_MAX_ANGLE = 150.0
SERVO_CENTER_ANGLE = 90.0
SERVO_STEP_ANGLE = 10.0
# Độ rộng xung SG90. Nếu servo rung/kẹt ở hai biên, đổi về 0.001 / 0.002.
SERVO_MIN_PULSE_WIDTH = 0.0005
SERVO_MAX_PULSE_WIDTH = 0.0024

# --- BƠM NƯỚC R385 QUA RELAY ---
# Chân BCM nối chân IN của relay module (SRD-05VDC-SL-C).
PUMP_PIN = 23
# True nếu relay kích mức HIGH, False nếu relay kích mức LOW.
# Board "High/Low Level Trigger" có jumper chọn mức; đặt cho khớp.
PUMP_ACTIVE_HIGH = True

# Chỉ phun khi phát hiện lửa đạt ngưỡng tin cậy riêng (cao hơn ngưỡng hiển thị).
PUMP_CONFIDENCE_THRESHOLD = 0.60
# Số kết quả suy luận liên tiếp cần xác nhận trước khi phun.
PUMP_CONFIRM_FRAMES = 3
# Thời gian phun tối đa mỗi lần (giây).
PUMP_MAX_SECONDS = 5.0
# Thời gian chờ giữa hai lần phun (giây).
PUMP_COOLDOWN = 15.0
# Giới hạn số lần phun trong 60 giây.
PUMP_MAX_PER_MINUTE = 4

# Nếu không có thao tác điều khiển nào từ web trong khoảng này (giây),
# hệ thống tự disarm chế độ phun tự động. Bơm vẫn tự tắt theo PUMP_MAX_SECONDS.
ACTUATOR_WATCHDOG_SECONDS = 30.0
