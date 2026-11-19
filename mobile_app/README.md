# Ứng dụng Di động (Mobile App) — Giám sát Lửa & Khói IoT

Ứng dụng di động viết bằng **React Native (Expo)** hỗ trợ cả **Android** và **iOS**, kết nối trực tiếp qua mạng Wi-Fi/LAN tới máy chủ `web_server.py` trên Raspberry Pi hoặc Laptop.

## Tính năng chính
- **Đổi IP linh hoạt & tự động lưu:** Nhập địa chỉ IP của Raspberry Pi (ví dụ `http://192.168.1.50:5000`) ngay trên ứng dụng.
- **Xem Camera trực tiếp:** Hỗ trợ cả luồng **MJPEG (`/video_feed`)** và chế độ **Snapshot (`/api/snapshot`)** kèm hiển thị FPS Camera & AI.
- **Cảnh báo Rung khẩn cấp trên điện thoại:** Tự động đổi giao diện báo động Đỏ và **rung điện thoại** khi hệ thống xác nhận có Lửa.
- **Điều khiển từ xa:**
  - Xoay góc camera Servo (`← Trái`, `Giữa (90°)`, `Phải →`).
  - Bật/Tắt chế độ **Phun nước tự động**, bấm **Phun nước** thủ công hoặc **DỪNG BƠM** khẩn cấp.
  - Bấm **Gửi thử cảnh báo Telegram** trực tiếp từ điện thoại.

## Cách chạy nhanh trên điện thoại thật (Không cần build phức tạp)

1. Đảm bảo máy chủ Python đang chạy trên Raspberry Pi (hoặc Laptop):
   ```bash
   python web_server.py
   ```
2. Tải ứng dụng **Expo Go** trên điện thoại (từ Google Play Store hoặc Apple App Store).
3. Mở Terminal tại thư mục `mobile_app`:
   ```bash
   cd mobile_app
   npm install
   npx expo start
   ```
4. Dùng điện thoại quét **mã QR** hiện trên màn hình Terminal:
   - Khi App mở lên, bấm vào dòng **`IP: ... ✎`** ở góc trên cùng và nhập địa chỉ IP của máy đang chạy `web_server.py` (ví dụ `http://192.168.1.15:5000`) rồi bấm **Kết nối**.
