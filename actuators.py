# actuators.py
"""
Điều khiển cơ cấu chấp hành:
- CameraServo: servo SG90 pan camera, giới hạn góc để không xoắn dây USB.
- WaterPump: bơm R385 qua relay, có giới hạn thời gian phun, cooldown,
  giới hạn số lần mỗi phút và chế độ arm/disarm cho phun tự động.

Trên laptop, hai lớp này chỉ ghi log để test logic mà không cần phần cứng.
"""

import os
import threading
import time
import types
from collections import deque

import config


class _SysfsPWMServo:
    def __init__(self, pin, min_pulse_width=0.0005, max_pulse_width=0.0024, frame_width=0.02):
        self.pin = int(pin)
        chips = sorted(
            (f"/sys/class/pwm/{name}" for name in os.listdir("/sys/class/pwm") if name.startswith("pwmchip")),
            key=lambda path: int(path.rsplit("pwmchip", 1)[1]),
        )
        if not chips:
            raise RuntimeError("Kernel PWM chưa được bật; không tìm thấy pwmchip")
        self.chip_path = chips[0]
        if os.path.realpath(os.path.join(self.chip_path, "device", "driver")).endswith("/pwm-gpio") and self.pin != 18:
            raise RuntimeError("pwm-gpio hiện được cấu hình cho GPIO18")
        self.channel = 0
        self.pwm_path = f"{self.chip_path}/pwm{self.channel}"
        self.min_pw = float(min_pulse_width)
        self.max_pw = float(max_pulse_width)
        self.period_ns = int(round(float(frame_width) * 1_000_000_000))
        self._angle = None

        if not os.path.isdir(self.pwm_path):
            with open(f"{self.chip_path}/export", "w", encoding="utf-8") as f:
                f.write(str(self.channel))
            for _ in range(20):
                if os.path.isdir(self.pwm_path):
                    break
                time.sleep(0.01)

        with open(f"{self.pwm_path}/enable", "w", encoding="utf-8") as f:
            f.write("0")
        with open(f"{self.pwm_path}/period", "w", encoding="utf-8") as f:
            f.write(str(self.period_ns))

    @property
    def angle(self):
        return self._angle

    @angle.setter
    def angle(self, value):
        if value is None:
            self.detach()
            return
        ratio = max(0.0, min(1.0, float(value) / 180.0))
        pulse_s = self.min_pw + ratio * (self.max_pw - self.min_pw)
        duty_ns = int(round(pulse_s * 1_000_000_000))
        with open(f"{self.pwm_path}/duty_cycle", "w", encoding="utf-8") as f:
            f.write(str(duty_ns))
        with open(f"{self.pwm_path}/enable", "w", encoding="utf-8") as f:
            f.write("1")
        self._angle = float(value)

    def detach(self):
        try:
            with open(f"{self.pwm_path}/enable", "w", encoding="utf-8") as f:
                f.write("0")
        except Exception:
            pass
        self._angle = None

    def close(self):
        self.detach()


def _patch_lgpio_pwm_pin(servo_device):
    try:
        import lgpio
    except ImportError:
        return
    pin = getattr(getattr(servo_device, "pwm_device", None), "pin", None)
    if pin is None or not hasattr(pin, "_pwm") or not hasattr(pin, "factory"):
        return
    if not hasattr(pin.factory, "_handle"):
        return

    def _float_set_state(self, value):
        if self._pwm:
            freq, prev_duty = self._pwm
            duty = round(float(value) * 100.0, 4)
            if duty != prev_duty or not getattr(self, "_pwm_active", False):
                self._pwm = (freq, duty)
                self._pwm_active = True
                lgpio.tx_pwm(self.factory._handle, self._number, freq, duty)
        else:
            self._pwm_active = False
            lgpio.gpio_write(self.factory._handle, self._number, bool(value))

    def _smart_set_frequency(self, value):
        if value is None or value == 0:
            if self._pwm:
                lgpio.tx_pwm(self.factory._handle, self._number, 0, 0)
                lgpio.gpio_write(self.factory._handle, self._number, 0)
                self._pwm = None
                self._pwm_active = False
        else:
            prev_duty = self._pwm[1] if self._pwm else 0.0
            if not self._pwm:
                self._pwm_active = False
            self._pwm = (value, prev_duty)

    pin._set_state = types.MethodType(_float_set_state, pin)
    pin._set_frequency = types.MethodType(_smart_set_frequency, pin)


