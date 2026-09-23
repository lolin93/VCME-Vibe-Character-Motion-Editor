"""Loopback-only UI; computation runs in an isolated Docker job."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from urllib.parse import unquote, urlparse
from pipeline import DEFAULT_MOTION
import editor_api
import runtime_health

ROOT = Path(__file__).resolve().parents[1]
LOCK = threading.Lock()
ACTIVE = None
IMAGE = 'vcme-storymem:transition-v27'

def safe_job(job_id):
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('Invalid job ID')
    return ROOT/'jobs'/job_id

def status(job, **data):
    tmp=job/'status.tmp'
    tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    tmp.replace(job/'status.json')

def worker(job):
    global ACTIVE
    try:
        status(job,state='running',message='處理中，詳見執行紀錄')
        request=json.loads((job/'request.json').read_text(encoding='utf-8'))
        check=runtime_health.health()
        if not check['ready']:
            (job/'run.log').write_text(check.get('detail',''),encoding='utf-8')
            status(job,state='failed',message=check['message'],error_code=check['code'])
            return
        cmd=['docker','run','--rm','--name','vcme-v58-job-'+job.name,'--shm-size','16g']
        if request['mode']!='retime': cmd+=['--gpus','all']
        cmd+=['--entrypoint','python3.10','-v',str(ROOT)+':/workspace',
              '-v',str(ROOT/'models')+':/workspace/models:ro',
              '-e','PYTHONPATH=/workspace/external/sam2:/workspace/external/StoryMem',
              '-e','PYTHONDONTWRITEBYTECODE=1','-w','/workspace',IMAGE,
              '-u','app/pipeline.py','--request','/workspace/jobs/'+job.name+'/request.json']
        with (job/'run.log').open('w',encoding='utf-8') as log:
            p=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        target='selection.json' if request['mode']=='select' else 'result.mp4'
        ok=p.returncode==0 and (job/target).is_file()
        message=('人物選取完成，請確認綠色範圍' if request['mode']=='select' else '影片已完成，可以預覽與匯出') if ok else runtime_health.failure((job/'run.log').read_text(encoding='utf-8',errors='replace'))
        status(job,state='done' if ok else 'failed',message=message,exit_code=p.returncode)
    except Exception as exc:
        status(job,state='failed',message=str(exc))
    finally:
        with LOCK: ACTIVE=None

def recover_worker(job):
    """Observe only this app's orphaned container; never restart a generation."""
    global ACTIVE
    request=json.loads((job/'request.json').read_text(encoding='utf-8'))
    target='selection.json' if request['mode']=='select' else 'result.mp4'
    try:
        # docker wait preserves the exit status even when --rm removes the container.
        p=subprocess.run(['docker','wait','vcme-v58-job-'+job.name],capture_output=True,text=True)
        successful_exit=p.returncode==0 and p.stdout.strip()=='0'
        ok=(job/target).is_file() and (successful_exit or (job/'completed.json').is_file())
        status(job,state='done' if ok else 'interrupted',message='已找回完成的工作；請檢查紀錄' if ok else '先前工作已停止且無完整結果；沒有自動重跑')
    finally:
        with LOCK: ACTIVE=None

