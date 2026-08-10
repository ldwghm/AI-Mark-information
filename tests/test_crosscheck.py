import unittest

from stock_report import crosscheck


class TargetSelectionTests(unittest.TestCase):
    def test_always_includes_four_indices(self):
        targets = crosscheck.select_crosscheck_targets({})
        self.assertTrue(set(crosscheck.INDEX_CODES).issubset(targets))

    def test_picks_top_movers_by_absolute_change(self):
        latest = {'watchlist_technicals': [
            {'code': '600001', 'chg_pct': 0.1},
            {'code': '600002', 'chg_pct': -9.8},
            {'code': '600003', 'chg_pct': 5.2},
        ]}
        targets = crosscheck.select_crosscheck_targets(latest, top_movers=2)
        self.assertIn('600002', targets)   # 跌幅最大
        self.assertIn('600003', targets)
        self.assertNotIn('600001', targets)

    def test_includes_highlights_and_sector_leaders(self):
        latest = {'sectors': [{'leader': {'code': '300001'}, 'laggard': {'code': '300002'}}]}
        targets = crosscheck.select_crosscheck_targets(latest, highlight_codes=['688981'])
        self.assertIn('688981', targets)
        self.assertIn('300001', targets)
        self.assertIn('300002', targets)


class ComparisonTests(unittest.TestCase):
    def test_agreeing_sources_yield_no_conflict(self):
        self.assertIsNone(crosscheck.compare_quotes(
            '600522', {'price': 100.0, 'src': 'sina'}, {'price': 100.2, 'src': 'tencent'}))

    def test_disagreeing_sources_flagged(self):
        conflict = crosscheck.compare_quotes(
            '600522', {'price': 100.0, 'src': 'sina'}, {'price': 103.0, 'src': 'tencent'})
        self.assertIsNotNone(conflict)
        self.assertAlmostEqual(conflict['diff_pct'], 3.0, places=3)
        self.assertEqual(conflict['primary_source'], 'sina')
        self.assertEqual(conflict['secondary_source'], 'tencent')

    def test_missing_secondary_is_not_a_conflict(self):
        self.assertIsNone(crosscheck.compare_quotes('600522', {'price': 100.0}, None))

    def test_zero_price_is_not_a_conflict(self):
        self.assertIsNone(crosscheck.compare_quotes(
            '600522', {'price': 0}, {'price': 100.0}))


class CrossValidateTests(unittest.TestCase):
    def test_matches_prefixed_and_bare_codes(self):
        primary = {'sh600522': {'price': 100.0, 'src': 'sina'}}
        secondary = {'sh600522': {'price': 105.0, 'src': 'tencent'}}
        conflicts = crosscheck.cross_validate(primary, secondary, {'600522'})
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]['code'], '600522')

    def test_results_sorted_by_severity(self):
        primary = {'sh000001': {'price': 100.0}, 'sh600522': {'price': 100.0}}
        secondary = {'sh000001': {'price': 101.0}, 'sh600522': {'price': 110.0}}
        conflicts = crosscheck.cross_validate(
            primary, secondary, {'000001', '600522'})
        self.assertEqual([c['code'] for c in conflicts], ['600522', '000001'])

    def test_summary_shape(self):
        summary = crosscheck.summarize([{'code': 'a', 'diff_pct': 4.0},
                                        {'code': 'b', 'diff_pct': 1.0}])
        self.assertEqual(summary['checked_conflicts'], 2)
        self.assertEqual(summary['max_diff_pct'], 4.0)

    def test_empty_summary(self):
        self.assertEqual(crosscheck.summarize([])['checked_conflicts'], 0)


if __name__ == '__main__':
    unittest.main()
