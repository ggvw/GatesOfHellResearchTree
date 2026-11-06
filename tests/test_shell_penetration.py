"""Nominal penetration is shell-specific and distinct from health damage."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from create_research_tree_html import (
    annotate_unit_metadata, penetration_at_distance, weapon_penetration_settings,
)
from game_data import GameData, Mod
from test_game_data import pak


PRESET = '''(define "penetration_medium" {parameters "%shell"
    {projectileDamageTable {10 (+ %a (+ 1.3 (/ (- %a %b) 4.4)))} {30 %a} {100 %b}}
})'''


class ShellPenetrationTests(unittest.TestCase):
    def test_named_formula_preserves_shell_types(self):
        settings = weapon_penetration_settings('''
            ("penetration_medium" shell(ap) a(109) b(92))
            ("penetration_medium" shell(apcbche) a(88) b(81))
        ''', {'penetration_medium': PRESET})
        self.assertIsNone(settings['default'])
        self.assertEqual(penetration_at_distance(settings['ammo']['ap'], 10), 114.16)
        self.assertEqual(penetration_at_distance(settings['ammo']['ap'], 100), 92)
        self.assertEqual(penetration_at_distance(settings['ammo']['apcbche'], 10), 90.89)

    def test_exact_interpolation_unknown_and_no_extrapolation(self):
        curve = [(0, 100), (20, 80), (100, 40)]
        self.assertEqual(penetration_at_distance(curve, 10), 90)
        self.assertEqual(penetration_at_distance(curve, 100), 40)
        self.assertIsNone(penetration_at_distance(curve, 101))
        self.assertIsNone(penetration_at_distance([(20, 80), (100, 40)], 10))
        self.assertIsNone(penetration_at_distance([(0, None), (20, 80)], 10))
        self.assertEqual(penetration_at_distance([(10, 0)], 10), 0)

    def test_positional_presets_and_nested_macros(self):
        presets = {
            'penetration': '(define "penetration" {projectileDamageTable {0 %0} {100 %1}})',
            'round': '(define "round" ("penetration" args 20 10))',
        }
        curve = weapon_penetration_settings('("round")', presets)['default']
        self.assertEqual(penetration_at_distance(curve, 10), 19)
        self.assertEqual(penetration_at_distance(curve, 100), 10)

    def test_comments_inactive_modes_and_health_damage_are_not_penetration(self):
        settings = weapon_penetration_settings('''
            ; {projectileDamageTable {10 999}}
            (define "unused" {projectileDamageTable {10 888}})
            (mod "mp" {projectileDamageTable {10 777}})
            {healthDamage 500} {minimumDamageModifier 600}
            {spreading {projectileDamageTable {10 666}}}
        ''', {})
        self.assertEqual(settings, {'default': None, 'ammo': {}})
        invalid = weapon_penetration_settings('{projectileDamageTable {10 %unknown} {100 0}}', {})
        self.assertIsNone(penetration_at_distance(invalid['default'], 10))

    def test_inherited_overrides_do_not_mutate_parent(self):
        parent = weapon_penetration_settings('''{projectileDamageTable {10 10} {100 5}}
            {parameters "ap" {projectileDamageTable {10 100} {100 50}}}''', {})
        child = weapon_penetration_settings('''{parameters "ap"
            {projectileDamageTable {10 120} {100 60}}}''', {}, parent)
        self.assertEqual(penetration_at_distance(parent['ammo']['ap'], 100), 50)
        self.assertEqual(penetration_at_distance(child['ammo']['ap'], 100), 60)
        self.assertEqual(child['default'], parent['default'])

    def test_layered_inheritance_scoped_presets_and_carried_ammunition(self):
        with TemporaryDirectory() as temporary:
            resource = Path(temporary) / 'resource'
            pak(resource / 'entity/vehicle.pak', {'-vehicle/tank_medium/tank.def': '''
                {Weaponry {place "gun" {weapon "child" filling "bullet_test ap" 1}}}
                {inventory {item "bullet_test ap ammo" 5} {item "bullet_test apcr ammo" 0}}
            '''})
            pak(resource / 'gamelogic.pak', {
                'set/stuff/gun/.presets': PRESET,
                'set/stuff/smg/.presets': '(define "penetration_medium" {healthDamage 999})',
                'set/stuff/gun/parent': '''{filling "bullet_test" 1} {calibre 75}
                    {projectileDamageTable {10 500} {100 400}}
                    ("penetration_medium" shell(ap) a(109) b(92))
                    ("penetration_medium" shell(apcr) a(160) b(130))''',
                'set/stuff/gun/child': '{from "parent"}',
            })
            mod = Mod('1', 'Penetration override', Path(temporary) / 'mod')
            pak(mod.path / 'resource/custom.pak', {'set/stuff/gun/child': '''{from "parent"
                {parameters "ap" {projectileDamageTable {10 200} {100 150}}}}'''})
            for mods, expected in (([], 92), ([mod], 150)):
                with self.subTest(mods=mods), GameData(resource, mods) as data:
                    nodes = [{'id': 'tank'}]
                    annotate_unit_metadata([{'faction': 'eng', 'nodes': nodes}],
                                           data.view('entity/'), data.view(), {})
                    rows = nodes[0]['vehicle_weapons'][0]['armor_penetration']
                    by_shell = {row['ammunition']: row for row in rows}
                    ap, apcr = by_shell['ap'], by_shell['apcr']
                    self.assertEqual(ap['ammunition'], 'ap')
                    self.assertEqual(ap['penetration_100m_mm'], expected)
                    self.assertTrue(ap['carried'])
                    self.assertFalse(apcr['carried'])
                    self.assertFalse(by_shell['default']['carried'])

    def test_maximum_range_uses_shell_range_not_curve_endpoint(self):
        with TemporaryDirectory() as temporary:
            resource = Path(temporary) / 'resource'
            pak(resource / 'entity/vehicle.pak', {'-vehicle/tank_medium/tank.def':
                '{Weaponry {place "gun" {weapon "child"}}}'})
            pak(resource / 'gamelogic.pak', {
                'set/stuff/gun/parent': '''{calibre 75} {range 170 200}
                    {projectileDamageTable {0 90} {250 40}}
                    {parameters "ap" {projectileDamageTable {10 150} {100 100} {200 60} {215 0}}}
                    {parameters "heat" {range 170 180}
                        {projectileDamageTable {0 100} {180 100} {195 0}}}
                    {parameters "apcr" {maxRange 150}}
                    {parameters "unresolved" {maxRange %unknown}}
                    {parameters "outside" {maxRange 500}}
                ''',
                'set/stuff/gun/child': '{from "parent"}',
            })
            mod = Mod('1', 'Shell range override', Path(temporary) / 'mod')
            pak(mod.path / 'resource/custom.pak', {'set/stuff/gun/child':
                '{from "parent" {parameters "ap" {maxRange 100}}}'})
            for mods, ap_range, ap_penetration in (([], 200, 60), ([mod], 100, 100)):
                with self.subTest(mods=mods), GameData(resource, mods) as data:
                    nodes = [{'id': 'tank'}]
                    annotate_unit_metadata([{'faction': 'eng', 'nodes': nodes}],
                                           data.view('entity/'), data.view(), {})
                    rows = {row['ammunition']: row for row in nodes[0]['vehicle_weapons'][0]['armor_penetration']}
                    self.assertEqual(rows['ap']['maximum_range_m'], ap_range)
                    self.assertEqual(rows['ap']['penetration_max_range_mm'], ap_penetration)
                    self.assertEqual(rows['heat']['maximum_range_m'], 180)
                    self.assertEqual(rows['heat']['penetration_max_range_mm'], 100)
                    self.assertEqual(rows['apcr']['penetration_max_range_mm'], 60)
                    self.assertIsNone(rows['unresolved']['maximum_range_m'])
                    self.assertIsNone(rows['unresolved']['penetration_max_range_mm'])
                    self.assertIsNone(rows['outside']['penetration_max_range_mm'])


if __name__ == '__main__':
    unittest.main()
