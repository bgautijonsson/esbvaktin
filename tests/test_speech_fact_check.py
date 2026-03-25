"""Tests for the speech fact-checking pipeline.

6 priority tests covering:
1. Extraction context contains speech guardrails
2. Extraction context contains speaker metadata
3. Sighting registration: match inserts sighting
4. Sighting registration: no match creates unpublished claim
5. Sighting registration: unverifiable discarded
6. Select speeches excludes checked
"""

from __future__ import annotations

import sqlite3
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from esbvaktin.pipeline.models import Claim, ClaimAssessment, ClaimType, Verdict
from esbvaktin.pipeline.prepare_context import prepare_speech_extraction_context

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def work_dir(tmp_path):
    return tmp_path / "speech_check"


@pytest.fixture
def speaker_metadata():
    return {
        "name": "Þorgerður Katrín Gunnarsdóttir",
        "party": "Samfylkingin",
        "speech_type": "flutningsræða",
        "issue_title": "Aðild Íslands að Evrópusambandinu",
        "date": "2026-03-09",
        "session": "157",
    }


@pytest.fixture
def sample_assessments():
    """Three assessments: one matchable, one new, one unverifiable."""
    return [
        ClaimAssessment(
            claim=Claim(
                claim_text="Ísland hefur fiskað 30% af þorski Norðaustur-Atlantshafsins",
                original_quote="30% af þorski",
                category="fisheries",
                claim_type=ClaimType.STATISTIC,
                confidence=0.9,
            ),
            verdict=Verdict.PARTIALLY_SUPPORTED,
            explanation="Talan er nokkurn veginn rétt en vantar samhengi.",
            supporting_evidence=["FISH-DATA-001"],
            contradicting_evidence=[],
            missing_context=None,
            confidence=0.8,
        ),
        ClaimAssessment(
            claim=Claim(
                claim_text="ESB-aðild myndi lækka matvælaverð um 20%",
                original_quote="matvælaverð myndi lækka um 20%",
                category="trade",
                claim_type=ClaimType.FORECAST,
                confidence=0.7,
            ),
            verdict=Verdict.UNSUPPORTED,
            explanation="Engar heimildir styðja þessa tölu.",
            supporting_evidence=[],
            contradicting_evidence=["TRADE-DATA-002"],
            missing_context="Fjöldi breyta hefur áhrif á matvælaverð.",
            confidence=0.85,
        ),
        ClaimAssessment(
            claim=Claim(
                claim_text="Viðhorf almennings mun breytast þegar nær dregur",
                original_quote="viðhorf almennings mun breytast",
                category="polling",
                claim_type=ClaimType.FORECAST,
                confidence=0.4,
            ),
            verdict=Verdict.UNVERIFIABLE,
            explanation="Ekki hægt að sannreyna spá um framtíðarviðhorf.",
            supporting_evidence=[],
            contradicting_evidence=[],
            missing_context=None,
            confidence=0.3,
        ),
    ]


@pytest.fixture
def mock_althingi_db(tmp_path):
    """Create a minimal althingi.db for selection tests."""
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
    # EU-related speeches
    conn.execute(
        "INSERT INTO speeches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "rad001",
            "Þorgerður Katrín Gunnarsdóttir",
            "mp1",
            "2026-03-09T17:10:00",
            None,
            None,
            "516",
            "Aðild Íslands að Evrópusambandinu",
            "flutningsræða",
            157,
        ),
    )
    conn.execute(
        "INSERT INTO speech_texts VALUES (?, ?, ?, ?)",
        ("rad001", "Samfylkingin", 2500, "Ég legg til að Ísland sæki um aðild..."),
    )
    conn.execute(
        "INSERT INTO speeches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "rad002",
            "Sigmundur Davíð Gunnlaugsson",
            "mp2",
            "2026-03-09T18:00:00",
            None,
            None,
            "516",
            "Aðild Íslands að Evrópusambandinu",
            "ræða",
            157,
        ),
    )
    conn.execute(
        "INSERT INTO speech_texts VALUES (?, ?, ?, ?)",
        ("rad002", "Miðflokkurinn", 1800, "Þetta er baktjaldamakk..."),
    )
    # Already-checked speech (will be excluded)
    conn.execute(
        "INSERT INTO speeches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "rad003",
            "Guðrún Hafsteinsdóttir",
            "mp3",
            "2026-03-09T19:00:00",
            None,
            None,
            "516",
            "Aðild Íslands að Evrópusambandinu",
            "ræða",
            157,
        ),
    )
    conn.execute(
        "INSERT INTO speech_texts VALUES (?, ?, ?, ?)",
        ("rad003", "Sjálfstæðisflokkur", 900, "Ég vara við þessu..."),
    )
    conn.commit()
    conn.close()
    return db_path


# ── Test 1: Extraction context contains speech guardrails ─────────


def test_extraction_context_contains_speech_guardrails(work_dir, speaker_metadata):
    """Speech guardrails (filtering intent expressions etc.) appear in context."""
    work_dir.mkdir(parents=True)
    path = prepare_speech_extraction_context(
        speech_text="Ég legg hér fram tillögu um ESB-aðild.",
        speaker_metadata=speaker_metadata,
        output_dir=work_dir,
        language="is",
    )
    content = path.read_text(encoding="utf-8")

    # Check key guardrail phrases exist
    assert "við munum" in content.lower() or "Við munum" in content
    assert "þingræðumálefnum" in content.lower() or "þingskápur" in content.lower()
    assert "Viljayfirlýsingar" in content or "Intent expressions" in content
    assert "Dæmisögur" in content or "Anecdotes" in content


