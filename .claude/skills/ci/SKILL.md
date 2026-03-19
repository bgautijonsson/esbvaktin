# CI

Monitor GitHub Actions CI runs. Shows status, investigates failures, and downloads relevant logs.

## Usage

```
/ci                     # Latest run status
/ci list                # Recent runs (last 10)
/ci <run-id>            # Details for specific run
/ci failures            # Show only failed runs
/ci logs <run-id>       # Download and show failure logs
```

## Steps

### Step 1: Parse Arguments

Determine the subcommand from the user's input:
- No args or empty → show latest run
- `list` → show recent runs
- `failures` → show recent failed runs
- A number → show details for that run ID
- `logs` followed by a number → download and show logs for that run

### Step 2: Execute

#### Latest run (default)

```bash
gh run list --workflow=ci.yml --limit 1 --json databaseId,status,conclusion,headBranch,headSha,event,createdAt,updatedAt,url
```

Show a formatted summary:
```
═══ CI Status ═══
Run #ID on BRANCH (EVENT) — STATUS
  Started: TIME
  SHA: SHORT_SHA
  URL: LINK
```

If the run is `in_progress`, offer to watch it:
```bash
gh run watch RUN_ID
```

If the run `completed` with `failure`, automatically proceed to Step 3.

#### List recent runs

```bash
gh run list --workflow=ci.yml --limit 10 --json databaseId,status,conclusion,headBranch,headSha,createdAt
```

Format as a table:
```
═══ Recent CI Runs ═══
 #ID     Branch     Status        SHA       Time
 12345   main       success       abc1234   2h ago
 12344   feat/x     failure       def5678   5h ago
 ...
```

#### Failures only

```bash
gh run list --workflow=ci.yml --limit 10 --status failure --json databaseId,conclusion,headBranch,headSha,createdAt
```

Same table format, filtered to failures.

#### Specific run

```bash
gh run view RUN_ID --json databaseId,status,conclusion,headBranch,headSha,event,createdAt,updatedAt,jobs,url
```

Show full details including per-job status.

### Step 3: Investigate Failures

When a run has failed (either detected automatically or via `logs` subcommand):

```bash
gh run view RUN_ID --log-failed
```

This downloads only the failed step logs. Parse the output to find:
1. Which job failed (lint or test)
2. The specific error messages
3. Suggested fixes

Format the failure report:
```
═══ CI Failure Report ═══
Run #ID on BRANCH — failed

FAILED JOB: test
  Step: Run pytest
  Error: ...

  Likely cause: ...
  Suggested fix: ...
```

For **lint failures**, show the ruff errors and suggest `uv run --extra dev ruff check --fix src/ scripts/`.

For **test failures**, show the pytest output with failing test names and error messages. If it's a DB-related failure, note that CI uses a fresh PostgreSQL with pgvector (no seed data).

### Step 4: Offer Next Steps

Based on the findings, suggest concrete actions:
- If lint failed: offer to auto-fix with ruff
- If tests failed: offer to run the failing tests locally
- If the run is in progress: offer to wait for completion
- If everything passed: just confirm all green

## Notes

- This skill is **read-only** — it never modifies code or re-triggers runs.
- Uses `gh` CLI exclusively. If `gh` is not authenticated, show a clear error.
- Time displays should be relative (e.g., "2h ago") for readability.
- The CI workflow has two jobs: `lint` (ruff) and `test` (pytest with pgvector).
- CI runs on push to main and on pull requests to main.
