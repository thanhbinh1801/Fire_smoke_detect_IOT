# Hệ thống giám sát lửa/khói IoT

Ứng dụng chạy webcam USB, suy luận YOLO ONNX và điều khiển cảnh báo/bơm nước trên Raspberry Pi. Giao diện web xem video trực tiếp, trạng thái, FPS, điều khiển servo pan camera và bơm nước. Luồng camera và AI chạy nền, trình duyệt nhận một luồng MJPEG đã mã hóa dùng chung thay vì chạy suy luận cho từng người xem.

## Phần cứng

- Raspberry Pi 4 (64-bit) với Raspberry Pi OS Bookworm.
- Webcam USB cắm cổng USB 3.0 (cổng xanh) để đủ băng thông.
- Servo SG90 pan camera.
- Bơm mini R385 qua relay module 5V (SRD-05VDC-SL-C).
- Tùy chọn: LED GPIO BCM 27 và passive buzzer BCM 17.
- Nguồn: pin 9V cho bơm, nguồn 5V riêng cho servo/relay (adapter hoặc power bank), nguồn riêng cho Pi.

> **Cảnh báo:** pin 9V PP3 chỉ phù hợp demo ngắn. Bơm R385 kéo ~0.5–0.8A làm pin 9V tụt áp nhanh, bơm yếu và relay có thể nhả liên tục. Khi demo/bảo vệ nên dùng adapter 9–12V 2A hoặc pack 6xAA/3S 18650. Không bao giờ đấu trực tiếp 9V vào Pi.

## Nối dây

### 1. Bơm R385 qua relay

```
Pin 9V (+) ── cầu chì 2A ── COM1 (relay)
NO1 (relay) ── Bơm (+)
Bơm (-) ── Pin 9V (-)
Diode 1N4007: cathode (vạch) → Bơm (+), anode → Bơm (-)
```

- Dùng tiếp điểm **COM1 + NO1** (thường mở): bơm chỉ chạy khi relay đóng.
- **Bắt buộc diode flyback** song song hai đầu bơm để bảo vệ tiếp điểm relay.
- Nên thêm công tắc nguồn 9V và cầu chì 2A trên đường dương.

### 2. Relay module → Raspberry Pi

```
Relay VCC ── 5V (adapter 5V hoặc chân 5V của Pi)
Relay GND ── GND chung
Relay IN1 ── GPIO BCM 23 (physical pin 16)
```

- Board có jumper **High/Low Level Trigger**: đặt mức HIGH cho khớp `PUMP_ACTIVE_HIGH = True` trong `config.py`.
- Nếu relay đóng ngay khi cấp điện hoặc trạng thái ngược, đổi `PUMP_ACTIVE_HIGH = False`.
- Nếu relay đóng trước khi chương trình chạy (GPIO còn floating), thêm điện trở **10kΩ từ IN1 xuống GND** để khóa bơm ở trạng thái tắt lúc khởi động.
- Relay trong ảnh dùng cuộn 5V; **không cấp 9V vào VCC relay**.

### 3. Servo SG90 → Raspberry Pi

```
Servo dây cam (signal) ── GPIO BCM 18 (physical pin 12)
Servo dây đỏ (V+)     ── 5V nguồn ngoài
Servo dây nâu (GND)   ── GND chung
Tụ 470–1000µF          ── giữa 5V và GND, đặt gần servo
```

- **Không cấp servo từ chân 5V của Pi** nếu muốn tránh sụt áp/reboot. Chỉ nối signal và GND về Pi.
- Nếu servo rung hoặc kẹt ở hai biên, chỉnh `SERVO_MIN_PULSE_WIDTH` / `SERVO_MAX_PULSE_WIDTH` trong `config.py` về `0.001` / `0.002`.
- Giới hạn mềm mặc định 30°–150° để không xoắn dây USB. Gắn bracket sao cho trọng tâm webcam nằm trên trục quay.

### 4. Webcam USB

- Cắm vào cổng **USB 3.0** trên Pi.
- Code tự bật **MJPG** để đạt FPS cao ở 640x480. Không cần cấu hình thêm.
- Cố định dây USB bằng strain-relief gần camera để lực xoay không truyền vào connector.

### 5. GND chung

Tất cả nguồn phải nối **GND chung**: pin 9V, adapter 5V cho servo/relay, và Raspberry Pi. Thiếu GND chung relay/servo sẽ chập chờn hoặc không hoạt động.

## Cài đặt Raspberry Pi

