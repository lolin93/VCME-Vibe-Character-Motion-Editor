from __future__ import annotations

import subprocess
from pathlib import Path


def run_existing_sam2_tracker(
    sam2_project: Path,
    python_exe: Path,
    video_path: Path,
    output_dir: Path,
    click_x: int | None = None,
    click_y: int | None = None,
    max_frames: int | None = None,
    checkpoint: Path | None = None,
    model_config: str | None = None,
    box: tuple[int, int, int, int] | None = None,
) -> list[Path]:
    """Call an existing SAM2 run_tracking.py and return generated mask PNGs."""
    sam2_project = sam2_project.resolve()
    python_exe = python_exe.resolve() if python_exe.is_absolute() else python_exe
    video_path = video_path.resolve()
    output_dir = output_dir.resolve()
    if checkpoint is not None:
        checkpoint = checkpoint.resolve()
    script = sam2_project / "run_tracking.py"
    if not script.is_file():
        raise FileNotFoundError(f"SAM2 tracker not found: {script}")

    command = [
        str(python_exe),
        str(script),
        str(video_path),
        "--output-dir",
        str(output_dir),
    ]
    if click_x is not None:
        command.extend(["--click-x", str(click_x)])
    if click_y is not None:
        command.extend(["--click-y", str(click_y)])
    if max_frames is not None:
        command.extend(["--max-frames", str(max_frames)])
    if checkpoint is not None:
        command.extend(["--checkpoint", str(checkpoint)])
    if model_config:
        command.extend(["--model-config", model_config])
    if box is not None:
        command.extend(["--box", *(str(value) for value in box)])

    subprocess.run(command, cwd=str(sam2_project), check=True)
    masks = sorted(output_dir.glob("mask_*.png"))
    if not masks:
        raise RuntimeError(f"SAM2 did not produce masks in: {output_dir}")
    return masks
