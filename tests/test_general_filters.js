// Run with: node tests/test_general_filters.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'create_research_tree_html.py'), 'utf8');
const code = source.slice(source.indexOf('  function applyFilters()'), source.indexOf('  function prerequisiteSet('));
const nodes = [
  {id: 'zero', unit: {cp: 0}, indirect_fire: false},
  {id: 'direct', unit: {cp: 2}, indirect_fire: false},
  {id: 'indirect', unit: {cp: 7}, indirect_fire: true},
  {id: 'unknown', unit: {cp: null}},
];
const highlighted = new Set();
const elements = new Map();
const document = {getElementById(id) {
  if (!elements.has(id)) elements.set(id, {value: '', textContent: ''});
  return elements.get(id);
}};
const context = {
  document, tree: {nodes}, byId: new Map(nodes.map(node => [node.id, node])),
  nodeElements: new Map(nodes.map(node => [node.id, {classList: {
    toggle(name, match) {
      if (name !== 'filter-match') return;
      if (match) highlighted.add(node.id);
      else highlighted.delete(node.id);
    },
  }}])),
  unitRows: new Map(nodes.map(node => [node.id, {hidden: false}])),
  firepowerControls: new Map(), armourControls: new Map(), gunRangeControls: [],
  selectedValues: () => new Set(), selectedBranchTypes: () => new Set(),
  largestGun: () => null, matchesArmour: () => true, updateGraphLayout() {},
  filterCount: {}, inventoryOptions: {}, weaponRoleOptions: {},
  infantryWeaponOptions: {}, specialistOptions: {},
};
for (const name of code.matchAll(/\b(\w+Input)\.value/g)) context[name[1]] = {value: ''};
vm.createContext(context);
vm.runInContext(code, context);

for (const mode of ['graph', 'table']) {
  context.viewMode = mode;
  for (const [min, max, indirect, expected] of [
    ['', '', '', ['zero', 'direct', 'indirect', 'unknown']],
    ['0', '', '', ['zero', 'direct', 'indirect']],
    ['2', '', '', ['direct', 'indirect']],
    ['2', '2', '', ['direct']],
    ['7', '2', '', []],
    ['', '2', '', ['zero', 'direct']],
    ['', '', 'yes', ['indirect']],
    ['', '', 'no', ['zero', 'direct']],
    ['2', '7', 'yes', ['indirect']],
    ['2', '7', 'no', ['direct']],
  ]) {
    context.minCpInput.value = min;
    context.maxCpInput.value = max;
    context.hasIndirectFireInput.value = indirect;
    context.applyFilters();
    assert.deepEqual([...context.unitRows].filter(([, row]) => !row.hidden).map(([id]) => id), expected);
    const active = min !== '' || max !== '' || indirect !== '';
    assert.deepEqual([...highlighted], active ? expected : []);
  }
}

assert.match(source, /id="min-caliber"[^>]*step="1"/);
assert.match(source, /const filterControls = \[[^\n]*minCpInput/);
assert.match(source, /for \(const input of filterControls\) if \(input.type === 'number'\) input.value = ''/);
assert.ok(source.includes("hasIndirectFireInput.value = '';"));

// Both infantry limits must be met by one real soldier, never by a vehicle crew.
nodes.splice(0, nodes.length,
  {id: 'mixed', unit_class: 'infantry', members: [
    {count: 1, health: 300, vision_range_m: 100, equipped_vision_range_m: 100},
    {count: 1, health: 150, vision_range_m: 125, equipped_vision_range_m: 230},
  ]},
  {id: 'elite', unit_class: 'infantry', members: [{count: 2, health: 300, vision_range_m: 125, equipped_vision_range_m: 145}]},
  {id: 'unknown', unit_class: 'infantry', members: [{count: 1, health: null, vision_range_m: null}]},
  {id: 'empty', unit_class: 'infantry', members: [{count: 0, health: 999, vision_range_m: 999, equipped_vision_range_m: 999}]},
  {id: 'tank', unit_class: 'other', members: [{count: 2, health: 300, vision_range_m: 125, equipped_vision_range_m: 230}]},
);
context.byId = new Map(nodes.map(node => [node.id, node]));
context.nodeElements = new Map(nodes.map(node => [node.id, {classList: {toggle() {}}}]));
context.unitRows = new Map(nodes.map(node => [node.id, {hidden: false}]));
context.minCpInput.value = '';
context.maxCpInput.value = '';
context.hasIndirectFireInput.value = '';
for (const mode of ['graph', 'table']) {
  context.viewMode = mode;
  for (const [health, vision, expected] of [
    ['300', '', ['mixed', 'elite']],
    ['', '125', ['mixed', 'elite']],
    ['300', '125', ['elite']],
    ['301', '125', []],
    ['0', '0', ['mixed', 'elite']],
    ['', '', ['mixed', 'elite', 'unknown', 'empty', 'tank']],
  ]) {
    context.minInfantryHealthInput.value = health;
    context.minInfantryVisionInput.value = vision;
    context.applyFilters();
    assert.deepEqual([...context.unitRows].filter(([, row]) => !row.hidden).map(([id]) => id), expected);
  }
  for (const [health, baseVision, equippedVision, expected] of [
    ['', '', '145', ['mixed', 'elite']],
    ['', '', '230', ['mixed']],
    ['300', '', '230', []],
    ['300', '125', '145', ['elite']],
    ['', '', '231', []],
    ['', '', '0', ['mixed', 'elite']],
    ['', '', '', ['mixed', 'elite', 'unknown', 'empty', 'tank']],
  ]) {
    context.minInfantryHealthInput.value = health;
    context.minInfantryVisionInput.value = baseVision;
    context.minInfantryEquippedVisionInput.value = equippedVision;
    context.applyFilters();
    assert.deepEqual([...context.unitRows].filter(([, row]) => !row.hidden).map(([id]) => id), expected);
  }
}
assert.match(source, /const filterControls = \[[^\n]*minInfantryHealthInput[^\n]*minInfantryVisionInput/);
assert.ok(source.includes("health: member.health ?? 'Unknown'"));
assert.ok(source.includes("base_vision_range_m: member.vision_range_m ?? 'Unknown'"));
assert.ok(source.includes("equipped_vision_reach_estimate_m: member.equipped_vision_range_m ?? 'Unknown'"));
assert.match(source, /const filterControls = \[[^\n]*minInfantryEquippedVisionInput/);
console.log('General filter checks passed in graph and table modes.');
