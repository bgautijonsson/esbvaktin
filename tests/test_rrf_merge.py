"""Tests for Reciprocal Rank Fusion merge — no DB required."""

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
