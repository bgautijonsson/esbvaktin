"""Tests for the lightweight pipeline telemetry log (cost-09)."""

from esbvaktin.pipeline import metrics


def test_append_and_read_roundtrip(tmp_path):
    p = tmp_path / "_metrics.jsonl"
    metrics.append_metric({"work_dir": "a1", "claim_count": 3}, p)
    metrics.append_metric({"work_dir": "a2", "claim_count": 5}, p)
    records = metrics.read_metrics(p)
    assert len(records) == 2
    assert records[0]["work_dir"] == "a1"
    assert records[1]["claim_count"] == 5


def test_read_missing_returns_empty(tmp_path):
    assert metrics.read_metrics(tmp_path / "nope.jsonl") == []


def test_append_preserves_icelandic(tmp_path):
    """ensure_ascii=False so Icelandic round-trips (no ASCII transliteration)."""
    p = tmp_path / "_metrics.jsonl"
    metrics.append_metric({"source": "Ísland og Evrópusambandið"}, p)
    assert metrics.read_metrics(p)[0]["source"] == "Ísland og Evrópusambandið"


def test_summarise_aggregates(tmp_path):
    records = [
        {
            "claim_count": 3,
            "verdict_counts": {"supported": 2, "misleading": 1},
            "assessment_context_bytes": 1000,
        },
        {
            "claim_count": 5,
            "verdict_counts": {"supported": 1, "unverifiable": 4},
            "assessment_context_bytes": 2000,
        },
    ]
    s = metrics.summarise(records)
    assert s["runs"] == 2
    assert s["total_claims"] == 8
    assert s["verdict_totals"]["supported"] == 3
    assert s["verdict_totals"]["unverifiable"] == 4
    assert s["total_assessment_context_bytes"] == 3000


def test_summarise_empty():
    s = metrics.summarise([])
    assert s["runs"] == 0
    assert s["total_claims"] == 0
    assert s["verdict_totals"] == {}
