import config
import web_server
from actuators import CameraServo, WaterPump


def test_get_status_does_not_reset_watchdog(monkeypatch):
    monkeypatch.setattr(config, "PLATFORM", "laptop")
    monkeypatch.setattr(web_server.FireMonitor, "start", lambda self: None)

    monitor = web_server.FireMonitor()
    monitor._servo = CameraServo()
    monitor._pump = WaterPump()
    monitor._last_control_at = 100.0

    for _ in range(5):
        status = monitor.get_status()
        assert "auto_armed" in status

    assert monitor._last_control_at == 100.0


def test_real_control_actions_reset_watchdog(monkeypatch):
    monkeypatch.setattr(config, "PLATFORM", "laptop")
    monkeypatch.setattr(web_server.FireMonitor, "start", lambda self: None)

    monitor = web_server.FireMonitor()
    monitor._servo = CameraServo()
    monitor._pump = WaterPump()
    monitor._last_control_at = 100.0

    ok, _ = monitor.set_auto_arm(True)
    assert ok
    assert monitor._last_control_at > 100.0

    previous = monitor._last_control_at
    monitor._last_control_at = 50.0
    ok, _ = monitor.servo_action({"action": "left"})
    assert ok
    assert monitor._last_control_at >= previous

    monitor._pump.cleanup()
    monitor._servo.cleanup()
