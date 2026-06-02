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

# Verified slug-drift orphans (xrepo-01): the esbvaktin-stored (normalised) URL maps to a
# real frettasafn article_id, but the article's slug drifted post-publish so is_known_url
# cannot resolve the stored URL. We mark the article_id (future reposts arrive via
# frettasafn's canonical URL and stay deduped) and the gate excludes these URLs from its
# audited candidate set. See docs/specs/2026-06-02-xrepo-01-registry-retirement-design.md.
ORPHAN_BACKFILL: dict[str, str] = {
    "https://www.visir.is/g/20262853438d/thridjungur-and-vigur-at-kvaeda-greidslunni": "c3f9a5f8dfaa91c9",  # noqa: E501
    "https://www.visir.is/g/20262859056d/gudrun-um-thorgerdi-yfirlaeti-hefur-ekki-reynst-henni-radgjafi-": "ff54198e3b0a1c56",  # noqa: E501
}


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


def gate_candidates(local: set[str], site_db: set[str]) -> set[str]:
    """Site/DB-only URLs the gate audits: drop locally-scanned URLs (still covered by
    check_duplicate's data/analyses/ scan post-retirement) and the known slug-drift
    orphans (handled out-of-band by marking their article_ids; their URLs cannot resolve)."""
    return site_db - local - {_norm(u) for u in ORPHAN_BACKFILL}


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


def backfill(
    gaps: set[str],
    *,
    mark_urls_fn=None,
    mark_articles_fn=None,
) -> tuple[int, list[str]]:
    """Write the gap URLs into consumer_state. Resolvable URLs are marked by URL; the known
    slug-drift orphans (which cannot resolve by URL) are marked by their verified
    article_id. A guard asserts the unmatched-by-URL set is exactly the known orphans, so a
    drifted gap set fails loud instead of mis-backfilling. Returns
    (url_resolved_rows, orphan_article_ids_written). Deps injectable for testing."""
    from esbvaktin.utils import frettasafn_state

    mark_urls_fn = mark_urls_fn or frettasafn_state.mark_urls
    mark_articles_fn = mark_articles_fn or frettasafn_state.mark_articles

    meta = {"backfilled_by": "xrepo-01", "reason": "pre-Phase-3 gap"}
    url_rows, unmatched = mark_urls_fn(
        sorted(gaps), "processed", metadata_per_url=dict.fromkeys(gaps, meta)
    )

    expected_orphans = {_norm(u) for u in ORPHAN_BACKFILL}
    if set(unmatched) != expected_orphans:
        raise RuntimeError(
            f"backfill guard: URLs unmatched by frettasafn ({sorted(unmatched)}) != known "
            f"orphans ({sorted(expected_orphans)}). The gap set drifted — re-verify "
            "ORPHAN_BACKFILL before backfilling."
        )

    orphan_ids = list(ORPHAN_BACKFILL.values())
    mark_articles_fn(orphan_ids, "processed", metadata=meta)
    return url_rows, orphan_ids


def main(argv: list[str] | None = None) -> int:
    import argparse

    from esbvaktin.ground_truth.operations import get_connection

    parser = argparse.ArgumentParser(description="xrepo-01 registry-retirement gate.")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Write the gap URLs into consumer_state (resolvable URLs by URL, known "
        "orphans by article_id), then re-run without this flag to confirm 0 gaps.",
    )
    ns = parser.parse_args(argv)

    # data/analyses/ URLs stay covered by check_duplicate's scan post-retirement, so they
    # are never at risk. Only site/DB-only URLs (not locally scanned) need consumer_state.
    local = analyses_urls()
    conn = get_connection()
    try:
        site_db = site_report_urls() | db_sighting_urls(conn)
    finally:
        conn.close()

    if ns.backfill:
        # Raw gap set (no orphan exclusion): resolvable URLs are marked by URL and the
        # orphans surface as unmatched for the by-article_id backfill.
        raw = site_db - local
        raw_gaps = uncovered_urls(raw, local, consumer_state_by_url(raw))
        if not raw_gaps:
            print("Nothing to backfill — consumer_state already covers every gap.")
            return 0
        url_rows, orphan_ids = backfill(raw_gaps)
        print(
            f"Backfilled {url_rows} URL-resolved + {len(orphan_ids)} orphan-id "
            "consumer_state rows. Re-run `retire_registry.py` (no flag) to confirm 0 gaps."
        )
        return 0

    candidates = gate_candidates(local, site_db)
    state = consumer_state_by_url(candidates)
    gaps = uncovered_urls(candidates, local, state)

    if not gaps:
        print(
            f"Coverage OK: {len(local)} data/analyses/ URLs stay scan-covered; all "
            f"{len(candidates)} audited site/DB-only URLs are in consumer_state "
            f"({len(ORPHAN_BACKFILL)} slug-drift orphans excluded — backfilled by "
            "article_id). Safe to retire article_registry.json."
        )
        return 0

    print(
        f"BLOCKED: {len(gaps)} of {len(candidates)} audited site/DB-only URLs are neither "
        "locally scanned nor in consumer_state — retiring the registry would lose their "
        "dedup:",
        file=sys.stderr,
    )
    for u in sorted(gaps):
        print(f"  - {u}", file=sys.stderr)
    print(
        "\nRun `retire_registry.py --backfill` to write them into consumer_state, then "
        "re-run to confirm 0.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
