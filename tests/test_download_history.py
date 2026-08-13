"""重试只对限流有意义。

2026-08-13 早报实测：CCR 会话里 yfinance 被出口代理拒在连接层
（`curl: (7) CONNECT tunnel failed, response 403`），55 个 ticker 白跑两遍，
两次报同样的错。连接被拒是确定性的，重试改变不了它。
"""
import unittest

from stock_report import cloud_fetch


class FakeYF:
    """按剧本依次返回或抛出；记录被调用了几次。"""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    def download(self, tickers, **kwargs):
        self.calls += 1
        step = self.script.pop(0) if self.script else None
        if isinstance(step, Exception):
            raise step
        return step


TICKERS = ['300308.SZ', '688041.SS']


class DownloadHistory(unittest.TestCase):
    def test_proxy_refusal_is_not_retried(self):
        yf = FakeYF(Exception('Failed to perform, curl: (7) CONNECT tunnel failed, '
                              'response 403'))

        self.assertIsNone(cloud_fetch.download_history(yf, TICKERS))
        self.assertEqual(yf.calls, 1)

    def test_rate_limit_is_retried(self):
        yf = FakeYF(Exception('429 Too Many Requests'), ['bar'])

        self.assertEqual(cloud_fetch.download_history(yf, TICKERS), ['bar'])
        self.assertEqual(yf.calls, 2)

    def test_timeout_is_retried(self):
        yf = FakeYF(Exception('Read timed out'), ['bar'])

        self.assertEqual(cloud_fetch.download_history(yf, TICKERS), ['bar'])
        self.assertEqual(yf.calls, 2)

    def test_gateway_wobble_is_retried(self):
        yf = FakeYF(Exception('HTTP 503 Service Unavailable'), ['bar'])

        self.assertEqual(cloud_fetch.download_history(yf, TICKERS), ['bar'])
        self.assertEqual(yf.calls, 2)

    def test_ticker_digits_do_not_look_like_a_gateway_error(self):
        """yfinance 报错常把 ticker 抄进去；600504.SS 不该被当成 504 网关超时。"""
        yf = FakeYF(Exception("$600504.SS: possibly delisted; no price data found"))

        self.assertIsNone(cloud_fetch.download_history(yf, ['600504.SS']))
        self.assertEqual(yf.calls, 1)

    def test_the_real_ccr_error_is_not_retried(self):
        """2026-08-13 早报逐字抄下来的那条。"""
        yf = FakeYF(Exception(
            'Failed to perform, curl: (7) CONNECT tunnel failed, response 403. '
            'See https://curl.se/libcurl/c/libcurl-errors.html first for more details.'))

        self.assertIsNone(cloud_fetch.download_history(yf, TICKERS))
        self.assertEqual(yf.calls, 1)

    def test_retry_budget_is_not_exceeded(self):
        yf = FakeYF(Exception('429 rate limit'), Exception('429 rate limit'))

        self.assertIsNone(cloud_fetch.download_history(yf, TICKERS))
        self.assertEqual(yf.calls, 2)

    def test_empty_frame_is_not_retried(self):
        """没抛异常但表是空的：ticker 层面全军覆没，再拉一次还是同一批空值。"""
        yf = FakeYF([], [])

        self.assertIsNone(cloud_fetch.download_history(yf, TICKERS))
        self.assertEqual(yf.calls, 1)

    def test_none_frame_is_not_retried(self):
        yf = FakeYF(None)

        self.assertIsNone(cloud_fetch.download_history(yf, TICKERS))
        self.assertEqual(yf.calls, 1)

    def test_first_attempt_success_costs_one_call(self):
        yf = FakeYF(['bar'])

        self.assertEqual(cloud_fetch.download_history(yf, TICKERS), ['bar'])
        self.assertEqual(yf.calls, 1)

    def test_attempts_floor_is_one(self):
        yf = FakeYF(['bar'])

        self.assertEqual(cloud_fetch.download_history(yf, TICKERS, attempts=0), ['bar'])
        self.assertEqual(yf.calls, 1)

    def test_period_and_grouping_are_preserved(self):
        """技术指标要 3 个月日线、按 ticker 分组——参数错了指标会整片错。"""
        captured = {}

        class Recorder:
            def download(self, tickers, **kwargs):
                captured.update(kwargs)
                captured['tickers'] = tickers
                return ['bar']

        cloud_fetch.download_history(Recorder(), TICKERS)

        self.assertEqual(captured['tickers'], TICKERS)
        self.assertEqual(captured['period'], '3mo')
        self.assertEqual(captured['group_by'], 'ticker')
        self.assertFalse(captured['progress'])


if __name__ == '__main__':
    unittest.main()
