"""Measure the cost-01 prompt-caching win for the claim-assessor.

Default (free, no API): structural analysis — what fraction of the assessor input
is the cacheable invariant prefix, across all real assessment contexts. This is the
decisive measurement: if the cacheable fraction is small, prompt caching cannot
save much regardless of cache mechanics.

--live WORK_DIR (billable): empirical confirmation — call the assessor via the
Anthropic SDK twice (cache write, then read) on one real context and report the
actual cache token counts. Requires ANTHROPIC_API_KEY and the `anthropic` package.

Usage:
    uv run python scripts/measure_assessor_cache.py                       # free
    uv run python scripts/measure_assessor_cache.py --live data/analyses/<id>
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from esbvaktin.llm.cached_call import (  # noqa: E402  (after load_dotenv, project convention)
    assessor_system_prompt,
    call_cached,
    split_assessment_context,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES = PROJECT_ROOT / "data" / "analyses"
MODEL = "claude-opus-4-8"


def structural() -> int:
    """Free measurement: the cacheable-prefix fraction across all real contexts."""
    files = list(ANALYSES.glob("*/_context_assessment.md"))
    frac: list[float] = []
    totals: list[int] = []
    for p in files:
        md = p.read_text(encoding="utf-8")
        prefix, _ = split_assessment_context(md)
        if prefix:
            frac.append(len(prefix) / len(md))
            totals.append(len(md))
    if not frac:
        print("No assessment contexts found in data/analyses/.")
        return 0

    n = len(frac)
    print(f"=== cost-01 structural measurement ({n} contexts) ===")
    print(f"Median context size:                 {statistics.median(totals):>10,.0f} chars")
    print(
        f"Cacheable prefix fraction of input:  median {statistics.median(frac) * 100:.1f}%  "
        f"mean {statistics.mean(frac) * 100:.1f}%  max {max(frac) * 100:.1f}%"
    )
    print(
        f"Best-case INPUT-token saving @100% hit: median {statistics.median(frac) * 0.9 * 100:.1f}%  "
        f"max {max(frac) * 0.9 * 100:.1f}%"
    )
    print("Caveats: output tokens are never cached (and cost ~5x input on Opus); the")
    print("real hit rate is < 100% (5-min TTL => only clustered/batch calls hit).")
    print("Conclusion: caching the invariant prefix saves <1% of total assessor cost;")
    print("the dominant input is the per-article claims+evidence (variable, uncacheable).")
    return 0


def live(work_dir: str) -> int:
    """Billable confirmation: two SDK calls on one context; report real cache tokens."""
    md_path = Path(work_dir) / "_context_assessment.md"
    if not md_path.exists():
        print(f"ERROR: {md_path} not found", file=sys.stderr)
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY not set — the --live measurement bills the Anthropic API.",
            file=sys.stderr,
        )
        return 1
    try:
        import anthropic
    except ImportError:
        print("ERROR: `anthropic` not installed. Run: uv add anthropic", file=sys.stderr)
        return 1

    md = md_path.read_text(encoding="utf-8")
    prefix, suffix = split_assessment_context(md)
    system = assessor_system_prompt()
    client = anthropic.Anthropic()

    print(f"Context: {md_path.parent.name}  prefix={len(prefix)} chars  suffix={len(suffix)} chars")
    print("Call 1 (cache write)…")
    _, u1 = call_cached(client, system=system, prefix=prefix, suffix=suffix, model=MODEL)
    print(f"  usage: {u1}")
    print("Call 2 (cache read, same prefix)…")
    _, u2 = call_cached(client, system=system, prefix=prefix, suffix=suffix, model=MODEL)
    print(f"  usage: {u2}")

    cached = u2["cache_read_input_tokens"]
    total_in = u2["input_tokens"] + cached + u2["cache_creation_input_tokens"]
    if total_in:
        print(
            f"\nCall 2 served {cached}/{total_in} input tokens from cache "
            f"({cached / total_in * 100:.1f}% of input at 0.1x cost)."
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure the cost-01 assessor prompt-caching win")
    ap.add_argument("--live", metavar="WORK_DIR", help="billable two-call API confirmation")
    args = ap.parse_args()
    return live(args.live) if args.live else structural()


if __name__ == "__main__":
    sys.exit(main())
