#!/usr/bin/env python3
"""Validate that a pipeline work dir's agent outputs were actually written (rel-03/rel-08).

Subagents report success without writing their output ~25% of the time, and every skill
duplicates a "verify the file, retry once" block that a forgetful run can skip. This is
the single, reliable source of that check: for each ``_context_<step>.md`` present in a
work dir, the matching ``_<step>.json`` must exist and be non-empty.

Two consumers:
  - orchestration / CI call it directly to HARD-FAIL on a missing output
    (``validate_workdir.py <dir>`` exits non-zero);
  - the advisory SubagentStop hook (.claude/hooks/verify-subagent-output.sh) calls it with
    ``--recent`` to SURFACE gaps without blocking — claim-assessor and omissions-analyst
    run in parallel, so a missing output at one agent's stop can be legitimate.

Usage:
    uv run python scripts/validate_workdir.py data/analyses/<id>   # validate one dir
    uv run python scripts/validate_workdir.py --recent             # most-recent work dir
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"

# Each agent context file and the JSON output the agent is instructed to write.
EXPECTED_OUTPUTS = {
    "_context_extraction.md": "_claims.json",
    "_context_assessment.md": "_assessments.json",
    "_context_omissions.md": "_omissions.json",
    "_context_entities.md": "_entities.json",
}


def missing_outputs(workdir: Path) -> list[tuple[str, str]]:
    """For each agent context file present in ``workdir``, the (context, output) pairs
    whose output JSON is missing or empty."""
    missing: list[tuple[str, str]] = []
    for ctx, out in EXPECTED_OUTPUTS.items():
        if (workdir / ctx).exists():
            out_path = workdir / out
            if not out_path.exists() or out_path.stat().st_size == 0:
                missing.append((ctx, out))
    return missing


def most_recent_workdir(analyses_dir: Path = ANALYSES_DIR) -> Path | None:
    """The most recently modified analysis dir (what a subagent most likely just wrote)."""
    if not analyses_dir.exists():
        return None
    dirs = [d for d in analyses_dir.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def _report(workdir: Path) -> list[tuple[str, str]]:
    missing = missing_outputs(workdir)
    if missing:
        print(f"Missing agent output(s) in {workdir.name}:", file=sys.stderr)
        for ctx, out in missing:
            print(f"  - {ctx} present but {out} missing/empty", file=sys.stderr)
    return missing


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--recent" in argv:
        workdir = most_recent_workdir()
        if workdir is None:
            return 0
    elif argv:
        workdir = Path(argv[0])
    else:
        print("usage: validate_workdir.py <workdir> | --recent", file=sys.stderr)
        return 2
    return 1 if _report(workdir) else 0


if __name__ == "__main__":
    sys.exit(main())
