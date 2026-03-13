"""Tests for evidence retrieval.

These tests require a running PostgreSQL database with seeded evidence.
Run: docker compose up -d && uv run python scripts/seed_evidence.py insert data/seeds/
"""

import os

import pytest

from esbvaktin.pipeline.models import KNOWN_TOPICS, Claim, ClaimType
from esbvaktin.pipeline.retrieve_evidence import (
    retrieve_evidence_for_claim,
    retrieve_evidence_for_claims,
)
from tests.conftest import requires_embeddings

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set — requires running PostgreSQL",
    ),
    requires_embeddings,
]


@pytest.fixture
def fisheries_claim() -> Claim:
    return Claim(
        claim_text=(
            "Iceland would lose control of its fishing waters"
            " under the Common Fisheries Policy"
        ),
        original_quote="The CFP would force Iceland to hand over its fishing waters",
        category="fisheries",
        claim_type=ClaimType.LEGAL_ASSERTION,
        confidence=0.9,
    )


@pytest.fixture
def trade_claim() -> Claim:
    return Claim(
        claim_text="Food prices in Iceland are 50-70% higher than the EU average",
        original_quote="consumers paying 50-70% more than the EU average for basic groceries",
        category="trade",
        claim_type=ClaimType.STATISTIC,
        confidence=0.85,
    )


@pytest.fixture
def unknown_topic_claim() -> Claim:
    return Claim(
        claim_text="EU membership would improve Iceland's healthcare system",
        original_quote="EU membership would improve Iceland's healthcare system",
        category="healthcare",
        claim_type=ClaimType.PREDICTION,
        confidence=0.6,
    )


class TestRetrieveEvidenceForClaim:
    def test_returns_evidence_for_fisheries(self, fisheries_claim):
        result = retrieve_evidence_for_claim(fisheries_claim, top_k=5)
        assert len(result.evidence) > 0
        assert len(result.evidence) <= 5
        assert result.claim == fisheries_claim

    def test_evidence_sorted_by_similarity(self, fisheries_claim):
        result = retrieve_evidence_for_claim(fisheries_claim, top_k=5)
        similarities = [e.similarity for e in result.evidence]
        assert similarities == sorted(similarities, reverse=True)

    def test_returns_evidence_for_trade(self, trade_claim):
        result = retrieve_evidence_for_claim(trade_claim, top_k=5)
        assert len(result.evidence) > 0

    def test_unknown_topic_still_returns_evidence(self, unknown_topic_claim):
        """Claims with unknown categories should still get unfiltered results."""
        result = retrieve_evidence_for_claim(unknown_topic_claim, top_k=5)
        # Should still find something via unfiltered search
        assert result.evidence is not None

    def test_evidence_has_required_fields(self, fisheries_claim):
        result = retrieve_evidence_for_claim(fisheries_claim, top_k=3)
        for ev in result.evidence:
            assert ev.evidence_id
            assert ev.statement
            assert ev.similarity > 0
            assert ev.source_name


class TestRetrieveEvidenceForClaims:
    def test_batch_retrieval(self, fisheries_claim, trade_claim):
        results, bank_matches = retrieve_evidence_for_claims(
            [fisheries_claim, trade_claim], top_k=3
        )
        assert len(results) == 2
        assert results[0].claim == fisheries_claim
        assert results[1].claim == trade_claim
        assert isinstance(bank_matches, dict)

    def test_empty_list(self):
        results, bank_matches = retrieve_evidence_for_claims([], top_k=5)
        assert results == []
        assert bank_matches == {}


class TestKnownTopics:
    def test_known_topics_exist(self):
        assert "fisheries" in KNOWN_TOPICS
        assert "trade" in KNOWN_TOPICS
        assert "sovereignty" in KNOWN_TOPICS
        assert "eea_eu_law" in KNOWN_TOPICS
        assert "agriculture" in KNOWN_TOPICS

    def test_healthcare_not_known(self):
        assert "healthcare" not in KNOWN_TOPICS
