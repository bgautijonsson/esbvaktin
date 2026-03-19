"""Backfill NULL article dates in DB sightings and report files.

Resolves dates from the inbox and URL patterns using the metadata utility.
Two passes: DB sightings first, then local report files.

Usage:
    uv run python scripts/backfill_article_dates.py              # Full backfill
    uv run python scripts/backfill_article_dates.py --dry-run    # Preview only
    uv run python scripts/backfill_article_dates.py --db-only    # DB sightings only
    uv run python scripts/backfill_article_dates.py --files-only # Report files only
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from esbvaktin.utils.metadata import resolve_metadata

ANALYSES_DIR = Path("data/analyses")

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def backfill_db(dry_run: bool = False) -> dict[str, int]:
    """Fix NULL source_date in claim_sightings using metadata resolution."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()
    cur = conn.execute(
        "SELECT DISTINCT source_url FROM claim_sightings WHERE source_date IS NULL"
    )
    null_urls = [row[0] for row in cur.fetchall() if row[0]]

    if not null_urls:
        logger.info("No NULL source_date rows in DB.")
        return {"resolved": 0, "remaining": 0}

    logger.info("Found %d distinct URLs with NULL source_date", len(null_urls))

    resolved = 0
    remaining = 0
    for url in null_urls:
        meta = resolve_metadata(url)
        if meta.date:
            if not dry_run:
                conn.execute(
                    "UPDATE claim_sightings SET source_date = %s "
                    "WHERE source_url = %s AND source_date IS NULL",
                    (meta.date, url),
                )
                conn.commit()
            logger.info("  %s → %s", url[:60], meta.date)
            resolved += 1
        else:
            logger.debug("  %s → no date found", url[:60])
            remaining += 1

    # Also backfill missing source_title where possible
    cur = conn.execute(
        "SELECT DISTINCT source_url FROM claim_sightings "
        "WHERE (source_title IS NULL OR source_title = '') AND source_url IS NOT NULL"
    )
    null_title_urls = [row[0] for row in cur.fetchall() if row[0]]
    titles_fixed = 0
    for url in null_title_urls:
        meta = resolve_metadata(url)
        if meta.title:
            if not dry_run:
                conn.execute(
                    "UPDATE claim_sightings SET source_title = %s "
                    "WHERE source_url = %s AND (source_title IS NULL OR source_title = '')",
                    (meta.title, url),
                )
                conn.commit()
            titles_fixed += 1

    if titles_fixed:
        logger.info("Also fixed %d missing source_title values", titles_fixed)

    conn.close()
    return {"resolved": resolved, "remaining": remaining}


def backfill_files(dry_run: bool = False) -> dict[str, int]:
    """Fix NULL article_date in local _report_final.json files."""
    report_paths = sorted(ANALYSES_DIR.glob("*/_report_final.json"))

    if not report_paths:
        logger.info("No report files found.")
        return {"resolved": 0, "remaining": 0}

    resolved = 0
    remaining = 0
    for path in report_paths:
        try:
            report = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("  Skipping %s: %s", path.parent.name, e)
            continue

        if report.get("article_date"):
            continue  # Already has a date

        url = report.get("article_url", "")
        if not url:
            remaining += 1
            continue

        meta = resolve_metadata(url)
        patched = False

        if meta.date and not report.get("article_date"):
            report["article_date"] = str(meta.date)
            patched = True

        if meta.title and not report.get("article_title"):
            report["article_title"] = meta.title
            patched = True

        if meta.source and not report.get("article_source"):
            report["article_source"] = meta.source
            patched = True

        if patched:
            if not dry_run:
                path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
            logger.info(
                "  %s → date=%s title=%s",
                path.parent.name,
                report.get("article_date", "?"),
                (report.get("article_title") or "?")[:40],
            )
            resolved += 1
        else:
            remaining += 1

    return {"resolved": resolved, "remaining": remaining}


def main():
    parser = argparse.ArgumentParser(description="Backfill NULL article dates")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--db-only", action="store_true", help="Only fix DB sightings")
    parser.add_argument("--files-only", action="store_true", help="Only fix report files")
    args = parser.parse_args()

    prefix = "[DRY RUN] " if args.dry_run else ""
    do_db = not args.files_only
    do_files = not args.db_only

    if do_db:
        print(f"\n{prefix}=== Pass 1: DB claim_sightings ===")
        db_counts = backfill_db(dry_run=args.dry_run)
        print(f"{prefix}DB: {db_counts['resolved']} resolved, {db_counts['remaining']} remaining")

    if do_files:
        print(f"\n{prefix}=== Pass 2: Report files ===")
        file_counts = backfill_files(dry_run=args.dry_run)
        print(
            f"{prefix}Files: {file_counts['resolved']} resolved, "
            f"{file_counts['remaining']} remaining"
        )

    if do_db and do_files:
        total_resolved = db_counts["resolved"] + file_counts["resolved"]
        total_remaining = db_counts["remaining"] + file_counts["remaining"]
        print(f"\n{prefix}Total: {total_resolved} resolved, {total_remaining} remaining NULLs")


if __name__ == "__main__":
    main()
