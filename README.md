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

Sao chép `.env.example` thành `.env` để ghi đè cấu hình. `PLATFORM=auto` tự nhận diện Raspberry Pi từ device tree (hoặc Linux ARM khi device tree không có); có thể đặt tường minh `PLATFORM=pi` hoặc `PLATFORM=laptop`. Dashboard hiển thị rõ chế độ GPIO thật hay mô phỏng.

Các thiết lập chính (giá trị trong `.env` được ưu tiên):

- `PLATFORM = "pi"`, `CAMERA_SOURCE = "usb"`: Pi dùng webcam USB.
- `WEBCAM_INDEX = 0`: đổi nếu webcam không phải `/dev/video0`.
- `CONFIDENCE_THRESHOLD = 0.40`: ngưỡng hiển thị/cảnh báo chung.
- `FIRE_CONFIRM_WINDOW_SECONDS = 1.5`, `FIRE_CONFIRM_MIN_RATIO = 0.6`, `FIRE_CONFIRM_MIN_SAMPLES = 4`: xác nhận lửa theo cửa sổ thời gian cho còi/LED.
- `PUMP_CONFIDENCE_THRESHOLD = 0.60`: ngưỡng riêng để phun nước (cao hơn để giảm báo động giả).
- `PUMP_CONFIRM_WINDOW_SECONDS = 3.0`, `PUMP_CONFIRM_MIN_RATIO = 0.7`, `PUMP_CONFIRM_MIN_SAMPLES = 8`: cửa sổ xác nhận trước khi phun tự động.
- `PUMP_MAX_SECONDS = 5.0`, `PUMP_COOLDOWN = 15.0`, `PUMP_MAX_PER_MINUTE = 4`: giới hạn an toàn của bơm.
- `NOZZLE_PAN_PIN = 18`, `NOZZLE_TILT_PIN = 19`: tín hiệu servo trái/phải và lên/xuống của vòi (số BCM).
- `NOZZLE_CAMERA_OFFSET_X_CM`, `NOZZLE_CAMERA_OFFSET_Y_CM`: độ lệch camera so với vòi theo trục sàn, đơn vị cm; dùng làm giá trị hiệu chuẩn ban đầu.
- `SERVO_SETTLE_SECONDS = 0.8`: thời gian chờ servo ổn định; các biến `SERVO_*` còn dùng cho lớp servo tương thích cũ.
- `PUMP_PIN = 23`, `PUMP_ACTIVE_HIGH = True`: chân relay và mức kích.
- `ACTUATOR_WATCHDOG_SECONDS = 600`: tự disarm phun tự động nếu không có thao tác điều khiển thật từ web trong 10 phút (việc mở tab poll `/api/status` không reset bộ đếm).
- `DISPLAY_FPS = 15`: giới hạn tần suất vẽ overlay ở `main.py` để nhường CPU cho ONNX.
- `SAVE_SNAPSHOT`: lưu ảnh khi có lửa (mặc định tắt).
- Thiết lập AI trên app di động chỉ áp dụng trong phiên chạy hiện tại, không ghi lại vào `.env` và không thay đổi giới hạn an toàn bơm/servo.
- `CORS_ALLOWED_ORIGINS`: danh sách origin chính xác, phân cách bằng dấu phẩy, chỉ cần cấu hình nếu dùng Expo Web. App Expo native và dashboard cùng origin không cần CORS; không dùng `*`.

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

- `GET /api/status`: trạng thái camera, AI, servo, bơm, chế độ arm, Telegram.
- `GET /video_feed`: luồng MJPEG.
- `POST /api/servo` với `{"action": "left" | "right" | "center"}` hoặc `{"action": "set", "angle": 90}`.
- `POST /api/pump` với `{"action": "on" | "stop"}`.
- `POST /api/pump/arm` với `{"armed": true | false}`.
- `POST /api/camera/<action>`: lấy nét/đảo màu (lấy nét chỉ có tác dụng với camera CSI).
- `POST /api/telegram/test`: gửi ảnh và tin nhắn kiểm tra về Telegram Bot.
- `POST /api/restart`: khởi động lại pipeline.

## Demo vòi nước hai SG90, camera cố định

