"""Generate a real viewer fixture and test geometry in sandboxed headless Chrome."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from create_research_tree_html import write_html

LAYOUT_PROBE = r'''<script>
addEventListener('load', () => {
  const failures = [];
  const check = (condition, message) => { if (!condition) failures.push(message); };
  const rect = id => document.getElementById(id).getBoundingClientRect();
  const inspect = stage => {
    const header = rect('viewer-header'), workspace = rect('workspace'), faction = rect('faction');
    check(workspace.top >= header.bottom - 1, stage + ': workspace overlaps header');
    check(workspace.height > 100, stage + ': no usable workspace');
    check(faction.top >= 0 && faction.bottom <= workspace.top + 1, stage + ': faction not above workspace');
    check(faction.right <= innerWidth && faction.left >= 0, stage + ': faction outside screen');
    const hit = document.elementFromPoint(faction.left + faction.width / 2, faction.top + faction.height / 2);
    check(hit?.id === 'faction', stage + ': faction obscured');
    for (const id of ['filter-panel', 'viewport', 'table-view', 'details']) {
      const element = document.getElementById(id);
      if (!element.hidden) check(rect(id).top >= workspace.top - 1, stage + ': ' + id + ' overlaps header');
    }
  };
  inspect('collapsed');
  document.getElementById('data-limitations').open = true;
  inspect('expanded');
  const view = document.getElementById('view-mode');
  view.value = 'table'; view.dispatchEvent(new Event('change'));
  inspect('table');
  document.getElementById('filter-toggle').click();
  inspect('sidebar-toggle');
  const result = document.createElement('pre'); result.id = 'layout-result';
  result.textContent = JSON.stringify({ok: failures.length === 0, failures, width: innerWidth});
  document.body.append(result);
});
</script>'''


def fixture(directory):
    trees = [{'faction': 'fin', 'mod_id': 'preset:test', 'mod_name': 'Combined preset',
              'viewer_limitations': ['Long warning ' * 45] * 3,
              'nodes': [{'id': 'unit', 'display_name': 'Unit', 'requires': [], 'cost': 1,
                         'node_type': 'unit', 'position': {'x': 1, 'y': 1}, 'stats': {}}]}]
    path = write_html(trees, directory)
    text = path.read_text().replace('</body>', LAYOUT_PROBE + '</body>')
    path.write_text(text)
    return path


class LayoutTests(unittest.TestCase):
    def test_header_and_workspace_containment(self):
        with tempfile.TemporaryDirectory() as temp:
            text = fixture(Path(temp)).read_text()
        self.assertLess(text.index('id="viewer-header"'), text.index('id="data-limitations"'))
        self.assertLess(text.index('id="data-limitations"'), text.index('id="toolbar"'))
        self.assertLess(text.index('id="workspace"'), text.index('id="filter-panel"'))
        self.assertNotIn('inset: 54px', text)
        self.assertNotIn('top: 54px', text)

    @unittest.skipUnless(shutil.which('google-chrome'), 'Google Chrome unavailable')
    def test_actual_browser_geometry_desktop_and_mobile(self):
        import re
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            page = fixture(root)
            for width, height in [(1440, 1000), (480, 900)]:
                with self.subTest(width=width):
                    process = subprocess.run([
                        'google-chrome', '--headless', '--disable-gpu',
                        '--no-first-run', '--no-default-browser-check',
                        f'--user-data-dir={root / str(width)}',
                        f'--window-size={width},{height}', '--virtual-time-budget=3000',
                        '--dump-dom', page.as_uri()], capture_output=True, text=True, timeout=45)
                    self.assertEqual(process.returncode, 0, process.stderr[-2000:])
                    match = re.search(r'<pre id="layout-result">(.*?)</pre>', process.stdout)
                    self.assertIsNotNone(match, process.stderr[-2000:])
                    result = json.loads(match[1].replace('&quot;', '"').replace('&amp;', '&'))
                    self.assertTrue(result['ok'], result)


if __name__ == '__main__':
    unittest.main()
