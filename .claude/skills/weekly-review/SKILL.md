# Weekly Review

Generate the weekly overview and editorial for ESBvaktin. Checks inbox coverage first, flags articles that should be analysed before writing the editorial, and gates on user approval before publishing.

## Usage

```
/weekly-review              # Current week (Monday–Sunday containing today)
/weekly-review 2026-W12     # Specific ISO week
/weekly-review last         # Previous week
```

## Steps

### Step 0: Determine Target Week

Parse the argument to find the target week:

- **No argument:** Current ISO week (the Monday–Sunday range containing today)
- **`YYYY-Www`:** Specific ISO week
- **`last`:** Previous ISO week

```bash
uv run python -c "
from datetime import date, timedelta
import sys

arg = 'TARGET_ARG'  # Replace with actual argument or 'current'

today = date.today()
if arg in ('current', ''):
    iso = today.isocalendar()
    week_str = f'{iso[0]}-W{iso[1]:02d}'
elif arg == 'last':
    last_week = today - timedelta(days=7)
    iso = last_week.isocalendar()
    week_str = f'{iso[0]}-W{iso[1]:02d}'
else:
    week_str = arg

# Parse to date range
year, wn = week_str.split('-W')
from datetime import date
jan4 = date(int(year), 1, 4)
week1_mon = jan4 - timedelta(days=jan4.isoweekday() - 1)
monday = week1_mon + timedelta(weeks=int(wn) - 1)
sunday = monday + timedelta(days=6)
print(f'WEEK={week_str}')
print(f'START={monday}')
print(f'END={sunday}')
"
```

Save `WEEK`, `START`, and `END` for subsequent steps.

### Step 1: Check Inbox Coverage

Run the inbox coverage check to see if there are unanalysed articles that should be processed first:

```bash
uv run python -c "
from datetime import date
from scripts.generate_overview import check_inbox_coverage, _print_inbox_check

coverage = check_inbox_coverage(date.fromisoformat('START'), date.fromisoformat('END'))
has_recs = _print_inbox_check(coverage, 'WEEK')
"
```

**If recommendations exist:**

Present them to the user with a clear question:

```markdown
## Inbox Coverage — WEEK

N articles from this week haven't been analysed yet. These would fill topic gaps:

| # | Source | Title | Topics | Priority |
|---|--------|-------|--------|----------|
| 1 | ... | ... | ... | HIGH |

**Options:**
1. Analyse these first (recommended) — I'll run `/analyse-article` on them
2. Skip and proceed with the editorial as-is
3. Pick specific articles to analyse

Which would you prefer?
```

**Wait for the user's response.** Do not proceed until they choose.

- If the user says **analyse** or picks articles: run `/analyse-article` for each, then return to Step 2
- If the user says **skip** or **proceed**: continue to Step 2
- If articles are blog.is posts or clearly low quality, note that in the recommendation ("these are blog posts — likely low value")

**If no recommendations:** proceed to Step 1b.

### Step 1b: Check Claim Publication Gap

The overview generator only counts articles with **published claims**. If many articles have been analysed but their claims are still unpublished, the editorial will undercount articles and misrepresent week-over-week trends. Run this check before generating data:

```bash
uv run python -c "
from src.esbvaktin.ground_truth.operations import get_connection

conn = get_connection()

for label, s, e in [('TARGET', 'START', 'END'), ('PREVIOUS', 'PREV_START', 'PREV_END')]:
    total = conn.execute('''
        SELECT COUNT(DISTINCT source_url) FROM claim_sightings
        WHERE source_date BETWEEN %s AND %s AND source_url IS NOT NULL
    ''', (s, e)).fetchone()[0]
    published = conn.execute('''
        SELECT COUNT(DISTINCT s.source_url) FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.source_date BETWEEN %s AND %s
          AND s.source_url IS NOT NULL
    ''', (s, e)).fetchone()[0]
    gap = total - published
    print(f'{label}: {total} total articles, {published} with published claims (gap: {gap})')

conn.close()
"
```

Replace `START`/`END` with target week dates and `PREV_START`/`PREV_END` with the previous week's dates.

**If gap > 5 for either week:**

Present the numbers to the user:

```markdown
## Claim Publication Gap — WEEK

The overview only counts articles with published claims. There's a significant gap:

| Week | Total articles | With published claims | Gap |
|------|---------------|-----------------------|-----|
| PREV_WEEK | X | Y | Z |
| WEEK | X | Y | Z |

The editorial would say "Y articles this week" instead of the actual X. This will distort week-over-week comparisons.

**Recommended:** Run a full export to publish claims and update the site first:
```bash
./scripts/run_export.sh --site-dir ~/esbvaktin-site
```

**Options:**
1. Run export first, then regenerate overview (recommended)
2. Proceed anyway — the editorial will use published-only numbers
```

