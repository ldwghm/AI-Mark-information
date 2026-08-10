import unittest

from stock_report.health_check import evaluate_health


class HealthCheckTests(unittest.TestCase):
    def test_current_snapshot_and_delivery_are_healthy(self):
        result = evaluate_health(
            mode='morning',
            expected_date='2026-08-10',
            now='2026-08-10T02:00:00Z',
            latest={
                'report_type': 'morning',
                'fetch_date': '2026-08-10',
                'fetch_time': '2026-08-10T00:37:00',
            },
            delivery={'status': 'sent', 'mode': 'morning', 'report_date': '2026-08-10'},
        )
        self.assertTrue(result['healthy'])
        self.assertEqual(result['issues'], [])

    def test_missing_delivery_is_unhealthy(self):
        result = evaluate_health(
            mode='afternoon',
            expected_date='2026-08-10',
            now='2026-08-10T08:00:00Z',
            latest={
                'report_type': 'afternoon',
                'fetch_date': '2026-08-10',
                'fetch_time': '2026-08-10T06:30:00',
            },
            delivery=None,
        )
        self.assertFalse(result['healthy'])
        self.assertIn('delivery receipt is missing', result['issues'])

    def test_stale_snapshot_is_unhealthy(self):
        result = evaluate_health(
            mode='morning',
            expected_date='2026-08-10',
            now='2026-08-10T06:00:00Z',
            latest={
                'report_type': 'morning',
                'fetch_date': '2026-08-10',
                'fetch_time': '2026-08-10T00:00:00',
            },
            delivery={'status': 'sent', 'mode': 'morning', 'report_date': '2026-08-10'},
            max_age_hours=3,
        )
        self.assertFalse(result['healthy'])
        self.assertTrue(any('snapshot age' in issue for issue in result['issues']))


if __name__ == '__main__':
    unittest.main()
