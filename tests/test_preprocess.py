import cv2
import numpy as np

from detector import FireSmokeDetector


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
