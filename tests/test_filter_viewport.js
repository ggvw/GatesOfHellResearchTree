// Run with: node tests/test_filter_viewport.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'create_research_tree_html.py'), 'utf8');
const code = source.slice(source.indexOf('  const filterControls ='), source.indexOf("  document.getElementById('search').addEventListener"));

function control(type = 'number') {
  return {type, value: '10', checked: true, listeners: {},
    addEventListener(event, callback) { this.listeners[event] = callback; }};
}
const clear = control('button');
const multiInputs = [control('checkbox')];
const context = {
  scale: 1.75, tx: -430, ty: 195, updates: 0, summaries: 0,
  selectedBranchTypes: () => new Set(['tanks']),
  applyFilters() { context.updates++; },
  updateFilterSummaries() { context.summaries++; },
  fitTree() { context.scale = 1; context.tx = 0; context.ty = 0; },
  document: {getElementById: () => clear, querySelectorAll: () => multiInputs},
  armourControls: new Map([['front', control()]]),
  firepowerControls: new Map([['primary', control()]]),
  gunRangeControls: [{input: control()}], penetrationControls: [{input: control()}],
};
for (const name of code.matchAll(/\b(\w+Input)\b/g)) context[name[1]] = control();
for (const name of ['inventoryOptions', 'weaponRoleOptions', 'infantryWeaponOptions', 'specialistOptions', 'branchOptions']) {
  context[name] = control('checkbox');
}
vm.createContext(context);
vm.runInContext(code + '\nthis.controls = filterControls;', context);

for (const input of [...context.controls, context.inventoryOptions, context.weaponRoleOptions,
  context.infantryWeaponOptions, context.specialistOptions, context.branchOptions]) {
  const previousUpdates = context.updates;
  input.listeners.input();
  assert.equal(context.updates, previousUpdates + 1);
  assert.deepEqual([context.scale, context.tx, context.ty], [1.75, -430, 195]);
}
clear.listeners.click();
assert.deepEqual([context.scale, context.tx, context.ty], [1.75, -430, 195]);
for (const input of context.controls) if (input.type === 'number' && input !== context.armourPartInput) assert.equal(input.value, '');
assert.equal(context.hasIndirectFireInput.value, '');
assert.equal(multiInputs[0].checked, false);
assert.ok(source.includes("document.getElementById('fit').addEventListener('click', fitTree)"));
console.log('Filter edits, branch selection, and clearing filters preserve zoom and pan; Fit tree remains available.');
