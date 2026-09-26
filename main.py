# main.py
"""
Chương trình chính: Hệ thống Giám sát & Nhận diện Khói Lửa Thông Minh
Chạy được trên Laptop (Webcam) và Raspberry Pi 4 (Arducam CSI + Passive Buzzer).
"""

import os
import sys
import time
import cv2

# Đảm bảo in tiếng Việt/ký tự đặc biệt không bị crash trên console Windows (cp1252)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
from camera import FireCamera
from detector import FireSmokeDetector
from alert import AlertSystem
import display

def main():
    print("=" * 60)
    print(">>> HE THONG NHAN DIEN KHOI & LUA (CAMERA AI + IOT) <<<")
    print(f"Nen tang cau hinh: {config.PLATFORM.upper()}")
    print("=" * 60)

    # 1. Khởi tạo các module
    camera = FireCamera()
    detector = FireSmokeDetector()
    alert = AlertSystem()

    # 2. Tạo thư mục lưu snapshot nếu được bật
    if config.SAVE_SNAPSHOT:
        os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)

    print("\n[He thong] Bat dau giam sat...")
    print("-> Nhan 'q' tren cua so video hoac Ctrl+C trong terminal de dung.\n")

    frame_count = 0
    fps_start_time = time.time()
    current_fps = 0.0

    try:
        while True:
            loop_start = time.time()

            # Lấy 1 khung hình từ camera
            frame = camera.get_frame()

            # Chạy AI nhận diện
            detections = detector.detect(frame)

            # Xử lý khi có phát hiện
            if detections:
                labels = [d["label"] for d in detections]
                confs = [round(d["conf"], 2) for d in detections]
                print(f"[CANH BAO] Phat hien: {labels} | Confidence: {confs}")

                # Kích hoạt còi báo động (chạy ngầm, không block camera)
                alert.trigger()

                # Lưu ảnh chụp bằng chứng
                if config.SAVE_SNAPSHOT:
                    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(
                        config.SNAPSHOT_DIR, f"alert_{timestamp_str}_{int(time.time() * 1000) % 1000}.jpg"
                    )
                    cv2.imwrite(filename, frame)

            # Tính toán FPS
            frame_count += 1
            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                current_fps = frame_count / elapsed
                frame_count = 0
                fps_start_time = time.time()

            # Hiển thị lên màn hình (nếu bật)
            if config.SHOW_DISPLAY:
                display_frame = display.draw_overlay(frame.copy(), detections, fps=current_fps)
                keep_running = display.show(display_frame)
                if not keep_running:
                    print("[He thong] Nhan lenh thoat tu ban phim.")
                    break
            else:
                # Nếu chạy không màn hình (Headless trên Pi), nghỉ nhẹ 10ms tránh quá tải CPU không cần thiết
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n[He thong] Dang dung theo yeu cau nguoi dung (Ctrl+C)...")
    except Exception as e:
        print(f"\n[Loi he thong]: {e}")
    finally:
        print("[He thong] Dang giai phong camera va tai nguyen GPIO...")
        camera.close()
        alert.cleanup()
        if config.SHOW_DISPLAY:
            display.close()
        print("[He thong] Da dung an toan. Tam biet!")

if __name__ == "__main__":
    main()
