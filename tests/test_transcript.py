"""Tests for panel show transcript parsing."""

import pytest
from datetime import date

from esbvaktin.pipeline.transcript import (
    ParsedTranscript,
    TranscriptTurn,
    parse_transcript,
    _parse_header,
    _parse_name_role,
    _detect_moderator,
)


# ── Minimal transcript fixture ──────────────────────────────────────

MINIMAL_TRANSCRIPT = """\
# 25. þáttur: Stefnt að kosningu um ESB í sumar

**Source:** Silfrið (RÚV) | **Date:** 2026-03-10T12:38:51 | **URL:** https://shows.acast.com/silfri/episodes/25-attur
**Words:** 500 | **Language:** is

Mælandi 1: Gott kvöld og velkomin í Silfrið. Hér eru gestir kvöldsins.

Þorgerður Katrín Gunnarsdóttir (utanríkisráðherra): Þetta er náttúrulega \
algjör lýðræðisveisla sem ríkisstjórnin er að bjóða upp á.

Sigmundur Davíð Gunnlaugsson (formaður Miðflokksins): Ég er algjörlega \
ósammála. Þetta er verið að fara á bak við þjóðina.

Mælandi 1: Takk fyrir komuna.
"""


# ── Header parsing ──────────────────────────────────────────────────


def test_parse_header_extracts_all_fields():
    meta = _parse_header(MINIMAL_TRANSCRIPT)
    assert meta["title"] == "25. þáttur: Stefnt að kosningu um ESB í sumar"
    assert meta["show_name"] == "Silfrið"
    assert meta["broadcaster"] == "RÚV"
    assert meta["date"] == date(2026, 3, 10)
    assert meta["url"] == "https://shows.acast.com/silfri/episodes/25-attur"
    assert meta["word_count"] == 500
    assert meta["episode"] == "25. þáttur"


def test_parse_header_missing_fields():
    meta = _parse_header("# Some Title\n\nJust text here.")
    assert meta["title"] == "Some Title"
    assert "show_name" not in meta
    assert "date" not in meta


# ── Name/role parsing ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "label, expected_name, expected_role",
    [
        ("Þorgerður Katrín Gunnarsdóttir (utanríkisráðherra)", "Þorgerður Katrín Gunnarsdóttir", "utanríkisráðherra"),
        ("Sigmundur Davíð Gunnlaugsson (formaður Miðflokksins)", "Sigmundur Davíð Gunnlaugsson", "formaður Miðflokksins"),
        ("Mælandi 1", "Mælandi 1", None),
        ("Guðrún Hafsteinsdóttir (formaður Sjálfstæðisflokksins)", "Guðrún Hafsteinsdóttir", "formaður Sjálfstæðisflokksins"),
    ],
)
def test_parse_name_role(label, expected_name, expected_role):
    name, role = _parse_name_role(label)
    assert name == expected_name
    assert role == expected_role


# ── Full transcript parsing ─────────────────────────────────────────


def test_parse_transcript_basic():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    assert isinstance(result, ParsedTranscript)
    assert result.title == "25. þáttur: Stefnt að kosningu um ESB í sumar"
    assert result.show_name == "Silfrið"
    assert result.broadcaster == "RÚV"
    assert result.date == date(2026, 3, 10)
    assert result.episode == "25. þáttur"


def test_parse_transcript_turn_count():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    assert len(result.turns) == 4


def test_parse_transcript_moderator_detection():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    moderator_turns = [t for t in result.turns if t.is_moderator]
    speaker_turns = [t for t in result.turns if not t.is_moderator]
    assert len(moderator_turns) == 2
    assert len(speaker_turns) == 2


def test_parse_transcript_speaker_names():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    names = result.participant_names
    assert "Þorgerður Katrín Gunnarsdóttir" in names
    assert "Sigmundur Davíð Gunnlaugsson" in names
    assert len(names) == 2  # moderator excluded


def test_parse_transcript_participants():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    participants = result.participants
    assert len(participants) == 2
    tk = next(p for p in participants if p["name"] == "Þorgerður Katrín Gunnarsdóttir")
    assert tk["role"] == "utanríkisráðherra"


def test_parse_transcript_speaker_roles():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    tk = next(t for t in result.turns if t.speaker_name == "Þorgerður Katrín Gunnarsdóttir")
    assert tk.speaker_role == "utanríkisráðherra"
    sd = next(t for t in result.turns if t.speaker_name == "Sigmundur Davíð Gunnlaugsson")
    assert sd.speaker_role == "formaður Miðflokksins"


def test_parse_transcript_turn_text():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    tk = next(t for t in result.turns if t.speaker_name == "Þorgerður Katrín Gunnarsdóttir")
    assert "lýðræðisveisla" in tk.text
    assert "Sigmundur" not in tk.text  # shouldn't bleed into next turn


def test_parse_transcript_turn_counts_property():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    counts = result.speaker_turn_counts
    assert counts["Moderator"] == 2
    assert counts["Þorgerður Katrín Gunnarsdóttir"] == 1
    assert counts["Sigmundur Davíð Gunnlaugsson"] == 1


