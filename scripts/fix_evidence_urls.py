"""Fix evidence source URLs — update generic/missing URLs with specific deep links.

Usage:
    # Show current URL quality stats:
    uv run python scripts/fix_evidence_urls.py status

    # Preview fixes from a JSON file (dry run):
    uv run python scripts/fix_evidence_urls.py preview data/seeds/url_fixes.json

    # Apply fixes:
    uv run python scripts/fix_evidence_urls.py apply data/seeds/url_fixes.json
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from esbvaktin.ground_truth import get_connection


def show_status() -> None:
    """Show URL quality breakdown by topic."""
    conn = get_connection()
    cur = conn.execute("""
        SELECT topic,
               COUNT(*) AS total,
               COUNT(CASE WHEN source_url IS NOT NULL AND source_url != ''
                          AND length(source_url) - length(replace(source_url, '/', '')) > 3
                     THEN 1 END) AS specific,
               COUNT(CASE WHEN source_url IS NULL OR source_url = ''
                     THEN 1 END) AS missing,
               COUNT(CASE WHEN source_url IS NOT NULL AND source_url != ''
                          AND length(source_url) - length(replace(source_url, '/', '')) <= 3
                     THEN 1 END) AS generic
        FROM evidence
        GROUP BY topic
        ORDER BY total DESC
    """)
    rows = cur.fetchall()

    total_all = sum(r[1] for r in rows)
    specific_all = sum(r[2] for r in rows)
    missing_all = sum(r[3] for r in rows)
    generic_all = sum(r[4] for r in rows)

    print(f"\nEvidence URL quality — {total_all} entries\n")
    print(f"  {'Topic':<20} {'Total':>5} {'Specific':>8} {'Missing':>7} {'Generic':>7}")
    print(f"  {'─' * 48}")
    for topic, total, specific, missing, generic in rows:
        print(f"  {topic:<20} {total:>5} {specific:>8} {missing:>7} {generic:>7}")
    print(f"  {'─' * 48}")
    print(f"  {'TOTAL':<20} {total_all:>5} {specific_all:>8} {missing_all:>7} {generic_all:>7}")
    pct = specific_all / total_all * 100 if total_all else 0
    print(f"\n  Specific URL rate: {pct:.1f}%\n")
    conn.close()


def load_fixes(path: Path) -> list[dict]:
    """Load URL fixes from JSON. Format: [{evidence_id, source_url}, ...]."""
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = [data]
    for fix in data:
        if "evidence_id" not in fix or "source_url" not in fix:
            print(f"  ERROR: fix missing required fields: {fix}")
            sys.exit(1)
    return data


def preview_fixes(path: Path) -> None:
    """Show what would change."""
    fixes = load_fixes(path)
    conn = get_connection()

    print(f"\nPreviewing {len(fixes)} URL fixes from {path.name}\n")
    found = 0
    for fix in fixes:
        eid = fix["evidence_id"]
        new_url = fix["source_url"]
        cur = conn.execute(
            "SELECT source_url FROM evidence WHERE evidence_id = %s", (eid,)
        )
        row = cur.fetchone()
        if row is None:
            print(f"  SKIP {eid}: not in DB")
            continue
        old_url = row[0] or "(none)"
        if old_url == new_url:
            print(f"  SKIP {eid}: already correct")
            continue
        found += 1
        print(f"  {eid}")
        print(f"    old: {old_url}")
        print(f"    new: {new_url}")

    print(f"\n  {found} entries would be updated\n")
    conn.close()


def apply_fixes(path: Path) -> None:
    """Apply URL fixes to the database."""
    fixes = load_fixes(path)
    conn = get_connection()

    updated = 0
    skipped = 0
    for fix in fixes:
        eid = fix["evidence_id"]
        new_url = fix["source_url"]
        cur = conn.execute(
            "UPDATE evidence SET source_url = %s WHERE evidence_id = %s AND (source_url IS NULL OR source_url = '' OR source_url != %s)",
            (new_url, eid, new_url),
        )
        if cur.rowcount:
            updated += 1
        else:
            skipped += 1

    conn.commit()
    conn.close()
    print(f"\n  Updated {updated} URLs, skipped {skipped}\n")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "status":
        show_status()
    elif cmd in ("preview", "apply"):
        if len(sys.argv) < 3:
            print(f"Usage: fix_evidence_urls.py {cmd} <json_file>")
            sys.exit(1)
        path = Path(sys.argv[2])
        if not path.exists():
            print(f"File not found: {path}")
            sys.exit(1)
        if cmd == "preview":
            preview_fixes(path)
        else:
            apply_fixes(path)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
