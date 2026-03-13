# ESB Vaktin

Backend for [esbvaktin.is](https://esbvaktin.is) — an independent, data-driven civic information platform for Iceland's EU membership referendum (29 August 2026).

## What it does

ESB Vaktin monitors Icelandic public discourse about EU membership, extracts factual claims, and assesses them against a curated evidence database. The platform tracks claims equally regardless of whether they are pro-EU or anti-EU.

**Pipeline:** articles and speeches are scanned → factual claims extracted → matched against 390+ evidence entries → assessed on a five-point scale (supported, partially supported, unsupported, misleading, unverifiable) → published with full source transparency.

## Architecture

- **Ground Truth database** — PostgreSQL + pgvector with curated evidence (legal texts, economic data, treaty provisions, precedents)
- **Analysis pipeline** — Claude-powered claim extraction, assessment, and omission analysis via custom agents
- **Icelandic NLP** — GreynirCorrect + Málstaður API for language quality
- **Site export** — generates static JSON data for the [11ty frontend](https://github.com/bgautijonsson/esbvaktin-site)

## Tech stack

Python 3.12+ · uv · PostgreSQL 17 + pgvector · BAAI/bge-m3 embeddings · Claude (Anthropic) · GreynirCorrect · 11ty

## Setup

```bash
cp .env.example .env           # Fill in API keys
docker compose up -d           # Start PostgreSQL
uv sync                        # Install dependencies
uv run python scripts/seed_evidence.py insert data/seeds/  # Seed evidence
```

Optional dependency groups: `--extra embeddings`, `--extra icelandic`, `--extra dev`, `--extra email`, `--extra ghost`.

## Licence

Code is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). Content and data in `data/seeds/` are licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

See [Aðferðafræði](https://esbvaktin.is/adferdarfraedi/) for methodology.