Web dashboard hiện điều khiển hai servo của **vòi nước**, không quay webcam.
Kích thước hiệu chuẩn ban đầu: sàn 43 × 31 cm, đầu vòi cao 29 cm, webcam cao
36 cm, vị trí XY của cả hai tạm đặt tại tâm sàn (21.5, 15.5). Đo lại khi lắp.

### Cấu hình phần cứng trước khi chạy

- Cấp nguồn 5V riêng cho hai servo, GND chung với Raspberry Pi; dây tín hiệu về GPIO.
  Bơm dùng nguồn 12V qua tiếp điểm relay, không cấp 12V vào Pi/servo.
- Chốt đấu dây: `NOZZLE_PAN_PIN=18` cho servo trái/phải và `NOZZLE_TILT_PIN=19`
  cho servo lên/xuống. Giá trị này đã có trong `config.py`, `.env.example` và `.env`
  cục bộ. `.env` được git bỏ qua; khi chép sang Pi, dùng `.env.example` hoặc cập nhật
  hai dòng này trong `.env` của Pi. GPIO13 không được dùng cho servo thứ hai vì ghi
  chú phần cứng trước đó có tải đang cắm ở chân này.
- Đặt `NOZZLE_{PAN,TILT}_{MIN,MAX,ZERO}` theo giới hạn và vị trí lắp tay servo.
  ZERO của tilt là vòi thẳng xuống; ZERO của pan là hướng +X của cơ cấu.
  Mặc định giới hạn 30–150°; **không đảm bảo phủ toàn sàn với mọi cách lắp**.
  Chỉ mở rộng giới hạn sau khi đã thử cơ khí với ống nước gắn đầy đủ.
- `SERVO_PWM_BACKEND=auto` dùng kernel PWM nếu có overlay `pwm-gpio` ánh xạ đúng GPIO;
  chân chưa có overlay dùng `gpiozero`/`lgpio` với bản vá duty cycle. Đặt `kernel`
  để yêu cầu cả hai trục dùng kernel PWM, hoặc `lgpio` nếu không dùng overlay.
  Mỗi overlay `pwm-gpio` có một chip/kênh 0 riêng; code đọc Device Tree để phân biệt
  chip của GPIO18 và GPIO19, không dùng chung kênh của một chip cho hai servo.
  Lỗi quyền sysfs được báo trực tiếp, không fallback sang GPIO đang bị overlay giữ.
- `NOZZLE_HOLD_POSITION=false` mặc định detach sau thời gian ổn định như cơ chế cũ.
  Nếu tải vòi/ống làm trôi góc, kiểm tra nguồn/cơ khí và có thể đặt `true` để giữ PWM;
  kiểm tra lại độ rung và độ ổn định khi phun.

### Chạy web với kernel PWM trên Pi 4

Dừng các chương trình đang điều khiển GPIO. Trong `.env`, đặt
`SERVO_PWM_BACKEND=kernel`. Nếu muốn giữ xung liên tục như bản một servo cũ,
đặt thêm `NOZZLE_HOLD_POSITION=true`; mặc định `false` vẫn detach sau thời gian ổn định.
Nạp mỗi overlay đúng một lần (kiểm tra trước bằng `dtoverlay -l`):

```bash
sudo dtoverlay pwm-gpio gpio=18
sudo dtoverlay pwm-gpio gpio=19
sudo ./venv/bin/python web_server.py
```

Log mỗi servo phải ghi `kernel PWM` với **hai PWM chip khác nhau**. Dashboard/API
status có `servo.pan.pwm_backend` và `servo.tilt.pwm_backend` để kiểm tra backend.
Chạy bằng Python của venv với quyền root nếu user chưa có quyền ghi PWM sysfs.
Code web không tự nạp overlay hoặc tự nâng quyền. Overlay nạp bằng lệnh trên mất
sau reboot. Để giữ cấu hình, thêm dưới mục `[all]` trong `/boot/firmware/config.txt`:

```ini
dtoverlay=pwm-gpio,gpio=18
dtoverlay=pwm-gpio,gpio=19
```

Hai dòng này thay cho cấu hình `pwm-gpio` trùng chân nếu đã có; không thêm lặp.
`pwm-gpio` phát PWM bằng phần mềm trong kernel, không phải PWM phần cứng.
Backend khởi tạo thành công chưa xác nhận chuyển động cơ khí của servo.

### Cách lắp dây trên Raspberry Pi 4 (header 40 chân)