class CameraServo:
    """Servo pan gắn webcam. Chỉ nối signal về Pi; servo dùng nguồn 5V riêng."""

    def __init__(self):
        self.platform = config.PLATFORM
        self.min_angle = float(getattr(config, "SERVO_MIN_ANGLE", 30.0))
        self.max_angle = float(getattr(config, "SERVO_MAX_ANGLE", 150.0))
        self.center_angle = float(getattr(config, "SERVO_CENTER_ANGLE", 90.0))
        self.step_angle = float(getattr(config, "SERVO_STEP_ANGLE", 10.0))
        self.settle_seconds = max(
            0.0, float(getattr(config, "SERVO_SETTLE_SECONDS", 0.6))
        )
        self._lock = threading.Lock()
        self._angle = self._clamp(self.center_angle)
        self._servo = None
        self._detach_timer = None
        self._moving_until = 0.0

        if self.platform == "pi":
            min_pw = float(getattr(config, "SERVO_MIN_PULSE_WIDTH", 0.0005))
            max_pw = float(getattr(config, "SERVO_MAX_PULSE_WIDTH", 0.0024))
            if os.path.isdir("/sys/class/pwm/pwmchip0") and int(config.SERVO_PIN) in (
                12,
                13,
                18,
                19,
            ):
                try:
                    self._servo = _SysfsPWMServo(
                        config.SERVO_PIN,
                        min_pulse_width=min_pw,
                        max_pulse_width=max_pw,
                    )
                    self._servo.angle = self._angle
                    pwm_mode = "hardware/kernel PWM"
                except Exception:
                    self._servo = None
            if self._servo is None:
                from gpiozero import AngularServo

                self._servo = AngularServo(
                    config.SERVO_PIN,
                    initial_angle=self._angle,
                    min_angle=0.0,
                    max_angle=180.0,
                    min_pulse_width=min_pw,
                    max_pulse_width=max_pw,
                )
                _patch_lgpio_pwm_pin(self._servo)
                self._servo.angle = self._angle
                pwm_mode = "lgpio PWM"
            with self._lock:
                self._schedule_detach_locked()
            print(
                f"[Servo] SG90 trên GPIO BCM {config.SERVO_PIN} ({pwm_mode}), "
                f"góc {self.min_angle:.0f}-{self.max_angle:.0f}."
            )
        else:
            print("[Servo] Chế độ laptop - giả lập servo qua console.")

    def _clamp(self, angle):
        return max(self.min_angle, min(self.max_angle, float(angle)))

    def _schedule_detach_locked(self):
        if self._detach_timer is not None:
            self._detach_timer.cancel()
            self._detach_timer = None
        if self._servo is not None and self.settle_seconds > 0.0:
            self._detach_timer = threading.Timer(self.settle_seconds, self._detach)
            self._detach_timer.daemon = True
            self._detach_timer.start()

    def _detach(self):
        with self._lock:
            self._detach_timer = None
            if self._servo is not None:
                try:
                    self._servo.detach()
                except Exception:
                    pass

    def set_angle(self, angle):
        """Đặt góc tuyệt đối, tự kẹp trong khoảng an toàn."""
        value = self._clamp(angle)
        with self._lock:
            self._angle = value
            if self.settle_seconds > 0.0:
                self._moving_until = time.monotonic() + self.settle_seconds
            if self._servo is not None:
                try:
                    self._servo.angle = value
                    self._schedule_detach_locked()
                except Exception as error:
                    print(f"[Servo] Lỗi điều khiển: {error}")
                    return None
        print(f"[Servo] Góc hiện tại: {value:.0f}°")
        return value

    def is_moving(self):
        with self._lock:
            return time.monotonic() < self._moving_until

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
            "moving": self.is_moving(),
            "available": self.platform == "pi",
        }

    def cleanup(self):
        with self._lock:
            if self._detach_timer is not None:
                self._detach_timer.cancel()
                self._detach_timer = None
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
