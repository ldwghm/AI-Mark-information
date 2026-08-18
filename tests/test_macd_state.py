"""60 分钟 MACD 顶部钝化 / 结构 / 消失。

三种状态用的是徐小明那套术语，**不是标准定义**——span 怎么取、比哪两个峰、
用收盘还是最高价都是自定的。代码化的意义是把主观固定成可回测的东西，
所以这些参数在测试里也当参数验，不当常量信。

数值场景直接抄自那套讲法的教科书例子：

    前高 A：价 3400，DIF 32
    次高 B：价 3420，DIF 30      → 价格新高、DIF 未新高 = 钝化
      B 之后 DIF 30→29           → 顶部结构形成
      B 之后 DIF 30→31→34（>32） → 钝化消失

最要紧的一条：**钝化 ≠ 见顶**。三种状态必须分得开，否则报告会把预警
写成结论。
"""
import unittest

from stock_report import macd_state as M
import technical_indicators as TI


def series(peak_a=3400.0, peak_b=3420.0, tail=None):
    """造一段有两个明确 swing high 的收盘价。

    形状：低 → A → 回落 → B → tail。span=3 需要左右各 3 根确认，
    所以每个峰前后都留足 4 根。
    """
    out = [3350.0, 3360.0, 3370.0, 3380.0]
    out += [peak_a]
    out += [3390.0, 3380.0, 3370.0, 3360.0]
    out += [3380.0, 3395.0, 3405.0]
    out += [peak_b]
    out += list(tail if tail is not None else [3410.0, 3405.0, 3400.0])
    return out


def dif_for(closes, a_val, b_val, tail_vals):
    """给上面的序列配一条 DIF：A 处 a_val、B 处 b_val、其余线性填充。"""
    n = len(closes)
    dif = [20.0] * n
    ia = closes.index(max(closes[:9]))
    ib = 12
    dif[ia] = a_val
    dif[ib] = b_val
    for k, v in enumerate(tail_vals):
        if ib + 1 + k < n:
            dif[ib + 1 + k] = v
    return dif, ia, ib


class SwingHighTests(unittest.TestCase):
    def test_finds_a_clean_local_max(self):
        self.assertEqual(M.swing_highs([1, 2, 3, 9, 3, 2, 1], span=3), [3])

    def test_edges_are_never_peaks(self):
        """最后 span 根内的高点还没被右侧确认，拿来比就是用未来数据。"""
        self.assertEqual(M.swing_highs([1, 2, 3, 4, 5, 6, 9], span=3), [])

    def test_span_is_a_parameter(self):
        values = [1, 5, 2, 6, 2, 5, 1]
        self.assertEqual(M.swing_highs(values, span=1), [1, 3, 5])
        self.assertEqual(M.swing_highs(values, span=3), [3])

    def test_flat_plateau_does_not_produce_two_peaks(self):
        self.assertEqual(len(M.swing_highs([1, 2, 3, 7, 7, 3, 2, 1, 0], span=3)), 1)

    def test_empty(self):
        self.assertEqual(M.swing_highs([], span=3), [])


class MacdSeriesTests(unittest.TestCase):
    CLOSES = [100 + (i % 7) * 2 + i * 0.4 for i in range(80)]

    def test_last_value_matches_the_daily_card_calculation(self):
        """同一份数据在两处必须给同一个 DIF/DEA，否则报告自相矛盾。"""
        dif, dea = M.macd_series(self.CLOSES)
        m, d, _h = TI.calc_macd(self.CLOSES)
        self.assertAlmostEqual(round(dif[-1], 3), m, places=3)
        self.assertAlmostEqual(round(dea[-1], 3), d, places=3)

    def test_dif_is_aligned_with_the_price_series(self):
        dif, dea = M.macd_series(self.CLOSES)
        self.assertEqual(len(dif), len(self.CLOSES))
        self.assertEqual(len(dea), len(self.CLOSES))

    def test_unsettled_head_of_dea_is_none_not_zero(self):
        _dif, dea = M.macd_series(self.CLOSES)
        self.assertIsNone(dea[0])
        self.assertIsNotNone(dea[-1])

    def test_short_input(self):
        self.assertEqual(M.macd_series([1.0]), ([], []))


