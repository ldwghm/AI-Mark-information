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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--mode", required=True, choices=["morning", "afternoon"])
    parser.add_argument("--date", required=True)
    for key in ARCHIVE_NAMES:
        parser.add_argument(f"--{key}", required=True)
    args = parser.parse_args()

    sources = {key: Path(getattr(args, key)) for key in ARCHIVE_NAMES}
    path = archive_bundle(Path(args.repo_root), args.mode, args.date, sources)
    print(path.as_posix())


if __name__ == "__main__":
    main()
