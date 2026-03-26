"""Tests for Icelandic-first pipeline components."""

from pathlib import Path
from tempfile import TemporaryDirectory

from esbvaktin.pipeline.assemble_report import (
    assemble_report,
    render_report_is,
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
from esbvaktin.pipeline.prepare_context import (
    prepare_assessment_context,
    prepare_extraction_context,
    prepare_omission_context,
    prepare_translation_context,
)


def _sample_claims() -> list[ClaimAssessment]:
    """Create sample claims for testing."""
    return [
        ClaimAssessment(
            claim=Claim(
                claim_text="Ísland myndi missa yfirráð yfir fiskveiðum",
                original_quote="Ísland myndi missa yfirráð yfir fiskveiðum sínum",
                category="fisheries",
                claim_type=ClaimType.LEGAL_ASSERTION,
                confidence=0.9,
            ),
            verdict=Verdict.PARTIALLY_SUPPORTED,
            explanation="FISH-LEGAL-002 staðfestir að sjávarútvegsstefna ESB myndi ná til íslenskra hafsvæða.",
            supporting_evidence=["FISH-LEGAL-002"],
            contradicting_evidence=[],
            missing_context="Ísland myndi halda fullveldi samkvæmt UNCLOS.",
            confidence=0.8,
        ),
        ClaimAssessment(
            claim=Claim(
                claim_text="Aflaheimild gæti minnkað um 30%",
                original_quote="aflaheimild gæti minnkað um allt að 30 prósent",
                category="fisheries",
                claim_type=ClaimType.FORECAST,
                confidence=0.7,
            ),
            verdict=Verdict.UNVERIFIABLE,
            explanation="Engar heimildir í staðreyndagrunni gefa upp þessa tilteknu tölu.",
            supporting_evidence=[],
            contradicting_evidence=[],
            missing_context="30% talan á sér enga þekkta heimild.",
            confidence=0.4,
        ),
    ]


def _sample_omissions() -> OmissionAnalysis:
    return OmissionAnalysis(
        omissions=[
            Omission(
                topic="fisheries",
                description="Greinin nefnir ekki aðlögunartímabil sem Ísland gæti samið um.",
                relevant_evidence=["FISH-LEGAL-003"],
            ),
        ],
        framing_assessment=FramingAssessment.LEANS_ANTI_EU,
        overall_completeness=0.35,
    )


class TestRenderReportIs:
    """Tests for native Icelandic report rendering."""

    def test_basic_structure(self):
        claims = _sample_claims()
        omissions = _sample_omissions()
        report = render_report_is(claims, omissions, "Yfirlit hér")

        assert "# " in report  # Has heading
        assert "## Yfirlit" in report
        assert "## Niðurstöður mats" in report
        assert "## Fullyrðingamat" in report
        assert "## Eyður og sjónarhorn" in report

    def test_icelandic_verdict_labels(self):
        claims = _sample_claims()
        omissions = _sample_omissions()
        report = render_report_is(claims, omissions, "Test")

        assert "Stutt að hluta" in report
        assert "Ekki hægt að sannreyna" in report

    def test_icelandic_framing_label(self):
        claims = _sample_claims()
        omissions = _sample_omissions()
        report = render_report_is(claims, omissions, "Test")

        assert "Hallar á ESB-neikvæða hlið" in report

    def test_footer(self):
        claims = _sample_claims()
        omissions = _sample_omissions()
        report = render_report_is(claims, omissions, "Test")

        assert "ESBvaktin.is" in report
        assert "óháð" in report

    def test_evidence_ids_preserved(self):
        claims = _sample_claims()
        omissions = _sample_omissions()
        report = render_report_is(claims, omissions, "Test")

        assert "FISH-LEGAL-002" in report
        assert "FISH-LEGAL-003" in report


class TestAssembleReport:
    """Tests for report assembly with language parameter."""

    def test_icelandic_default(self):
        claims = _sample_claims()
        omissions = _sample_omissions()
        report = assemble_report(claims, omissions, "Yfirlit")

        assert report.language == "is"
        assert report.report_text_is != ""
        assert report.report_text_en == ""

    def test_english_explicit(self):
        claims = _sample_claims()
        omissions = _sample_omissions()
        report = assemble_report(claims, omissions, "Summary", language="en")

        assert report.language == "en"
        assert report.report_text_en != ""
        assert report.report_text_is == ""

    def test_evidence_collected(self):
        claims = _sample_claims()
        omissions = _sample_omissions()
        report = assemble_report(claims, omissions, "Test")

        assert "FISH-LEGAL-002" in report.evidence_used
        assert "FISH-LEGAL-003" in report.evidence_used


class TestContextTemplates:
    """Tests for Icelandic-first context templates."""

    def test_extraction_context_icelandic(self):
        with TemporaryDirectory() as tmpdir:
            path = prepare_extraction_context("Grein um ESB-aðild", Path(tmpdir), language="is")
            content = path.read_text()

            assert "Fullyrðingagreining" in content
            assert "claim_text" in content  # JSON keys stay English
            assert "íslensku" in content.lower() or "íslensku" in content

    def test_extraction_context_english(self):
        with TemporaryDirectory() as tmpdir:
            path = prepare_extraction_context("Article about EU", Path(tmpdir), language="en")
            content = path.read_text()

            assert "Claim Extraction Task" in content
            assert "claim_text" in content

    def test_assessment_context_icelandic(self):
        from esbvaktin.pipeline.models import ClaimWithEvidence, EvidenceMatch

        cwe = ClaimWithEvidence(
            claim=Claim(
                claim_text="Test claim",
                original_quote="Test quote",
                category="fisheries",
                claim_type=ClaimType.STATISTIC,
                confidence=0.9,
            ),
            evidence=[
                EvidenceMatch(
                    evidence_id="FISH-DATA-001",
                    statement="Test evidence",
                    similarity=0.85,
                    source_name="Test source",
                    caveats=None,
                )
            ],
        )

        with TemporaryDirectory() as tmpdir:
            path = prepare_assessment_context([cwe], Path(tmpdir), language="is")
            content = path.read_text()

            assert "Fullyrðingamat" in content
            assert "Meginreglur" in content
            assert "FISH-DATA-001" in content  # Evidence IDs preserved

    def test_omission_context_icelandic(self):
        from esbvaktin.pipeline.models import ClaimWithEvidence

        cwe = ClaimWithEvidence(
            claim=Claim(
                claim_text="Test",
                original_quote="Test",
                category="fisheries",
                claim_type=ClaimType.STATISTIC,
                confidence=0.9,
            ),
            evidence=[],
        )

        with TemporaryDirectory() as tmpdir:
            path = prepare_omission_context("Article text", [cwe], Path(tmpdir), language="is")
            content = path.read_text()

            assert "Greining á því sem vantar" in content
            assert "Meginreglur" in content

    def test_translation_context_is_to_en(self):
        with TemporaryDirectory() as tmpdir:
            path = prepare_translation_context(
                "# Íslensk skýrsla", Path(tmpdir), direction="is_to_en"
            )
            content = path.read_text()

            assert "Icelandic → English" in content

    def test_translation_context_en_to_is(self):
        with TemporaryDirectory() as tmpdir:
            path = prepare_translation_context(
                "# English report", Path(tmpdir), direction="en_to_is"
            )
            content = path.read_text()

            assert "English → Icelandic" in content
