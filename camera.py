# camera.py
"""
Module thu thập hình ảnh camera:
- "pi": Dùng Picamera2 (chuẩn chính thức cho Raspberry Pi OS Bookworm & Arducam IMX519)
  + Tối ưu cấu hình Video Stream 30 FPS.
  + Hỗ trợ Autofocus và Manual Focus cho thấu kính IMX519.
  + Hỗ trợ phím 'c' để đảo màu trực tiếp nếu bị ngược màu Đỏ - Xanh lam.
  + Threaded Camera đọc khung hình mượt mà không bị nghẽn buffer.
- "laptop": Dùng OpenCV VideoCapture với webcam để test.
"""

import threading
import time
import cv2
import config

class FireCamera:
    def __init__(self):
        self.platform = config.PLATFORM
        self.running = True
        self.frame = None
        self.lock = threading.Lock()
        self.swap_rb = getattr(config, "CAMERA_SWAP_RB", False)
        self.lens_position = 2.0  # Tiêu cự ban đầu cho cự ly 0.5m

        if self.platform == "pi":
            try:
                from picamera2 import Picamera2
            except ImportError:
                raise ImportError(
                    "Không tìm thấy thư viện picamera2! "
                    "Hãy chắc chắn đã cài: sudo apt install python3-picamera2 "
                    "và tạo venv với cờ --system-site-packages"
                )

            self.picam2 = Picamera2()
            target_fps = getattr(config, "CAMERA_FPS", 30)
            camera_config = self.picam2.create_video_configuration(
                main={
                    "size": (config.FRAME_WIDTH, config.FRAME_HEIGHT),
                    "format": "RGB888"
                },
                controls={
                    "FrameRate": target_fps
                }
            )
            self.picam2.configure(camera_config)
            self.picam2.start()
            print(f"[Camera] Da khoi dong Picamera2 ({config.FRAME_WIDTH}x{config.FRAME_HEIGHT} @ {target_fps}fps)")

            # Cấu hình tự động lấy nét và phơi sáng cho Arducam IMX519 (BẮT BUỘC gọi sau start())
            time.sleep(0.3)
            if getattr(config, "CAMERA_AUTOFOCUS", True):
                try:
                    # AfMode 2: Continuous AF (Tự động lấy nét liên tục)
                    self.picam2.set_controls({
                        "AfMode": 2,
                        "AfRange": 0,       # Full range (từ cận cảnh đến vô cực)
                        "AfSpeed": 0,       # Fast AF
                        "Sharpness": 1.5,   # Tăng độ nét vân lửa
                        "ExposureValue": -0.5 # Giảm chói lóa màn hình
                    })
                    # Chạy 1 chu kỳ tìm nét ban đầu
                    self.picam2.autofocus_cycle()
                    print("[Camera] Da kich hoat Continuous Autofocus & toi uu phoi sang cho Arducam IMX519.")
                except Exception as e:
                    print(f"[Camera] Canh bao cau hinh AF: {e}")

        elif self.platform == "laptop":
            self.cap = cv2.VideoCapture(config.WEBCAM_INDEX)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
            if not self.cap.isOpened():
                raise RuntimeError(
                    f"Khong mo duoc webcam index {config.WEBCAM_INDEX} - kiem tra lai WEBCAM_INDEX trong config.py"
                )
            print(f"[Camera] Da mo webcam laptop index {config.WEBCAM_INDEX}")

        else:
            raise ValueError(f"PLATFORM khong hop le: {self.platform}. Chon 'pi' hoac 'laptop'.")

        # Khởi chạy luồng chạy ngầm đọc frame liên tục (Threaded Reader)
        self.thread = threading.Thread(target=self._capture_worker, daemon=True)
        self.thread.start()

        # Đợi frame đầu tiên sẵn sàng
        start_wait = time.time()
        while self.frame is None and (time.time() - start_wait < 5.0):
            time.sleep(0.05)


    def trigger_autofocus(self):
        """Kích hoạt chu kỳ lấy nét tự động lại cho Arducam IMX519"""
        if self.platform == "pi" and hasattr(self, "picam2"):
            try:
                self.picam2.set_controls({"AfMode": 1, "AfTrigger": 0})
                time.sleep(0.05)
                self.picam2.set_controls({"AfMode": 2, "AfTrigger": 1})
                print("\n[Camera] >>> DA KICH HOAT LAY NET TU DONG (AUTOFOCUS) <<<")
            except Exception as e:
                print(f"[Camera] Loi Autofocus: {e}")

    def adjust_focus(self, step):
        """Chỉnh tiêu cự thủ công (step: +0.5 hoặc -0.5)"""
        if self.platform == "pi" and hasattr(self, "picam2"):
            try:
                self.lens_position = max(0.0, min(10.0, self.lens_position + step))
                # Chuyển AfMode sang Manual (0) và set LensPosition
                self.picam2.set_controls({"AfMode": 0, "LensPosition": float(self.lens_position)})
                print(f"\n[Camera] >>> CHINH TIEU CU THU CONG: {self.lens_position:.1f} dioptres <<<")
            except Exception as e:
                print(f"[Camera] Loi Focus: {e}")

    def _capture_worker(self):
        """Luồng đọc liên tục khung hình từ camera ở background"""
        while self.running:
            try:
                if self.platform == "pi":
                    raw = self.picam2.capture_array()
                    if self.swap_rb:
                        current_frame = cv2.cvtColor(raw, cv2.COLOR_RGB2BGR)
                    else:
                        current_frame = raw
                else:
                    ok, raw = self.cap.read()
                    if not ok:
                        time.sleep(0.01)
                        continue
                    current_frame = raw

                with self.lock:
                    self.frame = current_frame

            except Exception:
                time.sleep(0.01)

    def get_frame(self):
        """Trả về 1 frame dạng numpy array."""
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()

        time.sleep(0.02)
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def close(self):
        """Giải phóng camera"""
        self.running = False
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=1.0)

        if self.platform == "pi":
            if hasattr(self, "picam2"):
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except Exception:
                    pass
        else:
            if hasattr(self, "cap"):
                self.cap.release()
