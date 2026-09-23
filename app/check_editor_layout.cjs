const {createRequire}=require('node:module');
const load=createRequire(process.argv[2]+'/package.json');
const {chromium}=load('playwright');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1366,height:900}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 // Only suppress active-task UI for read-only interaction tests. No job is submitted.
 await page.route('**/api/config',async route=>{
  const r=await route.fetch();const data=await r.json();data.active=null;
  await route.fulfill({response:r,json:data});
 });
 await page.goto('http://127.0.0.1:7860',{waitUntil:'networkidle'});
 await page.locator('#file').setInputFiles('runtime/upload_test_mirrored.mp4');
 await page.waitForFunction(()=>document.querySelector('#video').videoWidth>0);
 const before=Number(await page.locator('#end').inputValue());
 const handle=await page.locator('#rightHandle').boundingBox();
 await page.mouse.move(handle.x+handle.width/2,handle.y+10);
 await page.mouse.down();await page.mouse.move(handle.x+40,handle.y+10,{steps:5});await page.mouse.up();
 const after=Number(await page.locator('#end').inputValue());
 if(after<=before)throw Error('Timeline handle did not change range');
 await page.locator('#next').click();
 await page.locator('#help').click();if(!await page.locator('#helpDialog').isVisible())throw Error('Help missing');
 await page.locator('#closeHelp').click();
 await page.screenshot({path:'runtime/EDITOR_DESKTOP.png',fullPage:true});
 await page.setViewportSize({width:820,height:1100});
 await page.screenshot({path:'runtime/EDITOR_NARROW.png',fullPage:true});
 const invalid=await page.request.post('http://127.0.0.1:7860/api/editor/run',{data:{mode:'select',media_id:'sample',start:0,end:3}});
 if(invalid.status()!==400)throw Error('Missing edge guard');
 if(errors.length)throw Error(errors.join('\n'));
 console.log(JSON.stringify({timeline_drag:true,before,after,help:true,responsive_screenshots:true,invalid_edge_rejected:true,jsErrors:errors}));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
