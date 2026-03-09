# ESBvaktin — CLAUDE.md

## Project Overview

Independent, data-driven civic information platform for Iceland's EU membership referendum (29 August 2026). Combines AI-summarised discourse tracking, Bayesian polling models, data journalism dashboards, and a cumulative claim tracker.

Domain: **esbvaktin.is**

## Architecture

Two core assets drive everything:

1. **Ground Truth Database** — PostgreSQL + pgvector with curated evidence (legal texts, economic data, treaty provisions, precedents)
2. **Article Analysis Pipeline** — email-submission-driven: public sends articles to `greining@esbvaktin.is`, pipeline extracts claims, compares against evidence, returns structured assessment

Post-launch additions: polling dashboard, claim tracker, economic dashboards, discourse digests.

Full architecture: ESB Obsidian vault → `Architecture.md`

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Package manager | uv |
| Ground Truth DB | PostgreSQL 17 + pgvector (self-hosted via Docker) |
| Embeddings | BAAI/bge-m3 (local multilingual, 1024-dim) |
| Article extraction | trafilatura |
| Analysis pipeline | Claude Code subagents |
| Icelandic correction | GreynirCorrect |
| Email | Mailgun inbound parsing + sending |
| CMS | Ghost |
| Polling model | Stan via cmdstanr (later, R) |
| Data viz | R + ggplot2 + plotly (later) |
| CI/CD | GitHub Actions |

## Project Structure

```
src/esbvaktin/          # Main package
  pipeline/             # Article analysis pipeline
  ground_truth/         # Evidence database operations
  utils/                # Shared utilities (embeddings, Icelandic NLP)
tests/                  # Tests
scripts/                # One-off scripts (seeding DB, etc.)
data/seeds/             # Evidence JSON seed files (committed)
data/{source}/          # CSV outputs from R scripts (gitignored)
R/                      # Data fetching scripts (Hagstofa, Eurostat, OECD, etc.)
.claude/skills/         # analyse-article, fact-check
```

## Conventions

### Evidence Seeds
- IDs: `{TOPIC}-{TYPE}-{NUMBER}` (e.g., `ENERGY-DATA-001`)
- Topics: fisheries, trade, eea_eu_law, sovereignty, agriculture, precedents, currency, labour, energy, housing, polling, party_positions, org_positions
- Valid `source_type` values: `official_statistics`, `legal_text`, `academic_paper`, `expert_analysis`, `international_org`
- Seed files go in `data/seeds/*.json` (committed); CSVs in `data/{source}/` (gitignored)

- Python code: type hints, f-strings, async where appropriate
- British/international spelling in English text
- Icelandic output uses GreynirCorrect for quality
- Environment variables for secrets (`.env`, never committed)
- Tests with pytest

## Key Commands

```bash
uv run pytest              # Run tests
uv run python -m esbvaktin # Run pipeline (TBD)
uv run python scripts/seed_evidence.py status          # Show DB summary
uv run python scripts/seed_evidence.py insert data/seeds/  # Seed all JSON files
docker compose up -d       # Start PostgreSQL
Rscript R/02_eurostat.R    # Fetch Eurostat data (example; scripts 01-07)
```

## Obsidian Output

Vault: `ESB` (MCP) / `~/Obsidian/ESB/` (direct path)

Route structured output (research, analyses, implementation notes) to the ESB vault following its conventions:

| Folder | Content |
|---|---|
| `Knowledge/<Topic>/` | Implementation notes, next-actions |
| `Reports/` | Article analysis reports from `/analyse-article` (named `YYYY-MM-DD — Title`). Include frontmatter with verdict breakdown, framing, completeness, and tags. |
| `Sessions/` | Session logs |

Use `_MOC.md` as entry points. See vault's `Vault Guide.md` for full conventions.

## Things 3

Area: **ESB Vaktin** (`7H4fB4Q8heJ9DXCXogup5V`)

## Important Context

- Referendum date: 29 August 2026 — time-sensitive project
- Independence and balance are core principles — both pro-EU and anti-EU claims assessed equally
- Related projects: Metill.is (polling patterns), Thingfrettir.is (discourse pipeline patterns)
- The ESB Obsidian vault is the source of truth for design decisions
