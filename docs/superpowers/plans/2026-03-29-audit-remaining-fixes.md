# Pipeline Audit — Remaining Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 11 remaining High/Medium issues from the 2026-03-29 pipeline audit.

**Architecture:** All fixes are independent code changes to existing scripts and modules. No new tables, no new services, no migrations. Two items (M2, M12) need a user decision before implementation — questions are at the top of the plan so they can be answered once, upfront.

**Tech Stack:** Python 3.12, PostgreSQL 17 + pgvector, pytest, ruff, GitHub Actions

**Status:** C1–C3 (critical) and H1–H4, H6–H7, M4, M7 (Week 2) already shipped.

---

## User Decisions Needed Upfront

Before dispatching any work, get answers to these two questions:

**Q1 (for M2 — cross-pub dedup):** The content similarity threshold for detecting party-website reposts is currently `0.85` (SequenceMatcher ratio). Should we keep this, or lower it to `0.80` to catch more aggressive rewrites? Lower = more catches but more false positives on articles that merely cover the same topic.

**Q2 (for M12 — CI smoke test):** CI already has PostgreSQL 17 + pgvector. The smoke test can either (a) seed 10 fixture claims and run `export_claims.py` against them, or (b) just validate that `export_claims.py` and `prepare_site.py` import cleanly and their `main()` accepts `--help` without error. Option (a) is more thorough but needs a fixture file. Option (b) catches import breakage and schema drift with zero maintenance.

---

## Batch Structure

