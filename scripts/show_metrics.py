"""Show pipeline telemetry summary (cost-09). Read-only.

Usage:
    uv run python scripts/show_metrics.py
"""

from esbvaktin.pipeline.metrics import read_metrics, summarise


def main() -> None:
    records = read_metrics()
    s = summarise(records)
    print("=== Pipeline telemetry (data/analyses/_metrics.jsonl) ===")
    print(f"Articles recorded:      {s['runs']}")
    print(f"Total claims assessed:  {s['total_claims']}")
    print(
        f"Assessment-context bytes (proxy for Opus input): {s['total_assessment_context_bytes']:,}"
    )
    if s["verdict_totals"]:
        print("Verdict totals:")
        for verdict, count in sorted(s["verdict_totals"].items(), key=lambda kv: -kv[1]):
            print(f"  {verdict}: {count}")
    if not records:
        print("(no runs recorded yet — telemetry accrues as assemble_report.py runs)")


if __name__ == "__main__":
    main()
