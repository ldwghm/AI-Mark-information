"""新一期抓取不许把某一行退回更早的交易日。

真实回归（2026-08-12→13）：16:11 与 17:54 两次抓取给出港/日/韩/台正确的
08-12 日线；05:41 那次（为美股收盘而跑）把它们覆盖成 08-11，^N225 退到
08-10。于是当天早报的 global_index_staleness 判 degrade——而这会每天重演。
"""
import unittest

from stock_report import global_markets as gm
from stock_report import timeutil


def row(code, date, price=100.0, close_hhmm='16:00', tz='Asia/Hong_Kong'):
    return {
        'code': code, 'name': code, 'market': 'HK', 'price': price,
        'chg': 0.5, 'prev_close': price - 1, 'market_date': date,
        'as_of': gm.market_close_iso(date, tz, close_hhmm),
        'source': 'yfinance', 'is_fallback': False,
    }


def snapshot(rows, fetch_time='2026-08-12T21:41:31Z', coverage='2/2'):
    return {
        'fetch_time': fetch_time,
        'markets': {'HK': {'name': '香港', 'timezone': 'Asia/Hong_Kong',
                           'indices': list(rows), 'stocks': [],
                           'coverage': coverage}},
    }


NOW = timeutil.parse_iso('2026-08-12T21:45:00Z')


class MergeForward(unittest.TestCase):
    def test_regressed_row_keeps_the_newer_date(self):
        previous = snapshot([row('^HSI', '2026-08-12', 25000.0)],
                            fetch_time='2026-08-12T09:54:00Z', coverage='1/1')
        fresh = snapshot([row('^HSI', '2026-08-11', 24800.0)], coverage='1/1')

        merged = gm.merge_forward(previous, fresh, now=NOW)
        kept = merged['markets']['HK']['indices'][0]

        self.assertEqual(kept['market_date'], '2026-08-12')
        self.assertEqual(kept['price'], 25000.0)
        self.assertTrue(kept['carried_forward'])
        self.assertEqual(kept['carried_reason'], 'regressed')
        self.assertEqual(merged['markets']['HK']['carried_rows'], ['^HSI'])

    def test_newer_row_wins_and_is_not_marked(self):
        previous = snapshot([row('^HSI', '2026-08-11', 24800.0)], coverage='1/1')
        fresh = snapshot([row('^HSI', '2026-08-12', 25000.0)], coverage='1/1')

        kept = gm.merge_forward(previous, fresh, now=NOW)['markets']['HK']['indices'][0]

        self.assertEqual(kept['market_date'], '2026-08-12')
        self.assertNotIn('carried_forward', kept)

    def test_same_date_is_left_alone(self):
        previous = snapshot([row('^HSI', '2026-08-12', 24800.0)], coverage='1/1')
        fresh = snapshot([row('^HSI', '2026-08-12', 25000.0)], coverage='1/1')

        kept = gm.merge_forward(previous, fresh, now=NOW)['markets']['HK']['indices'][0]

        self.assertEqual(kept['price'], 25000.0)      # 同日以本次为准
        self.assertNotIn('carried_forward', kept)

    def test_row_missing_this_time_is_carried(self):
        previous = snapshot([row('^HSI', '2026-08-12'), row('^HSCE', '2026-08-12')])
        fresh = snapshot([row('^HSI', '2026-08-12')])

        block = gm.merge_forward(previous, fresh, now=NOW)['markets']['HK']
        codes = [r['code'] for r in block['indices']]

        self.assertEqual(codes, ['^HSI', '^HSCE'])
        self.assertEqual(block['carried_rows'], ['^HSCE'])
        self.assertEqual(block['coverage'], '2/2')

    def test_corpse_older_than_stale_days_is_not_resurrected(self):
        previous = snapshot([row('^HSI', '2026-07-20')], coverage='1/1')
        fresh = snapshot([row('^HSI', '2026-07-15')], coverage='1/1')

        kept = gm.merge_forward(previous, fresh, now=NOW)['markets']['HK']['indices'][0]

        self.assertEqual(kept['market_date'], '2026-07-15')
        self.assertNotIn('carried_forward', kept)

    def test_market_level_fields_are_recomputed(self):
        """合并后忘了重算，market_date 会停在退化后的值——正是 08-13 快照里
        market_date=08-12 而行是 08-11 的那种自相矛盾。"""
        previous = snapshot([row('^HSI', '2026-08-12'), row('^HSCE', '2026-08-12')])
        fresh = snapshot([row('^HSI', '2026-08-11'), row('^HSCE', '2026-08-11')])

        block = gm.merge_forward(previous, fresh, now=NOW)['markets']['HK']

        self.assertEqual(block['market_date'], '2026-08-12')
        self.assertEqual(block['date_spread'], ['2026-08-12', '2026-08-12'])
        self.assertEqual(block['stale_rows'], [])
        self.assertTrue(all(not r['row_stale'] for r in block['indices']))

    def test_partial_regression_marks_the_lagging_row(self):
        """只有一行被救回、另一行本来就落后时，row_stale 必须仍然亮。"""
        previous = snapshot([row('^HSI', '2026-08-12'), row('^HSCE', '2026-08-10')])
        fresh = snapshot([row('^HSI', '2026-08-11'), row('^HSCE', '2026-08-10')])

        block = gm.merge_forward(previous, fresh, now=NOW)['markets']['HK']

        self.assertEqual(block['market_date'], '2026-08-12')
        self.assertEqual(block['stale_rows'], ['^HSCE'])

    def test_no_previous_snapshot_is_a_passthrough(self):
        fresh = snapshot([row('^HSI', '2026-08-11')], coverage='1/1')
        self.assertIs(gm.merge_forward(None, fresh, now=NOW), fresh)
        self.assertIs(gm.merge_forward({}, fresh, now=NOW), fresh)

    def test_unknown_market_in_previous_is_ignored(self):
        previous = {'markets': {'JP': {'indices': [row('^N225', '2026-08-12')],
                                       'stocks': [], 'coverage': '1/1'}}}
        fresh = snapshot([row('^HSI', '2026-08-11')], coverage='1/1')

        merged = gm.merge_forward(previous, fresh, now=NOW)

        self.assertEqual(list(merged['markets']), ['HK'])
        self.assertEqual(merged['markets']['HK']['indices'][0]['market_date'],
                         '2026-08-11')


class LoadPrevious(unittest.TestCase):
    def test_missing_or_broken_file_reads_as_none(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'nope.json'
            self.assertIsNone(gm.load_previous(missing))

            broken = Path(tmp) / 'broken.json'
            broken.write_text('{not json', encoding='utf-8')
            self.assertIsNone(gm.load_previous(broken))


if __name__ == '__main__':
    unittest.main()
