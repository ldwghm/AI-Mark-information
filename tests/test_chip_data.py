"""筹码侧三个字段：坏了半年，因为失败被吞成空表。

`northbound` / `dragon_tiger` / `margin_trading` 从 08-11 起连续 5 期归档都是
`[]`。2026-08-18 直连东财复现，三个查询都返回 HTTP 200 + `success:false`：

    北向   code=9501  QUOTA_BALANCE返回字段不存在
    龙虎榜 code=9501  SECURITY_NAME返回字段不存在
    两融   code=9501  SECURITY_NAME返回字段不存在

东财改了列名，而 `data["result"]["data"] if ... else []` 把应用层错误
悄悄变成空列表，日志里一个字都没有。这组测试锁的就是"失败必须响"。
"""
import unittest
from unittest import mock

import fetch_market_data as F
import report_renderer as R


def api(success=True, rows=None, message=None):
    return {'success': success, 'message': message,
            'result': {'data': rows if rows is not None else []}}


class DatacenterGetTests(unittest.TestCase):
    def test_application_level_failure_is_returned_not_swallowed(self):
        """这就是病根：HTTP 200 但 success=false。"""
        with mock.patch.object(F, 'safe_get',
                               return_value=api(False, message='SECURITY_NAME返回字段不存在')):
            rows, err = F.datacenter_get('龙虎榜', {'reportName': 'X'})
        self.assertEqual(rows, [])
        self.assertIn('SECURITY_NAME返回字段不存在', err)

    def test_transport_failure_is_also_reported(self):
        with mock.patch.object(F, 'safe_get', return_value=None):
            rows, err = F.datacenter_get('龙虎榜', {'reportName': 'X'})
        self.assertEqual(rows, [])
        self.assertTrue(err)

    def test_success_returns_rows_and_no_error(self):
        with mock.patch.object(F, 'safe_get', return_value=api(True, [{'A': 1}])):
            rows, err = F.datacenter_get('x', {'reportName': 'X'})
        self.assertEqual(rows, [{'A': 1}])
        self.assertIsNone(err)

    def test_client_param_defaults_to_web(self):
        seen = {}

        def fake(url, params=None, timeout=20):
            seen.update(params or {})
            return api(True, [])

        with mock.patch.object(F, 'safe_get', side_effect=fake):
            F.datacenter_get('x', {'reportName': 'X'})
        self.assertEqual(seen.get('client'), 'WEB')


