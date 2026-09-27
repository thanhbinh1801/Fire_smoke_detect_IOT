# camera.py
"""
Module thu thập hình ảnh camera:
- "pi": Dùng Picamera2 (chuẩn chính thức cho Raspberry Pi OS Bookworm & Arducam IMX519)
  + Tối ưu cấu hình Video Stream 30 FPS.
  + Hỗ trợ Continuous Autofocus cho thấu kính IMX519.
  + Chuyển đổi hệ màu chuẩn BGR giúp ngọn lửa hiển thị màu đỏ cam tự nhiên.
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
            # Dùng video configuration để tối ưu hóa FPS cao và độ trễ thấp
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

            # Cấu hình tự động lấy nét (Autofocus) cho Arducam IMX519
            if getattr(config, "CAMERA_AUTOFOCUS", True):
                try:
                    # 2 tương đương với Continuous Autofocus trong libcamera
                    self.picam2.set_controls({"AfMode": 2})
                    print("[Camera] Da kich hoat Continuous Autofocus cho Arducam IMX519.")
                except Exception as e:
                    print(f"[Camera] Canh bao cau hinh Autofocus: {e}")

            self.picam2.start()
            print(f"[Camera] Da khoi dong Picamera2 ({config.FRAME_WIDTH}x{config.FRAME_HEIGHT} @ {target_fps}fps)")

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

    def _capture_worker(self):
        """Luồng đọc liên tục khung hình từ camera ở background"""
        swap_rb = getattr(config, "CAMERA_SWAP_RB", True)

        while self.running:
            try:
                if self.platform == "pi":
                    raw = self.picam2.capture_array()
                    # Picamera2 trả về mảng RGB. Chuyển RGB sang BGR để hiển thị màu đỏ chuẩn trên OpenCV
                    if swap_rb:
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
        """Trả về 1 frame dạng numpy array (BGR chuẩn cho OpenCV)."""
        with self.lock:
            if self.frame is not None:
                return self.frame.copy()

        # Nếu chưa có frame thì đợi nhẹ
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
