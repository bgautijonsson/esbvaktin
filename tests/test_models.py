"""Tests for evidence entry and claim bank Pydantic models."""

from datetime import date

import pytest

from esbvaktin.claim_bank.models import CanonicalClaim
from esbvaktin.ground_truth.models import (
    Confidence,
    Domain,
    EvidenceEntry,
    SourceType,
)
from esbvaktin.pipeline.models import Claim, ClaimType, EpistemicType


def test_valid_evidence_entry():
    entry = EvidenceEntry(
        evidence_id="FISH-DATA-001",
        domain=Domain.ECONOMIC,
        topic="fisheries",
        subtopic="catch_volume",
        statement="Iceland's total marine catch was 1.1 million tonnes.",
        source_name="Hagstofa Íslands",
        source_type=SourceType.OFFICIAL_STATISTICS,
    )
    assert entry.evidence_id == "FISH-DATA-001"
    assert entry.domain == Domain.ECONOMIC
    assert entry.confidence == Confidence.HIGH
    assert entry.last_verified == date.today()
    assert entry.related_entries == []


def test_invalid_evidence_id_pattern():
    with pytest.raises(ValueError):
        EvidenceEntry(
            evidence_id="bad-id",
            domain=Domain.ECONOMIC,
            topic="fisheries",
            statement="Test statement",
            source_name="Test",
            source_type=SourceType.OFFICIAL_STATISTICS,
        )


def test_evidence_id_patterns():
    valid_ids = ["FISH-DATA-001", "EEA-LEGAL-003", "TRADE-COMP-012", "SOV-HIST-100"]
    for eid in valid_ids:
        entry = EvidenceEntry(
            evidence_id=eid,
            domain=Domain.LEGAL,
            topic="test",
            statement="Test",
            source_name="Test",
            source_type=SourceType.LEGAL_TEXT,
        )
        assert entry.evidence_id == eid


def test_all_domains():
    for domain in Domain:
        entry = EvidenceEntry(
            evidence_id="TEST-DATA-001",
            domain=domain,
            topic="test",
            statement="Test",
            source_name="Test",
            source_type=SourceType.OFFICIAL_STATISTICS,
        )
        assert entry.domain == domain


def test_optional_fields():
    entry = EvidenceEntry(
        evidence_id="TEST-DATA-001",
        domain=Domain.ECONOMIC,
        topic="test",
        statement="Test",
        source_name="Test",
        source_type=SourceType.OFFICIAL_STATISTICS,
    )
    assert entry.subtopic is None
    assert entry.source_url is None
    assert entry.source_date is None
    assert entry.caveats is None


def test_json_serialisation():
    entry = EvidenceEntry(
        evidence_id="FISH-DATA-001",
        domain=Domain.ECONOMIC,
        topic="fisheries",
        statement="Test statement",
        source_name="Test",
        source_type=SourceType.OFFICIAL_STATISTICS,
        caveats="Some caveat",
        related_entries=["FISH-DATA-002"],
    )
    data = entry.model_dump()
    assert data["evidence_id"] == "FISH-DATA-001"
    assert data["domain"] == "economic"
    assert data["related_entries"] == ["FISH-DATA-002"]

    # Round-trip
    entry2 = EvidenceEntry(**data)
    assert entry2 == entry


# ── CanonicalClaim tests ─────────────────────────────────────────────


def _make_claim(**overrides) -> CanonicalClaim:
    """Helper: minimal valid CanonicalClaim with optional overrides."""
    defaults = {
        "claim_slug": "test-claim-slug",
        "canonical_text_is": "Prófunarfullyrðing.",
        "category": "trade",
        "claim_type": "statistic",
        "verdict": "supported",
        "explanation_is": "Stutt skýring.",
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return CanonicalClaim(**defaults)


def test_canonical_claim_defaults_to_published():
    """New claims should be published by default (auto-publish)."""
    claim = _make_claim()
    assert claim.published is True


def test_canonical_claim_explicit_unpublished():
    """Explicitly setting published=False should be honoured."""
    claim = _make_claim(published=False)
    assert claim.published is False


def test_canonical_claim_required_fields():
    """CanonicalClaim requires slug, text, category, type, verdict, explanation, confidence."""
    with pytest.raises(ValueError):
        CanonicalClaim(claim_slug="test")  # missing all other required fields


def test_canonical_claim_slug_pattern():
    """Slugs must be lowercase alphanumeric with hyphens."""
    with pytest.raises(ValueError):
        _make_claim(claim_slug="UPPER-CASE")
    with pytest.raises(ValueError):
        _make_claim(claim_slug="has spaces")


def test_canonical_claim_confidence_bounds():
    """Confidence must be between 0 and 1."""
    with pytest.raises(ValueError):
        _make_claim(confidence=1.5)
    with pytest.raises(ValueError):
        _make_claim(confidence=-0.1)


def test_canonical_claim_evidence_defaults():
    """Evidence lists default to empty."""
    claim = _make_claim()
    assert claim.supporting_evidence == []
    assert claim.contradicting_evidence == []


# ── EpistemicType tests ───────────────────────────────────────────────


class TestEpistemicType:
    def test_enum_values(self):
        """EpistemicType should have exactly these four values."""
        assert EpistemicType.FACTUAL == "factual"
        assert EpistemicType.HEARSAY == "hearsay"
        assert EpistemicType.COUNTERFACTUAL == "counterfactual"
        assert EpistemicType.PREDICTION == "prediction"

    def test_claim_type_forecast_replaces_prediction(self):
        """ClaimType should use FORECAST, not PREDICTION."""
        assert ClaimType.FORECAST == "forecast"
        assert not hasattr(ClaimType, "PREDICTION")

    def test_claim_has_epistemic_type_field(self):
        """Claim can be constructed with an explicit epistemic_type."""
        claim = Claim(
            claim_text="Ísland myndi ganga í ESB",
            original_quote="Ísland myndi ganga í ESB",
            category="sovereignty",
            claim_type=ClaimType.LEGAL_ASSERTION,
            confidence=0.8,
            epistemic_type=EpistemicType.COUNTERFACTUAL,
        )
        assert claim.epistemic_type == EpistemicType.COUNTERFACTUAL

    def test_claim_epistemic_type_defaults_to_factual(self):
        """Claim without epistemic_type should default to factual."""
        claim = Claim(
            claim_text="Ísland er í EES",
            original_quote="Ísland er í EES",
            category="eea_eu_law",
            claim_type=ClaimType.LEGAL_ASSERTION,
            confidence=0.9,
        )
        assert claim.epistemic_type == EpistemicType.FACTUAL
