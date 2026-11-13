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
    await call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
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
    await evaluate(`document.getElementById('clear').click();true`);
    const localScroll=await evaluate(`(()=>{const c=[...document.querySelectorAll('.ai-tile-cell')].find(c=>c.scrollHeight>c.clientHeight);c.scrollTop=200;return {key:c.dataset.cellKey,top:c.scrollTop};})()`);
    await evaluate(`document.getElementById('search').value='tank';document.getElementById('search').dispatchEvent(new Event('input'));true`);
    assert.equal(await evaluate(`[...document.querySelectorAll('.ai-tile-cell')].find(c=>c.dataset.cellKey===${JSON.stringify(localScroll.key)}).scrollTop`),localScroll.top);
    await evaluate(`document.getElementById('search').value='';document.getElementById('search').dispatchEvent(new Event('input'));true`);
    assert(await evaluate(`(()=>{const c=[...document.querySelectorAll('.ai-tile-cell')].find(c=>c.scrollHeight>c.clientHeight);c.scrollTop=c.scrollHeight;c.lastElementChild.click();const n=c.lastElementChild.getBoundingClientRect(),r=c.getBoundingClientRect();return n.top>=r.top-1&&n.bottom<=r.bottom+1;})()`));
    await evaluate(`document.getElementById('clear').click();true`);
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
    await change('ai-variant','all');
    const screenshotDir=process.argv[3];
    if(screenshotDir)fs.mkdirSync(screenshotDir,{recursive:true});
    for (const width of [1440,1720]) {
      await call('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
      for (const faction of ['nat','sov','gdr']) for (const theme of ['dark','light']) {
        await change('faction',faction);
        await evaluate(`document.documentElement.dataset.theme=${JSON.stringify(theme)};new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
        assert(await evaluate(`(()=>{const c=[...document.querySelectorAll('.ai-tile-cell')].find(c=>c.scrollHeight>c.clientHeight);if(!c)return true;c.scrollTop=c.scrollHeight;const n=c.lastElementChild.getBoundingClientRect(),r=c.getBoundingClientRect();const ok=n.bottom<=r.bottom+1&&n.top>=r.top;c.scrollTop=0;return ok;})()`),'last tile reachable');
        const geometry=await evaluate(`(()=>{
          const viewport=document.getElementById('viewport').getBoundingClientRect();
          const band=document.querySelector('.ai-stage-band');
          const rows=[...band.querySelectorAll('.ai-tile-cell')].map(cell=>cell.getBoundingClientRect());
          const visible=rows.filter(r=>r.top>=viewport.top && r.bottom<=viewport.bottom).length;
          const cards=[...band.querySelectorAll('.node')];
          const cell=band.querySelector('.ai-tile-cell');
          const backgrounds=[...document.querySelectorAll('.ai-stage-band')].slice(0,2).map(el=>getComputedStyle(el).backgroundColor);
          return {visible,cardWidth:cards[0].getBoundingClientRect().width,worldHeight:document.getElementById('world').offsetHeight,
            labels:[...document.querySelectorAll('.ai-stage-band h2')].map(el=>el.textContent),backgrounds,cards:document.querySelectorAll('.node').length};
        })()`);
        assert(geometry.visible>=3,`${faction}/${width}: ${JSON.stringify(geometry)}`);
        assert(geometry.cardWidth>=69.9,JSON.stringify(geometry));
        assert.equal(geometry.cards,{nat:1214,sov:815,gdr:82}[faction]);
        assert(geometry.labels.includes('Stage 1'));
        assert.notEqual(geometry.backgrounds[0],geometry.backgrounds[1]);
        console.log('AI geometry',width,faction,theme,JSON.stringify(geometry));
        if(screenshotDir) {
          await evaluate(`Promise.all([...document.querySelectorAll('.node img')].slice(0,30).map(img=>img.decode().catch(()=>{})))`);
          const image=await call('Page.captureScreenshot',{format:'png'});
          fs.writeFileSync(path.join(screenshotDir,`${faction}-${theme}-${width}.png`),Buffer.from(image.data,'base64'));
        }
        if (theme==='dark' && faction!=='gdr') {
          for (const detailsOpen of [false,true]) {
            if(detailsOpen)await evaluate(`document.querySelector('.node').click();true`);
            const bounds=await evaluate(`(()=>{
              document.getElementById('fit').click();
              const v=document.getElementById('viewport').getBoundingClientRect();
              const bands=[...document.querySelectorAll('.ai-stage-band')];
              const rect=el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width};};
              return {viewport:rect(document.getElementById('viewport')),world:rect(document.getElementById('world')),
                first:rect(bands[0]),last:rect(bands.at(-1)),scale:new DOMMatrix(getComputedStyle(document.getElementById('world')).transform).a};
            })()`);
            for(const name of ['world','first','last']) {
              const r=bounds[name],v=bounds.viewport;
              assert(r.left>=v.left-.5 && r.right<=v.right+.5 && r.top>=v.top-.5 && r.bottom<=v.bottom+.5,
                `${faction}/${width}/details=${detailsOpen}/${name}: ${JSON.stringify(bounds)}`);
            }
            assert(bounds.scale<.06,'real wide AI overview must fit below former floor');
            const scales=await evaluate(`(()=>{
              const s=()=>new DOMMatrix(getComputedStyle(document.getElementById('world')).transform).a;
              document.getElementById('zoom-out').click();const out=s();
              document.getElementById('zoom-in').click();const back=s();
              const v=document.getElementById('viewport'),r=v.getBoundingClientRect();
              v.dispatchEvent(new WheelEvent('wheel',{deltaY:100,clientX:r.left+r.width/2,clientY:r.top+r.height/2,bubbles:true,cancelable:true}));
              return {out,back,wheel:s()};
            })()`);
            assert(Math.abs(scales.out/bounds.scale-.8)<.0001,JSON.stringify(scales));
            assert(Math.abs(scales.back/bounds.scale-1)<.0001,JSON.stringify(scales));
            assert(Math.abs(scales.wheel/bounds.scale-.89)<.0001,JSON.stringify(scales));
            console.log('AI Fit bounds and smooth zoom',width,faction,detailsOpen,JSON.stringify(bounds));
            await evaluate(`document.getElementById('clear').click();true`);
          }
        }
      }
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
