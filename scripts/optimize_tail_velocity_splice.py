from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from evaluate_optical_flow_epe import seam_metrics
from splice_overlapping_segments import read_frames, remove_letterbox


def hermite_unit(u: np.ndarray, start_slope: float, end_slope: float) -> np.ndarray:
    """Cubic Hermite curve from 0 to 1 with controllable endpoint slopes."""
    h10 = u * u * u - 2.0 * u * u + u
    h01 = -2.0 * u * u * u + 3.0 * u * u
    h11 = u * u * u - u * u
    return h10 * start_slope + h01 + h11 * end_slope


def interpolate(frames: list[np.ndarray], position: float) -> np.ndarray:
    lower = int(np.floor(position))
    upper = min(len(frames) - 1, lower + 1)
    alpha = float(position - lower)
    if upper == lower or alpha <= 1e-8:
        return frames[lower].copy()
    return cv2.addWeighted(frames[lower], 1.0 - alpha, frames[upper], alpha, 0.0)


def make_positions(
    source_count: int,
    target_count: int,
    tail_frames: int,
    end_slope: float,
) -> np.ndarray | None:
    positions = np.linspace(0.0, source_count - 1.0, target_count)
    tail_start = target_count - tail_frames
    if tail_start < 1 or tail_frames < 3:
        return None
    start_position = float(positions[tail_start])
    u = np.linspace(0.0, 1.0, tail_frames)
    normalized = hermite_unit(u, 1.0, end_slope)
    tail = start_position + normalized * (
        (source_count - 1.0) - start_position
    )
    positions[tail_start:] = tail
    # Reject reverse motion, duplicate scheduling, or overshoot. The tolerance
    # still permits very slow but strictly forward motion near the endpoint.
    if (
        np.any(np.diff(positions) <= 1e-5)
        or positions.min() < -1e-6
        or positions.max() > source_count - 1.0 + 1e-6
    ):
        return None
    return positions


def write_video(
    path: Path,
    frames: list[np.ndarray],
    fps: float,
    size: tuple[int, int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size
    )
    if not writer.isOpened():
        raise RuntimeError(f"Cannot create video: {path}")
    for frame in frames:
        writer.write(frame)
    writer.release()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Search a monotonic tail-only timing curve that minimizes seam "
            "optical-flow discontinuity without regenerating frames."
        )
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--generated", required=True, type=Path)
    parser.add_argument("--start-sec", required=True, type=float)
    parser.add_argument("--duration-sec", required=True, type=float)
    parser.add_argument("--tail-frames", default="6,8,10,12,15,18")
    parser.add_argument(
        "--end-slopes",
        default="0.15,0.25,0.4,0.55,0.7,0.85,1.0,1.15,1.3,1.5,1.75,2.0,2.25",
    )
    parser.add_argument("--window-frames", type=int, default=6)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    source, source_fps, source_size = read_frames(args.source)
    generated, _, _ = read_frames(args.generated)
    generated = [remove_letterbox(frame, source_size) for frame in generated]
    start = round(args.start_sec * source_fps)
    endpoint = min(
        len(source) - 2,
        round((args.start_sec + args.duration_sec) * source_fps),
    )
    end = endpoint + 1
    target_count = end - start
    end_seam_index = endpoint + 1
    start_seam_index = start
    tail_values = [int(value) for value in args.tail_frames.split(",")]
    slope_values = [float(value) for value in args.end_slopes.split(",")]

    trials: list[dict] = []
    best: dict | None = None
    best_output: list[np.ndarray] | None = None
    for tail_frames in tail_values:
        for end_slope in slope_values:
            positions = make_positions(
                len(generated), target_count, tail_frames, end_slope
            )
            if positions is None:
                continue
            replacement = [interpolate(generated, value) for value in positions]
            candidate = source[:start] + replacement + source[end:]
            start_metrics = seam_metrics(
                source,
                candidate,
                start_seam_index,
                args.window_frames,
                None,
            )
            end_metrics = seam_metrics(
                source,
                candidate,
                end_seam_index,
                args.window_frames,
                None,
            )
            # Tail optimization must not trade a large start regression for a
            # smaller end score. The small start term only breaks near ties.
            objective = end_metrics["score"] + 0.05 * start_metrics["score"]
            trial = {
                "tail_frames": tail_frames,
                "end_slope": end_slope,
                "start": start_metrics,
                "end": end_metrics,
                "objective": objective,
                "last_positions": [float(value) for value in positions[-8:]],
            }
            trials.append(trial)
            if best is None or objective < best["objective"]:
                best = trial
                best_output = candidate

    if best is None or best_output is None:
        raise RuntimeError("No valid monotonic tail schedule was found")
    write_video(args.output, best_output, source_fps, source_size)
    trials.sort(key=lambda item: item["objective"])
    report = {
        "method": "monotonic cubic-Hermite tail-only velocity retiming",
        "external_video_generator_used": False,
        "generated_frames_reused": True,
        "new_semantic_motion_generated": False,
        "source": str(args.source),
        "generated": str(args.generated),
        "start_sec": args.start_sec,
        "duration_sec": args.duration_sec,
        "source_fps": source_fps,
        "generated_frame_count": len(generated),
        "timeline_replacement_frames": target_count,
        "trial_count": len(trials),
        "best": best,
        "top_trials": trials[:12],
        "output": str(args.output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
