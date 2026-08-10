import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_report.pipeline_state import (
    archive_bundle,
    archive_relative_dir,
    build_delivery_state,
)


class PipelineStateTests(unittest.TestCase):
    def test_archive_path_is_mode_and_date_scoped(self):
        self.assertEqual(
            archive_relative_dir("morning", "2026-08-10"),
            Path("stock_report/data/archive/2026-08-10/morning"),
        )

    def test_delivery_state_records_verification_and_email_id(self):
        state = build_delivery_state(
            mode="afternoon",
            report_date="2026-08-10",
            email_id="email-123",
            sent_at="2026-08-10T06:03:00Z",
            verify_exit_code=0,
        )
        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["email_id"], "email-123")
        self.assertEqual(state["verify_exit_code"], 0)

    def test_archive_bundle_uses_stable_names_and_hash_manifest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = {}
            for key in ("latest", "analysis", "verdict", "html", "delivery"):
                path = root / f"source-{key}.txt"
                path.write_text(key, encoding="utf-8")
                sources[key] = path

            archive = archive_bundle(root, "morning", "2026-08-10", sources)

            self.assertEqual((archive / "latest.json").read_text(), "latest")
            self.assertEqual((archive / "analysis.json").read_text(), "analysis")
            self.assertEqual((archive / "report.html").read_text(), "html")
            manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], "morning")
            self.assertEqual(set(manifest["files"]), {
                "latest.json", "analysis.json", "verdict.json", "report.html", "delivery.json"
            })


if __name__ == "__main__":
    unittest.main()
