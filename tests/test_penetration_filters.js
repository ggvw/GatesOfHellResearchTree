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
const shell = (near, far, carried = true) => ({penetration_10m_mm: near, penetration_100m_mm: far, carried});
const node = {gun: {armor_penetration: [shell(120, 60), shell(100, 90), shell(999, 999, false)]}};
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

const statCode = source.slice(source.indexOf('  function penetrationStat('), source.indexOf('  function weaponStats('));
const stats = vm.runInNewContext(statCode + '\npenetrationStat;', {number: String});
assert.equal(stats({}, 'penetration_10m_mm'), 'Unknown');
const rows = stats({armor_penetration: [{...shell(100, 80, false), ammunition: 'apcr'}]}, 'penetration_10m_mm');
assert.deepEqual(Array.from(rows), ['APCR: 100 mm (not carried)']);
assert.match(source, /const filterControls = \[[^\n]*penetrationControls.map/);
console.log('Penetration filter and stat checks passed.');
