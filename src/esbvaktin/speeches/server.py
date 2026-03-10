"""FastMCP server exposing EU-related Alþingi speech search tools.

Reads from althingi.db (read-only).  Configure DB path via ALTHINGI_DB_PATH
environment variable or rely on the default ~/althingi/althingi-mcp/data/althingi.db.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from esbvaktin.speeches import db as database
from esbvaktin.speeches import search

mcp = FastMCP("esbvaktin-speeches")


async def _get_db():
    return await database.get_db()


# ── Tools ─────────────────────────────────────────────────────────────


@mcp.tool()
async def search_eu_speeches(
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    speaker: str | None = None,
    party: str | None = None,
    issue_only: bool = False,
    limit: int = 30,
) -> str:
    """Search Alþingi speeches related to the EU and referendum.

    Two modes:
    - With ``query``: full-text search across speech content (FTS5),
      e.g. "sjávarútvegur" to find EU speeches mentioning fisheries.
    - Without ``query``: list EU-related speeches by date (filtered by
      issue title matching EU/referendum keywords).

    Args:
        query: Free-text search query (Icelandic). Omit for date-ordered browse.
        date_from: Start date filter (YYYY-MM-DD)
        date_to: End date filter (YYYY-MM-DD)
        speaker: Filter by speaker name (partial match, e.g. "Sigmundur")
        party: Filter by party abbreviation (e.g. "S", "D", "V")
        issue_only: If true, only match EU keywords in issue titles (faster)
        limit: Max results (default 30)
    """
    db = await _get_db()
    results = await search.search_eu_speeches(
        db, query=query, date_from=date_from, date_to=date_to,
        speaker=speaker, party=party, issue_only=issue_only, limit=limit,
    )

    if not results:
        return "No EU-related speeches found matching your criteria."

    lines = [f"## EU speeches — {len(results)} results\n"]
    for r in results:
        date = (r.get("date") or "?")[:10]
        party_tag = f" [{r['party']}]" if r.get("party") else ""
        wc = f" ({r['word_count']} words)" if r.get("word_count") else ""
        lines.append(f"### {r['speaker']}{party_tag} — {date}{wc}")
        lines.append(f"**Issue:** {r['issue_title']} (#{r['issue_nr']})")
        lines.append(f"**ID:** `{r['speech_id']}` | **Type:** {r.get('speech_type', '?')}")
        if r.get("excerpt"):
            lines.append(f"> {search._snippet(r['excerpt'], 250)}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def get_speech(speech_id: str) -> str:
    """Get the full text and metadata of a specific speech.

    Args:
        speech_id: The speech ID (e.g. "rad20260309T150257")
    """
    db = await _get_db()
    result = await search.get_speech(db, speech_id)

    if not result:
        return f"Speech `{speech_id}` not found."

    party_tag = f" [{result['party']}]" if result.get("party") else ""
    date = (result.get("date") or "?")[:10]
    wc = result.get("word_count") or "?"

    header = (
        f"# {result['speaker']}{party_tag} — {date}\n\n"
        f"**Issue:** {result['issue_title']} (#{result['issue_nr']})\n"
        f"**Type:** {result.get('speech_type', '?')} | "
        f"**Words:** {wc} | "
        f"**Session:** {result.get('session', '?')}\n"
        f"**Time:** {result.get('started', '?')} – {result.get('ended', '?')}\n"
        f"**ID:** `{speech_id}`\n\n---\n\n"
    )

    text = result.get("full_text") or "(Speech text not yet fetched from API)"
    return header + text


@mcp.tool()
async def list_eu_debates(
    date_from: str | None = None,
    date_to: str | None = None,
    session: int | None = None,
    limit: int = 50,
) -> str:
    """List EU/referendum debate topics with speech counts and date ranges.

    Useful for understanding what EU topics have been debated and when.
    Returns issue number, title, speech count, speaker count, word total,
    and date range.

    Args:
        date_from: Start date (YYYY-MM-DD)
        date_to: End date (YYYY-MM-DD)
        session: Legislative session number (e.g. 157)
        limit: Max results (default 50)
    """
    db = await _get_db()
    results = await search.list_eu_debates(
        db, date_from=date_from, date_to=date_to, session=session, limit=limit,
    )

    if not results:
        return "No EU-related debates found."

    lines = [
        f"## EU debates — {len(results)} topics\n",
        "| Issue | Title | Speeches | Speakers | Words | First | Last |",
        "|-------|-------|----------|----------|-------|-------|------|",
    ]
    for r in results:
        title = r["issue_title"][:60]
        first = (r.get("first_date") or "?")[:10]
        last = (r.get("last_date") or "?")[:10]
        lines.append(
            f"| {r['issue_nr']} | {title} | {r['speech_count']} | "
            f"{r['speaker_count']} | {r['total_words']:,} | {first} | {last} |"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_speaker_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    issue_nr: str | None = None,
    limit: int = 50,
) -> str:
    """Summarise which MPs spoke on EU topics: speech count, total words, party.

    Useful for identifying the most active voices in EU debates and mapping
    party participation.

    Args:
        date_from: Start date (YYYY-MM-DD)
        date_to: End date (YYYY-MM-DD)
        issue_nr: Restrict to a specific issue number
        limit: Max results (default 50)
    """
    db = await _get_db()
    results = await search.get_speaker_summary(
        db, date_from=date_from, date_to=date_to, issue_nr=issue_nr, limit=limit,
    )

    if not results:
        return "No speaker data found for EU topics."

    lines = [
        f"## EU debate speakers — {len(results)} MPs\n",
        "| MP | Party | Speeches | Words | Issues | First | Last |",
        "|-----|-------|----------|-------|--------|-------|------|",
    ]
    for r in results:
        party = r.get("party") or "?"
        first = (r.get("first_speech") or "?")[:10]
        last = (r.get("last_speech") or "?")[:10]
        lines.append(
            f"| {r['speaker']} | {party} | {r['speech_count']} | "
            f"{r['total_words']:,} | {r['issues_spoken_on']} | {first} | {last} |"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_debate_timeline(
    issue_nr: str,
    date: str | None = None,
    limit: int = 100,
) -> str:
    """Get the chronological flow of speeches within a specific debate.

    Shows who spoke in what order, with excerpts — useful for understanding
    the back-and-forth dynamics of a parliamentary debate.

    Args:
        issue_nr: The issue/bill number (e.g. "320", "626")
        date: Restrict to a specific date (YYYY-MM-DD) if the issue spans days
        limit: Max speeches (default 100)
    """
    db = await _get_db()
    results = await search.get_debate_timeline(
        db, issue_nr=issue_nr, date=date, limit=limit,
    )

    if not results:
        return f"No speeches found for issue #{issue_nr}."

    # Determine issue title from first result
    title = results[0].get("issue_title", f"Issue #{issue_nr}")
    date_range = date or f"{results[0].get('date', '?')[:10]}–{results[-1].get('date', '?')[:10]}"

    lines = [f"## {title}\n**Date:** {date_range} | **Speeches:** {len(results)}\n"]

    for i, r in enumerate(results, 1):
        party_tag = f" [{r['party']}]" if r.get("party") else ""
        time = (r.get("started") or "?")[11:16]  # HH:MM
        wc = f" ({r['word_count']} w)" if r.get("word_count") else ""
        lines.append(f"**{i}. {r['speaker']}{party_tag}** — {time}{wc}")
        if r.get("excerpt"):
            lines.append(f"> {search._snippet(r['excerpt'], 200)}")
        lines.append("")
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────


def run_server() -> None:
    """Entry point for running the MCP server."""
    mcp.run()


if __name__ == "__main__":
    run_server()
