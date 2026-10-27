# main.py
"""Chế độ giám sát local bằng cửa sổ OpenCV."""

import os
import sys

# Giảm log Qt trên Linux. Không ép backend xcb để OpenCV tự chọn backend
# phù hợp với phiên desktop X11/Wayland đang chạy trên Raspberry Pi.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_LOGGING_RULES", "*=false;*.debug=false;qt.qpa.*=false")

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
from detector import FireSmokeDetector, AsyncFireDetector
from alert import AlertSystem
import display

def main():
    print("=" * 60)
    print(">>> HE THONG NHAN DIEN LUA THONG MINH (CAMERA AI + IOT) <<<")
    print(f"Nen tang cau hinh: {config.PLATFORM.upper()}")
    print("=" * 60)

    camera = None
    async_detector = None
    alert = None

    frame_count = 0
    fps_start_time = time.time()
    cam_fps = 0.0

    last_fire_time = 0.0
    last_result_time = 0.0
    last_camera_frame_time = 0.0
    fire_votes = 0
    cached_detections = []
    is_fire_confirmed = False

    hold_duration = getattr(config, "HOLD_FIRE_TIME", 1.5)
    required_fire_votes = max(1, int(getattr(config, "FIRE_CONFIRMATION_FRAMES", 2)))

    try:
        camera = FireCamera()
        raw_detector = FireSmokeDetector()
        async_detector = AsyncFireDetector(raw_detector)
        alert = AlertSystem()

        if config.SAVE_SNAPSHOT:
            os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)

        print("\n[He thong] Bat dau giam sat...")
        print("-> Nhan 'q' tren cua so video hoac Ctrl+C trong terminal de dung.\n")

        while True:
            # 1. Đọc frame trực tiếp từ camera
            frame, frame_time = camera.get_frame_with_timestamp()
            if frame is None:
                time.sleep(0.005)
                continue
            if time.monotonic() - frame_time > float(
                getattr(config, "CAMERA_STALE_TIMEOUT", 2.0)
            ):
                raise RuntimeError("Camera không cung cấp frame mới quá thời gian cho phép.")

            # 2. Chuyển frame mới nhất cho AI chạy ngầm và lấy kết quả tức thì (O(1), không chặn)
            if frame_time != last_camera_frame_time:
                last_camera_frame_time = frame_time
                async_detector.update_frame(frame)
            else:
                time.sleep(0.002)
                continue
            current_detections, ai_fps, result_time, _ = async_detector.get_result()
            now = time.time()

            # Chỉ đếm kết quả suy luận mới, không tính lặp frame UI thành nhiều lần xác nhận.
            has_new_result = result_time > 0 and result_time != last_result_time
            if has_new_result:
                last_result_time = result_time
                has_fire_now = any(
                    detection.get("label") == "fire"
                    for detection in current_detections
                )
                if has_fire_now:
                    fire_votes += 1
                    last_fire_time = now
                    cached_detections = current_detections
                    if fire_votes >= required_fire_votes:
                        is_fire_confirmed = True
                else:
                    fire_votes = 0

            if is_fire_confirmed and now - last_fire_time >= hold_duration:
                is_fire_confirmed = False
                fire_votes = 0
                cached_detections = []

            # 4. Điều khiển đèn LED GPIO 27 (Sáng ổn định tuyệt đối, không nhấp nháy chập chờn)
            alert.set_fire_led(is_fire_confirmed)

            # 5. Điều khiển còi sóng sin liên tục theo trạng thái lửa
            alert.set_buzzer(is_fire_confirmed)

            if config.SAVE_SNAPSHOT and has_new_result and any(
                detection.get("label") == "fire" for detection in current_detections
            ):
                timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(
                    config.SNAPSHOT_DIR,
                    f"alert_{timestamp_str}_{int(time.time() * 1000) % 1000}.jpg",
                )
                if not cv2.imwrite(filename, frame):
                    print(f"[Loi] Khong luu duoc snapshot: {filename}")

            # 6. Tính toán FPS hiển thị camera
            frame_count += 1
            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                cam_fps = frame_count / elapsed
                frame_count = 0
                fps_start_time = time.time()

            # 7. Hiển thị lên màn hình mượt mà không nhấp nháy
            # Xác định detections sẽ vẽ (ưu tiên box hiện tại, giữ đệm khi lửa chớp tắt < 0.6s)
            if current_detections and result_time and now - result_time < 0.6:
                detections_to_draw = current_detections
            elif now - last_fire_time < 0.6:
                detections_to_draw = cached_detections
            else:
                detections_to_draw = []

            display_frame = display.draw_overlay(frame, detections_to_draw, fps=cam_fps, ai_fps=ai_fps)

            # 8. Hiển thị trực tiếp bằng cửa sổ OpenCV trên máy local.
            if config.SHOW_DISPLAY:
                action = display.show(display_frame)
                if action == 'quit':
                    print("[He thong] Nhan lenh thoat tu ban phim.")
                    break
                elif action == 'color':
                    camera.toggle_color_swap()
                elif action == 'focus':
                    camera.trigger_autofocus()
                elif action == 'focus_near':
                    camera.adjust_focus(+0.2)
                elif action == 'focus_far':
                    camera.adjust_focus(-0.2)
            else:
                time.sleep(0.005)

    except KeyboardInterrupt:
        print("\n[He thong] Dang dung theo yeu cau nguoi dung (Ctrl+C)...")
    except Exception as e:
        print(f"\n[Loi he thong]: {e}")
    finally:
        print("[He thong] Dang giai phong tai nguyen...")
        for resource, method in (
            (async_detector, "stop"),
            (camera, "close"),
            (alert, "cleanup"),
        ):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception as error:
                    print(f"[Loi don dep {method}]: {error}")
        if config.SHOW_DISPLAY:
            display.close()
        print("[He thong] Da dung an toan. Tam biet!")

if __name__ == "__main__":
    main()
