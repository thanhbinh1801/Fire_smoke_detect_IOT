# 🔥 HỆ THỐNG IOT CAMERA AI NHẬN DIỆN KHÓI & LỬA (RASPBERRY PI 4)

Dự án giám sát và cảnh báo khói lửa thông minh theo thời gian thực sử dụng **Raspberry Pi 4**, còi báo động **Passive Buzzer** và camera (mẫu code và hướng dẫn này đang được cấu hình thực tế cho camera **Arducam IMX519**).

---

## 📌 1. Yêu cầu phần cứng & Sơ đồ đấu dây

### Phần cứng:
- **Board điều khiển:** Raspberry Pi 4 (khuyên dùng bản 4GB RAM trở lên).
- **Hệ điều hành:** Raspberry Pi OS 64-bit (Debian Bookworm).
- **Camera:** 
  - Trong dự án này, tác giả sử dụng camera **Arducam IMX519** (kết nối cổng CSI).
  - *Lưu ý:* Nếu bạn sử dụng loại camera khác (như Raspberry Pi Camera Module v2/v3 chính hãng, camera USB, v.v.), bạn chỉ cần cài driver/cấu hình phù hợp với loại camera đó sao cho hệ thống (`libcamera` / `Picamera2`) nhận diện được là có thể sử dụng code bình thường.
- **Còi báo:** Passive Buzzer (cần xung PWM).

### Sơ đồ nối chân GPIO cho Passive Buzzer:

| Chân Buzzer | Tên chân Raspberry Pi | Vị trí Pin vật lý | Ghi chú |
| :--- | :--- | :--- | :--- |
| **I/O / Signal (+)** | **GPIO 17 (BCM)** | **Pin 11** | Chân cấp xung PWM 2000Hz |
| **GND (-)** | **Ground (GND)** | **Pin 6** (hoặc Pin 9, 14) | Nối đất |
| **VCC** *(nếu module 3 chân)* | **3.3V / 5V** | **Pin 1 hoặc Pin 2** | Nguồn nuôi mạch |

---

## 🚀 2. Hướng dẫn cài đặt trên Raspberry Pi (Từng bước)

Mở Terminal trên Raspberry Pi (qua SSH hoặc trực tiếp trên màn hình Pi) và thực hiện tuần tự:

### Bước 2.1: Cấu hình Driver Camera

- **Trường hợp dùng Arducam IMX519 (giống cấu hình bài viết này):**  
  Arducam IMX519 cần nạp kernel driver riêng từ Arducam. Chạy các lệnh sau:
  ```bash
  # Tải script cài đặt tự động từ Arducam
  wget -O install_pivariety_pkgs.sh https://gist.githubusercontent.com/Gordon999/eb1576778f244198425ec88a80d46dd1/raw/install_pivariety_pkgs.sh
  chmod +x install_pivariety_pkgs.sh

  # Cài driver IMX519 cho kernel
  ./install_pivariety_pkgs.sh -p imx519_kernel_driver

  # Khởi động lại Pi để áp dụng driver
  sudo reboot
  ```

- **Trường hợp dùng camera khác (Pi Cam Module v2 / v3 / HQ Camera):**  
  Raspberry Pi OS Bookworm đã tích hợp sẵn driver trong nhân kernel, bạn **không cần chạy script của Arducam**, có thể bỏ qua bước cài trên.

> **Kiểm tra camera sau khi kết nối:**
> ```bash
> rpicam-hello -t 3000
> ```
> Nếu camera mở được khung hình trong 3 giây (hoặc không báo lỗi thiết bị), nghĩa là camera đã sẵn sàng.

---

### Bước 2.2: Chuẩn bị thư mục code & Model
Di chuyển vào thư mục dự án trên Pi (ví dụ bạn lưu tại `~/nhan_dien_chay`):

```bash
cd ~/nhan_dien_chay
```

Kiểm tra đảm bảo file model weights đã có trong thư mục `models/`:
```bash
ls -lh models/fire_smoke_yolov8n.pt
# File này có dung lượng khoảng ~6.3 MB
```

