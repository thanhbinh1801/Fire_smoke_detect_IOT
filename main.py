# main.py
"""
Chương trình chính: Hệ thống Giám sát & Nhận diện Lửa Thông Minh (Camera AI + IoT)
Tối ưu hóa:
- Đồng bộ tuyệt đối (Zero-Latency): Hình ảnh và Bounding Box luôn khớp 100%, không bị lệch vị trí khi di chuyển.
- Model ONNX chuẩn 480x640: Giữ nguyên tỷ lệ khung hình thực, đạt độ chính xác cao nhất (Confidence 0.80 - 0.89).
- Bật/tắt đèn LED GPIO 27 tức thời và còi báo động non-blocking.
"""

import os
import sys
import time
import cv2

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
    print(">>> HE THONG NHAN DIEN LUA THONG MINH (CAMERA AI + IOT) <<<")
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
            # 1. Đọc frame mới nhất từ camera
            frame = camera.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            # 2. Nhận diện lửa trên chính frame này
            detections = detector.detect(frame)
            has_fire = len(detections) > 0

            # 3. Điều khiển đèn LED GPIO 27 (Có lửa -> Bật ngay, Hết lửa -> Tắt ngay)
            alert.set_fire_led(has_fire)

            # 4. Kích hoạt còi báo động và lưu snapshot nếu có lửa
            if has_fire:
                confs = [round(d["conf"], 2) for d in detections]
                print(f"[CANH BAO] PHAT HIEN LUA! Confidence: {confs}")
                alert.trigger()

                if config.SAVE_SNAPSHOT:
                    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(
                        config.SNAPSHOT_DIR, f"alert_{timestamp_str}_{int(time.time() * 1000) % 1000}.jpg"
                    )
                    cv2.imwrite(filename, frame)

            # 5. Tính toán FPS
            frame_count += 1
            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                current_fps = frame_count / elapsed
                frame_count = 0
                fps_start_time = time.time()

            # 6. Hiển thị lên màn hình (Vẽ box trực tiếp lên CHÍNH frame vừa xử lý -> KHÔNG BAO GIỜ BỊ DELAY)
            if config.SHOW_DISPLAY:
                display_frame = display.draw_overlay(frame.copy(), detections, fps=current_fps)
                action = display.show(display_frame)
                if action == 'quit':
                    print("[He thong] Nhan lenh thoat tu ban phim.")
                    break
                elif action == 'focus':
                    camera.trigger_autofocus()
                elif action == 'focus_near':
                    camera.adjust_focus(+0.5)
                elif action == 'focus_far':
                    camera.adjust_focus(-0.5)
            else:
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
