import unittest

from stock_report import quality


def latest_with(coverage_priced, coverage_total, **extra):
    rows = [{'code': f'{600000 + i}', 'chg_pct': (1.0 if i < coverage_priced else None)}
            for i in range(coverage_total)]
    data = {
        'watchlist_technicals': rows,
        'expected_data_date': '2026-08-10',
        'data_quality': {'watchlist_coverage': f'{coverage_priced}/{coverage_total}'},
        'data_freshness': {'expected_date': '2026-08-10', 'stale_quote_count': 0},
    }
    data.update(extra)
    return data


class CoverageGateTests(unittest.TestCase):
    def test_full_coverage_passes(self):
        level, _ = quality.evaluate_coverage(latest_with(50, 50))
        self.assertEqual(level, quality.PASS)

    def test_below_ninety_percent_degrades(self):
        level, reason = quality.evaluate_coverage(latest_with(43, 50))  # 86%
        self.assertEqual(level, quality.DEGRADE)
        self.assertIn('降级线', reason)

    def test_below_seventy_percent_blocks(self):
        level, reason = quality.evaluate_coverage(latest_with(30, 50))  # 60%
        self.assertEqual(level, quality.BLOCK)
        self.assertIn('停发线', reason)

    def test_empty_universe_blocks(self):
        level, _ = quality.evaluate_coverage({'watchlist_technicals': [], 'data_quality': {}})
        self.assertEqual(level, quality.BLOCK)


class ContinuityGateTests(unittest.TestCase):
    def test_morning_mode_is_exempt(self):
        level, _, prior = quality.evaluate_continuity('morning', latest_with(50, 50), {})
        self.assertEqual(level, quality.PASS)
        self.assertIsNone(prior)

    def test_matching_dates_close_the_loop(self):
        level, _, prior = quality.evaluate_continuity(
            'afternoon', latest_with(50, 50), {'date': '2026-08-10'})
        self.assertEqual(level, quality.PASS)
        self.assertIsNone(prior)

    def test_stale_morning_analysis_blocks_and_marks_pending(self):
        # 实测故障：午报当天早报 final 还停在 8 月 4 日
        level, reason, prior = quality.evaluate_continuity(
            'afternoon', latest_with(50, 50), {'date': '2026-08-04'})
        self.assertEqual(level, quality.BLOCK)
        self.assertEqual(prior, 'pending')
        self.assertIn('2026-08-04', reason)

    def test_missing_morning_analysis_blocks(self):
        level, _, prior = quality.evaluate_continuity('afternoon', latest_with(50, 50), {})
        self.assertEqual(level, quality.BLOCK)
        self.assertEqual(prior, 'pending')


class RealtimeClaimTests(unittest.TestCase):
    def test_realtime_wording_with_stale_quotes_degrades(self):
        latest = latest_with(50, 50)
        latest['data_freshness']['stale_quote_count'] = 7
        level, reason = quality.evaluate_realtime_claims(
            latest, {'market_summary': '上证指数实时报3956点'})
        self.assertEqual(level, quality.DEGRADE)
        self.assertIn('实时', reason)

    def test_realtime_wording_without_stale_quotes_is_fine(self):
        level, _ = quality.evaluate_realtime_claims(
            latest_with(50, 50), {'market_summary': '上证指数实时报3956点'})
        self.assertEqual(level, quality.PASS)


class ExitCodeTests(unittest.TestCase):
    def test_block_maps_to_exit_three(self):
        self.assertEqual(quality.exit_code_for(quality.BLOCK), 3)

    def test_pass_and_degrade_still_send(self):
        self.assertEqual(quality.exit_code_for(quality.PASS), 0)
        self.assertEqual(quality.exit_code_for(quality.DEGRADE), 0)

    def test_combine_takes_strictest(self):
        self.assertEqual(
            quality.combine(quality.PASS, quality.DEGRADE, quality.BLOCK), quality.BLOCK)
        self.assertEqual(quality.combine(quality.PASS, quality.DEGRADE), quality.DEGRADE)


if __name__ == '__main__':
    unittest.main()
