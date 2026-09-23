"""Read-only source comparison; writes verification report only into the demo."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(sys.argv[1])
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''): h.update(chunk)
    return h.hexdigest()
pairs=[]
for sub in ('external','src','scripts'):
    for p in (ROOT/sub).rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:
            q=SOURCE/p.relative_to(ROOT)
            if q.is_file(): pairs.append((p,q))
for p in (ROOT/'models').rglob('*'):
    if p.is_file(): pairs.append((p,SOURCE.parent/'models'/p.relative_to(ROOT/'models')))
assets={
 'source.mp4':'source_screen_recording.mp4',
 'V58_Balanced.mp4':'outputs/standing_wave_storymem_wan22_a14b_v57_tail_velocity_v58/PLAY_THIS_V58_Balanced.mp4',
 'native_core.mp4':'outputs/standing_wave_storymem_wan22_a14b_native_seed2025_v40/01_01.mp4',
 'source_core.mp4':'outputs/standing_wave_storymem_wan22_a14b_native_seed2025_v40/source_clip.mp4',
 'source_mask.mp4':'outputs/standing_wave_storymem_wan22_a14b_native_seed2025_v40/M/mask_video.mp4',
 'restored_core.mp4':'outputs/standing_wave_storymem_wan22_a14b_v40_flowrestore_seed2025_v57/v57_restored_core.mp4'}
for name,relative in assets.items(): pairs.append((ROOT/'assets'/name,SOURCE/relative))
records=[]
for i,(p,q) in enumerate(pairs):
    a=digest(p); b=digest(q)
    records.append({'path':p.relative_to(ROOT).as_posix(),'source':str(q),'bytes':p.stat().st_size,'sha256':a,'match':a==b})
    if p.stat().st_size>100000000: print(f'{i+1}/{len(pairs)} {p.name}: {a==b}',flush=True)
result={'all_match':all(r['match'] for r in records),'files':len(records),'bytes':sum(r['bytes'] for r in records),'records':records}
(ROOT/'COPY_VERIFICATION.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='records'}),flush=True)
if not result['all_match']: raise SystemExit(1)
