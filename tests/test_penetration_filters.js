// Run with: node tests/test_penetration_filters.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'create_research_tree_html.py'), 'utf8');
const code = source.slice(source.indexOf('  function matchesPenetration('), source.indexOf('  function applyFilters('));
const context = {largestGun: node => node.gun};
const matches = vm.runInNewContext(code + '\nmatchesPenetration;', context);
const filter = (distance, value) => ({field: `penetration_${distance}m_mm`, input: {value: String(value)}});
const shell = (near, far, carried = true, maximum = 55) => ({penetration_10m_mm: near, penetration_100m_mm: far,
  penetration_max_range_mm: maximum, maximum_range_m: 200, carried});
const node = {gun: {armor_penetration: [shell(120, 60, true, 20), shell(100, 90, true, 70), shell(999, 999, false, 999)]}};
assert.equal(matches(node, []), true);
assert.equal(matches(node, [filter(10, 120)]), true);
assert.equal(matches(node, [filter(10, 121)]), false); // Uncarried APCR cannot qualify.
assert.equal(matches(node, [filter(100, 90)]), true);
assert.equal(matches(node, [filter(10, 120), filter(100, 90)]), false); // Cannot mix shells.
assert.equal(matches(node, [filter(10, 100), filter(100, 90)]), true);
assert.equal(matches({}, [filter(10, 0)]), false);
assert.equal(matches({gun: {armor_penetration: [shell(null, null)]}}, [filter(10, 0)]), false);
assert.equal(matches({gun: {armor_penetration: [shell(0, 0)]}}, [filter(10, 0)]), true);
assert.equal(matches({gun: {armor_penetration: [shell(100, 80, null)]}}, [filter(100, 80)]), true);
const maxFilter = value => ({field: 'penetration_max_range_mm', input: {value: String(value)}});
assert.equal(matches(node, [maxFilter(70)]), true);
assert.equal(matches(node, [maxFilter(71)]), false);
assert.equal(matches(node, [filter(10, 120), maxFilter(70)]), false);
assert.equal(matches(node, [filter(10, 100), filter(100, 90), maxFilter(70)]), true);
assert.equal(matches({gun: {armor_penetration: [shell(1, 1, true, null)]}}, [maxFilter(0)]), false);
assert.equal(matches({gun: {armor_penetration: [shell(1, 1, true, 0)]}}, [maxFilter(0)]), true);

const statCode = source.slice(source.indexOf('  function penetrationStat('), source.indexOf('  function weaponStats('));
const stats = vm.runInNewContext(statCode + '\npenetrationStat;', {number: String});
assert.equal(stats({}, 'penetration_10m_mm'), 'Unknown');
const rows = stats({armor_penetration: [{...shell(100, 80, false), ammunition: 'apcr'}]}, 'penetration_10m_mm');
assert.equal(rows, 'No carried ammunition with penetration data');
const mixed = {armor_penetration: [
  {...shell(100, 80), ammunition: 'ap'},
  {...shell(999, 999, false), ammunition: 'apcr'},
]};
for (const field of ['penetration_10m_mm', 'penetration_100m_mm', 'penetration_max_range_mm']) {
  const values = Array.from(stats(mixed, field));
  assert.equal(values.length, 1);
  assert.ok(values[0].startsWith('AP: '));
  assert.ok(!values[0].includes('APCR'));
}
assert.deepEqual(Array.from(stats({armor_penetration: [{...shell(100, 80, null), ammunition: 'ap'}]}, 'penetration_10m_mm')),
  ['AP: 100 mm']); // Preserve configured values when availability is unknown.
assert.deepEqual(Array.from(stats({armor_penetration: [{...shell(100, 80), ammunition: 'ap'}]}, 'penetration_max_range_mm')),
  ['AP: 55 mm at 200 m']);
assert.match(source, /const filterControls = \[[^\n]*penetrationControls.map/);
console.log('Penetration filter and stat checks passed.');
