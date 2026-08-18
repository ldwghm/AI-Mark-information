"""日线兜底：push2his 挂了也要有 OHLC。

2026-08-18 三次 Actions 运行里两次 push2his 整批失败（指数 0 bars、观察池
10 只全 0），technicals 于是静默退回 klines_cache。cache 由 yfinance 维护、
天天成功，所以"有数"——但它**只存收盘价与成交量，没有 OHLC**，这正是
playbook 规则 1 记的那次「51 行最高＝最低＝现价」的来源。

顺带修掉一个一直没人提的：日线只取 25 根，而 MACD(12,26,9) 需要 35 根，
所以 index_technicals 的 macd/macd_hist **每天都是 null**、macd_status
恒为「未知」。
"""
import unittest
from unittest import mock

import fetch_market_data as F
from technical_indicators import compute_stock_technical, parse_klines


class TickerMappingTests(unittest.TestCase):
    def test_shanghai_and_shenzhen(self):
        self.assertEqual(F.yf_ticker('1.600519'), '600519.SS')
        self.assertEqual(F.yf_ticker('0.300308'), '300308.SZ')
        self.assertEqual(F.yf_ticker('1.688256'), '688256.SS')
        self.assertEqual(F.yf_ticker('0.002230'), '002230.SZ')

    def test_indices_map_too(self):
        self.assertEqual(F.yf_ticker('1.000001'), '000001.SS')
        self.assertEqual(F.yf_ticker('0.399006'), '399006.SZ')

    def test_beijing_exchange_has_no_yahoo_ticker(self):
        """北交所 Yahoo 没有——返回 None，让调用方老实报 unavailable。"""
        for secid in ('0.831010', '0.430047', '0.920045'):
            self.assertIsNone(F.yf_ticker(secid), msg=secid)

    def test_malformed_input(self):
        for bad in ('', None, '600519', '2.600519', '1.abc'):
            self.assertIsNone(F.yf_ticker(bad), msg=repr(bad))


class LineFormatTests(unittest.TestCase):
    """兜底行必须能被现有 parse_klines 直接吃下，下游一行不用改。"""

    class Col:
        def __init__(self, m):
            self.m = m

        def __getitem__(self, k):
            return self.m[k]

    class Frame:
        def __init__(self, rows):
            self.index = [r[0] for r in rows]
            self._rows = {r[0]: r[1:] for r in rows}

        def __len__(self):
            return len(self.index)

        def __getitem__(self, name):
            i = ('Open', 'High', 'Low', 'Close', 'Volume').index(name)
            return LineFormatTests.Col({k: v[i] for k, v in self._rows.items()})

    ROWS = [('2026-08-14', 900.0, 920.0, 895.0, 910.0, 1000),
            ('2026-08-15', 912.0, 940.0, 905.0, 935.0, 1200),
            ('2026-08-18', 930.0, 1009.0, 971.81, 988.1, 22073870)]

    def lines(self):
        with mock.patch.dict('sys.modules', {'yfinance': mock.MagicMock(
                download=mock.Mock(return_value=self.Frame(self.ROWS)))}):
            return F.fetch_daily_klines_yf('300308.SZ')

    def test_field_order_matches_eastmoney(self):
        """日期,开,收,高,低,量,额,振幅,涨跌幅,涨跌额,换手率"""
        first = self.lines()[0].split(',')
        self.assertEqual(first[0], '2026-08-14')
        self.assertEqual(float(first[1]), 900.0)      # open
        self.assertEqual(float(first[2]), 910.0)      # close
        self.assertEqual(float(first[3]), 920.0)      # high
        self.assertEqual(float(first[4]), 895.0)      # low

    def test_amount_is_left_empty_not_invented(self):
        """Yahoo 不给成交额。空着比编一个 close*volume 诚实。"""
        for line in self.lines():
            self.assertEqual(line.split(',')[6], '')

    def test_parse_klines_reads_the_empty_amount_as_none_and_keeps_the_row(self):
        rows = parse_klines(self.lines())
        self.assertEqual(len(rows), 3)
        self.assertIsNone(rows[-1]['amount'])
        self.assertEqual(rows[-1]['high'], 1009.0)

    def test_chg_pct_is_computed_from_the_previous_close(self):
        second = self.lines()[1].split(',')
        self.assertAlmostEqual(float(second[8]), round((935.0 - 910.0) / 910.0 * 100, 2))

    def test_first_bar_has_no_previous_close_so_change_is_zero_not_invented(self):
        self.assertEqual(self.lines()[0].split(',')[8], '0')

    def test_prices_are_rounded(self):
        self.assertNotIn('988.0999755859375', '\n'.join(self.lines()))


