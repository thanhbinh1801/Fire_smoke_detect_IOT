import os
import builtins

import pytest

import actuators
import config


@pytest.fixture
def pwm_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(actuators, "_PWM_ROOT", str(tmp_path), raising=False)
    realpath = os.path.realpath

    def resolve(path, *args, **kwargs):
        if str(path).endswith(os.path.join("device", "driver")):
            return "/sys/bus/platform/drivers/pwm-gpio"
        return realpath(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", resolve)

    def chip(number, pin):
        root = tmp_path / f"pwmchip{number}"
        node = root / "device" / "of_node"
        node.mkdir(parents=True)
        (node / "gpios").write_bytes(b"".join(n.to_bytes(4, "big") for n in (7, pin, 0)))
        channel = root / "pwm0"
        channel.mkdir()
        for name, value in {"enable": "0", "period": "20000000", "duty_cycle": "0", "polarity": "normal"}.items():
            (channel / name).write_text(value)
        return channel

    return chip


def test_two_nozzle_axes_use_their_own_kernel_chip(pwm_tree, monkeypatch):
    # Kernel numbering need not match axis order, or start at zero.
    tilt = pwm_tree(2, 19)
    pan = pwm_tree(7, 18)
    monkeypatch.setattr(config, "PLATFORM", "pi")
    monkeypatch.setattr(config, "SERVO_PWM_BACKEND", "kernel", raising=False)
    monkeypatch.setattr(config, "NOZZLE_HOLD_POSITION", True)
    servo = actuators.NozzleServo()
    try:
        servo.move(60, 120)
        assert int((pan / "duty_cycle").read_text()) == 1133333
        assert int((tilt / "duty_cycle").read_text()) == 1766667
        assert servo.get_state()["pan"]["pwm_backend"] == "kernel"
        assert servo.get_state()["tilt"]["pwm_backend"] == "kernel"
    finally:
        servo.cleanup()
    assert (pan / "enable").read_text() == "0"
    assert (tilt / "enable").read_text() == "0"


def test_kernel_mode_requires_a_route_for_each_pin(pwm_tree, monkeypatch):
    pan = pwm_tree(0, 18)
    monkeypatch.setattr(config, "PLATFORM", "pi")
    monkeypatch.setattr(config, "SERVO_PWM_BACKEND", "kernel", raising=False)
    with pytest.raises(RuntimeError, match="GPIO19"):
        actuators.NozzleServo()
    assert (pan / "enable").read_text() == "0"


def test_sysfs_waits_for_udev_permissions(pwm_tree, monkeypatch):
    pan = pwm_tree(1, 18)
    original_open = builtins.open
    attempts = []

    def delayed_permissions(path, mode="r", *args, **kwargs):
        if os.path.normpath(str(path)) == os.path.normpath(str(pan / "enable")) and "+" in mode:
            attempts.append(mode)
            if len(attempts) <= 3:
                raise PermissionError("udev has not granted gpio access yet")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", delayed_permissions)
    servo = actuators._SysfsPWMServo(18)
    try:
        servo.angle = 90
        assert len(attempts) == 4
        assert (pan / "enable").read_text() == "1"
        assert (pan / "duty_cycle").read_text() == "1450000"
    finally:
        servo.close()


def test_sysfs_failure_does_not_fall_back_to_gpiozero(pwm_tree, monkeypatch):
    pwm_tree(0, 18)
    monkeypatch.setattr(config, "PLATFORM", "pi")

    def denied(*args, **kwargs):
        raise PermissionError("sysfs denied")

    monkeypatch.setattr(actuators, "_SysfsPWMServo", denied)
    with pytest.raises(RuntimeError, match="sysfs denied"):
        actuators.CameraServo()
