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
            'afternoon', latest_with(50, 50), {'date': '2026-08-10'},
            today='2026-08-10')
        self.assertEqual(level, quality.PASS)
        self.assertIsNone(prior)

    def test_stale_morning_analysis_blocks_and_marks_pending(self):
        # 实测故障：午报当天早报 final 还停在 8 月 4 日
        level, reason, prior = quality.evaluate_continuity(
            'afternoon', latest_with(50, 50), {'date': '2026-08-04'},
            today='2026-08-10')
        self.assertEqual(level, quality.BLOCK)
        self.assertEqual(prior, 'pending')
        self.assertIn('2026-08-04', reason)

    def test_missing_morning_analysis_blocks(self):
        level, _, prior = quality.evaluate_continuity(
            'afternoon', latest_with(50, 50), {}, today='2026-08-10')
        self.assertEqual(level, quality.BLOCK)
        self.assertEqual(prior, 'pending')


class DataCurrencyTests(unittest.TestCase):
    """午报数据必须是当日的——和闭环是两码事。

    线上实测：一次午报提交了 08-10 遗留的 latest（fetch_time 无时区、
    provenance 为空，说明 cloud_fetch 没重新生成），覆盖率只剩 45%。
    """

    def test_same_day_data_passes(self):
        level, _ = quality.evaluate_data_currency(
            'afternoon', latest_with(50, 50), today='2026-08-10')
        self.assertEqual(level, quality.PASS)

    def test_yesterday_data_blocks(self):
        latest = latest_with(50, 50)          # expected_data_date = 2026-08-10
        level, reason = quality.evaluate_data_currency(
            'afternoon', latest, today='2026-08-11')
        self.assertEqual(level, quality.BLOCK)
        self.assertIn('2026-08-10', reason)
        self.assertIn('非当日', reason)

    def test_missing_expected_date_degrades(self):
        latest = latest_with(50, 50)
        latest.pop('expected_data_date')
        latest['data_freshness'].pop('expected_date')
        level, _ = quality.evaluate_data_currency(
            'afternoon', latest, today='2026-08-10')
        self.assertEqual(level, quality.DEGRADE)

    def test_morning_mode_is_exempt(self):
        level, _ = quality.evaluate_data_currency(
            'morning', latest_with(50, 50), today='2026-08-11')
        self.assertEqual(level, quality.PASS)


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

    def test_snapshot_behind_live_market_cannot_claim_realtime(self):
        # 盘中市场已经走出新价，我们手上还是 40 分钟前的快照 -> 不能叫实时
        latest = latest_with(50, 50)
        latest['data_quality']['provenance'] = {'seconds_behind_market': 2400}
        level, reason = quality.evaluate_realtime_claims(
            latest, {'market_summary': '上证指数实时报3966点'}, mode='afternoon')
        self.assertEqual(level, quality.DEGRADE)
        self.assertIn('40 分钟', reason)

    def test_closing_price_after_close_may_claim_realtime(self):
        # 关键区分：收盘价距此刻好几个小时，但市场再没有更新的数据了
        latest = latest_with(50, 50)
        latest['data_quality']['provenance'] = {
            'max_stale_seconds': 6073.2,       # 距此刻 1.7 小时
            'seconds_behind_market': 0.0,      # 但就是最新可得
        }
        level, _ = quality.evaluate_realtime_claims(
            latest, {'market_summary': '上证指数实时报3966点'}, mode='afternoon')
        self.assertEqual(level, quality.PASS)

    def test_fresh_intraday_snapshot_may_claim_realtime(self):
        latest = latest_with(50, 50)
        latest['data_quality']['provenance'] = {'seconds_behind_market': 120}
        level, _ = quality.evaluate_realtime_claims(
            latest, {'market_summary': '上证指数实时报3966点'}, mode='afternoon')
        self.assertEqual(level, quality.PASS)

    def test_no_realtime_wording_never_trips_the_gate(self):
        latest = latest_with(50, 50)
        latest['data_freshness']['stale_quote_count'] = 9
        latest['data_quality']['provenance'] = {'seconds_behind_market': 99999}
        level, _ = quality.evaluate_realtime_claims(
            latest, {'market_summary': '上证指数收报3966点（8月10日收盘）'}, mode='afternoon')
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
