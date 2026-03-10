"""Sync speech context for the article analysis pipeline.

Detects MP names in article text using althingi.db, retrieves their
recent EU speech excerpts, and formats them as markdown context for
the assessment subagent.

Uses sync sqlite3 (not async aiosqlite) because the pipeline scripts
run synchronously.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_DEFAULT_DB = Path.home() / "althingi" / "althingi-mcp" / "data" / "althingi.db"

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


def _load_mp_names(conn: sqlite3.Connection) -> dict[str, str]:
    """Load all unique MP names from EU speeches.

    Returns {lowercase_name: original_name}.
    """
    issue_filter = " OR ".join(
        "s.issue_title LIKE ?" for _ in EU_ISSUE_PATTERNS
    )
    sql = f"""
        SELECT DISTINCT s.name
        FROM speeches s
        WHERE ({issue_filter})
    """
    rows = conn.execute(sql, EU_ISSUE_PATTERNS).fetchall()
    return {row["name"].lower(): row["name"] for row in rows}


def find_mp_names_in_text(text: str) -> list[str]:
    """Find names of known MPs that appear in the article text.

    Returns original-case names from althingi.db.
    Only matches full names (at least 2 words) to avoid false positives.
    """
    conn = _connect()
    if not conn:
        return []

    try:
        mp_names = _load_mp_names(conn)
        text_lower = text.lower()
        found = []
        for name_lower, name_original in mp_names.items():
            words = name_lower.split()
            if len(words) >= 2 and name_lower in text_lower:
                found.append(name_original)
        return found
    finally:
        conn.close()


def get_speech_excerpts(
    names: list[str],
    max_speeches_per_mp: int = 3,
    max_excerpt_len: int = 400,
) -> dict[str, list[dict]]:
    """Get recent EU speech excerpts for the given MP names.

    Returns {name: [{date, issue_title, excerpt, word_count}]}.
    """
    if not names:
        return {}

    conn = _connect()
    if not conn:
        return {}

    try:
        issue_filter = " OR ".join(
            "s.issue_title LIKE ?" for _ in EU_ISSUE_PATTERNS
        )

        results: dict[str, list[dict]] = {}
        for name in names:
            sql = f"""
                SELECT s.date, s.issue_title,
                       substr(t.full_text, 1, ?) AS excerpt,
                       t.word_count
                FROM speeches s
                LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
                WHERE s.name = ? AND ({issue_filter})
                ORDER BY s.date DESC
                LIMIT ?
            """
            params = (
                [max_excerpt_len + 100, name]
                + EU_ISSUE_PATTERNS
                + [max_speeches_per_mp]
            )
            rows = conn.execute(sql, params).fetchall()

            if rows:
                results[name] = []
                for row in rows:
                    excerpt = row["excerpt"] or ""
                    excerpt = excerpt.replace("\n", " ").strip()
                    if len(excerpt) > max_excerpt_len:
                        excerpt = excerpt[:max_excerpt_len].rsplit(" ", 1)[0] + "…"

                    results[name].append({
                        "date": row["date"],
                        "issue_title": row["issue_title"],
                        "excerpt": excerpt,
                        "word_count": row["word_count"] or 0,
                    })

        return results
    finally:
        conn.close()


def _format_speech_context(
    excerpts: dict[str, list[dict]],
    language: str = "is",
) -> str:
    """Format speech excerpts as markdown for the assessment subagent."""
    if not excerpts:
        return ""

    if language == "is":
        header = (
            "## Þingræður — bakgrunnsupplýsingar\n\n"
            "Eftirfarandi þingmenn sem nefndir eru í greininni hafa talað "
            "um ESB-mál á Alþingi. Hér eru nýlegar ræður þeirra til viðmiðunar — "
            "notaðu þær til að meta hvort fjölmiðlatilvitnun endurspegli afstöðu "
            "viðkomandi þingmanns réttilega.\n"
        )
    else:
        header = (
            "## Parliamentary Speeches — Background\n\n"
            "The following MPs mentioned in the article have spoken about EU matters "
            "in Alþingi. Here are their recent speeches for reference — use them to "
            "verify whether media quotes accurately reflect the MP's positions.\n"
        )

    sections = [header]

    for name, speeches in excerpts.items():
        sections.append(f"\n### {name}\n")
        for s in speeches:
            date = s["date"][:10] if s["date"] else "?"
            words = s["word_count"]
            title = s["issue_title"]
            excerpt = s["excerpt"]
            sections.append(
                f"**{date}** — _{title}_ ({words} orð):\n> {excerpt}\n"
            )

    return "\n".join(sections)


def build_speech_context(
    article_text: str,
    language: str = "is",
    max_speeches_per_mp: int = 3,
) -> str | None:
    """Build formatted speech context from an article.

    Detects MP names in the article, retrieves their recent EU speeches,
    and returns formatted markdown context. Returns None if no MPs found
    or althingi.db is unavailable.
    """
    names = find_mp_names_in_text(article_text)
    if not names:
        return None

    excerpts = get_speech_excerpts(names, max_speeches_per_mp=max_speeches_per_mp)
    if not excerpts:
        return None

    return _format_speech_context(excerpts, language=language)
