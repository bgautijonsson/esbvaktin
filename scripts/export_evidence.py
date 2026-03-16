"""Export all evidence entries for the /heimildir/ section of esbvaktin.is.

Queries the ground truth database and produces:
  - data/export/evidence_full.json   (all entries, all fields)
  - data/export/sources.json         (source_name → IS description lookup)
  - data/export/evidence_meta.json   (updated with slug + statement_is)

With --site-dir:
  - {site_dir}/assets/data/evidence.json   (lightweight listing for JS)
  - {site_dir}/assets/data/sources.json    (copy)

Usage:
    uv run python scripts/export_evidence.py
    uv run python scripts/export_evidence.py --site-dir ~/esbvaktin-site
    uv run python scripts/export_evidence.py --status
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = PROJECT_ROOT / "data" / "export"


def _get_connection():
    from esbvaktin.ground_truth.operations import get_connection
    return get_connection()


# ── Slug generation ────────────────────────────────────────────────────

def _make_slug(evidence_id: str) -> str:
    """evidence_id is already ASCII-safe — just lowercase it."""
    return evidence_id.lower()


# ── DB queries ─────────────────────────────────────────────────────────

_EVIDENCE_QUERY = """\
SELECT
    evidence_id, domain, topic, subtopic,
    statement, statement_is,
    source_name, source_url, source_date, source_type,
    source_description_is,
    confidence, caveats, caveats_is, related_entries,
    last_verified, created_at
