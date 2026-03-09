"""Tests for report assembly."""

from datetime import date

from esbvaktin.pipeline.assemble_report import (
    _collect_evidence_ids,
    assemble_report,
    render_report_en,
)
from esbvaktin.pipeline.models import (
    Claim,
    ClaimAssessment,
    ClaimType,
    FramingAssessment,
    Omission,
    OmissionAnalysis,
    Verdict,
)


def _make_claim(text: str = "test claim", category: str = "fisheries") -> Claim:
    return Claim(
        claim_text=text,
        original_quote=f"quote: {text}",
        category=category,
        claim_type=ClaimType.STATISTIC,
        confidence=0.9,
    )


def _make_assessment(
    verdict: Verdict = Verdict.SUPPORTED,
    supporting: list[str] | None = None,
    contradicting: list[str] | None = None,
) -> ClaimAssessment:
    return ClaimAssessment(
        claim=_make_claim(),
        verdict=verdict,
        explanation="Test explanation.",
        supporting_evidence=supporting or [],
        contradicting_evidence=contradicting or [],
        confidence=0.8,
    )


def _make_omissions(
    evidence_ids: list[str] | None = None,
    framing: FramingAssessment = FramingAssessment.BALANCED,
) -> OmissionAnalysis:
    omissions = []
    if evidence_ids:
        omissions.append(
            Omission(
                topic="fisheries",
                description="Missing context",
                relevant_evidence=evidence_ids,
            )
        )
    return OmissionAnalysis(
        omissions=omissions,
        framing_assessment=framing,
        overall_completeness=0.5,
    )


class TestCollectEvidenceIds:
    def test_collects_from_claims_and_omissions(self):
        claims = [
            _make_assessment(supporting=["FISH-DATA-001"], contradicting=["FISH-LEGAL-002"]),
            _make_assessment(supporting=["TRADE-DATA-001"]),
        ]
        omissions = _make_omissions(evidence_ids=["EEA-LEGAL-001"])
        ids = _collect_evidence_ids(claims, omissions)
        assert ids == ["EEA-LEGAL-001", "FISH-DATA-001", "FISH-LEGAL-002", "TRADE-DATA-001"]

    def test_deduplicates(self):
        claims = [
            _make_assessment(supporting=["FISH-DATA-001"]),
            _make_assessment(contradicting=["FISH-DATA-001"]),
        ]
        omissions = _make_omissions(evidence_ids=["FISH-DATA-001"])
        ids = _collect_evidence_ids(claims, omissions)
        assert ids == ["FISH-DATA-001"]

    def test_empty_inputs(self):
        ids = _collect_evidence_ids([], _make_omissions())
        assert ids == []


class TestRenderReportEn:
    def test_contains_title(self):
        report = render_report_en(
            claims=[_make_assessment()],
            omissions=_make_omissions(),
            summary="Test summary",
            article_title="Test Article",
        )
        assert "# Test Article" in report

    def test_contains_summary(self):
        report = render_report_en(
            claims=[],
            omissions=_make_omissions(),
            summary="This is the summary.",
        )
        assert "This is the summary." in report

    def test_contains_verdict_section(self):
        report = render_report_en(
            claims=[
                _make_assessment(verdict=Verdict.SUPPORTED),
                _make_assessment(verdict=Verdict.MISLEADING),
            ],
            omissions=_make_omissions(),
            summary="Test",
        )
        assert "supported" in report.lower()
        assert "misleading" in report.lower()

    def test_contains_framing_assessment(self):
        report = render_report_en(
            claims=[],
            omissions=_make_omissions(framing=FramingAssessment.LEANS_ANTI_EU),
            summary="Test",
        )
        assert "Leans anti-EU" in report

    def test_contains_footer(self):
        report = render_report_en(
            claims=[],
            omissions=_make_omissions(),
            summary="Test",
        )
        assert "ESBvaktin.is" in report


class TestAssembleReport:
    def test_assembles_complete_report_icelandic(self):
        """Default language is Icelandic — generates report_text_is."""
        claims = [_make_assessment(supporting=["FISH-DATA-001"])]
        omissions = _make_omissions(evidence_ids=["EEA-LEGAL-001"])
        report = assemble_report(
            claims=claims,
            omissions=omissions,
            summary="A balanced analysis.",
            article_title="Test",
            article_source="Test Source",
            article_date=date(2026, 2, 15),
        )
        assert report.article_title == "Test"
        assert report.analysis_date == date.today()
        assert "FISH-DATA-001" in report.evidence_used
        assert "EEA-LEGAL-001" in report.evidence_used
        assert report.report_text_is != ""
        assert report.language == "is"

    def test_assembles_complete_report_english(self):
        """Explicit language='en' generates report_text_en."""
        claims = [_make_assessment(supporting=["FISH-DATA-001"])]
        omissions = _make_omissions(evidence_ids=["EEA-LEGAL-001"])
        report = assemble_report(
            claims=claims,
            omissions=omissions,
            summary="A balanced analysis.",
            article_title="Test",
            language="en",
        )
        assert report.report_text_en != ""
        assert report.report_text_is == ""

    def test_assembles_minimal_report(self):
        report = assemble_report(
            claims=[],
            omissions=_make_omissions(),
            summary="No claims found.",
        )
        assert report.article_title is None
        assert report.evidence_used == []
        # Default is Icelandic — summary appears in Icelandic report
        assert "No claims found." in report.report_text_is