class StateMachineTests(unittest.TestCase):
    """用注入的 DIF 精确钉住三条分界。"""

    def run_state(self, a_dif, b_dif, tail_dif, tail_px=None):
        closes = series(tail=tail_px)
        dif, _ia, _ib = dif_for(closes, a_dif, b_dif, tail_dif)
        return M.top_state(closes, dif=dif, span=3, min_bars=0)

    def test_price_higher_but_dif_lower_is_blunting(self):
        out = self.run_state(32.0, 30.0, [30.0, 30.0, 30.0])
        self.assertEqual(out['state'], M.BLUNTING)
        self.assertIn('不等于顶部已确认', out['meaning'])

    def test_blunting_then_dif_turns_down_is_structure(self):
        out = self.run_state(32.0, 30.0, [30.0, 30.0, 29.0])
        self.assertEqual(out['state'], M.STRUCTURE)
        self.assertEqual(out['dif_now'], 29.0)
        self.assertEqual(out['dif_prev'], 30.0)

    def test_dif_reclaiming_the_prior_peak_clears_the_blunting(self):
        out = self.run_state(32.0, 30.0, [31.0, 33.0, 34.0])
        self.assertEqual(out['state'], M.CLEARED)
        self.assertEqual(out['dif_peak_after'], 34.0)

    def test_clearing_beats_structure_when_both_could_read(self):
        """先冲上去再回落一根：背离条件已不成立，不该报结构。"""
        out = self.run_state(32.0, 30.0, [34.0, 35.0, 34.5])
        self.assertEqual(out['state'], M.CLEARED)

    def test_dif_making_a_new_high_with_price_is_not_a_divergence(self):
        out = self.run_state(30.0, 32.0, [32.0, 32.0, 32.0])
        self.assertEqual(out['state'], M.NONE)

    def test_price_failing_to_make_a_new_high_is_not_a_divergence(self):
        closes = series(peak_a=3450.0, peak_b=3420.0)
        dif, _ia, _ib = dif_for(closes, 32.0, 30.0, [30.0, 30.0, 29.0])
        self.assertEqual(M.top_state(closes, dif=dif, span=3, min_bars=0)['state'],
                         M.NONE)

    def test_peaks_are_reported_with_price_and_dif(self):
        out = self.run_state(32.0, 30.0, [30.0, 30.0, 30.0])
        self.assertEqual(out['peak_prev']['price'], 3400.0)
        self.assertEqual(out['peak_prev']['dif'], 32.0)
        self.assertEqual(out['peak_last']['price'], 3420.0)
        self.assertEqual(out['peak_last']['dif'], 30.0)

    def test_bars_since_last_peak_is_reported(self):
        out = self.run_state(32.0, 30.0, [30.0, 30.0, 30.0])
        self.assertEqual(out['bars_since_last_peak'], 3)

    def test_params_ride_along_so_the_report_can_print_them(self):
        out = self.run_state(32.0, 30.0, [30.0, 30.0, 30.0])
        self.assertEqual(out['params']['span'], 3)
        self.assertEqual(out['params']['fast'], 12)

    def test_times_are_attached_when_supplied(self):
        closes = series()
        dif, _ia, _ib = dif_for(closes, 32.0, 30.0, [30.0, 30.0, 30.0])
        times = [f'2026-08-{d:02d} 10:30' for d in range(1, len(closes) + 1)]
        out = M.top_state(closes, times=times, dif=dif, span=3, min_bars=0)
        self.assertTrue(out['peak_last']['time'].startswith('2026-08-13'))


class GuardTests(unittest.TestCase):
    def test_short_series_is_insufficient_with_a_reason(self):
        out = M.top_state([1.0] * 10)
        self.assertEqual(out['state'], M.INSUFFICIENT)
        self.assertIn('需要至少', out['reason'])

    def test_empty_series(self):
        self.assertEqual(M.top_state([])['state'], M.INSUFFICIENT)
        self.assertEqual(M.top_state(None)['state'], M.INSUFFICIENT)

    def test_a_series_with_one_peak_reports_none_not_a_crash(self):
        closes = [3300.0 + i for i in range(20)] + [3400.0] + [3350.0 - i for i in range(20)]
        out = M.top_state(closes, span=3, min_bars=0, dif=[1.0] * len(closes))
        self.assertEqual(out['state'], M.NONE)
        self.assertIn('swing high', out['reason'])

    def test_monotonic_rise_has_no_confirmed_peak(self):
        closes = [3000.0 + i * 3 for i in range(60)]
        self.assertEqual(M.top_state(closes, span=3)['state'], M.NONE)


class ParseTests(unittest.TestCase):
    LINE = '2026-08-18 15:00,1779.01,1790.87,1796.83,1770.12,123456,7890123,1.2,0.6,10.5,0.4'

    def test_close_is_the_third_field(self):
        times, closes = M.parse_60m([self.LINE])
        self.assertEqual(closes, [1790.87])
        self.assertEqual(times, ['2026-08-18 15:00'])

    def test_malformed_lines_are_skipped_not_fatal(self):
        times, closes = M.parse_60m([self.LINE, 'garbage', '', 'a,b,c'])
        self.assertEqual(len(closes), 1)
        self.assertEqual(len(times), 1)

    def test_empty_input(self):
        self.assertEqual(M.parse_60m([]), ([], []))
        self.assertEqual(M.parse_60m(None), ([], []))