| Dây/chức năng | GPIO BCM | Chân vật lý trên Pi | Cách nối |
|---|---:|---:|---|
| Servo trái/phải: signal (cam/vàng) | 18 | 12 | Về dây tín hiệu servo pan |
| Servo lên/xuống: signal (cam/vàng) | 19 | 35 | Về dây tín hiệu servo tilt |
| Mass chung servo | GND | 6 | Nối hai dây nâu/đen và cực âm nguồn servo 5V |
| Nguồn servo: hai dây đỏ | — | — | Nối cực dương nguồn 5V riêng |
| Relay bơm: IN | 23 | 16 | Giữ cấu hình `PUMP_PIN=23` |
| Còi hiện có | 17 | 11 | Giữ nguyên |
| LED hiện có | 27 | 13 | Giữ nguyên |

**GPIO19 là chân vật lý 35, không phải chân vật lý 19.** Bảng số chân dựa trên
[tài liệu GPIO chính thức của Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).
Chọn đúng dây theo nhãn servo nếu màu thực tế khác bảng. Header dùng tín hiệu GPIO
3.3V; dây đỏ servo dùng nguồn 5V riêng, không nối nguồn 12V vào bất kỳ dây servo nào.
Nguồn dương 5V riêng chỉ cấp servo; nối chung GND với Pi theo bảng.

Mạch công suất bơm: `+12V → COM relay → NO relay → (+) bơm`, còn `(-) bơm → (-) nguồn
12V`. Nguồn logic VCC/GND của module relay phải theo đúng thông số module đang dùng;
không lấy nguồn bơm 12V cấp vào VCC của relay loại 5V. Phần mass/tách nguồn logic
thực hiện theo sơ đồ module relay thực tế.

Trước khi chạy, chuyển dây tín hiệu servo lên/xuống sang chân vật lý 35. Hai GPIO
18/19 phải dành cho ứng dụng này; không bật đồng thời SPI/I2S/PWM overlay chiếm các
chân đó. Phần mềm vẫn dùng hai đầu ra `gpiozero` độc lập.

### Bù lệch camera trong `.env`

```dotenv
NOZZLE_PAN_PIN=18
NOZZLE_TILT_PIN=19
NOZZLE_X_CM=21.5
NOZZLE_Y_CM=15.5
NOZZLE_HEIGHT_CM=29
NOZZLE_CAMERA_OFFSET_X_CM=0
NOZZLE_CAMERA_OFFSET_Y_CM=0
NOZZLE_CAMERA_HEIGHT_CM=36
NOZZLE_TARGET_HEIGHT_CM=0
NOZZLE_DRY_RUN=true
```

Gốc ở một góc sàn: +X dọc cạnh 43 cm, +Y dọc cạnh 31 cm. Đo độ lệch trong mặt phẳng
sàn từ vị trí đầu vòi tới tâm quang học camera (hình chiếu thẳng đứng của mỗi điểm):

```text
camera_x_cm = NOZZLE_X_CM + NOZZLE_CAMERA_OFFSET_X_CM
camera_y_cm = NOZZLE_Y_CM + NOZZLE_CAMERA_OFFSET_Y_CM
```

Ví dụ camera lệch từ vòi **3 cm theo +X và 2 cm theo -Y** thì nhập `3` và `-2`.
Với vòi tại (21.5,15.5), Camera X/Y trên dashboard ban đầu sẽ là (24.5,13.5).
Hai số `0` hiện tại chỉ là giá trị tạm vì chưa đo, không phải kết quả hiệu chuẩn.
Khoảng chênh cao 36−29=7 cm đã được tính riêng bằng hai chiều cao, không cộng vào
offset X/Y.

**Thứ tự ưu tiên:** nếu chưa có hiệu chuẩn đã lưu, phần mềm lấy các giá trị ban đầu
từ `.env`/biến môi trường (nếu không có thì dùng mặc định `config.py`). Khi đã lưu
dashboard, `data/nozzle_calibration.json` ưu tiên cho các số đo và tọa độ Camera X/Y.
Vì vậy sửa `.env` rồi khởi động lại **không ghi đè hiệu chuẩn đã lưu**. Trong trường
hợp đó, sửa trực tiếp Camera X/Y và các số đo trên dashboard rồi lưu lại; ví dụ trên
thì nhập Camera X=24.5, Camera Y=13.5. GPIO luôn theo `.env`/`config.py`, không theo
file hiệu chuẩn. Thay vị trí lắp camera cần chọn lại bốn góc ảnh.

