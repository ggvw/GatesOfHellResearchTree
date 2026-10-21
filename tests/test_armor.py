"""Armor details retain directional overrides and separate vehicle parts."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from create_research_tree_html import annotate_unit_metadata, vehicle_armor
from game_data import GameData, Mod
from test_game_data import pak


class ArmorTests(unittest.TestCase):
    def test_defaults_faces_and_material_are_separate(self):
        parts = vehicle_armor('''
            {volume "body1" {thickness 30 {front 80} {rear 10} {bottom 0}}}
            {volume "turret" {thickness {front 102} {left 89} {right 89}
                {rear 89} {top 31.75} {bottom 25.4}} {CastSteel 0.8063}}
            {volume "mantlet" {thickness 90}}
        ''')
        self.assertEqual(parts[0], {'part': 'body1', 'default_mm': 30,
                                   'front_mm': 80, 'rear_mm': 10, 'bottom_mm': 0})
        self.assertEqual(parts[1], {'part': 'turret', 'front_mm': 102, 'left_mm': 89,
                                   'right_mm': 89, 'rear_mm': 89, 'top_mm': 31.75,
                                   'bottom_mm': 25.4, 'cast_steel_coefficient': 0.8063})
        self.assertEqual(parts[2], {'part': 'mantlet', 'default_mm': 90})

    def test_uninvoked_templates_comments_and_health_are_excluded(self):
        self.assertEqual(vehicle_armor('''
            (define "unused" {volume "body" {thickness 999}})
            ; {volume "turret" {thickness 888}}
            ("general_durability" body(500) turret(300))
            {component "body" {hp 500}}
            {volume "engine" {thickness %unknown}}
        '''), [])

    def test_shortcuts_and_later_part_overrides(self):
        parts = vehicle_armor('''
            ("tracks" repair(30) thickness(20))
            ("gun1" repair(30) thickness(25))
            ("shield_tear" args "shield3" 7)
            ("armor" args "armorL1" 38.1)
            {volume "shield3" {thickness 8 {front 12}}}
        ''')
        self.assertEqual(parts, [
            {'part': 'tracks', 'default_mm': 20},
            {'part': 'gun1', 'default_mm': 25},
            {'part': 'shield3', 'default_mm': 8, 'front_mm': 12},
            {'part': 'armorL1', 'default_mm': 38.1},
        ])

    def test_included_armor_respects_mod_file_overrides(self):
        with TemporaryDirectory() as temporary:
            resource = Path(temporary) / 'resource'
            pak(resource / 'entity/vehicle.pak', {
                '-vehicle/tank_medium/tank.def': '(include "tank.ext")',
                '-vehicle/tank_medium/tank.ext': '{volume "body" {thickness 30}}',
            })
            pak(resource / 'gamelogic.pak', {})
            mod = Mod('1', 'Armor replacement', Path(temporary) / 'mod')
            pak(mod.path / 'resource/custom.pak', {
                'entity/-vehicle/tank_medium/tank.ext':
                    '{volume "body" {thickness 40 {front 80} {left 35}}}',
            })
            for mods, expected in (([], {'default_mm': 30}),
                                   ([mod], {'default_mm': 40, 'front_mm': 80, 'left_mm': 35})):
                nodes = [{'id': 'tank'}]
                with GameData(resource, mods) as data:
                    annotate_unit_metadata([{'faction': 'ger', 'nodes': nodes}],
                                           data.view('entity/'), data.view(), {})
                self.assertEqual(nodes[0]['armor_parts'], [{'part': 'body', **expected}])


if __name__ == '__main__':
    unittest.main()