class AnalyseTests(unittest.TestCase):
    def test_each_series_is_evaluated_independently(self):
        out = M.analyse({'上证指数': [], '科创50': []})
        self.assertEqual(set(out), {'上证指数', '科创50'})
        self.assertTrue(all(v['state'] == M.INSUFFICIENT for v in out.values()))

    def test_empty_mapping(self):
        self.assertEqual(M.analyse({}), {})
        self.assertEqual(M.analyse(None), {})


class RealisticSeriesTests(unittest.TestCase):
    """不注入 DIF，用真实计算跑一遍，证明整条链是通的。"""

    def test_a_decelerating_rally_produces_a_top_divergence(self):
        # 前 30 根走平：DIF 的前 slow(26) 根不参与比较，热身不够的话第一个峰
        # 会被过滤掉，只剩一个可用峰。真实 60min 有 128 根，不会遇到。
        closes = [1000.0] * 30
        for _ in range(18):
            closes.append(closes[-1] * 1.012)      # 急涨
        for _ in range(10):
            closes.append(closes[-1] * 0.994)      # 回调
        for _ in range(26):
            closes.append(closes[-1] * 1.0032)     # 慢涨，最终越过前高
        for _ in range(6):
            closes.append(closes[-1] * 0.999)      # 走平回落，确认右峰
        out = M.top_state(closes, span=3)
        self.assertIn(out['state'], (M.BLUNTING, M.STRUCTURE),
                      msg=f"实际 {out['state']}：{out}")
        self.assertGreater(out['peak_last']['price'], out['peak_prev']['price'])
        self.assertLess(out['peak_last']['dif'], out['peak_prev']['dif'])


class RenderTests(unittest.TestCase):
    import report_renderer as R

    MD = {'index_macd_60m': {
        'shanghai': {'name': '上证指数', 'state': 'blunting', 'label': '顶部钝化',
                     'bars': 128, 'params': {'span': 3, 'fast': 12, 'slow': 26, 'signal': 9},
                     'peak_prev': {'time': '2026-08-11 14:00', 'price': 3400.0, 'dif': 32.0},
                     'peak_last': {'time': '2026-08-14 10:30', 'price': 3420.0, 'dif': 30.0}},
        'star50': {'name': '科创50', 'state': 'structure', 'label': '顶部结构形成',
                   'bars': 128, 'params': {'span': 3, 'fast': 12, 'slow': 26, 'signal': 9},
                   'peak_prev': {'time': '2026-08-11 14:00', 'price': 1788.0, 'dif': 22.0},
                   'peak_last': {'time': '2026-08-14 11:30', 'price': 1795.0, 'dif': 18.0}},
        'chinext': {'name': '创业板指', 'state': 'insufficient', 'label': '数据不足',
                    'bars': 0}}}

    def test_states_are_visually_distinct(self):
        html = self.R._render_macd_60m(self.MD)
        self.assertIn('顶部钝化', html)
        self.assertIn('顶部结构形成', html)
        # 钝化用琥珀、结构用红——同色就等于把预警和结论画等号
        self.assertIn('#b45309', html)
        self.assertIn('#b91c1c', html)

    def test_blunting_is_labelled_a_warning_not_a_confirmed_top(self):
        self.assertIn('预警', self.R._render_macd_60m(self.MD))

    def test_parameters_are_printed_because_the_definition_is_not_standard(self):
        html = self.R._render_macd_60m(self.MD)
        self.assertIn('MACD(12,26,9)', html)
        self.assertIn('swing high 左右各 3 根确认', html)
        self.assertIn('非标准定义', html)

    def test_both_peaks_are_shown_so_the_claim_can_be_checked(self):
        html = self.R._render_macd_60m(self.MD)
        self.assertIn('3400.00', html)
        self.assertIn('3420.00', html)
        self.assertIn('DIF+32.00', html)

    def test_insufficient_series_are_dropped_not_rendered_as_no_divergence(self):
        html = self.R._render_macd_60m(self.MD)
        self.assertNotIn('创业板指', html)

    def test_all_insufficient_renders_nothing(self):
        md = {'index_macd_60m': {'a': {'state': 'insufficient'}}}
        self.assertEqual(self.R._render_macd_60m(md), '')

    def test_missing_key_renders_nothing(self):
        self.assertEqual(self.R._render_macd_60m({}), '')
        self.assertEqual(self.R._render_macd_60m(None), '')


class FetchWiringTests(unittest.TestCase):
    def test_the_morning_script_fetches_60m_and_stores_the_state(self):
        from pathlib import Path
        text = Path('fetch_market_data.py').read_text(encoding='utf-8')
        self.assertIn('from stock_report import macd_state', text)
        self.assertIn('"klt": "60"', text)
        self.assertIn('result["index_macd_60m"]', text)
        self.assertLess(text.index('result["index_macd_60m"]'),
                        text.index('json.dump(result'), '必须写盘前算完')


if __name__ == '__main__':
    unittest.main()
