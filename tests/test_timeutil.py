import unittest
from datetime import datetime, timezone

from stock_report import timeutil


class TimeFormatTests(unittest.TestCase):
    def test_utc_iso_ends_with_z_and_round_trips(self):
        moment = datetime(2026, 8, 10, 6, 21, 40, 956545, tzinfo=timezone.utc)
        text = timeutil.utc_iso(moment)
        self.assertEqual(text, '2026-08-10T06:21:40.956545Z')
        self.assertEqual(timeutil.parse_iso(text), moment)

    def test_bjt_iso_carries_offset(self):
        moment = datetime(2026, 8, 10, 6, 21, 39, tzinfo=timezone.utc)
        self.assertEqual(timeutil.bjt_iso(moment), '2026-08-10T14:21:39+08:00')

    def test_naive_legacy_format_is_read_as_utc_not_local(self):
        # 旧格式 "2026-08-10 06:21:40 UTC" 必须按 UTC 读回，否则新鲜度会凭空差 8 小时
        parsed = timeutil.parse_iso('2026-08-10 06:21:40 UTC')
        self.assertEqual(parsed, datetime(2026, 8, 10, 6, 21, 40, tzinfo=timezone.utc))

    def test_unparseable_returns_none(self):
        self.assertIsNone(timeutil.parse_iso('not a time'))
        self.assertIsNone(timeutil.parse_iso(''))


class AgeTests(unittest.TestCase):
    def test_age_seconds_between_offsets(self):
        now = datetime(2026, 8, 10, 6, 22, 0, tzinfo=timezone.utc)
        # 14:21:39+08:00 == 06:21:39Z -> 21 秒前
        self.assertAlmostEqual(
            timeutil.age_seconds('2026-08-10T14:21:39+08:00', now=now), 21.0, places=3)

    def test_future_timestamp_clamps_to_zero(self):
        now = datetime(2026, 8, 10, 6, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(timeutil.age_seconds('2026-08-10T07:00:00Z', now=now), 0.0)


class TradingDateTests(unittest.TestCase):
    def test_morning_takes_previous_trading_day(self):
        monday = datetime(2026, 8, 10, 8, 0, tzinfo=timeutil.BJT)
        # 周一早报要取上周五
        self.assertEqual(timeutil.trading_date_bjt('morning', monday), '2026-08-07')

    def test_afternoon_takes_today(self):
        monday = datetime(2026, 8, 10, 14, 0, tzinfo=timeutil.BJT)
        self.assertEqual(timeutil.trading_date_bjt('afternoon', monday), '2026-08-10')

    def test_weekend_afternoon_falls_back_to_friday(self):
        sunday = datetime(2026, 8, 9, 14, 0, tzinfo=timeutil.BJT)
        self.assertEqual(timeutil.trading_date_bjt('afternoon', sunday), '2026-08-07')


if __name__ == '__main__':
    unittest.main()
