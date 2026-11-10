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
from confirmation import build_alarm_confirmer
from detector import FireSmokeDetector, AsyncFireDetector
from alert import AlertSystem
from notifier import TelegramNotifier
import display

def main():
    print("=" * 60)
    print(">>> HE THONG NHAN DIEN LUA THONG MINH (CAMERA AI + IOT) <<<")
    print(f"Nen tang cau hinh: {config.PLATFORM.upper()}")
    print("=" * 60)

    camera = None
    async_detector = None
    alert = None
    notifier = None

    frame = None
    frame_count = 0
    fps_start_time = time.time()
    cam_fps = 0.0

    last_fire_time = 0.0
    last_result_time = 0.0
    last_camera_frame_time = 0.0
    smoke_votes = 0
    cached_detections = []
    is_fire_confirmed = False
    alarm_confirmer = build_alarm_confirmer()
    display_interval = 1.0 / max(1, int(getattr(config, "DISPLAY_FPS", 15)))
    next_display_at = 0.0
    required_smoke_votes = max(1, int(getattr(config, "SMOKE_CONFIRMATION_FRAMES", 2)))

    try:
        camera = FireCamera()
        raw_detector = FireSmokeDetector()
        async_detector = AsyncFireDetector(raw_detector)
        alert = AlertSystem()
        notifier = TelegramNotifier()

        if config.SAVE_SNAPSHOT:
            os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)

        print("\n[He thong] Bat dau giam sat...")
        print("-> Nhan 'q' tren cua so video hoac Ctrl+C trong terminal de dung.\n")

        while True:
            new_frame, frame_time = camera.get_frame_if_new(last_camera_frame_time)
            if frame_time <= 0.0:
                time.sleep(0.005)
                continue
            if time.monotonic() - frame_time > float(
                getattr(config, "CAMERA_STALE_TIMEOUT", 2.0)
            ):
                raise RuntimeError("Camera không cung cấp frame mới quá thời gian cho phép.")

            if new_frame is not None:
                frame = new_frame
                last_camera_frame_time = frame_time
                async_detector.update_frame(frame)
                frame_count += 1
            else:
                time.sleep(0.002)
                continue

            current_detections, ai_fps, result_time, _ = async_detector.get_result()
            now = time.time()

            has_new_result = bool(result_time and result_time != last_result_time)
            if has_new_result:
                last_result_time = result_time
                has_fire_now = any(
                    detection.get("label") == "fire"
                    for detection in current_detections
                )
                has_smoke_now = any(
                    detection.get("label") == "smoke"
                    for detection in current_detections
                )
                if has_fire_now:
                    last_fire_time = now
                    cached_detections = current_detections
            is_fire_confirmed = alarm_confirmer.update(
                current_detections, now=now, result_time=result_time
            )
            if has_new_result:
                if is_fire_confirmed and has_fire_now:
                    notifier.notify(
                        "fire", frame, current_detections, fps=cam_fps, ai_fps=ai_fps
                    )
                if has_smoke_now:
                    smoke_votes += 1
                    if smoke_votes >= required_smoke_votes and not is_fire_confirmed:
                        notifier.notify(
                            "smoke", frame, current_detections, fps=cam_fps, ai_fps=ai_fps
                        )
                else:
                    smoke_votes = 0

            if not is_fire_confirmed and not current_detections:
                cached_detections = []

            alert.set_fire_led(is_fire_confirmed)
            alert.set_buzzer(is_fire_confirmed)

            if config.SAVE_SNAPSHOT and is_fire_confirmed and has_new_result and any(
                detection.get("label") == "fire" for detection in current_detections
            ):
                if now - getattr(main, "_last_snapshot_time", 0.0) >= 2.0:
                    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(
                        config.SNAPSHOT_DIR,
                        f"alert_{timestamp_str}_{int(now * 1000) % 1000}.jpg",
                    )
                    if not cv2.imwrite(filename, frame):
                        print(f"[Loi] Khong luu duoc snapshot: {filename}")
                    main._last_snapshot_time = now

            elapsed = time.time() - fps_start_time
            if elapsed >= 1.0:
                cam_fps = frame_count / elapsed
                frame_count = 0
                fps_start_time = time.time()

            if config.SHOW_DISPLAY:
                mono_now = time.monotonic()
                if mono_now >= next_display_at:
                    next_display_at = mono_now + display_interval
                    if current_detections and result_time and now - result_time < 0.6:
                        detections_to_draw = current_detections
                    elif now - last_fire_time < 0.6:
                        detections_to_draw = cached_detections
                    else:
                        detections_to_draw = []

                    notifier.update_runtime_context(
                        frame,
                        detections_to_draw,
                        fps=cam_fps,
                        ai_fps=ai_fps,
                        confirmed_fire=is_fire_confirmed,
                    )
                    display_frame = display.draw_overlay(
                        frame, detections_to_draw, fps=cam_fps, ai_fps=ai_fps
                    )
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
