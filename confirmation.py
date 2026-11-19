from collections import deque
import os
import threading
import time

import cv2

import config


class FireConfirmer:
    def __init__(
        self,
        window_s=1.5,
        min_ratio=0.6,
        min_samples=4,
        threshold=0.4,
        hold_s=0.0,
        label="fire",
    ):
        self.window_s = max(0.05, float(window_s))
        self.min_ratio = max(0.0, min(1.0, float(min_ratio)))
        self.min_samples = max(1, int(min_samples))
        self.threshold = float(threshold)
        self.hold_s = max(0.0, float(hold_s))
        self.label = str(label)
        self._samples = deque()
        self._confirmed = False
        self._last_match_at = None
        self._last_result_time = 0.0

    def _prune(self, now):
        cutoff = now - self.window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def _window_satisfied(self):
        total = len(self._samples)
        if total < self.min_samples:
            return False
        positives = sum(1 for _, matched in self._samples if matched)
        return (positives / total) >= self.min_ratio

    def update(self, detections, now=None, result_time=None):
        current_now = time.monotonic() if now is None else float(now)
        should_record = True
        if result_time is not None:
            if result_time <= 0 or result_time == self._last_result_time:
                should_record = False
            else:
                self._last_result_time = float(result_time)

        if should_record:
            matched = any(
                item.get("label") == self.label
                and float(item.get("conf", 0.0)) >= self.threshold
                for item in (detections or ())
            )
            self._samples.append((current_now, matched))
            if matched:
                self._last_match_at = current_now

        self._prune(current_now)

        if self._window_satisfied():
            self._confirmed = True
        elif (
            self._confirmed
            and self.hold_s > 0.0
            and self._last_match_at is not None
            and (current_now - self._last_match_at) < self.hold_s
        ):
            self._confirmed = True
        else:
            self._confirmed = False

        return self._confirmed

    @property
    def is_confirmed(self):
        return self._confirmed

    def reset(self):
        self._samples.clear()
        self._confirmed = False
        self._last_match_at = None


def build_alarm_confirmer():
    fire_threshold = getattr(
        config,
        "FIRE_CONFIDENCE_THRESHOLD",
        getattr(config, "CONFIDENCE_THRESHOLD", 0.40),
    )
    return FireConfirmer(
        window_s=getattr(config, "FIRE_CONFIRM_WINDOW_SECONDS", 1.5),
        min_ratio=getattr(config, "FIRE_CONFIRM_MIN_RATIO", 0.6),
        min_samples=getattr(config, "FIRE_CONFIRM_MIN_SAMPLES", 4),
        threshold=fire_threshold,
        hold_s=getattr(config, "HOLD_FIRE_TIME", 1.5),
        label="fire",
    )


def build_smoke_confirmer():
    smoke_threshold = getattr(
        config,
        "SMOKE_CONFIDENCE_THRESHOLD",
        getattr(config, "CONFIDENCE_THRESHOLD", 0.38),
    )
    min_samples = int(
        getattr(
            config,
            "SMOKE_CONFIRM_MIN_SAMPLES",
            getattr(config, "SMOKE_CONFIRMATION_FRAMES", 2),
        )
    )
    return FireConfirmer(
        window_s=getattr(config, "SMOKE_CONFIRM_WINDOW_SECONDS", 2.0),
        min_ratio=getattr(config, "SMOKE_CONFIRM_MIN_RATIO", 0.5),
        min_samples=max(1, min_samples),
        threshold=smoke_threshold,
        hold_s=0.0,
        label="smoke",
    )


def build_pump_confirmer():
    return FireConfirmer(
        window_s=getattr(config, "PUMP_CONFIRM_WINDOW_SECONDS", 3.0),
        min_ratio=getattr(config, "PUMP_CONFIRM_MIN_RATIO", 0.7),
        min_samples=getattr(config, "PUMP_CONFIRM_MIN_SAMPLES", 8),
        threshold=getattr(config, "PUMP_CONFIDENCE_THRESHOLD", 0.60),
        hold_s=0.0,
        label="fire",
    )


class AsyncSnapshotSaver:
    """
    Bộ lưu ảnh snapshot bất đồng bộ trên luồng nền.
    Tránh việc cv2.imwrite ghi thẻ nhớ SD làm khựng luồng Camera -> AI -> Cảnh báo.
    """

    def __init__(self, snapshot_dir=None, cooldown_s=None):
        self.snapshot_dir = snapshot_dir or getattr(
            config, "SNAPSHOT_DIR", "data/snapshots"
        )
        self.cooldown_s = float(
            getattr(config, "SNAPSHOT_COOLDOWN", 2.0)
            if cooldown_s is None
            else cooldown_s
        )
        self._last_saved_at = 0.0
        self._saving = False
        self._lock = threading.Lock()

    def save_if_due(self, frame, now: float = None) -> bool:
        if not getattr(config, "SAVE_SNAPSHOT", False) or frame is None:
            return False
        current_now = time.time() if now is None else float(now)
        with self._lock:
            if self._saving or (current_now - self._last_saved_at) < self.cooldown_s:
                return False
            self._saving = True
            self._last_saved_at = current_now

        frame_copy = frame.copy()
        threading.Thread(
            target=self._write_worker,
            args=(frame_copy, current_now),
            daemon=True,
            name="AsyncSnapshotSaver",
        ).start()
        return True

    def _write_worker(self, frame, timestamp: float):
        try:
            os.makedirs(self.snapshot_dir, exist_ok=True)
            timestamp_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp))
            filename = os.path.join(
                self.snapshot_dir,
                f"alert_{timestamp_str}_{int(timestamp * 1000) % 1000}.jpg",
            )
            if not cv2.imwrite(filename, frame):
                print(f"[Snapshot] Lỗi: Không lưu được snapshot tại {filename}")
        except Exception as error:
            print(f"[Snapshot] Lỗi ghi ảnh cảnh báo: {error}")
        finally:
            with self._lock:
                self._saving = False
