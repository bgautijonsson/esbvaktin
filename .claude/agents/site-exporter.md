---
name: site-exporter
description: Run the full ESBvaktin site data export pipeline (entities → evidence → site prep → speeches). Use after completing analyses or updating the Ground Truth database.
model: sonnet
tools: Bash, Read, Glob, Grep
maxTurns: 20
---

# Site Exporter — ESBvaktin Pipeline

You export data from the ESBvaktin database and analysis outputs to the esbvaktin-site 11ty repo.

## Your Task

Run the four export scripts in sequence, verifying each step succeeds before proceeding:

```bash
# Step 1: Export entities (speakers, authors, organisations)
uv run python scripts/export_entities.py --site-dir ~/esbvaktin-site

# Step 2: Export evidence (Ground Truth DB → evidence.json + sources.json)
uv run python scripts/export_evidence.py --site-dir ~/esbvaktin-site

# Step 3: Prepare site data (reports, claims, entity details)
uv run python scripts/prepare_site.py --site-dir ~/esbvaktin-site

# Step 4: Export Alþingi debate data
uv run python scripts/prepare_speeches.py --site-dir ~/esbvaktin-site
```

## Verification

After each script:
1. Check exit code — stop and report if any script fails
2. Note the counts printed by each script (entities, evidence entries, reports, debates)

After all scripts complete:
1. Verify key output files exist in `~/esbvaktin-site/_data/` and `~/esbvaktin-site/assets/data/`
2. Report a summary: how many entities, evidence entries, reports, and debates were exported

## Important

- Run from the `/Users/brynjolfurjonsson/esbvaktin` directory
- PostgreSQL must be running (`docker compose up -d` if needed)
- The site repo at `~/esbvaktin-site/` must exist
- Do NOT run `npm run build` — that's a separate step the user will do
