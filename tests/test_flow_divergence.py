"""价格与主力资金背离。

阈值是 2026-08-13 快照 130 只样本标定的（f184 中位 +7.2%、p10 −0.5%），
不是普适常数——所以测试里也把它当参数测，不当常量信。

最要紧的一条不变式：**"检测不到"和"没有"必须分得开**。板块榜单只取涨幅
前列时整份快照一只下跌股都没有，此时"逆势承接 0 条"是取数口径造成的，
把它渲染成"今日无逆势承接"就是撒谎。
"""
import unittest

from stock_report import flow_divergence as FD


def row(code='300308', name='中际旭创', chg=5.0, flow_pct=-3.0,
        amount=-1e8, super_amt=-5e7, turnover=8.0):
    return {'f12': code, 'f14': name, 'f3': chg, 'f184': flow_pct,
            'f62': amount, 'f66': super_amt, 'f8': turnover}


class ClassifyTests(unittest.TestCase):
    def test_rising_on_outflow_is_distribution(self):
        hit = FD.classify(row(chg=7.12, flow_pct=-8.87))
        self.assertEqual(hit['kind'], FD.DISTRIBUTION)
        self.assertEqual(hit['label'], '涨但大额资金净流出')

    def test_falling_on_inflow_is_accumulation(self):
        hit = FD.classify(row(chg=-5.0, flow_pct=4.0, amount=1e8, super_amt=5e7))
        self.assertEqual(hit['kind'], FD.ACCUMULATION)

    def test_agreement_between_price_and_flow_is_not_a_signal(self):
        self.assertIsNone(FD.classify(row(chg=7.0, flow_pct=8.0)))
        self.assertIsNone(FD.classify(row(chg=-7.0, flow_pct=-8.0)))

    def test_small_move_is_below_threshold(self):
        self.assertIsNone(FD.classify(row(chg=1.0, flow_pct=-9.0)))

    def test_small_flow_is_below_threshold(self):
        self.assertIsNone(FD.classify(row(chg=9.0, flow_pct=-0.2)))

    def test_thresholds_are_parameters_not_constants(self):
        r = row(chg=1.5, flow_pct=-0.6)
        self.assertIsNone(FD.classify(r))
        self.assertIsNotNone(FD.classify(r, chg_threshold=1.0, flow_threshold=0.5))

    def test_super_order_disagreement_is_flagged(self):
        """主力净流出但超大单净流入——合计口径内部就不一致，信号该降级。"""
        hit = FD.classify(row(chg=5.0, flow_pct=-3.0, super_amt=+2e7))
        self.assertIs(hit['super_agrees'], False)

    def test_super_order_agreement_is_flagged(self):
        self.assertIs(FD.classify(row(chg=5.0, flow_pct=-3.0, super_amt=-2e7))['super_agrees'],
                      True)

    def test_missing_super_order_is_unknown_not_false(self):
        r = row()
        r.pop('f66')
        self.assertIsNone(FD.classify(r)['super_agrees'])

    def test_missing_fields_yield_no_signal(self):
        self.assertIsNone(FD.classify({'f12': 'x'}))
        self.assertIsNone(FD.classify({}))
        self.assertIsNone(FD.classify(None))

    def test_non_numeric_fields_are_ignored(self):
        self.assertIsNone(FD.classify({'f3': '-', 'f184': -9.0}))

    def test_strength_is_the_absolute_flow_share(self):
        self.assertAlmostEqual(FD.classify(row(chg=5.0, flow_pct=-11.24))['strength'], 11.24)


class ScanTests(unittest.TestCase):
    def test_results_are_sorted_by_strength(self):
        rows = [row(code='A', flow_pct=-2.0), row(code='B', flow_pct=-11.0),
                row(code='C', flow_pct=-6.0)]
        self.assertEqual([h['code'] for h in FD.scan(rows)], ['B', 'C', 'A'])

    def test_duplicate_codes_keep_the_strongest(self):
        rows = [row(code='A', flow_pct=-2.0), row(code='A', flow_pct=-9.0)]
        hits = FD.scan(rows)
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0]['main_net_pct'], -9.0)

    def test_limit_truncates(self):
        rows = [row(code=str(i), flow_pct=-(i + 2)) for i in range(6)]
        self.assertEqual(len(FD.scan(rows, limit=3)), 3)

    def test_empty_input(self):
        self.assertEqual(FD.scan([]), [])
        self.assertEqual(FD.scan(None), [])


