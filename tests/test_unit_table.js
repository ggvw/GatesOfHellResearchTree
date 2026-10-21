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
console.log('9 unit table checks passed.');
