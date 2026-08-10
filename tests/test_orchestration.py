import unittest
from datetime import datetime, timezone

from stock_report.orchestration import evaluate_snapshot, select_workflow_run


class SelectWorkflowRunTests(unittest.TestCase):
    def test_ignores_old_completed_run_and_selects_matching_request(self):
        runs = [
            {
                "id": 10,
                "display_title": "morning fetch old-request",
                "head_branch": "main",
                "created_at": "2026-08-10T00:00:00Z",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 11,
                "display_title": "morning fetch req-123",
                "head_branch": "main",
                "created_at": "2026-08-10T00:30:05Z",
                "status": "in_progress",
                "conclusion": None,
            },
        ]

        selected = select_workflow_run(
            runs,
            request_id="req-123",
            ref="main",
            dispatched_at=datetime(2026, 8, 10, 0, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(11, selected["id"])

    def test_returns_none_when_only_old_run_exists(self):
        runs = [
            {
                "id": 10,
                "display_title": "morning fetch req-123",
                "head_branch": "main",
                "created_at": "2026-08-09T23:59:00Z",
                "status": "completed",
                "conclusion": "success",
            }
        ]

        selected = select_workflow_run(
            runs,
            request_id="req-123",
            ref="main",
            dispatched_at=datetime(2026, 8, 10, 0, 30, tzinfo=timezone.utc),
        )

        self.assertIsNone(selected)


class SnapshotFreshnessTests(unittest.TestCase):
    def test_accepts_snapshot_created_by_current_run(self):
        snapshot = {
            "fetch_time": "2026-08-10T00:37:03.382930",
            "report_type": "morning",
        }

        result = evaluate_snapshot(
            snapshot,
            expected_mode="morning",
            not_before=datetime(2026, 8, 10, 0, 36, tzinfo=timezone.utc),
            now=datetime(2026, 8, 10, 0, 38, tzinfo=timezone.utc),
            max_age_seconds=900,
        )

        self.assertTrue(result["fresh"])
        self.assertLess(result["age_seconds"], 60)

    def test_rejects_snapshot_older_than_current_dispatch(self):
        snapshot = {
            "fetch_time": "2026-08-07T01:52:49.715201",
            "report_type": "morning",
        }

        result = evaluate_snapshot(
            snapshot,
            expected_mode="morning",
            not_before=datetime(2026, 8, 10, 0, 30, tzinfo=timezone.utc),
            now=datetime(2026, 8, 10, 0, 38, tzinfo=timezone.utc),
            max_age_seconds=900,
        )

        self.assertFalse(result["fresh"])
        self.assertIn("before dispatch", result["reason"])

    def test_rejects_wrong_report_mode(self):
        snapshot = {
            "fetch_time": "2026-08-10T00:37:03Z",
            "report_type": "afternoon",
        }

        result = evaluate_snapshot(
            snapshot,
            expected_mode="morning",
            not_before=datetime(2026, 8, 10, 0, 30, tzinfo=timezone.utc),
            now=datetime(2026, 8, 10, 0, 38, tzinfo=timezone.utc),
            max_age_seconds=900,
        )

        self.assertFalse(result["fresh"])
        self.assertIn("report_type", result["reason"])


if __name__ == "__main__":
    unittest.main()
