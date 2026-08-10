#!/usr/bin/env python3
"""Trigger one market-data workflow and retrieve the snapshot produced by that run."""

from __future__ import annotations

import argparse
import base64
import json
import os
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


def run_orchestration(mode, repo, ref, token, timeout_seconds=420, poll_seconds=10):
    workflow, data_path = MODE_CONFIG[mode]
    request_id = f"{mode}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    dispatched_at = datetime.now(timezone.utc)
    status = {
        "mode": mode,
        "request_id": request_id,
        "workflow": workflow,
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
    args = parser.parse_args()

    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GH_PAT/GITHUB_TOKEN is required")
    snapshot, status = run_orchestration(
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
