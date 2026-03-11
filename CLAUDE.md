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
| Analysis pipeline | Claude Code custom agents (`.claude/agents/`) |
| Icelandic correction | GreynirCorrect |
| Email | Mailgun inbound parsing + sending |
| Polling model | Stan via cmdstanr (later, R) |
| Data viz | R + ggplot2 + plotly (later) |
| CI/CD | GitHub Actions |

## Project Structure

```
src/esbvaktin/          # Main package
  pipeline/             # Article analysis pipeline
    transcript.py       # Panel show transcript parser + entity generation
    register_sightings.py  # Panel show sighting registration (source_type='panel_show')
  speeches/             # Alþingi speech MCP server (read-only, althingi.db)
    context.py          # Sync speech context for pipeline (MP name detection + excerpts)
    fact_check.py       # Speech selection, loading, work dir setup for fact-checking
    register_sightings.py  # Post-assessment: match→sighting, new→unpublished claim
  ground_truth/         # Evidence database operations
  utils/                # Shared utilities (embeddings, Icelandic NLP)
tests/                  # Tests
scripts/                # One-off scripts (seeding DB, etc.)
data/seeds/             # Evidence JSON seed files (committed)
data/{source}/          # CSV outputs from R scripts (gitignored)
R/                      # Data fetching scripts (Hagstofa, Eurostat, OECD, etc.)
.claude/skills/         # find-articles, analyse-article, fact-check, process-inbox, plan-verification
.claude/agents/         # Custom agents: claim-extractor, claim-assessor, omissions-analyst, entity-extractor, site-exporter, evidence-summariser
```

## Custom Agents

Skills orchestrate, agents execute. Skills (invoked via `/analyse-article` etc.) handle user interaction and Python orchestration. Agents handle the isolated LLM work units with restricted tools and model-appropriate tiers.

| Agent | Model | Tools | Purpose |
|---|---|---|---|
| `claim-extractor` | sonnet | Read, Write, Glob | Extract factual claims from articles/speeches/panels |
| `claim-assessor` | opus | Read, Write, Glob | Assess claims against Ground Truth evidence (hardest reasoning) |
| `omissions-analyst` | sonnet | Read, Write, Glob | Identify omissions, assess framing and completeness |
| `entity-extractor` | haiku | Read, Write, Glob | Extract speakers, authors, organisations with attribution |
| `site-exporter` | sonnet | Bash, Read, Glob, Grep | Run the 4-script site data export chain |
| `evidence-summariser` | sonnet | Read, Write, Glob | Write Icelandic summaries for Ground Truth evidence batches |

**Parallelisation:** `claim-assessor` + `omissions-analyst` always run in parallel (independent tasks). Multiple `evidence-summariser` instances can run in parallel across batches.

**Context flow:** Python `prepare_context.py` writes `_context_*.md` files with full instructions + data → agent reads context file → agent writes JSON output → Python parses output.

**Icelandic-only context:** Agents that write Icelandic (extractor, assessor, omissions, summariser) have Icelandic system prompts — zero English in the agent's context window. This prevents ASCII transliteration and translated-from-English syntax. Agents that don't write Icelandic prose (entity-extractor, site-exporter) use English.

## Conventions

### Evidence Seeds
- IDs: `{TOPIC}-{TYPE}-{NUMBER}` (e.g., `ENERGY-DATA-001`)
- Parliamentary record IDs use `PARL` type: `{TOPIC}-PARL-{NNN}` (e.g., `SOV-PARL-001`)
- Topics: fisheries, trade, eea_eu_law, sovereignty, agriculture, precedents, currency, labour, energy, housing, polling, party_positions, org_positions
- Valid `source_type` values: `official_statistics`, `legal_text`, `academic_paper`, `expert_analysis`, `international_org`, `parliamentary_record`
- Seed files go in `data/seeds/*.json` (committed); CSVs in `data/{source}/` (gitignored)

- Python code: type hints, f-strings, async where appropriate
- British/international spelling in English text
- Icelandic output uses GreynirCorrect for quality
- Subagent JSON output: always parse with `_extract_json()` (sanitises `„"` quotes, strips markdown fences). Subagent field names may vary (e.g. `verdict` vs `new_verdict`) — handle both.
- Environment variables for secrets (`.env`, never committed)
- Tests with pytest

## Key Commands

