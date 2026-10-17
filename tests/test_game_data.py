"""Exercise Workshop discovery, real file overlays, and mod-aware export/enrichment."""

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image

from game_data import GameData, Mod, discover_mods, expand_defines, mod_layers
from export_research_trees import build_unit_lookup, export, parse_research_entries, parse_unit_block
from create_research_tree_html import (annotate_unit_metadata, convert_images,
                                       load_localizations, load_trees, write_html)


def pak(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, 'w') as archive:
        for name, value in files.items():
            archive.writestr(name, value)


class GameDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.resource = self.root / 'steamapps/common/Game/resource'
        self.resource.mkdir(parents=True)

    def test_discovery_across_registered_libraries_and_missing_metadata(self):
        library = self.root / 'other/steamapps'
        (self.root / 'steamapps/libraryfolders.vdf').write_text(
            '"libraryfolders" { "1" { "path" "' + str(library.parent) + '" } }')
        folder = library / 'workshop/content/400750/123'
        (folder / 'resource').mkdir(parents=True)
        (folder / 'mod.info').write_text('{mod {name "Test mod"} {require "mod_456"}}')
        (folder.parent / '999').mkdir()
        with patch('game_data.Path.home', return_value=self.root), patch('game_data.warning') as warn:
            mods = discover_mods(self.resource)
        self.assertEqual([(mod.id, mod.name, mod.requires) for mod in mods], [('123', 'Test mod', ('456',))])
        self.assertTrue(warn.called)

    def test_dependencies_are_ordered_and_missing_or_cyclic_dependencies_rejected(self):
        base = Mod('1', 'Dependency', self.root)
        selected = Mod('2', 'Selected', self.root, ('1',))
        self.assertEqual(mod_layers(selected, [selected, base]), [base, selected])
        with self.assertRaisesRegex(ValueError, 'missing'):
            mod_layers(selected, [selected])
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            mod_layers(selected, [selected, Mod('1', 'Cycle', self.root, ('2',))])

    def test_overrides_mount_paths_loose_files_and_deletions(self):
        pak(self.resource / 'gamelogic.pak', {'set/shared.set': 'base', 'set/removed.set': 'remove'})
        dep = Mod('1', 'Dependency', self.root / 'dependency')
        mod = Mod('2', 'Selected', self.root / 'selected', deletes=('resource/set/removed.set',))
        pak(dep.path / 'resource/custom.pak', {'SET/Shared.set': 'dependency'})
        pak(mod.path / 'resource/a.pak', {'set/shared.set': 'first'})
        pak(mod.path / 'resource/z.pak', {'set/shared.set': 'last'})
        pak(mod.path / 'resource/interface/scene/portraits.pak', {'portrait/u.png': b'image'})
        loose = mod.path / 'resource/set/shared.set'
        loose.parent.mkdir()
        loose.write_text('loose wins')
        with GameData(self.resource, [dep, mod]) as data:
            self.assertEqual(data.view().read('SET\\SHARED.SET'), b'loose wins')
            self.assertNotIn('set/removed.set', data.files)
            self.assertEqual(data.view('interface/').read('scene/portrait/u.png'), b'image')
        with GameData(self.resource) as data:
            self.assertEqual(data.read('set/shared.set'), b'base')

    def test_bad_archives_missing_includes_and_cycles_do_not_crash(self):
        (self.resource / 'bad.pak').write_text('not a zip')
        pak(self.resource / 'gamelogic.pak', {
            'set/a.set': '(include "b.set") (include "missing.set")',
            'set/b.set': '(include "a.set")',
        })
        with patch('game_data.warning') as warn, GameData(self.resource) as data:
            self.assertEqual(data.text('set/a.set').strip(), '')
        messages = ' '.join(call.args[0] for call in warn.call_args_list)
        for diagnostic in ('Cannot parse archive', 'Missing reference', 'Include cycle'):
            self.assertIn(diagnostic, messages)

    def test_text_preserves_comments_without_loading_commented_includes(self):
        pak(self.resource / 'gamelogic.pak', {
            'set/a.set': '; (include "missing.set")\n{"mp/unit" ("inf" cost(3))} ; rifle squad',
        })
        with patch('game_data.warning') as warn, GameData(self.resource) as data:
            text = data.text('set/a.set')
        self.assertIn('; rifle squad', text)
        self.assertFalse(warn.called)

    def test_research_templates_fractional_positions_and_implicit_starter(self):
        pak(self.resource / 'gamelogic.pak', {
            'set/tree.set': '(include "tree.inc") ("branch" column(3) row(4)) '
                            '{positions {"starter" 0 0.5}}',
            'set/tree.inc': '(define "branch" ; a comment with ( unmatched\n'
                            '{"unit" requires "starter" costs 2 position (+ 2 %column) (+ 1 %row)})',
        })
        with GameData(self.resource) as data:
            entries = parse_research_entries(expand_defines(data.text('set/tree.set')))
        self.assertEqual([node['id'] for node in entries], ['unit', 'starter'])
        self.assertEqual(entries[0]['position'], {'x': 5, 'y': 5})
        self.assertEqual(entries[1]['position'], {'x': 0, 'y': 0.5})
        self.assertEqual(entries[1]['cost'], 0)

    def test_active_roster_uses_custom_include_names_in_declared_order(self):
        pak(self.resource / 'gamelogic.pak', {
            'set/multiplayer/units/roster_conquest.set': '{units (include "conquest/first.set") (include "conquest/custom.set")}',
            'set/multiplayer/units/conquest/first.set': '{"u" ("vehicle" cp(2))}',
            'set/multiplayer/units/conquest/custom.set': '{"u" ("vehicle" cp(7))}',
        })
        with GameData(self.resource) as data:
            blocks, _, _ = build_unit_lookup('new_faction', data.view())
        self.assertEqual(parse_unit_block('u', blocks['u'])['cp'], 7)

    def test_mod_localization_overrides_context_in_different_file(self):
        pak(self.resource.parent / 'localizations/default.pak', {
            'base.pot': 'msgctxt "unit"\nmsgid "Base unit"\nmsgstr ""\n',
            'later.pot': 'msgctxt "unit"\nmsgid "Later base unit"\nmsgstr ""\n'})
        mod = Mod('1', 'Mod', self.root / 'mod')
        (mod.path / 'resource').mkdir(parents=True)
        pak(mod.path / 'localizations/default.pak', {
            'base.pot': 'msgctxt "unit"\nmsgid "Mod unit"\nmsgstr ""\n'})
        with GameData(self.resource, [mod]) as data:
            self.assertEqual(load_localizations(data.view())['unit'], 'Mod unit')

    def test_bad_faction_json_is_logged_without_losing_valid_factions(self):
        directory = self.root / 'exports'
        directory.mkdir()
        (directory / 'bad.json').write_text('{broken')
        (directory / 'good.json').write_text(json.dumps({'faction': 'test', 'nodes': [{'id': 'u'}]}))
        with patch('create_research_tree_html.warning') as warn:
            trees = load_trees(directory)
        self.assertEqual([tree['faction'] for tree in trees], ['test'])
        self.assertTrue(warn.called)

    def test_unsupported_template_expressions_and_parse_errors_are_reported(self):
        messages = []
        expand_defines('(define "broken"', messages.append)
        expand_defines('{"u" requires "" costs 1 position (+ 2 %missing) 0}', messages.append)
        self.assertTrue(any('Parsing error' in message for message in messages))
        self.assertTrue(any('Unsupported' in message for message in messages))

    def test_export_keeps_base_and_selected_mod_separate_and_enriches_mod_weapon(self):
        image = io.BytesIO()
        Image.new('RGB', (2, 2), 'red').save(image, format='PNG')
        pak(self.resource / 'gamelogic.pak', {
            'set/dynamic_campaign/unit_research_test.set': '{"u" requires "" costs 1 position 0 0}',
            'set/multiplayer/units/conquest/settings_inf.set': '(define "inf_tier1" {cp 1})',
            'set/multiplayer/units/conquest/inf_test.set': '',
            'set/multiplayer/units/conquest/units_test.set': '{"u" ("vehicle" vehicle(tank) cp(2))}',
            'set/stuff/gun/testgun': '{calibre 20} ("reload time" seconds(2)) {filling "ammo" 1}',
        })
        pak(self.resource / 'interface/scene.pak', {'scene/portrait_squad/u_00.png': image.getvalue()})
        pak(self.resource / 'interface/pages.pak', {})
        pak(self.resource / 'entity/vehicles.pak', {
            '-vehicle/tank/tank.def': '(include "/properties/test-tank.ext")'})
        pak(self.resource / 'properties.pak', {
            'properties/test-tank.ext': '{Weaponry {place "gun" {weapon "testgun"}}}'})
        mod = Mod('123', 'Test mod', self.root / 'mod')
        pak(mod.path / 'resource/custom.pak', {
            'set/dynamic_campaign/unit_research_test.set': '{"u" requires "" costs 9 position 1.5 0}',
            'set/multiplayer/units/conquest/units_test.set': '{"u" ("vehicle" vehicle(tank) cp(7))}',
            'set/stuff/gun/testgun': '{calibre 80} ("reload time" seconds(4)) {filling "ammo" 1}',
        })
        output = self.root / 'export'
        with patch('export_research_trees.discover_mods', return_value=[mod]), patch('builtins.print'):
            export(self.resource, output, quiet=True)
        datasets = json.loads((output / 'datasets.json').read_text())
        self.assertEqual([item['id'] for item in datasets], ['', '123'])
        base = load_trees(output)
        selected = load_trees(output / 'mods/123')
        self.assertEqual(base[0]['nodes'][0]['cost'], 1)
        self.assertEqual(selected[0]['nodes'][0]['cost'], 9)
        self.assertEqual(base[0]['nodes'][0]['unit']['cp'], 2)
        self.assertEqual(selected[0]['nodes'][0]['unit']['cp'], 7)
        for trees, layers, calibre in [(base, [], 20), (selected, [mod], 80)]:
            with GameData(self.resource, layers) as data:
                annotate_unit_metadata(trees, data.view('entity/'), data.view(), {})
            self.assertEqual(trees[0]['nodes'][0]['main_gun_caliber_mm'], calibre)
        # Identical faction/unit IDs from different mods must have distinct image URLs.
        base[0].update(mod_id='', mod_name='None')
        selected[0].update(mod_id='123', mod_name='Test mod')
        selected[0]['nodes'][0]['image']['path'] = 'mods/123/' + selected[0]['nodes'][0]['image']['path']
        website = self.root / 'website'
        convert_images(base + selected, output, website)
        urls = [trees[0]['nodes'][0]['web_image'] for trees in (base, selected)]
        self.assertNotEqual(*urls)
        self.assertTrue(all((website / url).is_file() for url in urls))
        html = write_html(base + selected, website).read_text()
        self.assertLess(html.index('id="mod"'), html.index('id="faction"'))
        self.assertIn("modSelect.value = ''", html)


if __name__ == '__main__':
    unittest.main()
