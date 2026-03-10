"""Tests for esbvaktin.speeches.context — pipeline speech integration."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from esbvaktin.speeches.context import (
    _format_speech_context,
    build_speech_context,
    find_mp_names_in_text,
    get_speech_excerpts,
)


# ── find_mp_names_in_text ──────────────────────────────────────────


@pytest.fixture
def mock_db_with_names(tmp_path):
    """Create a minimal althingi.db with some test speakers."""
    db_path = tmp_path / "althingi.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE speeches (
            speech_id TEXT PRIMARY KEY,
            name TEXT,
            mp_id TEXT,
            date TEXT,
            started TEXT,
            ended TEXT,
            issue_nr TEXT,
            issue_title TEXT,
            speech_type TEXT,
            session INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE speech_texts (
            speech_id TEXT PRIMARY KEY,
            party TEXT,
            word_count INTEGER,
            full_text TEXT
        )
    """)
    # Insert test data — EU-related issue title
    conn.execute(
        "INSERT INTO speeches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "Jón Baldur Arnason", "mp1", "2026-03-01", None, None,
         "516", "Aðildarviðræður við ESB", "ræða", 157),
    )
    conn.execute(
        "INSERT INTO speech_texts VALUES (?, ?, ?, ?)",
        ("s1", "Viðreisn", 150, "Ég tel að ESB-aðild sé mikilvæg fyrir Ísland."),
    )
    conn.execute(
        "INSERT INTO speeches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s2", "Anna María Björnsdóttir", "mp2", "2026-03-02", None, None,
         "517", "Evrópumál á Íslandi", "ræða", 157),
    )
    conn.execute(
        "INSERT INTO speech_texts VALUES (?, ?, ?, ?)",
        ("s2", "Sjálfstæðisflokkur", 200, "Fullveldi Íslands er í hættu."),
    )
    conn.commit()
    conn.close()
    return db_path


def test_find_mp_names_exact_match(mock_db_with_names):
    """Names appearing in text are found."""
    with patch.dict("os.environ", {"ALTHINGI_DB_PATH": str(mock_db_with_names)}):
        text = "Jón Baldur Arnason sagðist mótfallinn ESB."
        names = find_mp_names_in_text(text)
        assert "Jón Baldur Arnason" in names


def test_find_mp_names_case_insensitive(mock_db_with_names):
    """Case-insensitive matching."""
    with patch.dict("os.environ", {"ALTHINGI_DB_PATH": str(mock_db_with_names)}):
        text = "jón baldur arnason er þingmaður."
        names = find_mp_names_in_text(text)
        assert "Jón Baldur Arnason" in names


def test_find_mp_names_not_found(mock_db_with_names):
    """Names not in text are not returned."""
    with patch.dict("os.environ", {"ALTHINGI_DB_PATH": str(mock_db_with_names)}):
        text = "Enginn þingmaður nefndur hér."
        names = find_mp_names_in_text(text)
        assert names == []


def test_find_mp_names_no_db():
    """Returns empty list if DB not available."""
    with patch.dict("os.environ", {"ALTHINGI_DB_PATH": "/nonexistent/althingi.db"}):
        names = find_mp_names_in_text("Jón Baldur Arnason ræddi.")
        assert names == []


# ── get_speech_excerpts ────────────────────────────────────────────


def test_get_speech_excerpts(mock_db_with_names):
    """Retrieves excerpts for known MPs."""
    with patch.dict("os.environ", {"ALTHINGI_DB_PATH": str(mock_db_with_names)}):
        excerpts = get_speech_excerpts(["Jón Baldur Arnason"])
        assert "Jón Baldur Arnason" in excerpts
        assert len(excerpts["Jón Baldur Arnason"]) == 1
        assert "ESB-aðild" in excerpts["Jón Baldur Arnason"][0]["excerpt"]


def test_get_speech_excerpts_empty_names(mock_db_with_names):
    """Empty names list returns empty dict."""
    with patch.dict("os.environ", {"ALTHINGI_DB_PATH": str(mock_db_with_names)}):
        assert get_speech_excerpts([]) == {}


# ── _format_speech_context ─────────────────────────────────────────


def test_format_speech_context_icelandic():
    """Formats excerpts as Icelandic markdown."""
    excerpts = {
        "Jón Baldur": [{
            "date": "2026-03-01",
            "issue_title": "ESB-aðild",
            "excerpt": "Ég tel þetta mikilvægt.",
            "word_count": 50,
        }]
    }
    result = _format_speech_context(excerpts, language="is")
    assert "Þingræður" in result
    assert "Jón Baldur" in result
    assert "2026-03-01" in result


def test_format_speech_context_empty():
    """Empty excerpts return empty string."""
    assert _format_speech_context({}) == ""


# ── build_speech_context ───────────────────────────────────────────


def test_build_speech_context_integration(mock_db_with_names):
    """End-to-end: article text → formatted context."""
    with patch.dict("os.environ", {"ALTHINGI_DB_PATH": str(mock_db_with_names)}):
        text = "Jón Baldur Arnason sagðist hafa áhyggjur af ESB-aðild."
        ctx = build_speech_context(text, language="is")
        assert ctx is not None
        assert "Jón Baldur Arnason" in ctx
        assert "Þingræður" in ctx


def test_build_speech_context_no_mps(mock_db_with_names):
    """Returns None if no MPs found in text."""
    with patch.dict("os.environ", {"ALTHINGI_DB_PATH": str(mock_db_with_names)}):
        ctx = build_speech_context("Engin þingmenn nefndir.", language="is")
        assert ctx is None
