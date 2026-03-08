"""Tests for pipeline Pydantic models."""

from datetime import date

import pytest
from pydantic import ValidationError

from esbvaktin.pipeline.models import (
    AnalysisReport,
    Claim,
    ClaimAssessment,
    ClaimType,
    ClaimWithEvidence,
    EvidenceMatch,
    FramingAssessment,
    Omission,
    OmissionAnalysis,
    Verdict,
)


class TestClaim:
    def test_valid_claim(self):
        claim = Claim(
            claim_text="Iceland would lose its fishing waters",
            original_quote="Iceland would lose control of its fishing waters under the CFP",
            category="fisheries",
            claim_type=ClaimType.LEGAL_ASSERTION,
            confidence=0.9,
        )
        assert claim.category == "fisheries"
        assert claim.claim_type == ClaimType.LEGAL_ASSERTION

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            Claim(
                claim_text="test",
                original_quote="test",
                category="fisheries",
                claim_type="statistic",
                confidence=1.5,
            )

        with pytest.raises(ValidationError):
            Claim(
                claim_text="test",
                original_quote="test",
                category="fisheries",
                claim_type="statistic",
                confidence=-0.1,
            )

    def test_claim_type_enum(self):
        for ct in ["statistic", "legal_assertion", "comparison", "prediction", "opinion"]:
            claim = Claim(
                claim_text="test",
                original_quote="test",
                category="trade",
                claim_type=ct,
                confidence=0.5,
            )
            assert claim.claim_type == ct

    def test_invalid_claim_type(self):
        with pytest.raises(ValidationError):
            Claim(
                claim_text="test",
                original_quote="test",
                category="trade",
                claim_type="invalid_type",
                confidence=0.5,
            )


class TestClaimWithEvidence:
    def test_with_evidence(self):
        claim = Claim(
            claim_text="test",
            original_quote="test quote",
            category="fisheries",
            claim_type="statistic",
            confidence=0.9,
        )
        evidence = EvidenceMatch(
            evidence_id="FISH-DATA-001",
            statement="Iceland's fisheries contribute 25% of exports",
            similarity=0.85,
            source_name="Hagstofa Íslands",
            caveats="2024 figures",
        )
        cwe = ClaimWithEvidence(claim=claim, evidence=[evidence])
        assert len(cwe.evidence) == 1
        assert cwe.evidence[0].evidence_id == "FISH-DATA-001"

    def test_empty_evidence(self):
        claim = Claim(
            claim_text="test",
            original_quote="test",
            category="other",
            claim_type="opinion",
            confidence=0.5,
        )
        cwe = ClaimWithEvidence(claim=claim, evidence=[])
        assert len(cwe.evidence) == 0


class TestClaimAssessment:
    def test_valid_assessment(self):
        ca = ClaimAssessment(
            claim=Claim(
                claim_text="test",
                original_quote="test",
                category="fisheries",
                claim_type="statistic",
                confidence=0.9,
            ),
            verdict=Verdict.PARTIALLY_SUPPORTED,
            explanation="The claim is broadly correct but misses important nuances.",
            supporting_evidence=["FISH-DATA-001"],
            contradicting_evidence=["FISH-LEGAL-003"],
            missing_context="Modern accession negotiations allow sector protections.",
            confidence=0.8,
        )
        assert ca.verdict == Verdict.PARTIALLY_SUPPORTED
        assert len(ca.supporting_evidence) == 1

    def test_all_verdicts(self):
        for v in Verdict:
            ca = ClaimAssessment(
                claim=Claim(
                    claim_text="t",
                    original_quote="t",
                    category="trade",
                    claim_type="statistic",
                    confidence=0.5,
                ),
                verdict=v,
                explanation="Test.",
                confidence=0.5,
            )
            assert ca.verdict == v

    def test_missing_context_optional(self):
        ca = ClaimAssessment(
            claim=Claim(
                claim_text="t",
                original_quote="t",
                category="trade",
                claim_type="statistic",
                confidence=0.5,
            ),
            verdict="supported",
            explanation="Fully supported.",
            confidence=0.9,
        )
        assert ca.missing_context is None


class TestOmissionAnalysis:
    def test_valid_omission_analysis(self):
        oa = OmissionAnalysis(
            omissions=[
                Omission(
                    topic="fisheries",
                    description="Article omits quota concentration issues",
                    relevant_evidence=["FISH-DATA-005"],
                ),
            ],
            framing_assessment=FramingAssessment.LEANS_ANTI_EU,
            overall_completeness=0.4,
        )
        assert len(oa.omissions) == 1
        assert oa.framing_assessment == FramingAssessment.LEANS_ANTI_EU

    def test_completeness_bounds(self):
        with pytest.raises(ValidationError):
            OmissionAnalysis(
                framing_assessment="balanced",
                overall_completeness=1.5,
            )

    def test_empty_omissions(self):
        oa = OmissionAnalysis(
            framing_assessment="balanced",
            overall_completeness=0.9,
        )
        assert len(oa.omissions) == 0


class TestAnalysisReport:
    def test_minimal_report(self):
        report = AnalysisReport(
            summary="Test summary",
            claims=[],
            omissions=OmissionAnalysis(
                framing_assessment="balanced",
                overall_completeness=0.5,
            ),
        )
        assert report.article_title is None
        assert report.analysis_date == date.today()
        assert report.evidence_used == []

    def test_full_report(self):
        report = AnalysisReport(
            article_title="Test Article",
            article_source="Test Source",
            article_date=date(2026, 2, 15),
            summary="A test analysis",
            claims=[
                ClaimAssessment(
                    claim=Claim(
                        claim_text="t",
                        original_quote="t",
                        category="fisheries",
                        claim_type="statistic",
                        confidence=0.9,
                    ),
                    verdict="supported",
                    explanation="Verified.",
                    supporting_evidence=["FISH-DATA-001"],
                    confidence=0.9,
                ),
            ],
            omissions=OmissionAnalysis(
                framing_assessment="balanced",
                overall_completeness=0.8,
            ),
            evidence_used=["FISH-DATA-001"],
            report_text_en="# Report",
            report_text_is="# Skýrsla",
        )
        assert report.article_title == "Test Article"
        assert len(report.claims) == 1
        assert report.report_text_is == "# Skýrsla"
