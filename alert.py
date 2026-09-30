# alert.py
"""
Module điều khiển còi báo động (Buzzer) và Đèn cảnh báo (LED).
- Hỗ trợ Passive Buzzer (PWM) và Active Buzzer trên GPIO BCM 17.
- Hỗ trợ Đèn LED cảnh báo cháy trên GPIO BCM 27.
- Chạy còi trong luồng nền (non-blocking thread) để không làm đơ camera/vòng lặp AI.
"""

import time
import math
import threading
import config

class AlertSystem:
    def __init__(self):
        self.platform = config.PLATFORM
        self.last_alert_time = 0.0
        self.last_fire_time = 0.0
        self.is_buzzing = False
        self.is_led_on = False
        self._lock = threading.Lock()
        # C᳝ liên tục cho còi sóng sin
        self._should_buzz = False
        self._buzz_thread = None

        if self.platform == "pi":
            # 1. Khởi tạo Còi Buzzer
            if getattr(config, "BUZZER_TYPE", "passive") == "passive":
                from gpiozero import PWMOutputDevice
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

            # 2. Khởi tạo Đèn LED báo cháy (GPIO 27)
            from gpiozero import LED
            self.led = LED(getattr(config, "LED_PIN", 27))
            print(f"[Alert] Da khoi tao Den LED tren GPIO BCM {getattr(config, 'LED_PIN', 27)}")
        else:
            print("[Alert] Dang chay che do laptop - coi & den gia lap qua console.")

    def _sound_on(self):
        """Bật còi"""
        if self.platform == "pi":
            if self.mode == "pwm":
                self.buzzer.value = 0.5
            else:
                self.buzzer.on()

    def _sound_off(self):
        """Tắt còi"""
        if self.platform == "pi":
            if self.mode == "pwm":
                self.buzzer.value = 0.0
            else:
                self.buzzer.off()

    def _led_on(self):
        """Bật đèn cảnh báo lửa"""
        if not self.is_led_on:
            self.is_led_on = True
            if self.platform == "pi":
                self.led.on()
            print(f"[LED] >>> BAT DEN CANH BAO LUA (GPIO {getattr(config, 'LED_PIN', 27)}) <<<")

    def _led_off(self):
        """Tắt đèn cảnh báo lửa"""
        if self.is_led_on:
            self.is_led_on = False
            if self.platform == "pi":
                self.led.off()
            print("[LED] >>> TAT DEN CANH BAO LUA <<<")

    def _buzz_sine_worker(self):
        """
        Luồng chạy ngầm: phát sóng sin liên tục (quét tần số 1000–3000 Hz theo hàm sin)
        - Tần số của âm thanh thay đổi mượt mà theo hàm sin 0.5 Hz
        - Chạy cho đến khi _should_buzz = False thì dừng ngay
        """
        t = 0.0
        dt = 0.02  # cập nhật mỗi 20ms
        f_center = 2000  # tần số trung tâm Hz
        f_range  = 1000  # biên độ quét Hz
        sweep_hz = 0.5   # tốc độ quét lên xuống (0.5 Hz = 2 giây/chu kỳ)

        while self._should_buzz:
            freq = int(f_center + f_range * math.sin(2 * math.pi * sweep_hz * t))
            if self.platform == "pi" and self.mode == "pwm":
                try:
                    self.buzzer.frequency = freq
                    self.buzzer.value = 0.5
                except Exception:
                    pass
            t += dt
            time.sleep(dt)

        self._sound_off()
        with self._lock:
            self.is_buzzing = False

    def set_fire_led(self, has_fire: bool):
        """
        Điều khiển đèn LED cảnh báo lửa ở GPIO 27:
        - Đèn CHỈ SÁNG khi nhận diện được lửa trong khung hình.
        - Khi khung hình không còn nhận diện được lửa, đèn lập tức TẮT ngay.
        """
        if has_fire:
            self._led_on()
        else:
            self._led_off()

    def set_buzzer(self, has_fire: bool):
        """
        Điều khiển còi liên tục theo trạng thái nhận diện:
        - has_fire=True  : bắt đầu hú sóng sin (nếu chưa chạy)
        - has_fire=False : dừng ngay lập tức
        """
        if has_fire:
            with self._lock:
                if self.is_buzzing:
                    return  # đang chạy rồi, không spawn thêm
                self._should_buzz = True
                self.is_buzzing = True
            if self.platform == "laptop":
                print("[ALERT] >>> COI GIA LAP: DANG HU SONG SIN <<<")
            self._buzz_thread = threading.Thread(
                target=self._buzz_sine_worker, daemon=True, name="BuzzSine"
            )
            self._buzz_thread.start()
        else:
            self._should_buzz = False  # worker tự dừng sau 1 vòng

    def trigger(self):
        """
        [Legacy] Kích hoạt còi (giữ để tương thích). Dùng set_buzzer() cho chế độ mới.
        """
        now = time.time()

        # Kiểm tra cooldown còi
        if now - self.last_alert_time < config.ALERT_COOLDOWN:
            return False

        if self.is_buzzing:
            return False

        self.last_alert_time = now
        worker = threading.Thread(target=self._buzz_worker, daemon=True)
        worker.start()
        return True

    def cleanup(self):
        """Dọn dẹp tài nguyên khi tắt chương trình"""
        self._sound_off()
        self._led_off()
        if self.platform == "pi":
            if hasattr(self, "buzzer"):
                self.buzzer.close()
            if hasattr(self, "led"):
                self.led.close()
