"""第二数据源：交叉验证必须在能联网的那一侧做。

CCR 会话里新浪/腾讯/yfinance 全部被出口代理拦掉，所以 cloud_fetch 那套
双源验证虽然写好了，实际每期都是 checked_pairs=0——不是没写，是跑不到。
2026-08-12 从 Actions runner 实测：sina 718ms、tencent 957ms、
netease 连不上、mootdx 18076ms，三个能通的与东财基线价格差 0.000%。
"""
import unittest
from datetime import datetime, timezone

from stock_report import cloud_fetch, crosscheck, second_source

SINA_LINE = ('var hq_str_sh600522="中天科技,33.20,33.00,33.55,33.80,33.10,'
             + ','.join(['0'] * 24) + ',2026-08-12,15:00:00,00";')
TENCENT_SEG = ('v_sh600522="1~中天科技~600522~33.55~33.00~33.20'
               + '~0' * 24 + '~20260812150000~0.55~1.67' + '~0' * 8 + '"')


def _sina_text(_url):
    return SINA_LINE


def _tencent_text(_url):
    return TENCENT_SEG


class SymbolTests(unittest.TestCase):
    def test_bare_code_is_never_guessed_to_be_an_index(self):
        """实测踩到：东财观察池里的 000001 是平安银行（约 11 元），
        映射成 sh000001（上证指数 3940 点）后交叉验证报出 34981% 的"冲突"。
        裸代码分不出指数和个股，所以一律按个股规则走。"""
        self.assertEqual(second_source.sina_symbol('000001'), 'sz000001')
        self.assertEqual(second_source.sina_symbol('399006'), 'sz399006')

    def test_stock_codes_follow_the_leading_digit(self):
        self.assertEqual(second_source.sina_symbol('600522'), 'sh600522')
        self.assertEqual(second_source.sina_symbol('688012'), 'sh688012')
        self.assertEqual(second_source.sina_symbol('300308'), 'sz300308')
        self.assertEqual(second_source.sina_symbol('002281'), 'sz002281')

    def test_already_prefixed_codes_are_accepted(self):
        self.assertEqual(second_source.sina_symbol('sh600522'), 'sh600522')


class ParserTests(unittest.TestCase):
    def test_sina_row_carries_price_change_and_provenance(self):
        quotes = second_source.fetch_sina(['600522'], fetcher=_sina_text)
        row = quotes['sh600522']
        self.assertEqual(row['price'], 33.55)
        self.assertEqual(row['prev_close'], 33.00)
        self.assertEqual(row['chg_pct'], 1.67)
        self.assertEqual(row['src'], 'sina')
        self.assertEqual(row['as_of'], '2026-08-12T15:00:00+08:00')
        self.assertFalse(row['is_fallback'])

    def test_tencent_row_parses_its_own_very_different_layout(self):
        quotes = second_source.fetch_tencent(['600522'], fetcher=_tencent_text)
        row = quotes['sh600522']
        self.assertEqual(row['price'], 33.55)
        self.assertEqual(row['src'], 'tencent')
        self.assertEqual(row['as_of'], '2026-08-12T15:00:00+08:00')

    def test_garbage_and_zero_prices_are_dropped_not_guessed(self):
        for junk in ('', 'nonsense', 'var hq_str_sh600522="";'):
            self.assertEqual(second_source.fetch_sina(['600522'],
                                                      fetcher=lambda _u, j=junk: j), {})
        zero = 'var hq_str_sh600522="中天,0,0,0,0,0,' + ','.join(['0'] * 22) + \
               ',2026-08-12,15:00:00,00";'
        self.assertEqual(second_source.fetch_sina(['600522'],
                                                  fetcher=lambda _u: zero), {})


class FailoverTests(unittest.TestCase):
    def test_falls_through_to_tencent_when_sina_returns_nothing(self):
        providers = (('sina', lambda codes: {}),
                     ('tencent', lambda codes: {'sh600522': {'price': 33.55}}))
        name, quotes = second_source.fetch_second_source(['600522'], providers)
        self.assertEqual(name, 'tencent')
        self.assertEqual(quotes['sh600522']['price'], 33.55)

    def test_a_raising_provider_does_not_abort_the_chain(self):
        def boom(codes):
            raise OSError('hq.sinajs.cn unreachable')
        providers = (('sina', boom),
                     ('tencent', lambda codes: {'sh600522': {'price': 33.55}}))
        name, _ = second_source.fetch_second_source(['600522'], providers)
        self.assertEqual(name, 'tencent')

    def test_all_providers_down_reports_no_source_rather_than_empty_agreement(self):
        providers = (('sina', lambda codes: {}), ('tencent', lambda codes: {}))
        name, quotes = second_source.fetch_second_source(['600522'], providers)
        self.assertIsNone(name)
        self.assertEqual(quotes, {})

    def test_no_codes_means_no_requests(self):
        called = []
        providers = (('sina', lambda codes: called.append(codes) or {}),)
        self.assertEqual(second_source.fetch_second_source([], providers), (None, {}))
        self.assertEqual(called, [])


