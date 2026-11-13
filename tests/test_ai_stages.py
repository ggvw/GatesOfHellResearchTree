import unittest
from ai_stages import mask_lua_comments, parse_roster, stage_bound, extract_ai


class AiStagesTests(unittest.TestCase):
    def test_comments_nested_tables_and_exact_ids(self):
        warnings = []
        source = '''-- unit = "bad(sov)"
Purchases["conquest.sov"] = {{Units = {
 {base={"Tank", "Heavy"}, unit="tank_ai(sov)", effects={"brace }"}},
 --[[ {unit="commented(sov)"} ]]
 {base={'Infantry', 'Single'}, unit='single(sov)'}
}}}'''
        rows = parse_roster(source, 'test.lua', warnings.append)
        self.assertEqual([r['purchase_id'] for r in rows], ['tank_ai(sov)', 'single(sov)'])
        self.assertEqual(rows[0]['category'], 'Tank / Heavy')
        self.assertEqual(warnings, [])

    def test_unsupported_expression_retained(self):
        warnings = []
        rows = parse_roster('{unit=make_unit(), base={"Tank"}}', 'x', warnings.append)
        self.assertEqual(len(rows), 1)
        self.assertTrue(warnings)
        self.assertIn('unknown:', rows[0]['purchase_id'])

    def test_concatenation_is_not_a_literal_prefix(self):
        for expression in ['"tank" .. suffix', '"tank" + suffix', '42', '0x74']:
            with self.subTest(expression=expression):
                warnings = []
                rows = parse_roster('{unit=' + expression + ', base={"Tank"}}', 'x', warnings.append)
                self.assertEqual(len(rows), 1)
                self.assertTrue(rows[0]['purchase_id'].startswith('unknown:'))
                self.assertEqual(len(warnings), 1)

    def test_supported_string_escapes_and_rejected_escapes(self):
        for literal, expected in [(r'"ta\"nk(sov)"', 'ta"nk(sov)'),
                                  (r'"\116ank(sov)"', 'tank(sov)'),
                                  (r'"\x74ank(sov)"', 'tank(sov)')]:
            with self.subTest(literal=literal):
                warnings = []
                self.assertEqual(parse_roster('{unit=' + literal + '}', 'x', warnings.append)[0]['purchase_id'], expected)
                self.assertFalse(warnings)
        for literal in [r'"\999ank"', r'"\xQZank"', r'"\u{74}ank"', r'"\qank"']:
            warnings = []
            row = parse_roster('{unit=' + literal + '}', 'x', warnings.append)[0]
            self.assertTrue(row['purchase_id'].startswith('unknown:'))
            self.assertTrue(warnings)

    def test_long_strings_are_opaque_direct_fields(self):
        warnings = []
        self.assertEqual(parse_roster('{note=[[unit="ghost(sov)"]]}', 'x', warnings.append), [])
        source = '{note=[=[ } {unit="ghost(sov)"} ]=], nested={note=[[ { } unit="fake" ]]}, unit="real(sov)", base={"Tank"}}'
        rows = parse_roster(source, 'x', warnings.append)
        self.assertEqual([r['purchase_id'] for r in rows], ['real(sov)'])
        self.assertEqual(rows[0]['category'], 'Tank')
        self.assertEqual(parse_roster('{unit=[=[tank(sov)]=],base={[[Tank]]}}', 'x', warnings.append)[0]['purchase_id'], 'tank(sov)')
        self.assertEqual(parse_roster('{note="unit=ghost",base={"Tank"}}', 'x', warnings.append), [])
        self.assertFalse(warnings)

    def test_exact_record_survives_nested_macro_alias(self):
        from ai_stages import add_purchase_alias, sdl_definitions
        from export_research_trees import extract_named_blocks
        definitions = sdl_definitions('(define "squad" {"%name(%side)" {research_stage 1} {research_stage_max 99}})')
        invocation = '("squad" name(tank) side(sov))'
        source = '{"tank(sov)" ' + invocation + ' {research_stage_max 3}}'
        records = extract_named_blocks(source)
        exact = records['tank(sov)']
        add_purchase_alias(records, invocation, definitions)
        self.assertEqual(records['tank(sov)'], exact)
        self.assertEqual(stage_bound(records['tank(sov)'], 'max_stage', definitions)['value'], 3)
        self.assertEqual(stage_bound(invocation, 'max_stage', definitions)['value'], 99)
        # Static extraction precedence only; this fixture does not execute the engine.

    def test_bounds_not_invented(self):
        self.assertEqual(stage_bound('', 'max_stage')['state'], 'absent')
        self.assertEqual(stage_bound('max_stage(%max)', 'max_stage')['state'], 'unknown')
        self.assertEqual(stage_bound('min_stage(0) max_stage(99)', 'max_stage')['value'], 99)

    def test_emitted_id_and_literal_template_defaults(self):
        from ai_stages import sdl_definitions, emitted_purchase_id
        definitions = sdl_definitions('''(define "generic" {research_stage %r} {research_stage_max 99})
(define "squad" {"%name(%side)" ("generic" r(%min_stage))})''')
        block = '("squad" name(real_ai)side(sov)min_stage(4))'
        self.assertEqual(emitted_purchase_id(block, definitions), 'real_ai(sov)')
        self.assertEqual(stage_bound(block, 'min_stage', definitions)['value'], 4)
        self.assertEqual(stage_bound(block, 'max_stage', definitions)['value'], 99)
        self.assertEqual(stage_bound('("squad" name(x) side(sov))', 'min_stage', definitions)['state'], 'unknown')
        self.assertEqual(stage_bound('{research_stage 2}', 'max_stage', definitions)['state'], 'absent')
        self.assertEqual(stage_bound('{research_stage_max 0}', 'max_stage', definitions)['value'], 0)

    def test_long_comment_line_preservation(self):
        source = '--[=[ one\nunit="hidden" ]=]\n{unit="yes"}'
        self.assertEqual(mask_lua_comments(source).count('\n'), 2)
        self.assertEqual(parse_roster(source, 'x', print)[0]['line'], 3)

    def test_unclosed_table_is_error(self):
        with self.assertRaises(ValueError):
            parse_roster('{unit="x"', 'x', print)

    def test_actual_loader_shape_and_schedule_direction(self):
        class Data:
            files = {'script/multiplayer/bot.main.lua': 'require([[/script/multiplayer/modes/]] .. gameMode)',
                     'script/multiplayer/modes/conquest.lua': 'require([[/script/multiplayer/modes/utility]])\nOnGameStartUtility("conquest")',
                     'script/multiplayer/modes/utility.lua': '''MaxDivisionArmyCount= {Faction = {["sov"]=2}}
local division = math.random(1, upperLimit)
local purchasesModule = [[/script/multiplayer/units/]]''',
                     'script/multiplayer/units/sov/conquest.sov.1.lua': '{unit="a(sov)"}',
                     'set/dynamic_campaign/duration_short.set': '{ResearchStages "0:1 3:2"}'}
            def text(self, name): return self.files[name]
            def warn(self, message): pass
        result = extract_ai(Data(), 'sov')
        self.assertEqual(result['variants'], [1,2])
        self.assertEqual(len(result['records']), 1)
        self.assertIn('missing', result['warnings'][0])
        self.assertEqual(result['schedules']['short'][1], {'games_played':3, 'stage':2})


class InstalledPresetAiTests(unittest.TestCase):
    def test_effective_real_rosters(self):
        from pathlib import Path
        from game_data import GameData, preset_layers
        resource = Path('/run/media/wbw/Big Games/steamapps/common/Call to Arms - Gates of Hell/resource')
        config = Path.home()/'.goh-mod-manager/config.json'
        if not resource.is_dir() or not config.is_file():
            self.skipTest('local game and named preset not installed')
        layers = preset_layers(config, 'Hotmod 1968 (Ultrahotmod)')
        with GameData(resource, layers) as data:
            sov = extract_ai(data, 'sov')
            nat = extract_ai(data, 'nat')
            self.assertEqual(sov['variants'], [1,2,3,4,5])
            self.assertEqual(nat['variants'], [1,2,3,4,5,6,7])
            self.assertEqual(len(sov['records']), 1618)
            self.assertEqual(len({row['purchase_id'] for row in sov['records']}), 815)
            self.assertEqual(len(sov['schedules']), 5)
            self.assertTrue(any('_ai' in row['purchase_id'] for row in sov['records']))


if __name__ == '__main__':
    unittest.main()
