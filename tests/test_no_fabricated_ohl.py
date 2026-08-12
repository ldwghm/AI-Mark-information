"""回填价不得伪造日内高低，渲染端不得把缺失印成数字。

病根：klines_cache 只存 closes 与 volumes，没有 OHLC。cloud_fetch 的缓存
分支曾写 `o = h = l = close`，于是 2026-08-11 午报邮件印出 51 行
「最高＝最低＝现价」——江波龙涨 6.70%，最高 412.50、最低 412.50。
一个伪造值和一根真十字星在 JSON 里无法区分，读者也无从分辨。
"""
import unittest

import report_renderer as rr


def _rt(name, current, chg, high=None, low=None, volume=None):
    return {'name': name, 'current': current, 'change_pct': chg,
            'high': high, 'low': low, 'volume': volume}


class FabricatedRangeTests(unittest.TestCase):
    def test_missing_high_low_renders_as_dash_not_zero(self):
        """_num() 把 None 折成 0，会印出 0.00——与真实的 0 元无法区分。"""
        self.assertEqual(rr._price_cell(None), '—')
        self.assertEqual(rr._price_cell(''), '—')
        self.assertEqual(rr._price_cell('-'), '—')
        self.assertEqual(rr._price_cell('abc'), '—')
        self.assertEqual(rr._price_cell(412.5), '412.50')
        self.assertEqual(rr._price_cell(0), '0.00')

    def test_pool_without_any_range_drops_the_two_columns(self):
        rows = [_rt('江波龙', 412.5, 6.7), _rt('中微公司', 389.99, 6.08)]
        self.assertFalse(rr._has_intraday_range(rows))
        html = rr.render_afternoon_report({'watchlist_rt': rows}, {}, '2026-08-11')
        self.assertNotIn('<th>最高</th>', html)
        self.assertNotIn('<th>最低</th>', html)
        self.assertIn('日内振幅本期不可得', html)

    def test_pool_with_real_range_keeps_the_columns(self):
        rows = [_rt('江波龙', 412.5, 6.7, high=418.0, low=401.2)]
        self.assertTrue(rr._has_intraday_range(rows))
        html = rr.render_afternoon_report({'watchlist_rt': rows}, {}, '2026-08-11')
        self.assertIn('<th>最高</th>', html)
        self.assertIn('418.00', html)
        self.assertIn('401.20', html)

    def test_partial_range_shows_dash_only_for_the_missing_rows(self):
        rows = [_rt('江波龙', 412.5, 6.7, high=418.0, low=401.2),
                _rt('中微公司', 389.99, 6.08)]
        html = rr.render_afternoon_report({'watchlist_rt': rows}, {}, '2026-08-11')
        self.assertIn('<th>最高</th>', html)
        self.assertIn('418.00', html)
        self.assertIn('—', html)

    def test_close_masquerading_as_ohlc_is_detected_as_no_range(self):
        """历史归档与其他抓取路径仍可能写 high==low==现价。

        渲染端分辨不出伪造值和真十字星，但整池 51 行全零振幅是不可能的——
        按"没有振幅数据"处理，好过原样印出去。
        """
        rows = [_rt('江波龙', 412.5, 6.7, high=412.5, low=412.5),
                _rt('中微公司', 389.99, 6.08, high=389.99, low=389.99),
                _rt('拓荆科技', 728.0, 5.41, high=728.0, low=728.0)]
        self.assertFalse(rr._has_intraday_range(rows))
        html = rr.render_afternoon_report({'watchlist_rt': rows}, {}, '2026-08-11')
        self.assertNotIn('<th>最高</th>', html)

    def test_one_flat_row_among_real_ones_keeps_the_columns(self):
        """真涨停股零振幅是合法数据，不能因为它把整列摘掉。"""
        rows = [_rt('江波龙', 412.5, 10.0, high=412.5, low=412.5),
                _rt('中微公司', 389.99, 6.08, high=395.0, low=380.0)]
        self.assertTrue(rr._has_intraday_range(rows))

    def test_the_2026_08_11_regression_never_returns(self):
        """当天真实形态：整池 high==low==current。修好后不该再出现这种一行。"""
        rows = [_rt('江波龙', 412.5, 6.7), _rt('拓荆科技', 728.0, 5.41)]
        html = rr.render_afternoon_report({'watchlist_rt': rows}, {}, '2026-08-11')
        # 现价出现一次即可，不该在最高/最低列里再出现两次
        self.assertEqual(html.count('412.50'), 1)
        self.assertEqual(html.count('728.00'), 1)


class BackfillProducesNullsTests(unittest.TestCase):
    """抓数端：拿不到实时报价时，缺失字段必须是 None 而不是收盘价或 0。"""

    def test_cache_branch_source_has_no_fabricated_assignment(self):
        import inspect
        from stock_report import cloud_fetch
        src = inspect.getsource(cloud_fetch)
        self.assertNotIn('o = h = l = close', src)
        self.assertNotIn('amt = close * vol', src)
        self.assertIn('o = h = l = None', src)

    def test_efinance_backfill_row_carries_no_invented_numbers(self):
        import inspect
        from stock_report import cloud_fetch
        src = inspect.getsource(cloud_fetch)
        self.assertNotIn("'open': price, 'high': price, 'low': price", src)
        self.assertNotIn("'volume': 0, 'amount': 0", src)


if __name__ == '__main__':
    unittest.main()
