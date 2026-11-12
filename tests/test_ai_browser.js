// Optional real-browser smoke test: node tests/test_ai_browser.js /absolute/path/index.html
// Uses installed Google Chrome with its sandbox enabled and Node's built-in WebSocket.
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
async function run() {
  if (!process.argv[2]) { console.log('Real AI browser smoke skipped: pass generated index.html path.'); return; }
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-stage-chrome-'));
  const chrome = spawn('/usr/bin/google-chrome', ['--headless=new', '--disable-gpu', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
  let socket;
  try {
    const endpoint = await new Promise((resolve, reject) => {
      let log=''; const timeout=setTimeout(()=>reject(Error('Chrome startup timeout: '+log)),15000);
      chrome.stderr.on('data',chunk=> {log+=chunk; const match=log.match(/DevTools listening on (ws:\/\/[^\s]+)/); if(match){clearTimeout(timeout);resolve(match[1]);}});
      chrome.on('exit',code=>reject(Error('Chrome exited '+code+' '+log)));
    });
    const address = new URL(endpoint);
    const pages = await (await fetch(`http://${address.host}/json/list`)).json();
    socket = new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
    await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
    let seq=0; const pending=new Map(), errors=[];
    socket.onmessage=event=>{const msg=JSON.parse(event.data); if(msg.id){const p=pending.get(msg.id);pending.delete(msg.id); msg.error?p.reject(Error(JSON.stringify(msg.error))):p.resolve(msg.result);} else if(msg.method==='Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.text+': '+msg.params.exceptionDetails.exception?.description);};
    const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
    const evaluate=async expression=>{const value=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true}); if(value.exceptionDetails)throw Error(value.exceptionDetails.exception?.description||value.exceptionDetails.text);return value.result.value;};
    await call('Runtime.enable');
    const loaded = new Promise(resolve=>{const previous=socket.onmessage;socket.onmessage=event=>{previous(event);if(JSON.parse(event.data).method==='Page.loadEventFired')resolve();};});
    await call('Page.enable');
    await call('Page.navigate',{url:'file://'+path.resolve(process.argv[2])});
    await loaded;
    const initial=await evaluate(`({factions:[...document.getElementById('faction').options].map(x=>x.value),cards:document.querySelectorAll('.node').length})`);
    assert.deepEqual(initial.factions,['gdr','nat','pol','prc','rus','sov']);
    assert(initial.cards>50);
    const change=async(id,value)=>evaluate(`document.getElementById(${JSON.stringify(id)}).value=${JSON.stringify(value)};document.getElementById(${JSON.stringify(id)}).dispatchEvent(new Event('change')); true`);
    await change('faction','sov');
    await change('graph-source','ai');
    const ai=await evaluate(`({cards:document.querySelectorAll('.node').length,edges:document.querySelectorAll('.edge').length,variants:[...document.getElementById('ai-variant').options].map(x=>x.value),images:document.querySelectorAll('.node img').length,text:document.querySelector('.node').textContent})`);
    assert.deepEqual(ai.variants,['all','1','2','3','4','5']);
    assert.equal(ai.cards,815); assert.equal(ai.edges,0); assert(ai.images>800); assert(ai.text.includes('stage'));
    assert(await evaluate(`document.querySelector('.node img').decode().then(()=>document.querySelector('.node img').naturalWidth > 0)`));
    await evaluate(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
    const transform = await evaluate(`document.getElementById('world').style.transform`);
    await evaluate(`document.getElementById('search').value='tank';document.getElementById('search').dispatchEvent(new Event('input'));true`);
    assert.equal(await evaluate(`document.getElementById('world').style.transform`),transform);
    await evaluate(`document.getElementById('search').value='';document.getElementById('search').dispatchEvent(new Event('input'));true`);
    await evaluate(`document.querySelector('.node').click(); true`);
    assert(await evaluate(`document.getElementById('detail-content').textContent.includes('AI stage eligibility only')`));
    await change('ai-variant','5');
    assert(await evaluate(`document.querySelectorAll('.node').length < 815`));
    await change('ai-display','eligible'); await change('ai-stage','99');
    assert(await evaluate(`document.querySelectorAll('.node').length < 815`));
    await change('ai-display','unlocks');
    for(const faction of initial.factions) {
      await change('faction',faction);
      assert(await evaluate(`document.querySelectorAll('.node').length > 50`));
      assert.equal(await evaluate(`document.querySelectorAll('.edge').length`),0);
    }
    await change('faction','sov');
    await change('graph-source','research');
    assert.equal(await evaluate(`document.querySelectorAll('.node').length`),703);
    assert(await evaluate(`document.querySelectorAll('.edge').length > 0`));
    assert.deepEqual(errors,[]);
    console.log('Sandbox-enabled Chrome: startup, six factions, SOV AI815/icons/variant5/details, retirement and player-mode restoration passed.');
  } finally {if(socket)socket.close();chrome.kill(); await new Promise(resolve=>chrome.once('exit',resolve));fs.rmSync(profile,{recursive:true,force:true});}
}
run().catch(error=>{console.error(error);process.exitCode=1;});
