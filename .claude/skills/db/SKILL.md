# DB

Query the Ground Truth Database with natural language or SQL. Read-only by default.

## Usage

```
/db                              # Show quick summary (verdict distribution + recent activity)
/db how many claims about fisheries are published?
/db verdict distribution by category
/db stale evidence
/db show me evidence about sovereignty
/db SELECT * FROM balance_audit
/db sighting drift
```

## Steps

### Step 1: Classify the Query

Determine what the user is asking:

1. **Raw SQL** — if the input looks like SQL (starts with SELECT, WITH, etc.), run it directly (Step 2a)
2. **Pre-built query** — match against known query templates (Step 2b)
3. **Evidence search** — if asking about specific topic content ("show me evidence about X"), run semantic search (Step 2c)
4. **Quick summary** — if no argument or just `/db`, show the default summary (Step 2d)

### Step 2a: Run Raw SQL (read-only)

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from esbvaktin.ground_truth.operations import get_connection

conn = get_connection()
rows = conn.execute('''USER_SQL_HERE''').fetchall()

# Get column names from cursor description
cols = [desc[0] for desc in conn.cursor().description] if hasattr(conn, 'cursor') else []

for row in rows:
    print(row)
conn.close()
"
```

**Safety:** Only allow SELECT statements. If the SQL contains INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or CREATE, **refuse** and tell the user to use the appropriate script instead.

Alternatively, use `psql` for simpler formatting:

```bash
psql "postgresql://esb:localdev@localhost:5432/esbvaktin" -c "USER_SQL_HERE"
```

### Step 2b: Pre-built Query Templates

Match the user's natural language to one of these queries:

**Verdict distribution:**
```sql
SELECT verdict, COUNT(*) as n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM claims WHERE published = TRUE
GROUP BY verdict ORDER BY n DESC;
```

**Verdict by category:**
```sql
SELECT category, verdict, COUNT(*) as n
FROM claims WHERE published = TRUE
GROUP BY category, verdict
ORDER BY category, n DESC;
```

**Balance audit (pro-EU vs anti-EU accuracy):**
```sql
SELECT * FROM balance_audit;
```

**Outlet verdicts:**
```sql
SELECT * FROM outlet_verdicts ORDER BY total_claims DESC;
```

**Stale evidence (not verified in 90+ days):**
```sql
SELECT * FROM stale_evidence;
```

**Evidence utilisation (most/least cited):**
```sql
SELECT * FROM evidence_utilisation ORDER BY citation_count DESC LIMIT 20;
```

**Claim velocity (new claims per week):**
```sql
SELECT * FROM claim_velocity ORDER BY week DESC LIMIT 12;
```

**Verdict trend (cumulative over time):**
```sql
SELECT * FROM verdict_weekly_trend ORDER BY week DESC LIMIT 20;
```

**Claim frequency (most-sighted claims):**
```sql
SELECT * FROM claim_frequency ORDER BY sighting_count DESC LIMIT 20;
```

**Sighting drift (claims with inconsistent verdicts across contexts):**
```sql
SELECT c.claim_slug, c.verdict as canonical_verdict, c.canonical_text_is,
       cs.speech_verdict, cs.source_url, cs.source_date
FROM claims c
JOIN claim_sightings cs ON c.id = cs.claim_id
WHERE cs.speech_verdict IS NOT NULL
  AND cs.speech_verdict != c.verdict
ORDER BY c.claim_slug;
```

**Claims about a topic:**
```sql
SELECT claim_slug, canonical_text_is, verdict, confidence
FROM claims
WHERE published = TRUE AND category = 'TOPIC'
ORDER BY verdict, confidence DESC;
```

**Evidence about a topic:**
```sql
SELECT evidence_id, topic, statement_is, confidence, source_name
FROM evidence
WHERE topic = 'TOPIC'
ORDER BY evidence_id;
```

**Recent sightings:**
```sql
SELECT cs.source_date, cs.source_domain, cs.speaker_name,
       c.canonical_text_is, c.verdict
FROM claim_sightings cs
JOIN claims c ON c.id = cs.claim_id
ORDER BY cs.source_date DESC NULLS LAST
LIMIT 20;
```

**Unverifiable claims with evidence now available:**
```sql
SELECT c.claim_slug, c.canonical_text_is
FROM claims c
WHERE c.verdict = 'unverifiable'
  AND c.published = TRUE
ORDER BY c.claim_slug;
```

### Step 2c: Semantic Evidence Search

When the user asks "show me evidence about X" or "what do we know about X":

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from esbvaktin.ground_truth.operations import get_connection, search_evidence

conn = get_connection()
results = search_evidence('USER_QUERY', top_k=10, conn=conn)

for r in results:
    print(f'{r.evidence_id} ({r.topic}, sim={r.similarity:.3f})')
    print(f'  {r.statement[:120]}')
    if r.statement_is:
        print(f'  IS: {r.statement_is[:120]}')
    print()
conn.close()
"
```

### Step 2d: Quick Summary

If no argument, show:

```bash
psql "postgresql://esb:localdev@localhost:5432/esbvaktin" -c "
SELECT 'Evidence' as table_name, COUNT(*) as total FROM evidence
UNION ALL
SELECT 'Claims', COUNT(*) FROM claims
UNION ALL
SELECT 'Published claims', COUNT(*) FROM claims WHERE published = TRUE
UNION ALL
SELECT 'Sightings', COUNT(*) FROM claim_sightings
UNION ALL
SELECT 'Stale evidence', COUNT(*) FROM evidence WHERE last_verified < CURRENT_DATE - INTERVAL '90 days';
"
```

Then show verdict distribution:
```bash
psql "postgresql://esb:localdev@localhost:5432/esbvaktin" -c "
SELECT verdict, COUNT(*) as n FROM claims WHERE published = TRUE GROUP BY verdict ORDER BY n DESC;
"
```

### Step 3: Format and Display

Present results as formatted tables in the terminal. For large result sets (>30 rows), summarise and offer to show the full results.

## Notes

- **Read-only.** This skill never modifies data. Block any mutating SQL.
- **Available views:** `balance_audit`, `outlet_verdicts`, `verdict_weekly_trend`, `evidence_utilisation`, `stale_evidence`, `claim_velocity`, `claim_frequency`. Use these instead of writing complex JOINs.
- **psql vs Python:** Use `psql` for simple queries with nice table formatting. Use Python when semantic search or post-processing is needed.
- **Topic names:** fisheries, trade, eea_eu_law, sovereignty, agriculture, precedents, currency, labour, energy, housing, polling, party_positions, org_positions.