### Hiệu chuẩn và thử nghiệm

Các số đo có thể lưu riêng bằng **Lưu thông số và áp dụng**, kể cả khi chưa chọn
bốn góc ảnh. Thao tác này dừng bơm, disarm, ghi file và áp dụng ngay vào bộ ngắm;
nếu đã có bốn góc được lưu thì giữ lại các góc đó. Chọn lại bốn góc rồi bấm
**Lưu 4 góc và hiệu chuẩn** để thay vùng ảnh. Khi chưa có bốn góc đã lưu,
click ngắm và ngắm tự động vẫn bị chặn. Thông báo lỗi lưu nằm ngay dưới vùng
điều khiển vòi và giữ nguyên qua các lần cập nhật trạng thái.

1. Chạy `python web_server.py` (Pi: `./venv/bin/python web_server.py`). Giữ
   **Ngắm khô — khóa bơm** bật. Chế độ này khóa cả phun tay và phun tự động.
2. Thử Trái/Phải/Lên/Xuống/Giữa. Mọi lệnh ngắm tay đều dừng bơm và disarm.
   Nút Lên/Xuống là bước góc servo; chiều vật lý phụ thuộc cách lắp.
3. Mở **Hiệu chuẩn phòng và cơ cấu**, chọn đúng kiểu:
   - `yaw_pitch`: trục đầu quay phương vị, trục sau nghiêng **qua hai phía của hướng
     thẳng xuống**. Phần mềm gập phương vị vào ±90° và đổi dấu góc nghiêng để tới phía
     đối diện. Với giới hạn pan hẹp có thể có vùng không tới được; phần mềm từ chối.
   - `tilt_xy`: hai trục nghiêng vuông góc nối tiếp, trục ngoài theo X, trục trong theo Y.
     Hai kiểu có công thức khác nhau, không chọn thay thế chỉ để vượt giới hạn góc.
4. Đặt gốc (0,0) tại một góc sàn; +X dọc cạnh 43 cm, +Y dọc cạnh 31 cm.
   Bấm **Chọn lại 4 góc**, rồi chọn trên ảnh theo thứ tự
   `(0,0) → (43,0) → (43,31) → (0,31)`; nhập vị trí XY và cao độ thực của camera/vòi.
   Chiều pan/tilt là +1 hoặc -1; hướng lắp trục là góc quay của hệ trục cơ cấu
   so với +X sàn, tính độ trong mặt phẳng XY. Đổi góc lắp bằng trường này.
5. Nhập cao mục tiêu: 0 cho mặt sàn, độ cao màn hình khi điện thoại nằm ngang,
   hoặc cao bấc khi dùng nến. `Điểm ngắm trong box`: 0.5 là tâm, 1 là đáy ảnh của
   khung; đáy ảnh không luôn là chân lửa khi nhìn từ trần. Mặc định dùng tâm.
6. Bấm **Lưu hiệu chuẩn và disarm**, rồi **Bật click để ngắm**. Click các điểm trên
   sàn để kiểm chứng. Tọa độ ngoài vùng ảnh đã chọn/ngoài sàn/vượt hành trình bị từ
   chối; không tự kẹp góc rồi phun lệch. Chọn bốn góc mới chỉ có hiệu lực sau khi lưu.
7. Điện thoại phát ảnh/video chỉ dùng cho nhận diện và ngắm khô. Bỏ điện thoại khỏi
   vùng phun, đặt khay/điểm đánh dấu để thử nước. Tắt ngắm khô (thao tác này disarm),
   click ngắm, chờ ổn định rồi dùng **Phun nước**. Mỗi đợt mặc định 1 giây,
   vẫn bị chặn bởi `PUMP_MAX_SECONDS`.
8. Đo lưới 3 × 3 tại X = 0, 21.5, 43 và Y = 0, 15.5, 31 cm nếu cơ cấu tới được;
   có thể dùng các điểm lùi vào mép khay. Ghi sai số tâm vết nước, mục tiêu ban đầu
   ≤3 cm. Mẫu bù nước là danh sách JSON `[{"x":10,"y":10,"dx":1,"dy":-2}]`:
   muốn nước tới (10,10) thì cần ngắm (11,8). **dx/dy là bù điểm ngắm đã đo**, không
   phải tự lấy dấu sai số vết nước. Phần mềm nội suy bù theo khoảng cách; thử lại sau
   mỗi thay đổi. Mẫu bù chỉ có giá trị với cùng bơm, đầu vòi, chiều cao và áp lực.
