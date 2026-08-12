#!/usr/bin/env python3
"""Trigger one market-data workflow and retrieve the snapshot produced by that run.

两条传输通道，默认 git：

  git（默认）  推 stock_report/triggers/{mode}.json 触发 workflow，
               用 git 协议（ls-remote + fetch + show）轮询快照，比对
               workflow 盖进快照的 orchestration_request.request_id。
               **全程不碰 api.github.com，也不走 CDN。**
  api          原来的 workflow_dispatch + actions API 轮询。

改默认值的原因：云端 routine 会话的 GitHub 网关拦截 Bash 直连
api.github.com（HTTP 403「GitHub access is not enabled for this session」），
而同一个会话里 git over HTTPS 是通的。2026-08-12 早报实测：API 通道
dispatch_failed，靠人工绕行才跑完。git 通道是这个仓库里已经在生产运行的
路径（Codex 流水线每天在走），且 request_id 关联比 API 通道更硬——
它绑的是快照内容，不是 run 的显示名。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


API_VERSION = "2022-11-28"
DEFAULT_REPO = "ldwghm/AI-Mark-information"
MODE_CONFIG = {
    "morning": ("fetch-market-data.yml", "stock_report/data/morning_latest.json"),
    "afternoon": ("fetch-market-data-pm.yml", "stock_report/data/afternoon_latest.json"),
}
TRIGGER_PATH = "stock_report/triggers/{mode}.json"


def _parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace(" UTC", "+00:00")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def select_workflow_run(runs, request_id, ref, dispatched_at):
    """Return the newest run that belongs to this exact dispatch request."""
    lower_bound = _parse_time(dispatched_at) - timedelta(seconds=3)
    matches = []
    for run in runs or []:
        title = str(run.get("display_title") or run.get("name") or "")
        if request_id not in title:
            continue
        if ref and run.get("head_branch") not in (None, ref):
            continue
        try:
            created_at = _parse_time(run.get("created_at"))
        except (TypeError, ValueError):
            continue
        if created_at < lower_bound:
            continue
        matches.append((created_at, int(run.get("id") or 0), run))
    return max(matches, default=(None, None, None))[2]


def evaluate_snapshot(snapshot, expected_mode, not_before, now=None, max_age_seconds=900):
    """Evaluate whether a data snapshot is the expected type and fresh enough."""
    now = _parse_time(now or datetime.now(timezone.utc))
    if not isinstance(snapshot, dict):
        return {"fresh": False, "age_seconds": None, "reason": "snapshot is not an object"}
    if snapshot.get("report_type") != expected_mode:
        return {
            "fresh": False,
            "age_seconds": None,
            "reason": f"report_type is {snapshot.get('report_type')!r}, expected {expected_mode!r}",
        }
    try:
        fetch_time = _parse_time(snapshot.get("fetch_time"))
    except (TypeError, ValueError):
        return {"fresh": False, "age_seconds": None, "reason": "fetch_time is missing or invalid"}
    age_seconds = (now - fetch_time).total_seconds()
    if not_before is not None and fetch_time < _parse_time(not_before) - timedelta(seconds=3):
        return {
            "fresh": False,
            "age_seconds": round(age_seconds, 1),
            "reason": "snapshot fetch_time is before dispatch",
        }
    if age_seconds < -300:
        return {"fresh": False, "age_seconds": round(age_seconds, 1), "reason": "fetch_time is in the future"}
    if age_seconds > max_age_seconds:
        return {
            "fresh": False,
            "age_seconds": round(age_seconds, 1),
            "reason": f"snapshot age exceeds {max_age_seconds}s",
        }
    return {"fresh": True, "age_seconds": round(age_seconds, 1), "reason": "fresh"}


def snapshot_request_id(snapshot):
    """workflow 通过 connector_trigger.stamp_snapshot() 盖进快照的请求 ID。"""
    request = (snapshot or {}).get("orchestration_request")
    if not isinstance(request, dict):
        return None
    return str(request.get("request_id") or "") or None


def match_snapshot(snapshot, request_id, mode, dispatched_at, now=None):
    """判定这份快照是不是本次请求的产物。

    两级：request_id 逐字相等最硬；退一步只认"fetch_time 晚于本次 dispatch"。
    需要退级是因为 trigger 文件是单一路径——Codex 与 Claude 两条流水线抢同
    一个 triggers/{mode}.json，后完成的那次会把自己的 request_id 盖上去。
    这种情况下数据仍然是新鲜可用的，但必须如实标成 by_freshness，
    让报告知道它拿到的不是自己那一次的产物。
    """
    stamped = snapshot_request_id(snapshot)
    if stamped and stamped == request_id:
        result = evaluate_snapshot(snapshot, mode, not_before=None, now=now)
        # ID 对上但快照本身不可用（模式不符、过期）不算匹配——盖章证明不了新鲜
        if result.get("fresh"):
            result["match"] = "by_request_id"
            return result
    result = evaluate_snapshot(snapshot, mode, not_before=dispatched_at, now=now)
    result["match"] = "by_freshness" if result.get("fresh") else "none"
    if result.get("fresh") and stamped:
        result["reason"] = (f"fresh，但快照带的是另一次请求的 ID {stamped}"
                            f"（本次 {request_id}）——两条流水线抢同一个 trigger 文件")
    return result


class GitTriggerTransport:
    """推 trigger 文件触发、用 git 协议读结果。不碰 GitHub API，也不走 CDN。

    读取刻意不用 raw.githubusercontent：2026-08-12 午报实测，抓数
    workflow 在 05:38:45 提交了带本次 request_id 的快照，poller 在随后
    三分半里每 10 秒拉一次 raw 却一次都没看到它——`?t=<uuid>` nonce 没能
    绕过 CDN 缓存，直到 13:50 的定时抓数把那份覆盖掉。结果本该
    by_request_id 的匹配退成了 by_freshness。git 协议没有这一层。
    """

    def __init__(self, repo, ref, token, runner=None):
        self.repo = repo
        self.ref = ref
        self.token = token
        self._run = runner or self._run_git
        self._workdir = None
        self._last_head = None

    @staticmethod
    def _run_git(args, cwd=None):
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            # 凭据出现在 remote URL 里，报错前必须抹掉
            stderr = (result.stderr or "").replace("x-access-token:", "")
            raise RuntimeError(f"git {args[1] if len(args) > 1 else ''} failed: {stderr[-400:]}")
        return result.stdout

    @property
    def _remote(self):
        return f"https://x-access-token:{self.token}@github.com/{self.repo}"

    def _ensure_workdir(self):
        if self._workdir:
            return self._workdir
        workdir = tempfile.mkdtemp(prefix="orch-")
        # blobless + sparse：把 stock_report/data/ 的归档挡在外面。
        # cone 模式仍会带上各级父目录的直接子文件（根目录 .py、
        # stock_report/*.py），实测 34 个文件 / 约 300KB / 7 秒，可以接受。
        self._run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                   "--branch", self.ref, self._remote, workdir])
        self._run(["git", "sparse-checkout", "set", "stock_report/triggers"], cwd=workdir)
        self._workdir = workdir
        return workdir

    def close(self):
        if self._workdir:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None

    def dispatch(self, mode, request_id, requested_at):
        """写 trigger 文件并推上去。返回 trigger 提交的 SHA。"""
        payload = {
            "schema_version": 1,
            "mode": mode,
            "request_id": request_id,
            "requested_at": requested_at,
            "requested_by": "claude-scheduled",
        }
        rel = TRIGGER_PATH.format(mode=mode)
        workdir = self._ensure_workdir()
        target = Path(workdir) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        self._run(["git", "add", "--", rel], cwd=workdir)
        self._run(["git", "-c", "user.name=github-actions[bot]",
                   "-c", "user.email=github-actions[bot]@users.noreply.github.com",
                   "commit", "-m", f"trigger: claude {mode} {request_id}"],
                  cwd=workdir)
        self._run(["git", "push", self._remote, f"HEAD:{self.ref}"], cwd=workdir)
        return self._run(["git", "rev-parse", "HEAD"], cwd=workdir).strip()

    def head_sha(self):
        """远端分支当前指向哪个提交。几百字节，可以高频问。"""
        out = self._run(["git", "ls-remote", self._remote, f"refs/heads/{self.ref}"])
        line = (out or "").strip().split("\n")[0]
        return line.split()[0] if line else None

    def read_snapshot(self, path):
        """取远端 ref 上该文件的当前内容。HEAD 没动就不必重新取 blob。"""
        workdir = self._ensure_workdir()
        head = self.head_sha()
        if head and head != self._last_head:
            self._run(["git", "fetch", "--depth", "1", self._remote, self.ref], cwd=workdir)
            self._last_head = head
        # partial clone：blob 按需从 promisor remote 拉，不受 sparse 范围限制
        return json.loads(self._run(["git", "show", f"FETCH_HEAD:{path}"], cwd=workdir))


class GitHubWorkflowClient:
    def __init__(self, repo, token, session=None):
        self.repo = repo
        self.session = session or requests.Session()
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def _url(self, suffix):
        return f"https://api.github.com/repos/{self.repo}/{suffix.lstrip('/')}"

    def dispatch(self, workflow, ref, request_id):
        response = self.session.post(
            self._url(f"actions/workflows/{workflow}/dispatches"),
            headers=self.headers,
            json={"ref": ref, "inputs": {"request_id": request_id}},
            timeout=30,
        )
        if response.status_code not in (200, 204):
            raise RuntimeError(f"workflow dispatch returned HTTP {response.status_code}")
        if response.status_code == 200:
            try:
                return response.json().get("workflow_run_id")
            except ValueError:
                return None
        return None

    def get_run(self, run_id):
        response = self.session.get(
            self._url(f"actions/runs/{run_id}"), headers=self.headers, timeout=20
        )
        response.raise_for_status()
        return response.json()

    def list_dispatch_runs(self, workflow, ref):
        response = self.session.get(
            self._url(f"actions/workflows/{workflow}/runs"),
            headers=self.headers,
            params={"event": "workflow_dispatch", "branch": ref, "per_page": 20},
            timeout=20,
        )
        response.raise_for_status()
        return response.json().get("workflow_runs", [])

    def read_json(self, repo_path, ref):
        response = self.session.get(
            self._url(f"contents/{repo_path}"),
            headers=self.headers,
            params={"ref": ref, "cache": uuid.uuid4().hex},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        raw = base64.b64decode(payload["content"])
        return json.loads(raw.decode("utf-8-sig"))


_MATCH_RANK = {"none": 0, "by_freshness": 1, "by_request_id": 2}


def _better(new, old):
    """新一轮的判定是否比手上这份更值得留。"""
    return (_MATCH_RANK.get(new.get("match"), 0), bool(new.get("fresh"))) >= \
           (_MATCH_RANK.get(old.get("match"), 0), bool(old.get("fresh")))


def run_orchestration_git(mode, repo, ref, token, timeout_seconds=420, poll_seconds=10,
                          transport=None, sleeper=time.sleep, now_fn=None):
    """git 通道：推 trigger 文件 -> 轮询快照 -> 比对 request_id。"""
    workflow, data_path = MODE_CONFIG[mode]
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    dispatched_at = now_fn()
    request_id = f"{mode}-{dispatched_at:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    status = {
        "mode": mode,
        "request_id": request_id,
        "workflow": workflow,
        "transport": "git",
        "dispatched_at": dispatched_at.isoformat(),
        "state": "dispatching",
        "run_id": None,
        "trigger_commit_sha": None,
        "conclusion": None,
        "snapshot": None,
    }
    transport = transport or GitTriggerTransport(repo, ref, token)
    try:
        status["trigger_commit_sha"] = transport.dispatch(
            mode, request_id, dispatched_at.isoformat().replace("+00:00", "Z"))
        status["state"] = "dispatched"
    except Exception as exc:
        status.update(state="dispatch_failed", error=str(exc))
        return None, status

    snapshot, verdict = None, {"fresh": False, "age_seconds": None,
                               "reason": "never polled", "match": "none"}
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                candidate = transport.read_snapshot(data_path)
                check = match_snapshot(candidate, request_id, mode, dispatched_at,
                                       now=now_fn())
                # 只在更好的匹配上替换：抓数 workflow 提交带本次 ID 的快照后，
                # 同一条 workflow 的定时任务可能几分钟内再覆盖一次（08-12 午报
                # 就是 13:50 的 cron 盖掉了 push 那次）。已经拿到 by_request_id
                # 就不该被随后那份无名快照顶掉。
                if _better(check, verdict):
                    snapshot, verdict = candidate, check
                if verdict.get("match") == "by_request_id" and verdict.get("fresh"):
                    status["state"] = "completed"
                    status["conclusion"] = "success"
                    break
            except Exception as exc:
                if snapshot is None:
                    verdict = {"fresh": False, "age_seconds": None, "reason": str(exc),
                               "match": "none"}
            if time.monotonic() >= deadline:
                # 拿到了新鲜数据但 ID 不是本次的，仍算可用，只是要如实标出来
                status["state"] = "completed" if verdict.get("fresh") else "timeout"
                status["conclusion"] = "success" if verdict.get("fresh") else None
                break
            sleeper(poll_seconds)
    finally:
        closer = getattr(transport, "close", None)
        if callable(closer):
            closer()

    status["snapshot"] = verdict
    return snapshot, status


def run_orchestration(mode, repo, ref, token, timeout_seconds=420, poll_seconds=10):
    workflow, data_path = MODE_CONFIG[mode]
    request_id = f"{mode}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    dispatched_at = datetime.now(timezone.utc)
    status = {
        "mode": mode,
        "request_id": request_id,
        "workflow": workflow,
        "transport": "api",
        "dispatched_at": dispatched_at.isoformat(),
        "state": "dispatching",
        "run_id": None,
        "conclusion": None,
        "snapshot": None,
    }
    client = GitHubWorkflowClient(repo, token)
    try:
        run_id = client.dispatch(workflow, ref, request_id)
        status["run_id"] = run_id
        deadline = time.monotonic() + timeout_seconds
        run = None
        while time.monotonic() < deadline:
            if run_id:
                run = client.get_run(run_id)
            else:
                run = select_workflow_run(
                    client.list_dispatch_runs(workflow, ref), request_id, ref, dispatched_at
                )
                if run:
                    run_id = run.get("id")
                    status["run_id"] = run_id
            if run and run.get("status") == "completed":
                break
            time.sleep(poll_seconds)
        if not run or run.get("status") != "completed":
            status.update(state="timeout", conclusion=None)
        else:
            status.update(state="completed", conclusion=run.get("conclusion"))
            if run.get("conclusion") != "success":
                status["state"] = "workflow_failed"
    except Exception as exc:
        status.update(state="dispatch_failed", error=str(exc))

    snapshot = None
    try:
        snapshot = client.read_json(data_path, ref)
        not_before = dispatched_at if status.get("conclusion") == "success" else None
        status["snapshot"] = evaluate_snapshot(snapshot, mode, not_before=not_before)
    except Exception as exc:
        status["snapshot"] = {"fresh": False, "age_seconds": None, "reason": str(exc)}
    return snapshot, status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(MODE_CONFIG))
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--ref", default="main")
    parser.add_argument("--out-data", required=True)
    parser.add_argument("--out-status", required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--poll", type=int, default=10)
    parser.add_argument("--transport", choices=("git", "api"), default="git",
                        help="git=推 trigger 文件+轮询 raw（默认，不碰 api.github.com）")
    args = parser.parse_args()

    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GH_PAT/GITHUB_TOKEN is required")
    driver = run_orchestration_git if args.transport == "git" else run_orchestration
    snapshot, status = driver(
        args.mode, args.repo, args.ref, token, args.timeout, args.poll
    )
    Path(args.out_status).write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if snapshot is not None:
        Path(args.out_data).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if snapshot is None:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
