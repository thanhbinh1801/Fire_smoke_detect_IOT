# HANDOFF - Tối ưu & Kiểm thử Hệ thống Nhận diện Lửa/Khói trên Raspberry Pi 4

## 1. Mục tiêu
Tối ưu hóa hiệu năng xử lý ảnh, độ chính xác nhận diện YOLOv8n (`320x320` ONNX), độ an toàn cơ cấu chấp hành (servo SG90, bơm R385, còi/LED) và triển khai kiểm thử thực tế trên Raspberry Pi 4 (`rasp@10.172.200.68`, Debian 13 Trixie 64-bit, Python 3.13).

## 2. Những việc đã hoàn thành & File đã sửa
- **Sửa Watchdog & Xác nhận theo cửa sổ thời gian (`confirmation.py`, `web_server.py`, `main.py`, `config.py`):** Bỏ `_touch_control()` khỏi `/api/status`, đặt `ACTUATOR_WATCHDOG_SECONDS = 600.0`, dùng `FireConfirmer` chung cho cảnh báo (1.5s) và bơm (3.0s), tạm dừng nhận diện khi servo đang quay (`servo.is_moving()`).
- **Tối ưu CPU & Độ nhạy nhận diện (`detector.py`, `camera.py`, `templates/index.html`, `display.py`):** Dùng `cv2.INTER_AREA` + `cv2.dnn.blobFromImage`, thêm xác nhận 2 bước ROI Zoom-in 1:1 (`320x320`) cho lửa nhỏ/xa (`0.22 <= conf < 0.40`), thêm `get_frame_if_new()`, khôi phục độ sáng webcam USB (`auto_exposure=3, gain=32, gamma=120`) và xóa toàn bộ tính năng đảo màu R-B.
- **Sửa điều khiển Servo (`actuators.py`):** Vá lỗi làm tròn số nguyên duty cycle của `gpiozero`/`lgpio` (`_patch_lgpio_pwm_pin`), tăng `SERVO_STEP_ANGLE = 15.0` và tự `detach()` sau `0.8s` để chống rung.
- **Đo hiệu năng & Kiểm thử (`benchmark.py`, `requirements-dev.txt`, `tests/`):** Tạo bộ 10 unit test (`pytest`) và benchmark trên cả laptop lẫn Pi 4 (7.73 FPS AI với webcam USB, `47.2°C`, `throttled=0x0`). Đã push lên `origin/main` (`97e9fd9`) và `git pull` trên Pi.

## 3. Phát hiện quan trọng trên Raspberry Pi 4
- **`gpiozero` + `lgpio` (`PWMSoftwareFallback`) trên Debian 13:** `LGPIOPin._set_state` ép `int(value * 100)` khiến góc `90°` (`7.25%`) và `100°` (`7.78%`) bị cắt thành `7%` làm servo không nhúc nhích. Đã quyết định giữ `lgpio` nhưng patch `_set_state` sang số thực `round(float(value) * 100.0, 4)` kết hợp `detach()` sau `0.8s` (không phụ thuộc daemon `pigpiod`).
- **Độ sáng Webcam USB (`/dev/video0`):** Webcam hỗ trợ `MJPG 640x480@30fps`, nhưng nếu `gain=0` hoặc khóa `exposure=200` ảnh sẽ rất tối; cần đặt `gain=32, exposure=313` trước khi bật `auto_exposure=3`.
- **Trạng thái chân GPIO thực tế (`pinctrl`):** Phát hiện tải cắm tại `GPIO 3` (Pin 5), `GPIO 13` (Pin 33), `GPIO 17` (Pin 11 - Buzzer), `GPIO 18` (Pin 12), `GPIO 27` (Pin 13 - LED); trong khi `GPIO 23` (Pin 16 - Relay bơm) đang để trống.

## 4. Việc còn dở & Bước tiếp theo
1. Kiểm tra lại dây vật lý trên Pi: xác nhận dây tín hiệu servo cắm đúng **Pin 12 (`GPIO BCM 18`)**, dây điều khiển relay cắm đúng **Pin 16 (`GPIO BCM 23`)** (hoặc cập nhật `SERVO_PIN`/`PUMP_PIN` trong `config.py` theo chân thực tế đang cắm).
2. Chạy `web_server.py` trên Pi, mở dashboard kiểm tra quay servo Trái/Center/Phải, bật/tắt relay và độ sáng webcam.
3. Thử nghiệm thực tế với ngọn lửa ở gần/xa và vật gây nhiễu màu đỏ/cam để tinh chỉnh `CONFIDENCE_THRESHOLD` (`0.40`) và `ROI_CANDIDATE_THRESHOLD` (`0.22`).

## 5. Lệnh chạy & Kiểm tra
```bash
# SSH vào Pi (đã cài sẵn SSH key)
ssh rasp@10.172.200.68

# Chạy unit test và benchmark trên Pi
cd ~/Fire_smoke_detect_IOT
./venv/bin/python -m pytest -v
./venv/bin/python benchmark.py --source 0 --frames 100 --threads 3

# Chạy Web Dashboard (truy cập http://10.172.200.68:5000)
./venv/bin/python web_server.py
```
