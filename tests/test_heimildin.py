"""Smoke tests for the Heimildin rhetoric analysis pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add scripts/heimildin to path so config module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "heimildin"))

from config import (
    DEBATES,
    KNOWN_TOPICS,
    TOPIC_LABELS_IS,
    TOPIC_LABELS_IS_LOWER,
    TOPIC_PREFIX_MAP,
)

# ---------------------------------------------------------------------------
# Config consistency
# ---------------------------------------------------------------------------


class TestConfig:
    def test_topic_labels_cover_known_topics(self):
        """Every known topic has an Icelandic label."""
        for topic in KNOWN_TOPICS:
            assert topic in TOPIC_LABELS_IS, f"Missing label for topic '{topic}'"

    def test_lowercase_labels_match(self):
        """Lowercase variant is derived correctly from TOPIC_LABELS_IS."""
        for key, val in TOPIC_LABELS_IS_LOWER.items():
            assert val == TOPIC_LABELS_IS[key].lower()

    def test_prefix_map_covers_known_topics(self):
        """Every prefix maps to a known topic."""
        prefix_targets = set(TOPIC_PREFIX_MAP.values())
        for target in prefix_targets:
            assert target in TOPIC_LABELS_IS, f"Prefix target '{target}' has no label"

    def test_prefix_map_is_injective(self):
        """No two prefixes map to the same topic."""
        seen: dict[str, str] = {}
        for prefix, topic in TOPIC_PREFIX_MAP.items():
            if topic in seen:
                pytest.fail(f"Duplicate: {prefix} and {seen[topic]} both map to '{topic}'")
            seen[topic] = prefix

    def test_debates_have_required_keys(self):
        """Each debate definition has the required structure."""
        for era, debates in DEBATES.items():
            assert era in ("esb", "ees"), f"Unknown era: {era}"
            for d in debates:
                assert "issue_nr" in d
                assert "session" in d
                assert "title" in d


# ---------------------------------------------------------------------------
# Instance ID format
# ---------------------------------------------------------------------------


class TestInstanceIDs:
    """Stable instance IDs follow the pattern rad{timestamp}:{index}."""

    def test_valid_format(self):
        valid = [
            "rad20260309T171000:3",
            "rad19930325T120423:12",
            "rad20260316T162822:0",
        ]
        import re

        pattern = re.compile(r"^rad\d{8}T\d{6}:\d+$")
        for iid in valid:
            assert pattern.match(iid), f"Invalid instance ID: {iid}"

    def test_invalid_format(self):
        import re

        pattern = re.compile(r"^rad\d{8}T\d{6}:\d+$")
        invalid = ["some_random_id", "rad2026:3", "3", ""]
        for iid in invalid:
            assert not pattern.match(iid), f"Should be invalid: {iid}"


# ---------------------------------------------------------------------------
# JSON sanitisation (Icelandic „" quotes)
# ---------------------------------------------------------------------------


class TestJSONSanitisation:
    """Icelandic „" quotes break json.loads — verify sanitisation works."""

    def test_icelandic_quotes_in_json(self):
        raw = '[{"text": "Þetta er „tilvitnun" í ræðu"}]'
        # Standard json.loads should fail on „"
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)

    def test_sanitised_quotes_parse(self):
        """The pipeline sanitises „" used as JSON field delimiters by agents."""
        # Agent sometimes uses „" as JSON quote characters
        raw = "[{\u201etext\u201c: \u201evalue\u201c}]"
        sanitised = raw.replace("\u201e", '"').replace("\u201c", '"')
        result = json.loads(sanitised)
        assert len(result) == 1
        assert result[0]["text"] == "value"

    def test_double_sanitisation_is_safe(self):
        """Sanitising already-clean JSON shouldn't break anything."""
        clean = '[{"text": "normal quotes"}]'
        sanitised = clean.replace("\u201e", '"').replace("\u201c", '"')
        result = json.loads(sanitised)
        assert result[0]["text"] == "normal quotes"


# ---------------------------------------------------------------------------
# Topic label round-trip
# ---------------------------------------------------------------------------


class TestTopicLabelRoundTrip:
    """Canonical ID prefix → topic → Icelandic label chain works."""

    def test_prefix_to_label(self):
        from generate_deliverables import _topic_label

        assert _topic_label("FIS-01") == "sjávarútvegur"
        assert _topic_label("SOV-03") == "fullveldi"
        assert _topic_label("EEA-12") == "ees/esb-löggjöf"
        assert _topic_label("DEM-07") == "lýðræði/ferli"

    def test_unknown_prefix_falls_back_to_other(self):
        from generate_deliverables import _topic_label

        # Unknown prefix maps to "other" → "annað"
        result = _topic_label("XYZ-01")
        assert result == "annað"

    def test_singleton_canonical_id(self):
        """Singleton IDs like 'FIS-Srad...' still extract the prefix."""
        from generate_deliverables import _topic_label

        assert _topic_label("FIS-Srad20260309T171000") == "sjávarútvegur"
