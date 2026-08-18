"""push2his 突发限流：退避重试。

2026-08-18 Actions 实测（run 32136573389）：前 4 个 push2his 请求成功、之后
整批 `RemoteDisconnected`——4 个 60m 请求和 10 只观察池日线全挂。今早那次
（32084883565，本次改动之前）连指数日线也是 0 bars。后果是 technicals 每天
静默退回 klines_cache：`is_fallback: true`、陈旧约 17 小时，且 cache 只有
收盘价没有 OHLC，正是 playbook 规则 1 那次「51 行最高＝最低＝现价」的根源。

**这与 cloud_fetch 里"yfinance 不重试"的判断不矛盾**：那边是代理
`CONNECT tunnel failed, response 403`，确定性策略拦截，重试两次报同样的错，
所以立刻认输；这里是连打请求把对端打崩，退避正是对症的。两条测试都在，
防止后来者把其中一条改成另一条的样子。
"""
import unittest
from unittest import mock

import fetch_market_data as F


class Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def boom(msg):
    return Exception(msg)


class SafeGetRetryTests(unittest.TestCase):
    def setUp(self):
        # 真 sleep 会让整个套件慢下来，且这里要断言的是重试次数不是时长
        patcher = mock.patch.object(F.time, 'sleep')
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, *script, **kwargs):
        self.calls = 0

        def fake(url, params=None, headers=None, timeout=None):
            step = script[min(self.calls, len(script) - 1)]
            self.calls += 1
            if isinstance(step, Exception):
                raise step
            return step

        with mock.patch.object(F.requests, 'get', side_effect=fake):
            return F.safe_get('https://push2his.eastmoney.com/x', **kwargs)

    def test_the_real_actions_failure_is_retried(self):
        """逐字抄自 run 32136573389 的日志。"""
        out = self.call(
            boom("('Connection aborted.', RemoteDisconnected('Remote end closed "
                 "connection without response'))"),
            Resp({'data': {'klines': ['x']}}))
        self.assertEqual(out, {'data': {'klines': ['x']}})
        self.assertEqual(self.calls, 2)

    def test_it_gives_up_after_the_budget(self):
        out = self.call(boom('Connection aborted. RemoteDisconnected'))
        self.assertIsNone(out)
        self.assertEqual(self.calls, 3)

    def test_backoff_grows(self):
        self.call(boom('Connection aborted'))
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [1.5, 3.0])

    def test_no_sleep_after_the_last_attempt(self):
        self.call(boom('Connection aborted'), **{'attempts': 2})
        self.assertEqual(self.sleep.call_count, 1)

    def test_a_deterministic_refusal_is_not_retried(self):
        """代理 403 那类：重试只是把同一个错误再收一遍。"""
        out = self.call(boom('CONNECT tunnel failed, response 403'))
        self.assertIsNone(out)
        self.assertEqual(self.calls, 1)

    def test_bad_json_is_not_retried(self):
        class Bad(Resp):
            def json(self):
                raise ValueError('Expecting value')

        self.assertIsNone(self.call(Bad(None)))
        self.assertEqual(self.calls, 1)

    def test_first_attempt_success_costs_one_call(self):
        self.assertEqual(self.call(Resp({'ok': 1})), {'ok': 1})
        self.assertEqual(self.calls, 1)
        self.sleep.assert_not_called()

    def test_attempts_floor_is_one(self):
        self.assertEqual(self.call(Resp({'ok': 1}), attempts=0), {'ok': 1})
        self.assertEqual(self.calls, 1)

    def test_timeout_is_retryable(self):
        out = self.call(boom('Read timed out'), Resp({'ok': 1}))
        self.assertEqual(out, {'ok': 1})
        self.assertEqual(self.calls, 2)

    def test_datacenter_still_gets_its_error_surfaced_through_the_retry_layer(self):
        """重试层不能把 datacenter 的 success=false 吞回去。"""
        payload = {'success': False, 'message': 'SECURITY_NAME返回字段不存在'}
        with mock.patch.object(F, 'safe_get', return_value=payload):
            rows, err = F.datacenter_get('龙虎榜', {'reportName': 'X'})
        self.assertEqual(rows, [])
        self.assertIn('SECURITY_NAME', err)


if __name__ == '__main__':
    unittest.main()
