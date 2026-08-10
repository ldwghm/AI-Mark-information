import unittest
from pathlib import Path


class PromptContractTests(unittest.TestCase):
    def test_production_prompts_publish_candidate_not_final_analysis(self):
        cases = (
            ('morning_prompt.md', 'morning'),
            ('afternoon_prompt.md', 'afternoon'),
        )
        for filename, mode in cases:
            text = (Path('stock_report/prompts') / filename).read_text(encoding='utf-8')
            self.assertIn('/tmp/orchestration.py', text)
            self.assertIn('request_id', text)
            self.assertIn(f'{mode}_analysis_candidate.json', text)
            self.assertNotIn(
                f"commit('stock_report/data/{mode}_analysis.json'",
                text,
            )
            self.assertIn('thesis_updates', text)
            self.assertIn('reflection', text)

    def test_codex_prompts_are_explicitly_shadow_only(self):
        for filename in ('codex_morning_prompt.md', 'codex_afternoon_prompt.md'):
            text = (Path('stock_report/prompts') / filename).read_text(encoding='utf-8')
            self.assertIn('影子', text)
            self.assertIn('不触发发信', text)


if __name__ == '__main__':
    unittest.main()
