from __future__ import annotations

import argparse
import math
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replace a source range using overlapping generated clips."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--generated", required=True, type=Path, nargs="+")
    parser.add_argument("--start-sec", required=True, type=float)
    parser.add_argument("--duration-sec", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--exact-source-endpoints",
        action="store_true",
        help="Replace the generated first/last frames with exact source frames.",
    )
    parser.add_argument(
        "--legacy-v24-timeline",
        action="store_true",
        help="Use the original v24/v26 rounded-frame stretch and canvas resize for A/B comparison.",
    )
    parser.add_argument(
        "--resample-mode",
        choices=("linear", "flow"),
        default="linear",
        help="Temporal conversion method; linear preserves legacy reproducibility.",
    )
    parser.add_argument(
        "--match-endpoint-color",
        action="store_true",
        help="Apply one smooth whole-segment color transform fitted to source endpoints.",
    )
    return parser.parse_args()


def read_frames(path: Path) -> tuple[list, float, tuple[int, int]]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    size = (
        int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames or fps <= 0:
        raise RuntimeError(f"Video has no readable frames: {path}")
    return frames, fps, size


def remove_letterbox(frame: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    target_w, target_h = target_size
    source_h, source_w = frame.shape[:2]
    target_aspect = target_w / target_h
    source_aspect = source_w / source_h
    if abs(target_aspect - source_aspect) < 1e-4:
        crop = frame
    elif source_aspect < target_aspect:
        content_h = max(1, round(source_w / target_aspect))
        top = max(0, (source_h - content_h) // 2)
        crop = frame[top:top + content_h]
    else:
        content_w = max(1, round(source_h * target_aspect))
        left = max(0, (source_w - content_w) // 2)
        crop = frame[:, left:left + content_w]
    return cv2.resize(crop, target_size, interpolation=cv2.INTER_LANCZOS4)


def _warp_with_flow(frame: np.ndarray, flow: np.ndarray, amount: float) -> np.ndarray:
    height, width = frame.shape[:2]
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )
    map_x = grid_x - np.float32(amount) * flow[..., 0]
    map_y = grid_y - np.float32(amount) * flow[..., 1]
    return cv2.remap(
        frame,
        map_x,
        map_y,
        cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REFLECT101,
    )


def resample_frames_linear(
    frames: list[np.ndarray], target_count: int
) -> list[np.ndarray]:
    if target_count < 2 or len(frames) < 2:
        raise ValueError('Temporal resampling requires at least two frames')
    output: list[np.ndarray] = []
    for index in range(target_count):
        position = index * (len(frames) - 1) / (target_count - 1)
        lower = int(math.floor(position))
        upper = min(len(frames) - 1, lower + 1)
        alpha = position - lower
        if upper == lower or alpha <= 1e-8:
            output.append(frames[lower].copy())
        else:
            output.append(cv2.addWeighted(
                frames[lower], 1.0 - alpha, frames[upper], alpha, 0.0
            ))
    return output


def resample_frames_flow(frames: list[np.ndarray], target_count: int) -> list[np.ndarray]:
    if target_count < 2 or len(frames) < 2:
        raise ValueError('Temporal resampling requires at least two frames')
    output: list[np.ndarray] = []
    flow_cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
    for index in range(target_count):
        position = index * (len(frames) - 1) / (target_count - 1)
        lower = int(math.floor(position))
        upper = min(len(frames) - 1, lower + 1)
        alpha = position - lower
        if upper == lower or alpha <= 1e-8:
            output.append(frames[lower].copy())
        else:
            # A raw dissolve between moving frames creates a visible double
            # person. Align both frames toward the requested instant first,
            # then blend only the aligned residuals.
            key = (lower, upper)
            if key not in flow_cache:
                gray_a = cv2.cvtColor(frames[lower], cv2.COLOR_BGR2GRAY)
                gray_b = cv2.cvtColor(frames[upper], cv2.COLOR_BGR2GRAY)
                flow_ab = cv2.calcOpticalFlowFarneback(
                    gray_a, gray_b, None, 0.5, 5, 21, 5, 7, 1.5, 0
                )
                flow_ba = cv2.calcOpticalFlowFarneback(
                    gray_b, gray_a, None, 0.5, 5, 21, 5, 7, 1.5, 0
                )
                flow_cache[key] = (flow_ab, flow_ba)
            flow_ab, flow_ba = flow_cache[key]
            from_lower = _warp_with_flow(frames[lower], flow_ab, alpha)
            from_upper = _warp_with_flow(frames[upper], flow_ba, 1.0 - alpha)
            output.append(cv2.addWeighted(
                from_lower, 1.0 - alpha, from_upper, alpha, 0.0
            ))
    return output


def match_endpoint_color(
    frames: list[np.ndarray], first_target: np.ndarray, last_target: np.ndarray
) -> list[np.ndarray]:
    """Match exposure/color continuously without compositing source pixels."""
    params = []
    for generated, target in ((frames[0], first_target), (frames[-1], last_target)):
        generated_f = generated.astype(np.float32)
        target_f = target.astype(np.float32)
        generated_mean = generated_f.mean(axis=(0, 1))
        target_mean = target_f.mean(axis=(0, 1))
        generated_std = generated_f.std(axis=(0, 1)).clip(min=1.0)
        target_std = target_f.std(axis=(0, 1))
        gain = np.clip(target_std / generated_std, 0.90, 1.10)
        offset = np.clip(target_mean - generated_mean * gain, -12.0, 12.0)
        params.append((gain, offset))
    corrected = []
    for index, frame in enumerate(frames):
        alpha = index / max(1, len(frames) - 1)
        gain = params[0][0] * (1.0 - alpha) + params[1][0] * alpha
        offset = params[0][1] * (1.0 - alpha) + params[1][1] * alpha
        value = frame.astype(np.float32) * gain.reshape(1, 1, 3)
        value += offset.reshape(1, 1, 3)
        corrected.append(np.clip(value, 0, 255).astype(np.uint8))
    return corrected


def main() -> None:
    args = parse_args()
    source, source_fps, source_size = read_frames(args.source)

    generated = []
    for index, path in enumerate(args.generated):
        frames, _, _ = read_frames(path)
        if args.legacy_v24_timeline:
            restored = [
                cv2.resize(frame, source_size, interpolation=cv2.INTER_LANCZOS4)
                for frame in frames
            ]
        else:
            restored = [remove_letterbox(frame, source_size) for frame in frames]
        generated.extend(restored if index == 0 else restored[1:])

    start = round(args.start_sec * source_fps)
    if args.legacy_v24_timeline:
        end = min(len(source), start + round(args.duration_sec * source_fps))
        endpoint = end - 1
    else:
        endpoint = round((args.start_sec + args.duration_sec) * source_fps)
        endpoint = min(len(source) - 2, endpoint)
        end = endpoint + 1
    if start >= len(source):
        raise ValueError("Replacement starts after the source video ends")

    target_count = end - start
    if args.match_endpoint_color:
        generated = match_endpoint_color(
            generated, source[start], source[endpoint]
        )
    if args.legacy_v24_timeline:
        replacement = [
            generated[round(index * (len(generated) - 1) / max(1, target_count - 1))]
            for index in range(target_count)
        ]
    else:
        if args.resample_mode == "flow":
            replacement = resample_frames_flow(generated, target_count)
        else:
            replacement = resample_frames_linear(generated, target_count)
    if args.exact_source_endpoints:
        replacement[0] = source[start].copy()
        replacement[-1] = source[endpoint].copy()

    output = source[:start] + replacement + source[end:]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(args.output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        source_fps,
        source_size,
    )
    if not writer.isOpened():
        raise RuntimeError(f"Cannot create output video: {args.output}")
    for frame in output:
        writer.write(frame)
    writer.release()
    print(f"Wrote {args.output} with {len(output)} frames")


if __name__ == "__main__":
    main()