```bash
cd ~/Fire_smoke_detect_IOT
sudo apt update
sudo apt install -y python3-gpiozero python3-opencv python3-venv fonts-dejavu-core libgl1 libglib2.0-0 v4l-utils
python3 -m venv venv --system-site-packages
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Kiểm tra webcam:

```bash
v4l2-ctl --list-devices
v4l2-ctl --list-formats-ext -d /dev/video0
```

## Cấu hình

Các thiết lập chính trong `config.py`:

- `PLATFORM = "pi"`, `CAMERA_SOURCE = "usb"`: Pi dùng webcam USB.
- `WEBCAM_INDEX = 0`: đổi nếu webcam không phải `/dev/video0`.
- `CONFIDENCE_THRESHOLD = 0.40`: ngưỡng hiển thị/cảnh báo chung.
- `FIRE_CONFIRM_WINDOW_SECONDS = 1.5`, `FIRE_CONFIRM_MIN_RATIO = 0.6`, `FIRE_CONFIRM_MIN_SAMPLES = 4`: xác nhận lửa theo cửa sổ thời gian cho còi/LED.
- `PUMP_CONFIDENCE_THRESHOLD = 0.60`: ngưỡng riêng để phun nước (cao hơn để giảm báo động giả).
- `PUMP_CONFIRM_WINDOW_SECONDS = 3.0`, `PUMP_CONFIRM_MIN_RATIO = 0.7`, `PUMP_CONFIRM_MIN_SAMPLES = 8`: cửa sổ xác nhận trước khi phun tự động.
- `PUMP_MAX_SECONDS = 5.0`, `PUMP_COOLDOWN = 15.0`, `PUMP_MAX_PER_MINUTE = 4`: giới hạn an toàn của bơm.
- `SERVO_PIN = 18`, `SERVO_MIN_ANGLE = 30`, `SERVO_MAX_ANGLE = 150`, `SERVO_SETTLE_SECONDS = 0.6`: giới hạn pan camera và tự detach PWM sau khi quay để chống rung.
- `PUMP_PIN = 23`, `PUMP_ACTIVE_HIGH = True`: chân relay và mức kích.
- `ACTUATOR_WATCHDOG_SECONDS = 600`: tự disarm phun tự động nếu không có thao tác điều khiển thật từ web trong 10 phút (việc mở tab poll `/api/status` không reset bộ đếm).
- `DISPLAY_FPS = 15`: giới hạn tần suất vẽ overlay ở `main.py` để nhường CPU cho ONNX.
- `SAVE_SNAPSHOT`: lưu ảnh khi có lửa (mặc định tắt).

## Chạy giao diện web

```bash
source venv/bin/activate
python web_server.py
```

Truy cập `http://<IP-cua-Raspberry-Pi>:5000` từ trình duyệt trong cùng mạng LAN. Tìm IP bằng `hostname -I`.

Dashboard có:

- Video trực tiếp, trạng thái lửa/khói, FPS camera/AI.
- **Trái / Center / Phải**: quay servo pan camera.
- **Bật phun tự động**: arm/disarm chế độ phun khi xác nhận lửa.
- **Phun nước**: bật bơm thủ công một đợt (tối đa 5 giây).
- **DỪNG BƠM**: tắt bơm ngay lập tức.

Máy chủ mặc định nghe trên `0.0.0.0` để thiết bị trong LAN truy cập. **Không chuyển tiếp cổng ra Internet** vì dashboard chưa có đăng nhập và có thể điều khiển bơm nước.

Chế độ cửa sổ OpenCV cũ vẫn chạy được bằng `python main.py`, nhưng không có điều khiển servo/bơm.

## API

- `GET /api/status`: trạng thái camera, AI, servo, bơm, chế độ arm.
- `GET /video_feed`: luồng MJPEG.
- `POST /api/servo` với `{"action": "left" | "right" | "center"}` hoặc `{"action": "set", "angle": 90}`.
- `POST /api/pump` với `{"action": "on" | "stop"}`.
- `POST /api/pump/arm` với `{"armed": true | false}`.
- `POST /api/camera/<action>`: lấy nét/đảo màu (lấy nét chỉ có tác dụng với camera CSI).
- `POST /api/restart`: khởi động lại pipeline.

## An toàn vận hành

- Auto-spray mặc định **OFF**. Chỉ bật sau khi đã kiểm tra vùng phun không có người/thiết bị điện.
- Bơm luôn tự tắt sau `PUMP_MAX_SECONDS`; nút **DỪNG BƠM** luôn có tác dụng.
- Không chạy bơm khô. Kiểm tra nước và đường ống trước khi arm.
- Không có thao tác điều khiển từ web quá 10 phút (`ACTUATOR_WATCHDOG_SECONDS`) → tự disarm auto (bơm vẫn tự tắt theo timer).
- Khi thoát chương trình, relay và servo được đưa về trạng thái an toàn.
- Raspberry Pi 4 chạy ONNX 3 luồng liên tục cần tản nhiệt + quạt và nguồn 5V/3A ổn định để tránh giảm xung ở 80°C.
- Với relay 5V điều khiển từ GPIO 3.3V của Pi, ưu tiên mức kích HIGH (`PUMP_ACTIVE_HIGH = True`) và kiểm tra thực tế relay nhả dứt khoát khi tắt.

