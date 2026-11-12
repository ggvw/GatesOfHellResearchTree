import unittest
from create_research_tree_html import set_hidden_factions


class HiddenFactionTests(unittest.TestCase):
    def test_exact_operator_selection_retains_fourteen(self):
        trees = [{'faction': faction} for faction in
                 'csa eng fin fra frg gdr ger isr nat pol prc rus sov usa'.split()]
        set_hidden_factions(trees, 'csa eng fin fra frg ger isr usa'.split())
        self.assertEqual(len(trees), 14)
        self.assertEqual([tree['faction'] for tree in trees if not tree['hidden_faction']],
                         'gdr nat pol prc rus sov'.split())
        other = [{'faction': 'csa'}]
        self.assertNotIn('hidden_faction', other[0])

    def test_reject_unknown_and_empty_selection(self):
        for excluded in [['typo'], ['fin']]:
            with self.subTest(excluded=excluded), self.assertRaises(ValueError):
                set_hidden_factions([{'faction': 'fin'}], excluded)
