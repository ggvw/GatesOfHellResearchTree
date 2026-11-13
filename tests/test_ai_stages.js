const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('create_research_tree_html.py', 'utf8');
const code = source.slice(source.indexOf('  function aiStageNodes('), source.indexOf('  function prepareAiTree('));
const context = {};
vm.createContext(context);
vm.runInContext(code, context);
const record = (purchase_id, variant, category, min, max) => ({purchase_id, roster_id:purchase_id, variant, category, min_stage:{value:min}, max_stage:{value:max}});
const data = {ai_nodes: [{id:'a(sov)', display_name:'A', requires:['player-prerequisite'], web_image:'a.png'}], ai:{records:[
  record('a(sov)',1,'Infantry',1,3), record('a(sov)',2,'Infantry',1,3),
  record('b(sov)',1,'Infantry',1,8), record('c(sov)',2,'Tank',4,99),
  record('unknown(sov)',1,'Tank',null,null),
]}};
const nodes = context.aiStageNodes(data);
assert.equal(nodes.length,4);
assert(nodes.every(node=>node.requires.length === 0));
assert.equal(nodes[0].web_image,'a.png');
assert.equal(nodes[0].ai_records.length,2);
assert.equal(new Set(nodes.map(node=>`${node.position.x}:${node.position.y}`)).size,4);
assert.equal(nodes[0].position.y,nodes[1].position.y);
assert(nodes[1].position.x > nodes[0].position.x);
assert(nodes[2].position.x > nodes[0].position.x);
assert(nodes[3].position.x > nodes[2].position.x);
assert.equal(context.aiStageNodes(data,'2').length,2);
assert.deepEqual(Array.from(context.aiStageNodes(data,'all','eligible',4),n=>n.id),['b(sov)','c(sov)','unknown(sov)']);
assert.equal(data.ai_nodes[0].requires[0],'player-prerequisite');
const crowded = context.aiStageNodes({ai:{records:Array.from({length:1000},(_,i)=>record('unit'+i,1,'Tank',1,99))}});
const layout = context.layoutAiCells(crowded);
assert.equal(layout.columns[0].tiles,6);
assert(layout.width < 1100);
assert(layout.height < 600, 'cell viewport height must not grow with 1000 units');
assert.equal(new Set(crowded.map(n=>`${n.ai_tile.x}:${n.ai_tile.y}`)).size,1000);
for (let i=0;i<crowded.length;i++) for(let j=i+1;j<crowded.length;j++) {
  const a=crowded[i].ai_tile,b=crowded[j].ai_tile;
  assert(Math.abs(a.x-b.x)>=150 || Math.abs(a.y-b.y)>=184, 'tiles must not overlap');
}
assert(source.includes("'Unknown stage' : `Stage ${column.stage}`"));
assert(source.includes('.ai-stage-band.alternate'));
assert(source.includes('html[data-theme="light"] .ai-stage-band'));
const zoomContext={tree:{ai_mode:true},viewMode:'graph',viewport:{clientWidth:1140,clientHeight:738},worldWidth:25212,worldHeight:2788,scale:1,tx:0,ty:0,setTransform(){}};
vm.createContext(zoomContext);
vm.runInContext(source.slice(source.indexOf('  function fitTree('),source.indexOf('  function keepSelectedNodeVisible(')),zoomContext);
zoomContext.fitTree();
const fitted=zoomContext.scale;
assert(fitted<.05);
assert(zoomContext.worldWidth*fitted<=1116);
zoomContext.zoomAt(.8);assert.equal(zoomContext.scale,fitted*.8);
zoomContext.zoomAt(1.25);assert(Math.abs(zoomContext.scale-fitted)<1e-12);
zoomContext.zoomAt(.89);assert(Math.abs(zoomContext.scale-fitted*.89)<1e-12);
zoomContext.tree.ai_mode=false;zoomContext.fitTree();assert.equal(zoomContext.scale,.06);
zoomContext.zoomAt(.1);assert.equal(zoomContext.scale,.05);
console.log('AI layout: exact IDs, variants, unknown bounds, retirement, 1000-unit bounded nonoverlapping grid, bands and AI/research zoom limits passed.');
