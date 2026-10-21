"""Only active entity settings should indicate indirect-fire capability."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from create_research_tree_html import annotate_unit_metadata, has_indirect_fire
from game_data import GameData
from test_game_data import pak


class IndirectFireTests(unittest.TestCase):
    def test_unused_shared_templates_do_not_grant_indirect_fire(self):
        text = '''
            (define "abm_dymamic_mortar"
                ("accuracy_by_motion" max_linear(5) label("quoted (parentheses)"))
            )
            (define "artillery_options" {props "artillery_minimap_heavy" "mortar"})
            {props "vehicle" "cannon" "trailer" "sq_ammo_supply"}
        '''
        self.assertFalse(has_indirect_fire(text))

    def test_comments_do_not_grant_indirect_fire(self):
        self.assertFalse(has_indirect_fire('''
            ; {props "mortar" "artillery_minimap"}
            ; ("abm_dymamic_mortar" dispersion(1))
            {props "vehicle"} ; "indirect_minimap"
        '''))

    def test_active_settings_preserve_real_indirect_fire(self):
        for text in (
            '{props "mortar"}',
            '{props "artillery_minimap"}',
            '{props "artillery_minimap_heavy"}',
            '{props "indirect_minimap"}',
            '("abm_dymamic_mortar" dispersion(1))',
            '(define "abm_dymamic_mortar" ("accuracy_by_motion" max_linear(5)))\n'
            '("abm_dymamic_mortar" dispersion(1))',
        ):
            with self.subTest(text=text):
                self.assertTrue(has_indirect_fire(text))


class IndirectFireIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.resource = Path(temporary.name) / 'resource'
        self.resource.mkdir()

    def test_close_support_howitzers_include_secondary_and_inherited_guns(self):
        pak(self.resource / 'gamelogic.pak', {
            'set/stuff/gun/.presets': '''
                (define "curved_firing_arc" {gravity 5.5})
                (define "indirect_settings" {aimtype curved})
                (define "range_160_howitzer"
                    ("curved_firing_arc") {range 160 160} ("indirect_settings"))
                (define "direct_settings" {aimtype direct})
            ''',
            'set/stuff/gun/76mm_qf3':
                '{from "pattern gun" ("range_160_howitzer") {calibre 76}}',
            'set/stuff/gun/inherited_howitzer': '{from "76mm_qf3"}',
            'set/stuff/gun/direct_gun': '("direct_settings") {calibre 88}',
            'set/stuff/gun/spigot_mortar': '("direct_settings") {gravity 1}',
            'set/stuff/gun/gun.pattern': '{aimtype direct}',
        })
        pak(self.resource / 'entity/vehicle.pak', {
            '-vehicle/tank_heavy/churchill.def': '''{Weaponry
                {place "gun" {weapon "direct_gun"}}
                {place "secondary" {weapon "76mm_qf3"}}
            }''',
            '-vehicle/tank_medium/support.def':
                '{Weaponry {place "gun" {weapon "inherited_howitzer"}}}',
            '-vehicle/tank_heavy/avre.def':
                '{Weaponry {place "gun" {weapon "spigot_mortar"}}}',
        })
        nodes = [{'id': name} for name in ('churchill', 'support', 'avre')]
        with GameData(self.resource) as data:
            count, *_ = annotate_unit_metadata([{'faction': 'eng', 'nodes': nodes}],
                                               data.view('entity/'), data.view(), {})
        self.assertEqual(count, 2)
        self.assertEqual([node['indirect_fire'] for node in nodes], [True, True, False])
        self.assertTrue(all(node['unit_class'] == 'tanks' for node in nodes))
        self.assertEqual({w['id']: w['indirect_fire'] for w in nodes[0]['vehicle_weapons']},
                         {'direct_gun': False, '76mm_qf3': True})
        self.assertTrue(nodes[1]['vehicle_weapons'][0]['indirect_fire'])

    def test_shared_cannon_properties_do_not_make_supply_trailer_artillery(self):
        shared = '(define "abm_dymamic_mortar" ("accuracy_by_motion" max_linear(5)))'
        pak(self.resource / 'properties.pak', {'properties/cannon.ext': shared})
        pak(self.resource / 'entity/vehicle.pak', {
            '-vehicle/trailer/ammo_trailer_eng.def':
                '(include "/properties/cannon.ext") {props "trailer" "sq_ammo_supply"}',
            '-vehicle/mortar/mortar.def':
                '(include "/properties/cannon.ext") ("abm_dymamic_mortar" dispersion(1))',
            '-vehicle/howitzer/howitzer.def':
                '(include "/properties/cannon.ext") {props "artillery_minimap_heavy"}',
        })
        pak(self.resource / 'gamelogic.pak', {})
        nodes = [{'id': name} for name in ('ammo_trailer_eng', 'mortar', 'howitzer')]
        with GameData(self.resource) as data:
            count, *_ = annotate_unit_metadata([{'faction': 'eng', 'nodes': nodes}],
                                               data.view('entity/'), data.view(), {})
        self.assertEqual(count, 2)
        self.assertFalse(nodes[0]['indirect_fire'])
        self.assertNotEqual(nodes[0]['unit_class'], 'artillery')
        self.assertTrue(nodes[1]['indirect_fire'])
        self.assertTrue(nodes[2]['indirect_fire'])

    def test_carried_piat_and_inherited_weapon_are_indirect_without_changing_infantry_role(self):
        pak(self.resource / 'gamelogic.pak', {
            'set/stuff/bazooka/piat.weapon': '{from "pattern rpg_weapon"}',
            'set/stuff/bazooka/rpg_weapon.pattern': '{gravity 0.75}',
            'set/stuff/bazooka/mod_piat.weapon': '{from "piat"}',
            'set/stuff/bazooka/bazooka.weapon': '{from "pattern rpg_weapon"}',
        })
        pak(self.resource / 'entity/vehicle.pak', {})
        def squad(weapon, count=1):
            return {'id': weapon + str(count), 'unit': {'definition_type': 'squad'},
                    'members': [{'count': count, 'breed_file': {
                        'icon_id': 'bazooka', 'inventory_items': [{'item': weapon}]}}]}
        nodes = [squad('piat'), squad('mod_piat'), squad('bazooka'), squad('piat', 0)]
        with GameData(self.resource) as data:
            count, *_ = annotate_unit_metadata([{'faction': 'eng', 'nodes': nodes}],
                                               data.view('entity/'), data.view(), {})
        self.assertEqual(count, 2)
        self.assertEqual([node['indirect_fire'] for node in nodes], [True, True, False, False])
        self.assertTrue(all(node['unit_class'] == 'infantry' for node in nodes))

    def test_tank_arc_presets_patterns_and_mod_overrides(self):
        pak(self.resource / 'gamelogic.pak', {
            'set/stuff/gun/.presets': '(define "curved_firing_arc" {gravity 5.5}) '
                '(define "range_howitzer" ("curved_firing_arc"))',
            'set/stuff/gun/arc_gun': '("range_howitzer")',
            'set/stuff/gun/inherited_gun': '{from "arc_gun"}',
            'set/stuff/gun/direct_gun': '{gravity 0.75}',
            'set/stuff/gun/curved_gun': '{from "pattern curved"}',
            'set/stuff/gun/curved.pattern': '{aimtype curved}',
            'set/stuff/gun/commented_gun': '; ("range_howitzer")\n{gravity 0.75}',
            'set/stuff/gun/cycle_a': '{from "cycle_b"}',
            'set/stuff/gun/cycle_b': '{from "cycle_a"}',
        })
        guns = ['arc_gun', 'inherited_gun', 'direct_gun', 'curved_gun', 'commented_gun', 'cycle_a']
        pak(self.resource / 'entity/vehicle.pak', {
            f'-vehicle/tank_medium/{gun}.def': '{Weaponry {place "gun" {weapon "' + gun + '"}}}'
            for gun in guns
        })
        nodes = [{'id': gun} for gun in guns]
        with GameData(self.resource) as data:
            count, *_ = annotate_unit_metadata([{'faction': 'eng', 'nodes': nodes}],
                                               data.view('entity/'), data.view(), {})
        self.assertEqual(count, 3)
        self.assertEqual([node['indirect_fire'] for node in nodes], [True, True, False, True, False, False])
        self.assertTrue(all(node['unit_class'] == 'tanks' for node in nodes))
        # A mod replacing the gun definition removes its inherited arc setting.
        from game_data import Mod
        mod = Mod('1', 'Direct gun override', self.resource.parent / 'mod')
        pak(mod.path / 'resource/custom.pak', {'set/stuff/gun/arc_gun': '{gravity 0.75}'})
        with GameData(self.resource, [mod]) as data:
            annotate_unit_metadata([{'faction': 'eng', 'nodes': nodes}],
                                   data.view('entity/'), data.view(), {})
        self.assertFalse(nodes[0]['indirect_fire'])
        self.assertFalse(nodes[1]['indirect_fire'])
    def test_sturmmoerser_prefixed_launcher_preserves_main_gun_ammo_and_indirect_fire(self):
        pak(self.resource / 'entity/vehicle.pak', {
            '-vehicle/tank_heavy/sturmtiger.def': '''{game_entity
                {Weaponry
                    {place "gun" {weapon "weapon 380mm_rw61" filled}}
                    {place "mgun" {weapon "mg34_tank" filled}}
                }
                {extender "inventory" {box {item "ammo 380mm_rw61" 13}}}
            }''',
        })
        pak(self.resource / 'gamelogic.pak', {
            'set/stuff/reactive/380mm_rw61.weapon': '''{from "pattern reactive"
                {filling "ammo 380mm_rw61" 1} {calibre 380}
                ("reload time" seconds(90)) {gravity 3}
            }''',
            'set/stuff/reactive/reactive.pattern': '{weapon_bullet {tag "mrl"}}',
            'set/stuff/mgun/mg34_tank': '{calibre 7.92}',
        })
        nodes = [{'id': 'sturmtiger'}]
        with GameData(self.resource) as data:
            count, *_ = annotate_unit_metadata([{'faction': 'ger', 'nodes': nodes}],
                                               data.view('entity/'), data.view(), {})
        node = nodes[0]
        self.assertEqual(count, 1)
        self.assertTrue(node['indirect_fire'])
        self.assertEqual(node['unit_class'], 'tanks')
        self.assertEqual(node['main_gun_caliber_mm'], 380)
        self.assertEqual(node['reload_time'], 90)
        self.assertEqual([w['id'] for w in node['vehicle_weapons']], ['380mm_rw61', 'mg34_tank'])
        gun = node['vehicle_weapons'][0]
        self.assertEqual(gun['mount_count'], 1)
        self.assertEqual(gun['rounds_before_reload'], 1)
        self.assertEqual(gun['ammunition'][0]['loaded_count'], 1)
        self.assertEqual(gun['ammunition'][0]['spare_count'], 13)
        self.assertEqual(gun['ammunition'][0]['total_count'], 14)

    def test_prefixed_and_plain_references_share_mount_counts(self):
        pak(self.resource / 'entity/vehicle.pak', {
            '-vehicle/tank_medium/tank.def': '''{Weaponry
                {place "left" {weapon "Weapon GUN" filled}}
                {place "right" {weapon "gun" filled}}
            }''',
        })
        pak(self.resource / 'gamelogic.pak', {
            'set/stuff/gun/gun': '{filling "ammo shells" 1} {calibre 20}',
        })
        nodes = [{'id': 'tank'}]
        with GameData(self.resource) as data:
            annotate_unit_metadata([{'faction': 'ger', 'nodes': nodes}],
                                   data.view('entity/'), data.view(), {})
        guns = nodes[0]['vehicle_weapons']
        self.assertEqual(len(guns), 1)
        self.assertEqual(guns[0]['mount_count'], 2)
        self.assertEqual(guns[0]['ammunition'][0]['loaded_count'], 2)
        self.assertFalse(nodes[0]['indirect_fire'])