def _eastmoney_snapshot(price=33.55):
    return {
        'watchlist_rt': [
            {'code': '600522', 'name': '中天科技', 'current': price,
             'change_pct': 1.67, 'data_date': '2026-08-12'},
            {'code': '300308', 'name': '中际旭创', 'current': 921.0,
             'change_pct': 3.9, 'data_date': '2026-08-12'}],
        'watchlist_technicals': [
            {'code': '600522', 'chg_pct': 1.67}, {'code': '300308', 'chg_pct': 3.9}],
        'sectors': [{'sector': '光纤光缆',
                     'leader': {'code': '600522'}, 'laggard': {'code': '300308'}}],
    }


class AttachCrosscheckTests(unittest.TestCase):
    def test_agreeing_sources_produce_a_real_checked_pair_count(self):
        snap = _eastmoney_snapshot()
        providers = (('sina', lambda codes: {
            'sh600522': {'price': 33.55, 'src': 'sina'},
            'sz300308': {'price': 921.0, 'src': 'sina'}}),)
        summary = second_source.attach_crosscheck(snap, providers)
        self.assertEqual(summary['status'], 'agreed')
        self.assertEqual(summary['checked_pairs'], 2)
        self.assertEqual(summary['max_diff_pct'], 0.0)
        self.assertEqual(summary['secondary_source'], 'sina')
        self.assertIs(snap['source_crosscheck'], summary)

    def test_a_real_disagreement_is_reported_not_silently_resolved(self):
        snap = _eastmoney_snapshot()
        providers = (('sina', lambda codes: {
            'sh600522': {'price': 40.00, 'src': 'sina'},
            'sz300308': {'price': 921.0, 'src': 'sina'}}),)
        summary = second_source.attach_crosscheck(snap, providers)
        self.assertEqual(summary['status'], 'conflict')
        self.assertEqual(summary['checked_pairs'], 2)
        self.assertIn('600522', summary['codes'])
        self.assertGreater(summary['max_diff_pct'], 0.5)

    def test_unreachable_second_source_says_unchecked_not_agreed(self):
        """这是整套东西的起点：0 次比对不能报成"两源一致"。"""
        snap = _eastmoney_snapshot()
        summary = second_source.attach_crosscheck(snap, (('sina', lambda c: {}),))
        self.assertEqual(summary['status'], 'unchecked')
        self.assertEqual(summary['checked_pairs'], 0)
        self.assertIsNone(summary['max_diff_pct'])
        self.assertIsNone(summary['secondary_source'])

    def test_only_decision_relevant_targets_are_double_fetched(self):
        """不是给 51 只都查两遍——那只是把请求量翻倍。"""
        asked = {}
        providers = (('sina', lambda codes: asked.setdefault('codes', codes) and {}),)
        snap = _eastmoney_snapshot()
        second_source.attach_crosscheck(snap, providers)
        self.assertEqual(set(asked['codes']), {'600522', '300308'})

    def test_snapshot_without_quotes_reports_why(self):
        summary = second_source.attach_crosscheck({}, (('sina', lambda c: {}),))
        self.assertEqual(summary['checked_pairs'], 0)
        self.assertIn('无从比对', summary['note'])


