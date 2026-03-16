#!/usr/bin/env bash
# Run the full 7-step ESBvaktin export pipeline with validation.
#
# Usage:
#   ./scripts/run_export.sh --site-dir ~/esbvaktin-site
#   ./scripts/run_export.sh                              # Export to data/export/ only

set -euo pipefail

SITE_ARG=""
if [[ "${1:-}" == "--site-dir" && -n "${2:-}" ]]; then
    SITE_ARG="--site-dir $2"
    echo "Site directory: $2"
fi

FAIL=0

run_step() {
    local step="$1"
    local desc="$2"
    shift 2
    echo ""
    echo "=== Step $step: $desc ==="
    if "$@"; then
        echo "  [OK] Step $step complete"
    else
        echo "  [FAIL] Step $step failed (exit $?)" >&2
        FAIL=1
        return 1
    fi
}

check_file() {
    local path="$1"
    local min_bytes="${2:-10}"
    if [[ ! -f "$path" ]]; then
        echo "  [WARN] Expected file missing: $path" >&2
        return 1
    fi
    local size
    size=$(wc -c < "$path" | tr -d ' ')
    if [[ "$size" -lt "$min_bytes" ]]; then
        echo "  [WARN] File suspiciously small ($size bytes): $path" >&2
        return 1
    fi
    return 0
}

echo "ESBvaktin Export Pipeline"
echo "========================"
echo "Started: $(date)"

# Step 1: Entities
run_step 1 "Export entities" \
    uv run python scripts/export_entities.py $SITE_ARG || exit 1

# Step 2: Evidence
run_step 2 "Export evidence" \
    uv run python scripts/export_evidence.py $SITE_ARG || exit 1
check_file "data/export/evidence_meta.json" 100

# Step 3: Topics
run_step 3 "Export topics" \
    uv run python scripts/export_topics.py $SITE_ARG || exit 1

# Step 4: Claims
run_step 4 "Export claims" \
    uv run python scripts/export_claims.py $SITE_ARG || exit 1
check_file "data/export/claims.json" 100

# Step 5: Prepare site (overlay DB verdicts)
run_step 5 "Prepare site data" \
    uv run python scripts/prepare_site.py $SITE_ARG || exit 1

# Step 6: Speeches
run_step 6 "Prepare speeches" \
    uv run python scripts/prepare_speeches.py $SITE_ARG || exit 1

# Step 7: Overviews
run_step 7 "Export overviews" \
    uv run python scripts/export_overviews.py $SITE_ARG || exit 1

echo ""
echo "========================"
if [[ "$FAIL" -eq 0 ]]; then
    echo "All 7 steps completed successfully."
else
    echo "WARNING: One or more steps had issues." >&2
fi
echo "Finished: $(date)"
