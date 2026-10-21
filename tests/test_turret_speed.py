"""Resolve configured turret traverse without confusing gun elevation or hull speed."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from create_research_tree_html import annotate_unit_metadata, sdl_number, turret_turn_speeds
from game_data import GameData, Mod
from test_game_data import pak


class TurretSpeedTests(unittest.TestCase):
    def test_numeric_expressions_and_invalid_values(self):
        self.assertAlmostEqual(sdl_number('(+ 6 (/ 16 2.5))'), 12.4)
        self.assertEqual(sdl_number('(* 2 (- 10 3))'), 14)
        self.assertEqual(sdl_number('0'), 0)
        for value in ('(/ 1 0)', 'nan', 'inf', '%unknown', '(+ 1', '1 2', '(unknown 2)'):
            with self.subTest(value=value):
                self.assertIsNone(sdl_number(value))

    def test_presets_auxiliary_turrets_and_explicit_overrides(self):
        speeds = turret_turn_speeds('''
            (define "turret_medium" {speed2 (+ 6 (/ %power_traverse 2.5))})
            {bone "aux_turret1" {speed2 5}}
            {bone "turret" ("turret_medium" power_traverse(16))}
            {bone "gun_rot" {speed2 100}}
            {bone "commander_rot" {speed2 180}}
        ''')
        self.assertEqual(speeds, [{'turret': 'turret', 'degrees_per_second': 12.4},
                                  {'turret': 'aux_turret1', 'degrees_per_second': 5}])
        self.assertEqual(turret_turn_speeds('''
            (define "turret_light" {speed2 (+ 10 (/ %power_traverse 2.5))})
            {bone "turret" ("turret_light" power_traverse(20)) {speed2 15}}
        '''), [{'turret': 'turret', 'degrees_per_second': 15}])

    def test_missing_zero_and_uninvoked_or_recursive_presets(self):
        self.assertEqual(turret_turn_speeds('''
            (define "unused" {bone "turret" {speed2 999}})
            ; {bone "turret" {speed2 888}}
            {bone "gun_rot" {speed2 20}}
        '''), [])
        for setting, expected in (('{speed2 0}', 0), ('', None), ('{speed2 %x}', None),
                                  ('{speed2 -5}', None), ('("cycle")', None)):
            with self.subTest(setting=setting):
                self.assertEqual(turret_turn_speeds(
                    '(define "cycle" ("cycle")) {bone "turret" ' + setting + '}'),
                    [{'turret': 'turret', 'degrees_per_second': expected}])

    def test_mod_preset_override_updates_node_stat(self):
        with TemporaryDirectory() as temporary:
            resource = Path(temporary) / 'resource'
            pak(resource / 'properties.pak', {'properties/turret.ext':
                '(define "turret_medium" {speed2 (+ 6 (/ %power_traverse 2.5))})'})
            pak(resource / 'entity/vehicle.pak', {'-vehicle/tank_medium/tank.def': '''
                (include "/properties/turret.ext")
                {bone "turret" ("turret_medium" power_traverse(16))}
            '''})
            pak(resource / 'gamelogic.pak', {})
            mod = Mod('1', 'Turret override', Path(temporary) / 'mod')
            pak(mod.path / 'resource/custom.pak', {'properties/turret.ext':
                '(define "turret_medium" {speed2 (* 2 %power_traverse)})'})
            for mods, expected in (([], 12.4), ([mod], 32)):
                nodes = [{'id': 'tank'}]
                with GameData(resource, mods) as data:
                    annotate_unit_metadata([{'faction': 'ger', 'nodes': nodes}],
                                           data.view('entity/'), data.view(), {})
                self.assertEqual(nodes[0]['turret_turn_speed_deg_s'], expected)


if __name__ == '__main__':
    unittest.main()
