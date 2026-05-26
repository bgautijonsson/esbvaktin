#!/usr/bin/env python3
"""Grammar-correct article capsule text via Málstaður.

Capsules live in `data/analyses/{id}/_report_final.json` under the
"capsule" key. The exporter reads that field when it builds report files
for the site, so updating it here flows through on the next re-export.

We also keep `_capsule.txt` in the same directory in sync (when present)
so the two on-disk views agree.

Usage:
    uv run python scripts/correct_capsules.py status
    uv run python scripts/correct_capsules.py correct --since 2026-05-02 --dry-run
    uv run python scripts/correct_capsules.py correct --since 2026-05-02
    uv run python scripts/correct_capsules.py correct --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # safe to call even if env is pre-populated — won't override

from esbvaktin.utils.malstadur import (  # noqa: E402
    MalstadurAuthError,
    MalstadurClient,
    MalstadurError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"

# Inline marker so re-runs can detect "already corrected" without a DB.
# Stored alongside `capsule` in _report_final.json.
CAPSULE_FLAG_KEY = "capsule_proofread_at"


def _parse_cutoff(since: str | None) -> float | None:
    if not since:
        return None
    dt = datetime.fromisoformat(since)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _iter_candidates(since_ts: float | None):
    """Yield (analysis_dir, report_path, report_data, capsule) for candidates."""
    if not ANALYSES_DIR.is_dir():
        return
    for adir in sorted(ANALYSES_DIR.iterdir()):
        if not adir.is_dir():
            continue
        report_path = adir / "_report_final.json"
        if not report_path.exists():
            continue
        if since_ts is not None and report_path.stat().st_mtime < since_ts:
            continue
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        capsule = (data.get("capsule") or "").strip()
        if not capsule:
            continue
        yield adir, report_path, data, capsule


def status(args: argparse.Namespace) -> None:
    since_ts = _parse_cutoff(args.since)
    candidates = list(_iter_candidates(since_ts))
    pending = [c for c in candidates if not c[2].get(CAPSULE_FLAG_KEY)]
    chars = sum(len(c[3]) for c in pending)
    print(f"{'=' * 60}")
    print("CAPSULE QUALITY STATUS")
    print(f"{'=' * 60}")
    print(f"  Candidates (with capsule): {len(candidates)}")
    print(f"  Already proofread:         {len(candidates) - len(pending)}")
    print(f"  Pending:                   {len(pending)} ({chars:,} chars, ~{chars // 100} kr)")
    if args.since:
        print(f"  Filter: report mtime >= {args.since}")
    print(f"{'=' * 60}")


def correct(args: argparse.Namespace) -> None:
    since_ts = _parse_cutoff(args.since)
    candidates = list(_iter_candidates(since_ts))
    pending = [c for c in candidates if not c[2].get(CAPSULE_FLAG_KEY)]

    if not pending:
        print("No pending capsules. Nothing to do.")
        return

    if args.limit:
        pending = pending[: args.limit]

    total_chars = sum(len(c[3]) for c in pending)
    cost = total_chars // 100
    print(f"Found {len(pending)} capsules ({total_chars:,} chars, ~{cost} kr)")
    if args.since:
        print(f"  Filter: report mtime >= {args.since}")

    if args.dry_run:
        print("\n--dry-run: would correct these capsules:")
        for adir, _path, _data, capsule in pending[:10]:
            print(f"  {adir.name:<40s} ({len(capsule):4d} chars)")
        if len(pending) > 10:
            print(f"  ... and {len(pending) - 10} more")
        return

    try:
        client = MalstadurClient()
    except MalstadurError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    corrected = 0
    changed = 0
    chars_done = 0
    errors: list[tuple[str, str]] = []
    smoke_logged = 0

    with client:
        for adir, report_path, data, capsule in pending:
            try:
                results = client.correct_grammar([capsule])
            except MalstadurAuthError as e:
                print(f"\nFATAL auth error — aborting run: {e}", file=sys.stderr)
                errors.append((adir.name, str(e)))
                break
            except MalstadurError as e:
                print(f"  {adir.name} API error: {e}")
                errors.append((adir.name, str(e)))
                continue
            except Exception as e:
                print(f"  {adir.name} unexpected error: {e}")
                errors.append((adir.name, str(e)))
                continue

            new_capsule = results[0] if results else capsule
            if smoke_logged < 5 and new_capsule != capsule:
                print(f"\n  [smoke] {adir.name}:")
                print(f"    BEFORE: {capsule[:160]}")
                print(f"    AFTER:  {new_capsule[:160]}")
                smoke_logged += 1

            if new_capsule != capsule:
                changed += 1
                data["capsule"] = new_capsule
            data[CAPSULE_FLAG_KEY] = datetime.now(UTC).isoformat(timespec="seconds")
            chars_done += len(capsule)

            try:
                report_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except Exception as e:
                print(f"  {adir.name} write error: {e}")
                errors.append((adir.name, str(e)))
                continue

            # Keep _capsule.txt in sync when it exists.
            capsule_txt = adir / "_capsule.txt"
            if capsule_txt.exists():
                try:
                    capsule_txt.write_text(new_capsule + "\n", encoding="utf-8")
                except Exception as e:
                    print(f"  {adir.name} _capsule.txt sync error: {e}")

            corrected += 1
            if corrected % 25 == 0:
                print(
                    f"  [{corrected}/{len(pending)}] processed, "
                    f"{changed} changed, {chars_done:,} chars"
                )

    print(f"\n{'=' * 60}")
    print("Capsule correction complete")
    print(f"  Capsules processed:  {corrected}")
    print(f"  Capsules changed:    {changed}")
    print(f"  Characters:          {chars_done:,}")
    print(f"  Est. cost:           ~{chars_done // 100} kr")
    if errors:
        print(f"  Errors:              {len(errors)}")
        for name, err in errors[:20]:
            print(f"    {name}: {err}")
    print(f"{'=' * 60}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Grammar-correct article capsules via Málstaður")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="Show pending capsules")
    s.add_argument("--since", help="Only count reports with mtime >= DATE (YYYY-MM-DD)")

    c = sub.add_parser("correct", help="Run correction")
    c.add_argument("--since", help="Only process reports with mtime >= DATE (YYYY-MM-DD)")
    c.add_argument("--limit", type=int, help="Cap number of reports")
    c.add_argument("--dry-run", action="store_true", help="Preview without API calls")

    args = parser.parse_args()

    if args.command == "status":
        status(args)
    elif args.command == "correct":
        correct(args)


if __name__ == "__main__":
    main()
