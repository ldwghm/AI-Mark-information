import unittest
from pathlib import Path

from stock_report.verify import verdict_path_for


class VerifyPathTests(unittest.TestCase):
    def test_candidate_verdict_never_overwrites_candidate(self):
        candidate = Path("stock_report/data/morning_analysis_candidate.json")
        self.assertEqual(
            verdict_path_for(candidate),
            Path("stock_report/data/morning_analysis_candidate_verdict.json"),
        )


if __name__ == "__main__":
    unittest.main()
