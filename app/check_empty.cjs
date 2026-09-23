const {createRequire}=require('node:module');
const load=createRequire(process.argv[2]+'/package.json');
const {chromium}=load('playwright');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1000}});
 const errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 await page.addInitScript(()=>{localStorage.setItem('vcmeSelectedMedia','sample');localStorage.setItem('vcmeActiveJob','efad161a745544f5be498ac6c99b09c2');});
 await page.goto('http://127.0.0.1:7860',{waitUntil:'networkidle'});
 async function assertEmpty(){
  if(await page.locator('.media-card').count())throw Error('Startup has media cards');
  if(await page.locator('#video').getAttribute('src'))throw Error('Startup has video source');
  if(!await page.locator('#emptyStage').isVisible())throw Error('Missing empty state');
  if(!await page.locator('#play').isDisabled()||!await page.locator('#generate').isDisabled())throw Error('Empty controls not disabled');
  if(await page.locator('#showExample').count())throw Error('Historical demo entry still visible');
 }
 await assertEmpty();
 if(requests.some(u=>u.includes('/assets/')||u.includes('/media/')||u.endsWith('/api/media')))throw Error('Automatically fetched old videos');
 await page.locator('#sourceLane').click();
 await page.screenshot({path:'runtime/EMPTY_UI.png',fullPage:true});
 const chooser=page.waitForEvent('filechooser');
 await page.locator('#emptyUpload').click();
 await (await chooser).setFiles('runtime/upload_test_mirrored.mp4');
 await page.waitForFunction(()=>document.querySelector('#video').videoWidth>0,null,{timeout:120000});
 if(await page.locator('.media-card').count()!==1)throw Error('Should show only this uploaded video');
 if(await page.locator('#play').isDisabled()||await page.locator('#start').isDisabled())throw Error('Upload did not unlock editor');
 await page.reload({waitUntil:'networkidle'});await assertEmpty();
 if(errors.length)throw Error(errors.join('\n'));
 console.log(JSON.stringify({empty_start:true,ignores_previous_media:true,no_preloaded_video_requests:true,upload_enables_editor:true,reload_empty:true,jsErrors:errors}));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});

