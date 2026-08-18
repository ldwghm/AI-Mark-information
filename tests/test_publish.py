"""Step 3 走 git 通道提交两个产物。

背景：2026-08-13 早报的 Step 3 用 `api.github.com/contents`，被会话网关 403
拦下，靠模型临场手写 clone+push 才救回来。publish.py 把那段固化成脚本。
"""
import json
import tempfile
import unittest
from pathlib import Path

from stock_report import publish


class FakeGit:
    """记录 git 调用；clone 时把目标目录建出来，好让复制文件成立。"""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on
        self._sha = 0

    def __call__(self, args, cwd=None):
        self.calls.append((tuple(args), cwd))
        verb = publish.verb_of(args)
        if self.fail_on and verb == self.fail_on:
            raise RuntimeError(f'git {verb} failed: boom')
        if verb == 'clone':
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        if verb == 'rev-parse':
            self._sha += 1
            return f'{self._sha:040x}\n'
        return ''

    def verbs(self):
        return [publish.verb_of(args) for args, _cwd in self.calls]


def write_json(directory, name, payload):
    path = Path(directory) / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return path


class Publish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.latest = write_json(self.tmp.name, 'latest.json', {'fetch_time': 'x'})
        self.candidate = write_json(self.tmp.name, 'cand.json', {'date': '2026-08-13'})
        self.workdir = Path(self.tmp.name) / 'wd'

    def run_publish(self, git, mode='morning', **kwargs):
        return publish.publish(mode, self.latest, self.candidate,
                               repo='o/r', ref='main', token='tok',
                               runner=git, workdir=str(self.workdir), **kwargs)

    def test_latest_is_committed_before_the_candidate(self):
        """send-report 由候选的 push 触发，触发时必须已经能读到配套 latest。"""
        git = FakeGit()
        self.run_publish(git, date='2026-08-13')

        messages = [args[args.index('-m') + 1]
                    for args, _cwd in git.calls if '-m' in args]
        self.assertEqual(messages, ['data: morning merged snapshot 2026-08-13',
                                    'analysis: morning candidate 2026-08-13'])

    def test_both_commits_go_up_in_one_push(self):
        git = FakeGit()
        self.run_publish(git)

        self.assertEqual(git.verbs().count('push'), 1)
        self.assertEqual(git.verbs().count('commit'), 2)
        self.assertEqual(git.verbs()[-1], 'push')

    def test_files_land_at_their_repo_paths(self):
        git = FakeGit()
        self.run_publish(git)

        target = self.workdir / 'stock_report/data/morning_latest.json'
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')),
                         {'fetch_time': 'x'})
        self.assertTrue(
            (self.workdir / 'stock_report/data/morning_analysis_candidate.json').is_file())

    def test_afternoon_writes_afternoon_paths(self):
        git = FakeGit()
        shas = self.run_publish(git, mode='afternoon')

        self.assertEqual(sorted(shas), [
            'stock_report/data/afternoon_analysis_candidate.json',
            'stock_report/data/afternoon_latest.json'])

    def test_returns_a_distinct_sha_per_file(self):
        git = FakeGit()
        shas = self.run_publish(git)

        self.assertEqual(len(set(shas.values())), 2)

    def test_broken_json_is_caught_before_any_git_call(self):
        """坏 JSON 推上去等于当天报告报废，必须在联网之前就拦下。"""
        (Path(self.tmp.name) / 'cand.json').write_text('{oops', encoding='utf-8')
        git = FakeGit()

        with self.assertRaises(json.JSONDecodeError):
            self.run_publish(git)
        self.assertEqual(git.calls, [])

    def test_missing_token_never_reaches_git(self):
        git = FakeGit()
        with self.assertRaises(RuntimeError) as caught:
            publish.publish('morning', self.latest, self.candidate,
                            repo='o/r', token='', runner=git,
                            workdir=str(self.workdir))
        self.assertIn('GH_PAT', str(caught.exception))
        self.assertEqual(git.calls, [])

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            publish.publish('evening', self.latest, self.candidate, repo='o/r')

    def test_git_failure_message_scrubs_the_credential(self):
        def boom(args, cwd=None):
            raise RuntimeError(publish._scrub(
                'fatal: https://x-access-token:ghp_secret@github.com/o/r denied'))

        with self.assertRaises(RuntimeError) as caught:
            self.run_publish(boom)
        self.assertNotIn('x-access-token', str(caught.exception))

    def test_clone_is_shallow_and_sparse(self):
        """完整克隆会把 archive/ 下的历年归档一起拉下来。"""
        git = FakeGit()
        self.run_publish(git)

        clone = next(args for args, _cwd in git.calls if 'clone' in args)
        for flag in ('--depth', '--filter=blob:none', '--sparse'):
            self.assertIn(flag, clone)

    def test_push_failure_propagates(self):
        with self.assertRaises(RuntimeError):
            self.run_publish(FakeGit(fail_on='push'))


class VerbOf(unittest.TestCase):
    def test_config_flag_value_is_not_the_subcommand(self):
        self.assertEqual(publish.verb_of(
            ['git', '-c', 'user.name=github-actions[bot]', 'commit', '-m', 'x']),
            'commit')

    def test_plain_subcommand(self):
        self.assertEqual(publish.verb_of(['git', 'push', 'remote', 'HEAD:main']), 'push')

    def test_no_subcommand(self):
        self.assertEqual(publish.verb_of(['git', '--version']), '')


class Scrub(unittest.TestCase):
    def test_scrub_handles_none(self):
        self.assertEqual(publish._scrub(None), '')


if __name__ == '__main__':
    unittest.main()
