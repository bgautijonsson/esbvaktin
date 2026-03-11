"""Export claims from PostgreSQL to Parquet + JSON for the client-side claim tracker.

Usage:
    uv run python scripts/export_claims.py --site-dir ~/esbvaktin-site  # Export + copy to site
    uv run python scripts/export_claims.py              # Export to data/export/ only
    uv run python scripts/export_claims.py --all        # Export all claims (including unpublished)
    uv run python scripts/export_claims.py --status     # Show export stats

Output:
    data/export/claims.parquet   — for DuckDB-WASM in the browser
    data/export/claims.json      — fallback for non-WASM browsers
    {site-dir}/assets/data/claims.json  — if --site-dir provided
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = PROJECT_ROOT / "data" / "export"


def _get_connection():
    """Get a psycopg connection using standard project config."""
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")

    import psycopg

    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="esbvaktin",
        user="esb",
        password="localdev",
    )


def _fetch_claims(*, include_unpublished: bool = False) -> list[dict]:
    """Fetch denormalised claims with sighting data from PostgreSQL."""
    conn = _get_connection()

    where_clause = "" if include_unpublished else "WHERE c.published = TRUE"

    rows = conn.execute(
        f"""
        SELECT
            c.claim_slug,
            c.canonical_text_is,
            c.canonical_text_en,
            c.category,
            c.claim_type,
            c.verdict,
            c.explanation_is,
            c.explanation_en,
            c.missing_context_is,
            c.confidence,
            c.last_verified,
            c.version,
            c.created_at,
            COUNT(s.id) AS sighting_count,
            MAX(s.source_date) AS last_seen,
            MIN(s.source_date) AS first_seen
        FROM claims c
        LEFT JOIN claim_sightings s ON c.id = s.claim_id
        {where_clause}
        GROUP BY c.id
        ORDER BY COUNT(s.id) DESC, c.category, c.claim_slug
        """
    ).fetchall()

    columns = [
        "claim_slug", "canonical_text_is", "canonical_text_en",
        "category", "claim_type", "verdict",
        "explanation_is", "explanation_en", "missing_context_is",
        "confidence", "last_verified", "version", "created_at",
        "sighting_count", "last_seen", "first_seen",
    ]

    claims = []
    for row in rows:
        claim = dict(zip(columns, row))
        # Convert dates/datetimes to strings for JSON serialisation
        for key in ("last_verified", "last_seen", "first_seen"):
            if isinstance(claim[key], (date, datetime)):
                claim[key] = claim[key].isoformat()
        if isinstance(claim["created_at"], datetime):
            claim["created_at"] = claim["created_at"].isoformat()
        claims.append(claim)

    # Fetch individual sightings and attach to claims
    sighting_rows = conn.execute(
        f"""
        SELECT
            c.claim_slug,
            s.source_url,
            s.source_title,
            s.source_date,
            s.source_type
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        {where_clause}
        ORDER BY s.source_date DESC
        """
    ).fetchall()

    sightings_by_slug: dict[str, list[dict]] = {}
    for slug, url, title, sdate, stype in sighting_rows:
        sighting = {
            "source_url": url,
            "source_title": title,
            "source_date": sdate.isoformat() if isinstance(sdate, (date, datetime)) else sdate,
            "source_type": stype,
        }
        sightings_by_slug.setdefault(slug, []).append(sighting)

    for claim in claims:
        claim["sightings"] = sightings_by_slug.get(claim["claim_slug"], [])

    conn.close()
    return claims


def _to_parquet(claims: list[dict], path: Path) -> None:
    """Write claims to a Parquet file."""
    if not claims:
        print("No claims to export.")
        return

    # Build Arrow arrays column by column
    columns = {
        "claim_slug": pa.array([c["claim_slug"] for c in claims], type=pa.string()),
        "canonical_text_is": pa.array([c["canonical_text_is"] for c in claims], type=pa.string()),
        "canonical_text_en": pa.array([c["canonical_text_en"] for c in claims], type=pa.string()),
        "category": pa.array([c["category"] for c in claims], type=pa.string()),
        "claim_type": pa.array([c["claim_type"] for c in claims], type=pa.string()),
        "verdict": pa.array([c["verdict"] for c in claims], type=pa.string()),
        "explanation_is": pa.array([c["explanation_is"] for c in claims], type=pa.string()),
        "explanation_en": pa.array([c["explanation_en"] for c in claims], type=pa.string()),
        "missing_context_is": pa.array(
            [c["missing_context_is"] for c in claims], type=pa.string()
        ),
        "confidence": pa.array([c["confidence"] for c in claims], type=pa.float32()),
        "last_verified": pa.array([c["last_verified"] for c in claims], type=pa.string()),
        "version": pa.array([c["version"] for c in claims], type=pa.int32()),
        "created_at": pa.array([c["created_at"] for c in claims], type=pa.string()),
        "sighting_count": pa.array([c["sighting_count"] for c in claims], type=pa.int32()),
        "last_seen": pa.array([c["last_seen"] for c in claims], type=pa.string()),
        "first_seen": pa.array([c["first_seen"] for c in claims], type=pa.string()),
        "sightings_json": pa.array(
            [json.dumps(c.get("sightings", []), ensure_ascii=False) for c in claims],
            type=pa.string(),
        ),
    }

    table = pa.table(columns)
    pq.write_table(table, path, compression="snappy")


def _to_json(claims: list[dict], path: Path) -> None:
    """Write claims to a JSON file (fallback for non-WASM browsers)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(claims, f, ensure_ascii=False, indent=2)


