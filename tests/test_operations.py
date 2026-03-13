"""Integration tests for database operations.

Requires a running PostgreSQL instance with pgvector.
Set DATABASE_URL environment variable or have .env file.

Usage:
    uv run pytest tests/test_operations.py -v
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

from tests.conftest import requires_embeddings

# Skip all tests if no database connection or no embeddings
pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL not set — need a running PostgreSQL instance",
    ),
    requires_embeddings,
]

from esbvaktin.ground_truth import (
    Confidence,
    Domain,
    EvidenceEntry,
    SourceType,
    get_connection,
    get_topic_counts,
    get_total_count,
    init_schema,
    insert_evidence,
    search_evidence,
)


@pytest.fixture(scope="module")
def db_conn():
    """Set up a clean test schema."""
    conn = get_connection()
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_entry():
    return EvidenceEntry(
        evidence_id="TEST-DATA-999",
        domain=Domain.ECONOMIC,
        topic="test_topic",
        subtopic="test_sub",
        statement="This is a test evidence entry for automated testing.",
        source_name="Test Source",
        source_type=SourceType.OFFICIAL_STATISTICS,
        confidence=Confidence.HIGH,
    )


def test_insert_and_retrieve(db_conn, sample_entry):
    """Test that we can insert an entry and find it via semantic search."""
    # Clean up any previous test entry
    db_conn.execute("DELETE FROM evidence WHERE evidence_id = 'TEST-DATA-999'")
    db_conn.commit()

    insert_evidence(sample_entry, conn=db_conn)

    # Search for it
    results = search_evidence("test evidence automated", top_k=5, conn=db_conn)
    found = [r for r in results if r.evidence_id == "TEST-DATA-999"]
    assert len(found) == 1
    assert found[0].topic == "test_topic"
    assert found[0].similarity > 0.3

    # Clean up
    db_conn.execute("DELETE FROM evidence WHERE evidence_id = 'TEST-DATA-999'")
    db_conn.commit()


def test_upsert_updates_existing(db_conn, sample_entry):
    """Test that inserting with same evidence_id updates the entry."""
    db_conn.execute("DELETE FROM evidence WHERE evidence_id = 'TEST-DATA-999'")
    db_conn.commit()

    insert_evidence(sample_entry, conn=db_conn)

    updated = sample_entry.model_copy(update={"statement": "Updated test statement."})
    insert_evidence(updated, conn=db_conn)

    row = db_conn.execute(
        "SELECT statement FROM evidence WHERE evidence_id = 'TEST-DATA-999'"
    ).fetchone()
    assert row[0] == "Updated test statement."

    # Clean up
    db_conn.execute("DELETE FROM evidence WHERE evidence_id = 'TEST-DATA-999'")
    db_conn.commit()


def test_topic_filter(db_conn, sample_entry):
    """Test that topic_filter narrows results."""
    db_conn.execute("DELETE FROM evidence WHERE evidence_id = 'TEST-DATA-999'")
    db_conn.commit()

    insert_evidence(sample_entry, conn=db_conn)

    results_with_filter = search_evidence(
        "test evidence", topic_filter="test_topic", top_k=5, conn=db_conn
    )
    results_wrong_filter = search_evidence(
        "test evidence", topic_filter="nonexistent_topic", top_k=5, conn=db_conn
    )

    assert any(r.evidence_id == "TEST-DATA-999" for r in results_with_filter)
    assert not any(r.evidence_id == "TEST-DATA-999" for r in results_wrong_filter)

    # Clean up
    db_conn.execute("DELETE FROM evidence WHERE evidence_id = 'TEST-DATA-999'")
    db_conn.commit()


def test_get_counts(db_conn):
    """Test count functions return sensible values."""
    total = get_total_count(db_conn)
    assert isinstance(total, int)
    assert total >= 0

    topics = get_topic_counts(db_conn)
    assert isinstance(topics, dict)
