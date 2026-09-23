from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Evaluate source/generated seam continuity with optical-flow EPE.'
    )
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--start-sec', required=True, type=float)
    parser.add_argument('--end-sec', required=True, type=float)
    parser.add_argument('--window-frames', type=int, default=6)
    parser.add_argument('--threshold', type=float, default=3.0)
    parser.add_argument('--start-threshold', type=float, default=None)
    parser.add_argument('--end-threshold', type=float, default=None)
    parser.add_argument('--mask', type=Path, default=None)
    parser.add_argument('--report', type=Path, default=None)
    parser.add_argument('--rerun-script', type=Path, default=None)
    parser.add_argument('--max-reruns', type=int, default=1)
    return parser.parse_args()


def read_video(path: Path) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f'Cannot open video: {path}')
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames or fps <= 0:
        raise RuntimeError(f'Video has no readable frames: {path}')
    return frames, fps


def optical_flow(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    gray_a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    return cv2.calcOpticalFlowFarneback(
        gray_a,
        gray_b,
        None,
        0.5,
        5,
        21,
        4,
        7,
        1.5,
        0,
    )


def endpoint_error(
    predicted: np.ndarray,
    reference: np.ndarray,
    mask: np.ndarray | None,
) -> float:
    error = np.linalg.norm(predicted - reference, axis=2)
    if mask is not None:
        active = mask > 0.05
        if np.any(active):
            return float(error[active].mean())
    return float(error.mean())


def resize_like(frame: np.ndarray, reference: np.ndarray) -> np.ndarray:
    if frame.shape[:2] == reference.shape[:2]:
        return frame
    return cv2.resize(
        frame,
        (reference.shape[1], reference.shape[0]),
        interpolation=cv2.INTER_LINEAR,
    )


def mask_for_index(
    masks: list[np.ndarray] | None,
    index: int,
    reference: np.ndarray,
) -> np.ndarray | None:
    if not masks:
        return None
    frame = resize_like(masks[min(max(index, 0), len(masks) - 1)], reference)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0


def seam_metrics(
    source: list[np.ndarray],
    candidate: list[np.ndarray],
    seam_index: int,
    window: int,
    masks: list[np.ndarray] | None,
) -> dict[str, float]:
    if seam_index < 1 or seam_index >= min(len(source), len(candidate)):
        raise ValueError(f'Seam frame is out of range: {seam_index}')
    source_before = source[seam_index - 1]
    source_after = source[seam_index]
    candidate_before = resize_like(candidate[seam_index - 1], source_before)
    candidate_after = resize_like(candidate[seam_index], source_after)
    reference_flow = optical_flow(source_before, source_after)
    candidate_flow = optical_flow(candidate_before, candidate_after)
    active_mask = mask_for_index(masks, seam_index, source_after)
    reference_epe = endpoint_error(candidate_flow, reference_flow, active_mask)

    first_pair = max(0, seam_index - window)
    last_pair = min(len(candidate) - 2, seam_index + window - 1)
    flows: list[np.ndarray] = []
    for index in range(first_pair, last_pair + 1):
        first = resize_like(candidate[index], source_after)
        second = resize_like(candidate[index + 1], source_after)
        flows.append(optical_flow(first, second))
    continuity_values: list[float] = []
    for offset in range(len(flows) - 1):
        index = first_pair + offset + 1
        active = mask_for_index(masks, index, source_after)
        continuity_values.append(
            endpoint_error(flows[offset + 1], flows[offset], active)
        )
    continuity_epe = float(np.mean(continuity_values)) if continuity_values else 0.0
    return {
        'reference_epe': reference_epe,
        'continuity_epe': continuity_epe,
        'score': max(reference_epe, continuity_epe),
    }


def maybe_rerun(args: argparse.Namespace, state_path: Path) -> dict:
    result = {'requested': False, 'attempt': 0}
    if args.rerun_script is None:
        return result
    attempt = 0
    if state_path.is_file():
        attempt = int(json.loads(state_path.read_text(encoding='utf-8')).get('attempt', 0))
    if attempt >= args.max_reruns:
        result['reason'] = 'maximum reruns reached'
        result['attempt'] = attempt
        return result
    attempt += 1
    state_path.write_text(json.dumps({'attempt': attempt}, indent=2), encoding='utf-8')
    if args.rerun_script.suffix.lower() == '.ps1':
        command = [
            'powershell',
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            str(args.rerun_script),
        ]
    else:
        command = [str(args.rerun_script)]
    completed = subprocess.run(command, check=False)
    result.update({
        'requested': True,
        'attempt': attempt,
        'exit_code': completed.returncode,
    })
    return result


def main() -> int:
    args = parse_args()
    source, source_fps = read_video(args.source)
    candidate, candidate_fps = read_video(args.candidate)
    if abs(source_fps - candidate_fps) > 0.01:
        raise ValueError(f'FPS mismatch: {source_fps} vs {candidate_fps}')
    masks = read_video(args.mask)[0] if args.mask else None
    start_index = round(args.start_sec * source_fps)
    # The generated interval includes its exact source endpoint.  Its outside
    # seam is therefore the following frame.
    end_index = round(args.end_sec * source_fps) + 1
    metrics = {
        'start': seam_metrics(
            source, candidate, start_index, args.window_frames, masks
        ),
        'end': seam_metrics(
            source, candidate, end_index, args.window_frames, masks
        ),
    }
    start_threshold = args.start_threshold or args.threshold
    end_threshold = args.end_threshold or args.threshold
    score = max(metrics['start']['score'], metrics['end']['score'])
    passed = (
        metrics['start']['score'] <= start_threshold
        and metrics['end']['score'] <= end_threshold
    )
    report_path = args.report or args.candidate.with_suffix(
        '.epe_passed.json' if passed else '.epe_rejected.json'
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        'source': str(args.source.resolve()),
        'candidate': str(args.candidate.resolve()),
        'fps': source_fps,
        'window_frames': args.window_frames,
        'threshold': args.threshold,
        'start_threshold': start_threshold,
        'end_threshold': end_threshold,
        'metrics': metrics,
        'score': score,
        'passed': passed,
    }
    if not passed:
        state_path = report_path.with_suffix('.rerun_state.json')
        report['rerun'] = maybe_rerun(args, state_path)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    marker_path = report_path.with_suffix('.passed' if passed else '.rejected')
    marker_path.write_text(
        f'score={score:.6f}\n'
        f'start={metrics["start"]["score"]:.6f}\n'
        f'end={metrics["end"]["score"]:.6f}\n',
        encoding='utf-8',
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == '__main__':
    sys.exit(main())
