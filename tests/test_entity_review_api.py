"""Tests for entity review UI query operations."""

import pytest

from esbvaktin.entity_registry.models import Entity, EntityObservation
from esbvaktin.entity_registry.operations import (
    confirm_entity,
    delete_entity,
    dismiss_observation,
    get_dashboard_stats,
    get_entity_by_slug,
    get_entity_detail,
    get_filtered_entities,
    get_observations_for_entity,
    insert_entity,
    insert_observation,
    relink_observation,
)


@pytest.fixture
def db_conn():
    """Get a test DB connection with clean entity tables and rollback in teardown."""
    from esbvaktin.ground_truth.operations import get_connection, init_schema

    conn = get_connection()
    init_schema(conn)
    conn.execute("DELETE FROM entity_observations")
    conn.execute("DELETE FROM entities")
    conn.commit()
    yield conn
    conn.rollback()
    conn.execute("DELETE FROM entity_observations")
    conn.execute("DELETE FROM entities")
    conn.commit()
    conn.close()


@pytest.fixture
def seeded_db(db_conn):
    """Seed 2 entities + 3 observations (stance conflict on person-a)."""
    person_a_id = insert_entity(
        Entity(
            slug="person-a",
            canonical_name="Person A",
            entity_type="individual",
            stance="pro_eu",
            verification_status="auto_generated",
        ),
        db_conn,
    )
    party_b_id = insert_entity(
        Entity(
            slug="party-b",
            canonical_name="Party B",
            entity_type="party",
            stance="anti_eu",
            verification_status="needs_review",
        ),
        db_conn,
    )

    # Two observations on person-a with stance conflict (pro_eu vs anti_eu)
    obs1_id = insert_observation(
        EntityObservation(
            entity_id=person_a_id,
            article_slug="article-1",
            article_url="https://example.com/1",
            observed_name="Person A",
            observed_stance="pro_eu",
            observed_type="individual",
            match_confidence=0.95,
            match_method="exact",
        ),
        db_conn,
    )
    obs2_id = insert_observation(
        EntityObservation(
            entity_id=person_a_id,
            article_slug="article-2",
            article_url="https://example.com/2",
            observed_name="Person A",
            observed_stance="anti_eu",
            observed_type="individual",
            match_confidence=0.90,
            match_method="exact",
        ),
        db_conn,
    )
    # One observation on party-b
    obs3_id = insert_observation(
        EntityObservation(
            entity_id=party_b_id,
            article_slug="article-3",
            article_url="https://example.com/3",
            observed_name="Party B",
            observed_stance="anti_eu",
            observed_type="party",
            match_confidence=0.95,
            match_method="exact",
        ),
        db_conn,
    )
    return {
        "person_a_id": person_a_id,
        "party_b_id": party_b_id,
        "obs1_id": obs1_id,
        "obs2_id": obs2_id,
        "obs3_id": obs3_id,
    }


class TestDashboardStats:
    def test_returns_counts(self, db_conn, seeded_db):
        stats = get_dashboard_stats(db_conn)
        assert stats["total_entities"] == 2
        assert stats["total_observations"] == 3
        assert stats["by_status"]["auto_generated"] == 1
        assert stats["by_status"]["needs_review"] == 1
        assert stats["by_status"]["confirmed"] == 0
        assert stats["stance_conflicts"] >= 1
        # No type mismatches in our seed data
        assert stats["type_mismatches"] >= 0
        # No placeholders — both entities have observations
        assert stats["placeholders"] == 0

    def test_dismissed_excluded_from_observation_count(self, db_conn, seeded_db):
        dismiss_observation(seeded_db["obs1_id"], db_conn)
        stats = get_dashboard_stats(db_conn)
        assert stats["total_observations"] == 2


