import argparse
import json
from pathlib import Path

import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('--input', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--dilation', type=int, default=31)
p.add_argument('--sigma', type=float, default=7.0)
p.add_argument(
    '--window', type=int, default=-1,
    help='Local temporal radius; negative keeps the legacy all-frame union.',
)
p.add_argument('--report', type=Path)
a = p.parse_args()
cap = cv2.VideoCapture(str(a.input))
fps = float(cap.get(cv2.CAP_PROP_FPS))
frames = []
while True:
    ok, frame = cap.read()
    if not ok:
        break
    frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
cap.release()
if not frames or fps <= 0:
    raise RuntimeError(f'Unreadable mask video: {a.input}')
kernel_size = max(1, a.dilation | 1)
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
if a.window < 0:
    union = np.maximum.reduce(frames)
    envelopes = [union for _ in frames]
    method = 'temporal union of all SAM2 person masks'
else:
    envelopes = []
    for index in range(len(frames)):
        low = max(0, index - a.window)
        high = min(len(frames), index + a.window + 1)
        envelopes.append(np.maximum.reduce(frames[low:high]))
    method = 'local temporal SAM2 person-mask envelope'
processed = []
for envelope in envelopes:
    envelope = cv2.dilate(envelope, kernel)
    envelope = cv2.GaussianBlur(
        envelope, (0, 0), sigmaX=a.sigma, sigmaY=a.sigma
    )
    processed.append(np.clip(envelope, 0, 255).astype(np.uint8))
height, width = processed[0].shape
a.output.parent.mkdir(parents=True, exist_ok=True)
writer = cv2.VideoWriter(str(a.output), cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
if not writer.isOpened():
    raise RuntimeError(f'Cannot create mask video: {a.output}')
for envelope in processed:
    writer.write(cv2.cvtColor(envelope, cv2.COLOR_GRAY2BGR))
writer.release()
report = {
    'method': method + ', dilation, Gaussian feathering',
    'input_frames': len(frames), 'fps': fps, 'size': [width, height],
    'dilation_kernel': kernel_size, 'gaussian_sigma': a.sigma,
    'window_each_side': a.window,
    'coverage_mean': float(np.mean([(frame > 12).mean() for frame in processed])),
    'coverage_max': float(np.max([(frame > 12).mean() for frame in processed])),
    'generated_pixels_reused': False, 'vace_used': False,
}
if a.report:
    a.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
