# actuators.py
"""
Điều khiển cơ cấu chấp hành:
- CameraServo: servo SG90 pan camera, giới hạn góc để không xoắn dây USB.
- WaterPump: bơm R385 qua relay, có giới hạn thời gian phun, cooldown,
  giới hạn số lần mỗi phút và chế độ arm/disarm cho phun tự động.

Trên laptop, hai lớp này chỉ ghi log để test logic mà không cần phần cứng.
"""

import threading
import time
from collections import deque

import config


class CameraServo:
    """Servo pan gắn webcam. Chỉ nối signal về Pi; servo dùng nguồn 5V riêng."""

    def __init__(self):
        self.platform = config.PLATFORM
        self.min_angle = float(getattr(config, "SERVO_MIN_ANGLE", 30.0))
        self.max_angle = float(getattr(config, "SERVO_MAX_ANGLE", 150.0))
        self.center_angle = float(getattr(config, "SERVO_CENTER_ANGLE", 90.0))
        self.step_angle = float(getattr(config, "SERVO_STEP_ANGLE", 10.0))
        self._lock = threading.Lock()
        self._angle = self._clamp(self.center_angle)
        self._servo = None

        if self.platform == "pi":
            from gpiozero import AngularServo

            self._servo = AngularServo(
                config.SERVO_PIN,
                initial_angle=self._angle,
                min_angle=0.0,
                max_angle=180.0,
                min_pulse_width=float(
                    getattr(config, "SERVO_MIN_PULSE_WIDTH", 0.0005)
                ),
                max_pulse_width=float(
                    getattr(config, "SERVO_MAX_PULSE_WIDTH", 0.0024)
                ),
            )
            print(
                f"[Servo] SG90 trên GPIO BCM {config.SERVO_PIN}, "
                f"góc {self.min_angle:.0f}-{self.max_angle:.0f}."
            )
        else:
            print("[Servo] Chế độ laptop - giả lập servo qua console.")

    def _clamp(self, angle):
        return max(self.min_angle, min(self.max_angle, float(angle)))

    def set_angle(self, angle):
        """Đặt góc tuyệt đối, tự kẹp trong khoảng an toàn."""
        value = self._clamp(angle)
        with self._lock:
            self._angle = value
            if self._servo is not None:
                try:
                    self._servo.angle = value
                except Exception as error:
                    print(f"[Servo] Lỗi điều khiển: {error}")
                    return None
        print(f"[Servo] Góc hiện tại: {value:.0f}°")
        return value

    def step(self, direction):
        """Quay tương đối: direction > 0 sang phải, < 0 sang trái."""
        with self._lock:
            target = self._angle + (self.step_angle if direction > 0 else -self.step_angle)
        return self.set_angle(target)

    def center(self):
        return self.set_angle(self.center_angle)

    def get_angle(self):
        with self._lock:
            return self._angle

    def get_state(self):
        return {
            "angle": round(self.get_angle(), 1),
            "min_angle": self.min_angle,
            "max_angle": self.max_angle,
            "center_angle": self.center_angle,
            "available": self.platform == "pi",
        }

    def cleanup(self):
        with self._lock:
            if self._servo is not None:
                try:
                    self._servo.detach()
                except Exception:
                    pass
                try:
                    self._servo.close()
                except Exception:
                    pass
                self._servo = None


