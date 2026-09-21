const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const locales = ['en','uk','pl','de','es','fr'].map(code => [code, fs.readFileSync(path.join(root,'../src-core/vaultdrop/locales',code+'.json'),'utf8')]);
const server = http.createServer((req,res) => {
 const name=req.url==='/'?'index.html':req.url.slice(1);
 if(!['index.html','app.js','bridge.js','model.js','style.css'].includes(name)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript; charset=utf-8':name.endsWith('.css')?'text/css':'text/html; charset=utf-8');
 res.end(fs.readFileSync(path.join(root,'ui',name)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({channel:process.env.VAULTDROP_BROWSER||'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1180,height:860}});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  // Explicit host double for UI tests; never bundled in the product.
  await page.addInitScript(({locales})=>{
   const handlers={},emit=(name,payload)=>handlers[name]?.({payload});
   window.testHost={picks:[],scenario:'safe',calls:[],emit};
   window.__TAURI__={event:{listen:async(name,fn)=>{handlers[name]=fn;return()=>{};}},window:{getCurrentWindow:()=>({onCloseRequested:async fn=>{testHost.close=fn;},destroy:async()=>{testHost.destroyed=true;}})},core:{invoke:async(command,args)=>{
    testHost.calls.push({command,args});
    switch(command){
     case 'locales':return locales;
     case 'drive_mask':return 7;
     case 'list_drives':return [{root:'C:\\',label:'Windows',fs:'NTFS',total:512*2**30,free:185*2**30,system:true,disk:0},{root:'D:\\',label:'Samsung T7',fs:'exFAT',total:1e12,free:724*2**30,usb:true,disk:1},{root:'E:\\',label:'Archive',fs:'NTFS',total:2e12,free:1.3e12,disk:2}];
     case 'pick_folder':return testHost.picks.shift()||null;
     case 'folder_stats':if(args.path.includes('missing'))throw 'Folder not found';return {files:1248,bytes:12.4*2**30,errors:0};
     case 'inspect_folder':return {exists:false,empty:true,backup:false};
     case 'ask':return true;
     case 'find_backups':return [];
     case 'cancel_run':emit('cli-exit',1);return;
     case 'open_path':return;
     case 'run_cli':{
      const scenario=testHost.scenario;
      setTimeout(()=>{
       emit('cli-line',JSON.stringify({event:'start',files:1248,bytes:12.4*2**30}));
       emit('cli-line',JSON.stringify({event:'progress',files_done:517,bytes_done:5.8*2**30,current:'Photos/2026/IMG_0428.jpg'}));
       if(scenario==='running')return;
       if(scenario==='crash'){emit('cli-exit',-1);return;}
       setTimeout(()=>{
        const event=args.args[0]==='verify'?{result:{result:scenario==='incomplete'?'INCOMPLETE':'INTACT',intact:1248,changed:0,missing:0,unreadable:0,run_verdict:scenario==='incomplete'?'FAIL':'SAFE TO FORMAT'}}:{report:{verdict:'SAFE TO FORMAT',ok:1248,total:1248,bytes_read:12.4*2**30,seconds:150,dests:['D:\\VaultDrop Backups\\Photos and documents']}};
        emit('cli-line',JSON.stringify({event:'done',...event,text:'Operation result'}));emit('cli-exit',scenario==='incomplete'?1:0);
       },60);
      },30);return;
     }
     default:throw Error('Unknown host command: '+command);
    }
   }}};
  },{locales});
  await page.goto('http://127.0.0.1:'+server.address().port);
  await page.waitForFunction(()=>document.querySelectorAll('.drive').length===3);
  assert(await page.locator('#start').isDisabled());
  assert.equal(await page.locator('html').getAttribute('lang'),'en');
  await page.evaluate(()=>testHost.picks.push('C:\\Users\\Alex\\Photos and documents'));
  await page.click('#pick-source');await page.waitForFunction(()=>document.querySelector('#plan-files').textContent.includes('248'));
  await page.locator('.drive').filter({hasText:'Samsung T7'}).click();assert(await page.locator('#start').isEnabled());
  const shots=path.join(root,'../docs/screenshots');fs.mkdirSync(shots,{recursive:true});
  const shot=name=>page.screenshot({path:path.join(shots,name+'-en.png'),fullPage:true});
  await shot('backup');
  for(const lang of ['uk','de','pl','es','fr','en']){
   await page.selectOption('#lang',lang);assert.equal(await page.locator('html').getAttribute('lang'),lang);
   assert.equal(await page.locator('[data-i18n]').evaluateAll(ns=>ns.filter(n=>n.textContent.startsWith('ui.')).length),0);
  }
  await page.setViewportSize({width:760,height:600});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await shot('compact');
  await page.setViewportSize({width:1180,height:860});
  await page.click('#start');await page.waitForSelector('#result-card.ok');await shot('result');
  await page.click('#done');await page.click('#tab-verify');await page.waitForSelector('.empty-state');await shot('verify');
  await page.evaluate(()=>{testHost.scenario='incomplete';testHost.picks.push('D:\\Backup');});
  await page.click('#pick-backup');await page.waitForSelector('#result-card.warn');assert((await page.locator('#result-title').textContent()).includes('incomplete'));
  await page.click('#done');await page.click('#tab-copy');await page.evaluate(()=>{testHost.scenario='running';});
  await page.click('#start');await page.waitForFunction(()=>document.querySelector('#progress-percent').textContent!=='0%');assert(await page.locator('#tab-copy').isDisabled());await shot('progress');
  await page.click('#stop-run');await page.waitForSelector('#result-card.warn');assert((await page.locator('#result-title').textContent()).includes('stopped'));
  await page.click('#done');await page.evaluate(()=>{testHost.scenario='crash';});
  await page.click('#start');await page.waitForSelector('#result-card.bad');assert((await page.locator('#result-text').textContent()).includes('-1'));
  await page.click('#done');await page.evaluate(()=>testHost.picks.push('C:\\missing'));
  await page.click('#pick-source');await page.waitForSelector('#global-error:not([hidden])');assert(await page.locator('#start').isDisabled());assert.deepEqual(errors,[]);
  console.log('UI passed: copy, verify, incomplete backup, cancellation, crash, folder error, six languages, compact layout.');
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
