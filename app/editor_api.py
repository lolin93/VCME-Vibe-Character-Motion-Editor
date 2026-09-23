"""Local upload catalog and validated editor requests. No external generation service."""
import json
import math
from pathlib import Path
import subprocess
import uuid
import time
from urllib.parse import parse_qs, urlparse
from selection import frame_count

ROOT=Path(__file__).resolve().parents[1]
LIMIT_MB=100
MAX_SOURCE_SECONDS=60
MAX_EDIT_SECONDS=10

def valid_id(value):
    if not isinstance(value,str) or len(value)!=32 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid identifier')
    return value

def probe(path):
    p=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
       'stream=width,height,avg_frame_rate,nb_frames,duration:format=duration','-of','json',str(path)],
       capture_output=True,text=True,check=True,timeout=30)
    data=json.loads(p.stdout)
    if not data.get('streams'): raise ValueError('找不到影片影像軌')
    v=data['streams'][0]
    a,b=v.get('avg_frame_rate','0/1').split('/')
    fps=float(a)/float(b) if float(b) else 0
    duration=float(v.get('duration') or data['format']['duration'])
    if not math.isfinite(duration) or not math.isfinite(fps) or fps<=0 or duration<=0:
        raise ValueError('無效影片時間資訊')
    return {'duration':duration,'fps':fps,'width':int(v['width']),'height':int(v['height'])}

def media(value, include_removed=False):
    if value=='sample':
        return {'id':'sample','name':'範例原片（非上傳影片）',**probe(ROOT/'assets/source.mp4'),
                'url':'/assets/source.mp4','source':'/workspace/assets/source.mp4'}
    ident=valid_id(value)
    item=json.loads((ROOT/'media'/ident/'metadata.json').read_text(encoding='utf-8'))
    if item.get('removed_at') and not include_removed:
        raise ValueError('此素材已移除，請先復原或重新上傳')
    return item

def set_removed(ident, removed):
    valid_id(ident)
    item=media(ident,include_removed=True)
    if removed: item['removed_at']=time.time()
    else: item.pop('removed_at',None)
    path=ROOT/'media'/ident/'metadata.json'
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)
    return item

def catalog():
    items=[]
    for p in sorted((ROOT/'media').glob('*/metadata.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        item=json.loads(p.read_text(encoding='utf-8'))
        if not item.get('removed_at'): items.append(item)
    return items

def upload(handler):
    size=int(handler.headers.get('Content-Length','0'))
    if not 0<size<=LIMIT_MB*1024*1024:
        raise ValueError(f'上傳上限 {LIMIT_MB} MB')
    label=parse_qs(urlparse(handler.path).query).get('name',['uploaded-video'])[0][:160]
    ident=uuid.uuid4().hex
    folder=ROOT/'media'/ident
    folder.mkdir(parents=True)
    with (folder/'original.upload').open('wb') as f:
        remaining=size
        while remaining:
            chunk=handler.rfile.read(min(1024*1024,remaining))
            if not chunk: raise ValueError('上傳未完成，請重試')
            f.write(chunk)
            remaining-=len(chunk)
    original=probe(folder/'original.upload')
    if not 2<=original['duration']<=MAX_SOURCE_SECONDS:
        raise ValueError(f'展示版目前接受 2–{MAX_SOURCE_SECONDS} 秒影片')
    # Keep original; normalize a separate working copy for browser and bounded RAM.
    p=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',
        '-i',str(folder/'original.upload'),'-map','0:v:0','-map','0:a:0?',
        '-vf',"scale=854:854:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
        '-r','30','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',
        '-c:a','aac','-movflags','+faststart',str(folder/'source.mp4')],
        capture_output=True,text=True,timeout=180)
    if p.returncode: raise ValueError('影片轉換失敗：'+p.stderr[-600:])
    info=probe(folder/'source.mp4')
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',
        '-i',str(folder/'source.mp4'),'-frames:v','1','-vf','scale=240:-2',str(folder/'thumbnail.jpg')],
        capture_output=True,check=True,timeout=30)
    info.update(id=ident,name=label,url=f'/media/{ident}/source.mp4',
                thumbnail=f'/media/{ident}/thumbnail.jpg',source=f'/workspace/media/{ident}/source.mp4',
                original=original,normalization='Working copy: H.264, 30 fps, longest edge <=854; original preserved.')
    (folder/'metadata.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    return info

def validate(data):
    mode=data.get('mode')
    if mode not in ('select','generate'): raise ValueError('此介面只接受人物選取或重新生成')
    m=media(data.get('media_id'))
    start=float(data['start']); end=float(data['end'])
    x=float(data.get('x',.5)); y=float(data.get('y',.42))
    click=float(data.get('click_time',start))
    if not all(math.isfinite(v) for v in (start,end,x,y,click)):
        raise ValueError('時間或座標不是有效數字')
    # Endpoint diagnostics and V58 retiming require real source on both sides.
    margin=2/m['fps']
    if start<margin or end>m['duration']-margin or not 1<=end-start<=MAX_EDIT_SECONDS:
        raise ValueError(f'修改區間需 1–{MAX_EDIT_SECONDS} 秒，首尾各留至少 2 幀原片')
    if not 0<=x<=1 or not 0<=y<=1 or not start<=click<=end:
        raise ValueError('請在修改區間內點選人物')
    seed=int(data.get('seed',2025)); motion=str(data.get('motion','')).strip()
    if not 0<=seed<2**63: raise ValueError('Seed 超出範圍')
    request={'mode':mode,'source':m['source'],'media_id':m['id'],'media_name':m['name'],
       'start':start,'duration':end-start,'end':end,'click_time':click,'x':x,'y':y,
       'seed':seed,'motion':motion,'preserve':data.get('preserve',True) is True,
       'frame_count':frame_count(end-start),
       'recipe':'Native StoryMem/Wan2.2 + V57 background restoration + V58 tail retiming; user-upload adaptation'}
    if mode=='generate':
        if not motion or len(motion)>8000: raise ValueError('請填寫動作描述（最多 8000 字）')
        ident=valid_id(data.get('selection_id'))
        selection=json.loads((ROOT/'jobs'/ident/'selection.json').read_text(encoding='utf-8'))
        state=json.loads((ROOT/'jobs'/ident/'status.json').read_text(encoding='utf-8'))
        if state.get('state')!='done': raise ValueError('人物追蹤尚未成功完成')
        for k in ('source','media_id','start','duration'):
            if selection[k]!=request[k]: raise ValueError('影片或區間已更改，請重新點選人物')
        request.update(selection_id=ident,first_x=selection['first_x'],first_y=selection['first_y'])
    return request
