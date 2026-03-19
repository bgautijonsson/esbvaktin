# Evidence Hunt

Research and draft new evidence entries to fill gaps in the Ground Truth Database.

## Usage

```
/evidence-hunt                         # Identify gaps from audit + unverifiable claims
/evidence-hunt fisheries               # Research a specific topic
/evidence-hunt data/analyses/20260310_123456  # Fill gaps from a specific analysis
/evidence-hunt "What is Iceland's fishing quota allocation?"  # Research a specific question
```

## Steps

### Step 1: Identify Evidence Gaps

Determine what needs researching based on the input:

**If no argument or topic keyword:** Run the gap identification pipeline:

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from esbvaktin.ground_truth.operations import get_connection

conn = get_connection()

# Unverifiable published claims (these NEED evidence)
unverifiable = conn.execute('''
    SELECT claim_slug, canonical_text_is, category
    FROM claims
    WHERE verdict = 'unverifiable' AND published = TRUE
    ORDER BY category
''').fetchall()

# Topics with low evidence coverage
topic_counts = conn.execute('''
    SELECT topic, COUNT(*) as n FROM evidence
    GROUP BY topic ORDER BY n ASC
''').fetchall()

# Evidence cited in contradictions
contradicted = conn.execute('''
    SELECT DISTINCT UNNEST(contradicting_evidence) as eid
    FROM claims WHERE contradicting_evidence != '{}'
''').fetchall()

print(f'=== EVIDENCE GAPS ===')
print(f'Unverifiable published claims: {len(unverifiable)}')
for slug, text, cat in unverifiable:
    print(f'  [{cat}] {text[:80]}...')

print(f'\nTopic coverage (ascending):')
for topic, n in topic_counts:
    print(f'  {topic}: {n} entries')

print(f'\nContradicted evidence IDs (may need strengthening): {len(contradicted)}')
conn.close()
"
```

**If an analysis directory is given:** Load `_report_final.json` and identify unverifiable/partially supported claims:

```bash
uv run python -c "
import json
from pathlib import Path

work_dir = Path('ANALYSIS_DIR')
report = json.loads((work_dir / '_report_final.json').read_text())

gaps = []
for item in report.get('claims', []):
    verdict = item.get('verdict', item.get('new_verdict', ''))
    if verdict in ('unverifiable', 'partially_supported'):
        gaps.append({
            'claim': item.get('claim', {}).get('claim_text', ''),
            'category': item.get('claim', {}).get('category', 'other'),
            'verdict': verdict,
            'missing_context': item.get('missing_context', ''),
        })

print(f'Found {len(gaps)} claims needing evidence:')
for g in gaps:
    print(f'  [{g[\"verdict\"]}] [{g[\"category\"]}] {g[\"claim\"][:80]}...')
    if g['missing_context']:
        print(f'    Missing: {g[\"missing_context\"][:100]}')
"
```

**If a topic keyword is given:** Focus research on that topic.

### Step 2: Research Sources

For each identified gap, search available sources. Use these in parallel where independent:

**Parliamentary speeches (Alþingi MCP):**
```
search_eu_speeches(query="<topic keywords>", limit=10)
```

Look for speeches by ministers or committee members that cite specific data, reports, or legal provisions. These are high-value evidence sources.

**News articles (Fréttasafn MCP):**
```
search_news(query="<topic keywords>", limit=10)
```

News articles are lower priority as evidence — prefer them only when they cite official statistics or expert analyses.

**Official sources (WebFetch):**
- Hagstofa Íslands (px.hagstofa.is) — Icelandic statistics
- Eurostat — EU statistics
- EFTA Court (eftacourt.int) — EEA legal precedents
- EUR-Lex (eur-lex.europa.eu) — EU legal texts
- Government of Iceland (government.is, stjornarradid.is) — official positions
- Althingi (althingi.is) — parliamentary records

**Web search:**
Use WebSearch for specific factual queries ("Iceland fishing quota EU common fisheries policy statistics").

### Step 3: Evaluate Found Sources

For each source found, evaluate against the evidence schema requirements:

1. **Source type** — must be one of: `official_statistics`, `legal_text`, `academic_paper`, `expert_analysis`, `international_org`, `parliamentary_record`
2. **Confidence** — `high` (official statistics, legal text), `medium` (expert analysis, international org), `low` (general commentary)
3. **Verifiability** — must have a concrete, citable source URL
4. **Relevance** — must directly address the claim gap, not just be tangentially related

### Step 4: Draft Evidence Entries

For each viable source, draft a seed entry in the standard format:

```bash
uv run python -c "
import json
from pathlib import Path
from datetime import date

