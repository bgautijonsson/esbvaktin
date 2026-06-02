"""Semantic retrieval of EU-related Alþingi speeches from althingi.db speech_vec.

Reuses althingi's already-built bge-m3 vectors (read-only, zero new corpus
compute — xrepo-04B) to find the speeches most relevant to a set of claim
vectors. speech_vec is NOT EU-scoped (it holds all embedded speeches), so an EU
issue-title filter is applied after the KNN. Vectors are fp16 upstream, so we
reason in cosine-equivalence (ranking), never bit-identical distances.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from .constants import EU_ISSUE_PATTERNS

_DEFAULT_DB = Path.home() / "althingi" / "althingi-mcp" / "data" / "althingi.db"
_log = logging.getLogger(__name__)


def _db_path(db_path: Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return Path(os.environ.get("ALTHINGI_DB_PATH", str(_DEFAULT_DB)))


def _normalise(vec: Sequence[float]) -> list[float]:
    """Unit-normalise a vector (no-op on the zero vector)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return list(vec)
    return [x / norm for x in vec]


def connect_with_vec(db_path: Path | None = None) -> sqlite3.Connection | None:
    """Open althingi.db read-only with the sqlite-vec extension loaded.

    Returns None (logged once) if the DB is missing or the extension can't load,
    so callers degrade gracefully rather than crash.
    """
    path = _db_path(db_path)
    if not path.exists():
        _log.warning("althingi.db not found at %s — skipping semantic speech retrieval", path)
        return None
    try:
        import sqlite_vec
    except ImportError:
        _log.warning("sqlite-vec not installed — skipping semantic speech retrieval")
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn
    except Exception as e:  # pragma: no cover - defensive
        _log.warning("could not open althingi.db with sqlite-vec: %s", e)
        return None


def search_speeches_by_vectors(
    query_vectors: Sequence[Sequence[float]],
    *,
    k_per_query: int = 40,
    max_speeches: int = 6,
    eu_only: bool = True,
    db_path: Path | None = None,
) -> list[dict]:
    """Return the EU speeches most relevant to the given query vectors.

    For each query vector, run a sqlite-vec KNN over speech_vec, join chunks to
    speeches, apply the EU issue-title filter, and keep each speech's nearest
    chunk as its excerpt. Returns up to ``max_speeches`` dicts ranked by
    distance: ``{speech_id, name, date, issue_title, excerpt, distance}``.
    """
    if not query_vectors:
        return []
    conn = connect_with_vec(db_path)
    if conn is None:
        return []
    try:
        import sqlite_vec

        eu_clause = (
            " OR ".join("s.issue_title LIKE ?" for _ in EU_ISSUE_PATTERNS) if eu_only else "1=1"
        )
        eu_params = list(EU_ISSUE_PATTERNS) if eu_only else []
        sql = f"""
            WITH knn AS (
                SELECT chunk_id, distance FROM speech_vec
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT sc.speech_id, s.name, s.date, s.issue_title,
                   sc.chunk_text, knn.distance
            FROM knn
            JOIN speech_chunks sc ON sc.chunk_id = knn.chunk_id
            JOIN speeches s ON s.speech_id = sc.speech_id
            WHERE {eu_clause}
            ORDER BY knn.distance
        """

        # Dedupe to distinct speeches across all chunks and all query vectors,
        # keeping each speech's nearest chunk as its excerpt.
        best: dict[str, dict] = {}
        for vec in query_vectors:
            q = sqlite_vec.serialize_float32(_normalise(vec))
            for r in conn.execute(sql, [q, k_per_query, *eu_params]).fetchall():
                sid = r["speech_id"]
                if sid not in best or r["distance"] < best[sid]["distance"]:
                    best[sid] = {
                        "speech_id": sid,
                        "name": r["name"],
                        "date": r["date"],
                        "issue_title": r["issue_title"],
                        "excerpt": r["chunk_text"],
                        "distance": r["distance"],
                    }

        return sorted(best.values(), key=lambda d: d["distance"])[:max_speeches]
    finally:
        conn.close()