9. Thử tự động: bật arm. Một mục tiêu fire đạt cửa sổ xác nhận bơm sẽ được ngắm;
   phải có ảnh chụp mới sau khi servo ổn định và còn lửa gần mục tiêu mới được phun.
   Ngắm khô vẫn chạy chu trình này nhưng không bật relay. Không cần tắt ngắm khô
   để thử AI với màn hình. DỪNG BƠM hủy chu trình và disarm ngay.

Hiệu chuẩn lưu nguyên tử tại `data/nozzle_calibration.json`, được git bỏ qua và nạp
lại khi khởi động. Chế độ ngắm khô theo `.env` khi khởi động; thay đổi trên web chỉ
áp dụng phiên hiện tại. Thay vị trí/góc camera, crop, focus/zoom hoặc tỉ lệ khung hình
thì cần hiệu chuẩn lại. Phần mềm tự chặn khi tỉ lệ khung hình khác lúc hiệu chuẩn.
Homography giả thiết sàn phẳng; bù cao độ dùng camera XY đã đo. Mô hình hướng vòi
giả thiết hai trục gần giao nhau và đầu vòi gần tâm quay; sai lệch cơ khí nhỏ/tia nước
được bù bằng đo thực nghiệm, chưa có mô hình đạn đạo hay tự nhìn vết nước.

API mới: `POST /api/nozzle` với `action` là `calibrate` (kèm `calibration`),
`dry_run` (kèm boolean `enabled`), hoặc `aim` (kèm `u,v` chuẩn hóa 0..1 hay `x,y` cm).
`GET /api/status` thêm `nozzle`, `frame_size` và `servo.pan`/`servo.tilt`; giữ trường
`servo.angle` cho client cũ. `/api/servo` thêm `up`/`down`; client mobile cũ vẫn điều
khiển pan và nhận trạng thái, phần hiệu chuẩn hai trục dùng dashboard web.

### Kiểm thử tự động

`python -m pytest -q` kiểm tra hình học, phối cảnh/cao độ, giới hạn vùng phun,
xác nhận cùng mục tiêu, kết quả AI chụp trước khi ổn định, ngắm khô, cooldown,
API và watchdog. Laptop giả lập GPIO; cần kiểm thử trên Pi và phun thực tế để
đánh giá nguồn, khả năng giữ góc, sai số tia nước và nhận diện nến thật.
`node tests/test_nozzle_ui.cjs` kiểm tra tọa độ click khi ảnh có viền trống và thao tác
dừng/disarm trước khi chọn góc hiệu chuẩn, không cần cài thêm thư viện Node.

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
- `notifier.py`: gửi thông báo kèm ảnh cảnh báo qua Telegram Bot (bất đồng bộ).
- `config.py`: cấu hình nền tảng, model, camera, GPIO, Telegram và web.

## Xử lý sự cố

- **Không mở được webcam:** kiểm tra `v4l2-ctl --list-devices`, đổi `WEBCAM_INDEX`, đảm bảo không có ứng dụng khác đang dùng camera.
- **FPS thấp:** cắm USB 3.0, kiểm tra `WEBCAM_FOURCC = "MJPG"` được camera hỗ trợ.
- **Relay đóng ngược:** đổi `PUMP_ACTIVE_HIGH` hoặc jumper High/Low trên board.
- **Servo rung/không quay:** kiểm tra nguồn 5V ngoài, GND chung, và độ rộng xung; thử `0.001`/`0.002`.
- **Bơm không chạy:** kiểm tra cầu chì, diode, tiếp điểm COM/NO, và nguồn 9V còn đủ áp.
- **Model không nạp:** xác nhận `MODEL_PATH` trỏ đến model ONNX và ONNX Runtime cài được cho kiến trúc/Python đang dùng.
- **Web không truy cập được từ thiết bị khác:** kiểm tra cùng mạng, firewall và `WEB_HOST`; không mở cổng công khai ra Internet.