## Đo hiệu năng (Benchmark)

Chạy benchmark độc lập (dùng ảnh tổng hợp, file video/ảnh hoặc webcam):

```bash
python benchmark.py --source synthetic --frames 100 --threads 3
python benchmark.py --source sample.mp4 --frames 200 --threads 3
python benchmark.py --source 0 --frames 200 --threads 3
```

Trên Raspberry Pi, script tự đọc thêm nhiệt độ (`vcgencmd measure_temp`) và cờ giảm xung (`vcgencmd get_throttled`).

## Đánh giá model

Thư mục `models/` hiện có `fire_smoke_yolov8n.onnx` (~12 MB) để chạy và `fire_smoke_yolov8n.pt` (~6 MB). Đây là model nhỏ, hợp lý làm **baseline cho Raspberry Pi CPU**, nhưng kích thước file và tên model không chứng minh độ chính xác. Chưa có bộ validation/benchmark kèm dự án để xác nhận mAP, recall khói/lửa hay FPS thực tế trên Pi 4.

Khuyến nghị:

1. Đánh giá ONNX hiện tại trên video/camera đúng vị trí lắp đặt. Xác minh metadata/thứ tự nhãn `fire`, `smoke`; code có fallback nhãn `{0: fire, 1: smoke}` nếu model không chứa metadata.
2. So sánh với một model YOLO nano được fine-tune trên dữ liệu đại diện cho môi trường sử dụng. Bắt đầu với nano để giữ tốc độ trên Pi 4.
3. Đo riêng precision/recall, mAP50-95, false alarm trên nền nóng/ánh sáng đỏ và độ trễ/FPS trên chính Pi. Tách tập test theo địa điểm/thời điểm quay.
4. Chỉ thay file model sau khi kiểm tra input/output ONNX và thứ tự lớp; xuất ONNX với preprocessing nhất quán. Tài liệu Ultralytics có hướng dẫn [export ONNX](https://docs.ultralytics.com/modes/export/) và [đánh giá model detect](https://docs.ultralytics.com/tasks/detect/).

Các model cộng đồng về fire/smoke có thể dùng làm ứng viên kiểm thử, không phải bảo đảm chất lượng: [YOLOv8-Fire-and-Smoke-Detection](https://github.com/Abonia1/YOLOv8-Fire-and-Smoke-Detection) mô tả dữ liệu Roboflow và notebook đánh giá; [fire-and-smoke-detection-yolov8](https://github.com/luminous0219/fire-and-smoke-detection-yolov8) công bố YOLOv8n nhưng README không cung cấp số đo validation đủ để khẳng định model tốt hơn model hiện có. Hãy xem giấy phép, nguồn dữ liệu và kiểm thử độc lập trước khi dùng.

## Cấu trúc

- `web_server.py`: Flask dashboard, REST endpoints, pipeline camera/AI/cảnh báo/actuator.
- `templates/index.html`: giao diện dashboard.
- `actuators.py`: servo SG90 (tự detach sau khi quay) và bơm R385 qua relay, kèm giới hạn an toàn.
- `confirmation.py`: xác nhận lửa theo cửa sổ thời gian dùng chung cho cảnh báo và bơm.
- `benchmark.py`: đo độ trễ preprocess/infer/postprocess, FPS và nhiệt độ Pi.
- `main.py`: chế độ cửa sổ OpenCV (chỉ camera + AI + còi/LED).
- `camera.py`: webcam USB qua OpenCV hoặc Picamera2 CSI.
- `detector.py`: suy luận ONNX, lọc box và worker bất đồng bộ.
- `display.py`: overlay hình ảnh.
- `alert.py`: LED và buzzer.
- `config.py`: cấu hình nền tảng, camera, model, GPIO và web.

## Xử lý sự cố

- **Không mở được webcam:** kiểm tra `v4l2-ctl --list-devices`, đổi `WEBCAM_INDEX`, đảm bảo không có ứng dụng khác đang dùng camera.
- **FPS thấp:** cắm USB 3.0, kiểm tra `WEBCAM_FOURCC = "MJPG"` được camera hỗ trợ.
- **Relay đóng ngược:** đổi `PUMP_ACTIVE_HIGH` hoặc jumper High/Low trên board.
- **Servo rung/không quay:** kiểm tra nguồn 5V ngoài, GND chung, và độ rộng xung; thử `0.001`/`0.002`.
- **Bơm không chạy:** kiểm tra cầu chì, diode, tiếp điểm COM/NO, và nguồn 9V còn đủ áp.
- **Model không nạp:** xác nhận `MODEL_PATH` trỏ đến model ONNX và ONNX Runtime cài được cho kiến trúc/Python đang dùng.
- **Web không truy cập được từ thiết bị khác:** kiểm tra cùng mạng, firewall và `WEB_HOST`; không mở cổng công khai ra Internet.
