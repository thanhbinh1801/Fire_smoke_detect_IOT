import time

from gpiozero import Device
from gpiozero.pins.mock import MockFactory, MockPWMPin

import config
from actuators import CameraServo, WaterPump


def test_water_pump_arm_cooldown_and_rate_limit(monkeypatch):
    monkeypatch.setattr(config, "PLATFORM", "laptop")
    monkeypatch.setattr(config, "PUMP_MAX_SECONDS", 0.3)
    monkeypatch.setattr(config, "PUMP_COOLDOWN", 1.0)
    monkeypatch.setattr(config, "PUMP_MAX_PER_MINUTE", 2)

    pump = WaterPump()
    try:
        ok, _ = pump.spray("auto", automatic=True)
        assert not ok

        pump.arm(True)
        ok, _ = pump.spray("auto", automatic=True, duration=0.2)
        assert ok
        pump.stop()

        ok, _ = pump.spray("auto", automatic=True, duration=0.2)
        assert not ok

        pump._last_end_at = time.monotonic() - 2.0
        ok, _ = pump.spray("auto", automatic=True, duration=0.2)
        assert ok
        pump.stop()

        pump._last_end_at = time.monotonic() - 2.0
        ok, _ = pump.spray("auto", automatic=True, duration=0.2)
        assert not ok
    finally:
        pump.cleanup()


def test_camera_servo_auto_detaches_on_pi(monkeypatch):
    Device.pin_factory = MockFactory(pin_class=MockPWMPin)
    monkeypatch.setattr(config, "PLATFORM", "pi")
    monkeypatch.setattr(config, "SERVO_SETTLE_SECONDS", 0.15)

    servo = CameraServo()
    try:
        servo.set_angle(120.0)
        assert servo.get_angle() == 120.0
        assert servo.is_moving()
        assert servo._servo.value is not None
        time.sleep(0.25)
        assert not servo.is_moving()
        assert servo._servo.value is None
    finally:
        servo.cleanup()
        Device.pin_factory.reset()
