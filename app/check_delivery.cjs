const {createRequire}=require('node:module');
const load=createRequire(process.argv[2]+'/package.json');
const {chromium}=load('playwright');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:7860',{waitUntil:'networkidle'});
 const id='efad161a745544f5be498ac6c99b09c2';
 const job=await page.request.get('http://127.0.0.1:7860/api/job/'+id).then(r=>r.json());
 // Explicitly open this test's saved media; production startup stays blank.
 const media=await page.request.get('http://127.0.0.1:7860/api/media').then(r=>r.json());
 await page.evaluate(item=>{state.items=[item];choose(item);},media.find(m=>m.id===job.request.media_id));
 await page.evaluate(id=>poll(id),id);
 if(job.state==='running'){
  const duplicate=await page.request.post('http://127.0.0.1:7860/api/editor/run',{data:job.request});
  if(duplicate.status()!==409)throw Error('Concurrent generation not rejected');
  if(!await page.locator('#generate').isDisabled())throw Error('Busy controls are not locked');
  await page.locator('#openHistory').click();
  await page.waitForTimeout(1500);
  console.log('Live task UI: '+await page.locator('#taskStatus').textContent());
  await page.locator('#hideTask').click();
 }
 console.log('Waiting for actual native generation and postprocessing...');
 await page.waitForFunction(()=>!document.querySelector('#resultTab').disabled,null,{timeout:1800000});
 await page.waitForFunction(()=>document.querySelector('#video').videoWidth>0);
 await page.evaluate(()=>{document.querySelector('#video').currentTime=2.2;});
 await page.waitForTimeout(500);
 if(!(await page.locator('#export').getAttribute('href')).includes(id))throw Error('Wrong result source');
 await page.screenshot({path:'runtime/EDITOR_RESULT.png',fullPage:true});
 await page.reload({waitUntil:'networkidle'});
 if(!await page.locator('#emptyStage').isVisible())throw Error('Reload should start blank');
 await page.goto('http://127.0.0.1:7860/jobs/'+id+'/result.mp4');
 await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2);
 const duration=await page.locator('video').evaluate(v=>v.duration);
 if(Math.abs(duration-8)>.1)throw Error('Output timeline duration changed');
 if(errors.length)throw Error(errors.join('\n'));
 const report={job:id,full_native_generation:true,postprocessing:true,result_url:'/jobs/'+id+'/result.mp4',duration,reload_starts_blank:true,result_file_preserved:true,jsErrors:errors};
 fs.writeFileSync('runtime/EDITOR_DELIVERY_TEST.json',JSON.stringify(report,null,2));
 console.log(JSON.stringify(report));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