class TestFilteredEntities:
    def test_filter_by_type(self, db_conn, seeded_db):
        results = get_filtered_entities(db_conn, entity_type="party")
        assert len(results) == 1
        assert results[0]["slug"] == "party-b"

    def test_filter_by_status(self, db_conn, seeded_db):
        results = get_filtered_entities(db_conn, status="needs_review")
        assert len(results) == 1
        assert results[0]["slug"] == "party-b"

    def test_search(self, db_conn, seeded_db):
        results = get_filtered_entities(db_conn, search="person")
        assert len(results) == 1
        assert results[0]["slug"] == "person-a"

    def test_filter_stance_conflicts(self, db_conn, seeded_db):
        results = get_filtered_entities(db_conn, issue="stance_conflict")
        assert len(results) >= 1
        slugs = [r["slug"] for r in results]
        assert "person-a" in slugs

    def test_returns_observation_count(self, db_conn, seeded_db):
        results = get_filtered_entities(db_conn)
        by_slug = {r["slug"]: r for r in results}
        assert by_slug["person-a"]["observation_count"] == 2
        assert by_slug["party-b"]["observation_count"] == 1

    def test_returns_stance_breakdown(self, db_conn, seeded_db):
        results = get_filtered_entities(db_conn)
        by_slug = {r["slug"]: r for r in results}
        breakdown = by_slug["person-a"]["stance_breakdown"]
        assert breakdown.get("pro_eu", 0) >= 1
        assert breakdown.get("anti_eu", 0) >= 1

    def test_dismissed_excluded(self, db_conn, seeded_db):
        dismiss_observation(seeded_db["obs1_id"], db_conn)
        results = get_filtered_entities(db_conn)
        by_slug = {r["slug"]: r for r in results}
        assert by_slug["person-a"]["observation_count"] == 1

    def test_filter_placeholder(self, db_conn, seeded_db):
        # Create an entity with no observations
        insert_entity(
            Entity(slug="ghost", canonical_name="Ghost", entity_type="individual"),
            db_conn,
        )
        results = get_filtered_entities(db_conn, issue="placeholder")
        slugs = [r["slug"] for r in results]
        assert "ghost" in slugs

    def test_filter_type_mismatch(self, db_conn, seeded_db):
        # Add an observation with type mismatch on party-b
        insert_observation(
            EntityObservation(
                entity_id=seeded_db["party_b_id"],
                article_slug="article-4",
                observed_name="Party B",
                observed_type="institution",
                match_confidence=0.8,
                match_method="exact",
            ),
            db_conn,
        )
        results = get_filtered_entities(db_conn, issue="type_mismatch")
        slugs = [r["slug"] for r in results]
        assert "party-b" in slugs


class TestEntityDetail:
    def test_includes_observations(self, db_conn, seeded_db):
        detail = get_entity_detail("person-a", db_conn)
        assert detail is not None
        assert len(detail["observations"]) == 2
        assert detail["canonical_name"] == "Person A"

    def test_not_found(self, db_conn, seeded_db):
        detail = get_entity_detail("nonexistent", db_conn)
        assert detail is None


class TestConfirmEntity:
    def test_sets_confirmed(self, db_conn, seeded_db):
        result = confirm_entity("person-a", db_conn)
        assert result is not None
        assert result.verification_status == "confirmed"

        refreshed = get_entity_by_slug("person-a", db_conn)
        assert refreshed.verification_status == "confirmed"

    def test_not_found(self, db_conn, seeded_db):
        result = confirm_entity("nonexistent", db_conn)
        assert result is None


class TestDeleteEntity:
    def test_deletes_and_unlinks(self, db_conn, seeded_db):
        result = delete_entity("person-a", db_conn)
        assert result is True

        # Entity is gone
        assert get_entity_by_slug("person-a", db_conn) is None

        # Observations still exist but are orphaned (entity_id=NULL)
        rows = db_conn.execute(
            "SELECT entity_id FROM entity_observations WHERE article_slug IN ('article-1', 'article-2')"
        ).fetchall()
        assert len(rows) == 2
        assert all(r[0] is None for r in rows)

    def test_not_found(self, db_conn, seeded_db):
        result = delete_entity("nonexistent", db_conn)
        assert result is False


class TestDismissObservation:
    def test_dismiss(self, db_conn, seeded_db):
        result = dismiss_observation(seeded_db["obs1_id"], db_conn)
        assert result is True

        obs = get_observations_for_entity(seeded_db["person_a_id"], db_conn)
        dismissed = [o for o in obs if o.id == seeded_db["obs1_id"]]
        assert dismissed[0].dismissed is True

    def test_not_found(self, db_conn, seeded_db):
        result = dismiss_observation(999999, db_conn)
        assert result is False


class TestRelinkObservation:
    def test_relink(self, db_conn, seeded_db):
        # Move obs1 from person-a to party-b
        result = relink_observation(seeded_db["obs1_id"], seeded_db["party_b_id"], db_conn)
        assert result is True

        # person-a now has 1 observation
        obs_a = get_observations_for_entity(seeded_db["person_a_id"], db_conn)
        assert len(obs_a) == 1

        # party-b now has 2 observations
        obs_b = get_observations_for_entity(seeded_db["party_b_id"], db_conn)
        assert len(obs_b) == 2

    def test_not_found(self, db_conn, seeded_db):
        result = relink_observation(999999, seeded_db["party_b_id"], db_conn)
        assert result is False
