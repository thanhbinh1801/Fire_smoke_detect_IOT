# camera.py
"""
Module thu thập hình ảnh camera:
- "pi": Dùng Picamera2 (chuẩn chính thức cho Raspberry Pi OS Bookworm & Arducam IMX519)
  + Khóa nét cố định (Manual Focus Lock) chống hiện tượng săn nét làm mờ vân lửa.
  + Điều chỉnh phơi sáng giảm chói lóa từ màn hình điện thoại / ngọn lửa.
  + Xuất mảng RGB888 chuẩn xác trực tiếp cho mạng nơ-ron AI.
  + Hỗ trợ phím nóng '[' và ']' để vi chỉnh tiêu cự thấu kính.
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
        self.lens_position = getattr(config, "CAMERA_LENS_POSITION", 2.0)
        self.swap_rb = getattr(config, "CAMERA_SWAP_RB", False)

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
                    "format": "BGR888"
                },
                controls={
                    "FrameRate": target_fps
                }
            )
            self.picam2.configure(camera_config)
            self.picam2.start()
            print(f"[Camera] Da khoi dong Picamera2 ({config.FRAME_WIDTH}x{config.FRAME_HEIGHT} BGR888 @ {target_fps}fps)")

            # Cấu hình Lấy Nét Tự Động (Continuous AF) và Phơi Sáng cho Arducam IMX519
            time.sleep(0.3)
            try:
                exp_comp = getattr(config, "CAMERA_EXPOSURE_COMP", -0.5)
                auto_focus = getattr(config, "CAMERA_AUTOFOCUS", True)

                ctrls = {
                    "Sharpness": 1.5,
                    "ExposureValue": float(exp_comp)
                }

                if auto_focus:
                    # AfMode 2 = Continuous Auto Focus (Tự động bám nét liên tục ở mọi khoảng cách)
                    ctrls["AfMode"] = 2
                    print("[Camera] DA BAT LAY NET TU DONG LIEN TUC (Continuous AF - AfMode=2).")
                else:
                    # AfMode 0 = Manual Focus (Khóa cứng thấu kính)
                    ctrls["AfMode"] = 0
                    ctrls["LensPosition"] = float(self.lens_position)
                    print(f"[Camera] KHOA NET CO DINH tai LensPosition = {self.lens_position} dioptres.")

                self.picam2.set_controls(ctrls)
            except Exception as e:
                print(f"[Camera] Canh bao cau hinh controls: {e}")

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
        """Kích hoạt chu kỳ lấy nét tự động lại nếu cần"""
        if self.platform == "pi" and hasattr(self, "picam2"):
            try:
                self.picam2.set_controls({"AfMode": 1, "AfTrigger": 0})
                time.sleep(0.05)
                self.picam2.set_controls({"AfMode": 1, "AfTrigger": 1})
                print("\n[Camera] >>> DA KICH HOAT CHU KY LAY NET TU DONG <<<")
            except Exception as e:
                print(f"[Camera] Loi Autofocus: {e}")

    def adjust_focus(self, step):
        """Vi chỉnh tiêu cự thủ công (step: +0.2 hoặc -0.2)"""
        if self.platform == "pi" and hasattr(self, "picam2"):
            try:
                self.lens_position = max(0.0, min(10.0, round(self.lens_position + step, 2)))
                self.picam2.set_controls({"AfMode": 0, "LensPosition": float(self.lens_position)})
                print(f"\n[Camera] >>> TIEU CU HIEN TAI: {self.lens_position:.2f} dioptres <<<")
            except Exception as e:
                print(f"[Camera] Loi Focus: {e}")

    def toggle_color_swap(self):
        """Đảo kênh màu R-B trực tiếp khi đang chạy (hỗ trợ phím nóng 'c')"""
        self.swap_rb = not self.swap_rb
        mode = "DAO KENH R-B" if self.swap_rb else "MAC DINH"
        print(f"\n[Camera] >>> DA CHUYEN CHE DO MAU: {mode} <<<")
        return self.swap_rb

    def _capture_worker(self):
        """Luồng đọc liên tục khung hình từ camera ở background"""
        while self.running:
            try:
                if self.platform == "pi":
                    raw = self.picam2.capture_array()
                    # Picamera2 trả về mảng RGB trong bộ nhớ; chuyển sang BGR chuẩn OpenCV
                    base_bgr = cv2.cvtColor(raw, cv2.COLOR_RGB2BGR)
                else:
                    ok, raw = self.cap.read()
                    if not ok:
                        time.sleep(0.01)
                        continue
                    base_bgr = raw

                if self.swap_rb:
                    current_frame = cv2.cvtColor(base_bgr, cv2.COLOR_BGR2RGB)
                else:
                    current_frame = base_bgr

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
