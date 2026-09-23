"""V40-derived native generation on uploaded intervals, optional V57, then V58."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from selection import frame_count, select

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
DEFAULT_MOTION = ('continue the original upright incoming motion with unchanged momentum, naturally settle front-facing with both feet planted, make one small clear relaxed open-palm right-hand greeting wave beside the face, lower the hand before the final quarter, and spend the final quarter smoothly resuming the exact original outgoing step and body velocity; remain standing throughout; never kneel, crouch, sit, jump or dance during the greeting; preserve identity, clothing, camera, lighting and background')

def run(args, cwd=ROOT, env=None):
    print('RUN:', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)

def py(script, *args, env=None):
    run([sys.executable, ROOT / script, *args], env=env)

def track(video, output, x, y, count=49, prompt_frame=0):
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / 'external/sam2') + os.pathsep + env.get('PYTHONPATH', '')
    py('external/sam2/run_tracking.py', video, '--output-dir', output,
       '--checkpoint', ROOT / 'external/sam2/checkpoints/sam2.1_hiera_tiny.pt',
       '--model-config', 'configs/sam2.1/sam2.1_hiera_t.yaml',
       '--click-x', round(x * 480), '--click-y', round(y * 832), '--max-frames', count,
       '--prompt-frame', prompt_frame, env=env)

def prepare(source, job, request):
    from video_io import get_video_info, sample_clip_frames, write_video
    from frame_builder import export_frame_controls
    from input_analyzer import build_text_plan, text_plan_to_dict
    from mask_builder import make_mask_from_png_sequence
    info = get_video_info(source)
    duration = request['duration']
    n = frame_count(duration)
    if request['start'] < 0 or request['start'] + duration > info.frame_count / info.fps:
        raise ValueError('Selected interval is outside the source video.')
    frames = sample_clip_frames(source, request['start'], duration, 16, n)
    write_video(job / 'source_clip.mp4', frames, 16, 480, 832)
    frame_info = export_frame_controls(frames, job, 480, 832, 5)
    text = text_plan_to_dict(build_text_plan(request['motion']))
    selection_job = ROOT/'jobs'/request['selection_id']
    selection = json.loads((selection_job/'selection.json').read_text(encoding='utf-8'))
    for key in ('source','start','duration','media_id'):
        if selection[key] != request[key]:
            raise ValueError('Selection no longer matches this source and interval')
    shutil.copytree(selection_job/'source_masks',job/'source_masks')
    request['first_x'],request['first_y']=selection['first_x'],selection['first_y']
    make_mask_from_png_sequence(sorted((job / 'source_masks').glob('mask_*.png')),
        480, 832, 16, job, dilate_pixels=15, feather_pixels=9,
        max_dilate_pixels=26, dilation_motion_gain=220.0, temporal_sigma_frames=1.0)
    controls = job / 'controls'
    controls.mkdir()
    shutil.copy2(job / 'source_clip.mp4', controls / 'source_01.mp4')
    py('scripts/build_temporal_envelope_mask.py', '--input', job / 'M/mask_video.mp4',
       '--output', controls / 'mask_01.mp4', '--dilation', 25, '--sigma', 4.0,
       '--window', -1, '--report', job / 'mask_parameters.json')
    shutil.copy2(frame_info['first_frame'], job / 'first_frame_condition.png')
    shutil.copy2(frame_info['last_frame'], job / 'tfm_last_frame.png')
    # Preserve the recovered runner: five candidates, three selected initial memories.
    keys = frame_info['memory_keyframes']
    for i, key in enumerate([keys[0], keys[len(keys)//2], keys[-1]], 1):
        shutil.copy2(key, job / ('source_keyframe_%02d.jpg' % i))
    # General actions must not inherit the historical wave-only prohibitions.
    text['negative_prompt'] = 'different person, changed clothes, broken anatomy, extra fingers, fused fingers, missing hand, motion smear, duplicated body, ghosting, dissolve, black silhouette, unstable camera'
    text['model_prompt'] += ' Begin with the original incoming motion and smoothly resume the original outgoing motion near the end.'
    (job / 'manifest.json').write_text(json.dumps({'source':str(source), 'F':frame_info, 'T':text, 'settings':request},ensure_ascii=False,indent=2),encoding='utf-8')
    (job / 'vcme_story.json').write_text(json.dumps({'story_overview':'Source conditioned motion edit','scenes':[{'scene_num':1,'cut':[False],'video_prompts':[text['model_prompt']]}]},ensure_ascii=False),encoding='utf-8')
    return text

def generate(source, job, request):
    text = prepare(source, job, request)
    # No ambient experimental env switches are inherited by the generation subprocess.
    env = {k:v for k,v in os.environ.items() if not k.startswith('STORYMEM_')}
    env.update({
      'PYTHONPATH': str(ROOT / 'external/StoryMem'),
      'STORYMEM_RESUME_EXISTING':'1', 'STORYMEM_MAX_NEW_SHOTS':'1',
      'STORYMEM_USE_HPSV3_KEYFRAMES':'0', 'STORYMEM_SOFT_LOCK_LAST_FRAME':'0',
      'STORYMEM_START_SOFT_LOCK':'0', 'STORYMEM_START_HARD_LOCK_LATENTS':'1',
      'STORYMEM_END_HARD_LOCK_LATENTS':'1', 'STORYMEM_LATENT_OVERLAP_FRAMES':'0',
      'STORYMEM_POSE_LOCK_STRENGTH':'0', 'STORYMEM_SOURCE_PRESERVE_WEIGHT':'0',
      'STORYMEM_TERMINAL_RAMP':'0','STORYMEM_KEEP_FIRST_FRAME':'1',
      'STORYMEM_FIRST_FRAME_CONDITION_FILE':'first_frame_condition.png',
      'STORYMEM_DYNAMIC_CFG':'1','STORYMEM_CFG_ENDPOINT':'2.75',
      'STORYMEM_CFG_MIDDLE':'4.50','STORYMEM_CFG_RAMP_FRAMES':'2',
      'PYTORCH_CUDA_ALLOC_CONF':'expandable_segments:True','MALLOC_ARENA_MAX':'2'})
    request['generation_env'] = {k:v for k,v in env.items() if k.startswith('STORYMEM_')}
    (job / 'runtime.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    model_root = ROOT / 'models'
    run([sys.executable,'pipeline.py','--story_script_path',job/'vcme_story.json',
      '--i2v_model_path',model_root/'Wan2.2-I2V-A14B',
      '--lora_weight_path',model_root/'StoryMem/Wan2.2-MI2V-A14B',
      '--size','832*480','--max_memory_size','5','--fix','3',
      '--output_dir',job,'--seed',request['seed'],'--sample_steps','40',
      '--frame_num',str(frame_count(request['duration'])),'--sample_guide_scale','3.5','--resident_models',
      '--convert_model_dtype','--no_lock_last_frame','--lora_rank','128',
      '--m2v_first_shot','--mi2v','--source_video_path',job/'controls',
      '--mask_video_path',job/'controls','--last_frame_path',job/'tfm_last_frame.png',
      '--negative_prompt',text['negative_prompt']],cwd=ROOT/'external/StoryMem',env=env)
    return job / '01_01.mp4', job / 'source_clip.mp4', job / 'M/mask_video.mp4'

def restore(core, source_core, source_mask, job, request):
    import cv2
    from video_io import write_video
    n=frame_count(request['duration'])
    track(core, job / 'generated_masks', request.get('first_x',request['x']), request.get('first_y',request['y']),n)
    frames = [cv2.imread(str(p)) for p in sorted((job/'generated_masks').glob('mask_*.png'))]
    if len(frames) != n or any(f is None for f in frames):
        raise RuntimeError('SAM2 generated-person masks are incomplete.')
    write_video(job/'generated_mask.mp4',frames,16,480,832)
    py('scripts/restore_generated_background_flow.py','--generated',core,'--source',source_core,
       '--source-mask',source_mask,'--generated-mask',job/'generated_mask.mp4',
       '--output',job/'restored_core.mp4','--alpha-video',job/'background_alpha.mp4',
       '--report',job/'background_report.json','--local-window',1,'--guard-pixels',18,
       '--feather-pixels',24,'--minimum-flow-confidence',0.72)
    return job/'restored_core.mp4'

def finish(source, core, job, request):
    py('scripts/optimize_tail_velocity_splice.py','--source',source,'--generated',core,
       '--start-sec',request['start'],'--duration-sec',request['duration'],'--tail-frames',15,
       '--end-slopes',0.4,'--window-frames',6,'--output',job/'assembled.mp4',
       '--report',job/'tail_report.json')
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',job/'assembled.mp4','-i',source,
         '-map','0:v:0','-map','1:a?','-c:a','aac',
         '-c:v','libx264','-preset','medium','-crf','16','-pix_fmt','yuv420p',
         '-movflags','+faststart',job/'result.mp4'])
    py('scripts/evaluate_optical_flow_c1c2_continuity.py','--source',source,
       '--candidate',job/'result.mp4','--start-sec',request['start'],
       '--end-sec',request['start']+request['duration'],'--report',job/'motion_report.json')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args()
    request=json.loads(args.request.read_text(encoding='utf-8'))
    job=args.request.resolve().parent
    source=Path(request['source'])
    if request['mode']=='select':
        select(source,job,request,track)
        (job/'completed.json').write_text(json.dumps({'mode':'select','success':True}),encoding='utf-8')
        print('DONE: SAM2 selection',flush=True)
        return
    if request['mode']=='generate':
        core, source_core, mask=generate(source,job,request)
        if request.get('preserve',True):
            core=restore(core,source_core,mask,job,request)
    elif request['mode']=='repair':
        core=restore(ROOT/'assets/native_core.mp4',ROOT/'assets/source_core.mp4',ROOT/'assets/source_mask.mp4',job,request)
    elif request['mode']=='retime':
        core=ROOT/'assets/restored_core.mp4'
    else:
        raise ValueError('Unknown mode')
    finish(source,core,job,request)
    (job/'completed.json').write_text(json.dumps({'mode':request['mode'],'success':True}),encoding='utf-8')
    print('DONE: '+str(job/'result.mp4'),flush=True)

if __name__=='__main__':
    main()
