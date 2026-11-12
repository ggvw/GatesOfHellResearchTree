"""Keep malformed source counts unresolved instead of inventing repairs."""
import sys
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from export_research_trees import parse_unit_block, describe_unit_members, parse_research_entries
from create_research_tree_html import write_html


class MalformedRosterTests(unittest.TestCase):
    def test_exact_finnish_m62_source_token(self):
        block = ('("squad_with2types_conquest" side(fin) name(single_bazooker_fin_m62) '
                 'period(m62_coldwar) min_stage(20) max_stage(99) '
                 'c1(antitank_pzs_m62:1) c2(antitank_pzs_ammo:_m621))')
        unit = parse_unit_block('single_bazooker_fin_m62', block)
        self.assertEqual(unit['members'][0]['count'], 1)
        self.assertEqual(unit['members'][1]['raw_count'], '_m621')
        self.assertIsNone(unit['members'][1]['count'])
        self.assertIsNone(unit['unit_count'])
        with tempfile.TemporaryDirectory() as directory:
            with ZipFile(Path(directory) / 'empty.zip', 'w') as archive:
                details, cost, _ = describe_unit_members(unit, {}, {}, {}, archive)
            self.assertIsNone(cost)
            self.assertIsNone(unit['cp'])
            self.assertEqual(details[1]['raw_count'], '_m621')
            trees = [{'faction': 'fin', 'nodes': [{'id': unit['id'], 'members': details}],
                      'viewer_limitations': ['Duplicate IDs: graph uses last definition only.']}]
            html = write_html(trees, Path(directory)).read_text()
            self.assertIn('Data limitations', html)
            self.assertIn('malformed roster count', html)
            self.assertIn('graph uses last definition only', html)

    def test_unknown_at_carrier_count_is_not_zero_or_partial_total(self):
        from create_research_tree_html import annotate_infantry_capabilities
        node = {'unit_class': 'infantry', 'members': [
            {'count': None, 'breed_file': {'inventory_items': [{'item': 'bazooka'}]}},
            {'count': 2, 'breed_file': {'inventory_items': [{'item': 'bazooka'}]}},
        ]}
        annotate_infantry_capabilities(node, {'bazooka'}, set(), set())
        self.assertIsNone(node['anti_tank_weapon_count'])
        node['members'][0]['count'] = 0
        annotate_infantry_capabilities(node, {'bazooka'}, set(), set())
        self.assertEqual(node['anti_tank_weapon_count'], 2)

    def test_commented_records_excluded_but_section_preserved(self):
        text = (';---IFVs---\n; {"inactive" requires "" costs 9 position 0 0}\n'
                '{"active;id" requires "" costs 1 position 1 1} ; ignored\n')
        records = parse_research_entries(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], 'active;id')
        self.assertEqual(records[0]['research_section'], 'IFVs')

    def test_distinct_duplicate_grants_are_parsed(self):
        text = ('{"zbd86" requires "yw531" costs 5 position 11 6}\n'
                '{"zbd86" requires "squad_guards_mech_con(prc)" costs 0 position 14 4.5}\n'
                '{tech "pol_desnatowa_1960" requires "" costs 5 position 0 8}\n'
                '{tech "pol_desnatowa_1960" requires "" costs 0 position 0 9}')
        records = parse_research_entries(text)
        self.assertEqual(len(records), 4)
        self.assertEqual([record['cost'] for record in records], [5, 0, 5, 0])
        self.assertNotEqual(records[0]['requires'], records[1]['requires'])


if __name__ == '__main__':
    unittest.main()
