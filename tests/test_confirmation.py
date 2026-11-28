from confirmation import FireConfirmer, build_alarm_confirmer, build_pump_confirmer


def test_transient_fire_under_window_not_confirmed():
    confirmer = FireConfirmer(
        window_s=1.5, min_ratio=0.6, min_samples=4, threshold=0.4, hold_s=1.5
    )
    fire = [{"label": "fire", "conf": 0.75, "box": (10, 10, 50, 50)}]

    assert not confirmer.update(fire, now=0.0, result_time=1.0)
    assert not confirmer.update(fire, now=0.25, result_time=2.0)
    assert not confirmer.update([], now=0.50, result_time=3.0)
    assert not confirmer.update([], now=0.75, result_time=4.0)
    assert not confirmer.update([], now=1.00, result_time=5.0)


def test_sustained_fire_confirmed_and_holds_then_expires():
    confirmer = FireConfirmer(
        window_s=1.5, min_ratio=0.6, min_samples=4, threshold=0.4, hold_s=1.5
    )
    fire = [{"label": "fire", "conf": 0.75, "box": (10, 10, 50, 50)}]

    assert not confirmer.update(fire, now=0.0, result_time=1.0)
    assert not confirmer.update(fire, now=0.4, result_time=2.0)
    assert not confirmer.update(fire, now=0.8, result_time=3.0)
    assert confirmer.update(fire, now=1.2, result_time=4.0)

    assert confirmer.update([], now=1.6, result_time=5.0)
    assert confirmer.update([], now=2.4, result_time=6.0)
    assert not confirmer.update([], now=2.8, result_time=7.0)


def test_duplicate_result_time_ignored():
    confirmer = FireConfirmer(
        window_s=1.5, min_ratio=0.6, min_samples=3, threshold=0.4, hold_s=0.0
    )
    fire = [{"label": "fire", "conf": 0.8, "box": (0, 0, 20, 20)}]

    assert not confirmer.update(fire, now=0.0, result_time=10.0)
    assert not confirmer.update(fire, now=0.05, result_time=10.0)
    assert not confirmer.update(fire, now=0.10, result_time=10.0)


def test_alarm_and_pump_confirm_on_third_distinct_result(monkeypatch):
    import config
    monkeypatch.setattr(config, "FIRE_CONFIDENCE_THRESHOLD", 0.35)
    monkeypatch.setattr(config, "PUMP_CONFIDENCE_THRESHOLD", 0.35)
    monkeypatch.setattr(config, "FIRE_CONFIRM_MIN_SAMPLES", 3)
    monkeypatch.setattr(config, "PUMP_CONFIRM_MIN_SAMPLES", 3)
    alarm = build_alarm_confirmer()
    pump = build_pump_confirmer()
    fire = [{"label": "fire", "conf": 0.35, "box": (0, 0, 20, 20)}]
    for confirmer in (alarm, pump):
        assert not confirmer.update(fire, now=0, result_time=1)
        assert not confirmer.update(fire, now=.1, result_time=1)
        assert not confirmer.update(fire, now=.2, result_time=2)
        assert confirmer.update(fire, now=.3, result_time=3)
        confirmer.reset()
        for idx in range(3):
            assert not confirmer.update([dict(fire[0], conf=.349)],
                                        now=idx*.1, result_time=idx+1)