class WaterPump:
    """Bơm R385 qua relay, an toàn theo thời gian và trạng thái arm."""

    def __init__(self):
        self.platform = config.PLATFORM
        self._lock = threading.RLock()
        self._device = None
        self._armed = False
        self._on = False
        self._started_at = 0.0
        self._ends_at = 0.0
        self._last_end_at = None
        self._reason = ""
        self._runs = deque()
        self._timer = None

        self.max_seconds = float(getattr(config, "PUMP_MAX_SECONDS", 5.0))
        self.cooldown = float(getattr(config, "PUMP_COOLDOWN", 15.0))
        self.max_per_minute = int(getattr(config, "PUMP_MAX_PER_MINUTE", 4))

        if self.platform == "pi":
            from gpiozero import OutputDevice

            self._device = OutputDevice(
                config.PUMP_PIN,
                active_high=bool(getattr(config, "PUMP_ACTIVE_HIGH", True)),
                initial_value=False,
            )
            print(
                f"[Pump] Relay trên GPIO BCM {config.PUMP_PIN} "
                f"(active_high={getattr(config, 'PUMP_ACTIVE_HIGH', True)})."
            )
        else:
            print("[Pump] Chế độ laptop - giả lập bơm qua console.")

        self._write_output(False)

    def _write_output(self, on):
        if self._device is not None:
            try:
                if on:
                    self._device.on()
                else:
                    self._device.off()
            except Exception as error:
                print(f"[Pump] Lỗi điều khiển relay: {error}")
        else:
            print(f"[Pump] GIẢ LẬP: {'BẬT' if on else 'TẮT'} bơm.")

    def _prune_runs(self, now):
        while self._runs and now - self._runs[0] >= 60.0:
            self._runs.popleft()

    def arm(self, enabled):
        with self._lock:
            self._armed = bool(enabled)
            if not self._armed and self._on:
                self._finish_locked()
            print(f"[Pump] Chế độ tự động: {'ARM' if self._armed else 'DISARM'}.")
            return self._armed

    def is_armed(self):
        with self._lock:
            return self._armed

    def spray(self, reason="manual", automatic=False, duration=None):
        """
        Kích hoạt một đợt phun. Trả về (ok, message).
        - automatic=True: chỉ chạy khi đã arm, tôn trọng cooldown và giới hạn/phút.
        - automatic=False: người dùng chủ động, bỏ qua cooldown nhưng vẫn có max time.
        """
        with self._lock:
            if self._on:
                return False, "Bơm đang chạy."

            now = time.monotonic()
            if automatic:
                if not self._armed:
                    return False, "Chế độ phun tự động chưa được bật."
                if self._last_end_at is not None and now - self._last_end_at < self.cooldown:
                    remaining = self.cooldown - (now - self._last_end_at)
                    return False, f"Đang cooldown, còn {remaining:.0f} giây."
                self._prune_runs(now)
                if len(self._runs) >= self.max_per_minute:
                    return False, "Đã đạt giới hạn số lần phun mỗi phút."

            burst = self.max_seconds if duration is None else float(duration)
            burst = max(0.2, min(self.max_seconds, burst))
            self._on = True
            self._started_at = now
            self._ends_at = now + burst
            self._reason = reason
            self._runs.append(now)
            self._write_output(True)
            self._timer = threading.Timer(burst, self._finish)
            self._timer.daemon = True
            self._timer.start()

            print(f"[Pump] Bật {burst:.1f}s ({reason}).")
            return True, f"Đã bật bơm {burst:.1f} giây."

    def _finish(self):
        with self._lock:
            self._finish_locked()

    def _finish_locked(self):
        was_on = self._on
        self._on = False
        self._started_at = 0.0
        self._ends_at = 0.0
        if was_on:
            self._last_end_at = time.monotonic()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._write_output(False)
        if was_on:
            print("[Pump] Đã tắt bơm.")

    def stop(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._finish_locked()
            return True, "Đã dừng bơm."

    def get_state(self):
        with self._lock:
            now = time.monotonic()
            self._prune_runs(now)
            remaining = max(0.0, self._ends_at - now) if self._on else 0.0
            cooldown_remaining = 0.0
            if self._last_end_at is not None and not self._on:
                cooldown_remaining = max(
                    0.0, self.cooldown - (now - self._last_end_at)
                )
            return {
                "state": "on" if self._on else "off",
                "armed": self._armed,
                "reason": self._reason,
                "seconds_remaining": round(remaining, 1),
                "cooldown_remaining": round(cooldown_remaining, 1),
                "runs_last_minute": len(self._runs),
                "max_per_minute": self.max_per_minute,
                "available": self.platform == "pi",
            }

    def cleanup(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._on = False
            self._write_output(False)
            if self._device is not None:
                try:
                    self._device.close()
                except Exception:
                    pass
                self._device = None
