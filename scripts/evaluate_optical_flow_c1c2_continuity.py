from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def read(path: Path) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames or fps <= 0:
        raise RuntimeError(f"No frames in {path}")
    return frames, fps


def flow(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    first_gray = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
    second_gray = cv2.cvtColor(second, cv2.COLOR_BGR2GRAY)
    return cv2.calcOpticalFlowFarneback(
        first_gray, second_gray, None, 0.5, 5, 21, 4, 7, 1.5, 0
    )


def resize(frame: np.ndarray, reference: np.ndarray) -> np.ndarray:
    if frame.shape[:2] == reference.shape[:2]:
        return frame
    return cv2.resize(frame, (reference.shape[1], reference.shape[0]))


def active_mask(
    masks: list[np.ndarray] | None,
    index: int,
    reference: np.ndarray,
) -> np.ndarray | None:
    if not masks:
        return None
    mask = resize(masks[min(max(index, 0), len(masks) - 1)], reference)
    return cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY) > 12


def epe(value: np.ndarray, reference: np.ndarray, active: np.ndarray | None) -> float:
    error = np.linalg.norm(value - reference, axis=2)
    if active is not None and np.any(active):
        return float(error[active].mean())
    return float(error.mean())


def magnitude(value: np.ndarray, active: np.ndarray | None) -> float:
    result = np.linalg.norm(value, axis=2)
    if active is not None and np.any(active):
        return float(result[active].mean())
    return float(result.mean())


def seam_metrics(
    source: list[np.ndarray],
    candidate: list[np.ndarray],
    seam_index: int,
    window: int,
    masks: list[np.ndarray] | None,
) -> dict[str, float]:
    first_pair = max(0, seam_index - window)
    last_pair = min(len(source) - 2, len(candidate) - 2, seam_index + window - 1)
    pair_indices = list(range(first_pair, last_pair + 1))
    source_flows = []
    candidate_flows = []
    c1_errors = []
    for index in pair_indices:
        reference = source[index]
        source_value = flow(reference, source[index + 1])
        candidate_value = flow(
            resize(candidate[index], reference),
            resize(candidate[index + 1], reference),
        )
        active = active_mask(masks, index + 1, reference)
        source_flows.append(source_value)
        candidate_flows.append(candidate_value)
        c1_errors.append(epe(candidate_value, source_value, active))

    c2_errors = []
    source_acceleration = []
    for offset in range(len(pair_indices) - 1):
        index = pair_indices[offset] + 1
        active = active_mask(masks, index, source[index])
        source_delta = source_flows[offset + 1] - source_flows[offset]
        candidate_delta = candidate_flows[offset + 1] - candidate_flows[offset]
        c2_errors.append(epe(candidate_delta, source_delta, active))
        source_acceleration.append(magnitude(source_delta, active))

    seam_pair = seam_index - 1
    seam_offset = seam_pair - first_pair
    return {
        "seam_flow_epe": float(c1_errors[seam_offset]),
        "window_flow_epe_mean": float(np.mean(c1_errors)),
        "window_acceleration_epe_mean": float(np.mean(c2_errors)),
        "source_acceleration_magnitude_mean": float(
            np.mean(source_acceleration)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--start-sec", required=True, type=float)
    parser.add_argument("--end-sec", required=True, type=float)
    parser.add_argument("--window-frames", type=int, default=6)
    parser.add_argument("--mask", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    source, fps = read(args.source)
    candidate, candidate_fps = read(args.candidate)
    if abs(fps - candidate_fps) > 0.01:
        raise ValueError(f"FPS mismatch: {fps} vs {candidate_fps}")
    masks = read(args.mask)[0] if args.mask else None
    report = {
        "metric": "source-relative optical-flow C1 velocity and C2 acceleration EPE",
        "source": str(args.source),
        "candidate": str(args.candidate),
        "fps": fps,
        "window_frames": args.window_frames,
        "start": seam_metrics(
            source,
            candidate,
            round(args.start_sec * fps),
            args.window_frames,
            masks,
        ),
        "end": seam_metrics(
            source,
            candidate,
            round(args.end_sec * fps) + 1,
            args.window_frames,
            masks,
        ),
        "note": "Zero is ideal; rank candidates against the same source and interval.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
