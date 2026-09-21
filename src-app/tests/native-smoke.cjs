// Run against the packaged Windows app with a dedicated WebView profile and CDP port.
// Only OS confirmation dialogs are auto-accepted; all scans, copy and verify use the real host/core.
const { chromium }=require('playwright');
const fs=require('node:fs');const path=require('node:path');const crypto=require('node:crypto');const assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..');
 const work=path.join(root,'.tmp','native-smoke-'+Date.now());
 const source=path.join(work,'Тестові файли');const dest1=path.join(work,'copy-one');const dest2=path.join(work,'copy-two');
 fs.mkdirSync(path.join(source,'Фото, 2026'),{recursive:true});
 const fixtures={'notes.txt':Buffer.from('VaultDrop native release smoke test.\n'),'empty.txt':Buffer.alloc(0),'Фото, 2026/дані.bin':crypto.randomBytes(4*1024*1024+73)};
 for(const [rel,data]of Object.entries(fixtures))fs.writeFileSync(path.join(source,rel),data);
 const browser=await chromium.connectOverCDP(process.env.VAULTDROP_CDP||'http://127.0.0.1:19371');
 const page=browser.contexts()[0].pages().find(p=>p.url().includes('tauri.localhost'));
 assert(page,'Native WebView page not found');
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.evaluate(({source,dest1,dest2})=>{
  localStorage.setItem('vaultdrop.lang',JSON.stringify('uk'));
  localStorage.setItem('vaultdrop.source',JSON.stringify(source));
  localStorage.setItem('vaultdrop.dests',JSON.stringify([{custom:dest1},{custom:dest2}]));
 },{source,dest1,dest2});
 await page.reload();
 await page.waitForFunction(()=>document.querySelector('#start')?.disabled===false);
 await page.evaluate(()=>{
  const real=window.__TAURI__.core.invoke;
  window.__TAURI__={...window.__TAURI__,core:{...window.__TAURI__.core,invoke:(command,args)=>command==='ask'?Promise.resolve(true):real(command,args)}};
 });
 await page.click('#start');
 await page.waitForSelector('#result-card.ok',{timeout:60000});
 for(const dest of[dest1,dest2])for(const[rel,data]of Object.entries(fixtures))assert.deepEqual(fs.readFileSync(path.join(dest,rel)),data);
 for(const dest of[dest1,dest2]){assert.equal(JSON.parse(fs.readFileSync(path.join(dest,'vaultdrop-report.json'))).verdict,'SAFE TO FORMAT');assert(!fs.existsSync(path.join(dest,'.vaultdrop.running')));}
 await page.screenshot({path:path.join(root,'docs/screenshots/native-result-uk.png'),fullPage:true});
 await page.click('#done');await page.click('#tab-verify');
 await page.locator('.backup').filter({hasText:dest1}).locator('button').click();
 await page.waitForSelector('#result-card.ok',{timeout:60000});
 await page.click('#done');
 const corrupt=path.join(dest1,'notes.txt');const changed=fs.readFileSync(corrupt);changed[0]^=1;fs.writeFileSync(corrupt,changed);
 await page.locator('.backup').filter({hasText:dest1}).locator('button').click();
 await page.waitForSelector('#result-card.bad',{timeout:60000});
 assert((await page.locator('#problems').textContent()).includes('notes.txt'));
 await page.screenshot({path:path.join(root,'docs/screenshots/native-damaged-uk.png'),fullPage:true});
 for(const [rel,data]of Object.entries(fixtures))assert.deepEqual(fs.readFileSync(path.join(source,rel)),data);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',work,files:Object.keys(fixtures).length,destinations:2,checks:['packaged UI','real volume scan','native folder stats','real copy and uncached read-back','binary equality','zero-byte file','Unicode and comma paths','native verify intact','native verify changed byte','originals unchanged','no JavaScript errors']},null,2));
 await page.evaluate(()=>localStorage.clear());
 await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});

