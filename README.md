# Nhận diện lửa chạy local trên Raspberry Pi

Ứng dụng dùng Picamera2 để đọc camera CSI, chạy model YOLOv8 ONNX và hiển thị kết quả trực tiếp trên màn hình kết nối với Raspberry Pi bằng cửa sổ OpenCV. Flask và dashboard web đã được loại bỏ.

## Yêu cầu

- Raspberry Pi 4 chạy Raspberry Pi OS 64-bit có giao diện Desktop.
- Camera CSI, cấu hình hiện tại dành cho Arducam IMX519.
- Màn hình kết nối trực tiếp với Raspberry Pi.
- Tùy chọn: LED tại GPIO 27 và passive buzzer tại GPIO 17.

Ứng dụng cần chạy trong phiên Desktop của Pi. Không chạy bằng SSH thuần hoặc service không có display vì `cv2.imshow` cần môi trường đồ họa.

## Cài đặt

Mở Terminal ngay trên Raspberry Pi:

```bash
cd ~/nhan_dien_chay
sudo apt update
sudo apt install -y python3-picamera2 python3-gpiozero python3-opencv python3-venv libgl1 libglib2.0-0
python3 -m venv venv --system-site-packages
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Kiểm tra camera trước khi chạy:

```bash
rpicam-hello -t 3000
```

## Chạy local

Trong Terminal thuộc phiên Desktop của Raspberry Pi:

```bash
cd ~/nhan_dien_chay
source venv/bin/activate
python main.py
```

Chương trình sẽ mở cửa sổ `Fire & Smoke Detector - IoT System`; không khởi động web server và không cần truy cập địa chỉ IP.

Phím điều khiển:

- `q` hoặc `Esc`: thoát.
- `c`: đảo kênh đỏ/xanh nếu màu camera bị sai.
- `f`: kích hoạt lại autofocus.
- `[` / `]`: chỉnh tiêu cự xa/gần thủ công.

## Cấu hình

Thiết lập mặc định trong `config.py`:

```python
PLATFORM = "pi"
SHOW_DISPLAY = True
CAMERA_AUTOFOCUS = False
CAMERA_LENS_POSITION = 2.5
```

Các tùy chọn thường dùng:

- `CAMERA_LENS_POSITION`: tiêu cự thủ công của IMX519.
- `CAMERA_AUTOFOCUS = True`: bật autofocus nếu driver hỗ trợ.
- `CONFIDENCE_THRESHOLD`: ngưỡng nhận diện lửa.
- `SAVE_SNAPSHOT = True`: lưu ảnh cảnh báo vào `data/snapshots`.
- `LED_PIN` và `BUZZER_PIN`: chân GPIO theo chuẩn BCM.

## Lỗi thường gặp

### Không mở được cửa sổ

Hãy chạy lệnh từ Terminal trong Raspberry Pi Desktop. Nếu đang SSH, đăng nhập trực tiếp vào Desktop của Pi rồi chạy lại.

### Không tìm thấy Picamera2

Đảm bảo môi trường ảo được tạo với `--system-site-packages`:

```bash
deactivate
rm -rf venv
python3 -m venv venv --system-site-packages
```

### Camera không trả hình

Đóng các chương trình khác đang dùng camera, chạy lại `rpicam-hello`, sau đó kiểm tra cáp CSI và driver IMX519.

## Cấu trúc chính

- `main.py`: vòng lặp ứng dụng local.
- `camera.py`: Picamera2 và luồng đọc camera.
- `detector.py`: suy luận ONNX bất đồng bộ.
- `display.py`: overlay và cửa sổ OpenCV.
- `alert.py`: LED và buzzer GPIO.
- `config.py`: cấu hình Raspberry Pi.
