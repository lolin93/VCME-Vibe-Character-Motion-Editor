from __future__ import annotations

from pathlib import Path

import numpy as np

from video_io import fit_with_letterbox, write_image


def export_frame_controls(
    frames: list[np.ndarray],
    output_dir: Path,
    width: int,
    height: int,
    memory_count: int,
) -> dict:
    if len(frames) < 2:
        raise ValueError("At least two frames are required for frame controls.")

    frame_dir = output_dir / "F"
    memory_dir = frame_dir / "memory_keyframes"
    memory_dir.mkdir(parents=True, exist_ok=True)

    fitted = [fit_with_letterbox(frame, width, height) for frame in frames]
    first_path = frame_dir / "first_frame.png"
    last_path = frame_dir / "last_frame.png"
    write_image(first_path, fitted[0])
    write_image(last_path, fitted[-1])

    memory_paths: list[str] = []
    if memory_count > 0:
        if memory_count == 1:
            indices = [0]
        else:
            indices = [
                round(i * (len(fitted) - 1) / (memory_count - 1))
                for i in range(memory_count)
            ]
        for order, index in enumerate(indices):
            path = memory_dir / f"memory_{order:02d}_frame_{index:04d}.png"
            write_image(path, fitted[index])
            memory_paths.append(str(path.resolve()))

    return {
        "first_frame": str(first_path.resolve()),
        "last_frame": str(last_path.resolve()),
        "memory_keyframes": memory_paths,
    }

