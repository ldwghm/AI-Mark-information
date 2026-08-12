"""合并不得把当日盘中层换成昨收。

2026-08-12 午报实测：GitHub Actions 在 13:42 抓到了完整的当日盘中数据
（50/50 行 data_date=2026-08-12），但 realtime_indices / watchlist_rt /
sectors / index_5day_kline 都不在 MERGE_KEYS 里，合并后被 CCR 会话自己
那份 klines_cache 昨收盖掉：quote_source=none、fallback_rows=50。
当时靠模型自己核对 data_quality 才发现，手写 overlay 脚本救回来。
"""
import unittest

from stock_report import cloud_fetch


def _actions_snapshot():
    """Actions 那份的真实形状：行上只有 data_date，指数上只有 time。"""
    return {
        'fetch_date': '2026-08-12',
        'expected_data_date': '2026-08-12',
        'realtime_indices': {'sh000001': {
            'name': '上证指数', 'price': 3940.35, 'change_pct': 0.16,
            'time': '13:42:20', 'high': 3947.38, 'low': 3927.55}},
        'index_5day_kline': [{'d': 1}],
        'sectors': [{'sector': '光通信/CPO/光模块', 'avg_chg': 4.77}],
        'watchlist_rt': [
            {'code': '300308', 'name': '中际旭创', 'current': 917.68,
             'change_pct': 3.46, 'high': 936.8, 'low': 876.01, 'open': 880.13,
             'yesterday_close': 886.96, 'volume': 258531,
             'amount': 23607412328.83, 'data_date': '2026-08-12'}],
    }


def _cache_result():
    """CCR 连不上行情源时 cloud_fetch 自己产出的那份：昨收。"""
    return {
        'fetch_date': '2026-08-12',
        'realtime_indices': {'sh000001': {
            'name': '上证指数', 'price': 3934.09, 'change_pct': 0.0,
            'as_of': '2026-08-11T15:00:00+08:00'}},
        'sectors': [{'sector': '光通信/CPO/光模块', 'avg_chg': -1.0}],
        'watchlist_rt': [{'code': '300308', 'name': '中际旭创', 'current': 886.96,
                          'change_pct': 2.59, 'data_date': '2026-08-11',
                          'as_of': '2026-08-11T15:00:00+08:00'}],
        'watchlist_technicals': [{
            'code': '300308', 'name': '中际旭创', 'close': 886.96, 'chg_pct': 2.59,
            'open': None, 'high': None, 'low': None, 'prev_close': 864.58,
            'data_date': '2026-08-11', 'ma5': 914.83, 'ma20': 989.14,
            'source': 'klines_cache', 'is_fallback': True,
            'as_of': '2026-08-11T15:00:00+08:00', 'technicals_source': 'cache'}],
    }


class AsOfTests(unittest.TestCase):
    def test_reads_time_field_when_rows_carry_no_as_of(self):
        moment = cloud_fetch.intraday_as_of(_actions_snapshot())
        self.assertIsNotNone(moment)
        self.assertEqual(moment.strftime('%Y-%m-%d %H:%M'), '2026-08-12 13:42')

    def test_reads_row_as_of_when_present(self):
        moment = cloud_fetch.intraday_as_of(_cache_result())
        self.assertEqual(moment.strftime('%Y-%m-%d %H:%M'), '2026-08-11 15:00')

    def test_empty_snapshot_has_no_moment(self):
        self.assertIsNone(cloud_fetch.intraday_as_of({}))
        self.assertIsNone(cloud_fetch.intraday_as_of(
            {'watchlist_rt': ['not-a-dict'], 'realtime_indices': None}))


