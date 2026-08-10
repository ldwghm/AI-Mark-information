"""Evaluate whether a scheduled report produced fresh data and a delivery receipt."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _parse_utc(value):
    text = str(value or '').strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        # GitHub-hosted runners use UTC; existing fetch scripts write naive timestamps.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate_health(
    *, mode, expected_date, now, latest, delivery, max_age_hours=12,
):
    issues = []
    now_utc = _parse_utc(now)
    latest = latest if isinstance(latest, dict) else {}
    delivery = delivery if isinstance(delivery, dict) else None

    if latest.get('report_type') != mode:
        issues.append(f"latest report_type is not {mode}")
    if latest.get('fetch_date') != expected_date:
        issues.append(f"latest fetch_date is not {expected_date}")
    try:
        age_hours = (now_utc - _parse_utc(latest.get('fetch_time'))).total_seconds() / 3600
        if age_hours < -0.1 or age_hours > max_age_hours:
            issues.append(f"snapshot age is {age_hours:.2f}h (limit {max_age_hours}h)")
    except (TypeError, ValueError):
        age_hours = None
        issues.append('snapshot fetch_time is missing or invalid')

    if delivery is None:
        issues.append('delivery receipt is missing')
    else:
        if delivery.get('status') != 'sent':
            issues.append('delivery status is not sent')
        if delivery.get('mode') != mode:
            issues.append(f"delivery mode is not {mode}")
        if delivery.get('report_date') != expected_date:
            issues.append(f"delivery report_date is not {expected_date}")

    return {
        'healthy': not issues,
        'mode': mode,
        'expected_date': expected_date,
        'checked_at': now_utc.isoformat().replace('+00:00', 'Z'),
        'snapshot_age_hours': None if age_hours is None else round(age_hours, 3),
        'issues': issues,
    }


def _read_json(path):
    candidate = Path(path)
    if not candidate.is_file():
        return None
    return json.loads(candidate.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', required=True, choices=['morning', 'afternoon'])
    parser.add_argument('--expected-date', required=True)
    parser.add_argument('--latest', required=True)
    parser.add_argument('--delivery', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--now', default=datetime.now(timezone.utc).isoformat())
    parser.add_argument('--max-age-hours', type=float, default=12)
    args = parser.parse_args()
    result = evaluate_health(
        mode=args.mode,
        expected_date=args.expected_date,
        now=args.now,
        latest=_read_json(args.latest),
        delivery=_read_json(args.delivery),
        max_age_hours=args.max_age_hours,
    )
    Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['healthy'] else 2)


if __name__ == '__main__':
    main()
