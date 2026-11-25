import json
import math
from types import SimpleNamespace

import pytest
from gpiozero import Device
from gpiozero.pins.mock import MockFactory, MockPWMPin

import config
import aiming
import web_server
from actuators import NozzleServo, WaterPump
from aiming import FloorCalibration, NozzleController


def calibrated(**changes):
    return dict(corners=[[0, 0], [1, 0], [1, 1], [0, 1]], mechanism="tilt_xy", **changes)


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PLATFORM", "laptop")
    monkeypatch.setattr(config, "NOZZLE_CALIBRATION_PATH", str(tmp_path / "calibration.json"))
    monkeypatch.setattr(config, "NOZZLE_DRY_RUN", True)
    monkeypatch.setattr(config, "PUMP_CONFIRM_MIN_SAMPLES", 2)
    clock = SimpleNamespace(mono=100.0, wall=1000.0)
    monkeypatch.setattr(aiming.time, "monotonic", lambda: clock.mono)
    monkeypatch.setattr(aiming.time, "time", lambda: clock.wall)
    servo, pump = NozzleServo(), WaterPump()
    controller = NozzleController()
    controller.save(calibrated())
    clock.mono += config.SERVO_SETTLE_SECONDS + .01
    clock.wall += config.SERVO_SETTLE_SECONDS + .01
    pump.arm(True)
    yield controller, servo, pump, clock
    pump.cleanup()
    servo.cleanup()


def tick(rig, x=0.5, y=0.5, delay=0.2, frame_time=None, detections=None, error=None):
    controller, servo, pump, clock = rig
    clock.mono += delay
    clock.wall += delay
    if detections is None:
        detections = [{"label": "fire", "conf": 0.9,
                       "box": [(x-.01)*640, (y-.01)*480, (x+.01)*640, (y+.01)*480]}]
    controller.update(detections, clock.wall, clock.mono if frame_time is None else frame_time,
                      (480, 640, 3), servo, pump, error)


def test_floor_mapping_and_height_parallax():
    cal = FloorCalibration(calibrated(camera_x_cm=20, camera_y_cm=10,
                                      target_height_cm=6))
    x, y = cal.image_to_floor(.25, .25, 4/3)
    assert x == pytest.approx(20 + (10.75-20)*30/36)
    assert y == pytest.approx(10 + (7.75-10)*30/36)


def test_perspective_mapping():
    cal = FloorCalibration({"corners": [[.2,.1],[.8,.2],[.9,.8],[.1,.9]]})
    for uv, xy in zip(cal.values["corners"], [(0,0),(43,0),(43,31),(0,31)]):
        assert cal.image_to_floor(*uv) == pytest.approx(xy, abs=1e-4)


@pytest.mark.parametrize("values", [
    {"corners": [[0,0]]*4}, {"corners": [[0,0],[1,1],[1,0],[0,1]]},
    {"target_height_cm": 29}, {"camera_height_cm": 0}, {"pan_sign": 0},
    {"length_cm": float("nan")}, {"mechanism": "unknown"},
    {"water_samples": [{"x": 1}]}, {"corners": [[0,0],[1,0],[1,1],[0,float("inf")]]},
])
def test_invalid_calibration_rejected(values):
    with pytest.raises(ValueError):
        FloorCalibration(values)


def test_outside_region_aspect_and_unreachable_rejected():
    cal = FloorCalibration({"corners": [[.1,.1],[.9,.1],[.9,.9],[.1,.9]]})
    with pytest.raises(ValueError):
        cal.image_to_floor(.01, .5)
    with pytest.raises(ValueError):
        cal.image_to_floor(.5, .5, 16/9)
    with pytest.raises(ValueError):
        cal.angles(21.5, 31)  # yaw +90 exceeds conservative 30..150 servo range


def test_two_axis_geometry_matches_forward_ray():
    cal = FloorCalibration(calibrated())
    for x, y in [(0,0), (43,0), (43,31), (0,31), (21.5,15.5)]:
        pan, tilt = cal.angles(x,y)
        p, t = math.radians(pan-config.NOZZLE_PAN_ZERO), math.radians(tilt-config.NOZZLE_TILT_ZERO)
        assert 21.5 + 29*math.tan(p) == pytest.approx(x)
        assert 15.5 + 29*math.tan(t)/math.cos(p) == pytest.approx(y)


def test_yaw_fold_reaches_both_sides():
    cal = FloorCalibration({"corners": [[0,0],[1,0],[1,1],[0,1]]})
    a, b = cal.angles(43, 31), cal.angles(0, 0)
    assert a[0] == pytest.approx(b[0])
    assert a[1]-90 == pytest.approx(-(b[1]-90))


