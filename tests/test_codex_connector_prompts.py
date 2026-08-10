import unittest
from pathlib import Path


class CodexConnectorPromptContractTests(unittest.TestCase):
    def test_shadow_prompts_use_connector_request_correlation_without_tokens(self):
        cases = (
            ("codex_morning_prompt.md", "morning"),
            ("codex_afternoon_prompt.md", "afternoon"),
        )
        for filename, mode in cases:
            text = (Path("stock_report/prompts") / filename).read_text(encoding="utf-8")
            self.assertIn("GitHub 连接器", text)
            self.assertIn(f"stock_report/triggers/{mode}.json", text)
            self.assertIn("fetch_file", text)
            self.assertIn("update_file", text)
            self.assertIn("request_id", text)
            self.assertIn("requested_at", text)
            self.assertIn("每 15 秒", text)
            self.assertIn("最多 8 分钟", text)
            self.assertIn("orchestration_request.request_id", text)
            self.assertIn(f"stock_report/data/shadow/{mode}_analysis_candidate.json", text)
            self.assertNotIn("GH_PAT", text)
            self.assertNotIn("GITHUB_TOKEN", text)
            self.assertNotIn("/tmp/orchestration.py", text)
            self.assertNotIn(f"stock_report/data/{mode}_analysis_candidate.json", text)


if __name__ == "__main__":
    unittest.main()
