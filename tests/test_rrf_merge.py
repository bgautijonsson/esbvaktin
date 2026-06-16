"""Tests for Reciprocal Rank Fusion merge — no DB required."""

import pytest

from esbvaktin.pipeline.retrieve_evidence import RRF_K, _rrf_merge


def _make_result(eid, similarity=0.5):
    """Helper to create a minimal SearchResult-like object."""
    from esbvaktin.ground_truth.models import SearchResult

    return SearchResult(
        evidence_id=eid,
        statement=f"Statement for {eid}",
        similarity=similarity,
        source_name="Test",
        source_url=None,
        domain="economic",
        topic="trade",
        subtopic=None,
        source_date=None,
        source_type="official_statistics",
        confidence="high",
        caveats=None,
        statement_is=None,
    )


def test_rrf_merge_both_lists():
    """Document in both lists ranks higher than document in one."""
    vector = [_make_result("A", 0.9), _make_result("B", 0.8)]
    keyword = [_make_result("A", 0.0), _make_result("C", 0.0)]

    merged = _rrf_merge(vector, keyword)
    ids = [r.evidence_id for r, score in merged]

    # A is in both lists — should rank first
    assert ids[0] == "A"
    # B and C each in one list
    assert "B" in ids
    assert "C" in ids


def test_rrf_merge_empty_keyword():
    """Works when keyword search returns nothing."""
    vector = [_make_result("A", 0.9), _make_result("B", 0.8)]
    merged = _rrf_merge(vector, [])
    assert len(merged) == 2
    assert merged[0][0].evidence_id == "A"


def test_rrf_merge_empty_vector():
    """Works when vector search returns nothing."""
    keyword = [_make_result("X", 0.0), _make_result("Y", 0.0)]
    merged = _rrf_merge([], keyword)
    assert len(merged) == 2
    assert merged[0][0].evidence_id == "X"


def test_rrf_merge_preserves_vector_similarity():
    """Vector result's similarity is preserved in the merged output."""
    vector = [_make_result("A", 0.85)]
    merged = _rrf_merge(vector, [])
    assert merged[0][0].similarity == 0.85


def test_rrf_merge_keyword_only_gets_score():
    """Document found only by keyword still gets an RRF score."""
    keyword = [_make_result("K1", 0.0)]
    merged = _rrf_merge([], keyword)
    assert len(merged) == 1
    assert merged[0][1] > 0  # has a positive RRF score


def test_rrf_k_constant():
    """RRF_K is the standard value of 60."""
    assert RRF_K == 60


# --- Characterisation / ranking-equality tests (guard the isretrieval swap) ---
#
# These pin the exact fused ORDER and the per-document RRF SCORES against values
# derived from the formula (1-based rank: weight / (RRF_K + rank)), independent of
# the implementation. They lock the contract so swapping the local _rrf_merge body
# for isretrieval.rrf_fuse must produce a byte-identical ranking.


def test_rrf_merge_exact_order_and_scores():
    """Fused order and scores match the 1-based-rank RRF formula exactly.

    vector  = [A(r1), B(r2), C(r3)]
    keyword = [B(r1), D(r2), A(r3)]

    A = 1/61 + 1/63   B = 1/62 + 1/61   C = 1/63   D = 1/62
    => order B > A > D > C
    """
    vector = [_make_result("A", 0.9), _make_result("B", 0.8), _make_result("C", 0.7)]
    keyword = [_make_result("B", 0.0), _make_result("D", 0.0), _make_result("A", 0.0)]

    merged = _rrf_merge(vector, keyword)
    ids = [r.evidence_id for r, _ in merged]
    scores = {r.evidence_id: s for r, s in merged}

    assert ids == ["B", "A", "D", "C"]
    assert scores["A"] == pytest.approx(1.0 / 61 + 1.0 / 63)
    assert scores["B"] == pytest.approx(1.0 / 62 + 1.0 / 61)
    assert scores["C"] == pytest.approx(1.0 / 63)
    assert scores["D"] == pytest.approx(1.0 / 62)


def test_rrf_merge_weights_applied():
    """Per-list weights scale each list's rank contribution."""
    vector = [_make_result("P", 0.9)]
    keyword = [_make_result("P", 0.0)]

    merged = _rrf_merge(vector, keyword, vector_weight=2.0, keyword_weight=0.5)
    assert len(merged) == 1
    result, score = merged[0]
    assert result.evidence_id == "P"
    assert score == pytest.approx(2.0 / 61 + 0.5 / 61)


def test_rrf_merge_tie_preserves_insertion_order():
    """On a score tie, vector-insertion order wins (stable sort over dict order).

    X and Y both score 1/61 + 1/62; X is inserted first (vector rank 1), so it
    ranks ahead of Y in the fused output.
    """
    vector = [_make_result("X", 0.9), _make_result("Y", 0.8)]
    keyword = [_make_result("Y", 0.0), _make_result("X", 0.0)]

    merged = _rrf_merge(vector, keyword)
    ids = [r.evidence_id for r, _ in merged]
    scores = {r.evidence_id: s for r, s in merged}

    assert scores["X"] == pytest.approx(scores["Y"])
    assert ids == ["X", "Y"]
