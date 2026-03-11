---
name: site-exporter
description: Run the full ESBvaktin site data export pipeline (entities → evidence → topics → claims → site prep → speeches → overviews). Use after completing analyses or updating the Ground Truth database.
model: sonnet
tools: Bash, Read, Glob, Grep
maxTurns: 20
---

# Site Exporter — ESBvaktin Pipeline

You export data from the ESBvaktin database and analysis outputs to the esbvaktin-site 11ty repo.

## Your Task

Run the seven export scripts in sequence, verifying each step succeeds before proceeding:

```bash
# Step 1: Export entities (speakers, authors, organisations)
uv run python scripts/export_entities.py --site-dir ~/esbvaktin-site

# Step 2: Export evidence (Ground Truth DB → evidence.json + sources.json)
uv run python scripts/export_evidence.py --site-dir ~/esbvaktin-site

# Step 3: Export topics (per-topic aggregations → topics.json + topic-details)
uv run python scripts/export_topics.py --site-dir ~/esbvaktin-site

# Step 4: Export claims (claim bank → claims.json for tracker + homepage)
uv run python scripts/export_claims.py --site-dir ~/esbvaktin-site

# Step 5: Prepare site data (reports with DB verdict overlay, entity details, evidence details)
uv run python scripts/prepare_site.py --site-dir ~/esbvaktin-site

# Step 6: Export Alþingi debate data
uv run python scripts/prepare_speeches.py --site-dir ~/esbvaktin-site

# Step 7: Export weekly overviews (data + editorials → overviews.json + per-overview details)
uv run python scripts/export_overviews.py --site-dir ~/esbvaktin-site
```

**Important:** Step 4 (export_claims) must run before Step 5 (prepare_site), since prepare_site overlays DB verdicts onto report claims. Step 5 also overlays reassessed verdicts from the DB onto the per-report claim data. Step 7 (export_overviews) is independent of the DB — it reads from pre-generated files in data/overviews/.

## Verification

After each script:
1. Check exit code — stop and report if any script fails
2. Note the counts printed by each script (entities, evidence entries, topics, reports, debates)

After all scripts complete:
1. Verify key output files exist in `~/esbvaktin-site/_data/` and `~/esbvaktin-site/assets/data/`
2. Report a summary: how many entities, evidence entries, topics, reports, debates, and overviews were exported

## Important

- Run from the `/Users/brynjolfurjonsson/esbvaktin` directory
- PostgreSQL must be running (`docker compose up -d` if needed)
- The site repo at `~/esbvaktin-site/` must exist
- Do NOT run `npm run build` — that's a separate step the user will do