class Handler(BaseHTTPRequestHandler):
    def json_response(self,data,code=200):
        raw=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        if self.headers.get('Host') not in ('127.0.0.1:7860','localhost:7860'):
            return self.send_error(403)
        path=unquote(urlparse(self.path).path)
        try:
            if path=='/api/config':
                return self.json_response({'motion':'','duration':3,'seed':2025,'active':ACTIVE,'max_duration':editor_api.MAX_EDIT_SECONDS})
            if path=='/api/health':
                return self.json_response(runtime_health.health())
            if path=='/api/media':
                return self.json_response(editor_api.catalog())
            if path=='/api/jobs':
                jobs=[]
                for p in sorted((ROOT/'jobs').glob('*/status.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:30]:
                    request=json.loads((p.parent/'request.json').read_text(encoding='utf-8'))
                    jobs.append({'id':p.parent.name,'mode':request['mode'],'media_id':request.get('media_id','sample'),**json.loads(p.read_text(encoding='utf-8'))})
                return self.json_response(jobs)
            if path.startswith('/api/job/'):
                job=safe_job(path.split('/')[-1])
                data=json.loads((job/'status.json').read_text(encoding='utf-8'))
                data['log']=(job/'run.log').read_text(encoding='utf-8',errors='replace')[-14000:] if (job/'run.log').exists() else ''
                data['request']=json.loads((job/'request.json').read_text(encoding='utf-8'))
                if (job/'selection.json').exists():
                    data['selection']=json.loads((job/'selection.json').read_text(encoding='utf-8'))
                return self.json_response(data)
            if path=='/': file=ROOT/'app/index.html'
            elif path in ('/editor.js','/editor.css'):
                file=ROOT/'app'/path[1:]
            elif path=='/favicon.ico':
                self.send_response(204); self.end_headers(); return
            elif path.startswith('/media/'):
                parts=path.strip('/').split('/')
                if len(parts)!=3 or parts[2] not in ('source.mp4','thumbnail.jpg','metadata.json'):
                    return self.send_error(404)
                file=ROOT/'media'/editor_api.valid_id(parts[1])/parts[2]
            elif path.startswith('/assets/'):
                name=path.split('/')[-1]
                if name not in ('source.mp4','V58_Balanced.mp4'): return self.send_error(404)
                file=ROOT/'assets'/name
            elif path.startswith('/jobs/'):
                parts=path.strip('/').split('/')
                if len(parts)==4 and parts[2]=='overlays' and len(parts[3])==10 and parts[3][:6].isdigit() and parts[3].endswith('.png'):
                    file=safe_job(parts[1])/'overlays'/parts[3]
                elif len(parts)==3 and parts[2] in ('result.mp4','selection.json','request.json','runtime.json','background_report.json','tail_report.json','motion_report.json','run.log'):
                    file=safe_job(parts[1])/parts[2]
                else:
                    return self.send_error(404)
            else: return self.send_error(404)
            if not file.is_file(): return self.send_error(404)
            size=file.stat().st_size; start=0; end=size-1
            range_header=self.headers.get('Range')
            if range_header:
                import re
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',range_header)
                if not match: return self.send_error(416)
                start=int(match[1]); end=min(int(match[2]),end) if match[2] else end
                if start>end: return self.send_error(416)
            self.send_response(206 if range_header else 200)
            self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            self.send_header('Accept-Ranges','bytes'); self.send_header('Content-Length',str(end-start+1))
            if range_header: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with file.open('rb') as f:
                f.seek(start); remaining=end-start+1
                while remaining:
                    chunk=f.read(min(65536,remaining))
                    if not chunk: break
                    self.wfile.write(chunk); remaining-=len(chunk)
        except (ValueError,FileNotFoundError,KeyError): self.send_error(404)
        except (BrokenPipeError,ConnectionResetError): pass

    def do_POST(self):
        global ACTIVE
        if self.headers.get('Origin') and self.headers['Origin']!='http://'+self.headers.get('Host',''):
            return self.send_error(403)
        if self.headers.get('Host') not in ('127.0.0.1:7860','localhost:7860'):
            return self.send_error(403)
        if urlparse(self.path).path in ('/api/media/remove','/api/media/restore'):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<1024: raise ValueError('Invalid request')
                data=json.loads(self.rfile.read(size)); ident=editor_api.valid_id(data.get('id'))
                with LOCK:
                    if ACTIVE:
                        req=json.loads((safe_job(ACTIVE)/'request.json').read_text(encoding='utf-8'))
                        if req.get('media_id')==ident:
                            return self.json_response({'error':'此影片正在處理中，完成後才能移除'},409)
                    item=editor_api.set_removed(ident,urlparse(self.path).path.endswith('/remove'))
                return self.json_response(item)
            except (ValueError,FileNotFoundError,KeyError) as exc:
                return self.json_response({'error':str(exc)},400)
        if self.path=='/api/run':
            return self.json_response({'error':'舊實驗入口已停用，請上傳影片並使用編輯器'},410)
        if urlparse(self.path).path in ('/api/media','/api/editor/run'):
            try:
                if urlparse(self.path).path=='/api/media':
                    return self.json_response(editor_api.upload(self),201)
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=32000: raise ValueError('Request too large')
                request=editor_api.validate(json.loads(self.rfile.read(size)))
                with LOCK:
                    if ACTIVE: return self.json_response({'error':'已有 SAM2 或生成工作執行中'},409)
                    ident=uuid.uuid4().hex; job=safe_job(ident); job.mkdir(parents=True)
                    request['runtime_image']=IMAGE
                    request['created_at']=time.time()
                    (job/'request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
                    status(job,state='queued',message='SAM2 追蹤中' if request['mode']=='select' else '已排入生成工作')
                    ACTIVE=ident
                    threading.Thread(target=worker,args=(job,),daemon=True).start()
                return self.json_response({'id':ident},202)
            except (ValueError,KeyError,FileNotFoundError,subprocess.SubprocessError) as exc:
                return self.json_response({'error':str(exc)},400)
        if self.path!='/api/run': return self.send_error(404)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<=0 or size>180*1024*1024: return self.json_response({'error':'影片上限 100 MB'},413)
            data=json.loads(self.rfile.read(size)); mode=data.get('mode')
            if mode=='generate':
                raise ValueError('請使用新版人物選取與生成介面 /api/editor/run')
            if mode not in ('generate','repair','retime'): raise ValueError('Invalid mode')
            start=float(data.get('start',2)); x=float(data.get('x',0.5)); y=float(data.get('y',0.42))
            seed=int(data.get('seed',2025)); motion=str(data.get('motion',DEFAULT_MOTION)).strip()
            if not all(math.isfinite(v) for v in (start,x,y)) or start<0 or not 0<=x<=1 or not 0<=y<=1 or not 0<=seed<2**63 or not motion or len(motion)>8000:
                raise ValueError('參數不合法')
            payload=None
            if mode=='generate' and data.get('video'):
                payload=base64.b64decode(data['video'],validate=True)
                if len(payload)>100*1024*1024: raise ValueError('影片超過 100 MB')
            with LOCK:
                if ACTIVE: return self.json_response({'error':'已有工作執行中'},409)
                job_id=uuid.uuid4().hex; job=safe_job(job_id); job.mkdir(parents=True)
                source='/workspace/assets/source.mp4'
                if payload is not None:
                    (job/'input.mp4').write_bytes(payload); source='/workspace/jobs/'+job_id+'/input.mp4'
                if mode!='generate': start=2.0
                request={'mode':mode,'source':source,'start':start,'duration':3.0,'seed':seed,'motion':motion,'x':x,'y':y,'recipe':'V40/V52 -> V57 -> V58 Balanced','runtime_image':IMAGE}
                (job/'request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
                status(job,state='queued',message='工作已建立'); ACTIVE=job_id
                threading.Thread(target=worker,args=(job,),daemon=True).start()
            self.json_response({'id':job_id},202)
        except (ValueError,KeyError) as exc: self.json_response({'error':str(exc)},400)

if __name__=='__main__':
    (ROOT/'jobs').mkdir(exist_ok=True)
    for p in (ROOT/'jobs').glob('*/status.json'):
        data=json.loads(p.read_text(encoding='utf-8'))
        if data.get('state') in ('running','queued'):
            check=subprocess.run(['docker','inspect','--format','{{.State.Running}}','vcme-v58-job-'+p.parent.name],capture_output=True,text=True)
            if check.returncode==0 and check.stdout.strip()=='true':
                ACTIVE=p.parent.name
                threading.Thread(target=recover_worker,args=(p.parent,),daemon=True).start()
            else:
                request=json.loads((p.parent/'request.json').read_text(encoding='utf-8'))
                target='selection.json' if request['mode']=='select' else 'result.mp4'
                ok=(p.parent/target).is_file() and (p.parent/'completed.json').is_file()
                status(p.parent,state='done' if ok else 'interrupted',message='找到上次工作結果，請检查紀錄' if ok else '上次工作已停止，紀錄已保留')
    print('VCME V58 Demo: http://127.0.0.1:7860',flush=True)
    server=ThreadingHTTPServer(('127.0.0.1',7860),Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nUI stopped. Existing Docker computation, if any, is not terminated.',flush=True)
    finally:
        server.server_close()