def test_parse_transcript_debate_text():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    text = result.debate_text(include_moderator=False)
    assert "Þorgerður Katrín" in text
    assert "Mælandi" not in text


def test_parse_transcript_debate_text_with_moderator():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    text = result.debate_text(include_moderator=True)
    assert "Mælandi 1" in text  # moderator name appears in bold label


def test_parse_transcript_speaker_text():
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    text = result.speaker_text("Þorgerður Katrín Gunnarsdóttir")
    assert "lýðræðisveisla" in text


# ── Edge cases ──────────────────────────────────────────────────────


def test_parse_transcript_empty():
    result = parse_transcript("")
    assert result.turns == []
    assert result.participant_names == []


def test_parse_transcript_no_header():
    text = "Mælandi 1: Halló.\n\nÞorgerður (ráðherra): Já, sæl.\n"
    result = parse_transcript(text)
    assert len(result.turns) == 2
    assert result.title == ""


def test_parse_transcript_episode_without_space():
    """Episode numbers like '25.þáttur' (no space) should still parse."""
    text = "# 25.þáttur: Test\n\nMælandi 1: Halló.\n"
    result = parse_transcript(text)
    assert result.episode == "25.þáttur"


def test_parse_transcript_multiple_moderators():
    """Some shows have two moderators."""
    text = """\
Mælandi 1: Fyrsti spurning.

Þorgerður (ráðherra): Svar.

Mælandi 2: Önnur spurning.
"""
    result = parse_transcript(text)
    moderators = [t for t in result.turns if t.is_moderator]
    assert len(moderators) == 2
    assert moderators[0].speaker_name == "Mælandi 1"
    assert moderators[1].speaker_name == "Mælandi 2"


# ── Named moderator detection ─────────────────────────────────────


NAMED_MODERATOR_TRANSCRIPT = """\
# Test þáttur

**Source:** Silfrið (RÚV) | **Date:** 2026-03-10T12:00:00
**Words:** 300 | **Language:** is

Bergsteinn Sigurðsson: Gott kvöld, velkomin í Silfrið.

Þorgerður Katrín (ráðherra): Takk fyrir.

Bergsteinn Sigurðsson: Hvað segir Sigmundur?

Sigmundur Davíð (formaður Miðflokksins): Ég er ósammála.

Bergsteinn Sigurðsson: En Lilja Dögg?

Lilja Dögg (formaður Framsóknar): Við þurfum umræðu.

Bergsteinn Sigurðsson: Takk kærlega.

Bergsteinn Sigurðsson: Og gott kvöld.
"""


def test_auto_detect_named_moderator():
    """Auto-detect moderator as the most-frequent no-role speaker."""
    result = parse_transcript(NAMED_MODERATOR_TRANSCRIPT)
    moderators = [t for t in result.turns if t.is_moderator]
    # Bergsteinn has 5 turns with no role — should be detected as moderator
    assert len(moderators) == 5
    assert all(t.speaker_name == "Bergsteinn Sigurðsson" for t in moderators)


def test_auto_detect_does_not_flag_panellists():
    """Panellists (with roles) should not be flagged as moderators."""
    result = parse_transcript(NAMED_MODERATOR_TRANSCRIPT)
    non_mod = [t for t in result.turns if not t.is_moderator]
    names = {t.speaker_name for t in non_mod}
    assert "Þorgerður Katrín" in names
    assert "Sigmundur Davíð" in names
    assert "Bergsteinn Sigurðsson" not in names


def test_explicit_moderator_names_override():
    """Explicit moderator_names takes precedence."""
    result = parse_transcript(
        NAMED_MODERATOR_TRANSCRIPT,
        moderator_names={"Bergsteinn Sigurðsson"},
    )
    moderators = [t for t in result.turns if t.is_moderator]
    assert len(moderators) == 5


def test_participants_exclude_auto_detected_moderator():
    """Auto-detected moderator should not appear in participants list."""
    result = parse_transcript(NAMED_MODERATOR_TRANSCRIPT)
    names = result.participant_names
    assert "Bergsteinn Sigurðsson" not in names
    assert len(names) == 3


def test_detect_moderator_threshold():
    """Speakers with fewer than 5 no-role turns should not be auto-detected."""
    turns = [
        TranscriptTurn("A", "A", None, "text", False),
        TranscriptTurn("A", "A", None, "text", False),
        TranscriptTurn("A", "A", None, "text", False),  # only 3 turns
        TranscriptTurn("B (role)", "B", "role", "text", False),
        TranscriptTurn("B (role)", "B", "role", "text", False),
    ]
    result = _detect_moderator(turns)
    assert result is None  # 3 < 5 threshold


def test_mælandi_pattern_skips_auto_detect():
    """If Mælandi pattern matches, auto-detection should not run."""
    result = parse_transcript(MINIMAL_TRANSCRIPT)
    # Already handled by _MODERATOR_RE — auto-detect not triggered
    moderators = [t for t in result.turns if t.is_moderator]
    assert len(moderators) == 2
    assert all("Mælandi" in t.speaker_name for t in moderators)
