'use strict';
const $=id=>document.getElementById(id), video=$('video');
const state={media:null,items:[],start:0,end:3,selection:null,result:null,view:'source',busy:null,maskURL:'',config:null};
let healthChecking=false, removedItem=null;
const time=t=>{t=Math.max(0,t||0);return String(Math.floor(t/60)).padStart(2,'0')+':'+(t%60).toFixed(2).padStart(5,'0');};
const notice=(text,error=false)=>{$('notice').textContent=text;$('notice').style.color=error?'#ffaaa6':'#b4c9c1';};
async function api(url,options){
 const response=await fetch(url,options);
 const data=await response.json();
 if(!response.ok)throw new Error(data.error||response.statusText);
 return data;
}
const post=(url,data)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function fit(){
 if(!video.videoWidth)return;
 const rect=$('stage').getBoundingClientRect();
 const scale=Math.min(rect.width/video.videoWidth,rect.height/video.videoHeight);
 $('picture').style.width=video.videoWidth*scale+'px';
 $('picture').style.height=video.videoHeight*scale+'px';
}
function frameCount(){return 4*Math.max(4,Math.round((state.end-state.start)*4))+1;}
function invalidate(){
 state.selection=null;state.maskURL='';$('mask').hidden=true;$('clickPoint').hidden=true;
 $('selectionStatus').textContent='尚未選取。請在修改區間內點選人物，等待自動辨識。';
 $('personClip').textContent='尚未選擇人物';buttons();
}
function buttons(){
 $('generate').disabled=!!state.busy||!state.selection||!$('motion').value.trim()||!state.health?.ready;
 for(const id of ['start','end','startSlider','endSlider','setStart','setEnd','clearSelection','import']){
  $(id).disabled=!!state.busy||(id!=='import'&&!state.media);
 }
 for(const id of ['play','back','next','seek','speed','zoom','sourceTab','leftHandle','rightHandle','showMask'])$(id).disabled=!state.media;
 $('emptyUpload').disabled=!!state.busy;
 $('motion').disabled=!state.media;
 $('resultTab').disabled=!state.result;
 $('export').classList.toggle('disabled',!state.result);
 $('export').setAttribute('aria-disabled',String(!state.result));
 if(state.result){$('export').href=state.result;$('export').download='VCME_'+state.media.name.replace(/[^\p{L}\p{N}._-]/gu,'_')+'.mp4';}
 else $('export').removeAttribute('href');
}
async function checkHealth(){
 if(healthChecking)return;
 healthChecking=true;$('retryHealth').disabled=true;$('runtimeState').textContent='正在檢查運算服務…';
 try{
  state.health=await api('/api/health');
  $('runtimeState').textContent=state.health.ready?'● 運算服務已就緒':'● 運算服務未就緒';
  $('runtimeState').style.color=state.health.ready?'#79e1c5':'#ffb190';
  if(!state.health.ready)notice(state.health.message,true);
  else if(state.media)notice('運算服務已就緒。請在清楚可見的人物軀幹上點一下。');
 }catch(error){state.health={ready:false};$('runtimeState').textContent='● 無法連線';notice('無法檢查運算服務，請確認本機程式仍在執行後重試。',true);}
 finally{healthChecking=false;$('retryHealth').disabled=false;buttons();}
}
async function removeMedia(item){
 if(!confirm('要移除「'+item.name+'」嗎？可按「復原移除」找回，已完成的影片與原檔會保留。'))return;
 try{
  await post('/api/media/remove',{id:item.id});
  removedItem=item;
  const remaining=state.items.filter(m=>m.id!==item.id);
  if(state.media?.id===item.id)emptyEditor();
  state.items=remaining;renderMedia();buttons();
  $('undoRemove').hidden=false;
  notice('已移除素材。若按錯，可按「復原移除」。原檔與既有生成結果已保留。');
 }catch(error){notice(error.message,true);}
}
function emptyEditor(){
 state.media=null;state.items=[];state.selection=null;state.result=null;
 $('motion').value='';
 video.pause();video.removeAttribute('src');video.load();
 for(const id of ['picture','stageHint','sourceClip','editRange','personClip','resultClip','playhead'])$(id).hidden=true;
 $('emptyStage').hidden=false;$('mediaTitle').textContent='尚未匯入影片';
 $('mediaList').replaceChildren();
 const hint=document.createElement('p');hint.className='muted';hint.textContent='尚無素材，請點「＋ 匯入」。';$('mediaList').append(hint);
 $('ruler').replaceChildren();$('start').value='';$('end').value='';
 $('start').placeholder='—';$('end').placeholder='—';
 $('selectionStatus').textContent='請先上傳影片，再點選要修改的人物。';
 $('rangeSummary').textContent='上傳影片後即可選取修改區間。';
 $('durationBadge').textContent='尚未選取區間';$('frameInfo').textContent='等待匯入影片';
 $('clock').textContent='00:00.00 / 00:00.00';$('seek').value=0;
 $('history').replaceChildren();buttons();
 notice('請先上傳自己的影片，再選人物、設定區間與動作。');
}
function drawTimeline(){
 if(!state.media)return;
 const d=state.media.duration;
 $('editRange').style.left=state.start/d*100+'%';$('editRange').style.width=(state.end-state.start)/d*100+'%';
 $('personClip').style.left=state.start/d*100+'%';$('personClip').style.width=(state.end-state.start)/d*100+'%';
 const ticks=$('ruler');ticks.replaceChildren();
 for(let i=0;i<6;i++){const span=document.createElement('span');span.style.left=i/6*100+'%';span.textContent=time(d*i/6);ticks.append(span);}
 $('sourceClip').textContent='工作影片 · '+d.toFixed(2)+' 秒';
 updateTime();
}
function syncRange(){
 for(const id of ['start','startSlider'])$(id).value=state.start.toFixed(2);
 for(const id of ['end','endSlider'])$(id).value=state.end.toFixed(2);
 $('rangeSummary').textContent='將修改 '+time(state.start)+' → '+time(state.end)+'，共 '+(state.end-state.start).toFixed(2)+' 秒';
 $('durationBadge').textContent=(state.end-state.start).toFixed(2)+' 秒 · '+frameCount()+' 幀';
 $('frameInfo').textContent='本次模型輸出 '+frameCount()+' 幀／16 fps；接回所選時間長度。';
 drawTimeline();
}
function range(which,value){
 if(!state.media||state.busy)return;
 const m=2/state.media.fps+.01,max=state.config.max_duration,edge=state.media.duration-m;
 value=Number(value);if(!Number.isFinite(value)){syncRange();return;}
 if(which==='start'){
  state.start=Math.min(Math.max(m,value),edge-1);
  state.end=Math.min(edge,Math.max(state.start+1,Math.min(state.end,state.start+max)));
 }else{
  state.end=Math.max(m+1,Math.min(edge,value));
  state.start=Math.max(m,Math.min(state.end-1,Math.max(state.start,state.end-max)));
 }
 state.start=Math.round(state.start*100)/100;state.end=Math.round(state.end*100)/100;
 invalidate();syncRange();
 if(video.currentTime<state.start||video.currentTime>state.end)video.currentTime=state.start;
}
function updateTime(){
 if(!state.media)return;
 $('clock').textContent=time(video.currentTime)+' / '+time(video.duration||state.media.duration);
 $('seek').value=video.currentTime;
 const lane=$('sourceLane');
 $('playhead').style.left=(80+lane.clientWidth*video.currentTime/state.media.duration)+'px';
 updateMask();
}
function updateMask(){
 const s=state.selection;
 if(!s||state.view!=='source'||!$('showMask').checked||video.currentTime<state.start-.03||video.currentTime>state.end+.03){
  $('mask').hidden=true;return;
 }
 const i=Math.min(s.frame_count-1,Math.max(0,Math.round((video.currentTime-state.start)/(state.end-state.start)*(s.frame_count-1))));
 const url='/jobs/'+s.id+'/overlays/'+String(i).padStart(6,'0')+'.png';
 if(state.maskURL!==url){state.maskURL=url;$('mask').src=url;}
 $('mask').hidden=false;
}
function renderMedia(){
 $('mediaList').replaceChildren();
 for(const item of state.items){
  const b=document.createElement('button');b.className='media-card'+(state.media?.id===item.id?' active':'');
  if(item.thumbnail){const img=document.createElement('img');img.src=item.thumbnail;img.alt='影片縮圖';b.append(img);}
  else{const v=document.createElement('video');v.src=item.url;v.muted=true;v.preload='metadata';b.append(v);}
  const title=document.createElement('strong');title.textContent=item.name;
  const meta=document.createElement('span');meta.textContent=item.duration.toFixed(2)+' 秒 · '+item.width+' × '+item.height;
  b.append(title,meta);b.onclick=()=>{if(state.busy){notice('請等目前工作完成後再切換影片。');return;}choose(item);};
  const wrapper=document.createElement('div');wrapper.className='media-entry';
  const remove=document.createElement('button');remove.className='remove-media';remove.textContent='移除';remove.title='移除 '+item.name;remove.setAttribute('aria-label','移除 '+item.name);
  remove.onclick=()=>removeMedia(item);wrapper.append(b,remove);$('mediaList').append(wrapper);
 }
}
function choose(item){
 if(state.media?.id!==item.id)$('motion').value='';
 state.media=item;state.result=null;state.view='source';
 $('emptyStage').hidden=true;
 for(const id of ['picture','stageHint','sourceClip','editRange','personClip','playhead'])$(id).hidden=false;
 localStorage.setItem('vcmeSelectedMedia',item.id);
 const margin=2/item.fps+.02;
 state.start=Math.round(Math.min(2,Math.max(margin,item.duration-3-margin))*100)/100;
 state.end=Math.round(Math.min(state.start+3,item.duration-margin)*100)/100;
 for(const id of ['startSlider','endSlider']){$(id).min=margin;$(id).max=item.duration-margin;}
 $('seek').max=item.duration;
 $('mediaTitle').textContent=item.name;
 video.src=item.url;video.load();invalidate();syncRange();renderMedia();switchView('source');
 $('resultClip').hidden=true;$('emptyResult').hidden=false;
 try{
  const saved=JSON.parse(localStorage.getItem('vcmeResult_'+item.id)||'null');
  if(saved&&/^[a-f0-9]{32}$/.test(saved.id)){
   state.result='/jobs/'+saved.id+'/result.mp4';
   $('resultClip').hidden=false;$('emptyResult').hidden=true;
   $('resultClip').style.left=saved.start/item.duration*100+'%';
   $('resultClip').style.width=saved.duration/item.duration*100+'%';
   buttons();
  }
 }catch(error){localStorage.removeItem('vcmeResult_'+item.id);}
 notice(state.health?.ready?'影片已上傳。選好修改區間後，點人物並輸入想要的動作。':'影片已上傳。運算服務未就緒，請先按「重新檢查」；不需要重新上傳。',!state.health?.ready);
}
function switchView(view){
 if(!state.media)return;
 if(view==='result'&&!state.result)return;
 const t=video.currentTime;
 state.view=view;video.pause();video.src=view==='source'?state.media.url:state.result;
 video.addEventListener('loadedmetadata',()=>{video.currentTime=Math.min(t,video.duration);fit();},{once:true});
 $('sourceTab').classList.toggle('active',view==='source');$('resultTab').classList.toggle('active',view==='result');
 $('stageHint').textContent=view==='source'?'在修改區間內暫停，點選人物':'生成結果 · 請檢查首尾接點與人物動作';
 $('clickPoint').hidden=true;updateMask();buttons();
}
function request(mode){
 return {mode,media_id:state.media.id,start:state.start,end:state.end,
  click_time:Math.min(state.end,Math.max(state.start,video.currentTime)),
  motion:$('motion').value,seed:$('seed').value,preserve:$('preserve').checked,
  selection_id:state.selection?.id};
}
function taskDialog(mode){
 $('taskTitle').textContent=mode==='select'?'正在選取人物':'正在生成新片段';
 $('taskStatus').textContent='工作已送出…';$('log').textContent='';
 if(!$('taskDialog').open)$('taskDialog').showModal();
}
async function startJob(req){
 state.busy='submitting';buttons();taskDialog(req.mode);
 try{
  const job=await post('/api/editor/run',req);state.busy=job.id;
  localStorage.setItem('vcmeActiveJob',job.id);poll(job.id);
 }catch(error){state.busy=null;buttons();$('taskDialog').close();notice(error.message,true);}
}
async function poll(id){
 try{
  const job=await api('/api/job/'+id);
  $('taskStatus').textContent=job.message;$('log').textContent=job.log;
  if(['queued','running'].includes(job.state)){
   const log=job.log||'';
   let phase=job.request.mode==='select'?'正在辨識人物並追蹤所選區間':'準備影片與動作條件';
   if(log.includes('Loading M2V')||log.includes('Creating WanModel'))phase='載入影片生成模型（首次載入可能較久）';
   const steps=[...log.matchAll(/(\d+)\/40\s*\[/g)];
   if(steps.length)phase='生成進度 '+steps[steps.length-1][1]+' / 40';
   if(log.includes('generated_masks'))phase='追蹤新生成人物並修復背景';
   if(log.includes('optimize_tail_velocity_splice.py'))phase='平滑動作過渡並接回影片';
   if(log.includes('evaluate_optical_flow_c1c2_continuity.py'))phase='評估首尾速度與加速度連續性';
   const elapsed=job.request.created_at?' · 已用 '+Math.floor((Date.now()/1000-job.request.created_at)/60)+' 分鐘':'';
   $('taskStatus').textContent=phase+elapsed;
   notice(job.request.mode==='select'?'正在追蹤人物，完成後請確認綠色選取範圍。':'正在根據你的動作描述修改影片。點「紀錄」可查看進度。');
   setTimeout(()=>poll(id),2500);return;
  }
  state.busy=null;localStorage.removeItem('vcmeActiveJob');$('taskDialog').close();
  if(job.state==='done'&&job.request.media_id===state.media?.id){
   if(job.request.mode==='select'){
    state.selection={...job.selection,id};
    state.start=job.request.start;state.end=job.request.start+job.request.duration;syncRange();
    $('selectionStatus').textContent='人物選取完成。請拖動播放頭，確認綠色範圍一直包住同一個人物。';
    $('personClip').textContent='✓ 已選取人物';
    notice('人物追蹤完成。請確認遮罩；若選到背景或漏人，重新點選後再生成。');
    updateMask();
   }else{
    state.result='/jobs/'+id+'/result.mp4';
    localStorage.setItem('vcmeResult_'+state.media.id,JSON.stringify({id,start:job.request.start,duration:job.request.duration}));
    const rc=$('resultClip');rc.hidden=false;rc.style.left=job.request.start/state.media.duration*100+'%';rc.style.width=job.request.duration/state.media.duration*100+'%';
    $('emptyResult').hidden=true;switchView('result');
    notice('新影片完成，已接回本次上傳的原片時間軸。請正常速度與慢速檢查接點；可匯出影片。');
   }
  }else if(job.state==='done')notice('先前的工作已完成，可從「紀錄」查看；目前畫布保持空白，請上傳影片開始。');
  else {notice(job.message,true);if(job.error_code==='engine_unavailable'||/dockerdesktoplinuxengine|docker daemon/i.test(job.log||''))checkHealth();}
  buttons();loadHistory();
 }catch(error){
  notice('暫時無法讀取工作狀態：'+error.message+'；稍後重試，不會重送生成。',true);
  setTimeout(()=>poll(id),6000);
 }
}
async function loadHistory(){
 const jobs=await api('/api/jobs');$('history').replaceChildren();
 for(const j of jobs.slice(0,12)){
  const labels={done:'已完成',failed:'未完成',running:'處理中',queued:'等待中',interrupted:'已中斷'};
  const b=document.createElement('button');b.textContent=(j.mode==='select'?'人物選取':'影片生成／修復')+' · '+(labels[j.state]||j.state)+' · '+j.id.slice(0,8);
  b.onclick=async()=>{
   const detail=await api('/api/job/'+j.id);
   taskDialog(detail.request.mode);$('taskStatus').textContent=detail.message;$('log').textContent=detail.log;
   if(j.state==='done'&&detail.request.mode!=='select'){
    const link=document.createElement('a');link.href='/jobs/'+j.id+'/result.mp4';link.textContent=' 下載此工作結果';link.download='VCME_'+j.id.slice(0,8)+'.mp4';
    $('taskStatus').append(link);
   }
  };$('history').append(b);
 }
}
$('picture').addEventListener('click',e=>{
 if(!state.media||state.busy||state.view!=='source')return;
 if(!state.health?.ready){notice(state.health?.message||'請先確認運算服務已就緒，再點選人物。',true);checkHealth();return;}
 video.pause();
 if(video.currentTime<state.start||video.currentTime>state.end){video.currentTime=state.start;notice('已移到修改起點，請再點一下人物。');return;}
 const r=$('picture').getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;
 invalidate();$('clickPoint').style.left=x*100+'%';$('clickPoint').style.top=y*100+'%';$('clickPoint').hidden=false;
 startJob({...request('select'),x,y});
});
$('generate').onclick=()=>{if(state.selection)startJob(request('generate'));};
$('import').onclick=()=>$('file').click();
$('emptyUpload').onclick=()=>$('file').click();
$('retryHealth').onclick=checkHealth;
$('undoRemove').onclick=async()=>{
 if(!removedItem)return;
 try{const item=await post('/api/media/restore',{id:removedItem.id});state.items.push(item);renderMedia();$('undoRemove').hidden=true;removedItem=null;notice('素材已復原，請點選素材繼續編輯。');}
 catch(error){notice(error.message,true);}
};
$('file').onchange=async()=>{
 const file=$('file').files[0];if(!file)return;
 if(file.size>100*1024*1024){notice('影片超過 100 MB 上限。',true);return;}
 state.busy='upload';buttons();notice('上傳並建立相容的工作影片，原檔會保留…');
 try{
  const item=await new Promise((resolve,reject)=>{
   const xhr=new XMLHttpRequest();xhr.open('POST','/api/media?name='+encodeURIComponent(file.name));
   xhr.upload.onprogress=e=>{if(e.lengthComputable)notice('影片上傳 '+Math.round(e.loaded/e.total*100)+'% · 接著建立工作副本');};
   xhr.onload=()=>{try{const d=JSON.parse(xhr.responseText);xhr.status<300?resolve(d):reject(new Error(d.error));}catch(e){reject(e);}};
   xhr.onerror=()=>reject(new Error('上傳連線中斷'));xhr.send(file);
  });
  state.busy=null;state.items.push(item);choose(item);
 }catch(error){notice(error.message,true);state.busy=null;buttons();}
 $('file').value='';
};
$('start').onchange=e=>range('start',e.target.value);$('end').onchange=e=>range('end',e.target.value);
$('startSlider').oninput=e=>range('start',e.target.value);$('endSlider').oninput=e=>range('end',e.target.value);
$('setStart').onclick=()=>range('start',video.currentTime);$('setEnd').onclick=()=>range('end',video.currentTime);
for(const [id,which] of [['leftHandle','start'],['rightHandle','end']]){
 $(id).onpointerdown=e=>{
  if(state.busy||!state.media)return;e.preventDefault();e.stopPropagation();$(id).setPointerCapture(e.pointerId);
  $(id).onpointermove=ev=>{if(!$(id).hasPointerCapture(ev.pointerId))return;const r=$('sourceLane').getBoundingClientRect();range(which,(ev.clientX-r.left)/r.width*state.media.duration);};
  $(id).onpointerup=ev=>{$(id).releasePointerCapture(ev.pointerId);$(id).onpointermove=null;};
 };
}
$('sourceLane').onclick=e=>{if(!state.media||e.target.id==='leftHandle'||e.target.id==='rightHandle')return;const r=$('sourceLane').getBoundingClientRect();video.currentTime=Math.max(0,Math.min(state.media.duration,(e.clientX-r.left)/r.width*state.media.duration));};
$('play').onclick=()=>{if(video.paused)video.play().catch(e=>notice('無法播放：'+e.message,true));else video.pause();};
$('back').onclick=()=>{video.pause();video.currentTime=Math.max(0,video.currentTime-1/(state.media?.fps||30));};
$('next').onclick=()=>{video.pause();video.currentTime=Math.min(video.duration,video.currentTime+1/(state.media?.fps||30));};
$('seek').oninput=e=>{video.currentTime=Number(e.target.value);};
$('speed').onchange=()=>{video.playbackRate=Number($('speed').value);};
$('zoom').oninput=()=>{$('timeline').style.width=Number($('zoom').value)*100+'%';drawTimeline();};
$('clearSelection').onclick=invalidate;$('showMask').onchange=updateMask;
$('sourceTab').onclick=()=>switchView('source');$('resultTab').onclick=()=>switchView('result');$('resultClip').onclick=()=>switchView('result');
$('help').onclick=()=>$('helpDialog').showModal();$('closeHelp').onclick=()=>$('helpDialog').close();
$('hideTask').onclick=()=>$('taskDialog').close();
$('focusEdit').onclick=()=>$('motion').focus();
$('openHistory').onclick=()=>{if(state.busy&&state.busy!=='upload')taskDialog('generate');else{$('history').parentElement.open=true;$('history').scrollIntoView({behavior:'smooth'});loadHistory();}};
$('motion').oninput=buttons;
video.addEventListener('loadedmetadata',()=>{fit();updateTime();});
video.addEventListener('timeupdate',updateTime);video.addEventListener('seeked',updateTime);
video.addEventListener('play',()=>{$('play').textContent='Ⅱ';});video.addEventListener('pause',()=>{$('play').textContent='▶';});
video.addEventListener('error',()=>{if(video.error)notice('影片無法播放：'+video.error.message,true);});
new ResizeObserver(()=>{fit();drawTimeline();}).observe($('stage'));
(async()=>{
 try{
  emptyEditor();
  state.config=await api('/api/config');
  $('motion').value='';
  checkHealth();
  // Opening the editor always starts blank; old files and jobs remain on disk.
  const active=state.config.active;
  if(active){
   const job=await api('/api/job/'+active);
   if(['running','queued'].includes(job.state)){
    state.busy=active;buttons();poll(active);
   }
  }
 }catch(error){notice('載入失敗：'+error.message,true);}
})();
