"""Tests for panel show extraction context preparation."""

import json
from datetime import date
from pathlib import Path

import pytest

from esbvaktin.pipeline.models import Claim, ClaimType
from esbvaktin.pipeline.transcript import ParsedTranscript, TranscriptTurn, parse_transcript
from esbvaktin.pipeline.prepare_context import prepare_panel_extraction_context


# ── Fixtures ────────────────────────────────────────────────────────

SAMPLE_TRANSCRIPT = """\
# 25. þáttur: Stefnt að kosningu um ESB í sumar

**Source:** Silfrið (RÚV) | **Date:** 2026-03-10T12:38:51 | **URL:** https://example.com/silfrid-25
**Words:** 800 | **Language:** is

Mælandi 1: Gott kvöld og velkomin í Silfrið. Hér erum við með fulltrúa allra flokka.

Þorgerður Katrín Gunnarsdóttir (utanríkisráðherra): Ríkisstjórnin leggur til \
þjóðaratkvæðagreiðslu um ESB-aðildarviðræður. Þetta er lýðræðisveisla.

Sigmundur Davíð Gunnlaugsson (formaður Miðflokksins): Ísland tapar fullveldi \
ef við göngum í ESB. Sjávarútvegsstefna ESB myndi eyðileggja sjávarútveginn.

Mælandi 1: Hvað segir Framsókn?

Lilja Dögg Alfreðsdóttir (formaður Framsóknarflokksins): Við þurfum að skoða \
þetta vandlega. Norðmenn höfnuðu ESB-aðild tvisvar.
"""


@pytest.fixture
def parsed_transcript():
    return parse_transcript(SAMPLE_TRANSCRIPT)


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "panel_test"
    d.mkdir()
    return d


# ── Context generation tests ────────────────────────────────────────


def test_panel_context_creates_file(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir)
    assert path.exists()
    assert path.name == "_context_extraction.md"


def test_panel_context_contains_title(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir)
    content = path.read_text()
    assert "Stefnt að kosningu um ESB í sumar" in content


def test_panel_context_contains_participants(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir)
    content = path.read_text()
    assert "Þorgerður Katrín Gunnarsdóttir" in content
    assert "Sigmundur Davíð Gunnlaugsson" in content
    assert "Lilja Dögg Alfreðsdóttir" in content


def test_panel_context_contains_metadata(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir)
    content = path.read_text()
    assert "Silfrið" in content
    assert "RÚV" in content
    assert "2026-03-10" in content


def test_panel_context_excludes_moderator_text(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir)
    content = path.read_text()
    # Moderator text should not appear in the debate section
    # (the header "Umræðan" section, not the metadata)
    debate_section = content.split("## Umræðan")[1] if "## Umræðan" in content else ""
    assert "Mælandi 1" not in debate_section


def test_panel_context_includes_speaker_text(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir)
    content = path.read_text()
    assert "lýðræðisveisla" in content
    assert "fullveldi" in content
    assert "Norðmenn höfnuðu" in content


def test_panel_context_requires_speaker_name_field(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir)
    content = path.read_text()
    assert "speaker_name" in content
    # Should mention it's required
    assert "nauðsynlegt" in content or "required" in content


def test_panel_context_has_debate_guardrails(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir)
    content = path.read_text()
    # Should have panel-show-specific exclusions
    assert "umsjónarmanns" in content or "Moderator" in content
    assert "Viljayfirlýsingar" in content or "Intent expressions" in content


def test_panel_context_english(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir, language="en")
    content = path.read_text()
    assert "Panel Show Debate" in content
    assert "speaker_name" in content
    assert "Moderator questions" in content


def test_panel_context_has_json_example(parsed_transcript, work_dir):
    path = prepare_panel_extraction_context(parsed_transcript, work_dir)
    content = path.read_text()
    assert '"speaker_name"' in content
    assert '"claim_text"' in content


# ── Claim model speaker_name tests ──────────────────────────────────


def test_claim_with_speaker_name():
    claim = Claim(
        claim_text="Ísland tapar fullveldi",
        original_quote="Ísland tapar fullveldi ef við göngum í ESB",
        category="sovereignty",
        claim_type=ClaimType.LEGAL_ASSERTION,
        confidence=0.9,
        speaker_name="Sigmundur Davíð Gunnlaugsson",
    )
    assert claim.speaker_name == "Sigmundur Davíð Gunnlaugsson"


def test_claim_without_speaker_name():
    claim = Claim(
        claim_text="Test claim",
        original_quote="Test quote",
        category="other",
        claim_type=ClaimType.OPINION,
        confidence=0.8,
    )
    assert claim.speaker_name is None


def test_claim_speaker_name_in_json():
    claim = Claim(
        claim_text="Test",
        original_quote="Test",
        category="other",
        claim_type=ClaimType.OPINION,
        confidence=0.8,
        speaker_name="Test Person",
    )
    data = claim.model_dump()
    assert data["speaker_name"] == "Test Person"


def test_claim_speaker_name_from_json():
    """Simulate parsing subagent output with speaker_name."""
    raw = {
        "claim_text": "Ísland tapar fullveldi",
        "original_quote": "Ísland tapar fullveldi ef við göngum í ESB",
        "speaker_name": "Sigmundur Davíð Gunnlaugsson",
        "category": "sovereignty",
        "claim_type": "legal_assertion",
        "confidence": 0.9,
    }
    claim = Claim.model_validate(raw)
    assert claim.speaker_name == "Sigmundur Davíð Gunnlaugsson"


def test_claim_backward_compat_no_speaker():
    """Existing claims without speaker_name should still parse."""
    raw = {
        "claim_text": "Old claim",
        "original_quote": "Old quote",
        "category": "trade",
        "claim_type": "statistic",
        "confidence": 0.85,
    }
    claim = Claim.model_validate(raw)
    assert claim.speaker_name is None
