const {chromium}=require('playwright');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..');const work=path.join(root,'.tmp','native-cancel-'+Date.now());
 const source=path.join(work,'source'),dest=path.join(work,'backup');fs.mkdirSync(source,{recursive:true});
 fs.writeFileSync(path.join(source,'large.bin'),Buffer.alloc(64*1024*1024,73));
 const browser=await chromium.connectOverCDP(process.env.VAULTDROP_CDP||'http://127.0.0.1:19371');
 try{
  const page=browser.contexts()[0].pages().find(p=>p.url().includes('tauri.localhost'));
  await page.evaluate(({source,dest})=>{localStorage.setItem('vaultdrop.source',JSON.stringify(source));localStorage.setItem('vaultdrop.dests',JSON.stringify([{custom:dest}]));localStorage.setItem('vaultdrop.lang','"uk"');},{source,dest});
  await page.reload();await page.waitForFunction(()=>document.querySelector('#start')?.disabled===false);
  await page.evaluate(()=>{const real=window.__TAURI__.core.invoke;window.__TAURI__={...window.__TAURI__,core:{...window.__TAURI__.core,invoke:(cmd,args)=>cmd==='ask'?Promise.resolve(true):real(cmd,args)}};});
  await page.click('#start');
  const limit=Date.now()+30000;while(!fs.existsSync(path.join(dest,'.vaultdrop.running'))){if(Date.now()>limit)throw Error('Worker never started');await new Promise(r=>setTimeout(r,10));}
  await page.click('#stop-run');await page.waitForSelector('#result-card.warn',{timeout:30000});
  assert((await page.locator('#result-title').textContent()).includes('зупинено'));
  assert(fs.existsSync(path.join(dest,'.vaultdrop.running')));
  await page.click('#done');await page.click('#start');await page.waitForSelector('#result-card.ok',{timeout:60000});
  const report=JSON.parse(fs.readFileSync(path.join(dest,'vaultdrop-report.json')));
  assert.equal(report.verdict,'SAFE TO FORMAT');assert(report.previous_run_interrupted.includes(dest));
  assert.equal(fs.statSync(path.join(dest,'large.bin')).size,64*1024*1024);
  assert.deepEqual(fs.readFileSync(path.join(dest,'large.bin')),fs.readFileSync(path.join(source,'large.bin')));
  assert(!fs.existsSync(path.join(dest,'.vaultdrop.running')));
  assert(!fs.readdirSync(dest).some(n=>n.startsWith('.vaultdrop-tmp-')));
  await page.evaluate(()=>localStorage.clear());
  console.log(JSON.stringify({status:'passed',work,checks:['native process-tree cancellation','interrupted marker retained','OS lock released','restart recovery','temporary files cleaned','64 MiB copy verified']},null,2));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