def test_water_offsets_are_command_corrections():
    cal = FloorCalibration(calibrated(water_samples=[{"x":21.5,"y":15.5,"dx":2,"dy":0}]))
    pan, tilt = cal.angles(21.5,15.5)
    assert pan == pytest.approx(90 + math.degrees(math.atan2(2,29)))
    assert tilt == 90


def test_save_load_and_invalid_save_is_atomic(rig):
    c, _, _, _ = rig
    before = json.loads(open(c.path, encoding="utf-8").read())
    with pytest.raises(ValueError):
        c.save({"length_cm": -1})
    assert json.loads(open(c.path, encoding="utf-8").read()) == before
    assert NozzleController(c.path).calibration.ready


def test_room_settings_can_be_saved_before_image_corners(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PLATFORM", "laptop")
    monkeypatch.setattr(config, "NOZZLE_CALIBRATION_PATH", str(tmp_path / "room.json"))
    monkeypatch.setattr(web_server.FireMonitor, "start", lambda self: None)
    monitor = web_server.FireMonitor()
    client = web_server.create_app(monitor).test_client()
    response = client.post("/api/nozzle", json={"action": "configure", "calibration": {
        "length_cm": 30, "width_cm": 11, "camera_height_cm": 36}})
    assert response.status_code == 200, response.get_json()
    reloaded = NozzleController(monitor._nozzle.path)
    assert reloaded.calibration.values["length_cm"] == 30
    assert reloaded.calibration.values["width_cm"] == 11
    assert reloaded.calibration.values["camera_height_cm"] == 36
    assert not reloaded.calibration.ready
    with pytest.raises(ValueError, match="Chưa hiệu chuẩn"):
        reloaded.calibration.image_to_floor(.5, .5)


def test_room_settings_update_saved_geometry_without_replacing_corners(rig, monkeypatch):
    c, servo, pump, _ = rig
    monkeypatch.setattr(web_server.FireMonitor, "start", lambda self: None)
    monitor = web_server.FireMonitor()
    monitor._nozzle, monitor._servo, monitor._pump = c, servo, pump
    client = web_server.create_app(monitor).test_client()
    response = client.post("/api/nozzle", json={"action": "configure", "calibration": {
        "length_cm": 30, "width_cm": 11, "corners": []}})
    assert response.status_code == 200, response.get_json()
    assert not pump.is_armed()
    assert c.calibration.image_to_floor(.5, .5) == pytest.approx((15, 5.5))
    assert NozzleController(c.path).calibration.ready


def test_dry_cycle_never_sprays_or_repeats_motion(rig):
    c, servo, pump, clock = rig
    tick(rig); tick(rig)
    assert c.phase == "aiming"
    tick(rig, delay=1)
    assert c.phase == "dry_complete"
    assert pump.get_state()["state"] == "off"
    tick(rig)
    assert c.phase == "dry_complete"


def test_auto_uses_post_settle_capture_not_completion_time(rig):
    c, servo, pump, clock = rig
    c.dry_run = False
    tick(rig); tick(rig)
    assert c.phase == "aiming"
    old_frame = c.settled_after - .1
    tick(rig, delay=.9, frame_time=old_frame)
    assert pump.get_state()["state"] == "off"
    tick(rig)
    assert pump.get_state()["state"] == "on"
    assert c.phase == "spraying"
    pump.stop()
    tick(rig); tick(rig)
    assert pump.get_state()["state"] == "off"  # cooldown preserved


def test_different_targets_do_not_share_confirmation(rig):
    c, _, pump, _ = rig
    tick(rig, x=.1); tick(rig, x=.9)
    assert c.phase == "idle"
    tick(rig, x=.9)
    assert c.phase == "confirming"
    assert pump.get_state()["state"] == "off"


@pytest.mark.parametrize("fault", ["lost", "error", "stale", "disarm"])
def test_aiming_faults_block_spray(rig, fault):
    c, _, pump, clock = rig
    c.dry_run = False
    tick(rig); tick(rig)
    if fault == "disarm":
        pump.arm(False)
    tick(rig, delay=1, detections=[] if fault == "lost" else None,
         error="AI failed" if fault == "error" else None,
         frame_time=clock.mono-2 if fault == "stale" else None)
    assert c.phase == "idle"
    assert pump.get_state()["state"] == "off"


def test_nan_and_partial_servo_targets_do_not_move(rig):
    _, servo, _, _ = rig
    old = servo.get_state()
    for angles in [(100, 200), (float("nan"), 90)]:
        with pytest.raises(ValueError):
            servo.move(*angles)
        assert servo.get_state() == old


def test_nozzle_http_controls_and_polling_preserve_watchdog(rig, monkeypatch):
    c, servo, pump, _ = rig
    monkeypatch.setattr(web_server.FireMonitor, "start", lambda self: None)
    monitor = web_server.FireMonitor()
    monitor._nozzle, monitor._servo, monitor._pump = c, servo, pump
    monitor._state["frame_size"] = [640,480]
    monitor._last_control_at = 1
    client = web_server.create_app(monitor).test_client()
    assert client.get("/api/status").status_code == 200
    assert monitor._last_control_at == 1
    assert client.post("/api/pump", json={"action":"on"}).status_code == 400
    assert client.post("/api/nozzle", json={"action":"aim","u":.5,"v":.5}).status_code == 200
    assert not pump.is_armed()
    assert client.post("/api/nozzle", json={"action":"dry_run","enabled":"false"}).status_code == 400
    assert client.post("/api/nozzle", json=[]).status_code == 400
    assert client.post("/api/nozzle", json={"action":"calibrate","calibration":{"corners":[]}}).status_code == 400
    assert client.post("/api/pump", json={"action":"stop"}).status_code == 200
    assert c.phase == "idle" and not pump.is_armed()


def test_real_nozzle_rejects_unconfigured_or_conflicting_pins(monkeypatch):
    monkeypatch.setattr(config, "PLATFORM", "pi")
    for tilt in (-1, config.NOZZLE_PAN_PIN, config.PUMP_PIN):
        monkeypatch.setattr(config, "NOZZLE_TILT_PIN", tilt)
        with pytest.raises(ValueError):
            NozzleServo()


def test_two_gpio_outputs_are_independent_and_detach(monkeypatch):
    old_factory = Device.pin_factory
    Device.pin_factory = MockFactory(pin_class=MockPWMPin)
    monkeypatch.setattr(config, "PLATFORM", "pi")
    monkeypatch.setattr(config, "NOZZLE_PAN_PIN", 18)
    monkeypatch.setattr(config, "NOZZLE_TILT_PIN", 19)
    monkeypatch.setattr(config, "NOZZLE_HOLD_POSITION", False)
    monkeypatch.setattr(config, "SERVO_SETTLE_SECONDS", .02)
    servo = NozzleServo()
    try:
        servo.move(105, 75)
        assert servo.pan._servo.pwm_device.pin is not servo.tilt._servo.pwm_device.pin
        assert servo.pan._servo.angle == pytest.approx(105)
        assert servo.tilt._servo.angle == pytest.approx(75)
        aiming.time.sleep(.04)
        assert servo.pan._servo.value is None
        assert servo.tilt._servo.value is None
    finally:
        servo.cleanup()
        Device.pin_factory.reset()
        Device.pin_factory = old_factory


def test_watchdog_expiry_blocks_ready_spray_before_actuation(rig, monkeypatch):
    c, servo, pump, clock = rig
    c.dry_run = False
    tick(rig); tick(rig)
    assert c.phase == "aiming"
    clock.mono += 1
    clock.wall += 1
    monkeypatch.setattr(web_server.FireMonitor, "start", lambda self: None)
    monitor = web_server.FireMonitor()
    monitor._nozzle = c
    monitor._last_control_at = clock.mono - config.ACTUATOR_WATCHDOG_SECONDS - 1
    monitor._advance_nozzle([{"label":"fire","conf":.9,"box":[310,230,330,250]}],
                            clock.wall, clock.mono, (480,640,3), servo, pump)
    assert not pump.is_armed()
    assert pump.get_state()["state"] == "off"
    assert c.phase == "idle"


def test_sensor_failure_stops_active_automatic_burst(rig):
    c, _, pump, _ = rig
    c.dry_run = False
    tick(rig); tick(rig); tick(rig, delay=1)
    assert pump.get_state()["state"] == "on"
    tick(rig, error="camera/inference unavailable")
    assert pump.get_state()["state"] == "off"
    assert c.phase == "idle"


def test_camera_offset_defaults_and_saved_calibration_precedence(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "NOZZLE_X_CM", 21.5)
    monkeypatch.setattr(config, "NOZZLE_Y_CM", 15.5)
    monkeypatch.setattr(config, "NOZZLE_CAMERA_OFFSET_X_CM", 3)
    monkeypatch.setattr(config, "NOZZLE_CAMERA_OFFSET_Y_CM", -2)
    monkeypatch.setattr(config, "NOZZLE_CAMERA_HEIGHT_CM", 36)
    controller = NozzleController(str(tmp_path / "calibration.json"))
    assert controller.calibration.values["camera_x_cm"] == 24.5
    assert controller.calibration.values["camera_y_cm"] == 13.5
    controller.save(calibrated(camera_x_cm=25, camera_y_cm=14))
    monkeypatch.setattr(config, "NOZZLE_CAMERA_OFFSET_X_CM", 5)
    reloaded = NozzleController(controller.path)
    assert reloaded.calibration.values["camera_x_cm"] == 25
    assert reloaded.calibration.values["camera_y_cm"] == 14
