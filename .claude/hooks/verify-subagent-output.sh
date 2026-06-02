#!/usr/bin/env bash
# Advisory SubagentStop hook (rel-03): after any subagent stops, check the most-recent
# pipeline work dir for agent outputs that were not written, and surface them.
#
# ADVISORY ONLY — always exits 0. claim-assessor and omissions-analyst run in parallel, so
# a missing _omissions.json at the instant the assessor stops can be legitimate (the
# omissions agent is still running). Blocking here (exit 2) would misfire and stall the
# unattended batch; instead we print a warning so a genuine dropped output is visible in
# the morning git-diff review. Reliable, blocking validation is the orchestration's job:
#   uv run python scripts/validate_workdir.py <work-dir>

cat >/dev/null 2>&1  # consume the SubagentStop event JSON on stdin

cd "$(dirname "$0")/../.." || exit 0
uv run python scripts/validate_workdir.py --recent || true
exit 0
