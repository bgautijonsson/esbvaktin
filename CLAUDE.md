# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# ESBvaktin

## Project Overview

Independent, data-driven civic information platform for Iceland's EU membership referendum (29 August 2026). Combines AI-summarised discourse tracking, Bayesian polling models, data journalism dashboards, and a cumulative claim tracker.

Domain: **esbvaktin.is**

## Architecture

Two core assets drive everything:

1. **Ground Truth Database** — PostgreSQL + pgvector with curated evidence (legal texts, economic data, treaty provisions, precedents)
2. **Article Analysis Pipeline** — email-submission-driven: public sends articles to `greining@esbvaktin.is`, pipeline extracts claims, compares against evidence, returns structured assessment

Post-launch additions: polling dashboard, claim tracker, economic dashboards, discourse digests.

Full architecture: ESB Obsidian vault → `Architecture.md`
Machine setup: `SETUP.md`

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Package manager | uv |
| Ground Truth DB | PostgreSQL 17 + pgvector + tsvector FTS (self-hosted via Docker) |
| Embeddings | BAAI/bge-m3 (local multilingual, 1024-dim) |
| Evidence retrieval | Hybrid: pgvector cosine + tsvector keyword, fused with RRF |
| Article extraction | trafilatura |
| Analysis pipeline | Claude Code custom agents (`.claude/agents/`) |
| Icelandic correction | GreynirCorrect + Málstaður API (via MCP) |
| Email | Mailgun inbound parsing + sending |
| Polling model | Stan via cmdstanr (later, R) |
| Data viz | R + ggplot2 + plotly (later) |
| CI/CD | GitHub Actions |

## Project Structure

```
src/esbvaktin/          # Main package
  pipeline/             # Article analysis pipeline
    detection.py        # Source type detection (is_panel_show)
    transcript.py       # Panel show transcript parser + entity generation
    register_sightings.py  # Panel show sighting registration (source_type='panel_show')
  speeches/             # Alþingi speech MCP server (read-only, althingi.db)
    constants.py        # Shared EU keyword/pattern constants
    context.py          # Sync speech context for pipeline (MP name detection + excerpts)
    fact_check.py       # Speech selection, loading, work dir setup for fact-checking
    register_sightings.py  # Post-assessment: match→sighting, new→unpublished claim
  ground_truth/         # Evidence database operations
  claim_bank/           # Canonical claims storage with verdicts for reuse across articles
  gap_planner/          # Evidence gap identification and research task generation
  corrections/          # Icelandic text correction pipeline (greynir, naturalness, inflections, EU terms)
  utils/                # Shared utilities (embeddings, Icelandic NLP)
tests/                  # Tests
scripts/                # One-off and pipeline scripts
  pipeline/             # Standalone scripts for each pipeline step (fetch, extract, evidence, assemble, etc.)
data/seeds/             # Evidence JSON seed files (committed)
data/analyses/          # Article analysis work directories (gitignored)
data/reassessment/      # Verdict reassessment outputs (gitignored)
data/evidence_is/       # Icelandic evidence summary outputs (gitignored)
data/overviews/         # Weekly overview generation (gitignored)
data/inbox/             # Article discovery inbox with persistent state
data/{source}/          # CSV outputs from R scripts (gitignored)
R/                      # Data fetching scripts (Hagstofa, Eurostat, OECD, etc.)
.claude/skills/         # find-articles, analyse-article, fact-check, process-inbox, plan-verification, health, db, evidence-hunt, reassess, tidy, process-articles, weekly-review
.claude/hooks/          # Pre-export validation hook
.claude/agents/         # Custom agents (11 total, see table below)
```

## Custom Agents

Skills orchestrate, agents execute. Skills (invoked via `/analyse-article` etc.) handle user interaction and Python orchestration. Agents handle the isolated LLM work units with restricted tools and model-appropriate tiers.

