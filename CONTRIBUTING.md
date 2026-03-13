# Contributing to ESB Vaktin

Thank you for your interest in contributing to ESB Vaktin — an independent civic information platform for Iceland's EU membership referendum.

## Principles

- **Independence**: The platform assesses pro-EU and anti-EU claims equally. Contributions must not introduce bias.
- **Transparency**: All analysis methodology is open. Agent prompts, evidence data, and assessment logic are committed to the repo.
- **Icelandic first**: Public-facing text is in Icelandic. Code comments and documentation are in English.

## Getting started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker (for PostgreSQL)
- Git

### Setup

```bash
git clone https://github.com/bgautijonsson/esbvaktin.git
cd esbvaktin

# 1. Environment
cp .env.example .env              # Fill in DATABASE_URL (defaults work for local Docker)

# 2. Database
docker compose up -d              # Start PostgreSQL 17 + pgvector
uv run python scripts/init_db.py --seed   # Create schema + seed evidence

# 3. Python dependencies (pick what you need)
uv sync                           # Core only
uv sync --extra dev               # + pytest, ruff (needed for contributing)
uv sync --extra icelandic         # + GreynirCorrect (needed for Icelandic text pipelines)
uv sync --extra embeddings        # + BAAI/bge-m3 (needed for semantic search, ~2GB model download)
```

### Dependency extras

| Extra | What it adds | When you need it |
|-------|-------------|------------------|
| (none) | Core: trafilatura, psycopg, httpx, pydantic | Always |
| `dev` | pytest, pytest-asyncio, ruff | Running tests, linting |
| `icelandic` | GreynirCorrect, icegrams, islenska, reynir | Icelandic text generation/correction |
| `embeddings` | FlagEmbedding, torch, transformers | Semantic search, evidence matching (~2GB download) |
| `email` | requests | Mailgun email integration |
| `ghost` | pyjwt | Ghost CMS publishing |

### Running tests

```bash
uv run --extra dev python -m pytest              # All tests
uv run --extra dev python -m pytest -k "test_name"  # Single test
```

### Linting

```bash
uv run --extra dev ruff check src/ scripts/       # Check
uv run --extra dev ruff check --fix src/ scripts/  # Auto-fix
```

Code style: Ruff with line-length 100, target Python 3.12, rules E/F/I/N/W/UP.

## Project structure

```
src/esbvaktin/
  pipeline/             # Article analysis pipeline (context preparation, orchestration)
  speeches/             # Alþingi speech integration (MCP server, fact-checking)
  ground_truth/         # Evidence database (schema, operations, models)
  utils/                # Shared utilities (embeddings, Icelandic NLP)
scripts/                # CLI scripts (seeding, export, pipeline tools)
data/seeds/             # Evidence JSON seed files (committed, CC BY-SA 4.0)
R/                      # Data fetching scripts (Hagstofa, Eurostat, OECD)
.claude/agents/         # AI agent definitions (the "prompts" — all committed)
.claude/skills/         # Pipeline orchestration skills
.claude/rules/          # Context rules for Icelandic quality, etc.
tests/                  # Test suite
```

## How the analysis pipeline works

See [METHODOLOGY.md](METHODOLOGY.md) for the full methodological description. In brief:

1. **Context preparation** (`src/esbvaktin/pipeline/prepare_context.py`) builds markdown files containing the article text, relevant evidence, and detailed instructions
2. **AI agents** (`.claude/agents/*.md`) read those context files and produce structured JSON output
3. **Python code** parses the JSON, assembles the report, and registers claims in the database

The agents are tool-restricted (Read + Write + Glob only — no internet access, no code execution) and their full prompt text is committed to this repo.

## Optional: Alþingi speeches

The speech analysis pipeline requires `althingi.db` — a SQLite database of parliamentary speeches. This comes from the [althingi-mcp](https://github.com/bgautijonsson/althingi-mcp) project.

To set it up:
1. Clone and build `althingi-mcp` (see its README)
2. Set `ALTHINGI_DB_PATH=/path/to/althingi.db` in your `.env`

The speeches pipeline is optional — the core article analysis works without it.

## Optional: Site export

The export pipeline generates static JSON for the [esbvaktin-site](https://github.com/bgautijonsson/esbvaktin-site) 11ty frontend. Export scripts default to `../esbvaktin-site` as sibling directory. Override with `--site-dir /path/to/site`.

## What to contribute

- **Evidence entries**: New data for the Ground Truth database (see `data/seeds/` for format)
- **Bug fixes**: Anything in the issue tracker
- **R data scripts**: Fetching public data from Hagstofa, Eurostat, Seðlabanki, etc.
- **Tests**: Expanding test coverage
- **Documentation**: Improving clarity for contributors

## Pull request process

1. Fork the repo and create a feature branch
2. Ensure tests pass: `uv run --extra dev python -m pytest`
3. Ensure linting passes: `uv run --extra dev ruff check src/ scripts/`
4. Write a clear PR description explaining *why*, not just *what*
5. One logical change per PR

## Code of conduct

This is a civic project. Contributions must be factual, non-partisan, and in good faith. We assess claims based on evidence, not political alignment.

## Licence

By contributing, you agree that your contributions will be licensed under AGPL-3.0 (code) and CC BY-SA 4.0 (data/content).
