"""Tests for evidence ordering and retrieval constants — no DB required."""

from esbvaktin.pipeline.retrieve_evidence import (
    MAX_EVIDENCE_PER_CLAIM,
    MIN_SIMILARITY,
    _reorder_primacy_recency,
)


def test_min_similarity_is_045():
    assert MIN_SIMILARITY == 0.45


def test_max_evidence_per_claim_is_7():
    assert MAX_EVIDENCE_PER_CLAIM == 7


def test_reorder_empty():
    assert _reorder_primacy_recency([]) == []


def test_reorder_single():
    assert _reorder_primacy_recency(["a"]) == ["a"]


def test_reorder_two():
    assert _reorder_primacy_recency(["a", "b"]) == ["a", "b"]


def test_reorder_three():
    # Input sorted desc: best, 2nd, 3rd
    # Output: best, 3rd, 2nd (2nd moves to end)
    result = _reorder_primacy_recency(["best", "2nd", "3rd"])
    assert result[0] == "best"
    assert result[-1] == "2nd"
    assert result[1] == "3rd"


def test_reorder_seven():
    items = [7, 6, 5, 4, 3, 2, 1]  # sorted descending
    result = _reorder_primacy_recency(items)
    assert result[0] == 7  # best first
    assert result[-1] == 6  # second-best last
    assert result[1:-1] == [5, 4, 3, 2, 1]  # rest in middle