class FallbackOrderTests(unittest.TestCase):
    def test_eastmoney_wins_when_it_answers(self):
        """东财给完整 OHLC＋成交额，能用就用它。"""
        with mock.patch.object(F, 'fetch_daily_klines_em', return_value=['x']), \
             mock.patch.object(F, 'fetch_daily_klines_yf') as yf:
            lines, source = F.fetch_daily_klines('0.300308', '300308.SZ')
        self.assertEqual((lines, source), (['x'], 'eastmoney'))
        yf.assert_not_called()

    FULL = [f'r{i}' for i in range(60)]      # ≥ min_bars，不会掉进 60m 聚合分支

    def test_yfinance_takes_over_when_push2his_returns_nothing(self):
        with mock.patch.object(F, 'fetch_daily_klines_em', return_value=[]), \
             mock.patch.object(F, 'fetch_daily_klines_yf', return_value=self.FULL):
            self.assertEqual(F.fetch_daily_klines('0.300308', '300308.SZ'),
                             (self.FULL, 'yfinance'))

    def test_both_down_is_reported_not_silently_empty(self):
        with mock.patch.object(F, 'fetch_daily_klines_em', return_value=[]), \
             mock.patch.object(F, 'fetch_daily_klines_yf', return_value=[]), \
             mock.patch.object(F, 'fetch_daily_from_60m_yf', return_value=[]):
            self.assertEqual(F.fetch_daily_klines('0.300308', '300308.SZ'),
                             ([], 'unavailable'))

    def test_source_is_stamped_on_the_watchlist_entry(self):
        with mock.patch.object(F, 'fetch_daily_klines_em', return_value=[]), \
             mock.patch.object(F, 'fetch_daily_klines_yf', return_value=self.FULL):
            entry = F.fetch_stock_kline('0.300308', '中际旭创')
        self.assertEqual(entry['klines_source'], 'yfinance')

    def test_index_without_a_ticker_stays_eastmoney_only(self):
        with mock.patch.object(F, 'fetch_daily_klines_em', return_value=['x']):
            entry = F.fetch_index_kline('1.000001', '上证指数')
        self.assertEqual(entry['klines_source'], 'eastmoney')


class SixtyMinuteAggregationTests(unittest.TestCase):
    """Yahoo 对创业板指与科创50 没有日线历史，只回今天一根。

    2026-08-18 实测：period 取 3mo/6mo/1y、start/end、Ticker.history 四种问法
    都是 1 行，而同一 ticker 的 60 分钟有 110 根。上证与深证成指日线正常。
    """

    class Col(dict):
        pass

    class Frame:
        def __init__(self, rows):
            self.index = [r[0] for r in rows]
            self._rows = {r[0]: r[1:] for r in rows}

        def __len__(self):
            return len(self.index)

        def __getitem__(self, name):
            i = ('Open', 'High', 'Low', 'Close', 'Volume').index(name)
            return SixtyMinuteAggregationTests.Col(
                {k: v[i] for k, v in self._rows.items()})

    ROWS = [
        # day 1 —— 含一根 11:30 午休切片，必须被剔除
        ('2026-08-17 09:30', 100.0, 105.0, 99.0, 104.0, 10),
        ('2026-08-17 10:30', 104.0, 108.0, 103.0, 107.0, 20),
        ('2026-08-17 11:30', 107.0, 999.0, 1.0, 107.0, 1),     # 午休切片，极值是脏的
        ('2026-08-17 13:30', 107.0, 110.0, 106.0, 109.0, 30),
        ('2026-08-17 14:30', 109.0, 111.0, 100.0, 101.0, 40),
        # day 2
        ('2026-08-18 09:30', 102.0, 106.0, 101.0, 105.0, 50),
        ('2026-08-18 14:30', 105.0, 120.0, 104.0, 118.0, 60),
    ]

    def lines(self):
        with mock.patch.object(F, 'fetch_index_60m_yf',
                               return_value=self.Frame(self.ROWS)):
            return F.fetch_daily_from_60m_yf('000688.SS')

    def test_one_line_per_trading_day(self):
        self.assertEqual([l.split(',')[0] for l in self.lines()],
                         ['2026-08-17', '2026-08-18'])

    def test_open_is_first_bar_and_close_is_last(self):
        first = self.lines()[0].split(',')
        self.assertEqual(float(first[1]), 100.0)   # 首根开
        self.assertEqual(float(first[2]), 101.0)   # 末根收

    def test_lunch_slice_is_excluded_from_the_daily_extremes(self):
        """午休切片的 999/1 是脏值，混进当日最高最低就毁了支撑压力位。"""
        first = self.lines()[0].split(',')
        self.assertEqual(float(first[3]), 111.0)   # 高，不是 999
        self.assertEqual(float(first[4]), 99.0)    # 低，不是 1

    def test_volume_is_summed_excluding_the_lunch_slice(self):
        self.assertEqual(int(self.lines()[0].split(',')[5]), 10 + 20 + 30 + 40)

    def test_amount_stays_empty(self):
        for line in self.lines():
            self.assertEqual(line.split(',')[6], '')

    def test_chg_pct_uses_the_previous_day_close(self):
        second = self.lines()[1].split(',')
        self.assertAlmostEqual(float(second[8]), round((118.0 - 101.0) / 101.0 * 100, 2))

    def test_no_frame_yields_nothing(self):
        with mock.patch.object(F, 'fetch_index_60m_yf', return_value=None):
            self.assertEqual(F.fetch_daily_from_60m_yf('000688.SS'), [])