**Wait for the user's response.** If they choose to export first, run the export pipeline and then continue to Step 2.

**If gap ≤ 5 for both weeks:** proceed to Step 2.

### Step 2: Check for Existing Overview Data

```bash
uv run python -c "
from pathlib import Path
d = Path('data/overviews/WEEK')
data_exists = (d / 'data.json').exists()
editorial_exists = (d / 'editorial.md').exists()
print(f'data.json: {\"exists\" if data_exists else \"missing\"}')
print(f'editorial.md: {\"exists\" if editorial_exists else \"missing\"}')
"
```

- If `editorial.md` already exists: inform the user and ask if they want to regenerate
- If `data.json` exists but no editorial: skip to Step 4 (context prep)
- If neither exists: continue to Step 3

### Step 3: Generate Overview Data

```bash
uv run python scripts/generate_overview.py --week WEEK --force --skip-inbox-check
```

The `--skip-inbox-check` flag is safe here because we already ran the check in Step 1. The `--force` flag handles the case where data.json exists from a previous run.

Note the key numbers printed (articles, claims, topics, diversity score).

### Step 4: Prepare Editorial Context

```bash
uv run python scripts/prepare_overview_context.py WEEK
```

This generates `data/overviews/WEEK/_context_is.md` with all the structured data the editorial agent needs.

### Step 5: Write Editorial

Launch the editorial-writer agent:

```
Agent: editorial-writer
Prompt: Read data/overviews/WEEK/_context_is.md and write the Icelandic weekly editorial.
        Write the result to data/overviews/WEEK/editorial.md.
```

After the agent completes, run a grammar check:

```bash
uv run python scripts/correct_icelandic.py check-editorial data/overviews/WEEK/editorial.md --fix
```

Apply any suggested fixes.

### Step 5b: Validate Editorial Against Claims

Run the editorial validator to cross-reference claims and entities:

```bash
uv run python scripts/validate_editorial.py data/overviews/WEEK/editorial.md --week WEEK
```

The validator flags:
- **HIGH:** Hearsay claims presented without attribution markers (e.g., "sögðu", "ónafngreindir")
- **MEDIUM:** Low-confidence claims (< 0.6) presented without uncertainty language

**If HIGH flags exist:** You MUST fix the editorial before presenting it to the user. Rewrite the flagged passages with proper attribution, then re-run the validator to confirm.

**If only MEDIUM flags:** Include them in the review presentation so the user can decide. The editorial may already handle these correctly — the validator uses simple heuristics.

**If no flags:** Proceed to Step 6.

### Step 6: Present Editorial for Review

**This is a mandatory gate.** Read the editorial and present the full text to the user:

```markdown
## Weekly Editorial — WEEK

[Full text of the editorial]

---

**Stats:** N words, M Málstaður corrections, K grammar issues
**Validation:** [N flags / clean pass]
**Coverage:** X articles analysed, Y topics active, Z entities

Does this look good? I can:
1. Push it to the site as-is
2. Regenerate with different emphasis
3. Edit specific sections
```

If there were MEDIUM validation flags, show them below the stats:

```markdown
**Validation notes (MEDIUM):**
- Claim 123: Low confidence (0.45) — check attribution in paragraph about X
```

**Wait for explicit approval.** Never proceed to Step 7 without the user confirming.

### Step 7: Export and Deploy

After user approval:

```bash
uv run python scripts/export_overviews.py --site-dir ~/esbvaktin-site
```

Then inform the user the overview is exported and ready. **Do not commit or push** — the user may want to bundle this with other changes or review the site build first. If they ask to push, follow normal commit workflow.

## Notes

- **The editorial review gate (Step 6) is non-negotiable.** Editorials are public-facing Icelandic prose that represent the project's voice. Never auto-push.
- **Inbox check (Step 1) is advisory.** The user decides whether to analyse more articles. Blog.is posts are often low quality — note this when recommending.
- **Publication gap check (Step 1b) prevents misleading numbers.** The overview generator's SQL joins on `published = TRUE`, so articles with only unpublished claims are invisible. A large gap (>5) means the editorial will significantly undercount articles and distort trends. The fix is to run the full export pipeline, which publishes claims via `export_claims.py`.
- **Regeneration is safe.** Steps 3–5 can be re-run if the user wants a different editorial. The `--force` flag on `generate_overview.py` handles overwrites.
- **The editorial-writer agent uses opus** — this is the most expensive agent. It reads exemplars from `knowledge/exemplars_editorial_is.md` and uses MCP tools for grammar.
- **Timing:** The full pipeline (Steps 3–5) takes ~3 minutes. The inbox check (Step 1) is instant.
- **Best run on Sunday or Monday** — ensures the full week's articles are available. Running mid-week will produce a partial overview.
