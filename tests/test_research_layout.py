"""研报式版面：结论在前，论据在后，分析层写的东西不再被丢掉。

背景：playbook Step 2 强制模型每期产出 forecast_ledger_entry、thesis_updates、
technical/fundamental/sentiment_analysis、anomaly_investigation、evidence_log、
reflection。2026-08-13 早报实测这些字段全部填满（11 条 thesis、3 档情景、
17 条证据、5 条异常），而渲染端一个都没取——模型每天写的分析有一半只进了归档。

同时早报从未调用 `_render_prediction`（只有午报调用），prediction.reasons
每天写、每天丢，只有 label 漏进顶部摘要卡。
"""
import json
import unittest

import report_renderer as R


ANALYSIS = {
    'date': '2026-08-13',
    'market_summary': '权重驱动的窄幅修复。',
    'review': '上期预测CPO走强，实际分化。',
    'reflection': {'prior_result': 'partial', 'error_type': '遗漏催化剂',
                   'lesson': '未跟踪海外算力资本开支指引。',
                   'rule_update': '每期检查三家云厂capex口径。'},
    'key_insights': ['光模块成交额占AI板块42%。', '主力净流入连续3日为负。'],
    'prediction': {'label': '窄幅震荡', 'confidence': 55, 'color': '#d97706',
                   'reasons': ['量能未能放大', '外围隔夜收跌']},
    'trading_advice': {'style': '防守', 'position': '总仓位35-50%',
                       'rationale': '等待量能确认。'},
    'forecast_ledger_entry': {
        'horizon': '1d',
        'next_check': '2026-08-14 收盘量能',
        'scenarios': [
            {'name': 'base', 'probability': 52,
             'conditions': ['成交额维持1.8万亿以上'],
             'invalidation': ['跌破3900且放量']},
            {'name': 'bull', 'probability': 30,
             'conditions': ['CPO龙头重新领涨'], 'invalidation': ['主力净流出扩大']},
            {'name': 'bear', 'probability': 18,
             'conditions': ['外围大幅回落'], 'invalidation': ['北向转为净买入']},
        ]},
    'technical_analysis': {'short_term': '短期承压。', 'medium_term': '中期多头未破。',
                           'long_term': '长期趋势向上。'},
    'fundamental_analysis': {'status': 'partial', 'summary': '仅两家披露指引。',
                             'evidence_ids': ['E1']},
    'sentiment_analysis': {'hard_data': '涨跌家数2100/3000。',
                           'social_signal': '雪球有传闻称某厂扩产。', 'confidence': 45},
    'anomaly_investigation': [
        {'signal': '某股放量跌7%', 'confirmed_causes': [],
         'candidate_causes': ['解禁临近'], 'unresolved': ['是否有大宗折价']}],
    'thesis_updates': [
        {'thesis_id': 'T1-CPO主线', 'status': 'weakened',
         'evidence_ids': ['E1', 'E2'], 'invalidation': '连续两日主力净流入转正'},
        {'thesis_id': 'T2-算力租赁', 'status': 'carried_forward', 'evidence_ids': []}],
    'evidence_log': [
        {'id': 'E1', 'kind': 'hard_fact', 'source': '东方财富',
         'source_url': 'https://data.eastmoney.com/x', 'published_at': '2026-08-12T15:00:00',
         'claim': '光模块板块成交额1271亿。'},
        {'id': 'E2', 'kind': 'social_signal', 'source': '雪球用户',
         'source_url': '', 'published_at': '2026-08-13T07:10:00',
         'claim': '传闻某厂扩产。'}],
    'risk_warnings': ['【事件风险】美联储纪要8月20日公布。'],
    'hk_us_summary': '隔夜美股AI链回落。',
}


MARKET_DATA = {
    'indices': {'shanghai': {'name': '上证指数', 'price': 3946.68, 'chg': 0.32},
                'chinext': {'name': '创业板指', 'price': 3602.08, 'chg': 1.49}},
    'index_technicals': {'shanghai': {'ma_trend': '强势多头', 'macd_status': '多头',
                                      'rsi_12': 63.16, 'volume_ratio': 0.89,
                                      'volume_label': '正常'}},
    'watchlist_technicals': [{'name': '中际旭创', 'code': '300308', 'close': 921.0,
                              'chg_pct': 3.84, 'ma_trend': '强势空头', 'rsi_12': 38.62,
                              'macd_status': '空头排列', 'volume_ratio': 0.72,
                              'score': 20, 'score_label': '★'}],
    'capital_flow_top30': [{'f12': '300308', 'f14': '中际旭创', 'f3': 3.84,
                            'f62': 2595589888.0, 'f6': 28408443493.0}],
    'ai_boards': [{'f14': '光模块', 'f3': 2.1, 'f12': 'BK1660'}],
}


