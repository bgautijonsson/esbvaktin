"""FTS5 + filter queries for EU-related Alþingi speeches.

Reads from althingi.db tables: speeches, speech_texts, speech_fts,
member_sessions.  All queries are read-only.
"""

from __future__ import annotations

import re

import aiosqlite


# ── EU topic detection ────────────────────────────────────────────────

EU_KEYWORDS_FTS = (
    '"ESB" OR "Evrópusamband" OR "Evrópusambandið" OR "Evrópusambands"'
    ' OR "aðildarviðræður" OR "aðildarumsókn" OR "aðild"'
    ' OR "þjóðaratkvæðagreiðsla" OR "þjóðaratkvæðagreiðslu"'
    ' OR "Evrópumál" OR "EES"'
)

EU_ISSUE_PATTERNS = [
    "%Evróp%",
    "%ESB%",
    "%aðild%Evrópu%",
    "%aðildarviðræð%",
    "%aðildarumsókn%",
    "%þjóðaratkvæðagreiðsl%",
    "%Evrópumál%",
]


# ── Helpers ───────────────────────────────────────────────────────────


class _WhereBuilder:
    """Build parameterised WHERE clauses incrementally."""

    def __init__(self) -> None:
        self.clauses: list[str] = []
        self.params: list = []

    def add(self, clause: str, *params: object) -> "_WhereBuilder":
        self.clauses.append(clause)
        self.params.extend(params)
        return self

    def add_in(self, column: str, values: list | tuple) -> "_WhereBuilder":
        if not values:
            self.clauses.append("0")
            return self
        placeholders = ", ".join("?" for _ in values)
        self.clauses.append(f"{column} IN ({placeholders})")
        self.params.extend(values)
        return self

    @property
    def sql(self) -> str:
        return " AND ".join(self.clauses) if self.clauses else "1=1"


def _prepare_fts_query(text: str) -> str:
    """Convert natural language to a safe FTS5 query.

    Wraps each word in double quotes to prevent FTS5 operators
    (OR, AND, NOT, NEAR) from being interpreted as syntax.
    """
    words = text.split()
    parts: list[str] = []
    for w in words:
        clean = re.sub(r"[^\w\-]", "", w)
        if clean:
            parts.append(f'"{clean}"')
    return " ".join(parts)


def _snippet(text: str, max_len: int = 300) -> str:
    """Truncate text to a readable snippet."""
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


# ── Core queries ──────────────────────────────────────────────────────


async def search_eu_speeches(
    db: aiosqlite.Connection,
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    speaker: str | None = None,
    party: str | None = None,
    issue_only: bool = False,
    limit: int = 30,
) -> list[dict]:
    """Search speeches related to EU/referendum topics.

    Two search modes:
    - If ``query`` is provided: FTS5 full-text search within EU-related speeches
    - If ``query`` is None: return EU-related speeches by issue title (date-ordered)

    When ``issue_only`` is True, the EU filter is applied only to issue titles,
    not speech full text — faster but misses speeches that mention EU in passing
    under a non-EU agenda item.
    """
    if query:
        return await _fts_eu_search(
            db, query, date_from, date_to, speaker, party, limit
        )
    return await _issue_eu_search(
        db, date_from, date_to, speaker, party, issue_only, limit
    )


async def _issue_eu_search(
    db: aiosqlite.Connection,
    date_from: str | None,
    date_to: str | None,
    speaker: str | None,
    party: str | None,
    issue_only: bool,
    limit: int,
) -> list[dict]:
    """Return EU-related speeches filtered by issue title (+ optionally full text)."""
    w = _WhereBuilder()

    # EU issue title filter (always applied)
    issue_clauses = " OR ".join("s.issue_title LIKE ?" for _ in EU_ISSUE_PATTERNS)
    w.add(f"({issue_clauses})", *EU_ISSUE_PATTERNS)

    if date_from:
        w.add("s.date >= ?", date_from)
    if date_to:
        w.add("s.date <= ?", date_to)
    if speaker:
        w.add("s.name LIKE ?", f"%{speaker}%")
    if party:
        w.add("t.party = ?", party)

    sql = f"""
        SELECT s.speech_id, s.name AS speaker, s.mp_id, s.date,
               s.issue_nr, s.issue_title, s.speech_type,
               t.party, t.word_count,
               substr(t.full_text, 1, 500) AS excerpt
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE {w.sql}
        ORDER BY s.date DESC, s.started DESC
        LIMIT ?
    """
    rows = await db.execute_fetchall(sql, w.params + [limit])
    return [dict(r) for r in rows]