---

### Bước 2.3: Cài đặt thư viện hệ thống & Môi trường Python

Chỉ cần copy và chạy nguyên khối lệnh sau (tự động cài đặt đầy đủ từ `picamera2`, `gpiozero` hệ thống đến các gói AI):

```bash
# 1. Cài đặt thư viện phần cứng hệ thống (BẮT BUỘC để dùng camera CSI và còi GPIO)
sudo apt update
sudo apt install -y python3-picamera2 python3-gpiozero python3-pip python3-venv libgl1 libglib2.0-0

# 2. Tạo môi trường ảo venv (BẮT BUỘC có cờ --system-site-packages để venv nhận picamera2 & gpiozero)
python3 -m venv venv --system-site-packages

# 3. Kích hoạt venv
source venv/bin/activate

# 4. Cài đặt các thư viện AI & YOLO từ requirements.txt
pip install -r requirements.txt --default-timeout=1000
```

---

## ⚙️ 3. Cấu hình trước khi chạy (`config.py`)

Mở file `config.py` trên Raspberry Pi:
```bash
nano config.py
```

Kiểm tra và thiết lập các thông số sau:
- **`PLATFORM = "pi"`** *(Bắt buộc đổi sang "pi" để dùng Picamera2 và GPIO thật)*
- **`SHOW_DISPLAY`**:
  - Đặt `True`: Nếu Pi đang cắm cáp HDMI vào màn hình.
  - Đặt `False`: Nếu bạn điều khiển Pi qua SSH từ xa (không có màn hình ngoài).
- **`SAVE_SNAPSHOT = True`**: Lưu ảnh lúc phát hiện cháy vào thư mục `data/snapshots/`.
- **`BUZZER_PIN = 17`**: Khớp với chân GPIO BCM đã cắm dây.
- **`BUZZER_TYPE = "passive"`**: Chế độ phát xung PWM cho còi chip thụ động.

*(Nhấn `Ctrl + O` -> `Enter` để lưu, `Ctrl + X` để thoát nano)*.

---

## ▶️ 4. Khởi chạy hệ thống

Khi đang ở trong thư mục dự án và venv đã kích hoạt:

```bash
python main.py
```

- **Khi an toàn:** Hệ thống liên tục quét qua camera Arducam.
- **Khi phát hiện khói hoặc lửa:**
  - Còi Passive Buzzer kêu cảnh báo ngắt quãng (bíp bíp bíp) trên chân GPIO 17 trong 2 giây.
  - Luồng cảnh báo chạy ngầm (non-blocking) nên hình ảnh camera và nhận diện vẫn mượt mà không bị khựng.
  - Console in chi tiết nhãn và độ tin cậy: `[CANH BAO] Phat hien: ['fire'] | Confidence: [0.82]`.
- **Dừng chương trình:** Nhấn `Ctrl + C` (hoặc phím `q` nếu có bật màn hình hiển thị).

---

## 🔄 5. (Tùy chọn) Cấu hình tự động chạy khi bật nguồn Pi (Systemd Service)

Để hệ thống hoạt động như một thiết bị IoT độc lập (chỉ cần cắm nguồn là tự chạy không cần mở máy tính gõ lệnh):

1. Tạo file service:
```bash
sudo nano /etc/systemd/system/fire_detector.service
```

2. Dán nội dung sau vào (thay `pi` bằng username của bạn nếu khác):
```ini
[Unit]
Description=IoT Fire & Smoke Detector Service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/nhan_dien_chay
ExecStart=/home/pi/nhan_dien_chay/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

3. Kích hoạt service:
```bash
# Nạp lại cấu hình systemd
sudo systemctl daemon-reload

# Bật tự động khởi động cùng hệ thống
sudo systemctl enable fire_detector.service

# Khởi chạy service ngay lập tức
sudo systemctl start fire_detector.service

# Kiểm tra trạng thái hoạt động
sudo systemctl status fire_detector.service
```

> Để dừng service: `sudo systemctl stop fire_detector.service`