# Draft entries — edit these based on research findings
entries = [
    {
        'evidence_id': 'TOPIC-TYPE-NNN',  # e.g. FISH-DATA-042
        'domain': 'economic',  # legal, economic, political, precedent
        'topic': 'fisheries',  # Must match DB topics
        'statement': 'English statement of the evidence fact.',
        'source_name': 'Source Organisation or Document Name',
        'source_url': 'https://...',
        'source_type': 'official_statistics',
        'confidence': 'high',
        'caveats': 'Any important limitations or context (English).',
        'related_entries': [],  # IDs of related existing evidence
    },
]

# Validate ID format
import re
for e in entries:
    if not re.match(r'^[A-Z]+-[A-Z]+-\d{3}$', e['evidence_id']):
        print(f'WARNING: Invalid ID format: {e[\"evidence_id\"]}')

# Write to seed file
output = Path('data/seeds/draft_evidence.json')
output.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
print(f'Drafted {len(entries)} entries to {output}')
print('Review and then run: uv run python scripts/seed_evidence.py insert data/seeds/draft_evidence.json')
"
```

**ID naming convention:**
- Topic prefix: `FISH`, `TRADE`, `SOV`, `EEA`, `AGRI`, `PREC`, `CURR`, `LABOUR`, `ENERGY`, `HOUSING`, `POLL`, `PARTY`, `ORG`
- Type: `DATA` (statistics), `LEGAL` (legal text), `ACAD` (academic), `EXPERT` (expert analysis), `INTL` (international org), `PARL` (parliamentary record)
- Number: sequential within topic-type, check existing max:

```bash
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from esbvaktin.ground_truth.operations import get_connection
conn = get_connection()
rows = conn.execute(\"SELECT evidence_id FROM evidence WHERE evidence_id LIKE 'TOPIC-TYPE-%' ORDER BY evidence_id DESC LIMIT 3\").fetchall()
for r in rows: print(r[0])
conn.close()
"
```

**Do not use `psql`** — it requires separate permission approval and hardcodes credentials.

### Step 5: Review and Insert

Present the drafted entries to the user for review. Show:
- Evidence ID
- Statement
- Source name and URL
- Confidence level
- Any caveats

After user approval:

```bash
uv run python scripts/seed_evidence.py insert data/seeds/draft_evidence.json
```

Then verify the new entries have embeddings:

```bash
uv run python scripts/verify_db.py
```

### Step 6: Update Related Claims

After inserting new evidence, check if any unverifiable claims can now be reassessed:

```bash
uv run python scripts/reassess_claims.py prepare --only unverifiable
```

If batches are generated, inform the user they can run `/reassess` to process them.

## Notes

- **Never auto-insert evidence.** Always present drafts for user review first.
- **Prefer authoritative sources:** official_statistics > legal_text > international_org > academic_paper > expert_analysis > parliamentary_record
- **ID uniqueness:** Always check existing IDs before assigning new ones.
- **Icelandic summaries:** New evidence will need IS summaries later — `generate_evidence_is.py` handles this in batches.
- **Source URL must be permanent:** Avoid URLs that will break (news article paywalls, temporary pages). Government and institutional URLs are preferred.
- **Related entries:** Link to existing evidence that covers the same topic. Check with semantic search:
  ```bash
  uv run python -c "
  from dotenv import load_dotenv; load_dotenv()
  from esbvaktin.ground_truth.operations import get_connection, search_evidence
  conn = get_connection()
  for r in search_evidence('YOUR STATEMENT', top_k=5, conn=conn):
      print(f'{r.evidence_id}: {r.statement[:80]}')
  conn.close()
  "
  ```
