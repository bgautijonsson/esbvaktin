"""Tests for the entity name matcher — matching cascade and confidence scoring."""

import pytest

from esbvaktin.entity_registry.matcher import (
    MATCH_THRESHOLDS,
    MatchResult,
    compute_disagreements,
    lemmatise_name,
    match_and_record_summary,
    match_entity,
)
from esbvaktin.entity_registry.models import Entity


@pytest.fixture
def registry() -> list[Entity]:
    """A small entity registry for testing."""
    return [
        Entity(
            id=1,
            slug="bjarni-benediktsson",
            canonical_name="Bjarni Benediktsson",
            entity_type="individual",
            stance="pro_eu",
            party_slug="sjalfstaedisflokkurinn",
            aliases=["Bjarna Benediktssonar"],
        ),
        Entity(
            id=2,
            slug="vidreisn",
            canonical_name="Viðreisn",
            entity_type="party",
            stance="pro_eu",
            aliases=["Viðreisnar"],
        ),
        Entity(
            id=3,
            slug="kristrun-frostadottir",
            canonical_name="Kristrún Frostadóttir",
            entity_type="individual",
            stance="pro_eu",
            aliases=["Kristrúnu Frostadóttur", "Kristrúnar Frostadóttur"],
        ),
    ]


class TestExactMatch:
    def test_exact_canonical(self, registry):
        result = match_entity("Bjarni Benediktsson", "individual", registry)
        assert isinstance(result, MatchResult)
        assert result.entity_id == 1
        assert result.method == "exact"
        assert result.confidence >= MATCH_THRESHOLDS["auto_link"]

    def test_exact_alias(self, registry):
        result = match_entity("Bjarna Benediktssonar", "individual", registry)
        assert result.entity_id == 1
        assert result.method == "alias"
        assert result.confidence >= MATCH_THRESHOLDS["auto_link"]

    def test_case_insensitive(self, registry):
        result = match_entity("bjarni benediktsson", "individual", registry)
        assert result.entity_id == 1


class TestLemmaMatch:
    @pytest.fixture(autouse=True)
    def _skip_without_islenska(self):
        try:
            from islenska import Bin  # noqa: F401
        except ImportError:
            pytest.skip("islenska not installed")

    def test_lemmatise_known_name(self):
        lemma = lemmatise_name("Bjarna")
        assert lemma is not None


class TestSubsetMatch:
    def test_two_word_subset(self, registry):
        result = match_entity("Kristrún Frostadóttir forsætisráðherra", "individual", registry)
        assert result.entity_id == 3
        assert result.method == "fuzzy"
        assert result.confidence >= MATCH_THRESHOLDS["flag"]

    def test_single_word_is_low(self, registry):
        result = match_entity("Bjarni", "individual", registry)
        assert result.confidence < MATCH_THRESHOLDS["flag"]


class TestNoMatch:
    def test_unknown_name(self, registry):
        result = match_entity("Guðmundur Sigurðsson", "individual", registry)
        assert result.entity_id is None
        assert result.confidence == 0.0

    def test_type_mismatch_lowers_confidence(self, registry):
        result = match_entity("Viðreisn", "individual", registry)
        assert result.confidence < MATCH_THRESHOLDS["flag"]


class TestDisagreements:
    def test_stance_disagreement(self):
        entity = Entity(
            id=1, slug="x", canonical_name="X", entity_type="individual", stance="pro_eu"
        )
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance="anti_eu",
            observed_role=None,
            observed_party=None,
            observed_type="individual",
        )
        assert disagreements["stance"] is True
        assert "role" not in disagreements

    def test_neutral_observation_no_disagreement(self):
        entity = Entity(
            id=1, slug="x", canonical_name="X", entity_type="individual", stance="pro_eu"
        )
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance="neutral",
            observed_role=None,
            observed_party=None,
            observed_type="individual",
        )
        assert disagreements is None

    def test_type_disagreement(self):
        entity = Entity(id=1, slug="x", canonical_name="X", entity_type="individual")
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance=None,
            observed_role=None,
            observed_party=None,
            observed_type="institution",
        )
        assert disagreements["type"] is True

    def test_party_disagreement(self):
        entity = Entity(
            id=1,
            slug="x",
            canonical_name="X",
            entity_type="individual",
            party_slug="vidreisn",
        )
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance=None,
            observed_role=None,
            observed_party="Samfylkingin",
            observed_type="individual",
        )
        assert disagreements["party"] is True


class TestMatchAndRecordSummary:
    def test_returns_summary(self):
        summary = match_and_record_summary(
            auto_linked=2, flagged=1, new_entities=0, disagreements=["stance"]
        )
        assert summary["auto_linked"] == 2
        assert summary["flagged"] == 1
        assert "stance" in summary["disagreements"]
