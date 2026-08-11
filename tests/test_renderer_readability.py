"""渲染端可读性：把已写在文本里的结构翻译成视觉层级。

背景：一期午报渲染进邮件的正文约 1.6 万字，risk_warnings 12 条平均 275 字，
全部平铺。当天唯一真正的市场风险（CPI）被 11 条数据口径说明埋在中间。
"""
import unittest

import report_renderer as R


class RichTextTests(unittest.TestCase):
    def test_lead_marker_becomes_subheading(self):
        html = R._rich_text('【盘中主线】CPO三龙头资金回流。')
        self.assertIn('<div class="subhead">盘中主线</div>', html)
        self.assertIn('CPO三龙头资金回流。', html)
        self.assertNotIn('【盘中主线】', html)

    def test_newlines_become_paragraphs(self):
        html = R._rich_text('第一段。\n第二段。\n\n第三段。')
        self.assertEqual(html.count('class="para"'), 3)

    def test_text_is_never_altered(self):
        text = '【标题】正文含数字 3956.48 与符号 +2.91%。'
        self.assertIn('正文含数字 3956.48 与符号 +2.91%。', R._rich_text(text))

    def test_empty_input(self):
        self.assertEqual(R._rich_text(''), '')
        self.assertEqual(R._rich_text(None), '')

    def test_split_lead_without_marker(self):
        self.assertEqual(R._split_lead('没有标题的正文'), (None, '没有标题的正文'))


class PositionExtractionTests(unittest.TestCase):
    def test_extracts_range_from_a_long_paragraph(self):
        # 实测形状：position 是 300 字论述，截断只会得到半句话
        text = ('总仓位建议35-50%（较今日早报的40-55%下调5个百分点，理由是早报据以'
                '给出结构建议的强弱排序已在盘中被证伪）')
        self.assertEqual(R._position_range(text), '35-50%')

    def test_single_percentage(self):
        self.assertEqual(R._position_range('维持 60% 仓位'), '60%')

    def test_short_text_passes_through(self):
        self.assertEqual(R._position_range('空仓观望'), '空仓观望')

    def test_empty(self):
        self.assertEqual(R._position_range(''), '')


class RiskClassificationTests(unittest.TestCase):
    """分类依据是分析层自己写的【】标题。"""

    CAVEATS = ('数据编排状态·逐字说明', '数据分层·最重要的一条', 'A股指数层完全缺失',
               '观察池个股无今日盘中价', '量比口径替换声明', '技术指标全部为昨日基准',
               '板块广度存在跨板块重复计算', '港股与韩股为盘中而非收盘',
               '新闻类证据未能逐字二次核验', '上一期午报闭环断裂',
               '单半日证据不足以宣布主线切换')
    RISKS = ('事件风险', '政策风险', '流动性风险')

    def test_2026_08_11_caveats_all_classified_as_caveats(self):
        for title in self.CAVEATS:
            self.assertTrue(R._is_caveat(title, ''), msg=f'{title} 被误判为市场风险')

    # 早报不写【】小标题，说法与午报不同，分类器更依赖这几个词
    MORNING_CAVEATS = ('数据编排状态·逐字说明', 'A股指数原始数据缺失·重要',
                       '个股行情为收盘回补，非实时', '港美股个股数据完全不可得',
                       '一条已知的来源冲突', '上一期归档缺口', '日股今日无有效时点')
    MORNING_RISKS = ('事件风险·美国7月CPI', '事件风险·美方审查境外算力租赁', '高位风险')
    # 这些是行情用语，长得像数据词但必须留在显眼处
    MARKET_TERMS = ('跳空缺口未回补', '缺口回补压力', '量能萎缩', '换手率异动')

    def test_real_risks_stay_prominent(self):
        for title in self.RISKS:
            self.assertFalse(R._is_caveat(title, ''), msg=f'{title} 被误判为数据口径')

    def test_morning_report_wording_also_classified(self):
        for title in self.MORNING_CAVEATS:
            self.assertTrue(R._is_caveat(title, ''), msg=f'{title} 被误判为市场风险')
        for title in self.MORNING_RISKS:
            self.assertFalse(R._is_caveat(title, ''), msg=f'{title} 被误判为数据口径')

    def test_market_vocabulary_is_never_swallowed_as_a_caveat(self):
        """「归档缺口」是数据问题，「跳空缺口」是市场风险——不能因为都有"缺口"就一起埋掉。"""
        for title in self.MARKET_TERMS:
            self.assertFalse(R._is_caveat(title, ''), msg=f'{title} 被误判为数据口径')

    def test_renderer_splits_into_two_blocks(self):
        analysis = {'risk_warnings': [
            '【数据分层·最重要的一条】本次latest内部存在两个时点。',
            '【事件风险】美国7月CPI将于8月12日公布。',
            '【技术指标全部为昨日基准】基准日均为2026-08-10收盘。',
        ]}
        html = R._render_risk_warnings(analysis)
        self.assertEqual(html.count('class="risk-item"'), 1)      # 只有 CPI
        self.assertEqual(html.count('class="caveat-item"'), 2)
        self.assertIn('数据口径与方法说明（2 条）', html)

    def test_no_warnings_renders_nothing(self):
        self.assertEqual(R._render_risk_warnings({'risk_warnings': []}), '')


