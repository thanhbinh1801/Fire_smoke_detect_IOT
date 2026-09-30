# web_state.py
"""
Module chia sẻ trạng thái giữa main loop (AI/camera) và web server (Flask).
Sử dụng threading.Lock để đảm bảo thread-safe khi đọc/ghi từ nhiều luồng.
"""

import threading
import time

# --- Shared frame buffer ---
_frame_lock = threading.Lock()
_latest_frame_jpg: bytes = b""   # JPEG bytes của frame mới nhất đã vẽ overlay

# --- Shared fire status ---
_status_lock = threading.Lock()
_fire_status = {
    "is_fire": False,
    "confidence": 0.0,
    "label": "",
    "cam_fps": 0.0,
    "ai_fps": 0.0,
    "updated_at": 0.0,
}

# --- Alert history (tối đa 50 bản ghi) ---
_alert_lock = threading.Lock()
_alert_history: list = []
MAX_ALERT_HISTORY = 50


# ── Ghi frame mới nhất (gọi từ main loop) ──────────────────────────────────

def set_frame(jpg_bytes: bytes):
    """Cập nhật frame JPEG mới nhất để web stream."""
    global _latest_frame_jpg
    with _frame_lock:
        _latest_frame_jpg = jpg_bytes


def get_frame() -> bytes:
    """Lấy frame JPEG mới nhất (thread-safe)."""
    with _frame_lock:
        return _latest_frame_jpg


# ── Ghi trạng thái phát hiện (gọi từ main loop) ────────────────────────────

def set_status(is_fire: bool, detections: list, cam_fps: float, ai_fps: float):
    """
    Cập nhật trạng thái hệ thống.
    detections: list of dict {"label": str, "conf": float, "box": [...]}
    """
    global _fire_status
    conf = max((d["conf"] for d in detections), default=0.0) if detections else 0.0
    label = detections[0]["label"] if detections else ""

    with _status_lock:
        _fire_status = {
            "is_fire": is_fire,
            "confidence": round(conf, 3),
            "label": label,
            "cam_fps": round(cam_fps, 1),
            "ai_fps": round(ai_fps, 1),
            "updated_at": time.time(),
        }

    # Ghi lịch sử cảnh báo khi có lửa
    if is_fire and detections:
        _add_alert(label, conf)


def get_status() -> dict:
    """Lấy trạng thái hiện tại (thread-safe)."""
    with _status_lock:
        return dict(_fire_status)


# ── Quản lý lịch sử alert ──────────────────────────────────────────────────

def _add_alert(label: str, conf: float):
    """Thêm bản ghi cảnh báo vào lịch sử (nội bộ)."""
    with _alert_lock:
        # Chống spam: không thêm nếu alert gần nhất < 5 giây trước
        if _alert_history:
            last_ts = _alert_history[-1]["timestamp"]
            if time.time() - last_ts < 5.0:
                return

        entry = {
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M:%S"),
            "label": label,
            "confidence": round(conf, 3),
        }
        _alert_history.append(entry)

        # Giới hạn 50 bản ghi mới nhất
        if len(_alert_history) > MAX_ALERT_HISTORY:
            _alert_history.pop(0)


def get_alert_history() -> list:
    """Lấy toàn bộ lịch sử cảnh báo (thread-safe)."""
    with _alert_lock:
        return list(reversed(_alert_history))  # Mới nhất lên đầu
