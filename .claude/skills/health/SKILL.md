# Health

Unified project health dashboard. Consolidates 18+ separate status commands into one view.

## Usage

```
/health                  # Full dashboard
/health db               # Database section only
/health pipeline         # Pipeline/inbox section only
/health audit            # Audit signals only
/health icelandic        # Icelandic quality only
```

## Steps

### Step 1: Database Health

Run these queries to get core DB stats:

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from esbvaktin.ground_truth.operations import get_connection

conn = get_connection()

# Core counts
evidence_total = conn.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
evidence_null_emb = conn.execute('SELECT COUNT(*) FROM evidence WHERE embedding IS NULL').fetchone()[0]
claims_total = conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0]
claims_published = conn.execute('SELECT COUNT(*) FROM claims WHERE published = TRUE').fetchone()[0]
claims_substantive = conn.execute('SELECT COUNT(*) FROM claims WHERE substantive = TRUE').fetchone()[0]
sightings_total = conn.execute('SELECT COUNT(*) FROM claim_sightings').fetchone()[0]
distinct_sources = conn.execute('SELECT COUNT(DISTINCT source_url) FROM claim_sightings').fetchone()[0]

# Verdict distribution (published only)
verdicts = conn.execute('''
    SELECT verdict, COUNT(*) FROM claims
    WHERE published = TRUE
    GROUP BY verdict ORDER BY COUNT(*) DESC
''').fetchall()

# Stale evidence (90+ days)
stale = conn.execute('''
    SELECT COUNT(*) FROM evidence
    WHERE last_verified < CURRENT_DATE - INTERVAL '90 days'
''').fetchone()[0]

# Evidence by topic
topics = conn.execute('''
    SELECT topic, COUNT(*) FROM evidence
    GROUP BY topic ORDER BY COUNT(*) DESC
''').fetchall()

print('=== DATABASE ===')
print(f'Evidence: {evidence_total} entries ({evidence_null_emb} missing embeddings, {stale} stale)')
print(f'Claims: {claims_total} total ({claims_published} published, {claims_substantive} substantive)')
print(f'Sightings: {sightings_total} across {distinct_sources} sources')
print()
print('Verdict distribution (published):')
for v, c in verdicts:
    print(f'  {v}: {c}')
print()
print('Evidence by topic:')
for t, c in topics:
    print(f'  {t}: {c}')

conn.close()
"
```

If the user only asked for `/health db`, stop here. Otherwise continue.

### Step 2: Audit Signals

```bash
uv run python scripts/audit_claims.py status
```

This shows counts for the 4 audit patterns (overconfident, denominator confusion, sighting drift, contradicting evidence ignored).

### Step 3: Pipeline & Inbox Status

```bash
uv run python scripts/manage_inbox.py status
```

```bash
uv run python scripts/build_article_registry.py --status
```

```bash
uv run python -c "
from esbvaktin.utils.frettasafn_state import consumer_summary
counts = consumer_summary('esbvaktin')
total = sum(counts.values())
print('=== CONSUMER_STATE (esbvaktin) ===')
print(f'  Total tracked: {total}')
for state in ('processed', 'rejected', 'skipped', 'in_progress'):
    if state in counts:
        print(f'  {state}: {counts[state]}')
"
```

The `consumer_state` totals (Phase 3 — written by `register_article_sightings.py` and `manage_inbox.py reject/skip`) should be roughly aligned with the registry's processed count. Divergence means either fresh activity hasn't propagated, or the registry is stale.

### Step 4: Icelandic Quality

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from esbvaktin.ground_truth.operations import get_connection

conn = get_connection()

# IS summary coverage
total = conn.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
has_is = conn.execute('SELECT COUNT(*) FROM evidence WHERE statement_is IS NOT NULL').fetchone()[0]
has_caveats_is = conn.execute('SELECT COUNT(*) FROM evidence WHERE caveats_is IS NOT NULL').fetchone()[0]
has_caveats = conn.execute('SELECT COUNT(*) FROM evidence WHERE caveats IS NOT NULL AND caveats != \'\'').fetchone()[0]

print('=== ICELANDIC QUALITY ===')
print(f'statement_is coverage: {has_is}/{total} ({100*has_is/total:.0f}%)')
print(f'caveats_is coverage: {has_caveats_is}/{has_caveats} (of entries with EN caveats)')

# Claims IS coverage
claims_total = conn.execute('SELECT COUNT(*) FROM claims WHERE published = TRUE').fetchone()[0]
claims_is = conn.execute('SELECT COUNT(*) FROM claims WHERE published = TRUE AND canonical_text_is IS NOT NULL').fetchone()[0]
print(f'Published claims with IS text: {claims_is}/{claims_total}')

conn.close()
"
```

### Step 5: Export Coverage

```bash
uv run python -c "
from pathlib import Path
import json

# Check site data freshness
site_dir = Path.home() / 'esbvaktin-site'
data_files = {
    'claims.json': 'assets/data/claims.json',
    'evidence.json': 'assets/data/evidence.json',
    'entities.json': 'assets/data/entities.json',
    'reports': '_data/reports',
}

print('=== EXPORT COVERAGE ===')
for label, rel_path in data_files.items():
    p = site_dir / rel_path
    if p.is_dir():
        count = len(list(p.glob('*.json')))
        print(f'  {label}: {count} files')
    elif p.exists():
        data = json.loads(p.read_text())
        count = len(data) if isinstance(data, list) else 'object'
        import os, time
        mtime = os.path.getmtime(p)
        age = (time.time() - mtime) / 3600
        print(f'  {label}: {count} entries (updated {age:.0f}h ago)')
    else:
        print(f'  {label}: MISSING')
"
```

### Step 6: Present Dashboard

Combine all output into a formatted dashboard. Use terminal output, not Obsidian — this is a quick status check.

Format as:

```
═══ ESBvaktin Health — YYYY-MM-DD ═══

DATABASE
  Evidence: N entries (N stale, N missing embeddings)
  Claims: N total (N published, N substantive)
  Sightings: N across N sources
  Verdicts: N supported, N partial, N misleading, N unsupported, N unverifiable

AUDIT SIGNALS
  [output from audit_claims.py status]

PIPELINE
  Inbox: N pending (N high, N medium, N low)
  Consumer state: N processed, N rejected, N skipped (frettasafn)
  Registry: N processed articles (transitional safety net)

ICELANDIC QUALITY
  statement_is: N/N (X%)
  caveats_is: N/N (X%)

EXPORT COVERAGE
  [site data file ages and counts]
```

Flag anything that needs attention with markers.

## Notes

- All queries are read-only — this skill never modifies data.
- Run all independent queries in parallel (Steps 1-5) for speed.
- If the DB is unreachable, show a clear error and still report what's available from files.
