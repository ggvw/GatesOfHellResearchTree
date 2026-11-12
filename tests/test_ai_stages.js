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
assert.equal(nodes[0].position.x,nodes[1].position.x);
assert(nodes[2].position.x > nodes[0].position.x);
assert(nodes[3].position.x > nodes[2].position.x);
assert.equal(context.aiStageNodes(data,'2').length,2);
assert.deepEqual(Array.from(context.aiStageNodes(data,'all','eligible',4),n=>n.id),['b(sov)','c(sov)','unknown(sov)']);
assert.equal(data.ai_nodes[0].requires[0],'player-prerequisite');
console.log('AI layout, exact IDs, variants, unknown bounds, retirement and no false prerequisite edges passed.');
