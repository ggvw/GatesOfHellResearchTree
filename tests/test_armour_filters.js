// Run with: node tests/test_armour_filters.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'create_research_tree_html.py'), 'utf8');
const start = source.indexOf('  function matchesArmour(');
const end = source.indexOf('  function applyFilters()', start);
const matches = vm.runInNewContext(source.slice(start, end) + '\nmatchesArmour;');
const tank = {armor_parts: [
  {part: 'body1', default_mm: 30, front_mm: 80, rear_mm: 10, bottom_mm: 0},
  {part: 'engine2', default_mm: 20, rear_mm: 40},
  {part: 'turret', default_mm: 50, front_mm: 70, top_mm: 16},
  {part: 'mantlet', default_mm: 120},
]};

assert.equal(matches(tank, 'hull', [['front', 80]]), true);
assert.equal(matches(tank, 'hull', [['front', 81]]), false);
assert.equal(matches(tank, 'hull', [['left', 30], ['right', 30]]), true);
assert.equal(matches(tank, 'hull', [['left', 31]]), false);
assert.equal(matches(tank, 'hull', [['rear', 40]]), true);
assert.equal(matches(tank, 'turret', [['front', 70], ['top', 16]]), true);
assert.equal(matches(tank, 'turret', [['top', 17]]), false);
assert.equal(matches(tank, 'main', [['front', 100]]), false);
assert.equal(matches(tank, 'any', [['front', 100]]), true);
assert.equal(matches(tank, 'hull', [['front', 80], ['rear', 40]]), false);
assert.equal(matches({armor_parts: [tank.armor_parts[0]]}, 'hull', [['bottom', 1]]), false);
assert.equal(matches({armor_parts: [tank.armor_parts[0]]}, 'hull', [['bottom', 0]]), true);
assert.equal(matches({armor_parts: [{part: 'turret', front_mm: 50}]}, 'turret', [['left', 0]]), false);
assert.equal(matches({}, 'main', [['front', 0]]), false);
assert.equal(matches({}, 'main', []), true);
assert.equal(matches(tank, 'turret', [['default', 50]]), true);
assert.equal(matches(tank, 'turret', [['default', 51]]), false);
console.log('17 armour filter checks passed.');
