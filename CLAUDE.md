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
| Language | Python 3.14 |
| Package manager | uv |
| Ground Truth DB | PostgreSQL + pgvector (Supabase or self-hosted) |
| Embeddings | OpenAI `text-embedding-3-small` or multilingual alternative |
| Article extraction | trafilatura |
| Analysis pipeline | Claude API (Anthropic SDK) |
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
data/                   # Local data files (not committed if large)
```

## Conventions

- Python code: type hints, f-strings, async where appropriate
- British/international spelling in English text
- Icelandic output uses GreynirCorrect for quality
- Environment variables for secrets (`.env`, never committed)
- Tests with pytest

## Key Commands

```bash
uv run pytest              # Run tests
uv run python -m esbvaktin # Run pipeline (TBD)
```

## Obsidian Output

Vault: `ESB` (MCP) / `~/Obsidian/ESB/` (direct path)

Route structured output (research, analyses, implementation notes) to the ESB vault following its conventions:

| Folder | Content |
|---|---|
| `Knowledge/<Topic>/` | Implementation notes, next-actions |
| `Sessions/` | Session logs |

Use `_MOC.md` as entry points. See vault's `Vault Guide.md` for full conventions.

## Important Context

- Referendum date: 29 August 2026 — time-sensitive project
- Independence and balance are core principles — both pro-EU and anti-EU claims assessed equally
- Related projects: Metill.is (polling patterns), Thingfrettir.is (discourse pipeline patterns)
- The ESB Obsidian vault is the source of truth for design decisions