# ── Test 2: Extraction context contains speaker metadata ──────────


def test_extraction_context_contains_speaker_metadata(work_dir, speaker_metadata):
    """Speaker name, party, and speech type appear in extraction context."""
    work_dir.mkdir(parents=True)
    path = prepare_speech_extraction_context(
        speech_text="Test ræðutexti.",
        speaker_metadata=speaker_metadata,
        output_dir=work_dir,
        language="is",
    )
    content = path.read_text(encoding="utf-8")

    assert "Þorgerður Katrín Gunnarsdóttir" in content
    assert "Samfylkingin" in content
    assert "flutningsræða" in content
    assert "157" in content


# ── Test 3: Sighting registration — match inserts sighting ────────


def test_register_sightings_match_inserts_sighting(sample_assessments):
    """When a claim matches an existing bank entry, a sighting is inserted."""
    from esbvaktin.claim_bank.models import ClaimBankMatch

    mock_match = ClaimBankMatch(
        claim_id=42,
        claim_slug="island-hefur-fiskad-30-percent",
        canonical_text_is="Ísland hefur fiskað 30% af þorski",
        similarity=0.85,
        verdict="partially_supported",
        explanation_is="Talan er rétt að mestu.",
        supporting_evidence=["FISH-DATA-001"],
        contradicting_evidence=[],
        confidence=0.8,
        last_verified=date.today(),
        is_fresh=True,
    )

    mock_conn = MagicMock()
    mock_conn.execute = MagicMock()

    with patch(
        "esbvaktin.speeches.register_sightings.search_claims",
        return_value=[mock_match],
    ):
        from esbvaktin.speeches.register_sightings import register_speech_sightings

        # Only pass the first assessment (the matchable one)
        counts = register_speech_sightings(
            assessments=[sample_assessments[0]],
            speech_id="rad001",
            source_url="https://www.althingi.is/altext/raeda/157/rad001.html",
            source_title="Test speech",
            conn=mock_conn,
        )

    assert counts["matched"] == 1
    assert counts["new_claims"] == 0
    assert counts["discarded"] == 0
    # Verify INSERT was called
    assert mock_conn.execute.called


# ── Test 4: No match creates auto-published claim ─────────────────


def test_register_sightings_no_match_creates_unpublished_claim(sample_assessments):
    """Non-unverifiable claim with no bank match creates a new auto-published claim."""
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=MagicMock(fetchone=lambda: (99,)))

    with (
        patch(
            "esbvaktin.speeches.register_sightings.search_claims",
            return_value=[],  # No match
        ),
        patch(
            "esbvaktin.speeches.register_sightings.add_claim",
            return_value=99,
        ) as mock_add,
    ):
        from esbvaktin.speeches.register_sightings import register_speech_sightings

        # Pass the second assessment (unsupported, no match)
        counts = register_speech_sightings(
            assessments=[sample_assessments[1]],
            speech_id="rad001",
            source_url="https://www.althingi.is/altext/raeda/157/rad001.html",
            source_title="Test speech",
            conn=mock_conn,
        )

    assert counts["new_claims"] == 1
    assert counts["matched"] == 0
    assert counts["discarded"] == 0
    # Verify the new claim was auto-published
    call_args = mock_add.call_args
    new_claim = call_args[0][0]
    assert new_claim.published is True
    assert new_claim.verdict == "unsupported"


# ── Test 5: Unverifiable discarded ────────────────────────────────


def test_register_sightings_unverifiable_discarded(sample_assessments):
    """Unverifiable claim with no bank match is discarded."""
    mock_conn = MagicMock()

    with (
        patch(
            "esbvaktin.speeches.register_sightings.search_claims",
            return_value=[],  # No match
        ),
        patch(
            "esbvaktin.speeches.register_sightings.add_claim",
        ) as mock_add,
    ):
        from esbvaktin.speeches.register_sightings import register_speech_sightings

        # Pass the third assessment (unverifiable, no match)
        counts = register_speech_sightings(
            assessments=[sample_assessments[2]],
            speech_id="rad001",
            source_url="https://www.althingi.is/altext/raeda/157/rad001.html",
            source_title="Test speech",
            conn=mock_conn,
        )

    assert counts["discarded"] == 1
    assert counts["matched"] == 0
    assert counts["new_claims"] == 0
    # Verify add_claim was NOT called
    mock_add.assert_not_called()


# ── Test 6: Select speeches excludes checked ──────────────────────


def test_select_speeches_excludes_checked(mock_althingi_db):
    """Already-checked speech IDs are excluded from selection."""
    with patch.dict("os.environ", {"ALTHINGI_DB_PATH": str(mock_althingi_db)}):
        from esbvaktin.speeches.fact_check import select_speeches_for_batch

        # Without exclusion — all 3 speeches
        all_speeches = select_speeches_for_batch(
            limit=10,
            min_words=100,
            exclude_checked=False,
        )
        all_ids = {s["speech_id"] for s in all_speeches}
        assert "rad003" in all_ids
        assert len(all_speeches) == 3

        # With exclusion — rad003 is "already checked"
        checked = {"rad003"}
        filtered = select_speeches_for_batch(
            limit=10,
            min_words=100,
            exclude_checked=True,
            checked_speech_ids=checked,
        )
        filtered_ids = {s["speech_id"] for s in filtered}
        assert "rad003" not in filtered_ids
        assert len(filtered) == 2