| Agent | Model | Tools | Purpose |
|---|---|---|---|
| `claim-extractor` | sonnet | Read, Write, Glob | Extract factual claims from articles/speeches/panels |
| `claim-assessor` | opus | Read, Write, Glob | Assess claims against Ground Truth evidence (hardest reasoning) |
| `omissions-analyst` | sonnet | Read, Write, Glob | Identify omissions, assess framing and completeness |
| `entity-extractor` | haiku | Read, Write, Glob | Extract speakers, authors, organisations with attribution |
| `site-exporter` | sonnet | Bash, Read, Glob, Grep | Run the 7-script site data export chain |
| `evidence-summariser` | sonnet | Read, Write, Glob, MCP mideind (check only) | Write Icelandic summaries for Ground Truth evidence batches |
| `editorial-writer` | opus | Read, Write, Glob, Grep, MCP morphology, MCP mideind | Write Icelandic weekly editorial from overview context |
| `claim-reviewer` | sonnet | Read, Write, Glob | Review published claims for substantiveness |
| `capsule-writer` | sonnet | Read, Write, Glob, MCP mideind | Write short Icelandic reader's note (constructive, curiosity-building) |
| `evidence-auditor` | sonnet | Read, Write, Glob | Audit Ground Truth entries for internal contradictions |
| `meta-claim-filter` | sonnet | Read, Write, Glob | Heimildin rhetoric classification (client project) |

**Parallelisation:** `claim-assessor` + `omissions-analyst` always run in parallel (independent tasks). Multiple `evidence-summariser` instances can run in parallel across batches.

**Context flow:** Python `prepare_context.py` writes `_context_*.md` files with full instructions + data → agent reads context file → agent writes JSON output → Python parses output.

**Icelandic-only context:** Agents that write Icelandic (extractor, assessor, omissions, summariser, editorial-writer, capsule-writer) have Icelandic system prompts — zero English in the agent's context window. This prevents ASCII transliteration and translated-from-English syntax. Agents that don't write Icelandic prose (entity-extractor, site-exporter) use English.

**Overview pipeline:** `generate_overview.py` (inbox coverage check → SQL → data.json, includes under-discussed topics) → `prepare_overview_context.py` (→ _context_is.md, digest-structured) → `editorial-writer` agent (opus, → editorial.md) → user review → `export_overviews.py` (strips heading, enriches slugs). `generate_overview.py` checks inbox for unanalysed articles from the target week before generating — if HIGH/MEDIUM articles cover gap topics, it blocks with recommendations (exit 2). Use `--force` to proceed anyway. Editorial writer uses MCP morphology tools for inflection and MCP mideind `correct_text` for grammar self-correction (one call per editorial), then reads `knowledge/exemplars_editorial_is.md` before writing. `correct_icelandic.py check-editorial` remains available for additional local checks if needed. **Never push editorials without user review.**

## Conventions

### Evidence Seeds
- IDs: `{TOPIC}-{TYPE}-{NUMBER}` (e.g., `ENERGY-DATA-001`)
- Parliamentary record IDs use `PARL` type: `{TOPIC}-PARL-{NNN}` (e.g., `SOV-PARL-001`)
- Topics: fisheries, trade, eea_eu_law, sovereignty, agriculture, precedents, currency, labour, energy, housing, polling, party_positions, org_positions
- Valid `source_type` values: `official_statistics`, `legal_text`, `academic_paper`, `expert_analysis`, `international_org`, `parliamentary_record`
- Seed files go in `data/seeds/*.json` (committed); CSVs in `data/{source}/` (gitignored)

### Claim Publishing
- Claims are **auto-published** at registration time (`published=True` by default)
- Only `unverifiable` factual claims stay unpublished (discarded at registration)
- Hearsay claims are published with `verdict=unverifiable` and `substantive=False` — visible on site with amber warning but excluded from credibility scoring
- The `substantive` flag is orthogonal: controls credibility scoring, not site visibility
- `publish_claims.py` provides manual publish/unpublish for edge cases
- `review_claims.py` flags trivia as `substantive=False` post-publication

### Epistemic Types
- `EpistemicType` (separate from `ClaimType`): `factual`, `hearsay`, `counterfactual`, `prediction`
- `ClaimType.PREDICTION` was renamed to `ClaimType.FORECAST` to avoid collision with `EpistemicType.PREDICTION`
- Hearsay: auto-`unverifiable`, published with warning, `substantive=False`. Short-circuits before evidence retrieval (no Opus cost)
- Predictions/counterfactuals: assessed on reasoning quality (source agreement, credibility, precedent), 0.8 confidence ceiling
- Counterfactual = past only ("ef X hefði..."), prediction = future ("ef aðild næðist myndi...")
- Site displays type-aware verdict labels (e.g., "Víðtæk samstaða" for well-supported predictions) and coloured badges/callouts
- Spec: `docs/specs/2026-03-25-epistemic-type-design.md`

