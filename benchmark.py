import argparse
import os
import shutil
import subprocess
import time

import cv2
import numpy as np
import onnxruntime as ort

import config
from detector import FireSmokeDetector


def _load_frames(source, count, width, height):
    if source == "synthetic":
        rng = np.random.default_rng(42)
        frames = []
        for idx in range(min(count, 16)):
            frame = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
            x1 = (idx * 25) % max(1, width - 120)
            y1 = (idx * 15) % max(1, height - 120)
            cv2.rectangle(frame, (x1, y1), (x1 + 100, y1 + 100), (0, 80, 255), -1)
            frames.append(frame)
        return [frames[i % len(frames)] for i in range(count)]

    if os.path.isdir(source):
        exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
        files = sorted(
            os.path.join(source, name)
            for name in os.listdir(source)
            if name.lower().endswith(exts)
        )
        loaded = [cv2.imread(path) for path in files]
        loaded = [img for img in loaded if img is not None]
        if not loaded:
            raise RuntimeError(f"Không tìm thấy ảnh hợp lệ trong thư mục: {source}")
        return [loaded[i % len(loaded)] for i in range(count)]

    if os.path.isfile(source):
        image = cv2.imread(source)
        if image is not None:
            return [image for _ in range(count)]
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Không mở được nguồn video/ảnh: {source}")
        frames = []
        while len(frames) < count:
            ok, frame = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
                if not ok:
                    break
            frames.append(frame)
        cap.release()
        if not frames:
            raise RuntimeError(f"Không đọc được frame nào từ: {source}")
        return frames

    if str(source).isdigit():
        cap = cv2.VideoCapture(int(source))
        if not cap.isOpened():
            raise RuntimeError(f"Không mở được webcam index {source}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        frames = []
        while len(frames) < count:
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
        cap.release()
        return frames

    raise ValueError(f"Nguồn không hợp lệ: {source}")


def _query_pi_metrics():
    vcgencmd = shutil.which("vcgencmd")
    if not vcgencmd:
        return None
    metrics = {}
    for key, arg in (("temp", "measure_temp"), ("throttled", "get_throttled")):
        try:
            out = subprocess.check_output(
                [vcgencmd, arg], text=True, timeout=2.0
            ).strip()
            metrics[key] = out
        except Exception:
            pass
    return metrics or None


def _summarize(values_ms):
    arr = np.asarray(values_ms, dtype=np.float64)
    return {
        "mean": float(np.mean(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
    }


def run_benchmark(source="synthetic", frames=100, warmup=10, threads=3, model_path=None):
    detector = FireSmokeDetector(model_path=model_path)
    if threads and threads > 0:
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = int(threads)
        detector.session = ort.InferenceSession(
            detector.model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )

    total_needed = max(1, int(warmup) + int(frames))
    sample_frames = _load_frames(
        source, total_needed, config.FRAME_WIDTH, config.FRAME_HEIGHT
    )

    for idx in range(int(warmup)):
        detector.detect(sample_frames[idx % len(sample_frames)])

    pre_times = []
    infer_times = []
    post_times = []
    total_times = []

    started_wall = time.perf_counter()
    for idx in range(int(frames)):
        frame = sample_frames[(int(warmup) + idx) % len(sample_frames)]
        t0 = time.perf_counter()
        blob, meta = detector.preprocess(frame)
        t1 = time.perf_counter()
        outputs = detector.infer(blob)
        t2 = time.perf_counter()
        detector.postprocess(outputs, meta)
        t3 = time.perf_counter()

        pre_times.append((t1 - t0) * 1000.0)
        infer_times.append((t2 - t1) * 1000.0)
        post_times.append((t3 - t2) * 1000.0)
        total_times.append((t3 - t0) * 1000.0)
    elapsed_wall = time.perf_counter() - started_wall

    report = {
        "source": source,
        "frames": int(frames),
        "threads": int(threads),
        "input_size": (detector.input_w, detector.input_h),
        "preprocess_ms": _summarize(pre_times),
        "infer_ms": _summarize(infer_times),
        "postprocess_ms": _summarize(post_times),
        "total_ms": _summarize(total_times),
        "fps": float(frames) / max(1e-9, elapsed_wall),
        "pi_metrics": _query_pi_metrics(),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description="Benchmark pipeline nhận diện lửa/khói")
    parser.add_argument("--source", default="synthetic")
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--threads", type=int, default=3)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    report = run_benchmark(
        source=args.source,
        frames=args.frames,
        warmup=args.warmup,
        threads=args.threads,
        model_path=args.model,
    )
    print("=" * 64)
    print(
        f"Source: {report['source']} | Frames: {report['frames']} | "
        f"Threads: {report['threads']} | Input: {report['input_size'][0]}x{report['input_size'][1]}"
    )
    print("-" * 64)
    for stage, key in (
        ("Preprocess", "preprocess_ms"),
        ("Inference ", "infer_ms"),
        ("Postproc  ", "postprocess_ms"),
        ("Total     ", "total_ms"),
    ):
        stats = report[key]
        print(
            f"{stage}: mean={stats['mean']:6.2f} ms | "
            f"p50={stats['p50']:6.2f} ms | p95={stats['p95']:6.2f} ms | "
            f"min={stats['min']:6.2f} ms | max={stats['max']:6.2f} ms"
        )
    print("-" * 64)
    print(f"Throughput: {report['fps']:.2f} FPS")
    if report["pi_metrics"]:
        print(f"Raspberry Pi: {report['pi_metrics']}")
    print("=" * 64)


if __name__ == "__main__":
    main()
