# Reassess

Orchestrate the full claim reassessment cycle: identify candidates, prepare context batches, run assessor agents in parallel, and apply updates to the database.

## Usage

```
/reassess                    # Reassess unverifiable + partially supported claims
/reassess unverifiable       # Only unverifiable claims
/reassess partial            # Only partially supported claims
/reassess overconfident      # Only verdict-audit flagged claims
/reassess overconfident 20   # Limit to 20 overconfident claims
/reassess evidence CURR-DATA-007 CURRENCY-DATA-017   # Claims citing these evidence entries
/reassess claims 123 456 789                          # Specific claims by ID
```

## Steps

### Step 1: Clean Previous Output

```bash
uv run python -c "
from pathlib import Path
import shutil

work_dir = Path('data/reassessment')
# Remove stale output files (context files will be regenerated)
for f in work_dir.glob('_assessments_batch_*.json'):
    f.unlink()
    print(f'Cleaned: {f.name}')
for f in work_dir.glob('_context_batch_*.md'):
    f.unlink()
    print(f'Cleaned: {f.name}')
print('Ready for fresh reassessment.')
"
```

### Step 2: Show Current Status

```bash
uv run python scripts/reassess_claims.py status
```

This shows the current verdict distribution and how many claims fall into each reassessment category.

### Step 3: Prepare Batches

Based on the user's argument, run the appropriate prepare command:

- **No argument or "all":** `uv run python scripts/reassess_claims.py prepare`
- **"unverifiable":** `uv run python scripts/reassess_claims.py prepare --only unverifiable`
- **"partial":** `uv run python scripts/reassess_claims.py prepare --only partial`
- **"overconfident":** `uv run python scripts/reassess_claims.py prepare --only overconfident`
- **"overconfident N":** `uv run python scripts/reassess_claims.py prepare --only overconfident --limit N`
- **"evidence ID1 ID2 ...":** `uv run python scripts/reassess_claims.py prepare --evidence ID1 ID2 ...`
- **"claims 123 456 ...":** `uv run python scripts/reassess_claims.py prepare --claims 123 456 ...`

Note the number of batches generated (printed by the script). Each batch produces a `_context_batch_N.md` file in `data/reassessment/`.

If no claims qualify for reassessment, stop and inform the user.

### Step 4: Run Assessment Agents (Parallel)

Launch one `claim-assessor` agent per batch. **Run all batches in parallel** — they are independent.

For each batch file `data/reassessment/_context_reassess_N.md`:

```
Agent: claim-assessor
Prompt: Read data/reassessment/_context_reassess_N.md and assess all claims against the provided evidence.
        Write the flat JSON array to data/reassessment/_assessments_batch_N.json.
```

Wait for all agents to complete.

### Step 5: Verify Agent Output

Check that all expected output files exist:

```bash
uv run python -c "
from pathlib import Path

work_dir = Path('data/reassessment')
contexts = sorted(work_dir.glob('_context_reassess_*.md'))
missing = []
for ctx in contexts:
    batch_num = ctx.stem.split('_')[-1]
    output = work_dir / f'_assessments_batch_{batch_num}.json'
    if not output.exists():
        missing.append(batch_num)
        print(f'MISSING: _assessments_batch_{batch_num}.json')
    else:
        import json
        data = json.loads(output.read_text())
        count = len(data) if isinstance(data, list) else '?'
        print(f'OK: batch {batch_num} — {count} assessments')

if missing:
    print(f'\n{len(missing)} batch(es) need re-running.')
else:
    print(f'\nAll {len(contexts)} batches complete. Ready to update.')
"
```

If any outputs are missing, retry those specific agents (one retry max per batch).

### Step 6: Apply Updates

```bash
uv run python scripts/reassess_claims.py update
```

This parses all `_assessments_batch_N.json` files, compares verdicts with current DB values, and updates changed entries.

### Step 7: Show Results

```bash
uv run python scripts/reassess_claims.py status
```

Compare with the status from Step 2 to show what changed.

Also run the audit to check if the reassessment introduced any new issues:

```bash
uv run python scripts/audit_claims.py status
```

## Notes

- **Batch size is 10 claims per batch** (configured in `reassess_claims.py`). This keeps agent context manageable.
- **Overconfident candidates** come from `audit_claims.py candidates` — claims flagged for sighting drift, contradicting evidence, or substantial caveats.
- **The prepare step auto-cleans stale output.** But Step 1 explicitly cleans to avoid confusion.
- **Agent model:** `claim-assessor` uses opus — this is the hardest reasoning task.
- **Idempotent:** Running `/reassess` multiple times is safe. The update step only changes verdicts when the agent's assessment differs from the DB.
- **Version tracking:** Each claim update increments the `version` field and updates `last_verified`.
