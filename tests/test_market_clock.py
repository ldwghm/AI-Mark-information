"""市场时钟：区分"数据旧"和"市场本来就没有更新的数据了"。

收盘价在收盘后距此刻可能好几个小时，但它就是最新可得——这种情况不该被判为
不新鲜。判据是落后于 last_market_tick 多少，而不是落后于此刻多少。
"""
import unittest
from datetime import datetime

from stock_report import timeutil

BJT = timeutil.BJT


def bjt(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=BJT)


class MarketOpenTests(unittest.TestCase):
    def test_open_during_morning_and_afternoon_sessions(self):
        self.assertTrue(timeutil.market_open_at(bjt(2026, 8, 10, 10, 0)))
        self.assertTrue(timeutil.market_open_at(bjt(2026, 8, 10, 14, 0)))

    def test_closed_during_lunch_and_after_hours(self):
        self.assertFalse(timeutil.market_open_at(bjt(2026, 8, 10, 12, 0)))
        self.assertFalse(timeutil.market_open_at(bjt(2026, 8, 10, 17, 16)))
        self.assertFalse(timeutil.market_open_at(bjt(2026, 8, 10, 8, 0)))

    def test_closed_on_weekend(self):
        self.assertFalse(timeutil.market_open_at(bjt(2026, 8, 9, 10, 0)))


class LastTickTests(unittest.TestCase):
    def test_during_session_latest_is_now(self):
        now = bjt(2026, 8, 10, 14, 0)
        self.assertEqual(timeutil.last_market_tick(now), now)

    def test_after_close_latest_is_todays_close(self):
        self.assertEqual(timeutil.last_market_tick(bjt(2026, 8, 10, 17, 16)),
                         bjt(2026, 8, 10, 15, 0))

    def test_during_lunch_latest_is_morning_close(self):
        self.assertEqual(timeutil.last_market_tick(bjt(2026, 8, 10, 12, 0)),
                         bjt(2026, 8, 10, 11, 30))

    def test_before_open_latest_is_previous_close(self):
        self.assertEqual(timeutil.last_market_tick(bjt(2026, 8, 10, 8, 0)),
                         bjt(2026, 8, 7, 15, 0))

    def test_weekend_falls_back_to_friday_close(self):
        self.assertEqual(timeutil.last_market_tick(bjt(2026, 8, 9, 10, 0)),
                         bjt(2026, 8, 7, 15, 0))


class BehindMarketTests(unittest.TestCase):
    def test_closing_price_after_close_is_not_behind(self):
        # 17:16 看 15:00 的收盘价：距此刻 2.3 小时，但落后市场 0
        behind = timeutil.seconds_behind_market(
            '2026-08-10T15:00:00+08:00', bjt(2026, 8, 10, 17, 16))
        self.assertEqual(behind, 0.0)

    def test_stale_snapshot_during_session_is_behind(self):
        behind = timeutil.seconds_behind_market(
            '2026-08-10T13:20:00+08:00', bjt(2026, 8, 10, 14, 0))
        self.assertEqual(behind, 2400.0)

    def test_yesterday_close_seen_today_is_far_behind(self):
        behind = timeutil.seconds_behind_market(
            '2026-08-07T15:00:00+08:00', bjt(2026, 8, 10, 14, 0))
        self.assertGreater(behind, 3 * 3600)

    def test_unparseable_as_of_returns_none(self):
        self.assertIsNone(timeutil.seconds_behind_market('', bjt(2026, 8, 10, 14, 0)))


if __name__ == '__main__':
    unittest.main()
