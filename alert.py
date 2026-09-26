# alert.py
"""
Module điều khiển còi báo động (Buzzer).
- Hỗ trợ Passive Buzzer (phát xung PWM) và Active Buzzer.
- Chạy còi trong luồng nền (non-blocking thread) để không làm đơ camera/vòng lặp AI.
"""

import time
import threading
import config

class AlertSystem:
    def __init__(self):
        self.platform = config.PLATFORM
        self.last_alert_time = 0.0
        self.is_buzzing = False
        self._lock = threading.Lock()

        if self.platform == "pi":
            if getattr(config, "BUZZER_TYPE", "passive") == "passive":
                from gpiozero import PWMOutputDevice
                # Passive buzzer cần tần số PWM (mặc định 2000Hz)
                self.buzzer = PWMOutputDevice(
                    pin=config.BUZZER_PIN,
                    frequency=getattr(config, "BUZZER_FREQUENCY", 2000)
                )
                self.mode = "pwm"
            else:
                from gpiozero import Buzzer
                self.buzzer = Buzzer(config.BUZZER_PIN)
                self.mode = "active"
            print(f"[Alert] Da khoi tao Buzzer ({self.mode}) tren GPIO BCM {config.BUZZER_PIN}")
        else:
            print("[Alert] Dang chay che do laptop - coi gia lap qua console.")

    def _sound_on(self):
        """Bật còi"""
        if self.platform == "pi":
            if self.mode == "pwm":
                self.buzzer.value = 0.5  # 50% duty cycle tạo sóng vuông chuẩn
            else:
                self.buzzer.on()

    def _sound_off(self):
        """Tắt còi"""
        if self.platform == "pi":
            if self.mode == "pwm":
                self.buzzer.value = 0.0
            else:
                self.buzzer.off()

    def _buzz_worker(self):
        """Luồng chạy ngầm điều khiển tiếng kêu ngắt quãng (bíp bíp bíp) tạo sự chú ý"""
        with self._lock:
            self.is_buzzing = True

        try:
            end_time = time.time() + config.ALERT_DURATION
            if self.platform == "laptop":
                print(f"[ALERT] >>> CANH BAO CHAY/KHOI! Còi gia lap dang keu trong {config.ALERT_DURATION}s <<<".encode("ascii", "replace").decode("ascii"))

            # Kêu ngắt quãng (beep 0.2s, nghỉ 0.1s)
            while time.time() < end_time:
                self._sound_on()
                time.sleep(0.2)
                self._sound_off()
                time.sleep(0.1)

        finally:
            self._sound_off()
            with self._lock:
                self.is_buzzing = False

    def trigger(self):
        """
        Kích hoạt cảnh báo.
        Không chặn luồng chính (non-blocking). Kiểm tra cooldown giữa các lần báo động.
        """
        now = time.time()
        if now - self.last_alert_time < config.ALERT_COOLDOWN:
            return False  # Vẫn trong thời gian cooldown

        if self.is_buzzing:
            return False  # Còi đang kêu từ lần gọi trước

        self.last_alert_time = now
        # Kích hoạt còi trong thread riêng để không nghẽn camera loop
        worker = threading.Thread(target=self._buzz_worker, daemon=True)
        worker.start()
        return True

    def cleanup(self):
        """Dọn dẹp tài nguyên khi tắt chương trình"""
        self._sound_off()
        if self.platform == "pi" and hasattr(self, "buzzer"):
            self.buzzer.close()
