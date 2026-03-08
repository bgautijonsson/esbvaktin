"""Tests for evidence entry Pydantic models."""

import pytest
from datetime import date

from esbvaktin.ground_truth.models import (
    Confidence,
    Domain,
    EvidenceEntry,
    SourceType,
)


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
