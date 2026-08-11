"""verify.py 端到端：退出码必须真的能阻断发信。

只测行为契约（退出码 + verdict 文件），不测内部实现——workflow 依赖的就是这两样。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def make_latest(priced=50, total=50, stale=0, conflicts=None, expected='2026-08-10'):
    rows = []
    for i in range(total):
        code = str(600000 + i)
        rows.append({
            'code': code, 'name': f'股{i}', 'sector': '算力',
            'close': 100.0, 'chg_pct': 1.0 if i < priced else None,
            'score': 60, 'volume_ratio': 1.0,
        })
        if i >= priced:
            rows[-1]['close'] = None
    return {
        'fetch_time': '2026-08-10T06:21:40.956545Z',
        'expected_data_date': expected,
        'report_type': 'afternoon',
        'watchlist_technicals': rows,
        'watchlist_rt': [{'code': r['code'], 'current': r['close'],
                          'change_pct': r['chg_pct']} for r in rows if r['close']],
        'data_freshness': {'expected_date': expected, 'quote_date_mode': expected,
                           'stale_quote_count': stale},
        'data_quality': {'index_data_confidence': 'high',
                         'watchlist_coverage': f'{priced}/{total}',
                         'source_conflicts': conflicts or []},
    }


def make_analysis(**extra):
    data = {
        'date': '2026-08-10',
        'market_summary': '上证指数收于3956.48点，涨0.42%。',
        'key_insights': ['算力板块平均涨1.2%'],
        'stock_highlights': [{'code': '600000', 'name': '股0', 'price': 100.0, 'chg_pct': 1.0}],
        'risk_warnings': ['数据为盘中快照'],
        'hk_us_summary': '港美股接口不可用，本期缺失',
        'reflection': {'prior_result': 'correct'},
        'review': '早报预测正确',
    }
    data.update(extra)
    return data


class VerifyExitCodeTests(unittest.TestCase):
    def run_verify(self, latest, analysis, mode='afternoon', morning=None, extra_args=()):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            lpath, apath = tmp / 'latest.json', tmp / 'analysis.json'
            vpath = tmp / 'verdict.json'
            lpath.write_text(json.dumps(latest), encoding='utf-8')
            apath.write_text(json.dumps(analysis), encoding='utf-8')

            args = [sys.executable, '-m', 'stock_report.verify', '--mode', mode,
                    '--latest', str(lpath), '--analysis', str(apath),
                    '--verdict', str(vpath)]
            if morning is not None:
                mpath = tmp / 'morning.json'
                mpath.write_text(json.dumps(morning), encoding='utf-8')
                args += ['--morning-analysis', str(mpath)]
            else:
                args += ['--morning-analysis', str(tmp / 'missing.json')]
            if not any(a == '--today' for a in extra_args):
                args += ['--today', '2026-08-10']
            args += list(extra_args)

            proc = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
            verdict = json.loads(vpath.read_text(encoding='utf-8')) if vpath.exists() else {}
            written = json.loads(apath.read_text(encoding='utf-8'))
            return proc.returncode, verdict, written

    def test_healthy_afternoon_passes(self):
        code, verdict, _ = self.run_verify(
            make_latest(), make_analysis(), morning={'date': '2026-08-10'})
        self.assertEqual(code, 0, msg=verdict)
        self.assertFalse(verdict['blocked'])

    def test_stale_morning_analysis_blocks_with_exit_3(self):
        code, verdict, written = self.run_verify(
            make_latest(), make_analysis(), morning={'date': '2026-08-04'})
        self.assertEqual(code, 3)
        self.assertTrue(verdict['blocked'])
        self.assertTrue(any('2026-08-04' in r for r in verdict['block_reasons']))
        # 复盘必须被强制改成 pending，不能留着"早报预测正确"
        self.assertEqual(written['reflection']['prior_result'], 'pending')
        self.assertTrue(written['review'].startswith('[待结算]'))

    def test_allow_open_loop_downgrades_instead_of_blocking(self):
        code, verdict, _ = self.run_verify(
            make_latest(), make_analysis(), morning={'date': '2026-08-04'},
            extra_args=['--allow-open-loop'])
        self.assertEqual(code, 0)
        self.assertFalse(verdict['blocked'])
        self.assertTrue(verdict['degraded'])

    def test_coverage_below_seventy_percent_blocks(self):
        code, verdict, _ = self.run_verify(
            make_latest(priced=30, total=50), make_analysis(),
            morning={'date': '2026-08-10'})
        self.assertEqual(code, 3)
        self.assertTrue(any('停发线' in r for r in verdict['block_reasons']))

    def test_index_conflict_over_point_three_percent_is_hard_fail(self):
        latest = make_latest(conflicts=[{
            'code': '000001', 'diff_pct': 0.9,
            'primary_source': 'sina', 'primary_price': 3956.0,
            'secondary_source': 'tencent', 'secondary_price': 3920.4}])
        code, verdict, _ = self.run_verify(
            latest, make_analysis(), morning={'date': '2026-08-10'})
        self.assertEqual(code, 2)
        self.assertTrue(any('指数' in r for r in verdict['hard_reasons']))

    def test_small_index_conflict_is_only_soft(self):
        latest = make_latest(conflicts=[{
            'code': '000001', 'diff_pct': 0.2,
            'primary_source': 'sina', 'primary_price': 3956.0,
            'secondary_source': 'tencent', 'secondary_price': 3948.1}])
        code, verdict, _ = self.run_verify(
            latest, make_analysis(), morning={'date': '2026-08-10'})
        self.assertEqual(code, 0)
        self.assertTrue(verdict['degraded'])

    def test_stock_price_deviation_over_one_percent_is_hard_fail(self):
        # highlight 报 106，实际 100 -> 6% 偏差，旧阈值 25% 会放过
        code, verdict, _ = self.run_verify(
            make_latest(),
            make_analysis(stock_highlights=[
                {'code': '600000', 'name': '股0', 'price': 106.0, 'chg_pct': 1.0}]),
            morning={'date': '2026-08-10'})
        self.assertEqual(code, 2)
        self.assertTrue(any('600000' in r for r in verdict['hard_reasons']))

    def test_direction_conflict_is_hard_fail(self):
        # 旧行为：方向相反只记软警告，照发不误
        code, verdict, _ = self.run_verify(
            make_latest(),
            make_analysis(stock_highlights=[
                {'code': '600000', 'name': '股0', 'price': 100.0, 'chg_pct': -2.5}]),
            morning={'date': '2026-08-10'})
        self.assertEqual(code, 2)
        self.assertTrue(any('方向相反' in r for r in verdict['hard_reasons']))

    def test_morning_mode_needs_no_morning_analysis(self):
        latest = make_latest()
        latest['report_type'] = 'morning'
        code, verdict, _ = self.run_verify(latest, make_analysis(), mode='morning')
        self.assertEqual(code, 0, msg=verdict)
        self.assertEqual(verdict['continuity']['level'], 'pass')


if __name__ == '__main__':
    unittest.main()
