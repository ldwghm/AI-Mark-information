#!/usr/bin/env python3
"""把早/午报的两个产物提交到仓库——走 git over HTTPS，不碰 GitHub API。

## 为什么需要这个文件

Step 0 的编排早已改走 git 通道（见 orchestration.py 的注释），但 playbook 的
Step 3 仍然写着 `api.github.com/contents`。CCR 会话的 GitHub 网关拦截 Bash 直
连该域名，于是 2026-08-13 早报实测：Step 3 第一次尝试必然 403，模型当场手写
了一段 clone+push 才把报告救回来。救回来了，但那是即兴发挥——换个模型、换个
心情就可能救不回来，而 Step 3 失败＝当天没有报告。

把那段即兴发挥固化成脚本，Step 3 就只剩一条命令，没有发挥空间。

## 两个提交，一次推送

`morning_latest.json` 必须先落，`morning_analysis_candidate.json` 后落——
send-report.yml 由候选文件的 push 触发，触发时要能读到配套的 latest。两者作为
**两个提交**一次推上去：workflow 检出的是 HEAD，顺序满足即可，不必推两次。
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

MODE_FILES = {
    'morning': (
        ('stock_report/data/morning_latest.json', 'data: morning merged snapshot'),
        ('stock_report/data/morning_analysis_candidate.json', 'analysis: morning candidate'),
    ),
    'afternoon': (
        ('stock_report/data/afternoon_latest.json', 'data: afternoon merged snapshot'),
        ('stock_report/data/afternoon_analysis_candidate.json', 'analysis: afternoon candidate'),
    ),
}

BOT = ('-c', 'user.name=github-actions[bot]',
       '-c', 'user.email=github-actions[bot]@users.noreply.github.com')


def _scrub(text):
    """凭据在 remote URL 里，任何回显前都要抹掉。"""
    return (text or '').replace('x-access-token:', '')


def verb_of(args):
    """git 的子命令名。

    不能简单取"第一个不以 - 开头的参数"：`git -c user.name=x commit` 里
    `user.name=x` 是 `-c` 的值，会被误当成子命令，报错就成了
    "git user.name=x failed"，看不出到底是哪一步挂的。
    """
    rest = list(args[1:])
    while rest:
        item = rest.pop(0)
        if item in ('-c', '--config-env', '-C'):
            if rest:
                rest.pop(0)
        elif not item.startswith('-'):
            return item
    return ''


def run_git(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f'git {verb_of(args)} failed: {_scrub(result.stderr)[-400:]}')
    return result.stdout


def load_json(path):
    """提交前先解析一遍。推上去才发现 JSON 坏了，等于当天报告直接报废。"""
    with open(path, encoding='utf-8-sig') as handle:
        return json.load(handle)


def publish(mode, latest, candidate, repo, ref='main', token=None, runner=None,
            date=None, workdir=None):
    """提交两个文件，返回 {repo_path: commit_sha}。"""
    if mode not in MODE_FILES:
        raise ValueError(f'unsupported mode: {mode}')
    token = token or os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('GH_PAT/GITHUB_TOKEN 缺失，无法提交')

    locals_ = [Path(latest), Path(candidate)]
    for path in locals_:
        load_json(path)

    _run = runner or run_git
    remote = f'https://x-access-token:{token}@github.com/{repo}'
    owned = workdir is None
    workdir = workdir or tempfile.mkdtemp(prefix='publish-')
    try:
        # 只需要一个能提交的工作树，不需要历史，也不需要别的文件。
        _run(['git', 'clone', '--depth', '1', '--branch', ref,
              '--filter=blob:none', '--sparse', remote, workdir])
        _run(['git', 'sparse-checkout', 'set', 'stock_report/data'], cwd=workdir)

        shas = {}
        for (repo_path, message), source in zip(MODE_FILES[mode], locals_):
            target = Path(workdir) / repo_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            _run(['git', 'add', '--', repo_path], cwd=workdir)
            full = f'{message} {date}' if date else message
            _run(['git', *BOT, 'commit', '-m', full], cwd=workdir)
            shas[repo_path] = _run(['git', 'rev-parse', 'HEAD'], cwd=workdir).strip()

        _run(['git', 'push', remote, f'HEAD:{ref}'], cwd=workdir)
        return shas
    finally:
        if owned:
            shutil.rmtree(workdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', required=True, choices=sorted(MODE_FILES))
    parser.add_argument('--latest', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--repo', default='ldwghm/AI-Mark-information')
    parser.add_argument('--ref', default='main')
    parser.add_argument('--date', default=None,
                        help='附在 commit message 后面的日期，默认取北京日期')
    args = parser.parse_args()

    # 刻意不 import timeutil：这个文件会被单独 curl 到 /tmp 执行，
    # 多一个同目录依赖就多一种 ImportError 的死法。
    from datetime import datetime, timedelta, timezone
    date = args.date or datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')

    shas = publish(args.mode, args.latest, args.candidate,
                   repo=args.repo, ref=args.ref, date=date)
    print(json.dumps({'mode': args.mode, 'commits': shas}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
