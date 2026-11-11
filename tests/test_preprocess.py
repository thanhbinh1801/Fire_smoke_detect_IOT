import cv2
import numpy as np

from detector import FireSmokeDetector


def _reference_preprocess(detector, frame):
    orig_h, orig_w = frame.shape[:2]
    scale = min(detector.input_w / orig_w, detector.input_h / orig_h)
    resized_w = max(1, int(round(orig_w * scale)))
    resized_h = max(1, int(round(orig_h * scale)))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=interp)
    pad_x = (detector.input_w - resized_w) // 2
    pad_y = (detector.input_h - resized_h) // 2
    model_frame = np.full((detector.input_h, detector.input_w, 3), 114, dtype=np.uint8)
    model_frame[pad_y:pad_y + resized_h, pad_x:pad_x + resized_w] = resized
    rgb_tensor = cv2.cvtColor(model_frame, cv2.COLOR_BGR2RGB)
    tensor = rgb_tensor.transpose((2, 0, 1)).astype(np.float32) / 255.0
    return np.expand_dims(tensor, axis=0)


def test_blob_from_image_matches_reference_preprocess_and_inference():
    detector = FireSmokeDetector()
    rng = np.random.default_rng(123)
    for shape in ((480, 640, 3), (320, 320, 3), (720, 1280, 3)):
        frame = rng.integers(0, 256, size=shape, dtype=np.uint8)
        ref_blob = _reference_preprocess(detector, frame)
        new_blob, _ = detector.preprocess(frame)

        assert ref_blob.shape == new_blob.shape
        assert new_blob.dtype == np.float32
        assert float(np.max(np.abs(ref_blob - new_blob))) < 1e-6

        out_ref = detector.infer(ref_blob)[0]
        out_new = detector.infer(new_blob)[0]
        assert float(np.max(np.abs(out_ref[:, :4, :] - out_new[:, :4, :]))) < 1e-3
        assert float(np.max(np.abs(out_ref[:, 4:, :] - out_new[:, 4:, :]))) < 1e-5


def test_roi_zoom_verifies_small_weak_candidate_and_maps_coordinates():
    detector = FireSmokeDetector()
    detector.conf_threshold = 0.40
    detector.roi_candidate_threshold = 0.22
    detector.roi_zoom_enabled = True

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    call_count = {"n": 0}

    def fake_infer(blob):
        call_count["n"] += 1
        preds = np.zeros((1, 6, 2100), dtype=np.float32)
        if call_count["n"] == 1:
            preds[0, 0, 0] = 225.0
            preds[0, 1, 0] = 190.0
            preds[0, 2, 0] = 12.0
            preds[0, 3, 0] = 12.0
            preds[0, 4, 0] = 0.28
        else:
            preds[0, 0, 0] = 160.0
            preds[0, 1, 0] = 160.0
            preds[0, 2, 0] = 24.0
            preds[0, 3, 0] = 24.0
            preds[0, 4, 0] = 0.72
        return [preds]

    detector.infer = fake_infer
    detections = detector.detect(frame)
    assert call_count["n"] == 2
    assert len(detections) == 1
    assert detections[0]["label"] == "fire"
    assert abs(detections[0]["conf"] - 0.72) < 1e-4
    x1, y1, x2, y2 = detections[0]["box"]
    assert 430 <= (x1 + x2) // 2 <= 470
    assert 280 <= (y1 + y2) // 2 <= 320
