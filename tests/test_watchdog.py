from types import SimpleNamespace
from unittest.mock import mock_open

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


def test_ai_settings_do_not_reset_watchdog(monkeypatch):
    monkeypatch.setattr(config, "PLATFORM", "laptop")
    monkeypatch.setattr(config, "FIRE_CONFIDENCE_THRESHOLD", 0.4)
    monkeypatch.setattr(config, "CONFIDENCE_THRESHOLD", 0.4)
    monkeypatch.setattr(web_server.FireMonitor, "start", lambda self: None)

    monitor = web_server.FireMonitor()
    monitor._detector = SimpleNamespace(
        preprocessor=SimpleNamespace(
            enable_clahe=False,
            auto_wb=False,
            sharpen=False,
            gamma=1.0,
        ),
        fire_conf_threshold=0.4,
        smoke_conf_threshold=0.38,
        conf_threshold=0.4,
        roi_zoom_enabled=True,
    )
    monitor._alarm_confirmer = SimpleNamespace(threshold=0.4)
    monitor._smoke_confirmer = SimpleNamespace(threshold=0.38)
    monitor._last_control_at = 100.0

    ok, _ = monitor.update_settings({"fire_confidence_threshold": 0.5})

    assert ok
    assert monitor._last_control_at == 100.0


def test_ai_settings_reject_invalid_values_without_partial_update(monkeypatch):
    monkeypatch.setattr(config, "PLATFORM", "laptop")
    monkeypatch.setattr(web_server.FireMonitor, "start", lambda self: None)

    monitor = web_server.FireMonitor()
    monitor._detector = SimpleNamespace(
        preprocessor=SimpleNamespace(
            enable_clahe=False,
            auto_wb=False,
            sharpen=False,
            gamma=1.0,
        ),
        fire_conf_threshold=0.4,
        smoke_conf_threshold=0.38,
        conf_threshold=0.4,
        roi_zoom_enabled=True,
    )
    monitor._alarm_confirmer = SimpleNamespace(threshold=0.4)
    monitor._smoke_confirmer = SimpleNamespace(threshold=0.38)

    ok, _ = monitor.update_settings(
        {"fire_confidence_threshold": 0.6, "pump_max_seconds": 10}
    )

    assert not ok
    assert monitor._detector.fire_conf_threshold == 0.4
    assert monitor._detector.roi_zoom_enabled is True


def test_platform_auto_detection_and_explicit_override(monkeypatch):
    monkeypatch.setattr(config, "_detect_platform", lambda: "pi")

    assert config._resolve_platform("auto") == "pi"
    assert config._resolve_platform("laptop") == "laptop"


def test_platform_detection_reads_raspberry_pi_device_tree(monkeypatch):
    monkeypatch.setattr(
        "builtins.open",
        mock_open(read_data=b"Raspberry Pi 4 Model B Rev 1.5\x00"),
    )

    assert config._detect_platform() == "pi"


def test_cors_only_allows_configured_origins(monkeypatch):
    monkeypatch.setattr(config, "CORS_ALLOWED_ORIGINS", "https://app.example")
    app = web_server.create_app(monitor=object())
    client = app.test_client()

    allowed = client.get("/missing", headers={"Origin": "https://app.example"})
    denied = client.get("/missing", headers={"Origin": "https://other.example"})

    assert allowed.headers.get("Access-Control-Allow-Origin") == "https://app.example"
    assert "Access-Control-Allow-Origin" not in denied.headers
