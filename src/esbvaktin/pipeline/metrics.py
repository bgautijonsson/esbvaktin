"""Lightweight pipeline telemetry (cost-09).

Records per-article output metrics — claim counts, verdict distribution, and the
assessment-context byte size as a proxy for Opus input cost — to a JSONL log, so the
overnight batch's volume and verdict mix become measurable run-over-run. Real token
counts require the Anthropic-SDK harness (cost-01, deferred); until then byte size is
the proxy.

Privacy-first: records counts, sizes, and ids/slugs only — never article or claim text.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# Project-level metrics log. data/analyses/ is gitignored, so this never ships.
DEFAULT_METRICS_PATH = Path(__file__).resolve().parents[3] / "data" / "analyses" / "_metrics.jsonl"


def append_metric(record: dict, metrics_path: Path = DEFAULT_METRICS_PATH) -> None:
    """Append one metrics record as a JSON line (ensure_ascii=False for Icelandic)."""
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    with metrics_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_metrics(metrics_path: Path = DEFAULT_METRICS_PATH) -> list[dict]:
    """Read all metrics records; empty list if the log doesn't exist yet."""
    if not metrics_path.exists():
        return []
    return [
        json.loads(line)
        for line in metrics_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def summarise(records: list[dict]) -> dict:
    """Aggregate metrics records for a /health-style summary."""
    verdict_totals: Counter[str] = Counter()
    for r in records:
        verdict_totals.update(r.get("verdict_counts", {}))
    return {
        "runs": len(records),
        "total_claims": sum(r.get("claim_count", 0) for r in records),
        "verdict_totals": dict(verdict_totals),
        "total_assessment_context_bytes": sum(
            r.get("assessment_context_bytes", 0) for r in records
        ),
    }
