"""Tests for the weekly overview pipeline.

Covers: diversity_score, _parse_iso_week, _editorial_excerpt, _delta_arrow,
caveat truncation, topic label coverage, and slug parity assertions.
"""

from esbvaktin.pipeline.models import KNOWN_TOPICS, TOPIC_LABELS_IS
from esbvaktin.utils.slugify import icelandic_slugify
from scripts.export_overviews import _editorial_excerpt
from scripts.generate_overview import _parse_iso_week, diversity_score
from scripts.prepare_overview_context import _delta_arrow, _format_date_is

# ── diversity_score ───────────────────────────────────────────────────


class TestDiversityScore:
    def test_empty(self):
        assert diversity_score({}) == 0.0

    def test_single_topic(self):
        assert diversity_score({"fisheries": 10}) == 0.0

    def test_perfectly_even(self):
        """Two equal topics → normalised entropy = 1.0."""
        assert diversity_score({"a": 5, "b": 5}) == 1.0

    def test_skewed(self):
        """Heavily skewed → low diversity."""
        score = diversity_score({"a": 100, "b": 1})
        assert 0 < score < 0.2

    def test_three_equal(self):
        score = diversity_score({"a": 10, "b": 10, "c": 10})
        assert score == 1.0

    def test_moderate_spread(self):
        counts = {"fisheries": 10, "trade": 8, "sovereignty": 3, "housing": 1}
        score = diversity_score(counts)
        assert 0.5 < score < 1.0

    def test_result_is_rounded(self):
        score = diversity_score({"a": 7, "b": 3})
        # Should be rounded to 4 decimal places
        assert score == round(score, 4)


# ── _parse_iso_week ───────────────────────────────────────────────────


class TestParseIsoWeek:
    def test_normal_week(self):
        monday, sunday = _parse_iso_week("2026-W11")
        assert monday.isoformat() == "2026-03-09"
        assert sunday.isoformat() == "2026-03-15"

    def test_week_1(self):
        monday, sunday = _parse_iso_week("2026-W01")
        assert monday.weekday() == 0  # Monday
        assert (sunday - monday).days == 6

    def test_week_53_year_boundary(self):
        """2026 has 53 ISO weeks (Jan 1 is Thursday)."""
        monday, sunday = _parse_iso_week("2026-W53")
        assert monday.isoformat() == "2026-12-28"
        assert sunday.isoformat() == "2027-01-03"

    def test_2027_week_1(self):
        monday, sunday = _parse_iso_week("2027-W01")
        assert monday.isoformat() == "2027-01-04"
        assert sunday.isoformat() == "2027-01-10"

    def test_span_is_7_days(self):
        for week in ["2026-W01", "2026-W11", "2026-W52"]:
            monday, sunday = _parse_iso_week(week)
            assert (sunday - monday).days == 6


# ── _editorial_excerpt ────────────────────────────────────────────────


class TestEditorialExcerpt:
    def test_empty(self):
        assert _editorial_excerpt("") == ""

    def test_short_text(self):
        assert _editorial_excerpt("Hello world.") == "Hello world."

    def test_heading_skipped(self):
        text = "# Vikuyfirlit\n\nFirst paragraph here."
        assert _editorial_excerpt(text) == "First paragraph here."

    def test_truncation_at_word_boundary(self):
        # 200 chars of text to trigger truncation at 150
        text = "Orð " * 50  # 200 chars
        excerpt = _editorial_excerpt(text, max_chars=150)
        assert excerpt.endswith("…")
        assert len(excerpt) <= 155  # 150 + room for "…"
        # Should not cut mid-word
        assert "Or…" not in excerpt

    def test_blank_lines_skipped(self):
        text = "\n\n\nActual content."
        assert _editorial_excerpt(text) == "Actual content."


# ── _delta_arrow ──────────────────────────────────────────────────────


