import cv2
import numpy as np

import config
from detector import FireSmokeDetector
from preprocessing import FramePreprocessor, parse_roi


def _legacy_preprocess(detector, frame):
    orig_h, orig_w = frame.shape[:2]
    scale = min(detector.input_w / orig_w, detector.input_h / orig_h)
    resized_w = max(1, int(round(orig_w * scale)))
    resized_h = max(1, int(round(orig_h * scale)))
    resized = cv2.resize(frame, (resized_w, resized_h))
    pad_x = (detector.input_w - resized_w) // 2
    pad_y = (detector.input_h - resized_h) // 2
    model_frame = np.full((detector.input_h, detector.input_w, 3), 114, dtype=np.uint8)
    model_frame[pad_y:pad_y + resized_h, pad_x:pad_x + resized_w] = resized
    rgb_tensor = cv2.cvtColor(model_frame, cv2.COLOR_BGR2RGB)
    tensor = rgb_tensor.transpose((2, 0, 1)).astype(np.float32) / 255.0
    return np.expand_dims(tensor, axis=0)


def test_blob_from_image_matches_legacy_preprocess_and_inference():
    detector = FireSmokeDetector()
    rng = np.random.default_rng(123)
    for shape in ((480, 640, 3), (320, 320, 3), (720, 1280, 3)):
        frame = rng.integers(0, 256, size=shape, dtype=np.uint8)
        legacy_blob = _legacy_preprocess(detector, frame)
        new_blob, _ = detector.preprocess(frame)

        assert legacy_blob.shape == new_blob.shape
        assert new_blob.dtype == np.float32
        assert float(np.max(np.abs(legacy_blob - new_blob))) < 1e-6

        out_legacy = detector.infer(legacy_blob)[0]
        out_new = detector.infer(new_blob)[0]
        assert float(np.max(np.abs(out_legacy[:, :4, :] - out_new[:, :4, :]))) < 1e-3
        assert float(np.max(np.abs(out_legacy[:, 4:, :] - out_new[:, 4:, :]))) < 1e-5


def test_frame_preprocessor_enhancements_and_channel_normalization():
    prep = FramePreprocessor(
        input_w=320,
        input_h=320,
        enable_clahe=True,
        clahe_clip_limit=2.0,
        gamma=0.85,
        denoise_kernel=3,
        auto_wb=True,
        sharpen=True,
        roi_spec="0.1,0.1,0.9,0.9",
    )
    assert prep.has_enhancements

    rng = np.random.default_rng(7)
    # Test BGR, Grayscale (2D), and BGRA (4-channel)
    bgr = rng.integers(10, 240, size=(480, 640, 3), dtype=np.uint8)
    gray = rng.integers(10, 240, size=(480, 640), dtype=np.uint8)
    bgra = rng.integers(10, 240, size=(480, 640, 4), dtype=np.uint8)

    for sample in (bgr, gray, bgra):
        blob, meta = prep.preprocess(sample)
        assert blob.shape == (1, 3, 320, 320)
        assert blob.dtype == np.float32
        assert 0.0 <= float(blob.min()) <= float(blob.max()) <= 1.0
        assert len(meta) == 5
        assert meta[0] == 480 and meta[1] == 640

    roi_box = parse_roi("0.25,0.25,0.75,0.75", 640, 480)
    assert roi_box == (160, 120, 480, 360)


def test_env_loaded_in_config():
    assert hasattr(config, "CONFIDENCE_THRESHOLD")
    assert hasattr(config, "FIRE_CONFIDENCE_THRESHOLD")
    assert hasattr(config, "SMOKE_CONFIDENCE_THRESHOLD")
    assert hasattr(config, "TELEGRAM_BOT_TOKEN")
    assert hasattr(config, "PREPROCESS_ENABLE_CLAHE")

