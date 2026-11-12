// Run with: node tests/test_stat_display.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'create_research_tree_html.py'), 'utf8');
// Include dynamically generated armour inputs as well as static weapon filters.
const millimetreInputs = [...source.matchAll(/<label[^>]*>[^<]*\(mm\)\s*<input\b[^>]*>/g)]
  .map(match => match[0]);
millimetreInputs.push(source.match(/Min \$\{name\} \(mm\) <input\b[^>]*>/)[0]);
assert.equal(millimetreInputs.length, 5);
for (const input of millimetreInputs) assert.match(input, /step="1"/);
const context = vm.createContext({
  esc: String,
  label: value => value.replaceAll('_', ' '),
  shown: value => value !== undefined && value !== null && value !== '',
  number: String,
  comparisonTable: () => '<table></table>',
  inventoryRows: () => ({}),
});
vm.runInContext(source.slice(source.indexOf('  function statSection('), source.indexOf('  function memberTables(')), context);
vm.runInContext(source.slice(source.indexOf('  function armorStats('), source.indexOf('  function renderDetails(')), context);
vm.runInContext(source.slice(source.indexOf('  function memberTables('), source.indexOf('  function armorStats(')), context);
const render = node => { context.node = node; return vm.runInContext('armorStats(node, true)', context); };
const output = render({armor_parts: [
  {part: 'body1', default_mm: 30, front_mm: 80, bottom_mm: 0, cast_steel_coefficient: 1.1},
  {part: 'turret', default_mm: 50},
  {part: 'shield', left_mm: 11},
]});
const header = output.match(/<thead>(.*?)<\/thead>/s)[1];
assert.ok(!header.includes('default'));
for (const face of ['front', 'left', 'right', 'rear', 'top', 'bottom']) assert.ok(header.includes(`${face} (mm)`));
const rows = [...output.matchAll(/<tr><th scope="row">.*?<\/th>(.*?)<\/tr>/gs)]
  .map(match => [...match[1].matchAll(/<td>(.*?)<\/td>/g)].map(cell => cell[1]));
assert.deepEqual(rows[0], ['80', '30', '30', '30', '30', '0', '1.1']);
assert.deepEqual(rows[1], ['50', '50', '50', '50', '50', '50', '—']);
assert.deepEqual(rows[2], ['—', '11', '—', '—', '—', '—', '—']);
assert.equal((render({armor_parts: [{part: 'hull', default_mm: 10}]}).match(/<td>10<\/td>/g) || []).length, 6);
assert.match(output, /<details class="metric-help" data-state-key="Armour stats help"><summary>Help<\/summary>/);
assert.match(vm.runInContext('memberTables({members: [{count: 1}]})', context),
  /<details class="metric-help" data-state-key="Infantry stats help"><summary>Help<\/summary>/);
assert.match(vm.runInContext('weaponStats({vehicle_weapons: [{id: "gun"}]}, true)', context),
  /<details class="metric-help" data-state-key="Weapon stats help"><summary>Help<\/summary>/);
for (const id of ['penetration-filter-help', 'range-filter-help', 'armour-filter-help', 'firepower-filter-help']) {
  const tag = source.match(new RegExp(`<details[^>]*id="${id}"[^>]*>`))[0];
  assert.ok(!/\bopen\b/.test(tag));
}
// Capture the actual quantities passed to the rendered comparison table.
context.comparisonTable = (columns, sections) => JSON.stringify({columns, sections});
context.node = {members: [
  {alias: 'known', count: 2, weapons: [{id: 'rifle'}]},
  {alias: 'unknown', count: null, weapons: [{id: 'rifle'}]},
  {alias: 'later', count: 1, weapons: [{id: 'rifle'}]},
]};
const roster = vm.runInContext('memberTables(node)', context);
assert.match(roster, /Infantry \(Unknown\)/);
assert.match(roster, /unknown ×Unknown/);
const carried = vm.runInContext('weaponStats(node, false)', context);
assert.match(carried, /"carried_count":null/);
context.node.members[1].count = 0;
assert.match(vm.runInContext('memberTables(node)', context), /Infantry \(3\)/);
assert.match(vm.runInContext('weaponStats(node, false)', context), /"carried_count":3/);
console.log('Armour fallback, unknown quantities and collapsed help display checks passed.');
