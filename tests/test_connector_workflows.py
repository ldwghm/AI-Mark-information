import unittest
from pathlib import Path


class ConnectorWorkflowContractTests(unittest.TestCase):
    def test_fetch_workflows_accept_mode_specific_connector_trigger_pushes(self):
        cases = (
            ("fetch-market-data.yml", "morning"),
            ("fetch-market-data-pm.yml", "afternoon"),
        )
        for name, mode in cases:
            text = (Path(".github/workflows") / name).read_text(encoding="utf-8")
            self.assertIn("push:", text)
            self.assertIn("branches: [main]", text)
            self.assertIn(f"- 'stock_report/triggers/{mode}.json'", text)
            self.assertIn("if: github.event_name == 'push'", text)
            self.assertIn("python -m stock_report.connector_trigger", text)
            self.assertIn(f"--mode {mode}", text)
            self.assertIn(f"--trigger stock_report/triggers/{mode}.json", text)
            self.assertIn('--trigger-commit-sha "$GITHUB_SHA"', text)


if __name__ == "__main__":
    unittest.main()