class CollectRowsTests(unittest.TestCase):
    def test_all_three_sources_are_merged_and_deduped(self):
        snap = {
            'board_stocks': [{'stocks': [row(code='A'), row(code='B')]}],
            'board_laggards': [{'stocks': [row(code='C', chg=-5.0)]}],
            'capital_flow_top30': [row(code='A'), row(code='D')],
        }
        self.assertEqual({r['f12'] for r in FD.collect_rows(snap)}, {'A', 'B', 'C', 'D'})

    def test_board_stocks_win_over_later_sources_for_the_same_code(self):
        snap = {'board_stocks': [{'stocks': [row(code='A', chg=9.0)]}],
                'capital_flow_top30': [row(code='A', chg=1.0)]}
        self.assertEqual(FD.collect_rows(snap)[0]['f3'], 9.0)

    def test_missing_keys_are_tolerated(self):
        self.assertEqual(FD.collect_rows({}), [])
        self.assertEqual(FD.collect_rows(None), [])


class AnalyseTests(unittest.TestCase):
    def test_the_two_directions_are_reported_separately(self):
        snap = {'board_stocks': [{'stocks': [
            row(code='A', chg=7.0, flow_pct=-6.0),
            row(code='B', chg=-7.0, flow_pct=6.0, amount=1e8, super_amt=5e7)]}]}
        out = FD.analyse(snap)
        self.assertEqual([h['code'] for h in out['distribution']], ['A'])
        self.assertEqual([h['code'] for h in out['accumulation']], ['B'])

    def test_a_sample_without_decliners_says_accumulation_is_undetectable(self):
        """08-13 快照就是这样：130 只样本涨跌幅最小 +0.9%。"""
        snap = {'board_stocks': [{'stocks': [row(code='A', chg=7.0, flow_pct=-6.0),
                                             row(code='B', chg=2.0, flow_pct=5.0)]}]}
        out = FD.analyse(snap)
        self.assertFalse(out['accumulation_detectable'])
        self.assertEqual(out['accumulation'], [])

    def test_a_sample_with_decliners_says_detectable_even_when_none_are_found(self):
        """今天真的一条都没有 —— 这和'看不见'是两件事。"""
        snap = {'board_stocks': [{'stocks': [row(code='A', chg=7.0, flow_pct=-6.0)]}],
                'board_laggards': [{'stocks': [row(code='B', chg=-5.0, flow_pct=-9.0)]}]}
        out = FD.analyse(snap)
        self.assertTrue(out['accumulation_detectable'])
        self.assertEqual(out['accumulation'], [])

    def test_thresholds_and_caveat_ride_along_for_the_renderer(self):
        out = FD.analyse({'board_stocks': []})
        self.assertEqual(out['thresholds']['chg_pct'], FD.CHG_THRESHOLD)
        self.assertIn('单笔成交金额', out['caveat'])

    def test_scanned_count_is_the_deduped_universe(self):
        snap = {'board_stocks': [{'stocks': [row(code='A'), row(code='A')]}]}
        self.assertEqual(FD.analyse(snap)['scanned'], 1)


class RealSnapshotTests(unittest.TestCase):
    PATH = 'stock_report/data/archive/2026-08-13/morning/latest.json'

    def test_the_2026_08_13_snapshot_finds_the_known_cases(self):
        import json
        try:
            with open(self.PATH, encoding='utf-8') as fh:
                snap = json.load(fh)
        except (OSError, ValueError):
            self.skipTest('归档不可用')
        out = FD.analyse(snap)
        names = [h['name'] for h in out['distribution']]
        # 太极实业：涨 7.12%、主力净流出 9.76 亿、超大单流出 5.66 亿、换手 24%
        self.assertIn('太极实业', names)
        self.assertIn('晶升股份', names)
        # 这份快照没有 board_laggards，另一半必须报"不可检出"
        self.assertFalse(out['accumulation_detectable'])


if __name__ == '__main__':
    unittest.main()