def _body(html):
    """只在 <body> 之后找。CSS 注释里也写中文（"附录压到灰"），
    直接在整页 find 会被样式表里的字骗到——第一版测试就是这么假失败的。"""
    marker = '</head>'
    return html[html.find(marker) + len(marker):] if marker in html else html


def _order(html, *needles):
    """返回各片段在正文中的下标，缺失记 -1。"""
    body = _body(html)
    return [body.find(n) for n in needles]


class ScenarioTests(unittest.TestCase):
    def test_probabilities_and_both_condition_columns_render(self):
        html = R._render_scenarios(ANALYSIS)
        self.assertIn('52%', html)
        self.assertIn('成立条件', html)
        self.assertIn('失效条件', html)
        self.assertIn('跌破3900且放量', html)

    def test_english_scenario_names_are_translated(self):
        html = R._render_scenarios(ANALYSIS)
        for cn in ('基准', '偏多', '偏空'):
            self.assertIn(cn, html)

    def test_horizon_and_next_check_are_shown(self):
        """没有下次检验点，这条预测第二天就无法机械判对错。"""
        html = R._render_scenarios(ANALYSIS)
        self.assertIn('1d', html)
        self.assertIn('2026-08-14 收盘量能', html)

    def test_missing_conditions_say_so_rather_than_render_blank(self):
        html = R._render_scenarios({'forecast_ledger_entry': {
            'scenarios': [{'name': 'base', 'probability': 100}]}})
        self.assertIn('未列出', html)

    def test_conditions_given_as_a_bare_string_still_render(self):
        html = R._render_scenarios({'forecast_ledger_entry': {
            'scenarios': [{'name': 'base', 'probability': 100, 'conditions': '量能放大'}]}})
        self.assertIn('量能放大', html)

    def test_no_ledger_renders_nothing(self):
        self.assertEqual(R._render_scenarios({}), '')
        self.assertEqual(R._render_scenarios(None), '')


class ViewMatrixTests(unittest.TestCase):
    def test_three_faces_are_all_present(self):
        html = R._render_view_matrix(ANALYSIS)
        for label in ('技术面', '基本面', '情绪面'):
            self.assertIn(label, html)

    def test_social_signal_is_marked_unverified(self):
        """playbook 边界 3：传闻不得当成事实。视觉上也必须分得开。"""
        html = R._render_view_matrix(ANALYSIS)
        self.assertIn('未证实', html)
        self.assertIn('雪球有传闻称某厂扩产。', html)

    def test_fundamental_status_is_surfaced(self):
        """status=partial 时说"基本面支持"和 verified 是两回事。"""
        self.assertIn('partial', R._render_view_matrix(ANALYSIS))

    def test_empty_input_renders_nothing(self):
        self.assertEqual(R._render_view_matrix({}), '')
        self.assertEqual(R._render_view_matrix(None), '')


class AnomalyTests(unittest.TestCase):
    def test_candidate_causes_are_not_presented_as_confirmed(self):
        html = R._render_anomalies(ANALYSIS)
        self.assertIn('已证实', html)
        self.assertIn('候选', html)
        self.assertIn('待核实', html)
        # 候选原因必须出现在"候选"标签之后，不能落进"已证实"那一格
        i_confirmed, i_candidate, i_cause = _order(html, '已证实', '候选', '解禁临近')
        self.assertLess(i_candidate, i_cause)
        self.assertLess(i_confirmed, i_candidate)

    def test_empty_bucket_shows_a_dash_not_a_hole(self):
        self.assertIn('—', R._render_anomalies(ANALYSIS))

    def test_signal_without_text_is_skipped(self):
        self.assertEqual(R._render_anomalies({'anomaly_investigation': [{'signal': ''}]}), '')


class ThesisTests(unittest.TestCase):
    def test_status_is_translated_and_ids_shown(self):
        html = R._render_thesis(ANALYSIS)
        self.assertIn('减弱', html)
        self.assertIn('延续', html)
        self.assertIn('T1-CPO主线', html)

    def test_invalidation_rides_along(self):
        self.assertIn('连续两日主力净流入转正', R._render_thesis(ANALYSIS))

    def test_no_updates_renders_nothing(self):
        self.assertEqual(R._render_thesis({}), '')