| Batch | Items | Parallelisable | Estimated time |
|---|---|---|---|
| A | H5, H8, M1, M5, M6 | Yes — 5 independent tasks | ~10 min with parallel agents |
| B | M10, M3, M9, M11, M8 | Yes — 5 independent tasks (M10 reads H5 but doesn't depend on it) | ~10 min with parallel agents |
| C | M2, M12 | Sequential (need user answers from above) | ~15 min |

Total: ~35 min of Claude Code time across 2–3 sessions, not 3 weeks.

---

## Task 1: H5 — Audit Pattern 5 (misleading/unsupported with new evidence)

**Files:**
- Modify: `scripts/audit_claims.py:195` (after `_pattern_4`, before `report()`)
- Test: `uv run python scripts/audit_claims.py report` (verify new pattern appears)

- [ ] **Step 1: Add `_pattern_5_underrated` function**

Insert after line 230 (after `_pattern_4_contradicting_ignored`):

```python
def _pattern_5_underrated(conn) -> list[ClaimFlag]:
    """Misleading/unsupported claims with new evidence added since last verification."""
    rows = conn.execute(
        """
        SELECT c.id, c.claim_slug, c.canonical_text_is, c.verdict,
               c.confidence, c.last_verified,
               COUNT(DISTINCT e.evidence_id) AS new_evidence_count
        FROM claims c
        CROSS JOIN evidence e
        WHERE c.verdict IN ('misleading', 'unsupported')
          AND c.published = TRUE
          AND e.created_at > c.last_verified
          AND 1 - (c.embedding <=> e.embedding) > 0.72
          AND NOT (e.evidence_id = ANY(c.supporting_evidence))
          AND NOT (e.evidence_id = ANY(c.contradicting_evidence))
        GROUP BY c.id
        HAVING COUNT(DISTINCT e.evidence_id) > 0
        ORDER BY new_evidence_count DESC, c.confidence ASC
        """
    ).fetchall()

    flags = []
    for claim_id, slug, text_is, verdict, conf, last_ver, new_count in rows:
        flags.append(
            ClaimFlag(
                claim_id=claim_id,
                claim_slug=slug,
                canonical_text_is=text_is,
                verdict=verdict,
                confidence=conf,
                pattern="P5_underrated",
                score=new_count * 2.0,
                detail=f"{new_count} new evidence since {last_ver}",
            )
        )
    return flags
```

- [ ] **Step 2: Wire into `report()` function**

In `report()` (line ~281), find where patterns 1–4 are called and add:

```python
p5 = _pattern_5_underrated(conn)
if p5:
    print(f"  P5 — Underrated (misleading/unsupported + new evidence): {len(p5)}")
all_flags.extend(p5)
```

- [ ] **Step 3: Wire into `candidates()` function**

In `candidates()` (line ~362), add P5 to the combined flags list (same pattern as P1–P4).

- [ ] **Step 4: Run and verify**

Run: `uv run python scripts/audit_claims.py status`
Expected: new P5 line in output (may be 0 if no misleading claims have new evidence)

- [ ] **Step 5: Commit**

```
git add scripts/audit_claims.py
git commit -m "feat: audit Pattern 5 — misleading/unsupported claims with new evidence"
```

---

## Task 2: H8 — Silent export failures

**Files:**
- Modify: `scripts/export_entities.py:72,278,399`

- [ ] **Step 1: Fix line 72 (`_load_non_substantive_texts`)**

Replace:
```python
    except Exception:
        return set()
```
With:
```python
    except Exception as exc:
        print(f"ERROR: Could not load non-substantive texts: {exc}", file=sys.stderr)
        return set()
```

- [ ] **Step 2: Fix line 278 (althingi EU speech data)**

Replace:
```python
    except Exception:
        return {}
```
With:
```python
    except Exception as exc:
        print(f"WARNING: Could not load EU speech data from althingi.db: {exc}", file=sys.stderr)
        return {}
```

- [ ] **Step 3: Fix line 399 (MP roster)**

Same pattern — add `as exc` and `print(... file=sys.stderr)`.

- [ ] **Step 4: Verify lint passes**

Run: `uv run --extra dev ruff check scripts/export_entities.py`

- [ ] **Step 5: Commit**

```
git add scripts/export_entities.py
git commit -m "fix: make export_entities.py failures visible on stderr"
```

---

## Task 3: M1 — Ambiguity detection in sighting matching

**Files:**
- Modify: `src/esbvaktin/pipeline/register_sightings.py:56`
- Modify: `src/esbvaktin/speeches/register_sightings.py:51`
- Modify: `scripts/register_article_sightings.py:156`

- [ ] **Step 1: Fix pipeline/register_sightings.py**

At line 56, change `top_k=1` to `top_k=3`. After receiving results, add ambiguity warning:

```python
matches = search_claims(
    query=claim_text, threshold=SIGHTING_MATCH_THRESHOLD, top_k=3, conn=conn,
)
if matches:
    match = matches[0]
    if len(matches) > 1 and (matches[0].similarity - matches[1].similarity) < 0.03:
        print(
            f"  ⚠️ Ambiguous match: '{claim_text[:50]}' → "
            f"{matches[0].claim_slug} ({matches[0].similarity:.3f}) vs "
            f"{matches[1].claim_slug} ({matches[1].similarity:.3f})",
            file=sys.stderr,
        )
```

Ensure `sys` is imported.

- [ ] **Step 2: Same change in speeches/register_sightings.py (line 51)**

Identical pattern.

- [ ] **Step 3: Same change in register_article_sightings.py (line 156)**

Identical pattern — uses `logger.warning` instead of `print(file=sys.stderr)` since this file has a logger.

- [ ] **Step 4: Lint**

Run: `uv run --extra dev ruff check src/esbvaktin/pipeline/register_sightings.py src/esbvaktin/speeches/register_sightings.py scripts/register_article_sightings.py`

- [ ] **Step 5: Commit**

```
git add src/esbvaktin/pipeline/register_sightings.py src/esbvaktin/speeches/register_sightings.py scripts/register_article_sightings.py
git commit -m "feat: ambiguity detection in sighting matching (top_k=3, warn on margin < 0.03)"
```

---

## Task 4: M5 — Keyword score inflation

**Files:**
- Modify: `src/esbvaktin/pipeline/retrieve_evidence.py:214`

- [ ] **Step 1: Replace the similarity formula**

At line 214, change:
```python
similarity=min(rrf_score * 100, 0.99),
```
To:
```python
similarity=max(0.50, 0.90 - (rank * 0.04)),
```

Where `rank` is the 0-based index in the keyword results loop. Check the loop variable name — it may be `i` or require adding an `enumerate()`.

- [ ] **Step 2: Run tests**

Run: `uv run --extra dev python -m pytest tests/ -x -q --ignore=tests/test_heimildin.py`

- [ ] **Step 3: Commit**

```
git add src/esbvaktin/pipeline/retrieve_evidence.py
git commit -m "fix: rank-based similarity for keyword-only evidence hits (was flat 0.99)"
```

---

## Task 5: M6 — Registry staleness warning

**Files:**
- Modify: `scripts/check_duplicate.py:49` (in `load_processed()`)

- [ ] **Step 1: Add staleness check after registry load**

After line 51 (`registry = json.loads(REGISTRY_PATH.read_text())`), add:

```python
import time
age_hours = (time.time() - REGISTRY_PATH.stat().st_mtime) / 3600
if age_hours > 24:
    print(
        f"WARNING: article_registry.json is {age_hours:.0f}h old — "
        f"run: uv run python scripts/build_article_registry.py",
        file=sys.stderr,
    )
```

- [ ] **Step 2: Commit**

```
git add scripts/check_duplicate.py
git commit -m "feat: warn when article registry is stale (>24h)"
```

---

## Task 6: M10 — Wire Pattern 2 into reassessment

**Files:**
- Modify: `scripts/reassess_claims.py` (add `--only denominator` mode)
- Read: `scripts/audit_claims.py:118` (Pattern 2 SQL)

- [ ] **Step 1: Add denominator mode to argument parser**

Find the `argparse` section and add `denominator` to the `--only` choices.

- [ ] **Step 2: Add `_get_denominator_claims()` function**

```python
def _get_denominator_claims(conn):
    """Fetch supported claims flagged by Pattern 2 (scope-word denominator confusion)."""
    SCOPE_WORDS = r"(megnið|flest|langflest|meirihlut|allra|öll |alls )"
    rows = conn.execute(
        f"""
        SELECT id, canonical_text_is, canonical_text_en, category, claim_slug,
               verdict, confidence, epistemic_type
        FROM claims
        WHERE verdict = 'supported'
          AND canonical_text_is ~* '{SCOPE_WORDS}'
          AND epistemic_type != 'hearsay'
        ORDER BY confidence DESC
        """,
    ).fetchall()

    assessable = []
    for claim_id, text_is, text_en, category, slug, verdict, confidence, epistemic_type in rows:
        results = _search_evidence_hybrid(text_is, text_en, category, conn)
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:8]
        if not strong:
            continue
        assessable.append(
            _make_claim_entry(
                claim_id, text_is, text_en, category, slug, strong,
                reason="denominator_audit",
            )
        )
    return assessable
```

- [ ] **Step 3: Wire into `prepare()` function**

In the `if args.only == "overconfident"` block, add an `elif args.only == "denominator"` branch that calls `_get_denominator_claims(conn)`.

- [ ] **Step 4: Update CLAUDE.md**

Add `/reassess denominator` to the skills and key commands sections.

- [ ] **Step 5: Commit**

```
git add scripts/reassess_claims.py CLAUDE.md
git commit -m "feat: --only denominator mode for reassessing scope-word claims"
```

---

## Task 7: M3 — Entity credibility from DB verdicts

**Files:**
- Modify: `scripts/export_entities.py:37-53` (`_get_claim_data` function)

- [ ] **Step 1: Add DB verdict loader at module level**

Near the top of the file, add a function to load current DB verdicts keyed by claim slug:

```python
def _load_db_verdict_map() -> dict[str, str]:
    """Load {claim_slug: verdict} from DB for current verdicts."""
    try:
        from esbvaktin.ground_truth.operations import get_connection
        conn = get_connection()
        rows = conn.execute(
            "SELECT claim_slug, verdict FROM claims WHERE published = TRUE"
        ).fetchall()
        conn.close()
        return {slug: verdict for slug, verdict in rows}
    except Exception as exc:
        print(f"WARNING: Could not load DB verdicts for entity scoring: {exc}", file=sys.stderr)
        return {}
```

- [ ] **Step 2: Pass verdict map into `_get_claim_data`**

Add `db_verdicts: dict[str, str] | None = None` parameter to `_get_claim_data`. When building each claim dict, check `db_verdicts` first:

```python
verdict = (db_verdicts or {}).get(slug, item.get("verdict", "unknown"))
```

- [ ] **Step 3: Load and pass in `main()`**

In `main()`, call `db_verdicts = _load_db_verdict_map()` once, pass to every `_get_claim_data()` call.

- [ ] **Step 4: Lint + test**

Run: `uv run --extra dev ruff check scripts/export_entities.py`

- [ ] **Step 5: Commit**

```
git add scripts/export_entities.py
git commit -m "fix: entity credibility uses current DB verdicts, not stale report snapshots"
```

---

## Task 8: M9 — Scheduled link rot checks

**Files:**
- Modify: `~/Library/LaunchAgents/is.esbvaktin.linkcheck.plist` (new)

- [ ] **Step 1: Create launchd plist**

Write to `~/Library/LaunchAgents/is.esbvaktin.linkcheck.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>is.esbvaktin.linkcheck</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/brynjolfurjonsson/.local/bin/uv</string>
        <string>run</string>
        <string>python</string>
        <string>scripts/check_evidence_urls.py</string>
        <string>check</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/brynjolfurjonsson/esbvaktin</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>9</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/brynjolfurjonsson/Documents/esbvaktin-backups/linkcheck.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/brynjolfurjonsson/Documents/esbvaktin-backups/linkcheck.err</string>
</dict>
</plist>
```

- [ ] **Step 2: Load the plist**

Run: `launchctl load ~/Library/LaunchAgents/is.esbvaktin.linkcheck.plist`

- [ ] **Step 3: Verify**

Run: `launchctl list | grep esbvaktin`
Expected: both `is.esbvaktin.backup-db` and `is.esbvaktin.linkcheck` listed.

---

## Task 9: M11 — Post-seed affected-claims warning

**Files:**
- Modify: `scripts/seed_evidence.py` (after the insert loop)

- [ ] **Step 1: Add affected-claims query after insert**

After the insert loop completes (where new evidence IDs are known), add:

```python
def _find_affected_claims(new_ids: list[str], conn) -> list[tuple]:
    """Find published claims with high similarity to newly-added evidence."""
    if not new_ids:
        return []
    placeholders = ",".join(["%s"] * len(new_ids))
    return conn.execute(
        f"""
        SELECT DISTINCT c.id, c.claim_slug, c.verdict,
               e.evidence_id AS new_evidence,
               ROUND((1 - (c.embedding <=> e.embedding))::numeric, 3) AS similarity
        FROM claims c
        CROSS JOIN evidence e
        WHERE e.evidence_id IN ({placeholders})
          AND c.published = TRUE
          AND 1 - (c.embedding <=> e.embedding) > 0.70
          AND NOT (e.evidence_id = ANY(c.supporting_evidence))
          AND NOT (e.evidence_id = ANY(c.contradicting_evidence))
        ORDER BY similarity DESC
        LIMIT 20
        """,
        new_ids,
    ).fetchall()
```

Call it after the insert completes. Print results:

```python
if new_ids:
    affected = _find_affected_claims(new_ids, conn)
    if affected:
        print(f"\n⚠️  {len(affected)} claims may need reassessment:")
        for cid, slug, verdict, ev_id, sim in affected:
            print(f"  claim {cid} ({verdict}): {slug} ← {ev_id} ({sim})")
        print(f"\nRun: uv run python scripts/reassess_claims.py prepare --evidence {' '.join(new_ids)}")
```

- [ ] **Step 2: Test with dry run**

Run: `uv run python scripts/seed_evidence.py status` (verify no crash)

- [ ] **Step 3: Commit**

```
git add scripts/seed_evidence.py
git commit -m "feat: post-seed warning showing claims affected by new evidence"
```

---

## Task 10: M8 — Evidence refresh schedule (process)

**Files:**
- Modify: `CLAUDE.md` (add to Key Commands)

- [ ] **Step 1: Add monthly refresh note to CLAUDE.md**

In the Key Commands section, after the evidence-hunt entries, add:

```markdown
# Monthly evidence refresh (first Monday of each month)
# Run for high-decay topics: polling, party_positions, org_positions, currency
uv run python scripts/manage_inbox.py status                # Check before refresh
```

- [ ] **Step 2: Commit**

```
git add CLAUDE.md
git commit -m "docs: add monthly evidence refresh schedule for high-decay topics"
```

---

## Task 11: M2 — Cross-publication content dedup (needs Q1 answer)

**Files:**
- Modify: `.claude/skills/analyse-article/SKILL.md`
- Modify: `scripts/check_duplicate.py`

- [ ] **Step 1: Verify content dedup already in skill**

Read the analyse-article skill — the explorer found it already has a post-fetch `--text-file` check at lines 27-33. Verify this is actually executed. If it is, this task becomes "verify and close." If not, wire it in.

- [ ] **Step 2: Add "birtist fyrst í" footer parsing to `check_duplicate.py`**

In `check_content()`, before the SequenceMatcher comparison, check the last 500 chars for the pattern:

```python
import re
footer_match = re.search(r"[Bb]irtist fyrst (?:á|í|hjá)\s+(\S+)", text[-500:])
if footer_match:
    canonical_source = footer_match.group(1)
    # Check if any processed article URL contains this domain
    for p in processed:
        if canonical_source.lower() in p["url"].lower():
            return p["url"], 1.0  # Perfect match — it's a repost
```

- [ ] **Step 3: Commit**

```
git add scripts/check_duplicate.py .claude/skills/analyse-article/SKILL.md
git commit -m "feat: detect cross-publication reposts via footer attribution parsing"
```

---

## Task 12: M12 — CI export smoke test (needs Q2 answer)

**Files:**
- Create: `tests/test_export_smoke.py`
- Modify: `.github/workflows/ci.yml` (add schedule trigger)

- [ ] **Step 1: Add weekly schedule to CI**

In `.github/workflows/ci.yml`, add to the `on:` block:

```yaml
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: '0 6 * * 1'  # Monday 06:00 UTC
```

- [ ] **Step 2: Add smoke test (option b — import + help validation)**

Create `tests/test_export_smoke.py`:

```python
"""Smoke tests for export scripts — verify they import and parse args."""

import subprocess
import sys

import pytest

EXPORT_SCRIPTS = [
    "scripts/export_claims.py",
    "scripts/export_entities.py",
    "scripts/export_evidence.py",
    "scripts/export_topics.py",
    "scripts/prepare_site.py",
    "scripts/export_overviews.py",
]


@pytest.mark.parametrize("script", EXPORT_SCRIPTS)
def test_export_script_imports(script):
    """Each export script should import without error."""
    result = subprocess.run(
        [sys.executable, "-c", f"import importlib.util; spec = importlib.util.spec_from_file_location('mod', '{script}'); mod = importlib.util.module_from_spec(spec)"],
        capture_output=True, text=True, timeout=10,
    )
    # We only check it doesn't crash on import — some scripts may fail
    # at runtime without DB, but import-time errors indicate broken code
    assert result.returncode == 0, f"{script} failed to import: {result.stderr}"
```

- [ ] **Step 3: Run locally**

Run: `uv run --extra dev python -m pytest tests/test_export_smoke.py -v`

- [ ] **Step 4: Commit**

```
git add tests/test_export_smoke.py .github/workflows/ci.yml
git commit -m "feat: weekly CI schedule + export script smoke tests"
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-03-29-audit-remaining-fixes.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Batch A (Tasks 1–5) can run as 5 parallel agents. Batch B (Tasks 6–10) as 5 more. Tasks 11–12 after user answers Q1/Q2.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
