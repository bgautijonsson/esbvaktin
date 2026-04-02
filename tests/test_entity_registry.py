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


from esbvaktin.entity_registry.operations import (  # noqa: E402
    get_all_entities,
    get_entity_by_slug,
    get_observations_for_entity,
    get_review_queue,
    insert_entity,
    insert_observation,
    merge_entities,
    update_entity,
)


@pytest.fixture
def db_conn():
    """Get a test DB connection (uses real local DB)."""
    from esbvaktin.ground_truth.operations import get_connection, init_schema

    conn = get_connection()
    init_schema(conn)
    conn.execute("DELETE FROM entity_observations")
    conn.execute("DELETE FROM entities")
    conn.commit()
    yield conn
    conn.rollback()  # clear any aborted transaction from error-path tests
    conn.execute("DELETE FROM entity_observations")
    conn.execute("DELETE FROM entities")
    conn.commit()
    conn.close()


class TestInsertEntity:
    def test_insert_and_retrieve(self, db_conn):
        entity = Entity(
            slug="test-person",
            canonical_name="Test Person",
            entity_type="individual",
            stance="pro_eu",
            stance_score=0.8,
            aliases=["Test Personu", "Test Persons"],
        )
        entity_id = insert_entity(entity, db_conn)
        assert entity_id > 0

        retrieved = get_entity_by_slug("test-person", db_conn)
        assert retrieved is not None
        assert retrieved.canonical_name == "Test Person"
        assert retrieved.stance == "pro_eu"
        assert "Test Personu" in retrieved.aliases

    def test_insert_duplicate_slug_raises(self, db_conn):
        entity = Entity(slug="dupe", canonical_name="Dupe", entity_type="individual")
        insert_entity(entity, db_conn)
        with pytest.raises(Exception):
            insert_entity(entity, db_conn)

    def test_returns_none_for_missing_slug(self, db_conn):
        assert get_entity_by_slug("nonexistent", db_conn) is None

    def test_get_all_entities(self, db_conn):
        insert_entity(Entity(slug="a", canonical_name="A", entity_type="individual"), db_conn)
        insert_entity(Entity(slug="b", canonical_name="B", entity_type="party"), db_conn)
        all_entities = get_all_entities(db_conn)
        assert len(all_entities) == 2


class TestInsertObservation:
    def test_insert_linked(self, db_conn):
        entity_id = insert_entity(
            Entity(slug="obs-test", canonical_name="Obs Test", entity_type="individual"),
            db_conn,
        )
        obs = EntityObservation(
            entity_id=entity_id,
            article_slug="article-1",
            article_url="https://example.com/1",
            observed_name="Obs Test",
            observed_stance="pro_eu",
            attribution_types=["quoted"],
            match_confidence=0.95,
            match_method="exact",
        )
        obs_id = insert_observation(obs, db_conn)
        assert obs_id > 0

        observations = get_observations_for_entity(entity_id, db_conn)
        assert len(observations) == 1
        assert observations[0].observed_stance == "pro_eu"

    def test_insert_unlinked(self, db_conn):
        obs = EntityObservation(
            article_slug="article-2",
            observed_name="Unknown Person",
        )
        obs_id = insert_observation(obs, db_conn)
        assert obs_id > 0


class TestReviewQueue:
    def test_queue_includes_needs_review(self, db_conn):
        insert_entity(
            Entity(
                slug="review-me",
                canonical_name="Review Me",
                entity_type="individual",
                verification_status="needs_review",
            ),
            db_conn,
        )
        insert_entity(
            Entity(
                slug="confirmed-one",
                canonical_name="Confirmed",
                entity_type="individual",
                verification_status="confirmed",
            ),
            db_conn,
        )
        queue = get_review_queue(db_conn)
        slugs = [e.slug for e in queue.entities]
        assert "review-me" in slugs
        assert "confirmed-one" not in slugs

    def test_queue_includes_unlinked_observations(self, db_conn):
        insert_observation(
            EntityObservation(article_slug="a", observed_name="Mystery"),
            db_conn,
        )
        queue = get_review_queue(db_conn)
        assert queue.unlinked_count > 0


class TestUpdateEntity:
    def test_update_stance(self, db_conn):
        entity_id = insert_entity(
            Entity(
                slug="updatable",
                canonical_name="Updatable",
                entity_type="individual",
                stance="neutral",
            ),
            db_conn,
        )
        update_entity(entity_id, {"stance": "pro_eu", "stance_score": 0.7}, db_conn)
        updated = get_entity_by_slug("updatable", db_conn)
        assert updated.stance == "pro_eu"
        assert updated.stance_score == 0.7


class TestMergeEntities:
    def test_merge_absorbs_aliases(self, db_conn):
        keep_id = insert_entity(
            Entity(
                slug="keep",
                canonical_name="Keep",
                entity_type="individual",
                aliases=["Keeps"],
            ),
            db_conn,
        )
        absorb_id = insert_entity(
            Entity(
                slug="absorb",
                canonical_name="Absorb",
                entity_type="individual",
                aliases=["Absorbs"],
            ),
            db_conn,
        )
        insert_observation(
            EntityObservation(entity_id=absorb_id, article_slug="a1", observed_name="Absorb"),
            db_conn,
        )

        merge_entities(keep_id=keep_id, absorb_id=absorb_id, conn=db_conn)

        assert get_entity_by_slug("absorb", db_conn) is None
        keep = get_entity_by_slug("keep", db_conn)
        assert "Absorb" in keep.aliases
        assert "Absorbs" in keep.aliases
        obs = get_observations_for_entity(keep_id, db_conn)
        assert len(obs) == 1
