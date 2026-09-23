from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from video_io import fit_with_letterbox, write_video


def _temporal_gaussian_smooth(
    masks: np.ndarray,
    sigma: float,
) -> np.ndarray:
    if sigma <= 0 or len(masks) < 2:
        return masks
    radius = max(1, int(np.ceil(3.0 * sigma)))
    offsets = np.arange(-radius, radius + 1, dtype=np.float32)
    weights = np.exp(-0.5 * (offsets / sigma) ** 2)
    weights /= weights.sum()
    padded = np.pad(
        masks,
        ((radius, radius), (0, 0), (0, 0)),
        mode='edge',
    )
    smoothed = np.empty_like(masks, dtype=np.float32)
    for index in range(len(masks)):
        window = padded[index:index + len(weights)]
        smoothed[index] = np.tensordot(weights, window, axes=(0, 0))
    return smoothed


def _dynamic_dilation_sizes(
    masks: list[np.ndarray],
    base_pixels: int,
    max_pixels: int,
    motion_gain: float,
) -> list[int]:
    sizes: list[int] = []
    previous = None
    for mask in masks:
        motion_ratio = 0.0
        if previous is not None:
            motion_ratio = float(
                np.count_nonzero(mask != previous) / mask.size
            )
        extra = int(round(motion_ratio * motion_gain))
        sizes.append(max(0, min(max_pixels, base_pixels + extra)))
        previous = mask
    return sizes


def make_full_edit_mask(
    frame_count: int,
    width: int,
    height: int,
    fps: int,
    output_dir: Path,
) -> dict:
    mask_dir = output_dir / "M"
    mask_dir.mkdir(parents=True, exist_ok=True)
    white = np.full((height, width, 3), 255, dtype=np.uint8)
    mask_path = mask_dir / "mask_video.mp4"
    write_video(mask_path, [white.copy() for _ in range(frame_count)], fps, width, height)
    return {
        "mask_video": str(mask_path.resolve()),
        "mode": "full_edit_fallback",
        "meaning": "white pixels are editable; black pixels are preserved",
    }


def make_mask_from_png_sequence(
    mask_paths: list[Path],
    width: int,
    height: int,
    fps: int,
    output_dir: Path,
    dilate_pixels: int = 15,
    feather_pixels: int = 9,
    max_dilate_pixels: int | None = None,
    dilation_motion_gain: float = 250.0,
    temporal_sigma_frames: float = 1.25,
) -> dict:
    mask_dir = output_dir / "M"
    mask_dir.mkdir(parents=True, exist_ok=True)
    binary_masks: list[np.ndarray] = []
    for path in mask_paths:
        mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise FileNotFoundError(f"Cannot read mask: {path}")
        _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
        if mask.shape != (height, width):
            mask = fit_with_letterbox(mask, width, height)
            _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
        binary_masks.append(mask)

    maximum = max_dilate_pixels
    if maximum is None:
        maximum = max(dilate_pixels, dilate_pixels * 2)
    dilation_sizes = _dynamic_dilation_sizes(
        binary_masks,
        base_pixels=dilate_pixels,
        max_pixels=maximum,
        motion_gain=dilation_motion_gain,
    )

    processed: list[np.ndarray] = []
    for mask, dilation in zip(binary_masks, dilation_sizes):
        if dilation > 0:
            size = dilation * 2 + 1
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (size, size),
            )
            mask = cv2.dilate(mask, kernel)
        processed.append(mask.astype(np.float32) / 255.0)

    mask_stack = _temporal_gaussian_smooth(
        np.stack(processed, axis=0),
        sigma=temporal_sigma_frames,
    )

    frames: list[np.ndarray] = []
    for mask in mask_stack:
        if feather_pixels > 0:
            blur_size = feather_pixels * 2 + 1
            mask = cv2.GaussianBlur(mask, (blur_size, blur_size), 0)
        mask_u8 = np.clip(mask * 255.0, 0, 255).astype(np.uint8)
        frames.append(cv2.cvtColor(mask_u8, cv2.COLOR_GRAY2BGR))

    mask_path = mask_dir / "mask_video.mp4"
    write_video(mask_path, frames, fps, width, height)
    return {
        "mask_video": str(mask_path.resolve()),
        "mode": "sam2_png_sequence",
        "frame_count": len(frames),
        "dynamic_dilation_pixels": dilation_sizes,
        "dilation_motion_gain": dilation_motion_gain,
        "spatial_feather_pixels": feather_pixels,
        "temporal_gaussian_sigma_frames": temporal_sigma_frames,
        "meaning": "white pixels are editable; black pixels are preserved",
    }
