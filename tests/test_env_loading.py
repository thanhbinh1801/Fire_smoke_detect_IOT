import builtins

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
