// Run with: node tests/test_unit_table.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'create_research_tree_html.py'), 'utf8');
const gunCode = source.slice(source.indexOf('  function largestGun('), source.indexOf('  function renderUnitTable('));
const prerequisiteCode = source.slice(source.indexOf('  function prerequisiteSet('), source.indexOf('  function selectNode('));
const nodes = [
  {id: 'base', cost: 2, requires: []},
  {id: 'left', cost: 3, requires: ['base']},
  {id: 'right', cost: 5, requires: ['base']},
  {id: 'unit', cost: 7, requires: ['left', 'right', 'missing']},
];
const context = {byId: new Map(nodes.map(node => [node.id, node]))};
vm.createContext(context);
const {largestGun, totalResearchPoints} = vm.runInContext(gunCode + prerequisiteCode + '\n({largestGun, totalResearchPoints})', context);
const cannon = {id: 'cannon', caliber_mm: 76, reload_time_seconds: 8, rate_of_fire_rpm: 7.5};
const machineGun = {id: 'mg', caliber_mm: 7.62, reload_time_seconds: 3, rate_of_fire_rpm: 600};
const launcher = {id: 'launcher', caliber_mm: 100};
const crew = [{count: 1, weapons: [launcher]}];
assert.equal(largestGun({unit: {vehicle: 'tank'}, vehicle_weapons: [machineGun, cannon], members: crew}), cannon);
assert.equal(largestGun({unit: {definition_type: 'squad_vehicle'}, members: crew}), null);
assert.equal(largestGun({members: [{count: 2, weapons: [machineGun, launcher]}]}), launcher);
assert.equal(largestGun({members: [{count: 0, weapons: [launcher]}]}), null);
assert.equal(largestGun({vehicle_weapons: [{id: 'unknown'}, cannon]}), cannon);
assert.equal(largestGun({}), null);
assert.equal(totalResearchPoints(nodes[3]), 17); // Shared prerequisites counted once.
assert.equal(totalResearchPoints(nodes[0]), 2);
context.byId.set('cycle', {id: 'cycle', cost: 4, requires: ['cycle', 'base']});
assert.equal(totalResearchPoints(context.byId.get('cycle')), 6);
const sortCode = source.slice(source.indexOf('  function nextTableSort('), source.indexOf('  const tableHeaders'));
const {nextTableSort, compareTableValues} = vm.runInContext(sortCode + '\n({nextTableSort, compareTableValues})', context);
const plain = value => JSON.parse(JSON.stringify(value));
const first = nextTableSort([], 1);
assert.deepEqual(plain(first), [{column: 1, direction: 'asc'}]);
const multiple = nextTableSort(first, 2);
assert.deepEqual(plain(multiple), [{column: 1, direction: 'asc'}, {column: 2, direction: 'asc'}]);
const secondaryDescending = nextTableSort(multiple, 2);
assert.deepEqual(plain(secondaryDescending), [{column: 1, direction: 'asc'}, {column: 2, direction: 'desc'}]);
assert.deepEqual(plain(nextTableSort(secondaryDescending, 2)), [{column: 1, direction: 'asc'}]);
const primaryDescending = nextTableSort(multiple, 1);
assert.deepEqual(plain(primaryDescending), [{column: 1, direction: 'desc'}, {column: 2, direction: 'asc'}]);
assert.deepEqual(plain(nextTableSort(primaryDescending, 1)), [{column: 2, direction: 'asc'}]);
assert.deepEqual(plain(nextTableSort(nextTableSort(first, 1), 1)), []);
assert.deepEqual(plain(nextTableSort(nextTableSort(secondaryDescending, 2), 2)), plain(multiple));
assert.deepEqual(plain(first), [{column: 1, direction: 'asc'}]); // No mutation.
assert.ok(compareTableValues(['A', 2], ['B', 10], first) < 0);
assert.ok(compareTableValues(['A', 0], ['B', 1], first) < 0);
assert.ok(compareTableValues(['A', null], ['B', 1], first) > 0);
assert.ok(compareTableValues(['A', null], ['B', 1], [{column: 1, direction: 'desc'}]) > 0);
assert.ok(compareTableValues(['A', 2, 10], ['B', 2, 3], multiple) > 0);
assert.ok(compareTableValues(['Tank 2'], ['Tank 10'], [{column: 0, direction: 'asc'}]) < 0);
assert.ok(compareTableValues([false], [true], [{column: 0, direction: 'asc'}]) < 0);
assert.equal(compareTableValues(['A', 2], ['B', 2], first), 0); // Preserve source order for ties.
console.log('Unit table and sorting checks passed.');
