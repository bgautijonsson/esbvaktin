"""Tests for esbvaktin.speeches.search — party normalisation and EU-scoped FTS.

xrepo-08: ``search_eu_speeches``'s party filter expected ballot-letter
abbreviations (D/S/V) but the althingi.db ``party`` column stores full Icelandic
party names, so every party-filtered call returned empty; and the FTS path never
re-applied the EU issue filter, leaking all-topic speeches. These tests pin the
fixed behaviour.

The in-memory fixture mirrors the live althingi.db schema (v8): the FTS5 table is
``fts5(speech_id UNINDEXED, full_text, full_text_norm)`` and ``party`` holds full
Icelandic names. Connections are injected, so no DB file or env patching is needed.
"""

from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio

from esbvaktin.speeches import search

_SCHEMA = """
CREATE TABLE speeches (
    speech_id TEXT PRIMARY KEY, name TEXT, mp_id TEXT, date TEXT,
    started TEXT, ended TEXT, issue_nr TEXT, issue_title TEXT,
    speech_type TEXT, xml_url TEXT, session INTEGER
);
CREATE TABLE speech_texts (
    speech_id TEXT PRIMARY KEY, session INTEGER, mp_id TEXT, party TEXT,
    full_text TEXT NOT NULL, word_count INTEGER NOT NULL DEFAULT 0,
    full_text_norm TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE speech_fts USING fts5(
    speech_id UNINDEXED, full_text, full_text_norm, tokenize='unicode61'
);
CREATE TABLE members (
    id TEXT, name TEXT, birth_date TEXT, abbreviation TEXT, session INTEGER
);
CREATE TABLE member_sessions (
    mp_id TEXT, session INTEGER, party TEXT, constituency TEXT,
    seat_type TEXT, from_date TEXT, to_date TEXT
);
CREATE TABLE ministers (
    mp_id TEXT, name TEXT, title TEXT, party TEXT, session INTEGER
);
"""

# (speech_id, issue_title, party, full_text) — issue_title decides EU membership,
# party stored as the full Icelandic name, full_text feeds FTS.
_SPEECHES = [
    (
        "sp_d",
        "Aðild Íslands að Evrópusambandinu",
        "Sjálfstæðisflokkur",
        "Hér ræðum við sjávarútvegur og aðild að Evrópusambandinu.",
    ),
    ("sp_s", "Aðild Íslands að Evrópusambandinu", "Samfylkingin", "Ég styð aðild og upptöku evru."),
    ("sp_non", "Fjárlög 2026", "Sjálfstæðisflokkur", "Fjárlög ríkisins og sjávarútvegur."),
]


async def _make_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.executescript(_SCHEMA)

    for i, (sid, issue, party, text) in enumerate(_SPEECHES):
        await db.execute(
            "INSERT INTO speeches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                "Ræðumaður",
                f"mp{i}",
                "2026-03-09",
                "2026-03-09T10:00:00",
                None,
                str(100 + i),
                issue,
                "ræða",
                None,
                157,
            ),
        )
        await db.execute(
            "INSERT INTO speech_texts VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, 157, f"mp{i}", party, text, len(text.split()), text),
        )
        await db.execute("INSERT INTO speech_fts VALUES (?, ?, ?)", (sid, text, text))

    # MPs for the sibling lookups: one Sjálfstæðisflokkur (D), one Samfylkingin (S).
    await db.execute(
        "INSERT INTO members VALUES (?, ?, ?, ?, ?)",
        ("1", "Bjarni Benediktsson", "1970-01-01", "BjB", 157),
    )
    await db.execute(
        "INSERT INTO members VALUES (?, ?, ?, ?, ?)",
        ("2", "Kristrún Frostadóttir", "1988-01-01", "KrF", 157),
    )
    await db.execute(
        "INSERT INTO member_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("1", 157, "Sjálfstæðisflokkur", "Reykjavík", "kjördæmakjörinn", "2024-12-01", None),
    )
    await db.execute(
        "INSERT INTO member_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2", 157, "Samfylkingin", "Reykjavík", "kjördæmakjörinn", "2024-12-01", None),
    )
    await db.execute(
        "INSERT INTO ministers VALUES (?, ?, ?, ?, ?)",
        ("1", "Bjarni Benediktsson", "forsætisráðherra", "Sjálfstæðisflokkur", 157),
    )
    await db.commit()
    return db


@pytest_asyncio.fixture
async def eu_db():
    db = await _make_db()
    try:
        yield db
    finally:
        await db.close()


# ── normalise_party (party-abbreviation mapping) ─────────────────────


def test_normalise_party_maps_ballot_letter_to_full_name():
    from esbvaktin.speeches.constants import normalise_party

    # The exact full names stored in althingi.db's `party` column.
    assert normalise_party("D") == "Sjálfstæðisflokkur"
    assert normalise_party("S") == "Samfylkingin"
    assert normalise_party("V") == "Vinstrihreyfingin - grænt framboð"
    assert normalise_party("B") == "Framsóknarflokkur"


def test_normalise_party_is_case_insensitive_and_trims():
    from esbvaktin.speeches.constants import normalise_party

    assert normalise_party("d") == "Sjálfstæðisflokkur"
    assert normalise_party(" p ") == "Píratar"


def test_normalise_party_passes_through_full_names_and_unknowns():
    from esbvaktin.speeches.constants import normalise_party

    # An already-full name is returned unchanged (callers may pass either form).
    assert normalise_party("Samfylkingin") == "Samfylkingin"
    # An unknown token degrades to a literal no-match, not a crash.
    assert normalise_party("X") == "X"
    # Falsy input is returned unchanged.
    assert normalise_party("") == ""


# ── party filter accepts ballot letters (the core bug) ───────────────


@pytest.mark.asyncio
async def test_search_eu_speeches_party_filter_accepts_ballot_letter(eu_db):
    results = await search.search_eu_speeches(eu_db, party="D")
    ids = {r["speech_id"] for r in results}
    assert ids == {"sp_d"}
    assert results[0]["party"] == "Sjálfstæðisflokkur"


@pytest.mark.asyncio
async def test_lookup_mp_party_filter_accepts_ballot_letter(eu_db):
    results = await search.lookup_mp(eu_db, party="D")
    names = {r["name"] for r in results}
    assert names == {"Bjarni Benediktsson"}


@pytest.mark.asyncio
async def test_list_current_mps_party_filter_accepts_ballot_letter(eu_db):
    results = await search.list_current_mps(eu_db, session=157, party="D")
    names = {r["name"] for r in results}
    assert names == {"Bjarni Benediktsson"}


@pytest.mark.asyncio
async def test_list_ministers_party_filter_accepts_ballot_letter(eu_db):
    results = await search.list_ministers(eu_db, party="D")
    assert [r["title"] for r in results] == ["forsætisráðherra"]


# ── FTS path stays scoped to EU issues ───────────────────────────────


@pytest.mark.asyncio
async def test_fts_search_excludes_non_eu_issue_speeches(eu_db):
    # "sjávarútvegur" appears in both an EU-agenda speech (sp_d) and a Fjárlög
    # speech (sp_non); a search for EU speeches must not leak the latter.
    results = await search.search_eu_speeches(eu_db, query="sjávarútvegur")
    ids = {r["speech_id"] for r in results}
    assert ids == {"sp_d"}


@pytest.mark.asyncio
async def test_fts_search_respects_party_within_eu_scope(eu_db):
    results = await search.search_eu_speeches(eu_db, query="sjávarútvegur", party="D")
    ids = {r["speech_id"] for r in results}
    assert ids == {"sp_d"}
