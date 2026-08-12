"""外围指数行滞后一个交易日：抓数端算出来的 row_stale 必须真的被用上。

2026-08-12 早报快照实测：港股个股是 8/11，而 ^HSI/^HSCE 是 8/10；
韩股个股 8/11 而 ^KS11 是 8/10；台股个股 8/11 而 ^TWII 是 8/10。
global_markets.py 逐行标了 row_stale、汇总了 stale_rows，然后
cloud_fetch 只 print 一行日志——verify 从不读，渲染端也不读。
唯一挡在陈旧指数和邮件之间的是模型自觉，那不是控制。
"""
import unittest

import report_renderer as rr
from stock_report import quality


def _latest(**overrides):
    latest = {
        'global_markets': {'markets': {
            'HK': {'market_date': '2026-08-11', 'indices': [
                {'code': '^HSI', 'name': '恒生指数', 'chg': 1.05,
                 'market_date': '2026-08-10', 'row_stale': True},
                {'code': '^HSCE', 'name': '恒生中国企业', 'chg': 1.06,
                 'market_date': '2026-08-10', 'row_stale': True}]},
            'TW': {'market_date': '2026-08-11', 'indices': [
                {'code': '^TWII', 'name': '台湾加权', 'chg': 1.59,
                 'market_date': '2026-08-10', 'row_stale': True}]},
            'US': {'market_date': '2026-08-11', 'indices': [
                {'code': '^GSPC', 'name': '标普500', 'chg': -0.32,
                 'market_date': '2026-08-11', 'row_stale': False}]},
        }}}
    latest.update(overrides)
    return latest


class StaleRowDetectionTests(unittest.TestCase):
    def test_finds_exactly_the_rows_the_fetcher_flagged(self):
        rows = quality.stale_index_rows(_latest())
        self.assertEqual({r['code'] for r in rows}, {'^HSI', '^HSCE', '^TWII'})
        self.assertNotIn('^GSPC', {r['code'] for r in rows})

    def test_clean_snapshot_passes(self):
        clean = {'global_markets': {'markets': {'US': {
            'market_date': '2026-08-11',
            'indices': [{'code': '^GSPC', 'name': '标普500', 'chg': -0.32,
                         'market_date': '2026-08-11', 'row_stale': False}]}}}}
        level, reason, detail = quality.evaluate_global_index_staleness(clean, {})
        self.assertEqual(level, quality.PASS)
        self.assertEqual(detail['stale_rows'], [])

    def test_missing_global_markets_does_not_explode(self):
        for empty in ({}, {'global_markets': None},
                      {'global_markets': {'markets': None}},
                      {'global_markets': {'markets': {'HK': None}}}):
            level, _, detail = quality.evaluate_global_index_staleness(empty, {})
            self.assertEqual(level, quality.PASS)
            self.assertEqual(detail['misattributed'], [])


class MisattributionTests(unittest.TestCase):
    def test_citing_the_stale_number_as_today_is_a_hard_failure(self):
        analysis = {'hk_us_summary': '港股今日走强，恒生指数涨1.05%，科网股普涨。'}
        level, reason, detail = quality.evaluate_global_index_staleness(
            _latest(), analysis)
        self.assertEqual([r['code'] for r in detail['misattributed']], ['^HSI'])
        self.assertIn('当作当日数据引用', reason)

    def test_dating_the_number_clears_it(self):
        """2026-08-11 早报的真实写法——标注了时点，不该被误判。"""
        analysis = {'hk_us_summary':
                    '【港股·最近有效时点2026-08-10收盘】恒生指数涨1.05%、'
                    '恒生科技指数涨1.26%，科网股与黄金股普涨。'}
        level, reason, detail = quality.evaluate_global_index_staleness(
            _latest(), analysis)
        self.assertEqual(detail['misattributed'], [])
        self.assertEqual(level, quality.DEGRADE)
        self.assertIn('滞后一个交易日', reason)

    def test_declaring_it_unavailable_clears_it(self):
        """2026-08-12 早报的真实写法。"""
        analysis = {'risk_warnings': [
            '恒生指数（^HSI，+1.05%）的 market_date 为 2026-08-10，'
            '8/11 的港/韩/台指数涨跌幅在本期为 unavailable。']}
        _, _, detail = quality.evaluate_global_index_staleness(_latest(), analysis)
        self.assertEqual(detail['misattributed'], [])

    def test_mentioning_the_index_without_its_number_is_not_a_hit(self):
        analysis = {'market_summary': '恒生指数方向以个股为准，8 只科网股全跌。'}
        _, _, detail = quality.evaluate_global_index_staleness(_latest(), analysis)
        self.assertEqual(detail['misattributed'], [])

    def test_a_different_index_number_nearby_is_not_a_hit(self):
        """+1.59% 是台湾加权的数字，出现在恒生附近不该算恒生被误引。"""
        analysis = {'hk_us_summary': '恒生指数方向存疑；台湾加权'
                                     '（最近有效时点2026-08-10）涨1.59%。'}
        _, _, detail = quality.evaluate_global_index_staleness(_latest(), analysis)
        self.assertEqual(detail['misattributed'], [])


class VerdictAndBadgeTests(unittest.TestCase):
    def test_renderer_surfaces_stale_indices_as_a_badge(self):
        analysis = {'market_summary': '指数强、AI链弱的背离延续。'}
        html = rr.render_morning_report(_latest(), analysis, '2026-08-12')
        self.assertIn('滞后 1 个交易日', html)
        self.assertIn('恒生指数', html)

    def test_no_badge_when_nothing_is_stale(self):
        self.assertEqual(rr._stale_index_names({}), [])
        self.assertEqual(rr._stale_index_names(
            {'global_markets': {'markets': {'US': {'indices': [
                {'code': '^GSPC', 'row_stale': False}]}}}}), [])


if __name__ == '__main__':
    unittest.main()
