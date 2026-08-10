import unittest

import requests

from stock_report import http_util


class FakeResponse:
    def __init__(self, status_code, text=''):
        self.status_code = status_code
        self.text = text
        self.encoding = None


class FakeSession:
    """按脚本依次返回响应或抛异常，并记录调用次数。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.slept = []

    def sleeper(self, seconds):
        self.slept.append(seconds)

    def test_success_on_first_try_does_not_sleep(self):
        session = FakeSession([FakeResponse(200, 'ok')])
        response = http_util.request_with_retry(
            'https://x', session=session, sleeper=self.sleeper)
        self.assertEqual(response.text, 'ok')
        self.assertEqual(session.calls, 1)
        self.assertEqual(self.slept, [])

    def test_retries_on_502_then_succeeds(self):
        session = FakeSession([FakeResponse(502), FakeResponse(200, 'ok')])
        response = http_util.request_with_retry(
            'https://x', session=session, sleeper=self.sleeper)
        self.assertEqual(response.text, 'ok')
        self.assertEqual(session.calls, 2)
        self.assertEqual(len(self.slept), 1)

    def test_backoff_grows(self):
        session = FakeSession([FakeResponse(429), FakeResponse(503), FakeResponse(200, 'ok')])
        http_util.request_with_retry('https://x', session=session,
                                     sleeper=self.sleeper, jitter=0)
        self.assertEqual(self.slept, [0.5, 1.0])

    def test_403_raises_immediately_without_retry(self):
        # 403 是"这个源不给你用"，反复请求只会让封禁更久
        session = FakeSession([FakeResponse(403)])
        with self.assertRaises(http_util.ProviderBlocked):
            http_util.request_with_retry('https://x', session=session, sleeper=self.sleeper)
        self.assertEqual(session.calls, 1)
        self.assertEqual(self.slept, [])

    def test_404_is_not_retried_and_returned(self):
        session = FakeSession([FakeResponse(404, 'missing')])
        response = http_util.request_with_retry(
            'https://x', session=session, sleeper=self.sleeper)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(session.calls, 1)

    def test_network_error_retries_then_raises(self):
        session = FakeSession([requests.ConnectionError('boom')] * 3)
        with self.assertRaises(requests.ConnectionError):
            http_util.request_with_retry('https://x', session=session, sleeper=self.sleeper)
        self.assertEqual(session.calls, 3)

    def test_get_text_swallows_failure(self):
        session = FakeSession([requests.ConnectionError('boom')] * 3)
        self.assertEqual(
            http_util.get_text('https://x', default='fallback',
                               session=session, sleeper=self.sleeper),
            'fallback')

    def test_get_text_swallows_provider_block(self):
        session = FakeSession([FakeResponse(403)])
        self.assertEqual(
            http_util.get_text('https://x', session=session, sleeper=self.sleeper), '')


if __name__ == '__main__':
    unittest.main()
