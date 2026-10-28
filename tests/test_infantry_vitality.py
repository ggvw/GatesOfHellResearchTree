"""Resolve soldier health and ordinary vision without counting scope bonuses."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from create_research_tree_html import (
    GameFiles, annotate_infantry_vitality, infantry_vitality,
    _named_parenthesized_blocks,
)
from game_data import GameData, Mod
from test_game_data import pak


HUMAN = '''{extender "vitality" {Health {max 100} {current 50}}}
{Sensor {Visor "eyes" {vision "human"}}}'''
VISION = '''
(define "radius" (mod "mp" {radius (* 0.5 %r)}) (mod not "mp" {radius (* 1.0 %r)}))
(define "spotting" ("radius" r(%r)) {rules {human 100}})
{"human" ("spotting" r(1.0))}
{"human_recon" ("spotting" r(1.25))}
'''
PERKS = '''
(define "standard" {"health" "200%"} {"vision" human})
(define "recon" {"health" "150%"} {"vision" human_recon} {"field_glass"})
'''


class InfantryVitalityTests(unittest.TestCase):
    def resolve(self, perks, extra=''):
        presets = _named_parenthesized_blocks(VISION + PERKS + extra, '(define ')
        return infantry_vitality(perks, HUMAN, VISION, presets)

    def test_health_percentage_and_standard_recon_ranges(self):
        self.assertEqual(self.resolve('("standard")'), {
            'health': 200, 'vision_profile': 'human', 'vision_range_m': 100,
        })
        self.assertEqual(self.resolve('("recon")'), {
            'health': 150, 'vision_profile': 'human_recon', 'vision_range_m': 125,
        })

    def test_defaults_and_explicit_overrides(self):
        self.assertEqual(self.resolve('')['health'], 100)
        self.assertEqual(self.resolve('')['vision_range_m'], 100)
        stats = self.resolve('("standard") {"health" "375%"} {"vision" human_recon}')
        self.assertEqual(stats['health'], 375)
        self.assertEqual(stats['vision_range_m'], 125)

    def test_comments_unused_presets_and_unknown_values(self):
        stats = self.resolve('''
            ; {"health" "999%"}
            (define "unused" {"health" "888%"} {"vision" human_recon})
            ("standard")
        ''')
        self.assertEqual(stats['health'], 200)
        self.assertEqual(stats['vision_range_m'], 100)
        self.assertIsNone(self.resolve('{"health" "%unknown"}')['health'])
        self.assertIsNone(self.resolve('{"vision" unknown}')['vision_range_m'])
        self.assertEqual(self.resolve('{"health" "0%"}')['health'], 0)

    def test_includes_mod_overrides_and_missing_breeds(self):
        with TemporaryDirectory() as temporary:
            resource = Path(temporary) / 'resource'
            pak(resource / 'properties.pak', {'properties/human.ext': HUMAN})
            pak(resource / 'gamelogic.pak', {
                'set/vision/vision.set': '(include "fields.inc")',
                'set/vision/fields.inc': VISION,
                'set/breed/presets/perks/health.inc': PERKS,
                'set/breed/test.set': '''{breed {perks
                    (include "/set/breed/presets/perks/health.inc")
                    ("standard")
                }}''',
            })
            mod = Mod('1', 'Health override', Path(temporary) / 'mod')
            pak(mod.path / 'resource/custom.pak', {
                'set/breed/presets/perks/health.inc':
                    '(define "standard" {"health" "350%"} {"vision" human_recon})',
            })
            for mods, health, vision in (([], 200, 100), ([mod], 350, 125)):
                with self.subTest(mods=mods), GameData(resource, mods) as data:
                    members = [{'breed_file': {'path': 'set/breed/test.set'}},
                               {'breed_file': {'path': 'set/breed/missing.set'}}, {}]
                    files = GameFiles(data.view(), data.view(), data.view(), data.view())
                    annotate_infantry_vitality([{'nodes': [{'members': members}]}], files)
                    self.assertEqual(members[0]['health'], health)
                    self.assertEqual(members[0]['vision_range_m'], vision)
                    for missing in members[1:]:
                        self.assertIsNone(missing['health'])
                        self.assertIsNone(missing['vision_range_m'])

            # The standalone archive entry point must resolve includes too.
            files = GameFiles(resource / 'properties.pak', resource / 'gamelogic.pak',
                              resource / 'gamelogic.pak', resource / 'properties.pak')
            member = {'breed_file': {'path': 'set/breed/test.set'}}
            annotate_infantry_vitality([{'nodes': [{'members': [member]}]}], files)
            self.assertEqual(member['health'], 200)
            self.assertEqual(member['vision_range_m'], 100)

    def test_equipped_vision_requires_carried_gear_and_matching_ability(self):
        optics = '''
            (define "glass" ("radius" r(%r)))
            {"rifle_telescope" ("glass" r(15))}
            {"field_glass" ("glass" r(30))}
        '''
        with TemporaryDirectory() as temporary:
            resource = Path(temporary) / 'resource'
            files = {
                'set/vision/vision.set': VISION + optics,
                'set/breed/presets/perks/health.inc': PERKS,
                'set/ability/telescope.set': '''{"telescope" from specialvision
                    {item "rifle" "sniper"} {aimed_vision "rifle_telescope"}}''',
                'set/ability/field_glass.set': '''{"field_glass" from specialvision
                    {item "field_glass"} {aimed_vision "field_glass"}}''',
                'set/stuff/rifle/base.pattern': '{tag "rifle"} {range 120 120}',
                'set/stuff/rifle/scoped': '{from "pattern base" {tag "sniper"} {range 130 130}}',
                'set/stuff/special/binocular': '{weapon_bullet {tag "field_glass"} {range 200 200}}',
                'set/stuff/rifle/unknown': '{from "pattern base" {tag "sniper"} {maxrange %unknown}}',
            }
            for name, abilities in [('plain', ''), ('sniper', '{"telescope"}'),
                                    ('observer', '{"field_glass"}'),
                                    ('both', '{"telescope"} {"field_glass"}')]:
                files[f'set/breed/{name}.set'] = '{breed {perks ("standard") ' + abilities + '}}'
            pak(resource / 'properties.pak', {'properties/human.ext': HUMAN})
            pak(resource / 'gamelogic.pak', files)
            mod = Mod('1', 'Binocular range override', Path(temporary) / 'mod')
            pak(mod.path / 'resource/custom.pak', {
                'set/vision/vision.set': VISION + optics.replace('r(30)', 'r(45)'),
            })

            def member(breed, items):
                return {'breed_file': {'path': f'set/breed/{breed}.set',
                                      'inventory_items': [{'item': item} for item in items]}}

            for mods, binocular_range in (([], 230), ([mod], 245)):
                members = [member('plain', ['scoped', 'binocular']),
                           member('sniper', ['scoped']),
                           member('observer', ['binocular']),
                           member('both', ['scoped', 'binocular']),
                           member('sniper', []), member('sniper', ['unknown'])]
                with self.subTest(mods=mods), GameData(resource, mods) as data:
                    views = GameFiles(data.view(), data.view(), data.view(), data.view())
                    annotate_infantry_vitality([{'nodes': [{'members': members}]}], views)
                    self.assertEqual([m['equipped_vision_range_m'] for m in members],
                                     [100, 145, binocular_range, binocular_range, 100, None])
                    self.assertEqual(members[0]['equipped_vision_sources'], [])
                    self.assertEqual(members[3]['equipped_vision_sources'], ['scoped', 'binocular'])
                    self.assertTrue(all(m['vision_range_m'] == 100 for m in members))


if __name__ == '__main__':
    unittest.main()
