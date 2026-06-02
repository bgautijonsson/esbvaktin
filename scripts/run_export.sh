#!/usr/bin/env bash
# Run the full ESBvaktin export pipeline along its dependency DAG (latency-01).
#
# Thin wrapper around scripts/run_export.py, which runs the seven export steps
# concurrently where their real data dependencies allow (steps 1-4 + 6 are
# independent; step 5 waits on 1+2; step 7 waits on 1). See run_export.py for the
# DAG and the per-step size-floor gates.
#
# Usage:
#   ./scripts/run_export.sh --site-dir ~/esbvaktin-site
#   ./scripts/run_export.sh                              # export to data/export/ only

set -euo pipefail

exec uv run python "$(dirname "$0")/run_export.py" "$@"
