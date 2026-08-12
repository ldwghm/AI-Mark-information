"""verify.py 端到端：活性降级、未检查告警、highlight 时点标注。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def make_latest(live=0, fallback=51, intraday=True, crosscheck_summary=None):
    rows = []
    for i in range(live):
        rows.append({'code': f'{600000 + i}', 'name': f'活{i}', 'close': 100.0,
                     'chg_pct': 1.0, 'source': 'sina', 'is_fallback': False,
                     'as_of': '2026-08-11T14:23:20+08:00'})
    for i in range(fallback):
        rows.append({'code': f'{700000 + i}', 'name': f'回{i}', 'close': 100.0,
                     'chg_pct': -6.01, 'source': 'klines_cache', 'is_fallback': True,
                     'as_of': '2026-08-10T15:00:00+08:00'})
    data = {
        'fetch_time': '2026-08-11T06:26:51.710540Z',
        'expected_data_date': '2026-08-11',
        'report_type': 'afternoon',
        'watchlist_technicals': rows,
        'watchlist_rt': [{'code': r['code'], 'current': r['close'],
                          'change_pct': r['chg_pct'], 'source': r['source'],
                          'is_fallback': r['is_fallback'], 'as_of': r['as_of']}
                         for r in rows],
        'data_freshness': {'expected_date': '2026-08-11',
                           'quote_date_mode': '2026-08-11', 'stale_quote_count': 0},
        'data_quality': {'index_data_confidence': 'high',
                         'watchlist_coverage': f'{len(rows)}/{len(rows)}',
                         'source_conflicts': [],
                         'crosscheck': crosscheck_summary if crosscheck_summary is not None
                         else {'checked_pairs': 12, 'checked_conflicts': 0,
                               'status': 'agreed', 'max_diff_pct': 0.0}},
    }
    if intraday:
        # 700000 今天有盘中价 108.0，与回填的 100.0 差 8%
        data['capital_flow_top30_rt'] = [{'f12': '700000', 'f2': 108.0, 'f3': 2.91}]
    return data


def make_analysis(highlight_code='700000', highlight_price=100.0, highlight_chg=-6.01):
    return {
        'date': '2026-08-11',
        'market_summary': '板块盘中普遍收红。',
        'key_insights': ['算力板块涨0.29%'],
        'stock_highlights': [{'code': highlight_code, 'name': '回0',
                              'price': highlight_price, 'chg_pct': highlight_chg,
                              'comment': '口径：本行为8/10收盘'}],
        'risk_warnings': ['个股价格为昨日收盘快照'],
        'hk_us_summary': '港美股接口不可用，本期缺失',
        'reflection': {'prior_result': 'correct'},
        'review': '早报预测正确',
    }


class VerifyLivenessE2ETests(unittest.TestCase):
    def run_verify(self, latest, analysis):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            lp, ap, vp, mp = (tmp / 'l.json', tmp / 'a.json',
                              tmp / 'v.json', tmp / 'm.json')
            lp.write_text(json.dumps(latest), encoding='utf-8')
            ap.write_text(json.dumps(analysis), encoding='utf-8')
            mp.write_text(json.dumps({'date': '2026-08-11'}), encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, '-m', 'stock_report.verify', '--mode', 'afternoon',
                 '--latest', str(lp), '--analysis', str(ap), '--verdict', str(vp),
                 '--morning-analysis', str(mp), '--today', '2026-08-11'],
                cwd=REPO, capture_output=True, text=True)
            verdict = json.loads(vp.read_text(encoding='utf-8')) if vp.exists() else {}
            written = json.loads(ap.read_text(encoding='utf-8'))
            return proc.returncode, verdict, written

    def test_all_fallback_degrades_and_is_recorded(self):
        code, verdict, _ = self.run_verify(make_latest(), make_analysis())
        self.assertEqual(code, 0)                      # 有盘中层，降级不阻断
        self.assertTrue(verdict['degraded'])
        self.assertEqual(verdict['liveness']['level'], 'degrade')
        self.assertEqual(verdict['liveness']['live_rows'], 0)
        self.assertEqual(verdict['liveness']['total_rows'], 51)

    def test_no_live_and_no_intraday_blocks(self):
        code, verdict, _ = self.run_verify(
            make_latest(intraday=False), make_analysis())
        self.assertEqual(code, 3)
        self.assertTrue(any('无任何当日数据' in r for r in verdict['block_reasons']))

    def test_unchecked_crosscheck_raises_a_warning(self):
        code, verdict, _ = self.run_verify(
            make_latest(crosscheck_summary={'checked_pairs': 0, 'checked_conflicts': 0,
                                            'status': 'unchecked', 'max_diff_pct': None}),
            make_analysis())
        self.assertEqual(code, 0)
        self.assertTrue(any('未做双源交叉验证' in r for r in verdict['soft_reasons']))

    def test_highlight_gets_price_provenance_stamped(self):
        _code, _verdict, written = self.run_verify(make_latest(), make_analysis())
        h = written['stock_highlights'][0]
        self.assertEqual(h['price_as_of'], '2026-08-10T15:00:00+08:00')
        self.assertTrue(h['price_is_fallback'])
        self.assertEqual(h['price_source'], 'klines_cache')

    def test_stale_highlight_with_todays_price_is_flagged(self):
        _code, verdict, written = self.run_verify(make_latest(), make_analysis())
        self.assertTrue(verdict['stale_highlights'])
        self.assertEqual(written['stock_highlights'][0]['intraday_price'], 108.0)
        self.assertTrue(any('今日盘中为 108.0' in r for r in verdict['soft_reasons']))

    def test_highlight_using_todays_price_is_not_flagged(self):
        _code, verdict, _ = self.run_verify(
            make_latest(), make_analysis(highlight_price=108.0))
        self.assertEqual(verdict['stale_highlights'], [])

    def test_mostly_live_data_passes_clean(self):
        code, verdict, _ = self.run_verify(
            make_latest(live=48, fallback=3, intraday=False),
            make_analysis(highlight_code='600000', highlight_price=100.0,
                          highlight_chg=1.0))
        self.assertEqual(code, 0)
        self.assertEqual(verdict['liveness']['level'], 'pass')


if __name__ == '__main__':
    unittest.main()
