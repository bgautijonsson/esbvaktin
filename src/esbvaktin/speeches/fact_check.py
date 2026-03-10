"""Speech fact-checking: selection, loading, and work dir setup.

Loads full speech text + metadata from althingi.db (sync sqlite3,
read-only), ranks speeches by evidence value for batch processing,
and prepares work directories for subagent execution.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from textwrap import shorten

_DEFAULT_DB = Path.home() / "althingi" / "althingi-mcp" / "data" / "althingi.db"

# Reuse constants from curate_speech_evidence for scoring
HIGH_VALUE_TYPES = ["flutningsræða", "ráðherraræða"]
MEDIUM_VALUE_TYPES = ["ræða", "svar"]

KEY_FIGURES = {
    "Þorgerður Katrín Gunnarsdóttir",
    "Kristrún Frostadóttir",
    "Sigmundur Davíð Gunnlaugsson",
    "Guðrún Hafsteinsdóttir",
    "Bjarni Benediktsson",
    "Guðlaugur Þór Þórðarson",
    "Logi Einarsson",
    "Diljá Mist Einarsdóttir",
}

EU_ISSUE_PATTERNS = [
    "%Evróp%", "%ESB%", "%aðild%Evrópu%", "%aðildarviðræð%",
    "%aðildarumsókn%", "%þjóðaratkvæðagreiðsl%", "%Evrópumál%",
]


def _db_path() -> Path:
    return Path(os.environ.get("ALTHINGI_DB_PATH", str(_DEFAULT_DB)))


def _connect() -> sqlite3.Connection | None:
    path = _db_path()
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _issue_filter_sql() -> tuple[str, list[str]]:
    clause = " OR ".join(f"s.issue_title LIKE ?" for _ in EU_ISSUE_PATTERNS)
    return clause, list(EU_ISSUE_PATTERNS)


def _score_speech(row: sqlite3.Row) -> float:
    """Score a speech by evidence value (higher = more valuable).

    Same scoring logic as curate_speech_evidence.py.
    """
    score = 0.0

    if row["speech_type"] in HIGH_VALUE_TYPES:
        score += 3.0
    elif row["speech_type"] in MEDIUM_VALUE_TYPES:
        score += 1.0

    if row["name"] in KEY_FIGURES:
        score += 2.0

    wc = row["word_count"] or 0
    if wc > 1500:
        score += 2.0
    elif wc > 800:
        score += 1.0
    elif wc < 300:
        score -= 1.0

    speech_date = row["date"][:10] if row["date"] else "2000-01-01"
    year = int(speech_date[:4])
    if year >= 2026:
        score += 2.0
    elif year >= 2024:
        score += 1.0

    return score


def get_speech_for_fact_check(speech_id: str) -> dict | None:
    """Load full speech text + metadata from althingi.db.

    Returns dict with keys: speech_id, name, party, date, session,
    issue_title, speech_type, word_count, full_text.
    Returns None if speech not found or DB unavailable.
    """
    conn = _connect()
    if not conn:
        return None

    try:
        row = conn.execute(
            """
            SELECT s.speech_id, s.name, t.party, s.date, s.session,
                   s.issue_title, s.speech_type, t.word_count, t.full_text
            FROM speeches s
            LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
            WHERE s.speech_id = ?
            """,
            (speech_id,),
        ).fetchone()

        if not row:
            return None

        return {
            "speech_id": row["speech_id"],
            "name": row["name"],
            "party": row["party"] or "?",
            "date": row["date"][:10] if row["date"] else "?",
            "session": str(row["session"]) if row["session"] else "?",
            "issue_title": row["issue_title"] or "?",
            "speech_type": row["speech_type"] or "ræða",
            "word_count": row["word_count"] or 0,
            "full_text": row["full_text"] or "",
        }
    finally:
        conn.close()


def select_speeches_for_batch(
    limit: int = 10,
    min_words: int = 300,
    exclude_checked: bool = True,
    checked_speech_ids: set[str] | None = None,
) -> list[dict]:
    """Rank EU speeches by value, excluding already-checked ones.

    Args:
        limit: Maximum number of speeches to return.
        min_words: Minimum word count threshold.
        exclude_checked: Whether to filter out already-checked speech_ids.
        checked_speech_ids: Pre-loaded set of checked IDs. If None and
            exclude_checked is True, will be loaded from PostgreSQL.

    Returns list of dicts with speech metadata + score, sorted by score descending.
    """
    conn = _connect()
    if not conn:
        return []

    if exclude_checked and checked_speech_ids is None:
        checked_speech_ids = _load_checked_speech_ids()

    try:
        issue_clause, params = _issue_filter_sql()

        sql = f"""
            SELECT s.speech_id, s.name, s.date, s.issue_title,
                   s.speech_type, t.word_count, t.party
            FROM speeches s
            LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
            WHERE ({issue_clause})
              AND t.word_count >= ?
            ORDER BY s.date DESC
        """
        rows = conn.execute(sql, params + [min_words]).fetchall()

        candidates = []
        for row in rows:
            sid = row["speech_id"]
            if exclude_checked and checked_speech_ids and sid in checked_speech_ids:
                continue

            score = _score_speech(row)
            candidates.append({
                "speech_id": sid,
                "name": row["name"],
                "date": row["date"][:10] if row["date"] else "?",
                "issue_title": row["issue_title"],
                "speech_type": row["speech_type"],
                "word_count": row["word_count"] or 0,
                "party": row["party"] or "?",
                "score": score,
            })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:limit]
    finally:
        conn.close()


def _load_checked_speech_ids() -> set[str]:
    """Query PostgreSQL for speech_ids already in claim_sightings."""
    try:
        from esbvaktin.ground_truth.operations import get_connection
        pg_conn = get_connection()
        rows = pg_conn.execute(
            "SELECT DISTINCT speech_id FROM claim_sightings "
            "WHERE source_type = 'althingi' AND speech_id IS NOT NULL"
        ).fetchall()
        pg_conn.close()
        return {row[0] for row in rows}
    except Exception:
        return set()


def _session_for_date(date_str: str) -> str:
    """Determine löggjafarþing session number from date."""
    if date_str >= "2025-09":
        return "157"
    elif date_str >= "2024-09":
        return "156"
    elif date_str >= "2023-09":
        return "155"
    elif date_str >= "2022-09":
        return "154"
    else:
        return "153"


def prepare_speech_work_dir(speech_id: str) -> Path | None:
    """Create work directory and write _speech.md for a speech.

    Work dirs go in data/speech_checks/{speech_id}/.
    Returns the work dir path, or None if speech not found.
    """
    speech = get_speech_for_fact_check(speech_id)
    if not speech:
        return None

    work_dir = Path("data/speech_checks") / speech_id
    work_dir.mkdir(parents=True, exist_ok=True)

    session = speech["session"]
    if session == "?":
        session = _session_for_date(speech["date"])

    source_url = (
        f"https://www.althingi.is/altext/raeda/{session}/{speech_id}.html"
    )

    # Write _speech.md with metadata header + full text
    lines = [
        f"# {speech['name']} — {speech['speech_type']}",
        "",
        f"- **Ræðumaður**: {speech['name']}, {speech['party']}",
        f"- **Tegund ræðu**: {speech['speech_type']}",
        f"- **Þingfundarheiti**: {speech['issue_title']}",
        f"- **Dagsetning**: {speech['date']}, {session}. löggjafarþing",
        f"- **Orðafjöldi**: {speech['word_count']}",
        f"- **Heimild**: {source_url}",
        "",
        "---",
        "",
        speech["full_text"],
    ]

    (work_dir / "_speech.md").write_text("\n".join(lines), encoding="utf-8")
    return work_dir
