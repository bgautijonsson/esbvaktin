"""Export evidence metadata (id → source_name, source_url) for the site.

Usage:
    uv run python scripts/export_evidence_meta.py

Output:
    data/export/evidence_meta.json
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = PROJECT_ROOT / "data" / "export"


def _get_connection():
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


def export_evidence_meta() -> dict[str, dict]:
    """Query DB for all evidence entries and return {id: {name, url}} lookup."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT evidence_id, source_name, source_url FROM evidence ORDER BY evidence_id"
    ).fetchall()
    conn.close()

    lookup = {}
    for evidence_id, source_name, source_url in rows:
        lookup[evidence_id] = {
            "source_name": source_name,
            "source_url": source_url,
        }
    return lookup


def main() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    lookup = export_evidence_meta()
    out_path = EXPORT_DIR / "evidence_meta.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(lookup, f, ensure_ascii=False, indent=2)

    with_url = sum(1 for v in lookup.values() if v["source_url"])
    print(f"Exported {len(lookup)} evidence entries ({with_url} with URLs) → {out_path}")


if __name__ == "__main__":
    main()
