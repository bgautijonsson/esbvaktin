"""Tests for authoritative session resolution (xrepo-07).

Legislative session is owned by althingi (speeches.session). esbvaktin must read it
directly, not re-derive it from dates — once session 158 opens (~Oct 2026, inside the
referendum window) a date ladder mislabels new speeches as 157, corrupting the
althingi.is citation URL that doubles as the cross-DB dedup key.
"""

from esbvaktin.speeches.fact_check import _session_for_date, resolve_session


def test_resolve_prefers_db_session_over_date_ladder():
    """The bomb: a session-158 speech dated in the 157 window must NOT be relabelled 157."""
    assert resolve_session("158", "2025-09-15") == "158"
    assert resolve_session(158, "2025-09-15") == "158"


def test_resolve_falls_back_to_ladder_when_session_missing():
    assert resolve_session("?", "2024-10-01") == "156"
    assert resolve_session(None, "2024-10-01") == "156"
    assert resolve_session("", "2023-10-01") == "155"


def test_session_for_date_knows_session_158():
    """Session 158 opens ~Oct 2026, inside the referendum project window."""
    assert _session_for_date("2026-10-15") == "158"
    assert _session_for_date("2025-09-15") == "157"
    assert _session_for_date("2024-10-01") == "156"
