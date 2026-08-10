import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stock_report import klines_cache, provenance


class ProvenanceTests(unittest.TestCase):
    def test_live_source_is_not_fallback(self):
        meta = provenance.build('sina', as_of='2026-08-10T14:21:38+08:00',
                                retrieved_at='2026-08-10T06:21:40Z')
        self.assertFalse(meta['is_fallback'])
        self.assertAlmostEqual(meta['stale_seconds'], 2.0, places=1)

    def test_backfill_source_marked_fallback(self):
        self.assertTrue(provenance.build('efinance_backfill')['is_fallback'])
        self.assertTrue(provenance.build('klines_cache')['is_fallback'])

    def test_stamp_keeps_numeric_fields_intact(self):
        # 关键约束：price/close 必须仍是裸数字，渲染端和 verify 依赖它
        row = {'code': '600522', 'close': 39.56, 'chg_pct': 1.2}
        provenance.stamp(row, 'sina', as_of='2026-08-10T14:21:38+08:00')
        self.assertEqual(row['close'], 39.56)
        self.assertEqual(row['source'], 'sina')
        self.assertIn('retrieved_at', row)

    def test_market_as_of_requires_both_parts(self):
        self.assertEqual(provenance.market_as_of('2026-08-10', '14:21:38'),
                         '2026-08-10T14:21:38+08:00')
        self.assertIsNone(provenance.market_as_of('2026-08-10', ''))
        self.assertIsNone(provenance.market_as_of('', '14:21:38'))

    def test_summarize_counts_sources(self):
        rows = [{'source': 'sina', 'stale_seconds': 3},
                {'source': 'efinance_backfill', 'is_fallback': True, 'stale_seconds': 90000}]
        summary = provenance.summarize(rows)
        self.assertEqual(summary['by_source']['sina'], 1)
        self.assertEqual(summary['fallback_rows'], 1)
        self.assertEqual(summary['max_stale_seconds'], 90000)


class KlinesCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 10, 7, 40, tzinfo=timezone.utc)

    def test_merge_appends_new_days(self):
        existing = {'dates': ['2026-08-06', '2026-08-07'], 'closes': [10.0, 11.0],
                    'volumes': [100.0, 110.0]}
        incoming = {'dates': ['2026-08-10'], 'closes': [12.0], 'volumes': [120.0]}
        merged = klines_cache.merge_series(existing, incoming, now=self.now)
        self.assertEqual(merged['dates'], ['2026-08-06', '2026-08-07', '2026-08-10'])
        self.assertEqual(merged['last_date'], '2026-08-10')
        self.assertEqual(merged['adjust'], klines_cache.ADJUST)

    def test_incoming_wins_on_same_day(self):
        existing = {'dates': ['2026-08-10'], 'closes': [10.0], 'volumes': [100.0]}
        incoming = {'dates': ['2026-08-10'], 'closes': [12.5], 'volumes': [125.0]}
        merged = klines_cache.merge_series(existing, incoming, now=self.now)
        self.assertEqual(merged['closes'], [12.5])

    def test_trims_to_max_bars(self):
        days = [f'2026-01-{i:02d}' for i in range(1, 32)]
        existing = {'dates': days, 'closes': [float(i) for i in range(31)],
                    'volumes': [1.0] * 31}
        merged = klines_cache.merge_series(existing, None, max_bars=10, now=self.now)
        self.assertEqual(len(merged['dates']), 10)
        self.assertEqual(merged['dates'][-1], '2026-01-31')

    def test_merge_from_empty_existing(self):
        incoming = {'dates': ['2026-08-10'], 'closes': [12.0], 'volumes': [120.0]}
        merged = klines_cache.merge_series(None, incoming, now=self.now)
        self.assertEqual(merged['last_date'], '2026-08-10')

    def test_none_closes_are_dropped(self):
        incoming = {'dates': ['2026-08-07', '2026-08-10'], 'closes': [None, 12.0],
                    'volumes': [0.0, 120.0]}
        merged = klines_cache.merge_series(None, incoming, now=self.now)
        self.assertEqual(merged['dates'], ['2026-08-10'])

    def test_needs_update_detects_stale_entry(self):
        self.assertTrue(klines_cache.needs_update({'last_date': '2026-08-04'}, '2026-08-10'))
        self.assertFalse(klines_cache.needs_update({'last_date': '2026-08-10'}, '2026-08-10'))
        self.assertTrue(klines_cache.needs_update(None, '2026-08-10'))

    def test_coverage_requires_enough_bars_and_freshness(self):
        cache = {
            'A': {'closes': [1.0] * 30, 'last_date': '2026-08-10'},   # 可用
            'B': {'closes': [1.0] * 30, 'last_date': '2026-08-04'},   # 过期
            'C': {'closes': [1.0] * 5, 'last_date': '2026-08-10'},    # 数据不足
        }
        usable, total, ratio = klines_cache.coverage(cache, ['A', 'B', 'C'], '2026-08-10')
        self.assertEqual((usable, total), (1, 3))
        self.assertAlmostEqual(ratio, 1 / 3)

    def test_round_trip_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'klines_cache.json'
            cache = {'600522': klines_cache.merge_series(
                None, {'dates': ['2026-08-10'], 'closes': [12.0], 'volumes': [1.0]},
                now=self.now)}
            klines_cache.save_cache(cache, path)
            self.assertEqual(klines_cache.load_cache(path), cache)

    def test_corrupt_cache_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'broken.json'
            path.write_text('{not json', encoding='utf-8')
            self.assertEqual(klines_cache.load_cache(path), {})

    def test_stale_entries_listed(self):
        cache = {'A': {'last_date': '2026-08-10'}, 'B': {'last_date': '2026-08-04'}}
        self.assertEqual(klines_cache.stale_entries(cache, '2026-08-10'), ['B'])


if __name__ == '__main__':
    unittest.main()
