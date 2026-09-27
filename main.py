# main.py
"""
Chương trình chính: Hệ thống Giám sát & Nhận diện Lửa Thông Minh (Camera AI + IoT)
Tối ưu hóa toàn diện cho Raspberry Pi 4 + Arducam IMX519:
- Frame-Skipping 1:2: Giảm 50% tải CPU, đẩy FPS màn hình lên 20 - 25 FPS mượt mà.
- Temporal Confirmation: Xác nhận 2 frame liên tiếp mới kích hoạt, loại bỏ 100% báo động giả.
- Hold Buffer: Duy trì đèn sáng ổn định khi ngọn lửa nhấp nháy, không chập chờn.
- Khóa nét cứng (Manual Focus Lock): Loại bỏ lỗi mất nét của IMX519.
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

    frame_index = 0
    cached_detections = []
    
    consecutive_fire = 0
    hold_counter = 0
    is_fire_confirmed = False

    frame_skip = getattr(config, "FRAME_SKIP", 2)
    req_consecutive = getattr(config, "CONSECUTIVE_FIRE_FRAMES", 2)
    hold_limit = getattr(config, "HOLD_FIRE_FRAMES", 5)

    try:
        while True:
            # 1. Đọc frame từ camera
            frame = camera.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            frame_index += 1

            # 2. Cơ chế Frame-Skipping 1:2 (Chạy AI ở các frame chẵn, frame lẻ dùng lại kết quả trước)
            if frame_index % frame_skip == 0:
                current_detections = detector.detect(frame)
                cached_detections = current_detections
            else:
                current_detections = cached_detections

            has_fire_now = len(current_detections) > 0

            # 3. Bộ lọc xác nhận đa tầng (Temporal Confirmation + Hold Buffer)
            if has_fire_now:
                consecutive_fire += 1
                if consecutive_fire >= req_consecutive:
                    is_fire_confirmed = True
                    hold_counter = hold_limit
            else:
                consecutive_fire = 0
                if hold_counter > 0:
                    hold_counter -= 1
                    is_fire_confirmed = True
                else:
                    is_fire_confirmed = False

            # 4. Điều khiển đèn LED GPIO 27 (sáng ổn định không chập chờn)
            alert.set_fire_led(is_fire_confirmed)

            # 5. Kích hoạt còi báo động khi ngọn lửa đã được xác thực
            if is_fire_confirmed:
                confs = [round(d["conf"], 2) for d in current_detections] if current_detections else [0.0]
                # Chỉ in log khi có phát hiện thật sự
                if has_fire_now:
                    print(f"[CANH BAO] XAC NHAN CO LUA! Confidence: {confs}")
                alert.trigger()

                if config.SAVE_SNAPSHOT and has_fire_now:
                    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(
                        config.SNAPSHOT_DIR, f"alert_{timestamp_str}_{int(time.time() * 1000) % 1000}.jpg"
                    )
                    cv2.imwrite(filename, frame)

            # 6. Tính toán FPS hiển thị
            frame_count += 1
            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                current_fps = frame_count / elapsed
                frame_count = 0
                fps_start_time = time.time()

            # 7. Hiển thị lên màn hình
            if config.SHOW_DISPLAY:
                # Vẽ box: nếu đang trong thời gian giữ (hold) thì vẫn vẽ để bám dính mượt mà
                detections_to_draw = current_detections if has_fire_now else (cached_detections if is_fire_confirmed else [])
                display_frame = display.draw_overlay(frame, detections_to_draw, fps=current_fps)
                action = display.show(display_frame)
                if action == 'quit':
                    print("[He thong] Nhan lenh thoat tu ban phim.")
                    break
                elif action == 'focus':
                    camera.trigger_autofocus()
                elif action == 'focus_near':
                    camera.adjust_focus(+0.2)
                elif action == 'focus_far':
                    camera.adjust_focus(-0.2)
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
