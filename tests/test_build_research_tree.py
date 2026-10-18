"""Exercise game detection, output safety checks, and the combined build launcher."""

import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image

import build_research_tree as launcher


def pak(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, 'w') as archive:
        for name, value in files.items():
            archive.writestr(name, value)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_resolves_game_root_and_resource_folder(self):
        resource = self.root / 'Game/resource'
        resource.mkdir(parents=True)
        self.assertIsNone(launcher.resolve_resource_dir(self.root / 'Game'))
        (resource / 'gamelogic.pak').touch()
        self.assertEqual(launcher.resolve_resource_dir(self.root / 'Game'), resource.resolve())
        self.assertEqual(launcher.resolve_resource_dir(resource), resource.resolve())
        self.assertIsNone(launcher.resolve_resource_dir(None))

    def test_detects_game_in_additional_library_with_manifest_installdir(self):
        steam = self.root / '.local/share/Steam'
        (steam / 'steamapps').mkdir(parents=True)
        library = self.root / 'Games/SteamLibrary'
        (steam / 'steamapps/libraryfolders.vdf').write_text(
            '"libraryfolders" { "1" { "path" "' + str(library) + '" } }')
        (library / 'steamapps').mkdir(parents=True)
        (library / 'steamapps/appmanifest_400750.acf').write_text('"AppState" { "installdir" "GoH" }')
        resource = library / 'steamapps/common/GoH/resource'
        resource.mkdir(parents=True)
        (resource / 'gamelogic.pak').touch()
        with patch.object(launcher.sys, 'platform', 'linux'), patch.object(launcher.os, 'name', 'posix'):
            self.assertEqual(launcher.find_game_resource_dirs(self.root), [resource.resolve()])

    def test_refuses_unsafe_output_folders(self):
        resource = self.root / 'Game/resource'
        resource.mkdir(parents=True)
        self.assertIsNone(launcher.check_output_dir(self.root / 'new', resource))
        self.assertIsNotNone(launcher.check_output_dir(Path.home(), resource))
        self.assertIsNotNone(launcher.check_output_dir(Path.home().parent, resource))
        self.assertIsNotNone(launcher.check_output_dir(self.root / 'Game/out', resource))
        self.assertIsNotNone(launcher.check_output_dir(self.root, resource))
        (self.root / 'documents').mkdir()
        (self.root / 'documents/notes.txt').write_text('keep')
        self.assertIn('not empty', launcher.check_output_dir(self.root / 'documents', resource))
        (self.root / 'documents/index.html').write_text('<html>unrelated</html>')
        self.assertIn('not empty', launcher.check_output_dir(self.root / 'documents', resource))
        (self.root / 'documents/index.html').write_text(launcher.OUTPUT_SIGNATURE)
        self.assertIsNone(launcher.check_output_dir(self.root / 'documents', resource))

    def test_command_line_rejects_missing_game_and_unsafe_output(self):
        with patch('builtins.print'):
            self.assertEqual(launcher.main(['--game-path', str(self.root)]), 2)
            resource = self.root / 'Game/resource'
            resource.mkdir(parents=True)
            (resource / 'gamelogic.pak').touch()
            self.assertEqual(launcher.main(['--game-path', str(self.root / 'Game'),
                                            '--output', str(Path.home())]), 2)

    def test_command_line_build_runs_both_scripts(self):
        image = io.BytesIO()
        Image.new('RGB', (2, 2), 'red').save(image, format='PNG')
        resource = self.root / 'Game/resource'
        pak(resource / 'gamelogic.pak', {
            'set/dynamic_campaign/unit_research_test.set': '{"u" requires "" costs 1 position 0 0}',
            'set/multiplayer/units/conquest/settings_inf.set': '(define "inf_tier1" {cp 1})',
            'set/multiplayer/units/conquest/inf_test.set': '',
            'set/multiplayer/units/conquest/units_test.set': '{"u" ("vehicle" vehicle(tank) cp(2))}',
        })
        pak(resource / 'interface/scene.pak', {'scene/portrait_squad/u_00.png': image.getvalue()})
        pak(resource / 'interface/pages.pak', {})
        pak(resource / 'entity/-vehicle.pak', {})
        pak(resource / 'properties.pak', {'properties/human.ext': '{Chassis {Run {Fast 5}}}'})
        pak(self.root / 'Game/localizations/default.pak', {})
        output = self.root / 'site'
        lines = []
        with patch('builtins.print', side_effect=lambda line, **_: lines.append(line)):
            code = launcher.main(['--game-path', str(self.root / 'Game'), '--output', str(output)])
        self.assertEqual(code, 0, '\n'.join(lines))
        self.assertTrue(launcher.is_previous_output(output))


if __name__ == '__main__':
    unittest.main()