class EvidenceTests(unittest.TestCase):
    def test_hard_fact_and_social_signal_are_labelled_differently(self):
        html = R._render_evidence(ANALYSIS)
        self.assertIn('硬事实', html)
        self.assertIn('社交信号', html)

    def test_http_source_becomes_a_link_and_bare_source_does_not(self):
        html = R._render_evidence(ANALYSIS)
        self.assertIn('href="https://data.eastmoney.com/x"', html)
        self.assertNotIn('href=""', html)

    def test_every_evidence_id_is_reachable(self):
        """前面的 E1/E7 引用若查不到出处就是死链。"""
        html = R._render_evidence(ANALYSIS)
        for e in ANALYSIS['evidence_log']:
            self.assertIn(e['id'], html)


class ReflectionTests(unittest.TestCase):
    def test_prior_result_is_translated(self):
        self.assertIn('部分正确', R._render_reflection(ANALYSIS))

    def test_lesson_and_rule_update_are_shown(self):
        html = R._render_reflection(ANALYSIS)
        self.assertIn('遗漏催化剂', html)
        self.assertIn('每期检查三家云厂capex口径。', html)

    def test_unknown_result_does_not_crash(self):
        self.assertIn('未标注', R._render_reflection({'reflection': {'lesson': 'x'}}))


class MorningLayoutTests(unittest.TestCase):
    """版面顺序本身就是被测对象——研报的价值一半在排序。"""

    def html(self, analysis=None, market_data=None):
        return R.render_morning_report(MARKET_DATA if market_data is None else market_data,
                                       ANALYSIS if analysis is None else analysis,
                                       '2026-08-13')

    def test_conclusion_comes_before_the_evidence(self):
        html = self.html()
        verdict, scenario, boards, appendix = _order(
            html, '一、投资结论与操作建议', '二、情景与失效条件', '五之3', '附录')
        self.assertTrue(0 < verdict < scenario < boards < appendix,
                        f'顺序错了: {(verdict, scenario, boards, appendix)}')

    def test_overseas_markets_precede_a_shares(self):
        """playbook Step 2 要求自上而下推理，版面顺序不能和推理顺序相反。"""
        html = self.html()
        overseas, a_share = _order(html, '五之1', '五之2')
        self.assertTrue(0 < overseas < a_share)

    def test_morning_report_finally_renders_prediction_reasons(self):
        """这是回归测试：早报此前从不调用 _render_prediction。"""
        html = self.html()
        self.assertIn('量能未能放大', html)
        self.assertIn('外围隔夜收跌', html)

    def test_risk_section_is_its_own_block_not_buried_in_analysis(self):
        html = self.html()
        self.assertIn('八、风险提示', html)
        self.assertIn('美联储纪要8月20日公布。', html)

    def test_every_analysis_field_reaches_the_page(self):
        """回归：这些字段过去全被丢弃。"""
        html = self.html()
        for probe in ('跌破3900且放量',            # forecast_ledger_entry
                      'T1-CPO主线',                # thesis_updates
                      '中期多头未破。',             # technical_analysis
                      '仅两家披露指引。',           # fundamental_analysis
                      '涨跌家数2100/3000。',        # sentiment_analysis
                      '解禁临近',                  # anomaly_investigation
                      '光模块板块成交额1271亿。',   # evidence_log
                      '每期检查三家云厂capex口径。'):  # reflection
            self.assertIn(probe, html, msg=f'{probe} 没渲染出去')

    def test_empty_analysis_still_renders_a_page(self):
        html = self.html(analysis={})
        self.assertIn('<html', html)
        self.assertNotIn('一、投资结论', html)

    def test_none_analysis_does_not_crash(self):
        self.assertIn('<html', R.render_morning_report({}, None, '2026-08-13'))


class RealArchiveTests(unittest.TestCase):
    """拿真实归档跑一遍——构造数据永远比真数据干净。"""

    PATH = 'stock_report/data/archive/2026-08-13/morning'

    def load(self, name):
        try:
            with open(f'{self.PATH}/{name}', encoding='utf-8') as fh:
                return json.load(fh)
        except (OSError, ValueError):
            self.skipTest(f'{self.PATH}/{name} 不可用')

    def test_the_2026_08_13_bundle_renders_with_all_new_sections(self):
        html = R.render_morning_report(self.load('latest.json'),
                                       self.load('analysis.json'), '2026-08-13')
        for section in ('一、投资结论与操作建议', '二、情景与失效条件', '三、上期复盘',
                        '四、核心逻辑', '六、异常追因', '七、论点跟踪',
                        '八、风险提示', '附录'):
            self.assertIn(section, html, msg=f'{section} 缺失')


if __name__ == '__main__':
    unittest.main()