### Evidence Retrieval
- **Hybrid search:** pgvector cosine similarity + tsvector keyword search, fused with Reciprocal Rank Fusion (RRF, k=60)
- Keyword search catches acronyms (ESB, EES, EFTA, CFP), numbers, and legal references that embeddings handle poorly
- `MIN_SIMILARITY = 0.45` floor for pure-vector fallback (when no keyword matches)
- `MAX_EVIDENCE_PER_CLAIM = 7` hard cap
- Primacy-recency ordering: best evidence first, second-best last (exploits LLM attention patterns)
- Bank matches shown to assessor as "Fyrra mat" blocks with prior verdict + freshness label
- Confidence: 5% decay on disagreeing sightings, 2% boost on agreeing (capped at 0.95)

### Code Style
- Ruff: line-length 100, target py312, rules E/F/I/N/W/UP
- Type hints, f-strings, async where appropriate
- British/international spelling in English text

### Optional Dependency Groups
- `uv sync --extra embeddings` — FlagEmbedding + torch (for BAAI/bge-m3)
- `uv sync --extra icelandic` — GreynirCorrect, Icegrams, Islenska
- `uv sync --extra dev` — pytest, pytest-asyncio, ruff
- `uv sync --extra email` — Mailgun integration
- `uv sync --extra ghost` — Ghost CMS publishing

### Icelandic Output
- Icelandic output uses GreynirCorrect (local) and Málstaður API (via `mideind` MCP server) for quality — cost rules in `.claude/rules/mcp-costs.md`
- Subagent JSON output: always parse with `_extract_json()` (sanitises `„"` quotes, strips markdown fences). Subagent field names may vary (e.g. `verdict` vs `new_verdict`) — handle both.
- Icelandic language rules auto-load via `.claude/rules/` for `*_is.*` and `data/analyses/**` paths
- Environment variables for secrets (`.env`, never committed)

## Skills (Slash Commands)

```
/find-articles             # Discover new articles (no auto-analysis)
/find-articles 3           # Scan last 3 days
/find-articles backlog     # Check inbox backlog only
/process-articles          # Batch-analyse top 3 pending articles
/process-articles 5        # Batch-analyse top 5
/process-articles triage   # Show sorted triage table
/analyse-article <url>     # Full pipeline for single article
/process-inbox             # Lightweight claim harvesting (no full assessment)
/health                    # Unified project health dashboard
/health db                 # Database section only
/db                        # Quick DB summary (verdicts, counts)
/db stale evidence         # Query stale evidence
/db "SELECT ..."           # Run raw SQL (read-only)
/evidence-hunt             # Find and draft evidence for gaps
/evidence-hunt fisheries   # Research specific topic
/evidence-hunt monthly     # Refresh high-decay topics (polling, party_positions, org_positions, currency)
/reassess                  # Full reassessment cycle (unverifiable + partial)
/reassess overconfident    # Reassess audit-flagged claims only
/reassess denominator      # Reassess scope-word claims (denominator confusion audit)
/reassess evidence ID1 ID2 ...  # Reassess all claims citing these evidence entries
/reassess claims 123 456 ...    # Reassess specific claims by ID
/tidy                      # Full codebase quality audit
/tidy lint                 # Ruff lint only
/weekly-review              # Generate weekly overview + editorial (checks inbox first)
/weekly-review 2026-W12    # Specific week
/weekly-review last        # Previous week
/link-check                # Check evidence source URLs for link rot + content drift
/link-check populate       # Auto-populate source excerpts (content fingerprints)
/link-check report         # Show link health report
/ci                        # Latest CI run status
/ci list                   # Recent runs (last 10)
/ci failures               # Show only failed runs
/ci logs <run-id>          # Download and show failure logs
```

## Key Commands

