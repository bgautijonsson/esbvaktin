"""fresh-01: the monthly high-decay evidence refresh sweeps stale_evidence (90d+) plus
the four high-decay topics, flags the affected claims for the next *human-gated*
reassessment cycle, and prints a review note. It never auto-publishes — queueing only
sets needs_reassessment; the note frames everything as review.

monthly_evidence_refresh.py is a script, loaded via importlib.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "monthly_evidence_refresh.py"


def _load():
    spec = importlib.util.spec_from_file_location("_monthly_refresh_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_high_decay_topics_are_the_documented_four():
    m = _load()
    assert set(m.HIGH_DECAY_TOPICS) == {"polling", "party_positions", "org_positions", "currency"}


def test_merge_candidates_dedups_and_unions_reasons():
    m = _load()
    stale = [
        {"evidence_id": "POLL-DATA-001", "topic": "polling", "days_stale": 120},
        {"evidence_id": "TRADE-DATA-009", "topic": "trade", "days_stale": 200},
    ]
    high_decay = [
        {"evidence_id": "POLL-DATA-001", "topic": "polling", "days_stale": 120},  # also stale
        {"evidence_id": "CUR-DATA-003", "topic": "currency", "days_stale": 40},
    ]
    candidates = m.merge_candidates(stale, high_decay)
    by_id = {c["evidence_id"]: c for c in candidates}
    assert set(by_id) == {"POLL-DATA-001", "TRADE-DATA-009", "CUR-DATA-003"}
    # An entry that is both 90d-stale and in a high-decay topic carries both reasons.
    assert set(by_id["POLL-DATA-001"]["reasons"]) == {"stale", "high_decay"}
    assert by_id["TRADE-DATA-009"]["reasons"] == ["stale"]
    assert by_id["CUR-DATA-003"]["reasons"] == ["high_decay"]


def test_build_review_note_lists_candidates_and_stays_review_only():
    m = _load()
    candidates = [
        {
            "evidence_id": "POLL-DATA-001",
            "topic": "polling",
            "days_stale": 120,
            "reasons": ["stale", "high_decay"],
        },
        {
            "evidence_id": "CUR-DATA-003",
            "topic": "currency",
            "days_stale": 40,
            "reasons": ["high_decay"],
        },
    ]
    note = m.build_review_note(candidates, queued_claim_count=7, today=date(2026, 6, 1))

    assert "2026-06-01" in note
    assert "POLL-DATA-001" in note and "CUR-DATA-003" in note
    assert "7" in note  # claims flagged for reassessment
    assert "/reassess" in note  # the human-gated next step
    # Editorial discipline: a review note never frames anything as published.
    assert "publish" not in note.lower()


def test_queue_reassessment_flags_claims_without_publishing():
    m = _load()
    captured = {}

    class _Cur:
        rowcount = 3

    class _FakeConn:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params
            return _Cur()

    n = m.queue_reassessment(_FakeConn(), [101, 102, 103], reason="monthly_high_decay_refresh")
    assert n == 3
    sql = captured["sql"]
    assert "needs_reassessment = TRUE" in sql
    assert "reassessment_reason" in sql
    # Never touches the published flag — queueing is not publishing.
    assert "published" not in sql.lower()


def test_queue_reassessment_noops_on_empty():
    m = _load()

    class _BoomConn:
        def execute(self, *a, **k):
            raise AssertionError("must not execute SQL for an empty claim list")

    assert m.queue_reassessment(_BoomConn(), [], reason="x") == 0