class ThinDailyHistoryTests(unittest.TestCase):
    """"拿到 1 根"和"没拿到"一样没用——不能因为列表非空就当成功。"""

    def test_a_single_daily_bar_falls_through_to_aggregation(self):
        with mock.patch.object(F, 'fetch_daily_klines_em', return_value=[]), \
             mock.patch.object(F, 'fetch_daily_klines_yf', return_value=['only-one']), \
             mock.patch.object(F, 'fetch_daily_from_60m_yf',
                               return_value=[f'r{i}' for i in range(60)]):
            lines, source = F.fetch_daily_klines('1.000688', '000688.SS')
        self.assertEqual(source, 'yfinance_60m_agg')
        self.assertEqual(len(lines), 60)

    def test_enough_daily_bars_skips_aggregation(self):
        with mock.patch.object(F, 'fetch_daily_klines_em', return_value=[]), \
             mock.patch.object(F, 'fetch_daily_klines_yf',
                               return_value=[f'r{i}' for i in range(60)]), \
             mock.patch.object(F, 'fetch_daily_from_60m_yf') as agg:
            _lines, source = F.fetch_daily_klines('1.000001', '000001.SS')
        self.assertEqual(source, 'yfinance')
        agg.assert_not_called()

    def test_aggregation_that_is_no_better_does_not_win(self):
        with mock.patch.object(F, 'fetch_daily_klines_em', return_value=[]), \
             mock.patch.object(F, 'fetch_daily_klines_yf', return_value=['a', 'b']), \
             mock.patch.object(F, 'fetch_daily_from_60m_yf', return_value=['c']):
            lines, source = F.fetch_daily_klines('1.000688', '000688.SS')
        self.assertEqual((lines, source), (['a', 'b'], 'yfinance'))

    def test_no_ticker_means_unavailable_not_a_crash(self):
        """北交所：yf_ticker 返回 None。"""
        with mock.patch.object(F, 'fetch_daily_klines_em', return_value=[]):
            self.assertEqual(F.fetch_daily_klines('0.831010', None),
                             ([], 'unavailable'))


class BarCountTests(unittest.TestCase):
    def test_sixty_bars_is_enough_for_macd(self):
        """25 根算不出 MACD(12,26,9)：slow+signal=35。"""
        self.assertGreaterEqual(F.DAILY_BARS, 35)

    def test_twenty_five_bars_really_did_yield_no_macd(self):
        """回归说明：这就是 index_technicals 的 macd 每天为 null 的原因。"""
        closes = [f'2026-08-{i:02d},10,{10 + i * 0.1},11,9,100,1000,1,1,0.1,0.5'
                  for i in range(1, 26)]
        self.assertIsNone(compute_stock_technical(closes)['macd_hist'])

    def test_sixty_bars_produce_a_macd(self):
        lines = [f'2026-{1 + i // 28:02d}-{1 + i % 28:02d},10,{10 + i * 0.1},'
                 f'11,9,100,1000,1,1,0.1,0.5' for i in range(F.DAILY_BARS)]
        self.assertIsNotNone(compute_stock_technical(lines)['macd_hist'])


class ParseKlinesToleranceTests(unittest.TestCase):
    GOOD = '2026-08-18,930.0,988.1,1009.0,971.81,22073870,1234567,3.72,-1.29,-12.93,1.1'

    def test_full_eastmoney_line_is_unchanged(self):
        row = parse_klines([self.GOOD])[0]
        self.assertEqual(row['amount'], 1234567.0)
        self.assertEqual(row['chg_pct'], -1.29)

    def test_row_survives_a_missing_amount(self):
        row = parse_klines([self.GOOD.replace(',1234567,', ',,')])[0]
        self.assertIsNone(row['amount'])
        self.assertEqual(row['close'], 988.1)

    def test_broken_ohlc_still_drops_the_row(self):
        self.assertEqual(parse_klines(['2026-08-18,x,y,z,w,1,2,3,4']), [])

    def test_short_line_is_dropped(self):
        self.assertEqual(parse_klines(['2026-08-18,1,2']), [])


if __name__ == '__main__':
    unittest.main()