```bash
uv run --extra dev python -m pytest  # Run tests (pytest is in dev extras)
uv run python scripts/export_entities.py --site-dir ~/esbvaktin-site  # 1. Export entities
uv run python scripts/export_evidence.py --site-dir ~/esbvaktin-site  # 2. Export evidence for /heimildir/
uv run python scripts/export_topics.py --site-dir ~/esbvaktin-site    # 3. Export topics (per-topic aggregations)
uv run python scripts/export_claims.py --site-dir ~/esbvaktin-site    # 4. Export claims (tracker + homepage)
uv run python scripts/prepare_site.py --site-dir ~/esbvaktin-site     # 5. Prepare site data (overlays DB verdicts)
uv run python scripts/prepare_speeches.py --site-dir ~/esbvaktin-site # 6. Export Alþingi debate data
uv run python scripts/export_topics.py --status        # Show topic distribution
uv run python scripts/export_evidence.py --status        # Show evidence DB summary
uv run python scripts/generate_evidence_is.py prepare     # Prepare IS summary batches (12 batches × 30)
uv run python scripts/generate_evidence_is.py write       # Parse subagent output → update DB
uv run python scripts/generate_evidence_is.py status      # Show IS coverage
uv run python scripts/seed_evidence.py status          # Show DB summary
uv run python scripts/seed_evidence.py insert data/seeds/  # Seed all JSON files
uv run python scripts/curate_speech_evidence.py list        # Find high-value Alþingi speeches for evidence curation
uv run python scripts/fact_check_speeches.py select --limit 5  # Rank speeches for fact-checking
uv run python scripts/fact_check_speeches.py run <speech_id>   # Fact-check a single speech (run outside Claude Code session)
uv run python scripts/fact_check_speeches.py status            # Show fact-check progress
uv run python scripts/reassess_claims.py prepare           # Prepare reassessment batches (unverifiable + partial)
uv run python scripts/reassess_claims.py update            # Apply subagent reassessments to DB
uv run python scripts/reassess_claims.py status            # Show verdict distribution
uv run python scripts/build_article_registry.py --status  # Show processed article registry
uv run python scripts/check_duplicate.py --url URL        # Check if article already processed
docker compose up -d       # Start PostgreSQL
Rscript R/02_eurostat.R    # Fetch Eurostat data (example; scripts 01-07)
```

## Site Repo

Sibling repo `~/esbvaktin-site/` (public, `bgautijonsson/esbvaktin-site`). 11ty v3 static site. Has its own `CLAUDE.md` with full site conventions.
- `_data/` — 11ty build data (entities.json, reports/*.json, entity-details/*.json, evidence-details/*.json, debates/*.json)
- `assets/data/` — client-side JS data (entities.json, reports.json, claims.json, evidence.json, sources.json, debates.json) — **must be kept in sync** (export scripts write to both)
- `eleventy.config.js` — custom Nunjucks filters (isDate, localeString, verdictLabel, sourceTypeLabel, domainLabel, etc.), watches `assets/data`
- Build: `cd ~/esbvaktin-site && npm run build` (or `npm run serve` for dev)
- Data pipeline: `export_entities.py` → `export_evidence.py` → `export_topics.py` → `export_claims.py` → `prepare_site.py` (overlays DB verdicts) → `prepare_speeches.py` → build site
- `prepare_site.py` overlays DB verdicts onto `_report_final.json` snapshots — report files are immutable pipeline output, DB is source of truth for verdicts
- Homepage: server-rendered from `_data/home.js` which reads `assets/data/*.json` (countdown, signal cards, verdict distribution, recent reports, featured voices)
- Tracker JS architecture: `site-taxonomy.js` → `tracker-utils.js` → `tracker-renderer.js` → `tracker-controller.js` → page-specific tracker. Controller owns boot flow; page scripts keep only domain logic.
- Pages: `/umraedan/` (reports), `/fullyrdingar/` (claims), `/raddirnar/` (entities), `/heimildir/` (evidence, 338 detail pages), `/thingraedur/` (debates). `/greiningar/` redirects to `/umraedan/`.
- Nunjucks `capitalize` filter lowercases the rest of the string — don't use it for titles with proper nouns. Capitalise in Python data export instead.
- Speeches module has two DB access patterns: async aiosqlite (MCP server in `search.py`) and sync sqlite3 (pipeline in `context.py`, export scripts). Same althingi.db.

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
