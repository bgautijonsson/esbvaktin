"""Tests for semantic Alþingi speech retrieval from althingi.db speech_vec (xrepo-04B).

Builds a tiny in-test althingi.db with the sqlite-vec extension so the real
2.3 GB database is never touched. Vectors are crafted unit vectors so L2/cosine
ranking is deterministic — we assert ranking and the EU-scope filter, never
bit-identical distances (the real corpus is fp16; reason in cosine-equivalence).
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest
import sqlite_vec

DIM = 1024

_SCHEMA = """
    CREATE TABLE schema_version (version INTEGER);
    INSERT INTO schema_version (version) VALUES (8);
    CREATE TABLE speeches (
        speech_id TEXT, name TEXT, mp_id TEXT, date TEXT,
        issue_nr TEXT, issue_title TEXT, speech_type TEXT, session INTEGER
    );
    CREATE TABLE speech_chunks (
        chunk_id TEXT PRIMARY KEY, speech_id TEXT, chunk_idx INTEGER,
        chunk_text TEXT, token_count INTEGER
    );
    CREATE VIRTUAL TABLE speech_vec USING vec0(
        chunk_id TEXT PRIMARY KEY, embedding float[1024]
    );
"""


def _unit(nonzero: dict[int, float]) -> list[float]:
    """Build a normalised 1024-dim vector from {index: weight}."""
    v = [0.0] * DIM
    for i, w in nonzero.items():
        v[i] = w
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _insert_speech(
    conn: sqlite3.Connection,
    speech_id: str,
    name: str,
    date: str,
    issue_title: str,
    chunks: list[tuple[str, list[float]]],
) -> None:
    """Insert one speech with one or more (chunk_text, vector) chunks."""
    conn.execute(
        "INSERT INTO speeches (speech_id, name, date, issue_title, session) VALUES (?,?,?,?,?)",
        (speech_id, name, date, issue_title, 157),
    )
    for idx, (chunk_text, vec) in enumerate(chunks):
        chunk_id = f"{speech_id}:{idx}"
        conn.execute(
            "INSERT INTO speech_chunks (chunk_id, speech_id, chunk_idx, chunk_text, token_count)"
            " VALUES (?,?,?,?,?)",
            (chunk_id, speech_id, idx, chunk_text, len(chunk_text.split())),
        )
        conn.execute(
            "INSERT INTO speech_vec (chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, sqlite_vec.serialize_float32(vec)),
        )


@pytest.fixture
def make_db(tmp_path):
    """Factory: build an althingi.db (with sqlite-vec) from a list of speeches.

    Each speech: (speech_id, name, date, issue_title, [(chunk_text, vector), ...]).
    """

    def _make(speeches, name: str = "althingi.db") -> Path:
        db_path = tmp_path / name
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.executescript(_SCHEMA)
        for sp in speeches:
            _insert_speech(conn, *sp)
        conn.commit()
        conn.close()
        return db_path

    return _make


def test_eu_filter_excludes_nearest_non_eu_speech(make_db):
    """Nearest neighbour is the non-EU roads speech (e2=0.8); it must be
    filtered out and the nearest EU speech (fisheries, e0=0.6) returned."""
    from esbvaktin.speeches.speech_vectors import search_speeches_by_vectors

    db = make_db(
        [
            (
                "sp-fish",
                "Þorgerður Katrín",
                "2025-03-01",
                "Aðildarviðræður við Evrópusambandið — sjávarútvegur",
                [("Ræða um sjávarútveg og aðildarviðræður.", _unit({0: 1.0}))],
            ),
            (
                "sp-sov",
                "Bjarni Benediktsson",
                "2025-03-02",
                "Evrópusambandið og fullveldi Íslands",
                [("Ræða um fullveldi og Evrópusambandið.", _unit({1: 1.0}))],
            ),
            (
                "sp-road",
                "Sigurður Ingi",
                "2025-03-03",
                "Samgönguáætlun 2025–2037",
                [("Ræða um vegaframkvæmdir og samgöngur.", _unit({2: 1.0}))],
            ),
        ]
    )

    query = _unit({0: 0.6, 2: 0.8})  # closest to roads, then fisheries
    results = search_speeches_by_vectors([query], db_path=db, max_speeches=5)

    ids = [r["speech_id"] for r in results]
    assert "sp-road" not in ids, "non-EU speech must be filtered out"
    assert ids[0] == "sp-fish", "nearest EU speech should rank first"


def test_multichunk_speech_deduped_to_nearest_chunk(make_db):
    """A speech with two chunks appears once, with its nearest chunk's text as
    the excerpt."""
    from esbvaktin.speeches.speech_vectors import search_speeches_by_vectors

    db = make_db(
        [
            (
                "sp-multi",
                "Kristrún Frostadóttir",
                "2025-04-01",
                "Evrópusambandið — sjávarútvegsstefna",
                [
                    ("NEAREST chunk about fisheries.", _unit({0: 1.0})),
                    ("farther chunk on another angle.", _unit({0: 1.0, 3: 1.0})),
                ],
            ),
            (
                "sp-other",
                "Sigmundur Davíð",
                "2025-04-02",
                "Evrópumál og fullveldi",
                [("Ræða um fullveldi.", _unit({1: 1.0}))],
            ),
        ]
    )

    results = search_speeches_by_vectors([_unit({0: 1.0})], db_path=db, max_speeches=5)

    ids = [r["speech_id"] for r in results]
    assert ids.count("sp-multi") == 1, "multi-chunk speech must appear once"
    multi = next(r for r in results if r["speech_id"] == "sp-multi")
    assert multi["excerpt"] == "NEAREST chunk about fisheries."


def test_speech_relevant_to_two_claims_merged_once(make_db):
    """A speech surfaced by two different claim vectors is merged to a single
    entry, keeping its best (nearest) distance."""
    from esbvaktin.speeches.speech_vectors import search_speeches_by_vectors

    db = make_db(
        [
            (
                "sp-A",
                "Þorgerður Katrín",
                "2025-05-01",
                "Aðildarviðræður við Evrópusambandið",
                [("Ræða A um aðild.", _unit({0: 1.0}))],
            ),
            (
                "sp-B",
                "Bjarni Benediktsson",
                "2025-05-02",
                "Evrópusambandið og EES",
                [("Ræða B um EES.", _unit({1: 1.0}))],
            ),
        ]
    )

    # Two claims: one points at sp-A (e0), one at sp-B (e1).
    results = search_speeches_by_vectors(
        [_unit({0: 1.0}), _unit({1: 1.0})], db_path=db, max_speeches=5
    )

    ids = [r["speech_id"] for r in results]
    assert ids.count("sp-A") == 1, "sp-A must not be duplicated across claims"
    assert ids.count("sp-B") == 1, "sp-B must not be duplicated across claims"
    assert sorted(ids) == ["sp-A", "sp-B"]


def test_search_degrades_gracefully(make_db, tmp_path):
    """Missing DB or empty query list returns [] rather than raising — the
    additive-context safety contract."""
    from esbvaktin.speeches.speech_vectors import search_speeches_by_vectors

    missing = tmp_path / "does_not_exist.db"
    assert search_speeches_by_vectors([_unit({0: 1.0})], db_path=missing) == []

    db = make_db(
        [
            ("sp-x", "Nafn", "2025-01-01", "Evrópumál", [("texti", _unit({0: 1.0}))]),
        ]
    )
    assert search_speeches_by_vectors([], db_path=db) == []


def test_build_topical_context_formats_icelandic_block(make_db):
    """The formatted block carries the Icelandic header, the speaker, and the
    excerpt — and leaks no English header text into the Icelandic-only context."""
    from esbvaktin.speeches.context import build_topical_speech_context

    db = make_db(
        [
            (
                "sp-fish",
                "Þorgerður Katrín",
                "2025-03-01",
                "Aðildarviðræður við Evrópusambandið — sjávarútvegur",
                [("Við ræddum sjávarútvegsstefnu ESB í dag.", _unit({0: 1.0}))],
            ),
        ]
    )

    block = build_topical_speech_context(
        ["Ísland myndi tapa yfirráðum yfir fiskveiðilögsögu."],
        claim_embeddings=[_unit({0: 1.0})],
        db_path=db,
    )

    assert block is not None
    assert "Þingræður" in block  # Icelandic header
    assert "Alþing" in block
    assert "Þorgerður Katrín" in block  # speaker
    assert "sjávarútvegsstefnu ESB" in block  # excerpt text
    assert "Parliamentary" not in block  # no English header leaked
    assert "Background" not in block


def test_build_topical_context_returns_none_when_no_speeches(tmp_path):
    """No retrievable speeches (missing DB) ⇒ None, so the caller falls back to
    the existing quote-fidelity block."""
    from esbvaktin.speeches.context import build_topical_speech_context

    missing = tmp_path / "nope.db"
    block = build_topical_speech_context(
        ["einhver fullyrðing"], claim_embeddings=[_unit({0: 1.0})], db_path=missing
    )
    assert block is None


def test_combined_context_is_additive_and_graceful(monkeypatch):
    """build_speech_context_combined joins both blocks; if either is None the
    other still flows; if both are None it returns None."""
    from esbvaktin.speeches import context as ctx

    # Both blocks present → joined.
    monkeypatch.setattr(ctx, "build_speech_context", lambda *a, **k: "QUOTE")
    monkeypatch.setattr(ctx, "build_topical_speech_context", lambda *a, **k: "TOPICAL")
    out = ctx.build_speech_context_combined("article", ["claim"], language="is")
    assert out is not None and "QUOTE" in out and "TOPICAL" in out

    # Topical missing → quote-fidelity still flows.
    monkeypatch.setattr(ctx, "build_topical_speech_context", lambda *a, **k: None)
    assert ctx.build_speech_context_combined("article", ["claim"], language="is") == "QUOTE"

    # Both missing → None (caller adds no speech context).
    monkeypatch.setattr(ctx, "build_speech_context", lambda *a, **k: None)
    assert ctx.build_speech_context_combined("article", ["claim"], language="is") is None