class TldrTests(unittest.TestCase):
    def analysis(self, **extra):
        data = {
            'prediction': {'label': '权重驱动的窄幅修复而非普涨', 'confidence': 55},
            'trading_advice': {'position': '总仓位建议35-50%（较早报下调5个百分点）'},
            'risk_warnings': [
                '【数据分层·最重要的一条】本次latest存在两个时点。',
                '【事件风险】美国7月CPI将于8月12日20:30公布。',
            ],
        }
        data.update(extra)
        return data

    def market_data(self, **extra):
        data = {'data_quality': {'provenance': {
            'by_source': {'klines_cache': 50, 'efinance_backfill': 1},
            'fallback_rows': 51, 'seconds_behind_market': 84411.8},
            'crosscheck': {'checked_pairs': 0, 'status': 'unchecked'}}}
        data.update(extra)
        return data

    def test_card_leads_with_the_conclusion(self):
        html = R._render_tldr(self.analysis(), self.market_data())
        self.assertIn('权重驱动的窄幅修复', html)
        self.assertIn('先看这里', html)

    def test_position_is_the_number_not_the_essay(self):
        html = R._render_tldr(self.analysis(), self.market_data())
        self.assertIn('>35-50%<', html)
        self.assertNotIn('较早报下调5个百分点', html)

    def test_top_risk_skips_data_caveats(self):
        html = R._render_tldr(self.analysis(), self.market_data())
        self.assertIn('事件风险', html)
        self.assertNotIn('数据分层', html)

    def test_badges_expose_the_fallback_situation(self):
        html = R._render_tldr(self.analysis(), self.market_data())
        self.assertIn('0/51 为当日实时', html)
        self.assertIn('数据落后市场 23.4 小时', html)
        self.assertIn('未做双源交叉验证', html)
        self.assertIn('大盘指数本期缺失', html)

    def test_healthy_data_shows_green_badges(self):
        md = {'realtime_indices': {'sh000001': {'price': 3956}},
              'data_quality': {'provenance': {
                  'by_source': {'sina': 51}, 'fallback_rows': 0,
                  'seconds_behind_market': 30},
                  'crosscheck': {'checked_pairs': 14, 'checked_conflicts': 0,
                                 'status': 'agreed'}}}
        html = R._render_tldr(self.analysis(), md)
        self.assertIn('badge-ok', html)
        self.assertNotIn('大盘指数本期缺失', html)

    def test_legacy_crosscheck_without_checked_pairs_claims_nothing(self):
        # 旧格式 {"checked_conflicts":0,"max_diff_pct":0.0} 既不能说一致也不能说未检查
        md = self.market_data()
        md['data_quality']['crosscheck'] = {'checked_conflicts': 0, 'max_diff_pct': 0.0}
        html = R._render_tldr(self.analysis(), md)
        self.assertNotIn('双源已核对', html)
        self.assertNotIn('未做双源交叉验证', html)

    def test_no_analysis_renders_nothing(self):
        self.assertEqual(R._render_tldr(None, {}), '')


if __name__ == '__main__':
    unittest.main()
