"""Tests for pipeline output parsers."""

from pathlib import Path

import pytest

from esbvaktin.pipeline.parse_outputs import (
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
