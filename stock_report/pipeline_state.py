"""Deterministic delivery metadata and report-bundle archiving."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ARCHIVE_NAMES = {
    "latest": "latest.json",
    "analysis": "analysis.json",
    "verdict": "verdict.json",
    "html": "report.html",
    "delivery": "delivery.json",
}


def archive_relative_dir(mode: str, report_date: str) -> Path:
    if mode not in {"morning", "afternoon"}:
        raise ValueError(f"unsupported mode: {mode}")
    return Path("stock_report/data/archive") / report_date / mode


def already_delivered(repo_root: Path, mode: str, report_date: str) -> bool:
    """今天这一期是否已经发出去并归档了。

    定时抓数排在 routine 之前是为了给它备好数据，但 GitHub 的 schedule 会漂：
    2026-08-13 早报，cron 写 23:50 UTC，实际 00:44:45 才跑起来，此时 routine
    早已用自己 push trigger 抓的数据发完信、归了档。那次迟到的抓数把
    morning_latest.json 从"已投递的合并快照"覆盖成一份事后重抓的原始数据——
    归档还在，所以报告没坏，但工作副本从此和发出去的东西对不上。

    已投递就不必再抓：这一期的数据已经用掉了，下一期会重新抓。
    """
    delivery = (Path(repo_root) / archive_relative_dir(mode, report_date)
                / ARCHIVE_NAMES["delivery"])
    try:
        state = json.loads(delivery.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return state.get("status") == "sent"


def build_delivery_state(
    *, mode: str, report_date: str, email_id: str, sent_at: str,
    verify_exit_code: int,
) -> dict:
    return {
        "status": "sent",
        "mode": mode,
        "report_date": report_date,
        "email_id": email_id,
        "sent_at": sent_at,
        "verify_exit_code": int(verify_exit_code),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_bundle(
    repo_root: Path, mode: str, report_date: str, sources: dict[str, Path]
) -> Path:
    missing = sorted(set(ARCHIVE_NAMES) - set(sources))
    if missing:
        raise ValueError(f"missing archive sources: {', '.join(missing)}")

    archive = Path(repo_root) / archive_relative_dir(mode, report_date)
    archive.mkdir(parents=True, exist_ok=True)
    manifest_files = {}
    for key, stable_name in ARCHIVE_NAMES.items():
        source = Path(sources[key])
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = archive / stable_name
        shutil.copyfile(source, destination)
        manifest_files[stable_name] = {"sha256": _sha256(destination)}

    manifest = {
        "mode": mode,
        "report_date": report_date,
        "files": manifest_files,
    }
    (archive / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return archive


def _bjt_today() -> str:
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--mode", required=True, choices=["morning", "afternoon"])
    parser.add_argument("--date", default=None)
    parser.add_argument("--check-delivered", action="store_true",
                        help='只查询今天这一期是否已投递，打印 "sent"/"pending"')
    for key in ARCHIVE_NAMES:
        parser.add_argument(f"--{key}", default=None)
    args = parser.parse_args()

    date = args.date or _bjt_today()
    if args.check_delivered:
        print("sent" if already_delivered(Path(args.repo_root), args.mode, date)
              else "pending")
        return

    missing = [key for key in ARCHIVE_NAMES if getattr(args, key) is None]
    if missing:
        parser.error(f"missing --{' --'.join(missing)}")
    sources = {key: Path(getattr(args, key)) for key in ARCHIVE_NAMES}
    path = archive_bundle(Path(args.repo_root), args.mode, date, sources)
    print(path.as_posix())


if __name__ == "__main__":
    main()
