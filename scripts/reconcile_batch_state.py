#!/usr/bin/env python3
"""Post-batch state reconciliation validator (rel-06).

A read-only consistency check across the three state stores a processing batch touches:

  - data/inbox/inbox.json      (per-article status)
  - frettasafn consumer_state  (the canonical dedup state)
  - claim_sightings (Postgres) (per-report sightings)

Catches the documented silent-drop failure modes:

  - processed_without_consumer_state: inbox says processed, consumer_state disagrees
  - queued_but_processed:             inbox stuck at queued while consumer_state=processed
  - report_without_sightings:         a recent report registered no sightings

Read-only — it never writes anything. Exits non-zero on drift so the overnight batch can
fail loud and surface a stranded article or a dropped verdict for review.

Usage:
    uv run python scripts/reconcile_batch_state.py            # check recent reports (2 days)
    uv run python scripts/reconcile_batch_state.py --days 7   # widen the report window
"""

from __future__ import annotations

import json
import sys
import time
from collections import namedtuple
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INBOX_PATH = PROJECT_ROOT / "data" / "inbox" / "inbox.json"
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"

Finding = namedtuple("Finding", ["kind", "url", "detail"])


def _norm(url: str) -> str:
    return (url or "").rstrip("/").lower()


# ── Pure reconciliation ──────────────────────────────────────────────


def reconcile(inbox_entries, consumer_state_by_url, report_urls, sighting_urls) -> list:
    """Find cross-store drift. URLs are assumed already normalised by the caller."""
    findings: list = []
    for e in inbox_entries:
        url = e["url"]
        status = e["status"]
        cs = consumer_state_by_url.get(url)
        if status == "processed" and cs != "processed":
            findings.append(
                Finding(
                    "processed_without_consumer_state",
                    url,
                    f"inbox=processed but consumer_state={cs!r}",
                )
            )
        if status == "queued" and cs == "processed":
            findings.append(
                Finding(
                    "queued_but_processed",
                    url,
                    "inbox stuck at queued while consumer_state=processed (stranded)",
                )
            )
    for url in sorted(report_urls):
        if url not in sighting_urls:
            findings.append(
                Finding("report_without_sightings", url, "recent report registered no sightings")
            )
    return findings


def has_drift(findings) -> bool:
    return bool(findings)


# ── Loaders (thin I/O) ───────────────────────────────────────────────


def load_inbox_entries(path: Path = INBOX_PATH) -> list[dict]:
    if not path.exists():
        return []
    return [
        {"url": _norm(e.get("url", "")), "status": e.get("status", "")}
        for e in json.loads(path.read_text())
        if e.get("url")
    ]


def load_consumer_state_by_url(urls) -> dict:
    from esbvaktin.utils.frettasafn_state import is_known_url

    out: dict = {}
    for url in urls:
        rec = is_known_url(url)
        out[url] = rec["state"] if rec else None
    return out


def recent_report_urls(days: int = 2, now: float | None = None) -> set:
    """article_urls of reports written within the last `days` (approx. 'this batch')."""
    if not ANALYSES_DIR.exists():
        return set()
    cutoff = (now if now is not None else time.time()) - days * 86400
    urls = set()
    for rp in ANALYSES_DIR.glob("*/_report_final.json"):
        if rp.stat().st_mtime < cutoff:
            continue
        try:
            report = json.loads(rp.read_text())
        except Exception:
            continue
        url = _norm(report.get("article_url", ""))
        if url:
            urls.add(url)
    return urls


def load_sighting_urls(conn) -> set:
    rows = conn.execute("SELECT DISTINCT source_url FROM claim_sightings").fetchall()
    return {_norm(r[0]) for r in rows if r[0]}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    days = 2
    if "--days" in argv:
        i = argv.index("--days")
        if i + 1 < len(argv):
            days = int(argv[i + 1])

    inbox = load_inbox_entries()
    consumer_state = load_consumer_state_by_url([e["url"] for e in inbox])
    reports = recent_report_urls(days=days)

    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()
    try:
        sightings = load_sighting_urls(conn)
    finally:
        conn.close()

    findings = reconcile(inbox, consumer_state, reports, sightings)

    if not has_drift(findings):
        print(
            f"Batch state reconciliation OK "
            f"({len(inbox)} inbox entries, {len(reports)} recent reports)."
        )
        return 0

    print(f"DRIFT: {len(findings)} reconciliation finding(s):", file=sys.stderr)
    by_kind: dict[str, list] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    for kind in sorted(by_kind):
        print(f"\n## {kind} ({len(by_kind[kind])})", file=sys.stderr)
        for f in by_kind[kind]:
            print(f"  - {f.url}: {f.detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
