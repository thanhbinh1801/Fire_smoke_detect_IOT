import builtins
import subprocess
import sys
from pathlib import Path

import pytest

import config


@pytest.fixture(params=["dotenv", "fallback"])
def env_loader(request, monkeypatch):
    if request.param == "dotenv":
        pytest.importorskip("dotenv")
    else:
        original_import = builtins.__import__

        def without_dotenv(name, *args, **kwargs):
            if name == "dotenv":
                raise ImportError("exercise built-in parser")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", without_dotenv)


def test_env_servo_values_are_parsed(env_loader, monkeypatch, tmp_path):
    keys = ("PWM_TEST_BACKEND", "PWM_TEST_HOLD", "PWM_TEST_PIN", "PWM_TEST_PULSE")
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    path.write_text(
        'PWM_TEST_BACKEND="kernel"\nPWM_TEST_HOLD=true\n'
        'PWM_TEST_PIN=19 # BCM\nPWM_TEST_PULSE=0.0024\n', encoding="utf-8"
    )
    assert config.load_env_file(str(path))
    assert config._env_str(keys[0]) == "kernel"
    assert config._env_bool(keys[1], False) is True
    assert config._env_int(keys[2], 0) == 19
    assert config._env_float(keys[3], 0) == .0024


def test_explicit_environment_takes_precedence(env_loader, monkeypatch, tmp_path):
    monkeypatch.setenv("PWM_TEST_OVERRIDE", "kernel")
    path = tmp_path / ".env"
    path.write_text("PWM_TEST_OVERRIDE=lgpio\n", encoding="utf-8")
    assert config.load_env_file(str(path))
    assert config._env_str("PWM_TEST_OVERRIDE") == "kernel"
    assert config.load_env_file(str(path), override=True)
    assert config._env_str("PWM_TEST_OVERRIDE") == "lgpio"


def test_missing_env_is_reported(env_loader, tmp_path):
    assert config.load_env_file(str(tmp_path / "missing.env")) is False


def test_example_bootstraps_current_rig_without_saved_calibration(tmp_path):
    script = '''
import config, importlib, json, sys
assert config.load_env_file('.env.example', override=True)
importlib.reload(config)
from aiming import NozzleController
c = NozzleController(sys.argv[1])
v = c.calibration.values
assert (v['length_cm'], v['width_cm']) == (28, 18)
assert (v['nozzle_x_cm'], v['nozzle_y_cm'], v['nozzle_height_cm']) == (14, -8, 31)
assert (v['camera_x_cm'], v['camera_y_cm'], v['camera_height_cm']) == (14, 9, 36)
assert (v['mechanism'], v['rotation_deg'], v['pan_sign'], v['tilt_sign']) == ('tilt_xy', 90, -1, -1)
assert c.calibration.ready and c.dry_run
assert c.calibration.image_to_floor(*v['corners'][2]) == __import__('pytest').approx((28, 18), abs=1e-4)
# Dashboard calibration still wins over .env defaults on subsequent starts.
v['nozzle_height_cm'] = 32
c.save(v)
assert NozzleController(sys.argv[1]).calibration.values['nozzle_height_cm'] == 32
print('Example configuration and saved calibration precedence passed')
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "new-rig.json")],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
