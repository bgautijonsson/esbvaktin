#!/usr/bin/env bash
# Pre-export validation hook for ESBvaktin.
# Runs before any export script to catch data integrity issues.
#
# Called by Claude Code PreToolUse hook when Bash commands match export patterns.
# Reads tool input from stdin, checks if the command is an export script,
# and validates DB integrity before allowing it to proceed.

set -euo pipefail

# Parse stdin for the command being run
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('tool_input', {}).get('command', ''))" 2>/dev/null || echo "")

# Only check export commands
if ! echo "$COMMAND" | grep -qE '(export_claims|export_evidence|export_topics|export_entities|export_overviews|prepare_site|prepare_speeches|run_export)'; then
    exit 0
fi

# Run quick DB validation
cd "$(dirname "$0")/../.."

ISSUES=""

# Check 1: Null embeddings in evidence
NULL_EMB=$(uv run python -c "
from esbvaktin.ground_truth.operations import get_connection
conn = get_connection()
result = conn.execute('SELECT COUNT(*) FROM evidence WHERE embedding IS NULL').fetchone()[0]
print(result)
conn.close()
" 2>/dev/null || echo "?")

if [ "$NULL_EMB" != "0" ] && [ "$NULL_EMB" != "?" ]; then
    ISSUES="${ISSUES}WARNING: ${NULL_EMB} evidence entries missing embeddings.\n"
fi

# Check 2: Null embeddings in claims
NULL_CLAIM_EMB=$(uv run python -c "
from esbvaktin.ground_truth.operations import get_connection
conn = get_connection()
result = conn.execute('SELECT COUNT(*) FROM claims WHERE embedding IS NULL AND published = TRUE').fetchone()[0]
print(result)
conn.close()
" 2>/dev/null || echo "?")

if [ "$NULL_CLAIM_EMB" != "0" ] && [ "$NULL_CLAIM_EMB" != "?" ]; then
    ISSUES="${ISSUES}WARNING: ${NULL_CLAIM_EMB} published claims missing embeddings.\n"
fi

# Check 3: Claims referencing non-existent evidence
BROKEN_REFS=$(uv run python -c "
from esbvaktin.ground_truth.operations import get_connection
conn = get_connection()
sql = '''
    SELECT COUNT(DISTINCT c.id) FROM claims c,
    LATERAL UNNEST(c.supporting_evidence || c.contradicting_evidence) AS eid
    LEFT JOIN evidence e ON e.evidence_id = eid
    WHERE e.evidence_id IS NULL AND c.published = TRUE
'''
result = conn.execute(sql).fetchone()[0]
print(result)
conn.close()
" 2>/dev/null || echo "?")

if [ "$BROKEN_REFS" != "0" ] && [ "$BROKEN_REFS" != "?" ]; then
    ISSUES="${ISSUES}WARNING: ${BROKEN_REFS} published claims reference non-existent evidence IDs.\n"
fi

# Report results
if [ -n "$ISSUES" ]; then
    echo "Pre-export validation found issues:"
    echo -e "$ISSUES"
    echo "Export will proceed, but you may want to fix these first."
    echo "Run: uv run python scripts/verify_db.py"
    # Exit 0 to allow export to proceed (warnings, not blockers)
    # Change to exit 2 if you want to block exports with issues
    exit 0
fi

echo "Pre-export validation passed."
exit 0
