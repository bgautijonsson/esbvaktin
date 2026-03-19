#!/usr/bin/env bash
# Post-push CI monitor hook for ESBvaktin.
# Runs after git push commands to show the triggered CI run URL.
#
# Called by Claude Code PostToolUse hook when Bash commands match git push.
# Reads tool input from stdin, checks if the command was a push,
# then fetches the latest CI run URL.

set -euo pipefail

# Parse stdin for the command that was run
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('tool_input', {}).get('command', ''))" 2>/dev/null || echo "")

# Only trigger on git push commands
if ! echo "$COMMAND" | grep -qE '\bgit\s+push\b'; then
    exit 0
fi

# Brief pause for GitHub to register the run
sleep 3

# Fetch the latest workflow run
RUN_INFO=$(gh run list --workflow=ci.yml --limit 1 --json databaseId,status,conclusion,headBranch,event,url 2>/dev/null || echo "")

if [ -z "$RUN_INFO" ] || [ "$RUN_INFO" = "[]" ]; then
    echo "CI: Could not fetch workflow run (gh CLI may need auth or no runs found)."
    exit 0
fi

# Parse run details
STATUS=$(echo "$RUN_INFO" | python3 -c "import sys, json; r=json.load(sys.stdin)[0]; print(r.get('status','unknown'))" 2>/dev/null || echo "unknown")
BRANCH=$(echo "$RUN_INFO" | python3 -c "import sys, json; r=json.load(sys.stdin)[0]; print(r.get('headBranch','?'))" 2>/dev/null || echo "?")
RUN_ID=$(echo "$RUN_INFO" | python3 -c "import sys, json; r=json.load(sys.stdin)[0]; print(r.get('databaseId',''))" 2>/dev/null || echo "")

REPO_URL=$(gh repo view --json url -q .url 2>/dev/null || echo "")

if [ -n "$REPO_URL" ] && [ -n "$RUN_ID" ]; then
    echo "CI: Run #${RUN_ID} triggered on ${BRANCH} (${STATUS}) — ${REPO_URL}/actions/runs/${RUN_ID}"
else
    echo "CI: Run triggered on ${BRANCH} (${STATUS}). Use /ci for details."
fi

exit 0
