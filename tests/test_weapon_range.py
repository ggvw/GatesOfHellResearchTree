"""Configured firing ranges retain ammunition scopes and layered inheritance."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from create_research_tree_html import annotate_unit_metadata, weapon_range_settings
from game_data import GameData, Mod
from test_game_data import pak


class WeaponRangeTests(unittest.TestCase):
    def test_ai_and_direct_control_ranges_are_not_minimum_and_maximum(self):
        self.assertEqual(weapon_range_settings('{range 170 200} {minRange 30}', {}), {
            'default': {'ai_range_m': 170, 'direct_control_range_m': 200,
                        'minimum_firing_range_m': 30}, 'ammo': {}})

    def test_ammunition_overrides_do_not_replace_default_range(self):
        settings = weapon_range_settings('''{from "pattern gun"
            {range 200 200} {parameters "he" {range 180 180}}
            {parameters "heat" {range 170 170}}
        }''', {})
        self.assertEqual(settings['default']['ai_range_m'], 200)
        self.assertEqual(settings['ammo']['he']['ai_range_m'], 180)
        self.assertEqual(settings['ammo']['heat']['ai_range_m'], 170)

    def test_presets_arithmetic_and_later_settings_override_in_place(self):
        presets = {'range_custom': '(define "range_custom" {range %ai (+ %ai 20)})'}
        settings = weapon_range_settings('("range_custom" ai(180)) {aimRange 190} {minRange 0}', presets)
        self.assertEqual(settings['default'], {'ai_range_m': 190, 'direct_control_range_m': 200,
                                                'minimum_firing_range_m': 0})

    def test_unknown_inactive_or_unrelated_data_does_not_grant_a_range(self):
        settings = weapon_range_settings('''
            (define "unused" {range 999 999})
            ; {range 888 888}
            (mod "mp" {range 777 777})
            ("unknown" range(666))
            {spreading {radiusTable {range 555 555}}}
        ''', {})
        self.assertEqual(settings, {'default': {}, 'ammo': {}})
        self.assertIsNone(weapon_range_settings('{aimRange %missing}', {})['default']['ai_range_m'])

    def test_inherited_ammo_overrides_remain_overrides_without_mutating_parent(self):
        parent = weapon_range_settings('{range 100 120} {parameters "he" {aimRange 90}}', {})
        child = weapon_range_settings('{range 200 210} {parameters "he" {maxRange 180}}', {}, parent)
        self.assertEqual(child['default'], {'ai_range_m': 200, 'direct_control_range_m': 210})
        self.assertEqual(child['ammo']['he'], {'ai_range_m': 90, 'direct_control_range_m': 180})
        self.assertEqual(parent['ammo']['he'], {'ai_range_m': 90})

    def test_extraction_and_mod_override_preserve_ammo_and_weapon_inheritance(self):
        with TemporaryDirectory() as temporary:
            resource = Path(temporary) / 'resource'
            pak(resource / 'entity/vehicle.pak', {'-vehicle/tank_medium/tank.def':
                '{Weaponry {place "gun" {weapon "child"}}}'})
            pak(resource / 'gamelogic.pak', {
                'set/stuff/gun/gun.pattern': '{weapon_bullet {aimRange 15} {maxRange 25}}',
                'set/stuff/gun/.presets': '(define "range_200" {range 200 200})',
                'set/stuff/gun/parent': '{from "pattern gun" ("range_200") {parameters "he" {range 180 180}}}',
                'set/stuff/gun/child': '{from "parent" {minRange 0}}',
            })
            mod = Mod('1', 'Range override', Path(temporary) / 'mod')
            pak(mod.path / 'resource/custom.pak', {'set/stuff/gun/.presets':
                '(define "range_200" {range 240 250})'})
            for mods, ai, direct in (([], 200, 200), ([mod], 240, 250)):
                nodes = [{'id': 'tank'}]
                with GameData(resource, mods) as data:
                    annotate_unit_metadata([{'faction': 'ger', 'nodes': nodes}],
                                           data.view('entity/'), data.view(), {})
                gun = nodes[0]['vehicle_weapons'][0]
                self.assertEqual((gun['ai_range_m'], gun['direct_control_range_m']), (ai, direct))
                self.assertEqual(gun['minimum_firing_range_m'], 0)
                self.assertEqual(gun['ammunition_ranges'], [{'ammunition': 'he', 'ai_range_m': 180,
                    'direct_control_range_m': 180, 'minimum_firing_range_m': 0}])


if __name__ == '__main__':
    unittest.main()