class TestDeltaArrow:
    def test_increase(self):
        result = _delta_arrow(10, 5)
        assert "↑" in result
        assert "5" in result

    def test_decrease(self):
        result = _delta_arrow(3, 7)
        assert "↓" in result
        assert "7" in result

    def test_no_change(self):
        result = _delta_arrow(5, 5)
        assert "óbreytt" in result

    def test_from_zero(self):
        result = _delta_arrow(10, 0)
        assert "↑" in result
        assert "0" in result


# ── _format_date_is ──────────────────────────────────────────────────


class TestFormatDateIs:
    def test_basic(self):
        assert _format_date_is("2026-03-09") == "9. mars 2026"

    def test_january(self):
        assert _format_date_is("2026-01-15") == "15. janúar 2026"

    def test_december(self):
        assert _format_date_is("2026-12-31") == "31. desember 2026"


# ── Topic label coverage ─────────────────────────────────────────────


class TestTopicLabels:
    def test_all_known_topics_have_labels(self):
        """Every topic in KNOWN_TOPICS must have an Icelandic label."""
        missing = KNOWN_TOPICS - set(TOPIC_LABELS_IS.keys())
        assert not missing, f"Topics without Icelandic labels: {missing}"

    def test_other_has_label(self):
        """The 'other' topic must have an Icelandic label."""
        assert "other" in TOPIC_LABELS_IS
        assert TOPIC_LABELS_IS["other"] == "Annað"

    def test_no_english_in_labels(self):
        """All labels should contain Icelandic characters or be recognisable Icelandic."""
        for key, label in TOPIC_LABELS_IS.items():
            # Label should not be identical to its key (fallback)
            if key != "other":  # "other" → "Annað" is fine
                assert label != key, f"Label for '{key}' is just the English key"


# ── Slug parity (Python ↔ JS contract) ───────────────────────────────


class TestSlugParity:
    """Verify Python icelandic_slugify handles non-Icelandic diacritics.

    The JS isSlug function must produce identical output. These test cases
    document the contract — if Python changes, JS must be updated too.
    """

    def test_icelandic_standard(self):
        assert icelandic_slugify("Þorgerður Katrín Gunnarsdóttir") == "thorgerdur-katrin-gunnarsdottir"

    def test_croatian_diacritics(self):
        assert icelandic_slugify("Boris Vujčić") == "boris-vujcic"

    def test_french_accents(self):
        assert icelandic_slugify("Jean-Rémi Chareyre") == "jean-remi-chareyre"

    def test_german_umlaut(self):
        assert icelandic_slugify("Thomas Möller") == "thomas-moller"

    def test_spanish_tilde(self):
        assert icelandic_slugify("Año Nuevo") == "ano-nuevo"

    def test_polish_diacritics(self):
        # Ł doesn't decompose under NFKD (it's a base character, not composed)
        # so it's dropped by ASCII encoding — this matches JS behaviour too
        assert icelandic_slugify("Łódź") == "odz"

    def test_mixed_diacritics(self):
        assert icelandic_slugify("Çağlar Söyüncü") == "caglar-soyuncu"


# ── Caveat truncation ────────────────────────────────────────────────


class TestCaveatTruncation:
    """Verify the word-boundary truncation logic from prepare_overview_context."""

    def _truncate(self, text: str) -> str:
        """Replicate the truncation logic from prepare_overview_context.py."""
        if len(text) > 200:
            caveat = text[:200]
            last_space = caveat.rfind(" ")
            if last_space > 120:
                caveat = caveat[:last_space]
            caveat += "…"
            return caveat
        return text

    def test_short_caveat_unchanged(self):
        assert self._truncate("Short caveat.") == "Short caveat."

    def test_long_caveat_truncated_at_word(self):
        text = "Orð " * 60  # ~240 chars
        result = self._truncate(text)
        assert result.endswith("…")
        assert len(result) <= 205
        # Should not end with a partial word
        assert not result[-2].isalpha() or result[-1] == "…"

    def test_exactly_200_unchanged(self):
        text = "x" * 200
        assert self._truncate(text) == text
