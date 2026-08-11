import json
import unittest
from datetime import datetime, timezone

import pandas as pd

from stock_report import global_markets as gm


UNIVERSE = {
    'JP': {'name': '日股', 'timezone': 'Asia/Tokyo', 'close': '15:00',
           'indices': [['^N225', '日经225']],
           'stocks': [['8035.T', '东京电子'], ['6857.T', '爱德万测试']]},
    'US': {'name': '美股', 'timezone': 'America/New_York', 'close': '16:00',
           'indices': [['^SOX', '费城半导体']], 'stocks': [['NVDA', '英伟达']]},
}


def frame(dates, closes):
    return pd.DataFrame({'Close': closes}, index=pd.to_datetime(dates))


def fake_download(available):
    def download(_tickers):
        return lambda code: available.get(code)
    return download


class MarketCloseTests(unittest.TestCase):
    def test_tokyo_close_carries_jst_offset(self):
        self.assertEqual(gm.market_close_iso('2026-08-10', 'Asia/Tokyo', '15:00'),
                         '2026-08-10T15:00:00+09:00')

    def test_new_york_close_handles_dst(self):
        # 8 月是夏令时 -> -04:00；1 月是标准时 -> -05:00
        self.assertTrue(gm.market_close_iso('2026-08-10', 'America/New_York', '16:00')
                        .endswith('-04:00'))
        self.assertTrue(gm.market_close_iso('2026-01-12', 'America/New_York', '16:00')
                        .endswith('-05:00'))

    def test_taipei_half_day_close(self):
        self.assertEqual(gm.market_close_iso('2026-08-10', 'Asia/Taipei', '13:30'),
                         '2026-08-10T13:30:00+08:00')

    def test_bad_input_returns_none(self):
        self.assertIsNone(gm.market_close_iso('', 'Asia/Tokyo', '15:00'))
        self.assertIsNone(gm.market_close_iso('2026-08-10', 'Asia/Tokyo', 'noon'))


class ClassifyTests(unittest.TestCase):
    def test_recent_close_is_fresh(self):
        now = datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(gm.classify('2026-08-10T15:00:00+09:00', now), 'fresh')

    def test_old_close_is_stale(self):
        now = datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(gm.classify('2026-08-10T15:00:00+09:00', now), 'stale')

    def test_missing_is_unavailable(self):
        self.assertEqual(gm.classify(None), 'unavailable')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 11, 0, 30, tzinfo=timezone.utc)
        self.data = {
            '^N225': frame(['2026-08-07', '2026-08-10'], [42000.0, 42420.0]),
            '8035.T': frame(['2026-08-07', '2026-08-10'], [30000.0, 30900.0]),
            '6857.T': frame(['2026-08-07', '2026-08-10'], [9000.0, 8910.0]),
            '^SOX': frame(['2026-08-07', '2026-08-10'], [5000.0, 5100.0]),
            'NVDA': frame(['2026-08-07', '2026-08-10'], [220.0, 223.96]),
        }

    def test_each_market_gets_its_own_as_of(self):
        snap = gm.build_snapshot(fake_download(self.data), UNIVERSE, now=self.now)
        self.assertEqual(snap['markets']['JP']['as_of'], '2026-08-10T15:00:00+09:00')
        self.assertTrue(snap['markets']['US']['as_of'].endswith('-04:00'))

    def test_change_percent_computed_from_previous_close(self):
        snap = gm.build_snapshot(fake_download(self.data), UNIVERSE, now=self.now)
        nvda = snap['markets']['US']['stocks'][0]
        self.assertEqual(nvda['code'], 'NVDA')
        self.assertAlmostEqual(nvda['chg'], 1.8, places=1)

    def test_indices_and_stocks_are_separated(self):
        snap = gm.build_snapshot(fake_download(self.data), UNIVERSE, now=self.now)
        jp = snap['markets']['JP']
        self.assertEqual([i['code'] for i in jp['indices']], ['^N225'])
        self.assertEqual(len(jp['stocks']), 2)
        self.assertEqual(jp['coverage'], '3/3')

    def test_missing_ticker_lowers_coverage_not_crash(self):
        partial = dict(self.data)
        del partial['6857.T']
        snap = gm.build_snapshot(fake_download(partial), UNIVERSE, now=self.now)
        self.assertEqual(snap['markets']['JP']['coverage'], '2/3')
        self.assertEqual(snap['markets']['JP']['status'], 'fresh')

    def test_entirely_missing_market_is_unavailable(self):
        snap = gm.build_snapshot(fake_download({}), UNIVERSE, now=self.now)
        self.assertEqual(snap['markets']['JP']['status'], 'unavailable')
        self.assertEqual(snap['markets']['JP']['coverage'], '0/3')
        self.assertIsNone(snap['markets']['JP']['as_of'])

    def test_single_bar_cannot_compute_change(self):
        snap = gm.build_snapshot(
            fake_download({'^N225': frame(['2026-08-10'], [42000.0])}),
            UNIVERSE, now=self.now)
        self.assertEqual(snap['markets']['JP']['coverage'], '0/3')

    def test_rows_carry_provenance(self):
        snap = gm.build_snapshot(fake_download(self.data), UNIVERSE, now=self.now)
        row = snap['markets']['JP']['stocks'][0]
        self.assertEqual(row['source'], 'yfinance')
        self.assertIn('retrieved_at', row)
        self.assertIsNotNone(row['as_of_bjt'])

    def test_snapshot_is_json_serializable(self):
        snap = gm.build_snapshot(fake_download(self.data), UNIVERSE, now=self.now)
        json.dumps(snap, ensure_ascii=False)