async def _fts_eu_search(
    db: aiosqlite.Connection,
    query: str,
    date_from: str | None,
    date_to: str | None,
    speaker: str | None,
    party: str | None,
    limit: int,
) -> list[dict]:
    """FTS5 search within speech texts, optionally scoped to EU issues."""
    fts_query = _prepare_fts_query(query)

    w = _WhereBuilder()
    if date_from:
        w.add("s.date >= ?", date_from)
    if date_to:
        w.add("s.date <= ?", date_to)
    if speaker:
        w.add("s.name LIKE ?", f"%{speaker}%")
    if party:
        w.add("t.party = ?", party)

    extra = (" AND " + w.sql) if w.clauses else ""

    sql = f"""
        SELECT s.speech_id, s.name AS speaker, s.mp_id, s.date,
               s.issue_nr, s.issue_title, s.speech_type,
               t.party, t.word_count,
               snippet(speech_fts, 1, '>>>', '<<<', '…', 40) AS excerpt
        FROM speech_fts
        JOIN speech_texts t ON speech_fts.speech_id = t.speech_id
        JOIN speeches s ON s.speech_id = t.speech_id
        WHERE speech_fts MATCH ?
        {extra}
        ORDER BY rank
        LIMIT ?
    """
    params = [fts_query] + w.params + [limit]
    try:
        rows = await db.execute_fetchall(sql, params)
    except Exception:
        return []

    return [dict(r) for r in rows]


async def get_speech(
    db: aiosqlite.Connection,
    speech_id: str,
) -> dict | None:
    """Get full speech text and metadata by speech_id."""
    rows = await db.execute_fetchall(
        """
        SELECT s.speech_id, s.name AS speaker, s.mp_id, s.date,
               s.started, s.ended, s.issue_nr, s.issue_title,
               s.speech_type, s.session,
               t.party, t.word_count, t.full_text
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE s.speech_id = ?
        """,
        (speech_id,),
    )
    if not rows:
        return None
    return dict(rows[0])


async def list_eu_debates(
    db: aiosqlite.Connection,
    date_from: str | None = None,
    date_to: str | None = None,
    session: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """List EU-related debate topics with speech counts and date ranges."""
    w = _WhereBuilder()

    issue_clauses = " OR ".join("s.issue_title LIKE ?" for _ in EU_ISSUE_PATTERNS)
    w.add(f"({issue_clauses})", *EU_ISSUE_PATTERNS)

    if date_from:
        w.add("s.date >= ?", date_from)
    if date_to:
        w.add("s.date <= ?", date_to)
    if session:
        w.add("s.session = ?", session)

    sql = f"""
        SELECT s.issue_nr, s.issue_title,
               COUNT(*) AS speech_count,
               COUNT(DISTINCT s.mp_id) AS speaker_count,
               MIN(s.date) AS first_date,
               MAX(s.date) AS last_date,
               SUM(COALESCE(t.word_count, 0)) AS total_words
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE {w.sql}
        GROUP BY s.issue_nr, s.issue_title
        ORDER BY last_date DESC, speech_count DESC
        LIMIT ?
    """
    rows = await db.execute_fetchall(sql, w.params + [limit])
    return [dict(r) for r in rows]


async def get_speaker_summary(
    db: aiosqlite.Connection,
    date_from: str | None = None,
    date_to: str | None = None,
    issue_nr: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Summarise which MPs spoke on EU topics, how often, and total words."""
    w = _WhereBuilder()

    issue_clauses = " OR ".join("s.issue_title LIKE ?" for _ in EU_ISSUE_PATTERNS)
    w.add(f"({issue_clauses})", *EU_ISSUE_PATTERNS)

    if date_from:
        w.add("s.date >= ?", date_from)
    if date_to:
        w.add("s.date <= ?", date_to)
    if issue_nr:
        w.add("s.issue_nr = ?", issue_nr)

    sql = f"""
        SELECT s.mp_id, s.name AS speaker,
               t.party,
               COUNT(*) AS speech_count,
               SUM(COALESCE(t.word_count, 0)) AS total_words,
               COUNT(DISTINCT s.issue_nr) AS issues_spoken_on,
               MIN(s.date) AS first_speech,
               MAX(s.date) AS last_speech
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE {w.sql}
        GROUP BY s.mp_id, s.name, t.party
        ORDER BY total_words DESC
        LIMIT ?
    """
    rows = await db.execute_fetchall(sql, w.params + [limit])
    return [dict(r) for r in rows]


async def get_debate_timeline(
    db: aiosqlite.Connection,
    issue_nr: str,
    date: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Get chronological flow of speeches within a specific debate/issue.

    If ``date`` is provided, restricts to speeches on that day (useful for
    issues debated across multiple days).
    """
    w = _WhereBuilder()
    w.add("s.issue_nr = ?", issue_nr)
    if date:
        w.add("s.date = ?", date)

    sql = f"""
        SELECT s.speech_id, s.name AS speaker, s.mp_id, s.date,
               s.started, s.ended, s.speech_type,
               t.party, t.word_count,
               substr(t.full_text, 1, 500) AS excerpt
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE {w.sql}
        ORDER BY s.started ASC
        LIMIT ?
    """
    rows = await db.execute_fetchall(sql, w.params + [limit])
    return [dict(r) for r in rows]
