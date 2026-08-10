import unittest
from pathlib import Path


class FetchPushSafetyTests(unittest.TestCase):
    def test_fetch_workflows_rebase_before_pushing_concurrent_data_commits(self):
        for name in ("fetch-market-data.yml", "fetch-market-data-pm.yml"):
            text = (Path(".github/workflows") / name).read_text(encoding="utf-8")
            pull_position = text.find("git pull --rebase")
            push_position = text.find("git push")
            self.assertGreaterEqual(pull_position, 0)
            self.assertGreater(push_position, pull_position)


if __name__ == "__main__":
    unittest.main()