class UniverseFileTests(unittest.TestCase):
    def test_shipped_universe_is_well_formed(self):
        universe = gm.load_universe()
        self.assertEqual(set(universe), {'US', 'HK', 'JP', 'KR', 'TW'})
        for key, meta in universe.items():
            self.assertIn('timezone', meta, msg=key)
            self.assertRegex(meta['close'], r'^\d{2}:\d{2}$', msg=key)
            self.assertTrue(meta.get('indices'), msg=key)
            # 时区必须能真的解析，否则 as_of 会静默变 None
            self.assertIsNotNone(
                gm.market_close_iso('2026-08-10', meta['timezone'], meta['close']),
                msg=key)




class RowLevelStalenessTests(unittest.TestCase):
    """同一市场内各标的的交易日可能不一致。

    实测：Yahoo 的 ^HSI / ^N225 / ^TWII 比其成分股慢一天。市场级 as_of 取
    max 会把这件事盖住，分析层就会拿 08-07 的指数去解释 08-10 的个股表现。
    """

    def setUp(self):
        self.now = datetime(2026, 8, 11, 0, 30, tzinfo=timezone.utc)
        self.lagging = {
            '^N225': frame(['2026-08-06', '2026-08-07'], [42000.0, 42420.0]),
            '8035.T': frame(['2026-08-07', '2026-08-10'], [30000.0, 30900.0]),
            '6857.T': frame(['2026-08-07', '2026-08-10'], [9000.0, 8910.0]),
        }

    def test_lagging_index_is_flagged(self):
        snap = gm.build_snapshot(fake_download(self.lagging), UNIVERSE, now=self.now)
        jp = snap['markets']['JP']
        self.assertEqual(jp['stale_rows'], ['^N225'])
        self.assertTrue(jp['indices'][0]['row_stale'])
        self.assertFalse(jp['stocks'][0]['row_stale'])

    def test_date_spread_exposes_the_gap(self):
        snap = gm.build_snapshot(fake_download(self.lagging), UNIVERSE, now=self.now)
        self.assertEqual(snap['markets']['JP']['date_spread'],
                         ['2026-08-07', '2026-08-10'])

    def test_market_date_is_the_newest_not_the_index(self):
        snap = gm.build_snapshot(fake_download(self.lagging), UNIVERSE, now=self.now)
        self.assertEqual(snap['markets']['JP']['market_date'], '2026-08-10')

    def test_consistent_market_has_no_stale_rows(self):
        aligned = {
            '^N225': frame(['2026-08-07', '2026-08-10'], [42000.0, 42420.0]),
            '8035.T': frame(['2026-08-07', '2026-08-10'], [30000.0, 30900.0]),
            '6857.T': frame(['2026-08-07', '2026-08-10'], [9000.0, 8910.0]),
        }
        snap = gm.build_snapshot(fake_download(aligned), UNIVERSE, now=self.now)
        self.assertEqual(snap['markets']['JP']['stale_rows'], [])
        self.assertEqual(snap['markets']['JP']['date_spread'],
                         ['2026-08-10', '2026-08-10'])

if __name__ == '__main__':
    unittest.main()
