# Tidy

Audit the codebase for quality, consistency, and maintainability. Identifies issues and suggests targeted fixes.

## Usage

```
/tidy                   # Full audit
/tidy lint              # Ruff lint only
/tidy duplication       # Find duplicated patterns
/tidy docs              # Check CLAUDE.md accuracy
/tidy tests             # Run tests and report
```

## Steps

### Step 1: Ruff Lint Check

```bash
uv run --extra dev ruff check src/ scripts/ --statistics
```

If there are fixable issues:
```bash
uv run --extra dev ruff check --fix src/ scripts/
```

Report the count and categories of remaining issues (if any).

### Step 2: Run Tests

```bash
uv run --extra dev python -m pytest --tb=short -q
```

Report pass/fail counts. If any failures, show the failing test names and brief error messages.

### Step 3: Check for Common Code Issues

Search for patterns that indicate maintenance debt:

**Hardcoded credentials or connection strings:**
```
Grep for: postgresql://
Exclude: CLAUDE.md, settings.local.json, *.md (documentation)
Flag any hardcoded credentials in .py files — should use get_connection()
```

**sys.path hacks:**
```
Grep for: sys.path.insert|sys.path.append
Flag any remaining sys.path manipulation — imports should work without hacks
```

**Bare except clauses:**
```
Grep for: except:$|except:\s*$
Flag overly broad exception handling
```

**TODO/FIXME/HACK comments:**
```
Grep for: TODO|FIXME|HACK|XXX
List all with file:line context for triage
```

**Print statements in library code (not scripts):**
```
Grep for print( in src/esbvaktin/ (excluding __main__.py)
Library code should use logging, not print()
```

### Step 4: Check Documentation Accuracy

Verify that CLAUDE.md reflects the current state:

1. **Script commands** — check that all commands listed in CLAUDE.md's "Key Commands" actually work. **Use the Glob tool** to check for `scripts/*.py` and compare against the expected list. Do not use shell `for` loops or `[ -f ]` tests.

2. **DB schema** — verify table/column names mentioned in CLAUDE.md match the actual schema. **Use Python with `get_connection()`**, not `psql`:
   ```bash
   uv run python -c "
   from dotenv import load_dotenv; load_dotenv()
   from esbvaktin.ground_truth.operations import get_connection
   conn = get_connection()
   tables = conn.execute(\"SELECT tablename FROM pg_tables WHERE schemaname='public'\").fetchall()
   views = conn.execute(\"SELECT viewname FROM pg_views WHERE schemaname='public'\").fetchall()
   print('Tables:', [t[0] for t in tables])
   print('Views:', [v[0] for v in views])
   conn.close()
   "
   ```

3. **Agent definitions** — verify all 10 agents listed in CLAUDE.md exist. **Use the Glob tool** with pattern `.claude/agents/*.md`.

4. **Skill definitions** — verify all skills listed exist. **Use the Glob tool** with pattern `.claude/skills/*/SKILL.md`.

**Never use `ls`, `psql`, shell `for` loops, or `[ -f ]` tests** — these trigger permission prompts.

### Step 5: Find Duplicated Patterns

Look for code that could benefit from consolidation (but be conservative — only flag if 3+ copies exist):

**DB connection boilerplate:**
```
Grep for: get_connection() in scripts/
Count how many scripts have their own connection management
```

**Verdict distribution queries:**
```
Grep for: GROUP BY verdict in scripts/
Check if they could share a utility function
```

**Semantic search + dedup pattern:**
```
Grep for: search_evidence.*top_k in scripts/
Check for the dual IS+EN search pattern (_search_evidence_dual)
```

**JSON extraction with quote sanitisation:**
```
Grep for: _extract_json in scripts/ and src/
Verify all agent output parsing goes through this function
```

Report findings as a prioritised list, distinguishing between:
- **Should fix now** — bugs, security issues, broken imports
- **Worth consolidating** — 3+ copies of the same pattern
- **Leave alone** — similar but domain-specific code that would create leaky abstractions

### Step 6: Present Report

Format as a clean terminal report:

```
═══ ESBvaktin Tidy Report ═══

LINT
  X issues found (Y auto-fixed)
  [remaining issues if any]

TESTS
  X passed, Y failed, Z skipped

CODE QUALITY
  [issues found, grouped by severity]

DOCUMENTATION
  [mismatches between CLAUDE.md and reality]

DUPLICATION
  [patterns found 3+ times with file locations]

RECOMMENDED ACTIONS
  1. [highest priority fix]
  2. [next priority]
  ...
```

## Notes

- **Conservative approach.** This skill identifies issues but only auto-fixes lint (ruff --fix). Everything else requires user approval.
- **Don't over-refactor.** The goal is to flag genuine issues, not to rewrite working code. Three similar lines is fine; three similar 50-line blocks is a consolidation opportunity.
- **Skip false positives.** Print statements in scripts/ are intentional (CLI output). Print in src/ library code is the issue.
- **CLAUDE.md updates** — if mismatches are found, suggest specific edits rather than rewriting the whole file.
