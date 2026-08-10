#!/usr/bin/env python3
"""Validate a GitHub Connector request and attach it to one fetched snapshot."""

from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime
from pathlib import Path


VALID_MODES = {"morning", "afternoon"}
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$")


def _parse_timestamp(value):
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("requested_at must include a timezone")
    return parsed


def stamp_snapshot(snapshot, trigger, expected_mode, trigger_commit_sha=None):
    """Return a copy of snapshot carrying the exact connector request metadata."""
    if expected_mode not in VALID_MODES:
        raise ValueError(f"unsupported mode: {expected_mode}")
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object")
    if snapshot.get("report_type") != expected_mode:
        raise ValueError("snapshot report_type does not match mode")
    if not isinstance(trigger, dict):
        raise ValueError("trigger must be a JSON object")
    if trigger.get("mode") != expected_mode:
        raise ValueError("trigger mode does not match expected mode")

    request_id = str(trigger.get("request_id") or "").strip()
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise ValueError("request_id is missing or invalid")
    requested_at = str(trigger.get("requested_at") or "").strip()
    try:
        _parse_timestamp(requested_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("requested_at is missing or invalid") from exc

    stamped = copy.deepcopy(snapshot)
    request = {
        "schema_version": 1,
        "request_id": request_id,
        "requested_at": requested_at,
        "requested_by": str(trigger.get("requested_by") or "codex-scheduled"),
        "source": "github_connector_push",
    }
    if trigger_commit_sha:
        request["trigger_commit_sha"] = str(trigger_commit_sha)
    stamped["orchestration_request"] = request
    return stamped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=sorted(VALID_MODES))
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--trigger-commit-sha")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    trigger_path = Path(args.trigger)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    trigger = json.loads(trigger_path.read_text(encoding="utf-8-sig"))
    stamped = stamp_snapshot(snapshot, trigger, args.mode, args.trigger_commit_sha)
    snapshot_path.write_text(
        json.dumps(stamped, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(stamped["orchestration_request"], ensure_ascii=False))


if __name__ == "__main__":
    main()
