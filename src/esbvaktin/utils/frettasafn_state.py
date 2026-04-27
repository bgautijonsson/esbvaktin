"""ESBvaktin's bridge to frettasafn's consumer_state table.

Synchronous sqlite3 access to the frettasafn DB so esbvaktin scripts
(register_article_sightings, manage_inbox.reject, check_duplicate) can
record state without going through the MCP layer. ESBvaktin is the only
known consumer for now; consumer_id defaults to "esbvaktin".

Usage:
    from esbvaktin.utils.frettasafn_state import mark_urls, is_known_url

    mark_urls(["https://..."], state="processed",
              metadata_per_url={"https://...": {"report_slug": "..."}})

    record = is_known_url("https://...")
    if record and record["state"] in ("processed", "rejected"):
        ...

Configuration:
    FRETTASAFN_DB env var overrides the default path
    (~/frettasafn/data/frettasafn.db).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

CONSUMER_ID = "esbvaktin"
DEFAULT_DB = Path.home() / "frettasafn" / "data" / "frettasafn.db"
VALID_STATES = ("processed", "rejected", "skipped", "in_progress")
CHUNK_SIZE = 500  # SQLite default parameter limit is 999


def _db_path() -> Path:
    return Path(os.environ.get("FRETTASAFN_DB", str(DEFAULT_DB)))


def _connect() -> sqlite3.Connection:
    """Open a connection to the frettasafn DB. Caller must close()."""
    path = _db_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Frettasafn DB not found at {path}. Set FRETTASAFN_DB env var if it lives elsewhere."
        )
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def lookup_article_ids_by_url(urls: list[str]) -> dict[str, list[str]]:
    """Return url -> list[article_id] for URLs that exist in frettasafn.articles.

    Two-pass lookup mirrors the seed-script logic:
      1. Exact match (covers most cases)
      2. Prefix match for unmatched URLs (catches ?utm_medium=rss suffixes)
    """
    if not urls:
        return {}

    seen: dict[str, list[str]] = {}
    deduped = list(set(urls))

    with _connect() as conn:
        for i in range(0, len(deduped), CHUNK_SIZE):
            chunk = deduped[i : i + CHUNK_SIZE]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT article_id, url FROM articles WHERE url IN ({placeholders})",
                chunk,
            ).fetchall()
            for r in rows:
                seen.setdefault(r["url"], []).append(r["article_id"])

        missing = [u for u in deduped if u not in seen]
        for missing_url in missing:
            stem = missing_url.split("?")[0]
            rows = conn.execute(
                "SELECT article_id FROM articles WHERE url LIKE ?",
                (stem + "%",),
            ).fetchall()
            if rows:
                seen[missing_url] = [r["article_id"] for r in rows]

    return seen


def mark_articles(
    article_ids: list[str],
    state: str,
    metadata: dict | None = None,
    consumer_id: str = CONSUMER_ID,
) -> int:
    """Upsert state for each article_id. Returns count of rows written."""
    if state not in VALID_STATES:
        raise ValueError(f"state must be one of {VALID_STATES}")
    if not article_ids:
        return 0

    now = datetime.now(UTC).isoformat()
    metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    rows = [(consumer_id, aid, state, now, metadata_json) for aid in article_ids]

    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO consumer_state (consumer_id, article_id, state, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (consumer_id, article_id) DO UPDATE SET
                state = excluded.state,
                updated_at = excluded.updated_at,
                metadata = excluded.metadata
            """,
            rows,
        )
        conn.commit()

    return len(rows)


def mark_urls(
    urls: list[str],
    state: str,
    metadata_per_url: dict[str, dict] | None = None,
    consumer_id: str = CONSUMER_ID,
) -> tuple[int, list[str]]:
    """Upsert state for each URL after looking up its article_id(s).

    URLs that map to multiple article_ids (multi-source duplicates, e.g.
    heimildin articles also stored under stundin) get all their article_ids
    marked.

    Returns (rows_written, unmatched_urls). Unmatched URLs are not in
    frettasafn.articles — typical for panel-show transcripts ingested only
    into esbvaktin's own DB.
    """
    if state not in VALID_STATES:
        raise ValueError(f"state must be one of {VALID_STATES}")
    if not urls:
        return 0, []

    url_to_ids = lookup_article_ids_by_url(urls)
    unmatched = [u for u in urls if u not in url_to_ids]

    now = datetime.now(UTC).isoformat()
    rows: list[tuple] = []
    for url, aids in url_to_ids.items():
        meta = (metadata_per_url or {}).get(url)
        meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
        for aid in aids:
            rows.append((consumer_id, aid, state, now, meta_json))

    if not rows:
        return 0, unmatched

    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO consumer_state (consumer_id, article_id, state, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (consumer_id, article_id) DO UPDATE SET
                state = excluded.state,
                updated_at = excluded.updated_at,
                metadata = excluded.metadata
            """,
            rows,
        )
        conn.commit()

    return len(rows), unmatched


def is_known_url(url: str, consumer_id: str = CONSUMER_ID) -> dict | None:
    """Return the latest consumer_state record for this URL, or None.

    Returns None if:
      - URL doesn't exist in frettasafn.articles, OR
      - URL exists in articles but has no consumer_state record
    """
    url_to_ids = lookup_article_ids_by_url([url])
    if url not in url_to_ids:
        return None

    aids = url_to_ids[url]
    placeholders = ",".join("?" * len(aids))

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT article_id, state, updated_at, metadata
            FROM consumer_state
            WHERE consumer_id = ? AND article_id IN ({placeholders})
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            [consumer_id] + aids,
        ).fetchall()

    if not rows:
        return None

    r = rows[0]
    return {
        "article_id": r["article_id"],
        "state": r["state"],
        "updated_at": r["updated_at"],
        "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
    }


def consumer_summary(consumer_id: str = CONSUMER_ID) -> dict[str, int]:
    """Per-state counts for a consumer."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT state, COUNT(*) AS cnt
            FROM consumer_state
            WHERE consumer_id = ?
            GROUP BY state
            """,
            (consumer_id,),
        ).fetchall()
    return {r["state"]: r["cnt"] for r in rows}
