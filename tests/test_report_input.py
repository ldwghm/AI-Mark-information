import json
import tempfile
import unittest
from pathlib import Path

from stock_report.report_input import load_json_input


class ReportInputTests(unittest.TestCase):
    def test_local_file_takes_priority_over_remote_loader(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            local = Path(tmp) / "candidate.json"
            local.write_text(json.dumps({"source": "candidate"}), encoding="utf-8")

            result = load_json_input(
                local,
                remote_loader=lambda _: self.fail("remote loader must not be called"),
                remote_path="stock_report/data/old.json",
            )

        self.assertEqual({"source": "candidate"}, result)

    def test_missing_local_file_uses_remote_loader(self):
        result = load_json_input(
            "does-not-exist.json",
            remote_loader=lambda path: {"source": path},
            remote_path="stock_report/data/final.json",
        )

        self.assertEqual(
            {"source": "stock_report/data/final.json"},
            result,
        )

    def test_invalid_local_json_raises_instead_of_silently_using_old_remote_data(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            local = Path(tmp) / "candidate.json"
            local.write_text("{broken", encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                load_json_input(
                    local,
                    remote_loader=lambda _: {"source": "stale"},
                    remote_path="stock_report/data/final.json",
                )


if __name__ == "__main__":
    unittest.main()