```bash
# Article inbox
uv run python scripts/manage_inbox.py status              # Backlog summary
uv run python scripts/manage_inbox.py triage               # Sorted triage table for processing decisions
uv run python scripts/manage_inbox.py list                 # Pending articles
uv run python scripts/manage_inbox.py list --priority high # High priority only
uv run python scripts/manage_inbox.py next --high-only     # Next articles ready for analysis
uv run python scripts/manage_inbox.py next --limit 10      # Next N articles (HIGH + MEDIUM)
uv run python scripts/manage_inbox.py add-batch FILE.json  # Batch import from scan
uv run python scripts/manage_inbox.py queue ID [ID ...]    # Queue for analysis
uv run python scripts/manage_inbox.py reject ID [ID ...]   # Reject + add to rejected_urls.txt
uv run python scripts/manage_inbox.py skip ID [ID ...]     # Skip (not worth it)
uv run python scripts/manage_inbox.py prune --days 30      # Clean old entries

# Development
uv run --extra dev python -m pytest              # Run all tests
uv run --extra dev python -m pytest tests/test_models.py  # Single test file
uv run --extra dev python -m pytest -k "test_name"        # Single test by name
uv run --extra dev ruff check src/ scripts/      # Lint
uv run --extra dev ruff check --fix src/ scripts/  # Lint with auto-fix

# Export pipeline (all 7 steps with validation)
./scripts/run_export.sh --site-dir ~/esbvaktin-site   # Run full pipeline
# Or run individual steps:
uv run python scripts/export_entities.py --site-dir ~/esbvaktin-site  # 1. Export entities
uv run python scripts/export_evidence.py --site-dir ~/esbvaktin-site  # 2. Export evidence for /heimildir/
uv run python scripts/export_topics.py --site-dir ~/esbvaktin-site    # 3. Export topics (per-topic aggregations)
uv run python scripts/export_claims.py --site-dir ~/esbvaktin-site    # 4. Export claims (tracker + homepage)
uv run python scripts/prepare_site.py --site-dir ~/esbvaktin-site     # 5. Prepare site data (overlays DB verdicts)
uv run python scripts/prepare_speeches.py --site-dir ~/esbvaktin-site # 6. Export Alþingi debate data
uv run python scripts/export_overviews.py --site-dir ~/esbvaktin-site # 7. Export weekly overviews

# Database backup (daily via launchd, syncs to iCloud)
./scripts/backup_db.sh            # Manual backup
./scripts/backup_db.sh --status   # Show existing backups
uv run python scripts/export_topics.py --status        # Show topic distribution
uv run python scripts/generate_overview.py --week 2026-W11  # Generate weekly overview data (checks inbox first)
uv run python scripts/generate_overview.py --week 2026-W11 --force  # Skip inbox gap warning
uv run python scripts/generate_overview.py --status         # Show overview coverage
uv run python scripts/prepare_overview_context.py 2026-W11  # Prepare editorial context (Icelandic)
uv run python scripts/correct_icelandic.py check-editorial data/overviews/2026-W11/editorial.md --fix  # Post-process editorial
uv run python scripts/validate_editorial.py data/overviews/2026-W11/editorial.md  # Validate against claim DB
uv run python scripts/export_overviews.py --status         # Show overview export coverage
uv run python scripts/export_evidence.py --status        # Show evidence DB summary
uv run python scripts/generate_evidence_is.py prepare     # Prepare IS summary batches (12 batches × 30)
uv run python scripts/generate_evidence_is.py write       # Parse subagent output → update DB
uv run python scripts/generate_evidence_is.py status      # Show IS coverage
uv run python scripts/improve_evidence_is.py status              # Show IS quality (caveats, proofreading)
uv run python scripts/improve_evidence_is.py translate-caveats   # Translate EN caveats → IS via Málstaður
uv run python scripts/improve_evidence_is.py correct             # Grammar-correct IS fields via Málstaður
uv run python scripts/improve_evidence_is.py correct --dry-run   # Preview without API calls
# Note: `correct` may need 2-3 runs to converge (corrections change text hash → re-eligible)
uv run python scripts/seed_evidence.py status          # Show DB summary
uv run python scripts/seed_evidence.py insert data/seeds/  # Seed all JSON files

# Monthly evidence refresh (first Monday of month — polling, party_positions, org_positions, currency)
# These topics decay fastest; schedule via /evidence-hunt monthly
uv run python scripts/curate_speech_evidence.py list        # Find high-value Alþingi speeches for evidence curation
uv run python scripts/fact_check_speeches.py select --limit 5  # Rank speeches for fact-checking
uv run python scripts/fact_check_speeches.py run <speech_id>   # Fact-check a single speech (run outside Claude Code session)
uv run python scripts/fact_check_speeches.py status            # Show fact-check progress
uv run python scripts/reassess_claims.py prepare           # Prepare reassessment batches (auto-cleans stale output)
uv run python scripts/reassess_claims.py prepare --only overconfident --limit 30  # Verdict audit candidates
uv run python scripts/reassess_claims.py prepare --only denominator   # Scope-word claims (denominator confusion)
uv run python scripts/reassess_claims.py prepare --evidence ID1 ID2  # Claims citing these evidence entries
uv run python scripts/reassess_claims.py prepare --claims 123 456    # Specific claims by ID
uv run python scripts/reassess_claims.py update            # Apply subagent reassessments to DB
uv run python scripts/reassess_claims.py status            # Show verdict distribution
uv run python scripts/audit_claims.py report               # Full claim verdict audit (4 patterns)
uv run python scripts/audit_claims.py candidates           # Priority reassessment list
uv run python scripts/audit_claims.py status               # Quick audit summary
uv run python scripts/publish_claims.py status             # Claim publishing summary (should show 0 eligible)
uv run python scripts/publish_claims.py eligible           # Show unpublished claims eligible for publishing
uv run python scripts/publish_claims.py backfill           # One-time: publish all eligible unpublished claims
uv run python scripts/publish_claims.py unpublish <id>     # Manually suppress a published claim
uv run python scripts/backfill_epistemic_type.py status    # Epistemic type distribution
uv run python scripts/backfill_epistemic_type.py classify  # Classify claims (heuristic, dry run)
uv run python scripts/backfill_epistemic_type.py classify --apply  # Apply classification
uv run python scripts/backfill_epistemic_type.py correct --apply   # Fix hearsay verdicts
uv run python scripts/register_article_sightings.py        # Batch-register all unregistered reports into DB sightings
uv run python scripts/build_article_registry.py --status  # Show processed article registry
uv run python scripts/check_duplicate.py --url URL        # Check if article already processed
uv run python scripts/check_evidence_urls.py status        # Link health summary
uv run python scripts/check_evidence_urls.py check         # Check all evidence URLs (3-tier)
uv run python scripts/check_evidence_urls.py populate      # Auto-populate source excerpts
uv run python scripts/check_evidence_urls.py report        # Detailed link health report
docker compose up -d       # Start PostgreSQL
Rscript R/02_eurostat.R    # Fetch Eurostat data (example; scripts 01-07)
```