class TimeSkewTests(unittest.TestCase):
    """两次抓取不在同一时点时，价差不能归因于"源不一致"。

    实测踩到：拿 08-12 13:42 的东财快照去比 15:00 的新浪收盘价，26 对里
    报出 10 处"冲突"、最大 2.556%——那全是这五小时里的真实波动。
    盘中一分钟的正常波动就能越过 0.5% 阈值。
    """

    INTRADAY_NOW = datetime(2026, 8, 12, 5, 45, tzinfo=timezone.utc)   # 13:45 BJT

    def _providers(self, as_of, conflict=True):
        price = 40.0 if conflict else 33.55
        return (('sina', lambda codes: {
            'sh600522': {'price': price, 'src': 'sina', 'as_of': as_of},
            'sz300308': {'price': 921.0, 'src': 'sina', 'as_of': as_of}}),)

    def test_stale_intraday_quote_downgrades_conflict_to_skewed(self):
        summary = second_source.attach_crosscheck(
            _eastmoney_snapshot(), self._providers('2026-08-12T13:20:00+08:00'),
            now=self.INTRADAY_NOW)
        self.assertEqual(summary['status'], 'skewed')
        self.assertEqual(summary['as_of_skew_seconds'], 1500.0)   # 25 分钟
        self.assertIn('不能归因于来源分歧', summary['note'])

    def test_same_moment_conflict_stays_a_conflict(self):
        summary = second_source.attach_crosscheck(
            _eastmoney_snapshot(), self._providers('2026-08-12T13:44:30+08:00'),
            now=self.INTRADAY_NOW)
        self.assertEqual(summary['status'], 'conflict')
        self.assertEqual(summary['as_of_skew_seconds'], 30.0)

    def test_after_close_is_never_skewed_however_late_you_compare(self):
        """收盘后两个源报的都是同一根收盘价，隔多久比都成立。

        实测踩到：晚上 20:36 拿新浪收盘价对账，被判 301 分钟 skew，
        10 对全部作废——而那正是最干净的一次比对。
        """
        summary = second_source.attach_crosscheck(
            _eastmoney_snapshot(), self._providers('2026-08-12T15:00:00+08:00'),
            now=datetime(2026, 8, 12, 12, 36, tzinfo=timezone.utc))   # 20:36 BJT
        self.assertEqual(summary['status'], 'conflict')
        self.assertEqual(summary['as_of_skew_seconds'], 0.0)

    def test_agreement_is_never_downgraded_by_skew(self):
        """时点不同但价格仍然一致，那是更强的证据，不是更弱的。"""
        summary = second_source.attach_crosscheck(
            _eastmoney_snapshot(),
            self._providers('2026-08-12T13:20:00+08:00', conflict=False),
            now=self.INTRADAY_NOW)
        self.assertEqual(summary['status'], 'agreed')

    def test_missing_timestamps_leave_skew_unknown_not_zero(self):
        providers = (('sina', lambda codes: {
            'sh600522': {'price': 33.55}, 'sz300308': {'price': 921.0}}),)
        self.assertIsNone(second_source.attach_crosscheck(
            _eastmoney_snapshot(), providers)['as_of_skew_seconds'])


class CloudFetchAdoptsUpstreamTests(unittest.TestCase):
    def test_actions_side_result_is_preferred_when_local_checked_nothing(self):
        """CCR 本地 checked_pairs=0 什么也没证明；Actions 那次比对的正是
        我们最终采用的那份东财数据。"""
        import inspect
        src = inspect.getsource(cloud_fetch.main)
        self.assertIn("upstream = (OLD or {}).get('source_crosscheck')", src)
        self.assertIn("checked_by='github_actions'", src)
        self.assertIn("'crosscheck': cc_summary", src)

    def test_upstream_never_overrides_a_local_check_that_actually_ran(self):
        import inspect
        src = inspect.getsource(cloud_fetch.main)
        self.assertIn('if not checked_pairs and isinstance(upstream, dict)', src)


class FetchScriptWiringTests(unittest.TestCase):
    def test_both_actions_scripts_attach_the_crosscheck_before_writing(self):
        from pathlib import Path
        for name in ('fetch_market_data.py', 'fetch_market_data_pm.py'):
            text = Path(name).read_text(encoding='utf-8')
            self.assertIn('from stock_report import second_source', text, msg=name)
            self.assertIn('second_source.attach_crosscheck(result)', text, msg=name)
            self.assertLess(text.index('second_source.attach_crosscheck(result)'),
                            text.index('json.dump(result'), msg=f'{name}: 必须写盘前做')

    def test_second_source_survives_the_flat_layout(self):
        """CCR 把模块 curl 到 /tmp 平铺执行，包内相对导入会 ImportError。"""
        import ast
        from pathlib import Path
        tree = ast.parse(Path('stock_report/second_source.py').read_text(encoding='utf-8'))
        handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
        self.assertTrue(any(isinstance(h.type, ast.Name) and h.type.id == 'ImportError'
                            for h in handlers))


if __name__ == '__main__':
    unittest.main()
