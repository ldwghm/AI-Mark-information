import unittest

from stock_report.connector_trigger import stamp_snapshot


class ConnectorTriggerTests(unittest.TestCase):
    def test_stamps_exact_request_metadata_without_mutating_source(self):
        snapshot = {"report_type": "morning", "fetch_time": "2026-08-10T00:01:00Z"}
        trigger = {
            "schema_version": 1,
            "mode": "morning",
            "request_id": "codex-morning-20260810T000000Z-a1b2c3d4",
            "requested_at": "2026-08-10T00:00:00Z",
            "requested_by": "codex-scheduled",
        }

        stamped = stamp_snapshot(
            snapshot,
            trigger,
            expected_mode="morning",
            trigger_commit_sha="abc123",
        )

        self.assertNotIn("orchestration_request", snapshot)
        self.assertEqual(
            "codex-morning-20260810T000000Z-a1b2c3d4",
            stamped["orchestration_request"]["request_id"],
        )
        self.assertEqual("2026-08-10T00:00:00Z", stamped["orchestration_request"]["requested_at"])
        self.assertEqual("github_connector_push", stamped["orchestration_request"]["source"])
        self.assertEqual("abc123", stamped["orchestration_request"]["trigger_commit_sha"])

    def test_rejects_missing_request_id(self):
        trigger = {"mode": "morning", "requested_at": "2026-08-10T00:00:00Z"}

        with self.assertRaisesRegex(ValueError, "request_id"):
            stamp_snapshot({"report_type": "morning"}, trigger, expected_mode="morning")

    def test_rejects_trigger_for_wrong_mode(self):
        trigger = {
            "mode": "afternoon",
            "request_id": "codex-afternoon-20260810T060000Z-a1b2c3d4",
            "requested_at": "2026-08-10T06:00:00Z",
        }

        with self.assertRaisesRegex(ValueError, "mode"):
            stamp_snapshot({"report_type": "morning"}, trigger, expected_mode="morning")


if __name__ == "__main__":
    unittest.main()
