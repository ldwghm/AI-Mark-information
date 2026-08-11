"""2026-08-11 午报的回归用例。

那天四道门槛全判 PASS，而数据是：watchlist_coverage=51/51（100%）、
by_source={klines_cache:50, efinance_backfill:1}、活数据 0 行、
seconds_behind_market=84411.8（23.4 小时）、crosscheck 报 0 冲突 0.0%。

覆盖率只回答"有没有数字"，活性才回答"是不是今天的数字"；
交叉验证的"0 冲突"在没有第二个源时是假安慰。这两件事都在这里钉住。
"""
import unittest

from stock_report import crosscheck, quality


def rows(live=0, fallback=51):
    out = []
    for i in range(live):
        out.append({'code': f'{600000 + i}', 'chg_pct': 1.0,
                    'source': 'sina', 'is_fallback': False})
    for i in range(fallback):
        out.append({'code': f'{700000 + i}', 'chg_pct': 1.0,
                    'source': 'klines_cache', 'is_fallback': True})
    return out


def latest(live=0, fallback=51, intraday=True):
    data = {
        'expected_data_date': '2026-08-11',
        'watchlist_technicals': rows(live, fallback),
        'data_quality': {'watchlist_coverage': f'{live + fallback}/{live + fallback}'},
        'data_freshness': {'expected_date': '2026-08-11', 'stale_quote_count': 0},
    }
    if intraday:
        data['capital_flow_top30_rt'] = [{'f12': '300502', 'f2': 416.34, 'f3': 4.19}]
        data['ai_boards_rt'] = [{'f14': '算力概念', 'f3': 0.29}]
    return data


class LivenessGateTests(unittest.TestCase):
    def test_the_2026_08_11_case_no_longer_passes_silently(self):
        # 当天的真实形状：51 行全回填，但板块与资金流是今日的
        level, reason = quality.evaluate_liveness('afternoon', latest())
        self.assertEqual(level, quality.DEGRADE)
        self.assertIn('0 条当日实时报价', reason)

    def test_coverage_still_reports_a_perfect_score_on_that_data(self):
        # 说明为什么必须单独有活性门槛：覆盖率对 fallback 完全免疫
        cov_level, cov_reason = quality.evaluate_coverage(latest())
        self.assertEqual(cov_level, quality.PASS)
        self.assertIn('100%', cov_reason)

    def test_no_live_rows_and_no_intraday_layer_blocks(self):
        level, reason = quality.evaluate_liveness('afternoon', latest(intraday=False))
        self.assertEqual(level, quality.BLOCK)
        self.assertIn('无任何当日数据', reason)

    def test_minority_live_rows_degrade(self):
        level, reason = quality.evaluate_liveness('afternoon', latest(live=10, fallback=41))
        self.assertEqual(level, quality.DEGRADE)
        self.assertIn('10/51', reason)

    def test_mostly_live_passes(self):
        level, _ = quality.evaluate_liveness('afternoon', latest(live=48, fallback=3))
        self.assertEqual(level, quality.PASS)

    def test_morning_is_exempt_because_close_is_the_correct_basis(self):
        level, _ = quality.evaluate_liveness('morning', latest())
        self.assertEqual(level, quality.PASS)

    def test_empty_universe_blocks(self):
        level, _ = quality.evaluate_liveness('afternoon', {'watchlist_technicals': []})
        self.assertEqual(level, quality.BLOCK)

    def test_count_live_rows(self):
        self.assertEqual(quality.count_live_rows(latest(live=7, fallback=44)), (7, 51))


class UncheckedCrosscheckTests(unittest.TestCase):
    def test_zero_pairs_is_not_reported_as_agreement(self):
        summary = crosscheck.summarize([], checked_pairs=0)
        self.assertEqual(summary['status'], 'unchecked')
        self.assertIsNone(summary['max_diff_pct'])   # 关键：不是 0.0
        self.assertIn('未做交叉验证', summary['note'])

    def test_checked_and_agreed_is_distinguishable(self):
        summary = crosscheck.summarize([], checked_pairs=14)
        self.assertEqual(summary['status'], 'agreed')
        self.assertEqual(summary['max_diff_pct'], 0.0)

    def test_checked_with_conflicts(self):
        summary = crosscheck.summarize([{'code': '600522', 'diff_pct': 3.0}], checked_pairs=14)
        self.assertEqual(summary['status'], 'conflict')
        self.assertEqual(summary['max_diff_pct'], 3.0)

    def test_count_checked_pairs_needs_both_sides(self):
        primary = {'sh600522': {'price': 100.0}, 'sh000001': {'price': 3956.0}}
        secondary = {'sh600522': {'price': 100.1}}
        self.assertEqual(
            crosscheck.count_checked_pairs(primary, secondary, {'600522', '000001'}), 1)

    def test_count_checked_pairs_zero_when_no_secondary(self):
        self.assertEqual(
            crosscheck.count_checked_pairs({'sh600522': {'price': 100.0}}, {}, {'600522'}), 0)


if __name__ == '__main__':
    unittest.main()