class DragonTigerTests(unittest.TestCase):
    LATEST = [{'TRADE_DATE': '2026-08-17 00:00:00'}]
    BOARD = [
        {'TRADE_DATE': '2026-08-17 00:00:00', 'SECURITY_CODE': '002156',
         'SECURITY_NAME_ABBR': '通富微电', 'CLOSE_PRICE': 60.1, 'CHANGE_RATE': 10.0,
         'BILLBOARD_NET_AMT': 1020979966.24, 'BILLBOARD_BUY_AMT': 1.2e9,
         'BILLBOARD_SELL_AMT': 1.8e8, 'DEAL_AMOUNT_RATIO': 29.1,
         'EXPLANATION': '日涨幅偏离值达到7%的前5只证券', 'TURNOVERRATE': 12.0,
         'D1_CLOSE_ADJCHRATE': 3.2},
        {'TRADE_DATE': '2026-08-17 00:00:00', 'SECURITY_CODE': '000620',
         'SECURITY_NAME_ABBR': '盈新发展', 'CHANGE_RATE': 10.0,
         'BILLBOARD_NET_AMT': 252986879.78, 'DEAL_AMOUNT_RATIO': 36.9,
         'EXPLANATION': '连续三个交易日内，涨幅偏离值累计达到20%的证券'},
        {'TRADE_DATE': '2026-08-17 00:00:00', 'SECURITY_CODE': '000620',
         'SECURITY_NAME_ABBR': '盈新发展', 'CHANGE_RATE': 10.0,
         'BILLBOARD_NET_AMT': 190727581.75, 'DEAL_AMOUNT_RATIO': 23.8,
         'EXPLANATION': '日换手率达到20%的前5只证券'},
    ]

    def run_fetch(self, board=None):
        seq = [api(True, self.LATEST), api(True, self.BOARD if board is None else board)]
        with mock.patch.object(F, 'safe_get', side_effect=seq):
            return F.fetch_dragon_tiger()

    def test_rows_are_mapped_to_the_new_column_names(self):
        block = self.run_fetch()
        first = block['rows'][0]
        self.assertEqual(first['name'], '通富微电')       # SECURITY_NAME_ABBR
        self.assertEqual(first['net_buy'], 1020979966.24)  # BILLBOARD_NET_AMT
        self.assertEqual(first['board_deal_ratio'], 29.1)

    def test_same_stock_listed_twice_is_merged_not_summed(self):
        """000620 当天两次上榜，成交重叠——相加会凭空多出 1.9 亿。"""
        rows = self.run_fetch()['rows']
        codes = [r['code'] for r in rows]
        self.assertEqual(len(codes), len(set(codes)))
        merged = next(r for r in rows if r['code'] == '000620')
        self.assertEqual(merged['board_count'], 2)
        self.assertEqual(merged['net_buy'], 252986879.78)   # 取较大的那条，不是 4.4 亿
        self.assertIn('日换手率达到20%的前5只证券', merged['also_listed_for'])

    def test_the_representative_row_is_the_largest_by_absolute_net(self):
        board = list(reversed(self.BOARD))   # 小额那条先到
        merged = next(r for r in self.run_fetch(board)['rows'] if r['code'] == '000620')
        self.assertEqual(merged['net_buy'], 252986879.78)
        self.assertEqual(merged['board_count'], 2)

    def test_trade_date_is_locked_to_the_latest_board(self):
        self.assertEqual(self.run_fetch()['trade_date'], '2026-08-17')

    def test_api_error_surfaces_as_status_error(self):
        seq = [api(True, self.LATEST), api(False, message='字段不存在')]
        with mock.patch.object(F, 'safe_get', side_effect=seq):
            block = F.fetch_dragon_tiger()
        self.assertEqual(block['status'], 'error')
        self.assertIn('字段不存在', block['note'])

    def test_no_latest_date_yields_unavailable_not_a_crash(self):
        with mock.patch.object(F, 'safe_get', return_value=api(True, [])):
            self.assertEqual(F.fetch_dragon_tiger()['status'], 'unavailable')


class MarginTradingTests(unittest.TestCase):
    LATEST = [{'DATE': '2026-08-17 00:00:00'}]
    ROWS = [{'DATE': '2026-08-17 00:00:00', 'SCODE': '300308', 'SECNAME': '中际旭创',
             'SPJ': 1001.03, 'ZDF': 6.15, 'RZJME': 929032883, 'RZYE': 31295324497,
             'RZYEZB': 2.81665043, 'RQYE': 1000.0}]

    def test_columns_are_mapped_from_the_renamed_fields(self):
        seq = [api(True, self.LATEST), api(True, self.ROWS)]
        with mock.patch.object(F, 'safe_get', side_effect=seq):
            row = F.fetch_margin_trading()['rows'][0]
        self.assertEqual(row['name'], '中际旭创')        # SECNAME, 不是 SECURITY_NAME
        self.assertEqual(row['chg_pct'], 6.15)           # ZDF, 不是 CHANGE_RATE
        self.assertEqual(row['fin_net_buy'], 929032883)

    def test_query_is_filtered_to_the_latest_disclosure_date(self):
        """旧写法按 RZYE 倒序、不锁日期，会捞出 2024 年的行。"""
        captured = []

        def fake(url, params=None, timeout=20):
            captured.append(params)
            return api(True, self.LATEST if len(captured) == 1 else self.ROWS)

        with mock.patch.object(F, 'safe_get', side_effect=fake):
            block = F.fetch_margin_trading()
        self.assertEqual(block['trade_date'], '2026-08-17')
        self.assertIn("DATE='2026-08-17 00:00:00'", captured[1]['filter'])
        self.assertEqual(captured[1]['sortColumns'], 'RZJME')

    def test_api_error_surfaces(self):
        seq = [api(True, self.LATEST), api(False, message='boom')]
        with mock.patch.object(F, 'safe_get', side_effect=seq):
            self.assertEqual(F.fetch_margin_trading()['status'], 'error')


