# Hệ thống giám sát lửa/khói IoT

Ứng dụng chạy camera, suy luận YOLO ONNX và cảnh báo GPIO trên Raspberry Pi; giao diện web xem video trực tiếp, trạng thái, FPS và điều khiển lấy nét. Luồng camera và AI chạy nền, trình duyệt nhận một luồng MJPEG đã mã hóa dùng chung thay vì chạy suy luận cho từng người xem.

## Phần cứng và phần mềm

- Raspberry Pi 4 (64-bit) với Raspberry Pi OS Bookworm.
- Camera CSI (cấu hình hiện tại dành cho Arducam IMX519) hoặc webcam USB để thử trên laptop.
- Tùy chọn: LED GPIO BCM 27 và passive buzzer BCM 17.
- Python 3.10 trở lên; ONNX Runtime CPU, OpenCV, NumPy, Pillow và Flask.

## Cài đặt Raspberry Pi

```bash
cd ~/Fire_smoke_detect_IOT
sudo apt update
sudo apt install -y python3-picamera2 python3-gpiozero python3-opencv python3-venv fonts-dejavu-core libgl1 libglib2.0-0
python3 -m venv venv --system-site-packages
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Kiểm tra camera trước:

```bash
rpicam-hello -t 3000
```

## Chạy giao diện web

```bash
source venv/bin/activate
python web_server.py
```

Truy cập `http://<IP-cua-Raspberry-Pi>:5000` từ trình duyệt trong cùng mạng LAN. Tìm IP bằng `hostname -I`. Máy chủ mặc định nghe trên mọi giao diện mạng (`0.0.0.0`) để thiết bị khác trong LAN truy cập được; **không chuyển tiếp cổng này ra Internet hoặc dùng trên mạng không tin cậy** vì dashboard hiện chưa có đăng nhập.

Trên Windows/laptop để thử webcam, đổi `PLATFORM = "laptop"` trong `config.py`, cài dependencies trong `requirements.txt`, rồi chạy `python web_server.py`. Không cần GPIO vật lý trong chế độ laptop. Raspberry Pi dùng Picamera2/GPIO Zero và OpenCV từ gói hệ điều hành như phần cài đặt bên trên.

Dashboard hiển thị video, trạng thái lửa/khói, FPS camera/AI và có nút lấy nét, chỉnh nét xa/gần, đảo màu. Các endpoint trạng thái và điều khiển là `/api/status`, `/video_feed` và `/api/camera/<action>`. Nếu model/camera không khởi động được, dashboard sẽ hiển thị lỗi; nút thử lại sẽ khởi động lại pipeline.

Chế độ cửa sổ OpenCV cũ vẫn có thể chạy bằng `python main.py` trong phiên desktop cục bộ.

## Cấu hình

Thiết lập trong `config.py`:

- `PLATFORM`: `"pi"` hoặc `"laptop"`.
- `MODEL_PATH`: file ONNX dùng để nhận diện.
- `CONFIDENCE_THRESHOLD`, `IOU_THRESHOLD`: ngưỡng lọc box.
- `FIRE_CONFIRMATION_FRAMES`: số kết quả suy luận liên tiếp cần có lửa trước khi báo động.
- `HOLD_FIRE_TIME`: thời gian giữ báo động sau lần nhận diện lửa cuối.
- `CAMERA_STALE_TIMEOUT`: thời gian tối đa chờ frame camera mới trước khi báo lỗi pipeline.
- `WEB_HOST`, `WEB_PORT`, `WEB_STREAM_FPS`: máy chủ web và tốc độ mã hóa luồng xem.
- `CAMERA_LENS_POSITION`, `CAMERA_AUTOFOCUS`: lấy nét IMX519.
- `SAVE_SNAPSHOT`: lưu ảnh khi có lửa; mặc định tắt để hạn chế ghi liên tục.

LED/còi chỉ kích hoạt theo lớp `fire`; lớp `smoke` được hiển thị để cảnh báo sớm nhưng không bật còi. Hệ thống xác nhận lửa qua các kết quả suy luận mới, không tính lặp lại cùng một kết quả như nhiều frame độc lập.

## Đánh giá model

Thư mục `models/` hiện có `fire_smoke_yolov8n.onnx` (~12 MB) để chạy và `fire_smoke_yolov8n.pt` (~6 MB). Đây là model nhỏ, hợp lý làm **baseline cho Raspberry Pi CPU**, nhưng kích thước file và tên model không chứng minh độ chính xác. Chưa có bộ validation/benchmark đi kèm dự án để xác nhận mAP, recall khói/lửa hay FPS thực tế trên Pi 4.

Khuyến nghị:

1. Trước tiên đánh giá ONNX hiện tại trên video/camera đúng vị trí lắp đặt. Xác minh metadata/thứ tự nhãn `fire`, `smoke`; code có fallback nhãn `{0: fire, 1: smoke}` nếu model không chứa metadata.
2. So sánh với một model YOLO nano được fine-tune trên dữ liệu đại diện cho môi trường sử dụng. Bắt đầu với nano để giữ tốc độ trên Pi 4; thử small chỉ nếu benchmark thực tế còn đủ nhanh.
3. Đo riêng precision/recall, mAP50-95, false alarm trên nền nóng/ánh sáng đỏ và độ trễ/FPS trên chính Pi. Tách tập test theo địa điểm/thời điểm quay; không chọn model chỉ dựa trên mAP COCO hoặc demo video.
4. Chỉ thay file model sau khi kiểm tra input/output ONNX và thứ tự lớp; xuất ONNX với preprocessing nhất quán. Tài liệu Ultralytics có hướng dẫn [export ONNX](https://docs.ultralytics.com/modes/export/) và [đánh giá model detect](https://docs.ultralytics.com/tasks/detect/).

Các model cộng đồng về fire/smoke có thể dùng làm ứng viên kiểm thử, không phải bảo đảm chất lượng: [YOLOv8-Fire-and-Smoke-Detection](https://github.com/Abonia1/YOLOv8-Fire-and-Smoke-Detection) mô tả dữ liệu Roboflow và notebook đánh giá; [fire-and-smoke-detection-yolov8](https://github.com/luminous0219/fire-and-smoke-detection-yolov8) công bố YOLOv8n nhưng README không cung cấp số đo validation đủ để khẳng định model tốt hơn model hiện có. Hãy xem giấy phép, nguồn dữ liệu và kiểm thử độc lập trước khi dùng.

## Cấu trúc

- `web_server.py`: Flask dashboard, REST endpoints, pipeline camera/AI/cảnh báo.
- `templates/index.html`: giao diện dashboard.
- `main.py`: chế độ cửa sổ OpenCV.
- `camera.py`: Picamera2/webcam và luồng đọc frame.
- `detector.py`: suy luận ONNX, lọc box và worker bất đồng bộ.
- `display.py`: overlay hình ảnh.
- `alert.py`: LED và buzzer.
- `config.py`: cấu hình nền tảng, model, camera, GPIO và web.

## Xử lý sự cố

- **Camera không trả hình:** đóng ứng dụng khác đang dùng camera, thử `rpicam-hello`, kiểm tra cáp/driver.
- **Không tìm thấy Picamera2:** tạo virtualenv với `--system-site-packages` như hướng dẫn; gói Picamera2 thuộc Raspberry Pi OS.
- **Model không nạp:** xác nhận `MODEL_PATH` trỏ đến model ONNX và ONNX Runtime cài được cho kiến trúc/Python đang dùng.
- **Web không truy cập được từ thiết bị khác:** kiểm tra thiết bị cùng mạng, firewall và `WEB_HOST`; không mở cổng công khai ra Internet.
