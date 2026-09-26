# camera.py
"""
Module thu thập hình ảnh camera:
- "pi": Dùng Picamera2 (chuẩn chính thức cho Raspberry Pi OS Bookworm & camera CSI như Arducam IMX519)
- "laptop": Dùng OpenCV VideoCapture với webcam để test
"""

import config

class FireCamera:
    def __init__(self):
        self.platform = config.PLATFORM

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
            # Dùng định dạng BGR888 để tương thích trực tiếp với OpenCV và YOLO
            camera_config = self.picam2.create_preview_configuration(
                main={
                    "size": (config.FRAME_WIDTH, config.FRAME_HEIGHT),
                    "format": "BGR888"
                }
            )
            self.picam2.configure(camera_config)
            self.picam2.start()
            print(f"[Camera] Da khoi dong Picamera2 ({config.FRAME_WIDTH}x{config.FRAME_HEIGHT})")

        elif self.platform == "laptop":
            import cv2
            self.cv2 = cv2
            self.cap = cv2.VideoCapture(config.WEBCAM_INDEX)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
            if not self.cap.isOpened():
                raise RuntimeError(
                    f"Khong mo duoc webcam index {config.WEBCAM_INDEX} - kiem tra lai WEBCAM_INDEX trong config.py"
                )
            print(f"[Camera] Da mo webcam laptop index {config.WEBCAM_INDEX}")

        else:
            raise ValueError(f"PLATFORM không hợp lệ: {self.platform}. Chọn 'pi' hoặc 'laptop'.")

    def get_frame(self):
        """Trả về 1 frame dạng numpy array (BGR)."""
        if self.platform == "pi":
            return self.picam2.capture_array()
        else:
            ok, frame = self.cap.read()
            if not ok:
                raise RuntimeError("Không đọc được frame từ webcam laptop.")
            return frame

    def close(self):
        """Giải phóng camera"""
        if self.platform == "pi":
            if hasattr(self, "picam2"):
                self.picam2.stop()
                self.picam2.close()
        else:
            if hasattr(self, "cap"):
                self.cap.release()