class NorthboundTests(unittest.TestCase):
    ROWS = [{'TRADE_DATE': '2026-08-17 00:00:00', 'MUTUAL_TYPE': '001',
             'DEAL_AMT': 136873.91, 'NET_DEAL_AMT': None, 'FUND_INFLOW': None},
            {'TRADE_DATE': '2026-08-17 00:00:00', 'MUTUAL_TYPE': '003',
             'DEAL_AMT': 162796.96, 'NET_DEAL_AMT': None, 'FUND_INFLOW': None},
            {'TRADE_DATE': '2026-08-14 00:00:00', 'MUTUAL_TYPE': '001',
             'DEAL_AMT': 125496.5, 'NET_DEAL_AMT': None, 'FUND_INFLOW': None}]

    def block(self):
        with mock.patch.object(F, 'safe_get', return_value=api(True, self.ROWS)):
            return F.fetch_northbound()

    def test_only_the_latest_day_is_kept(self):
        rows = self.block()['rows']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['trade_date'] == '2026-08-17' for r in rows))

    def test_net_buy_stays_none_and_is_never_faked_from_turnover(self):
        """成交额不是净流入。交易所 2024-08 起就不发净买入了。"""
        for r in self.block()['rows']:
            self.assertIsNone(r['net_buy'])

    def test_raw_value_is_not_converted_while_the_unit_is_unverified(self):
        rows = self.block()['rows']
        self.assertEqual(rows[0]['deal_amt_raw'], 136873.91)
        self.assertIs(self.block()['unit_verified'], False)

    def test_channels_are_named(self):
        self.assertEqual({r['channel'] for r in self.block()['rows']},
                         {'沪股通', '深股通'})


class ChipRenderTests(unittest.TestCase):
    MD = {
        'dragon_tiger': {'status': 'ok', 'trade_date': '2026-08-17', 'rows': [
            {'code': '002156', 'name': '通富微电', 'chg_pct': 10.0,
             'net_buy': 1020979966.24, 'board_deal_ratio': 29.1, 'board_count': 2,
             'reason': '日涨幅偏离值达到7%的前5只证券',
             'also_listed_for': ['连续三日涨幅偏离30%']}]},
        'margin_trading': {'status': 'ok', 'trade_date': '2026-08-17', 'rows': [
            {'code': '300308', 'name': '中际旭创', 'chg_pct': 6.15,
             'fin_net_buy': 929032883, 'fin_balance': 31295324497,
             'fin_pct_of_float': 2.81665043}]},
        'northbound': {'status': 'partial', 'trade_date': '2026-08-17',
                       'unit_verified': False, 'rows': [
                           {'channel': '沪股通', 'deal_amt_raw': 136873.91, 'net_buy': None}]},
    }

    def test_all_three_render(self):
        html = R._render_chips(self.MD)
        for probe in ('通富微电', '中际旭创', '沪股通', '10.21亿', '9.29亿'):
            self.assertIn(probe, html)

    def test_multi_listing_is_flagged(self):
        self.assertIn('2次上榜', R._render_chips(self.MD))

    def test_unverified_unit_carries_a_visible_caveat(self):
        html = R._render_chips(self.MD)
        self.assertIn('单位未核实', html)
        self.assertNotIn('13.69亿', html)   # 不能擅自换算

    def test_fetch_error_is_shown_not_hidden(self):
        html = R._render_chips({'dragon_tiger': {'status': 'error', 'note': '字段不存在'}})
        self.assertIn('取数失败', html)
        self.assertIn('字段不存在', html)

    def test_legacy_empty_list_shape_still_renders(self):
        """归档里这三个字段是裸 []，渲染端不能因此炸掉。"""
        html = R._render_chips({'dragon_tiger': [], 'margin_trading': [],
                                'northbound': []})
        self.assertIn('本期无数据', html)

    def test_legacy_populated_list_shape_is_accepted(self):
        block = R._chip_block([{'code': '1', 'name': 'X', 'net_buy': 1e8}])
        self.assertEqual(block['status'], 'ok')

    def test_missing_keys_render_nothing_harmful(self):
        self.assertIsInstance(R._render_chips({}), str)
        self.assertIsInstance(R._render_chips(None), str)

    def test_section_appears_in_the_morning_report(self):
        html = R.render_morning_report(self.MD, {'market_summary': 'x'}, '2026-08-18')
        self.assertIn('筹码与杠杆', html)


if __name__ == '__main__':
    unittest.main()