_ICE_CHARS = re.compile(r"[þðáéíóúýæöÞÐÁÉÍÓÚÝÆÖ]")
_ICELANDIC_FIELDS = ["explanation_is", "missing_context_is"]


def _validate_icelandic(claims: list[dict]) -> int:
    """Check for ASCII-only Icelandic text. Prints warnings, returns count."""
    flagged = 0
    for c in claims:
        for field in _ICELANDIC_FIELDS:
            text = c.get(field, "") or ""
            if len(text) > 50 and not _ICE_CHARS.search(text):
                slug = c.get("claim_slug", "?")
                print(f"  WARNING: ASCII-only {field} in {slug}")
                flagged += 1
    return flagged


def _show_status(claims: list[dict]) -> None:
    """Print export summary stats."""
    print(f"Total claims: {len(claims)}")

    if not claims:
        return

    # Verdict breakdown
    verdicts: dict[str, int] = {}
    categories: dict[str, int] = {}
    for c in claims:
        verdicts[c["verdict"]] = verdicts.get(c["verdict"], 0) + 1
        categories[c["category"]] = categories.get(c["category"], 0) + 1

    print("\nBy verdict:")
    for v, n in sorted(verdicts.items(), key=lambda x: -x[1]):
        print(f"  {v}: {n}")

    print("\nBy category:")
    for cat, n in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {n}")

    total_sightings = sum(c["sighting_count"] for c in claims)
    print(f"\nTotal sightings: {total_sightings}")


def _parse_site_dir() -> Path | None:
    """Parse --site-dir argument."""
    if "--site-dir" in sys.argv:
        idx = sys.argv.index("--site-dir")
        if idx + 1 < len(sys.argv):
            return Path(sys.argv[idx + 1]).expanduser()
    return None


def main() -> None:
    include_all = "--all" in sys.argv
    status_only = "--status" in sys.argv
    site_dir = _parse_site_dir()

    claims = _fetch_claims(include_unpublished=include_all or status_only)

    if status_only:
        _show_status(claims)
        return

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    parquet_path = EXPORT_DIR / "claims.parquet"
    json_path = EXPORT_DIR / "claims.json"

    # Validate Icelandic text before export
    ascii_count = _validate_icelandic(claims)
    if ascii_count > 0:
        print(f"\n  {ascii_count} field(s) with ASCII-only Icelandic text (see warnings above)\n")

    _to_parquet(claims, parquet_path)
    _to_json(claims, json_path)

    # Copy to site repo if --site-dir provided
    if site_dir:
        import shutil

        site_claims = site_dir / "assets" / "data" / "claims.json"
        site_claims.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_path, site_claims)
        print(f"  {site_claims}")

    label = "all" if include_all else "published"
    print(f"Exported {len(claims)} {label} claims:")
    print(f"  {parquet_path}")
    print(f"  {json_path}")
    _show_status(claims)


if __name__ == "__main__":
    main()
