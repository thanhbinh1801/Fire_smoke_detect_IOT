# main.py
"""
Chương trình chính: Hệ thống Giám sát & Nhận diện Lửa Thông Minh
Chạy được trên Laptop (Webcam) và Raspberry Pi 4 (Arducam IMX519 + Passive Buzzer + LED).
Tối ưu:
- Hỗ trợ ASYNC 25-30 FPS mượt mà với model ONNX 256x256 siêu nhẹ.
- Tích hợp Temporal Persistence Filter chống chập chờn (mất tín hiệu giữa các frame).
"""

import os
import sys
import time
import threading
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

    async_detection = getattr(config, "ASYNC_DETECTION", True)
    persistence_limit = getattr(config, "BOX_PERSISTENCE", 4)

    if async_detection:
        # --- CHẾ ĐỘ ASYNC SIÊU MƯỢT (CAMERA ĐẠT 25-30 FPS, BÁM VẾT LIÊN TỤC) ---
        detections_lock = threading.Lock()
        latest_detections = []
        is_running = True
        new_frame_event = threading.Event()
        current_ai_frame = None

        def ai_worker():
            nonlocal latest_detections, current_ai_frame
            persistence_counter = 0
            persisted_results = []

            while is_running:
                if not new_frame_event.wait(timeout=0.1):
                    continue
                new_frame_event.clear()

                with detections_lock:
                    if current_ai_frame is None:
                        continue
                    frame_to_detect = current_ai_frame.copy()

                results = detector.detect(frame_to_detect)

                if results:
                    # Có lửa: nạp lại bộ đếm giữ vết và bật đèn LED
                    persistence_counter = persistence_limit
                    persisted_results = results
                    alert.set_fire_led(True)

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
                else:
                    # Tạm thời không thấy lửa: kiểm tra bộ đếm giữ vết chống chập chờn
                    if persistence_counter > 0:
                        persistence_counter -= 1
                        alert.set_fire_led(True)
                        with detections_lock:
                            latest_detections = persisted_results
                    else:
                        persisted_results = []
                        alert.set_fire_led(False)
                        with detections_lock:
                            latest_detections = []

        ai_thread = threading.Thread(target=ai_worker, daemon=True)
        ai_thread.start()

        try:
            while True:
                frame = camera.get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue

                # Đưa frame mới cho AI worker xử lý
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
        # --- CHẾ ĐỘ TUẦN TỰ (SYNCHRONOUS) KÈM CHỐNG CHẬP CHỜN ---
        persistence_counter = 0
        persisted_results = []

        try:
            while True:
                frame = camera.get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue

                results = detector.detect(frame)

                if results:
                    persistence_counter = persistence_limit
                    persisted_results = results
                    alert.set_fire_led(True)

                    confs = [round(d["conf"], 2) for d in results]
                    print(f"[CANH BAO] PHAT HIEN LUA! Confidence: {confs}")
                    alert.trigger()

                    if config.SAVE_SNAPSHOT:
                        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                        filename = os.path.join(
                            config.SNAPSHOT_DIR, f"alert_{timestamp_str}_{int(time.time() * 1000) % 1000}.jpg"
                        )
                        cv2.imwrite(filename, frame)
                    detections_to_draw = results
                else:
                    if persistence_counter > 0:
                        persistence_counter -= 1
                        alert.set_fire_led(True)
                        detections_to_draw = persisted_results
                    else:
                        persisted_results = []
                        alert.set_fire_led(False)
                        detections_to_draw = []

                frame_count += 1
                elapsed = time.time() - fps_start_time
                if elapsed >= 1.0:
                    current_fps = frame_count / elapsed
                    frame_count = 0
                    fps_start_time = time.time()

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