class IntradayMergeTests(unittest.TestCase):
    def test_the_2026_08_12_regression_todays_intraday_survives(self):
        result, old = _cache_result(), _actions_snapshot()
        source = cloud_fetch.apply_intraday_merge(result, old, 'afternoon')

        self.assertEqual(source, 'efinance@github_actions')
        self.assertEqual(result['watchlist_rt'][0]['current'], 917.68)
        self.assertEqual(result['realtime_indices']['sh000001']['price'], 3940.35)
        self.assertEqual(result['sectors'][0]['avg_chg'], 4.77)
        self.assertIn('index_5day_kline', result)

    def test_technicals_prices_follow_so_the_snapshot_stays_consistent(self):
        """只换 watchlist_rt 会造出「rt 是今日、technicals 是昨收」的矛盾快照——
        而 verify 的活性、覆盖率、provenance 读的都是 technicals。"""
        result, old = _cache_result(), _actions_snapshot()
        cloud_fetch.apply_intraday_merge(result, old, 'afternoon')

        tech = result['watchlist_technicals'][0]
        self.assertEqual(tech['close'], 917.68)
        self.assertEqual(tech['chg_pct'], 3.46)
        self.assertEqual(tech['high'], 936.8)
        self.assertEqual(tech['open'], 880.13)
        self.assertEqual(tech['data_date'], '2026-08-12')
        self.assertFalse(tech['is_fallback'])
        self.assertEqual(tech['source'], 'efinance@github_actions')
        # 指标仍来自缓存序列，必须留在行上
        self.assertEqual(tech['ma5'], 914.83)
        self.assertEqual(tech['technicals_source'], 'klines_cache')

    def test_liveness_gate_sees_the_repaired_snapshot_as_live(self):
        from stock_report import quality
        result, old = _cache_result(), _actions_snapshot()
        before = quality.count_live_rows(result)
        cloud_fetch.apply_intraday_merge(result, old, 'afternoon')
        after = quality.count_live_rows(result)
        self.assertEqual(before, (0, 1))     # 修好前：0 行实时
        self.assertEqual(after, (1, 1))      # 修好后：全部实时

    def test_older_merge_source_never_overwrites_fresher_local_data(self):
        """CCR 哪天能连上新浪，本地就是更新的那份——不能被昨天的盖掉。"""
        result = _cache_result()
        for row in result['watchlist_rt']:
            row.update(as_of='2026-08-12T13:55:00+08:00', current=920.0,
                       data_date='2026-08-12')
        result['watchlist_technicals'][0].update(close=920.0, is_fallback=False,
                                                 source='sina')
        source = cloud_fetch.apply_intraday_merge(result, _actions_snapshot(),
                                                  'afternoon')
        self.assertIsNone(source)
        self.assertEqual(result['watchlist_rt'][0]['current'], 920.0)
        self.assertEqual(result['watchlist_technicals'][0]['close'], 920.0)

    def test_morning_mode_has_no_intraday_layer(self):
        result = _cache_result()
        self.assertIsNone(cloud_fetch.apply_intraday_merge(
            result, _actions_snapshot(), 'morning'))
        self.assertEqual(result['watchlist_rt'][0]['current'], 886.96)

    def test_merge_source_without_the_layer_changes_nothing(self):
        result = _cache_result()
        self.assertIsNone(cloud_fetch.apply_intraday_merge(
            result, {'ai_boards': [1]}, 'afternoon'))

    def test_apply_merge_reports_the_source_up_to_data_quality(self):
        result = _cache_result()
        old = _actions_snapshot()
        old['ai_boards'] = [{'f14': '算力概念'}]
        source = cloud_fetch.apply_merge(result, old, 'afternoon')
        self.assertEqual(source, 'efinance@github_actions')
        self.assertEqual(result['ai_boards'], [{'f14': '算力概念'}])

    def test_quote_source_label_distinguishes_snapshot_from_backfill(self):
        """报成 efinance_backfill 会让人以为拿到的是昨收。"""
        import inspect
        src = inspect.getsource(cloud_fetch.main)
        self.assertIn("elif intraday_source:", src)
        self.assertIn("(盘中快照)", src)


if __name__ == '__main__':
    unittest.main()
