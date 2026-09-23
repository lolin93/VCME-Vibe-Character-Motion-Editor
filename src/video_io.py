from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    fps: float
    frame_count: int
    width: int
    height: int
    duration_sec: float


def get_video_info(video_path: Path) -> VideoInfo:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if fps <= 0 or frame_count <= 0:
        raise RuntimeError(f"Invalid video metadata: {video_path}")
    return VideoInfo(
        path=video_path,
        fps=fps,
        frame_count=frame_count,
        width=width,
        height=height,
        duration_sec=frame_count / fps,
    )


def fit_with_letterbox(frame: np.ndarray, width: int, height: int, value=(0, 0, 0)) -> np.ndarray:
    source_h, source_w = frame.shape[:2]
    scale = min(width / source_w, height / source_h)
    resized_w = max(1, round(source_w * scale))
    resized_h = max(1, round(source_h * scale))
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
    top = (height - resized_h) // 2
    bottom = height - resized_h - top
    left = (width - resized_w) // 2
    right = width - resized_w - left
    return cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=value
    )


def sample_clip_frames(
    video_path: Path,
    start_sec: float,
    duration_sec: float,
    model_fps: int,
    frame_count: int,
) -> list[np.ndarray]:
    info = get_video_info(video_path)
    if start_sec < 0:
        raise ValueError("--start-sec must be >= 0")
    if start_sec + duration_sec > info.duration_sec + 0.001:
        raise ValueError(
            f"Requested clip ends at {start_sec + duration_sec:.2f}s, "
            f"but video duration is {info.duration_sec:.2f}s."
        )

    capture = cv2.VideoCapture(str(video_path))
    frames: list[np.ndarray] = []
    # Always include both requested endpoints. The previous fixed-FPS loop
    # silently missed the final frame whenever max_frames capped the clip.
    sample_times = np.linspace(start_sec, start_sec + duration_sec, frame_count)
    for t in sample_times:
        source_index = min(info.frame_count - 1, round(t * info.fps))
        capture.set(cv2.CAP_PROP_POS_FRAMES, source_index)
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames:
        raise RuntimeError("No frames sampled from source video.")
    if len(frames) != frame_count:
        raise RuntimeError(
            f"Sampled {len(frames)} frames, expected {frame_count}; "
            "refusing to build misaligned endpoint controls."
        )
    return frames


def write_image(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"Cannot write image: {path}")


def write_video(path: Path, frames: list[np.ndarray], fps: int, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError(f"Cannot create video: {path}")
    for frame in frames:
        if frame.shape[1] != width or frame.shape[0] != height:
            frame = fit_with_letterbox(frame, width, height)
        writer.write(frame)
    writer.release()
