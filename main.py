# main.py
"""
Chương trình chính: Hệ thống Giám sát & Nhận diện Khói Lửa Thông Minh
Chạy được trên Laptop (Webcam) và Raspberry Pi 4 (Arducam CSI + Passive Buzzer).
"""

import os
import sys
import time
import threading
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

    async_detection = getattr(config, "ASYNC_DETECTION", True)

    if async_detection:
        # --- CHẾ ĐỘ ASYNC (GIÚP MÀN HÌNH CAMERA ĐẠT 25-30 FPS MƯỢT MÀ) ---
        detections_lock = threading.Lock()
        latest_detections = []
        is_running = True
        new_frame_event = threading.Event()
        current_ai_frame = None

        def ai_worker():
            nonlocal latest_detections, current_ai_frame
            while is_running:
                # Đợi có frame mới cần nhận diện
                if not new_frame_event.wait(timeout=0.1):
                    continue
                new_frame_event.clear()

                with detections_lock:
                    if current_ai_frame is None:
                        continue
                    frame_to_detect = current_ai_frame.copy()

                # Chạy AI nhận diện
                results = detector.detect(frame_to_detect)
                has_fire = any(d["label"].lower() == "fire" for d in results) if results else False

                # Đèn CHỈ SÁNG khi nhận diện được lửa
                alert.set_fire_led(has_fire)

                if results:
                    confs = [round(d["conf"], 2) for d in results]
                    print(f"[CANH BAO] PHAT HIEN LUA! Confidence: {confs}")
                    alert.trigger()

                    if config.SAVE_SNAPSHOT:
                        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                        filename = os.path.join(
                            config.SNAPSHOT_DIR, f"alert_{timestamp_str}_{int(time.time() * 1000) % 1000}.jpg"
                        )
                        cv2.imwrite(filename, frame_to_detect)

                with detections_lock:
                    latest_detections = results

        ai_thread = threading.Thread(target=ai_worker, daemon=True)
        ai_thread.start()

        try:
            while True:
                frame = camera.get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue

                # Cung cấp frame mới nhất cho AI worker nếu worker đã xử lý xong frame cũ
                if not new_frame_event.is_set():
                    with detections_lock:
                        current_ai_frame = frame
                    new_frame_event.set()

                with detections_lock:
                    detections_to_draw = list(latest_detections)

                # Tính toán FPS hiển thị
                frame_count += 1
                elapsed = time.time() - fps_start_time
                if elapsed >= 1.0:
                    current_fps = frame_count / elapsed
                    frame_count = 0
                    fps_start_time = time.time()

                # Hiển thị lên màn hình
                if config.SHOW_DISPLAY:
                    display_frame = display.draw_overlay(frame.copy(), detections_to_draw, fps=current_fps)
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
                    time.sleep(0.02)

        except KeyboardInterrupt:
            print("\n[He thong] Dang dung theo yeu cau nguoi dung (Ctrl+C)...")
        except Exception as e:
            print(f"\n[Loi he thong]: {e}")
        finally:
            is_running = False
            new_frame_event.set()
            ai_thread.join(timeout=1.0)
            print("[He thong] Dang giai phong camera va tai nguyen GPIO...")
            camera.close()
            alert.cleanup()
            if config.SHOW_DISPLAY:
                display.close()
            print("[He thong] Da dung an toan. Tam biet!")

    else:
        # --- CHẾ ĐỘ TUẦN TỰ (SYNCHRONOUS) ---
        try:
            while True:
                frame = camera.get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue

                detections = detector.detect(frame)
                has_fire = any(d["label"].lower() == "fire" for d in detections) if detections else False
                alert.set_fire_led(has_fire)

                if detections:
                    confs = [round(d["conf"], 2) for d in detections]
                    print(f"[CANH BAO] PHAT HIEN LUA! Confidence: {confs}")
                    alert.trigger()

                    if config.SAVE_SNAPSHOT:
                        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                        filename = os.path.join(
                            config.SNAPSHOT_DIR, f"alert_{timestamp_str}_{int(time.time() * 1000) % 1000}.jpg"
                        )
                        cv2.imwrite(filename, frame)

                frame_count += 1
                elapsed = time.time() - fps_start_time
                if elapsed >= 1.0:
                    current_fps = frame_count / elapsed
                    frame_count = 0
                    fps_start_time = time.time()

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
