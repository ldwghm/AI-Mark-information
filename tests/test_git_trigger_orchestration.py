"""git 传输通道：不碰 api.github.com 也能触发抓数并锁定本次快照。

起因：云端 routine 会话的 GitHub 网关拦截 Bash 直连 api.github.com
（HTTP 403「GitHub access is not enabled for this session」），而同一个
会话里 git over HTTPS 与 raw.githubusercontent 都是通的。2026-08-12 早报
实测 API 通道 dispatch_failed，全靠人工绕行才跑完。
"""
import json
import unittest
from datetime import datetime, timedelta, timezone

from stock_report import orchestration


BASE = datetime(2026, 8, 12, 0, 11, 47, tzinfo=timezone.utc)


def _snapshot(mode='morning', fetch_time=None, request_id=None):
    snap = {'report_type': mode,
            'fetch_time': (fetch_time or BASE + timedelta(seconds=90)).isoformat()}
    if request_id:
        snap['orchestration_request'] = {'schema_version': 1, 'request_id': request_id,
                                         'requested_at': BASE.isoformat(),
                                         'requested_by': 'claude-scheduled',
                                         'source': 'github_connector_push'}
    return snap


class FakeTransport:
    """按顺序吐出快照，模拟 workflow 跑完前后的 raw 内容。"""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.dispatched = []
        self.reads = 0

    def dispatch(self, mode, request_id, requested_at):
        self.dispatched.append((mode, request_id, requested_at))
        return 'c0ffee' + '0' * 34

    def read_snapshot(self, path):
        self.reads += 1
        item = self.sequence[min(self.reads - 1, len(self.sequence) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


class MatchingTests(unittest.TestCase):
    def test_exact_request_id_is_the_strong_match(self):
        snap = _snapshot(request_id='morning-x')
        r = orchestration.match_snapshot(snap, 'morning-x', 'morning', BASE,
                                         now=BASE + timedelta(seconds=120))
        self.assertEqual(r['match'], 'by_request_id')
        self.assertTrue(r['fresh'])

    def test_a_stale_snapshot_from_before_dispatch_is_not_a_match(self):
        old = _snapshot(fetch_time=BASE - timedelta(hours=3))
        r = orchestration.match_snapshot(old, 'morning-x', 'morning', BASE,
                                         now=BASE + timedelta(seconds=120))
        self.assertEqual(r['match'], 'none')
        self.assertFalse(r['fresh'])

    def test_another_pipelines_id_still_counts_as_fresh_but_is_labelled(self):
        """Codex 与 Claude 抢同一个 triggers/{mode}.json，后完成的盖住前一个。

        数据仍可用，但必须标成 by_freshness——报告有权知道它拿到的不是
        自己那一次的产物。
        """
        snap = _snapshot(request_id='codex-morning-20260812T002936Z-9eatsej5')
        r = orchestration.match_snapshot(snap, 'morning-mine', 'morning', BASE,
                                         now=BASE + timedelta(seconds=120))
        self.assertEqual(r['match'], 'by_freshness')
        self.assertTrue(r['fresh'])
        self.assertIn('另一次请求的 ID', r['reason'])

    def test_wrong_mode_never_matches(self):
        r = orchestration.match_snapshot(_snapshot(mode='afternoon', request_id='m'),
                                         'm', 'morning', BASE)
        self.assertEqual(r['match'], 'none')

    def test_unstamped_snapshot_reads_as_no_request_id(self):
        self.assertIsNone(orchestration.snapshot_request_id(_snapshot()))
        self.assertIsNone(orchestration.snapshot_request_id({}))
        self.assertIsNone(orchestration.snapshot_request_id(
            {'orchestration_request': 'not-a-dict'}))


class GitDriverTests(unittest.TestCase):
    def _run(self, sequence, timeout_seconds=0, **kw):
        # 默认 timeout_seconds=0：不匹配时只读一轮就收，避免测试空转到真实超时
        transport = FakeTransport(sequence)
        snap, status = orchestration.run_orchestration_git(
            'morning', 'ldwghm/AI-Mark-information', 'main', 'tok',
            timeout_seconds=timeout_seconds, transport=transport,
            sleeper=lambda s: None,
            now_fn=lambda: BASE + timedelta(seconds=90), **kw)
        return snap, status, transport

    def test_polls_until_the_workflow_stamps_this_request(self):
        stale = _snapshot(fetch_time=BASE - timedelta(hours=3))
        # 前两轮还是旧快照，第三轮 workflow 写完并盖了章
        def sequence():
            return [stale, stale, None]
        transport = FakeTransport([stale, stale, None])
        captured = {}

        def read(path):
            transport.reads += 1
            if transport.reads < 3:
                return stale
            return _snapshot(request_id=captured['rid'])
        transport.read_snapshot = read
        original_dispatch = transport.dispatch

        def dispatch(mode, request_id, requested_at):
            captured['rid'] = request_id
            return original_dispatch(mode, request_id, requested_at)
        transport.dispatch = dispatch

        snap, status = orchestration.run_orchestration_git(
            'morning', 'r', 'main', 'tok', transport=transport,
            sleeper=lambda s: None, now_fn=lambda: BASE + timedelta(seconds=90))
        self.assertEqual(status['state'], 'completed')
        self.assertEqual(status['conclusion'], 'success')
        self.assertEqual(status['snapshot']['match'], 'by_request_id')
        self.assertEqual(transport.reads, 3)
        self.assertEqual(snap['orchestration_request']['request_id'],
                         status['request_id'])

    def test_transport_and_trigger_sha_are_recorded(self):
        _, status, transport = self._run([_snapshot()])
        self.assertEqual(status['transport'], 'git')
        self.assertTrue(status['trigger_commit_sha'].startswith('c0ffee'))
        self.assertEqual(transport.dispatched[0][0], 'morning')
        self.assertTrue(transport.dispatched[0][1].startswith('morning-'))

    def test_dispatch_failure_stops_immediately_and_says_so(self):
        class Broken(FakeTransport):
            def dispatch(self, *a):
                raise RuntimeError('git push failed: permission denied')
        snap, status = orchestration.run_orchestration_git(
            'morning', 'r', 'main', 'tok', transport=Broken([]),
            sleeper=lambda s: None)
        self.assertIsNone(snap)
        self.assertEqual(status['state'], 'dispatch_failed')
        self.assertIn('permission denied', status['error'])

    def test_timeout_with_only_stale_data_is_not_reported_as_success(self):
        stale = _snapshot(fetch_time=BASE - timedelta(hours=3))
        snap, status, _ = self._run([stale], timeout_seconds=0)
        self.assertEqual(status['state'], 'timeout')
        self.assertIsNone(status['conclusion'])
        self.assertFalse(status['snapshot']['fresh'])

    def test_timeout_with_another_pipelines_fresh_data_is_usable_but_flagged(self):
        snap, status, _ = self._run([_snapshot(request_id='codex-whatever')],
                                    timeout_seconds=0)
        self.assertEqual(status['state'], 'completed')
        self.assertEqual(status['snapshot']['match'], 'by_freshness')

    def test_network_error_while_polling_does_not_crash_the_run(self):
        snap, status, _ = self._run([OSError('raw.githubusercontent unreachable')],
                                    timeout_seconds=0)
        self.assertEqual(status['state'], 'timeout')
        self.assertIn('unreachable', status['snapshot']['reason'])


class TransportPlumbingTests(unittest.TestCase):
    def test_dispatch_writes_a_valid_trigger_and_pushes_it(self):
        calls, written = [], {}

        def runner(args, cwd=None):
            calls.append(args)
            if args[:2] == ['git', 'rev-parse']:
                return 'a' * 40 + '\n'
            if 'commit' in args:
                rel = 'stock_report/triggers/morning.json'
                from pathlib import Path
                written['body'] = (Path(cwd) / rel).read_text(encoding='utf-8')
            return ''

        t = orchestration.GitTriggerTransport('o/r', 'main', 'tok', runner=runner)
        sha = t.dispatch('morning', 'morning-abc', '2026-08-12T00:11:47Z')

        self.assertEqual(sha, 'a' * 40)
        payload = json.loads(written['body'])
        self.assertEqual(payload['mode'], 'morning')
        self.assertEqual(payload['request_id'], 'morning-abc')
        self.assertEqual(payload['requested_by'], 'claude-scheduled')

        def verb(args):   # 跳过 -c 与 k=v 配置对，取真正的 git 子命令
            return next(x for x in args[1:]
                        if not x.startswith('-') and '=' not in x)
        verbs = [verb(a) for a in calls]
        self.assertEqual(verbs[0], 'clone')
        self.assertIn('add', verbs)
        self.assertLess(verbs.index('add'), verbs.index('commit'))
        self.assertIn('push', verbs)
        # blobless + sparse：这个仓库的 data/ 归档有几十 MB
        self.assertIn('--filter=blob:none', calls[0])
        self.assertIn('--sparse', calls[0])

    def test_the_trigger_payload_passes_connector_trigger_validation(self):
        """推上去的文件必须能被 workflow 那一步接受，否则抓数会失败。"""
        from stock_report import connector_trigger
        written = {}

        def runner(args, cwd=None):
            if 'commit' in args:
                from pathlib import Path
                written['body'] = (Path(cwd) / 'stock_report/triggers/morning.json'
                                   ).read_text(encoding='utf-8')
            return 'b' * 40 + '\n'

        orchestration.GitTriggerTransport('o/r', 'main', 'tok', runner=runner).dispatch(
            'morning', 'morning-20260812T001147Z-267fbf4b', '2026-08-12T00:11:47Z')
        stamped = connector_trigger.stamp_snapshot(
            {'report_type': 'morning'}, json.loads(written['body']), 'morning', 'sha1')
        self.assertEqual(stamped['orchestration_request']['request_id'],
                         'morning-20260812T001147Z-267fbf4b')

    def test_credentials_never_appear_in_error_text(self):
        import subprocess as sp

        def runner(args, cwd=None):
            raise RuntimeError('unused')
        t = orchestration.GitTriggerTransport('o/r', 'main', 'sekrit')
        completed = sp.CompletedProcess(args=['git'], returncode=1,
                                        stdout='', stderr='x-access-token:sekrit@github.com bad')
        original = sp.run
        try:
            sp.run = lambda *a, **k: completed
            with self.assertRaises(RuntimeError) as ctx:
                orchestration.GitTriggerTransport._run_git(['git', 'push'])
        finally:
            sp.run = original
        self.assertNotIn('x-access-token:', str(ctx.exception))

    def test_raw_url_is_cache_busted_and_never_hits_the_api_host(self):
        seen = {}

        def fetcher(url):
            seen['url'] = url
            return json.dumps(_snapshot())
        t = orchestration.GitTriggerTransport('o/r', 'main', 'tok', fetcher=fetcher)
        t.read_snapshot('stock_report/data/morning_latest.json')
        self.assertTrue(seen['url'].startswith('https://raw.githubusercontent.com/o/r/main/'))
        self.assertIn('?t=', seen['url'])
        self.assertNotIn('api.github.com', seen['url'])


class DefaultTransportTests(unittest.TestCase):
    def test_cli_defaults_to_git(self):
        import inspect
        src = inspect.getsource(orchestration.main)
        self.assertIn('default="git"', src)
        self.assertIn('run_orchestration_git if args.transport == "git"', src)

    def test_both_playbooks_ask_for_the_git_transport(self):
        from pathlib import Path
        for name in ('morning', 'afternoon'):
            text = Path(f'stock_report/prompts/{name}_prompt.md').read_text(encoding='utf-8')
            self.assertIn('--transport git', text, msg=name)

    def test_both_playbooks_tell_the_model_what_to_do_with_each_match_level(self):
        """by_freshness 是最容易被无声吞掉的一档：数据是新鲜的，只是不是本次
        请求的产物。playbook 不写清楚，模型就会当成正常情况不作声明。"""
        from pathlib import Path
        for name in ('morning', 'afternoon'):
            text = Path(f'stock_report/prompts/{name}_prompt.md').read_text(encoding='utf-8')
            for token in ('by_request_id', 'by_freshness', 'snapshot.match'):
                self.assertIn(token, text, msg=f'{name} 缺 {token}')


if __name__ == '__main__':
    unittest.main()