FROM evidence
ORDER BY evidence_id
"""


def _fetch_evidence() -> list[dict]:
    """Fetch all evidence entries from the database."""
    conn = _get_connection()
    rows = conn.execute(_EVIDENCE_QUERY).fetchall()
    cols = [
        "evidence_id", "domain", "topic", "subtopic",
        "statement", "statement_is",
        "source_name", "source_url", "source_date", "source_type",
        "source_description_is",
        "confidence", "caveats", "caveats_is", "related_entries",
        "last_verified", "created_at",
    ]
    conn.close()

    entries = []
    for row in rows:
        entry = dict(zip(cols, row))
        # Add slug
        entry["slug"] = _make_slug(entry["evidence_id"])
        # Serialise dates
        for date_field in ("source_date", "last_verified", "created_at"):
            val = entry.get(date_field)
            if val is not None:
                entry[date_field] = str(val)
        # related_entries: psycopg returns list or None
        if entry["related_entries"] is None:
            entry["related_entries"] = []
        entries.append(entry)

    return entries


# ── Sources lookup ─────────────────────────────────────────────────────

def _build_sources_lookup(entries: list[dict]) -> dict[str, dict]:
    """Build source_name → {description_is, count, url} lookup.

    Picks the most common source_description_is per source_name.
    """
    from collections import Counter

    source_desc: dict[str, Counter] = {}
    source_urls: dict[str, str | None] = {}
    source_counts: dict[str, int] = {}

    for e in entries:
        name = e["source_name"]
        source_counts[name] = source_counts.get(name, 0) + 1
        if name not in source_urls and e.get("source_url"):
            source_urls[name] = e["source_url"]
        desc = e.get("source_description_is")
        if desc:
            if name not in source_desc:
                source_desc[name] = Counter()
            source_desc[name][desc] += 1

    lookup = {}
    for name in sorted(source_counts):
        entry: dict = {"count": source_counts[name]}
        if name in source_urls:
            entry["url"] = source_urls[name]
        if name in source_desc:
            entry["description_is"] = source_desc[name].most_common(1)[0][0]
        lookup[name] = entry

    return lookup


# ── Listing entry (lightweight for client-side JS) ─────────────────────

def _listing_entry(e: dict) -> dict:
    """Lightweight version of an evidence entry for the listing page."""
    return {
        "slug": e["slug"],
        "evidence_id": e["evidence_id"],
        "domain": e["domain"],
        "topic": e["topic"],
        "source_type": e["source_type"],
        "confidence": e["confidence"],
        "statement": e.get("statement_is") or e["statement"],
        "source_name": e["source_name"],
        "source_date": e.get("source_date"),
        "related_count": len(e.get("related_entries", [])),
    }


# ── Evidence meta (backward-compatible with export_evidence_meta.py) ───

def _build_evidence_meta(entries: list[dict]) -> dict[str, dict]:
    """Build {evidence_id: {source_name, source_url, slug, statement_is}} lookup."""
    lookup = {}
    for e in entries:
        meta: dict = {
            "source_name": e["source_name"],
            "source_url": e.get("source_url"),
            "slug": e["slug"],
        }
        if e.get("statement_is"):
            meta["statement_is"] = e["statement_is"]
        lookup[e["evidence_id"]] = meta
    return lookup


# ── Status report ──────────────────────────────────────────────────────

def _print_status(entries: list[dict]) -> None:
    """Print a summary of the evidence database."""
    total = len(entries)
    with_is = sum(1 for e in entries if e.get("statement_is"))
    with_url = sum(1 for e in entries if e.get("source_url"))
    with_related = sum(1 for e in entries if e.get("related_entries"))

    topics: dict[str, int] = {}
    domains: dict[str, int] = {}
    source_types: dict[str, int] = {}
    confidence: dict[str, int] = {}

    for e in entries:
        topics[e["topic"]] = topics.get(e["topic"], 0) + 1
        domains[e["domain"]] = domains.get(e["domain"], 0) + 1
        source_types[e["source_type"]] = source_types.get(e["source_type"], 0) + 1
        confidence[e["confidence"]] = confidence.get(e["confidence"], 0) + 1

    print(f"\nEvidence Database: {total} entries")
    print(f"  Icelandic summaries: {with_is}/{total} ({with_is / total * 100:.0f}%)")
    print(f"  With source URLs:    {with_url}/{total}")
    print(f"  With related:        {with_related}/{total}")

    print(f"\nBy topic ({len(topics)}):")
    for t, c in sorted(topics.items(), key=lambda x: -x[1]):
        print(f"  {t:25s} {c}")

    print(f"\nBy domain ({len(domains)}):")
    for d, c in sorted(domains.items(), key=lambda x: -x[1]):
        print(f"  {d:25s} {c}")

    print(f"\nBy source type ({len(source_types)}):")
    for s, c in sorted(source_types.items(), key=lambda x: -x[1]):
        print(f"  {s:25s} {c}")

    print("\nBy confidence:")
    for cf, c in sorted(confidence.items(), key=lambda x: -x[1]):
        print(f"  {cf:25s} {c}")


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Export evidence for esbvaktin.is")
    parser.add_argument("--site-dir", type=Path, help="Site repo directory")
    parser.add_argument("--status", action="store_true", help="Print DB summary")
    args = parser.parse_args()

    entries = _fetch_evidence()

    if args.status:
        _print_status(entries)
        return

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Full export
    full_path = EXPORT_DIR / "evidence_full.json"
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f"Exported {len(entries)} evidence entries → {full_path}")

    # Sources lookup
    sources = _build_sources_lookup(entries)
    sources_path = EXPORT_DIR / "sources.json"
    with open(sources_path, "w", encoding="utf-8") as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)
    print(f"Exported {len(sources)} sources → {sources_path}")

    # Evidence meta (backward-compatible)
    meta = _build_evidence_meta(entries)
    meta_path = EXPORT_DIR / "evidence_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Exported evidence_meta.json ({len(meta)} entries) → {meta_path}")

    # Site assets
    if args.site_dir:
        site_dir = args.site_dir.expanduser().resolve()
        assets_dir = site_dir / "assets" / "data"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # Lightweight listing
        listing = [_listing_entry(e) for e in entries]
        listing_path = assets_dir / "evidence.json"
        with open(listing_path, "w", encoding="utf-8") as f:
            json.dump(listing, f, ensure_ascii=False, indent=2)
        print(f"Wrote listing JSON: {len(listing)} entries → {listing_path}")

        # Sources copy
        site_sources_path = assets_dir / "sources.json"
        with open(site_sources_path, "w", encoding="utf-8") as f:
            json.dump(sources, f, ensure_ascii=False, indent=2)
        print(f"Wrote sources JSON → {site_sources_path}")


if __name__ == "__main__":
    main()
