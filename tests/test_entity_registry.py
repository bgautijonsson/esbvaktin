"""Tests for entity registry models and operations."""

import pytest
from pydantic import ValidationError

from esbvaktin.entity_registry.models import (
    Entity,
    EntityObservation,
    MatchMethod,
    RoleEntry,
    VerificationStatus,
)


class TestEntity:
    def test_minimal(self):
        e = Entity(
            slug="bjarni-benediktsson",
            canonical_name="Bjarni Benediktsson",
            entity_type="individual",
        )
        assert e.verification_status == VerificationStatus.AUTO_GENERATED
        assert e.aliases == []
        assert e.roles == []
        assert e.is_icelandic is True

    def test_full(self):
        e = Entity(
            slug="bjarni-benediktsson",
            canonical_name="Bjarni Benediktsson",
            entity_type="individual",
            subtype="politician",
            stance="pro_eu",
            stance_score=0.8,
            stance_confidence=0.9,
            party_slug="sjalfstaedisflokkurinn",
            althingi_id=123,
            aliases=["Bjarna Benediktssonar", "Bjarna Benediktssyni"],
            roles=[RoleEntry(role="forsætisráðherra", from_date="2024-01-01")],
            verification_status="confirmed",
        )
        assert e.stance == "pro_eu"
        assert len(e.aliases) == 2
        assert e.roles[0].role == "forsætisráðherra"

    def test_invalid_entity_type(self):
        with pytest.raises(ValidationError):
            Entity(slug="x", canonical_name="X", entity_type="alien")

    def test_invalid_stance(self):
        with pytest.raises(ValidationError):
            Entity(slug="x", canonical_name="X", entity_type="individual", stance="maybe")

    def test_stance_score_bounds(self):
        with pytest.raises(ValidationError):
            Entity(slug="x", canonical_name="X", entity_type="individual", stance_score=1.5)


class TestEntityObservation:
    def test_minimal(self):
        obs = EntityObservation(
            article_slug="test-article",
            observed_name="Bjarni Benediktsson",
        )
        assert obs.entity_id is None
        assert obs.attribution_types == []
        assert obs.match_confidence is None

    def test_with_match(self):
        obs = EntityObservation(
            entity_id=1,
            article_slug="test-article",
            article_url="https://example.com/article",
            observed_name="Bjarna Benediktssonar",
            observed_stance="pro_eu",
            observed_role="forsætisráðherra",
            attribution_types=["quoted", "asserted"],
            claim_indices=[0, 2, 5],
            match_confidence=0.95,
            match_method="exact",
        )
        assert obs.match_method == MatchMethod.EXACT
        assert obs.claim_indices == [0, 2, 5]

    def test_disagreements(self):
        obs = EntityObservation(
            entity_id=1,
            article_slug="test-article",
            observed_name="Test",
            disagreements={"stance": True, "role": True},
        )
        assert obs.disagreements["stance"] is True

    def test_invalid_match_method(self):
        with pytest.raises(ValidationError):
            EntityObservation(
                article_slug="x",
                observed_name="X",
                match_method="telepathy",
            )


class TestRoleEntry:
    def test_current_role(self):
        r = RoleEntry(role="þingmaður", from_date="2024-01-01")
        assert r.to_date is None

    def test_past_role(self):
        r = RoleEntry(role="ráðherra", from_date="2021-06-01", to_date="2023-12-31")
        assert r.to_date == "2023-12-31"
