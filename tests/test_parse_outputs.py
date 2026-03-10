"""Tests for pipeline output parsers."""

from pathlib import Path

import pytest

from esbvaktin.pipeline.parse_outputs import (
    _extract_json,
    _sanitise_icelandic_quotes,
    parse_assessments,
    parse_claims,
    parse_omissions,
    parse_translation,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseClaims:
    def test_parse_sample_claims(self):
        claims = parse_claims(FIXTURES / "sample_claims.json")
        assert len(claims) == 3
        assert claims[0].category == "fisheries"
        assert claims[0].claim_type == "legal_assertion"
        assert claims[1].claim_type == "statistic"
        assert 0 <= claims[2].confidence <= 1

    def test_parse_claims_preserves_quotes(self):
        claims = parse_claims(FIXTURES / "sample_claims.json")
        assert "Brussels bureaucrats" in claims[0].original_quote

    def test_parse_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all")
        with pytest.raises(Exception):
            parse_claims(bad_file)

    def test_parse_raw_json_without_code_block(self, tmp_path):
        raw_file = tmp_path / "raw.json"
        raw_file.write_text("""[
  {
    "claim_text": "Test claim",
    "original_quote": "Test quote",
    "category": "trade",
    "claim_type": "statistic",
    "confidence": 0.8
  }
]""")
        claims = parse_claims(raw_file)
        assert len(claims) == 1
        assert claims[0].claim_text == "Test claim"


class TestParseAssessments:
    def test_parse_sample_assessments(self):
        assessments = parse_assessments(FIXTURES / "sample_assessments.json")
        assert len(assessments) == 3
        assert assessments[0].verdict == "partially_supported"
        assert assessments[1].verdict == "misleading"
        assert assessments[2].verdict == "unsupported"

    def test_assessment_evidence_ids(self):
        assessments = parse_assessments(FIXTURES / "sample_assessments.json")
        assert "FISH-LEGAL-001" in assessments[0].supporting_evidence
        assert "FISH-LEGAL-003" in assessments[0].contradicting_evidence

    def test_assessment_missing_context(self):
        assessments = parse_assessments(FIXTURES / "sample_assessments.json")
        assert assessments[0].missing_context is not None
        assert assessments[2].missing_context is None


class TestParseOmissions:
    def test_parse_sample_omissions(self):
        omissions = parse_omissions(FIXTURES / "sample_omissions.json")
        assert len(omissions.omissions) == 3
        assert omissions.framing_assessment == "leans_anti_eu"
        assert omissions.overall_completeness == 0.35

    def test_omission_evidence_ids(self):
        omissions = parse_omissions(FIXTURES / "sample_omissions.json")
        assert "TRADE-DATA-001" in omissions.omissions[1].relevant_evidence


class TestIcelandicQuoteSanitisation:
    """Tests for Icelandic/smart quote handling in JSON parsing."""

    def test_sanitise_low9_and_left_double(self):
        """„ (U+201E) and " (U+201C) — the standard Icelandic pair."""
        text = '"claim_text": "\u201eÞetta er rangt\u201c"'
        result = _sanitise_icelandic_quotes(text)
        assert "\u201e" not in result
        assert "\u201c" not in result
        assert '\\"' in result

    def test_sanitise_right_double(self):
        """\u201d (U+201D) — right double quotation mark."""
        text = '"value": "said \u201dhello\u201d"'
        result = _sanitise_icelandic_quotes(text)
        assert "\u201d" not in result

    def test_parse_claims_with_icelandic_quotes(self, tmp_path):
        """Full roundtrip: claims JSON with Icelandic quotes parses correctly."""
        # This simulates LLM output where Icelandic quotes appear in values
        claims_file = tmp_path / "claims.json"
        # Use raw string with actual Unicode characters
        claims_file.write_text(
            '[\n'
            '  {\n'
            '    "claim_text": "R\u00e1\u00f0herra sag\u00f0i \u201e\u00feetta s\u00e9 r\u00e9tt\u201c",\n'
            '    "original_quote": "R\u00e1\u00f0herra sag\u00f0i \u201e\u00feetta s\u00e9 r\u00e9tt\u201c",\n'
            '    "category": "sovereignty",\n'
            '    "claim_type": "opinion",\n'
            '    "confidence": 0.8\n'
            '  }\n'
            ']',
            encoding="utf-8",
        )
        claims = parse_claims(claims_file)
        assert len(claims) == 1
        assert "ráðherra" in claims[0].claim_text.lower()

    def test_extract_json_valid_unicode_quotes_preserved(self):
        """Valid JSON with Unicode quotes is returned as-is (no corruption)."""
        text = '```json\n{"key": "\u201eval\u201c"}\n```'
        result = _extract_json(text)
        # Unicode quotes are valid JSON — should parse without sanitisation
        import json
        parsed = json.loads(result)
        assert parsed["key"] == "\u201eval\u201c"

    def test_extract_json_sanitises_broken_quotes(self):
        """Broken JSON with „...ASCII-" pairs is sanitised to parse."""
        # „ followed by ASCII " (real delimiter) — this WOULD break json.loads
        text = '```json\n[{"key": "\u201eval""}]\n```'
        result = _extract_json(text)
        import json
        parsed = json.loads(result)
        assert len(parsed) == 1


class TestParseTranslation:
    def test_parse_plain_text(self, tmp_path):
        f = tmp_path / "translation.md"
        f.write_text("# Greining\n\nÞetta er prófun.")
        result = parse_translation(f)
        assert "Greining" in result
        assert "prófun" in result

    def test_parse_wrapped_in_code_block(self, tmp_path):
        f = tmp_path / "translation.md"
        f.write_text("```markdown\n# Greining\n\nÞetta er prófun.\n```")
        result = parse_translation(f)
        assert result.startswith("# Greining")
        assert "prófun" in result

    def test_strips_whitespace(self, tmp_path):
        f = tmp_path / "translation.md"
        f.write_text("\n\n  Halló  \n\n")
        result = parse_translation(f)
        assert result == "Halló"
