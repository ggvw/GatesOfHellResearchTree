// Execute the actual viewer startup with minimal browser-like DOM/select behavior.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || path.join(__dirname, '..', 'create_research_tree_html.py'), 'utf8');
const script = source.slice(source.lastIndexOf('<script>') + 8, source.lastIndexOf('</script>'));
class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.style = {};
    this.listeners = {}; this._value = ''; this.checked = false; this.open = false;
    this.classList = {add() {}, remove() {}, toggle() {}, contains() { return false; }};
  }
  get options() { return this.children; }
  get selectedOptions() { return this.children.filter(x => x.value === this.value); }
  get value() { return this._value; }
  set value(value) { this._value = String(value); }
  append(...items) { this.children.push(...items); if (this.tagName === 'SELECT' && !this._value) this._value = this.children[0]?.value || ''; }
  appendChild(item) { this.append(item); return item; }
  replaceChildren(...items) { this.children = []; this._value = ''; this.append(...items); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute() {} removeAttribute() {} querySelectorAll() { return []; }
  querySelector() { return new Element(); }
  getBoundingClientRect() { return {width: 1200, height: 800, left: 0, top: 0}; }
  closest() { return null; }
}
function run(trees) {
  const elements = new Map();
  const document = {documentElement: new Element(), body: new Element(),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element(['mod', 'faction'].includes(id) ? 'select' : 'div'));
      return elements.get(id);
    }, createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    querySelectorAll() { return []; }, addEventListener() {},
  };
  document.getElementById('tree-data').textContent = JSON.stringify(trees);
  const storage = {'research-tree-theme': 'removed-theme', 'research-tree-view': 'removed-view',
    'research-tree-faction': 'removed-faction', 'research-tree-mod': 'removed-mod'};
  const context = vm.createContext({document, console,
    localStorage: {getItem: key => storage[key] ?? null, setItem: (key, value) => { storage[key] = value; }},
    matchMedia: () => ({matches: false}), requestAnimationFrame: () => {},
    window: {addEventListener() {}}, ResizeObserver: class {observe() {}},
    CSS: {escape: String}, setTimeout: () => {},
  });
  vm.runInContext(script.replace('})();', 'globalThis.inspectViewer = code => eval(code); })();'), context);
  const evaluate = code => { context.inspectionCode = code; return vm.runInContext('inspectViewer(inspectionCode)', context); };
  assert.ok(evaluate('tree && tree.nodes.length > 0'));
  assert.equal(evaluate('tree.faction'), document.getElementById('faction').value);
  return {evaluate, document};
}
const tree = (mod_id, faction) => ({mod_id, mod_name: mod_id || 'None', faction, nodes: [
  {id: 'unit', display_name: 'Unit', cost: 1, requires: [], position: {x: 1, y: 1}, node_type: 'unit', stats: {}},
]});
const preset = 'preset:Hotmod 1968 (Ultrahotmod)';
let app = run([tree(preset, 'fin'), tree(preset, 'prc')]);
assert.equal(app.evaluate('modSelect.value'), preset);
assert.equal(app.evaluate('modSelect.options.length'), 1);
app.evaluate("factionSelect.value = 'prc'; factionSelect.listeners.change()");
assert.equal(app.evaluate('tree.faction'), 'prc');
app.evaluate("modSelect.value = 'removed'; factionSelect.value = 'eng'; renderTree('eng')");
assert.equal(app.evaluate('tree.mod_id'), preset);
assert.equal(app.evaluate('tree.faction'), 'fin');
app = run([tree(preset, 'fin'), tree('', 'eng'), tree('other', 'rus')]);
assert.equal(app.evaluate('tree.faction'), 'eng');
app.evaluate("modSelect.value = 'other'; modSelect.listeners.change()");
assert.equal(app.evaluate('tree.faction'), 'rus');
app.evaluate(`modSelect.value = ${JSON.stringify(preset)}; modSelect.listeners.change()`);
assert.equal(app.evaluate('tree.faction'), 'fin');
const fourteen = 'csa eng fin fra frg gdr ger isr nat pol prc rus sov usa'.split(' ').map(id => tree(preset, id));
const hiddenIds = 'csa eng fin fra frg ger isr usa'.split(' ');
for (const item of fourteen) item.hidden_faction = hiddenIds.includes(item.faction);
app = run([...fourteen, tree('unaffected', 'csa')]);
assert.equal(app.evaluate('tree.faction'), 'gdr');
assert.equal(app.evaluate('factionSelect.options.map(option => option.value).join(" ")'), 'gdr nat pol prc rus sov');
app.evaluate("renderTree('csa')");
assert.equal(app.evaluate('tree.faction'), 'gdr');
app.evaluate("modSelect.value = 'unaffected'; modSelect.listeners.change()");
assert.equal(app.evaluate('tree.faction'), 'csa');
if (process.argv[2]) {
  const data = JSON.parse(source.match(/<script id="tree-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
  const generated = run(data);
  assert.equal(generated.evaluate('tree.mod_id'), preset);
  assert.equal(generated.evaluate('modSelect.options.length'), 1);
  const visible = data.filter(item => !item.hidden_faction);
  assert.equal(generated.evaluate('factionSelect.options.length'), visible.length);
  if (data.some(item => item.hidden_faction)) {
    assert.equal(data.length, 14);
    assert.equal(visible.map(item => item.faction).join(' '), 'gdr nat pol prc rus sov');
    assert.equal(generated.evaluate('tree.faction'), 'gdr');
  }
  for (const faction of visible.map(item => item.faction)) {
    generated.evaluate(`factionSelect.value = ${JSON.stringify(faction)}; factionSelect.listeners.change()`);
    assert.equal(generated.evaluate('tree.faction'), faction);
    assert.ok(generated.evaluate('nodesLayer.children.length > 0'));
  }
  console.log(`Generated HTML startup: ${data.length} embedded, ${visible.length} selectable; all selectable factions rendered.`);
}
console.log('Actual viewer startup, preset-only selection, stale values and dataset/faction switching passed.');
