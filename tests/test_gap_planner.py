"""Tests for the Verification Gap Planner module."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from esbvaktin.gap_planner.models import EvidenceGap, GapCategory, ResearchTask, ResearchType
from esbvaktin.gap_planner.operations import categorise_gap, identify_gaps, summarise_gaps
from esbvaktin.gap_planner.prepare_context import prepare_gap_context
from esbvaktin.pipeline.models import (
    AnalysisReport,
    Claim,
    ClaimAssessment,
    ClaimType,
    FramingAssessment,
    OmissionAnalysis,
    Verdict,
)


def _make_assessment(
    claim_text: str,
    verdict: Verdict,
    explanation: str,
    missing_context: str | None = None,
    category: str = "fisheries",
) -> ClaimAssessment:
    return ClaimAssessment(
        claim=Claim(
            claim_text=claim_text,
            original_quote=claim_text,
            category=category,
            claim_type=ClaimType.STATISTIC,
            confidence=0.9,
        ),
        verdict=verdict,
        explanation=explanation,
        supporting_evidence=["FISH-DATA-001"] if verdict != Verdict.UNVERIFIABLE else [],
        contradicting_evidence=[],
        missing_context=missing_context,
        confidence=0.8 if verdict != Verdict.UNVERIFIABLE else 0.4,
    )


def _make_report(claims: list[ClaimAssessment]) -> AnalysisReport:
    return AnalysisReport(
        summary="Test",
        claims=claims,
        omissions=OmissionAnalysis(
            omissions=[],
            framing_assessment=FramingAssessment.BALANCED,
            overall_completeness=0.5,
        ),
    )


class TestCategoriseGap:
    """Tests for gap classification heuristics."""

    def test_missing_data(self):
        result = categorise_gap(
            "No data or statistics available for this specific claim.",
        )
        assert result == GapCategory.MISSING_DATA

    def test_missing_data_icelandic(self):
        result = categorise_gap(
            "Engar heimildir í staðreyndagrunni gefa upp þessa tölu.",
        )
        assert result == GapCategory.MISSING_DATA

    def test_speculative(self):
        result = categorise_gap(
            "The outcome would depend entirely on accession negotiations.",
        )
        assert result == GapCategory.SPECULATIVE

    def test_recent_event(self):
        result = categorise_gap(
            "Sjálfstæðisflokkurinn lagði fram lagafrumvarp um þetta 2026.",
        )
        assert result == GapCategory.RECENT_EVENT

    def test_recent_event_english(self):
        result = categorise_gap(
            "A bill was recently introduced in parliament about this.",
        )
        assert result == GapCategory.RECENT_EVENT

    def test_source_needed(self):
        result = categorise_gap(
            "This claim may well be accurate but cannot be verified with available evidence.",
        )
        assert result == GapCategory.SOURCE_NEEDED

    def test_contradictory(self):
        result = categorise_gap(
            "Conflicting evidence from multiple sources makes assessment difficult.",
        )
        assert result == GapCategory.CONTRADICTORY

    def test_default_fallback(self):
        result = categorise_gap("Some generic explanation without clear signals.")
        assert result == GapCategory.SOURCE_NEEDED

    def test_uses_missing_context(self):
        result = categorise_gap(
            "Not enough information.",
            missing_context="Engar heimildir um þetta."
        )
        assert result == GapCategory.MISSING_DATA


class TestIdentifyGaps:
    """Tests for gap identification from analysis reports."""

    def test_finds_unverifiable(self):
        claims = [
            _make_assessment("Supported claim", Verdict.SUPPORTED, "Good evidence"),
            _make_assessment("Unverifiable claim", Verdict.UNVERIFIABLE, "No data available"),
            _make_assessment("Another supported", Verdict.PARTIALLY_SUPPORTED, "OK"),
        ]
        report = _make_report(claims)
        gaps = identify_gaps(report)

        assert len(gaps) == 1
        assert gaps[0].claim_text == "Unverifiable claim"
        assert gaps[0].claim_index == 1

    def test_no_gaps(self):
        claims = [
            _make_assessment("Supported", Verdict.SUPPORTED, "Evidence confirms"),
        ]
        report = _make_report(claims)
        gaps = identify_gaps(report)

        assert len(gaps) == 0

    def test_multiple_gaps(self):
        claims = [
            _make_assessment("Gap 1", Verdict.UNVERIFIABLE, "No evidence"),
            _make_assessment("OK", Verdict.SUPPORTED, "Fine"),
            _make_assessment("Gap 2", Verdict.UNVERIFIABLE, "Would depend on negotiations"),
        ]
        report = _make_report(claims)
        gaps = identify_gaps(report)

        assert len(gaps) == 2
        assert gaps[0].claim_index == 0
        assert gaps[1].claim_index == 2

    def test_gap_category_assigned(self):
        claims = [
            _make_assessment(
                "Aflaheimild gæti minnkað um 30%",
                Verdict.UNVERIFIABLE,
                "Engar heimildir í staðreyndagrunni gefa upp þessa tilteknu tölu.",
            ),
        ]
        report = _make_report(claims)
        gaps = identify_gaps(report)

        assert gaps[0].gap_category == GapCategory.MISSING_DATA


class TestSummariseGaps:
    """Tests for gap summary statistics."""

    def test_counts_by_category(self):
        gaps = [
            EvidenceGap(
                claim_index=0, claim_text="A", category="fisheries",
                explanation="No data", gap_category=GapCategory.MISSING_DATA,
            ),
            EvidenceGap(
                claim_index=1, claim_text="B", category="trade",
                explanation="Speculative", gap_category=GapCategory.SPECULATIVE,
            ),
            EvidenceGap(
                claim_index=2, claim_text="C", category="fisheries",
                explanation="No data", gap_category=GapCategory.MISSING_DATA,
            ),
        ]
        summary = summarise_gaps(gaps)

        assert summary["missing_data"] == 2
        assert summary["speculative"] == 1


class TestPrepareGapContext:
    """Tests for gap analysis context generation."""

    def test_context_file_created(self):
        gaps = [
            EvidenceGap(
                claim_index=0,
                claim_text="Aflaheimild gæti minnkað um 30%",
                original_quote="aflaheimild gæti minnkað",
                category="fisheries",
                explanation="Engar heimildir",
                gap_category=GapCategory.MISSING_DATA,
                evidence_ids_consulted=["FISH-DATA-001"],
            ),
        ]

        with TemporaryDirectory() as tmpdir:
            path = prepare_gap_context(gaps, Path(tmpdir))
            assert path.exists()
            content = path.read_text()

            assert "Rannsóknaráætlun" in content
            assert "1 eyður greindar" in content
            assert "FISH-DATA-001" in content
            assert "research_type" in content  # JSON schema present
