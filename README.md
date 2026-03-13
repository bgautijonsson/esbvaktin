# ESB Vaktin

Backend for [esbvaktin.is](https://esbvaktin.is) — an independent, data-driven civic information platform for Iceland's EU membership referendum (29 August 2026).

## What it does

ESB Vaktin monitors Icelandic public discourse about EU membership, extracts factual claims, and assesses them against a curated evidence database. The platform tracks claims equally regardless of whether they are pro-EU or anti-EU.

**Pipeline:** articles and speeches are scanned → factual claims extracted → matched against 390+ evidence entries → assessed on a five-point scale (supported, partially supported, unsupported, misleading, unverifiable) → published with full source transparency.

## Transparency

**All AI prompts are published.** The agent definitions in [`.claude/agents/`](.claude/agents/) contain the exact instructions given to each AI model. The context preparation code in [`src/esbvaktin/pipeline/prepare_context.py`](src/esbvaktin/pipeline/prepare_context.py) shows how articles, evidence, and instructions are assembled. The evidence database is committed in [`data/seeds/`](data/seeds/).

See [METHODOLOGY.md](METHODOLOGY.md) for the full methodological description, or [Aðferðafræði](https://esbvaktin.is/adferdarfraedi/) on the site.

## Architecture

- **Ground Truth database** — PostgreSQL + pgvector with curated evidence (legal texts, economic data, treaty provisions, precedents)
- **Analysis pipeline** — Claude-powered claim extraction, assessment, and omission analysis via [custom agents](.claude/agents/)
- **Icelandic NLP** — GreynirCorrect + Málstaður API for language quality
- **Site export** — generates static JSON data for the [11ty frontend](https://github.com/bgautijonsson/esbvaktin-site)

## Tech stack

Python 3.12+ · [uv](https://docs.astral.sh/uv/) · PostgreSQL 17 + pgvector · BAAI/bge-m3 embeddings · Claude (Anthropic) · GreynirCorrect · 11ty

## Setup

```bash
git clone https://github.com/bgautijonsson/esbvaktin.git
cd esbvaktin
cp .env.example .env                              # DATABASE_URL defaults work for local Docker
docker compose up -d                              # Start PostgreSQL 17 + pgvector
uv sync --extra dev                               # Install dependencies + dev tools
uv run python scripts/init_db.py --seed           # Create schema + seed evidence
```

### Dependency extras

| Extra | What it adds | When you need it |
|-------|-------------|------------------|
| (none) | Core: trafilatura, psycopg, httpx, pydantic | Always |
| `dev` | pytest, pytest-asyncio, ruff | Running tests and linting |
| `icelandic` | GreynirCorrect, icegrams, islenska | Icelandic text generation/correction |
| `embeddings` | FlagEmbedding, torch, transformers | Semantic search, evidence matching (~2GB model) |
| `email` | requests | Mailgun email integration |
| `ghost` | pyjwt | Ghost CMS publishing |

### Optional: Alþingi speeches

The speech analysis pipeline requires `althingi.db` from the [althingi-mcp](https://github.com/bgautijonsson/althingi-mcp) project. Set `ALTHINGI_DB_PATH=/path/to/althingi.db` in `.env`. The core article pipeline works without it.

### Optional: Site export

Export scripts generate JSON for the [esbvaktin-site](https://github.com/bgautijonsson/esbvaktin-site) frontend. They default to `../esbvaktin-site` as sibling directory — override with `--site-dir /path/to/site`.

## Running tests

```bash
uv run --extra dev python -m pytest               # All tests
uv run --extra dev ruff check src/ scripts/        # Lint
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup details, dependency guide, and contribution guidelines.

## Licence

Code is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). Content and data in `data/seeds/` are licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
