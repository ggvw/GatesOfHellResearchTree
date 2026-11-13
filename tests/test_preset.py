"""Explicit preset selection never exports unrelated installed Workshop mods."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game_data import GameData, preset_layers, validate_preset_dataset
import export_research_trees as exporter
import create_research_tree_html as html


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.game = self.root / 'resource'
        self.game.mkdir()
        self.ids = ['2', '1']  # Deliberately not sorted numerically.
        self.write_config()
        for identifier in self.ids:
            folder = self.root / identifier
            (folder / 'resource/set/dynamic_campaign').mkdir(parents=True)
            (folder / 'mod.info').write_text('{name "Layer ' + identifier + '"}')
        (self.root / '1/mod.info').write_text('{name "Overlay"}{require "mod_2"}')
        factions = 'csa fin fra frg gdr nat pol prc rus sov'.split()
        for index, faction in enumerate(factions):
            identifier = self.ids[index % 2]
            (self.root / identifier / 'resource/set/dynamic_campaign' /
             f'unit_research_{faction}.set').write_text(faction)

    def write_config(self):
        self.config.write_text(json.dumps({'workshop_path': str(self.root),
                                          'presets': {'Full': self.ids}}))

    def test_order_and_ten_factions(self):
        layers = preset_layers(self.config, 'Full')
        self.assertEqual([item.id for item in layers], ['2', '1'])
        with GameData(self.game, layers) as data:
            self.assertEqual(exporter.discover_factions(data.view()),
                             'csa fin fra frg gdr nat pol prc rus sov'.split())

    def test_missing_and_order_fail_without_reordering(self):
        self.ids = ['1', '2']
        self.write_config()
        with self.assertRaisesRegex(ValueError, 'requires earlier'):
            preset_layers(self.config, 'Full')
        self.ids = ['999']
        self.write_config()
        with self.assertRaises(FileNotFoundError):
            preset_layers(self.config, 'Full')
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            preset_layers(self.config, 'Absent')

    def test_single_dataset_no_workshop_discovery_and_html_stack(self):
        layers = preset_layers(self.config, 'Full')
        output = self.root / 'output'
        def fake_export(game, target, data, **kwargs):
            target.mkdir()
            for faction in exporter.discover_factions(data.view()):
                (target / f'{faction}.json').write_text('{}')
        with patch.object(exporter, 'discover_mods', side_effect=AssertionError('discovery forbidden')), \
             patch.object(exporter, 'export_dataset', side_effect=fake_export):
            exporter.export(self.game, output, preset='Full', layers=layers, quiet=True)
        datasets = json.loads((output / 'datasets.json').read_text())
        self.assertEqual(len(datasets), 1)
        self.assertEqual(len(datasets[0]['factions_exported']), 10)
        self.assertIs(html.validate_preset_dataset(datasets, 'Full', layers), datasets)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            validate_preset_dataset(datasets, 'Full', list(reversed(layers)))

    def test_resource_less_layer_retained_with_warning(self):
        local = self.root / 'installer'
        local.mkdir()
        (local / 'mod.info').write_text('{name "External installer"}')
        layers = preset_layers(self.config, 'Full', [local])
        with GameData(self.game, layers) as data:
            self.assertEqual(layers[-1].id, 'installer')
            self.assertTrue(any('not emulated' in item for item in data.reported))

    def test_duplicate_and_incomplete_export_fail(self):
        self.ids = ['2', '2']
        self.write_config()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            preset_layers(self.config, 'Full')
        self.ids = ['2', '1']
        self.write_config()
        layers = preset_layers(self.config, 'Full')
        output = self.root / 'incomplete'
        def incomplete(game, target, data, **kwargs):
            target.mkdir()
            (target / 'csa.json').write_text('{}')
            data.warn('synthetic parser warning')
        with patch.object(exporter, 'export_dataset', side_effect=incomplete):
            with self.assertRaisesRegex(RuntimeError, 'Incomplete preset export'):
                exporter.export(self.game, output, preset='Full', layers=layers, quiet=True)
        manifest = json.loads((output / 'datasets.json').read_text())
        self.assertIn('synthetic parser warning', manifest[0]['warnings'])

    def test_optional_local_layer_is_explicit_and_last(self):
        local = self.root / 'repair'
        (local / 'resource').mkdir(parents=True)
        (local / 'mod.info').write_text('{name "Repair"}{require "mod_1"}')
        self.assertEqual([item.id for item in preset_layers(self.config, 'Full', [local])],
                         ['2', '1', 'repair'])
        self.assertEqual(len(preset_layers(self.config, 'Full')), 2)


if __name__ == '__main__':
    unittest.main()
