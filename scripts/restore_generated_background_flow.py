from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def read_video(path: Path, grayscale: bool = False) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frames.append(frame)
    capture.release()
    if not frames or fps <= 0:
        raise RuntimeError(f"No readable frames: {path}")
    return frames, fps


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def farneback(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    first_gray = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
    second_gray = cv2.cvtColor(second, cv2.COLOR_BGR2GRAY)
    return cv2.calcOpticalFlowFarneback(
        first_gray,
        second_gray,
        None,
        0.5,
        5,
        21,
        4,
        7,
        1.5,
        0,
    )


def flow_confidence(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Forward/backward confidence in first-frame coordinates."""
    forward = farneback(first, second)
    backward = farneback(second, first)
    height, width = first.shape[:2]
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )
    map_x = grid_x + forward[..., 0]
    map_y = grid_y + forward[..., 1]
    backward_at_destination = cv2.remap(
        backward,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=1000,
    )
    fb_error = np.linalg.norm(forward + backward_at_destination, axis=2)
    second_at_destination = cv2.remap(
        second,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    photo_error = np.mean(
        np.abs(first.astype(np.float32) - second_at_destination.astype(np.float32)),
        axis=2,
    )
    confidence = np.exp(-np.square(fb_error / 1.5))
    confidence *= np.exp(-np.square(photo_error / 22.0))
    confidence = cv2.GaussianBlur(confidence, (0, 0), 5.0)
    return np.clip(confidence, 0.0, 1.0)


def temporal_union(masks: list[np.ndarray], window: int) -> list[np.ndarray]:
    result: list[np.ndarray] = []
    for index in range(len(masks)):
        low = max(0, index - window)
        high = min(len(masks), index + window + 1)
        result.append(np.logical_or.reduce(masks[low:high]))
    return result


def smoothstep(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def protection_alpha(
    person: np.ndarray,
    guard_pixels: int,
    feather_pixels: int,
) -> np.ndarray:
    binary = person.astype(np.uint8)
    if guard_pixels > 0:
        size = guard_pixels * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        binary = cv2.dilate(binary, kernel)
    if feather_pixels <= 0:
        return binary.astype(np.float32)
    distance = cv2.distanceTransform(1 - binary, cv2.DIST_L2, 5)
    outside = smoothstep(distance / float(feather_pixels))
    alpha = 1.0 - outside
    alpha[binary > 0] = 1.0
    return alpha.astype(np.float32)


def background_metrics(
    source: list[np.ndarray],
    candidate: list[np.ndarray],
    person_masks: list[np.ndarray],
) -> tuple[float, float]:
    source_errors: list[float] = []
    temporal_errors: list[float] = []
    for index, (src, cur, person) in enumerate(
        zip(source, candidate, person_masks)
    ):
        background = (~person).astype(np.float32)
        denominator = max(float(background.sum()) * 3.0, 1.0)
        source_errors.append(float(
            (np.abs(cur.astype(np.float32) - src.astype(np.float32))
             * background[..., None]).sum() / denominator / 127.5
        ))
        if index:
            src_delta = src.astype(np.float32) - source[index - 1].astype(np.float32)
            cur_delta = cur.astype(np.float32) - candidate[index - 1].astype(np.float32)
            temporal_errors.append(float(
                (np.abs(cur_delta - src_delta) * background[..., None]).sum()
                / denominator / 127.5
            ))
    return float(np.mean(source_errors)), float(np.mean(temporal_errors))


def write_video(path: Path, frames: list[np.ndarray], fps: float) -> None:
    height, width = frames[0].shape[:2]
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError(f"Cannot create video: {path}")
    for frame in frames:
        writer.write(frame)
    writer.release()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Restore only reliable background pixels from a time-aligned source "
            "while preserving the generated person and a feathered guard band."
        )
    )
    parser.add_argument("--generated", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--source-mask", required=True, type=Path)
    parser.add_argument("--generated-mask", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--alpha-video", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--local-window", type=int, default=1)
    parser.add_argument("--guard-pixels", type=int, default=18)
    parser.add_argument("--feather-pixels", type=int, default=24)
    parser.add_argument("--minimum-flow-confidence", type=float, default=0.72)
    args = parser.parse_args()

    generated, generated_fps = read_video(args.generated)
    source, source_fps = read_video(args.source)
    source_masks, _ = read_video(args.source_mask, grayscale=True)
    generated_masks, _ = read_video(args.generated_mask, grayscale=True)
    counts = {len(generated), len(source), len(source_masks), len(generated_masks)}
    if len(counts) != 1:
        raise ValueError(
            "Generated, source and mask frame counts must match: "
            f"{len(generated)}, {len(source)}, {len(source_masks)}, "
            f"{len(generated_masks)}"
        )
    if abs(generated_fps - source_fps) > 0.01:
        raise ValueError(f"FPS mismatch: {generated_fps} vs {source_fps}")
    height, width = generated[0].shape[:2]
    if any(frame.shape[:2] != (height, width) for frame in source):
        source = [cv2.resize(frame, (width, height)) for frame in source]
    source_masks = [cv2.resize(mask, (width, height)) for mask in source_masks]
    generated_masks = [cv2.resize(mask, (width, height)) for mask in generated_masks]

    combined = [
        np.logical_or(source_mask > 24, generated_mask > 127)
        for source_mask, generated_mask in zip(source_masks, generated_masks)
    ]
    combined = temporal_union(combined, max(0, args.local_window))
    protection = [
        protection_alpha(mask, args.guard_pixels, args.feather_pixels)
        for mask in combined
    ]

    pair_confidence = [
        flow_confidence(source[index], source[index + 1])
        for index in range(len(source) - 1)
    ]
    confidence: list[np.ndarray] = []
    for index in range(len(source)):
        adjacent: list[np.ndarray] = []
        if index:
            adjacent.append(pair_confidence[index - 1])
        if index < len(pair_confidence):
            adjacent.append(pair_confidence[index])
        value = np.mean(adjacent, axis=0)
        value = np.maximum(value, args.minimum_flow_confidence)
        confidence.append(np.clip(value, 0.0, 1.0).astype(np.float32))

    output_frames: list[np.ndarray] = []
    alpha_frames: list[np.ndarray] = []
    person_core_differences: list[float] = []
    restore_coverages: list[float] = []
    confidence_means: list[float] = []
    for src, gen, person, protect, reliable in zip(
        source, generated, combined, protection, confidence
    ):
        restore = (1.0 - protect) * reliable
        # Keep the generated frame exactly in the person/guard core before
        # encoding. Only verified background pixels may move toward source.
        composed = (
            gen.astype(np.float32) * (1.0 - restore[..., None])
            + src.astype(np.float32) * restore[..., None]
        )
        composed = np.clip(np.rint(composed), 0, 255).astype(np.uint8)
        output_frames.append(composed)
        alpha_frames.append(cv2.cvtColor(
            np.clip(restore * 255.0, 0, 255).astype(np.uint8),
            cv2.COLOR_GRAY2BGR,
        ))
        if np.any(person):
            person_core_differences.append(float(
                np.abs(composed.astype(np.int16) - gen.astype(np.int16))[person].max()
            ))
        restore_coverages.append(float((restore > 0.05).mean()))
        confidence_means.append(float(reliable[~person].mean()))

    before_source, before_temporal = background_metrics(source, generated, combined)
    after_source, after_temporal = background_metrics(source, output_frames, combined)
    write_video(args.output, output_frames, generated_fps)
    write_video(args.alpha_video, alpha_frames, generated_fps)

    report = {
        "method": "background-only source restoration gated by bidirectional flow confidence",
        "generator_unchanged": True,
        "external_video_generator_used": False,
        "generated_person_reused_from": str(args.generated),
        "frame_count": len(output_frames),
        "fps": generated_fps,
        "size": [width, height],
        "settings": {
            "local_window": args.local_window,
            "guard_pixels": args.guard_pixels,
            "feather_pixels": args.feather_pixels,
            "minimum_flow_confidence": args.minimum_flow_confidence,
        },
        "restore_coverage_mean": float(np.mean(restore_coverages)),
        "background_flow_confidence_mean": float(np.mean(confidence_means)),
        "person_core_max_difference_before_encoding": float(
            max(person_core_differences, default=0.0)
        ),
        "metrics_before": {
            "background_source_mae": before_source,
            "background_temporal_delta_error": before_temporal,
        },
        "metrics_after_before_encoding": {
            "background_source_mae": after_source,
            "background_temporal_delta_error": after_temporal,
        },
        "inputs": {
            "generated": {"path": str(args.generated), "sha256": sha256(args.generated)},
            "source": {"path": str(args.source), "sha256": sha256(args.source)},
            "source_mask": {"path": str(args.source_mask), "sha256": sha256(args.source_mask)},
            "generated_mask": {
                "path": str(args.generated_mask),
                "sha256": sha256(args.generated_mask),
            },
        },
        "outputs": {
            "restored_core": str(args.output),
            "restore_alpha_video": str(args.alpha_video),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
