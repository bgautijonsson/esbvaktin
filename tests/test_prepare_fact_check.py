"""Tests for the lightweight fact-check context preparation."""

from pathlib import Path

from esbvaktin.pipeline.models import Claim, ClaimType, ClaimWithEvidence, EvidenceMatch
from esbvaktin.pipeline.prepare_fact_check import prepare_fact_check_context


def _make_claim(text: str = "Iceland would lose its fisheries", category: str = "fisheries"):
    return Claim(
        claim_text=text,
        original_quote=text,
        category=category,
        claim_type=ClaimType.LEGAL_ASSERTION,
        confidence=0.9,
    )


def _make_evidence(eid: str = "FISH-DATA-001", similarity: float = 0.85):
    return EvidenceMatch(
        evidence_id=eid,
        statement="Iceland controls its own fisheries under EEA.",
        similarity=similarity,
        source_name="Fiskistofa",
        caveats="Subject to EEA rules on market access.",
    )


def test_context_file_written(tmp_path: Path):
    cwe = ClaimWithEvidence(claim=_make_claim(), evidence=[_make_evidence()])
    result = prepare_fact_check_context([cwe], tmp_path)

    assert result.exists()
    assert result.name == "_context_fact_check.md"
    content = result.read_text()
    assert "Fact-Check Assessment" in content
    assert "Iceland would lose its fisheries" in content
    assert "FISH-DATA-001" in content
    assert "Fiskistofa" in content


def test_multiple_claims(tmp_path: Path):
    claims = [
        ClaimWithEvidence(claim=_make_claim("Claim A", "trade"), evidence=[_make_evidence("TRADE-DATA-001")]),
        ClaimWithEvidence(claim=_make_claim("Claim B", "housing"), evidence=[]),
    ]
    result = prepare_fact_check_context(claims, tmp_path)
    content = result.read_text()

    assert "Claim 1" in content
    assert "Claim 2" in content
    assert "TRADE-DATA-001" in content
    assert "No evidence found" in content


def test_caveats_included(tmp_path: Path):
    ev = _make_evidence()
    cwe = ClaimWithEvidence(claim=_make_claim(), evidence=[ev])
    result = prepare_fact_check_context([cwe], tmp_path)
    content = result.read_text()

    assert "Subject to EEA rules" in content


def test_verdict_options_listed(tmp_path: Path):
    cwe = ClaimWithEvidence(claim=_make_claim(), evidence=[_make_evidence()])
    result = prepare_fact_check_context([cwe], tmp_path)
    content = result.read_text()

    assert "supported" in content
    assert "unverifiable" in content
    assert "misleading" in content