## Known Friction

Documented limitations. Don't rediscover these — work around them or fix them.

- **Inline Python in SKILL.md breaks in delegated agents.** Subagents can't execute inline `python -c "..."` blocks due to Bash security scanner restrictions. Use standalone scripts in `scripts/` instead. If no script exists for a step, create one before delegating.
- **Icelandic `„"` quotes break JSON parsing.** Always use `from esbvaktin.utils.json_utils import extract_json` when parsing agent or MCP output. Never call `json.loads()` directly on text that may contain Icelandic quotes.
- **Batch processing requires phase-based orchestration.** Don't delegate the full `/analyse-article` pipeline to a single agent. Run phases from the main conversation: (1) dedup+inbox, (2) extraction agents in parallel, (3) assessment agents, (4) export. Each phase can use subagents.
- **Subagent output verification is manual.** After any agent writes a file, verify it exists with `Path(path).exists()` before proceeding. Agents report success without writing the file ~25% of the time.
- **`manage_inbox.py add-batch` breaks on Icelandic quotes.** Pre-sanitise the JSON scan file, or use `extract_json()` to parse it.

## Editorial Philosophy

ESBvaktin nurtures curiosity — it does not play gotcha. The goal is to help readers understand the EU debate more deeply, not to score points or expose who is "wrong".

- **Curiosity over judgement.** Lead with what's interesting and verifiable, not with who made a mistake. Assessments should explain what the evidence says, not just label a claim.
- **Constructive framing.** When a claim is unsupported or misleading, show what the evidence actually says and invite the reader to explore further. The capsule-writer agent's tone — "Þú ert leiðsögn, ekki dómari" — is the model for all public-facing output.
- **Enable deeper reading.** Every output (editorials, capsules, assessments) should make it easy for readers to follow the thread into primary sources and related topics.
- **No credibility scorekeeping.** Avoid framing entities as trustworthy/untrustworthy. Show what people have said and what the evidence says.
- **Balance is about fairness, not false equivalence.** Both sides are assessed with equal rigour. Patterns and quality of reasoning are legitimate observations.

This philosophy applies to all agents, export scripts, and any text that reaches the public site.

**Weekly editorials** are news digests, not fact-check reports. They answer: What was discussed? What context do readers need? How has the rhetoric evolved? What's missing from the debate? They never label individual claims as "villandi" or "óstudd" — they show what evidence says and let the reader draw conclusions.

## Design System

Always read `DESIGN.md` before making any visual or UI decisions. All font choices, colours, spacing, and aesthetic direction are defined there. Do not deviate without explicit user approval. In QA mode, flag any code that doesn't match DESIGN.md.

## Important Context

- Referendum date: 29 August 2026 — time-sensitive project
- Independence and balance are core principles — both pro-EU and anti-EU claims assessed equally
- Related projects: Metill.is (polling patterns), Thingfrettir.is (discourse pipeline patterns)
- The ESB Obsidian vault is the source of truth for design decisions
