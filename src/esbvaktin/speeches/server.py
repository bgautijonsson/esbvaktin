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


@mcp.tool()
async def lookup_mp(
    name: str | None = None,
    party: str | None = None,
    session: int | None = None,
    limit: int = 30,
) -> str:
    """Find MPs by name or party with their session history.

    Returns matching MPs with party, constituency, and seat type per session.
    Use this to find an MP's ID for get_mp_detail, or to browse MPs by party.

    Args:
        name: Partial name match (e.g. "Kristrún", "Bjarni")
        party: Party abbreviation (e.g. "S" for Samfylkingin, "D" for Sjálfstæðisflokkur)
        session: Legislative session number (e.g. 157 for current)
        limit: Max results (default 30)
    """
    db = await _get_db()
    results = await search.lookup_mp(db, name=name, party=party, session=session, limit=limit)

    if not results:
        return "No MPs found matching your criteria."

    # Group by MP to show consolidated view
    from collections import OrderedDict
    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for r in results:
        key = r["mp_id"]
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(r)

    lines = [f"## MPs found — {len(grouped)} matches\n"]
    for mp_id, entries in grouped.items():
        first = entries[0]
        birth = f" (b. {first['birth_date'][:4]})" if first.get("birth_date") else ""
        lines.append(f"### {first['name']}{birth}")
        lines.append(f"**ID:** `{mp_id}`\n")
        for e in entries:
            seat = e.get("seat_type") or "?"
            party_str = e.get("party") or "?"
            const = e.get("constituency") or "?"
            lines.append(f"- Session {e['session']}: {party_str} — {const} ({seat})")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def get_mp_detail(mp_id: str) -> str:
    """Get full profile of an MP: identity, all sessions served, minister roles.

    Use lookup_mp first to find the MP's ID.

    Args:
        mp_id: The MP's numeric ID (e.g. "1417")
    """
    db = await _get_db()
    result = await search.get_mp_detail(db, mp_id)

    if not result:
        return f"MP with ID `{mp_id}` not found."

    birth = f" (b. {result['birth_date']})" if result.get("birth_date") else ""
    lines = [
        f"# {result['name']}{birth}",
        f"**ID:** `{result['mp_id']}` | **Abbreviation:** {result.get('abbreviation', '?')}\n",
    ]

    # Session history
    sessions = result.get("sessions", [])
    if sessions:
        lines.append(f"## Parliamentary service — {len(sessions)} entries\n")
        lines.append("| Session | Party | Constituency | Seat | From | To |")
        lines.append("|---------|-------|-------------|------|------|-----|")
        for s in sessions:
            from_d = (s.get("from_date") or "—")[:10]
            to_d = (s.get("to_date") or "—")[:10]
            lines.append(
                f"| {s['session']} | {s.get('party', '?')} | "
                f"{s.get('constituency', '?')} | {s.get('seat_type', '?')} | "
                f"{from_d} | {to_d} |"
            )
        lines.append("")

    # Minister roles
    roles = result.get("minister_roles", [])
    if roles:
        lines.append(f"## Minister roles — {len(roles)} entries\n")
        for r in roles:
            lines.append(f"- **{r['title']}** (session {r['session']}, {r.get('party', '?')})")
        lines.append("")
    else:
        lines.append("## Minister roles\nNone on record.\n")

    return "\n".join(lines)


@mcp.tool()
async def list_ministers(
    session: int | None = None,
    party: str | None = None,
) -> str:
    """List cabinet ministers, optionally filtered by session or party.

    Defaults to showing all ministers across sessions. Use session=157 for
    the current cabinet.

    Args:
        session: Legislative session (e.g. 157)
        party: Party abbreviation filter
    """
    db = await _get_db()
    results = await search.list_ministers(db, session=session, party=party)

    if not results:
        return "No ministers found."

    # Group by session
    by_session: dict[int, list[dict]] = {}
    for r in results:
        by_session.setdefault(r["session"], []).append(r)

    lines = [f"## Ministers — {len(results)} entries\n"]
    for sess in sorted(by_session, reverse=True):
        entries = by_session[sess]
        lines.append(f"### Session {sess}\n")
        lines.append("| Name | Title | Party |")
        lines.append("|------|-------|-------|")
        for r in entries:
            lines.append(f"| {r['name']} | {r['title']} | {r.get('party', '?')} |")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def list_current_mps(
    session: int = 157,
    party: str | None = None,
) -> str:
    """List all MPs in a legislative session with party and constituency.

    Args:
        session: Legislative session (default 157 = current)
        party: Filter by party abbreviation
    """
    db = await _get_db()
    results = await search.list_current_mps(db, session=session, party=party)

    if not results:
        return f"No MPs found for session {session}."

    lines = [
        f"## MPs in session {session} — {len(results)} entries\n",
        "| Name | Party | Constituency | Seat | Born |",
        "|------|-------|-------------|------|------|",
    ]
    for r in results:
        birth = (r.get("birth_date") or "?")[:4]
        lines.append(
            f"| {r['name']} | {r.get('party', '?')} | "
            f"{r.get('constituency', '?')} | {r.get('seat_type', '?')} | {birth} |"
        )
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────


def run_server() -> None:
    """Entry point for running the MCP server."""
    mcp.run()


if __name__ == "__main__":
    run_server()
