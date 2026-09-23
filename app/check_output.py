"""Read-only video comparison with a diagnostic contact sheet."""
import argparse,json
from pathlib import Path
import cv2
import numpy as np

def sample(path,indices):
    cap=cv2.VideoCapture(str(path))
    meta={'frames':int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),'fps':cap.get(cv2.CAP_PROP_FPS),'width':int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),'height':int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
    images=[]
    for i in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES,i)
        ok,im=cap.read()
        if not ok: raise RuntimeError(f'Cannot decode frame {i} of {path}')
        images.append(im)
    cap.release()
    return meta,images

def main():
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);args=p.parse_args()
    req=json.loads((args.job/'request.json').read_text())
    source=Path(req['source']);start=req['start'];end=start+req['duration']
    meta,_=sample(source,[])
    times=[max(0,start-.2),start+.1,start+req['duration']*.33,start+req['duration']*.66,end-.1,min(meta['frames']/meta['fps']-.1,end+.2)]
    indices=[round(t*meta['fps']) for t in times]
    meta,src=sample(source,indices)
    out_meta,out=sample(args.job/'result.mp4',indices)
    assert meta==out_meta,(meta,out_meta)
    report={'source':str(source),'output':str(args.job/'result.mp4'),'metadata':meta,
            'same_timeline_and_dimensions':True,'sample_times':times,
            'sample_source_mae':[float(np.abs(a.astype(float)-b.astype(float)).mean()) for a,b in zip(src,out)],
            'note':'Outside-interval differences include video re-encoding. These diagnostics do not prove natural motion or seamless joins.'}
    rows=[]
    for label,frames in [('Source',src),('Generated result',out)]:
        tiles=[]
        for t,im in zip(times,frames):
            tile=cv2.resize(im,(160,220))
            cv2.rectangle(tile,(0,0),(160,24),(15,20,25),-1)
            cv2.putText(tile,f'{label} {t:.2f}s',(3,16),cv2.FONT_HERSHEY_SIMPLEX,.35,(255,255,255),1,cv2.LINE_AA)
            tiles.append(tile)
        rows.append(np.concatenate(tiles,axis=1))
    cv2.imwrite(str(args.job/'comparison.jpg'),np.concatenate(rows,axis=0))
    (args.job/'output_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()

