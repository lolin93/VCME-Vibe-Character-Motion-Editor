"""Actual point-prompt SAM2 selection, shared by preview and generation."""
import json
import math
from pathlib import Path

MODEL_W, MODEL_H, MODEL_FPS = 480, 832, 16

def frame_count(duration):
    return 4 * max(4, math.floor(float(duration) * MODEL_FPS / 4 + 0.5)) + 1

def select(source, job, request, track):
    import cv2
    import numpy as np
    from video_io import get_video_info, sample_clip_frames, write_video
    info = get_video_info(source)
    duration = request['duration']
    n = frame_count(duration)
    frames = sample_clip_frames(source, request['start'], duration, MODEL_FPS, n)
    write_video(job/'source_clip.mp4', frames, MODEL_FPS, MODEL_W, MODEL_H)
    scale = min(MODEL_W/info.width, MODEL_H/info.height)
    w, h = round(info.width*scale), round(info.height*scale)
    left, top = (MODEL_W-w)//2, (MODEL_H-h)//2
    x = (left + request['x']*(w-1))/MODEL_W
    y = (top + request['y']*(h-1))/MODEL_H
    index = min(n-1,max(0,round((request['click_time']-request['start'])/duration*(n-1))))
    track(job/'source_clip.mp4',job/'source_masks',x,y,n,index)
    masks = sorted((job/'source_masks').glob('mask_*.png'))
    previews = job/'overlays'
    previews.mkdir(exist_ok=True)
    counts=[]
    for i, p in enumerate(masks):
        mask=cv2.imread(str(p),cv2.IMREAD_GRAYSCALE)
        cropped=mask[top:top+h,left:left+w]
        counts.append(int(np.count_nonzero(cropped)))
        overlay=np.zeros((h,w,4),np.uint8)
        overlay[:,:,:3]=(180,225,75)
        overlay[:,:,3]=np.where(cropped>0,110,0).astype(np.uint8)
        cv2.imwrite(str(previews/f'{i:06d}.png'),overlay)
    if len(masks)!=n or counts[index]<20:
        raise RuntimeError('SAM2 did not find a usable object at this point. Click inside the person again.')
    first=cv2.imread(str(masks[0]),cv2.IMREAD_GRAYSCALE)
    distance=cv2.distanceTransform(first,cv2.DIST_L2,5)
    _,peak,_,point=cv2.minMaxLoc(distance)
    if peak<=0:
        raise RuntimeError('The selected person is not tracked at the first frame. Choose another interval.')
    result={**request,'frame_count':n,'prompt_frame':index,'model_x':x,'model_y':y,
            'first_x':point[0]/MODEL_W,'first_y':point[1]/MODEL_H,
            'mask_pixels':counts,'letterbox':{'left':left,'top':top,'width':w,'height':h},
            'warning':'SAM2 tracks the clicked object; review the overlay to confirm it is the intended person.'}
    (job/'selection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
