#!/usr/bin/env python3
"""xrepo-01 registry-retirement gate — read-only consumer_state coverage check.

Before article_registry.json is retired, every URL its three sources know
(data/analyses/ reports, ~/esbvaktin-site/_data/reports, DB claim_sightings) must be
covered by frettasafn consumer_state — otherwise retiring the local mirror would lose
dedup for those articles, making them re-analysable. This check NEVER writes; it exits
non-zero on gaps so the retirement is blocked until an operator backfills them via
``esbvaktin.utils.frettasafn_state.mark_urls`` and re-runs.

Usage:
    uv run python scripts/retire_registry.py        # check consumer_state coverage
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"
SITE_REPORTS_DIR = Path.home() / "esbvaktin-site" / "_data" / "reports"


def _norm(url: str) -> str:
    return (url or "").rstrip("/").lower()


def uncovered_urls(
    source_urls: set[str],
    locally_covered: set[str],
    state_by_url: dict[str, str | None],
) -> set[str]:
    """URLs that would lose dedup if the registry is retired.

    After retirement two mechanisms remain: check_duplicate's data/analyses/ scan
    (covers ``locally_covered``) and the consumer_state URL check (covers any URL with a
    non-None state). A URL is at risk only if NEITHER covers it — i.e. it is not locally
    scanned AND absent from consumer_state. (A data/analyses/ URL missing from
    consumer_state is still scan-covered, so it is not at risk.)
    """
    return {u for u in source_urls if u not in locally_covered and state_by_url.get(u) is None}


# ── Source URL gathering (thin I/O) ──────────────────────────────────


def analyses_urls() -> set[str]:
    urls: set[str] = set()
    if not ANALYSES_DIR.exists():
        return urls
    for rp in ANALYSES_DIR.glob("*/_report_final.json"):
        try:
            url = json.loads(rp.read_text()).get("article_url", "")
        except Exception:
            continue
        if url:
            urls.add(_norm(url))
    return urls


def site_report_urls() -> set[str]:
    urls: set[str] = set()
    if not SITE_REPORTS_DIR.exists():
        return urls
    for f in SITE_REPORTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        url = data.get("article_url") or data.get("url", "")
        if url:
            urls.add(_norm(url))
    return urls


def db_sighting_urls(conn) -> set[str]:
    rows = conn.execute("SELECT DISTINCT source_url FROM claim_sightings").fetchall()
    return {_norm(r[0]) for r in rows if r[0]}


def consumer_state_by_url(urls) -> dict[str, str | None]:
    from esbvaktin.utils.frettasafn_state import is_known_url

    out: dict[str, str | None] = {}
    for url in urls:
        rec = is_known_url(url)
        out[url] = rec["state"] if rec else None
    return out


def main(argv: list[str] | None = None) -> int:
    from esbvaktin.ground_truth.operations import get_connection

    # data/analyses/ URLs stay covered by check_duplicate's scan post-retirement, so they
    # are never at risk. Only site/DB-only URLs (not locally scanned) need consumer_state.
    local = analyses_urls()
    conn = get_connection()
    try:
        candidates = (site_report_urls() | db_sighting_urls(conn)) - local
    finally:
        conn.close()

    state = consumer_state_by_url(candidates)
    gaps = uncovered_urls(candidates, local, state)

    if not gaps:
        print(
            f"Coverage OK: {len(local)} data/analyses/ URLs stay scan-covered; all "
            f"{len(candidates)} site/DB-only URLs are in consumer_state. "
            "Safe to retire article_registry.json."
        )
        return 0

    print(
        f"BLOCKED: {len(gaps)} of {len(candidates)} site/DB-only URLs are neither locally "
        "scanned nor in consumer_state — retiring the registry would lose their dedup:",
        file=sys.stderr,
    )
    for u in sorted(gaps):
        print(f"  - {u}", file=sys.stderr)
    print(
        "\nBackfill them into consumer_state (esbvaktin.utils.frettasafn_state.mark_urls) "
        "and re-run before deleting the registry.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
