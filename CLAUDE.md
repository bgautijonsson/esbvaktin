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

Full architecture: Metill Obsidian vault → `ESB/ESB Architecture.md` (ESB lives under `ESB/` in the consolidated Metill vault)
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
    context.py          # Sync speech context for pipeline (named-MP quote-fidelity + topical relevance)
    speech_vectors.py   # Semantic speech retrieval from althingi.db speech_vec (sqlite-vec KNN, EU-scoped) — xrepo-04B
    fact_check.py       # Speech selection, loading, work dir setup for fact-checking
    register_sightings.py  # Post-assessment: match→sighting, new→unpublished claim
  ground_truth/         # Evidence database operations
  entity_registry/      # Canonical entity registry (identity, stance, observations)
    models.py           # Entity, EntityObservation, VerificationStatus, MatchMethod
    operations.py       # DB CRUD (insert, update, merge, review queue)
    matcher.py          # Name matching cascade (BÍN lemmatisation + aliases)
  claim_bank/           # Canonical claims storage with verdicts for reuse across articles
  gap_planner/          # Evidence gap identification and research task generation
  corrections/          # Project CLI wrapper (cli.py) over the shared ispipeline package; correction layers (greynir, naturalness, inflections, EU terms, Málstaður) now live in ispipeline
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
.claude/skills/         # find-articles, analyse-article, fact-check, process-inbox, plan-verification, health, db, evidence-hunt, reassess, tidy, process-articles, weekly-review, link-check, entity-review, ci (15 total)
.claude/hooks/          # Pre-export DB-integrity validation + post-push CI run-URL surfacing
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
- `uv sync --extra icelandic` — GreynirCorrect, Icegrams, Islenska, + `ispipeline` (shared correction layers, pinned by git ref @v0.1.0)
- `uv sync --extra dev` — pytest, pytest-asyncio, ruff
- `uv sync --extra email` — Mailgun integration
- `uv sync --extra ghost` — Ghost CMS publishing
- `uv sync --extra eval` — iseval harness (correction-quality CI gate)

### Icelandic Output
- Icelandic output uses GreynirCorrect (local) and Málstaður API (via `mideind` MCP server) for quality — cost rules in `.claude/rules/mcp-costs.md`
- Subagent JSON output: always parse with `_extract_json()` (sanitises `„"` quotes, strips markdown fences). Subagent field names may vary (e.g. `verdict` vs `new_verdict`) — handle both.
- Icelandic language rules auto-load via `.claude/rules/` for `*_is.*` and `data/analyses/**` paths
- Environment variables for secrets (`.env`, never committed)

## Eval gate (iseval)

CI gates the Icelandic correction pipeline against a committed baseline via the shared [iseval](https://github.com/bgautijonsson/iseval) harness (pinned by git ref in the `eval` extra of `pyproject.toml`). Adapter: `eval/iseval_adapter.py::EsbvaktinAdapter`; goldens: `eval/golden/`; tolerances: `eval/gate.json`.

- **Per-push** (`icelandic-eval` job): re-scores `eval/golden/` and fails the build if `fp_rate` rises >0.05 or any voice heuristic newly fires. Key-free, seconds.
- **Nightly** (`icelandic-eval-nightly`, Monday cron): also gates IceErrorCorpus precision/recall + gec detection (clones the corpora via a checkout of the iseval repo).

**If your change legitimately moves a number, re-baseline in the SAME PR** (fetch the corpora first with `~/iseval/scripts/eval_fetch_datasets` — they live in the gitignored `~/iseval/data/`):

```bash
uv run --extra icelandic --extra eval python -m iseval run \
  --product esbvaktin --family correction \
  --adapter eval.iseval_adapter:EsbvaktinAdapter \
  --golden eval/golden \
  --dataset iceerrorcorpus:$HOME/iseval/data/iceErrorCorpus/data/essays \
  --dataset gec:$HOME/iseval/data/gec-test-set/Type2 --sample 300 \
  --out eval/baseline.json
```

…then commit `eval/baseline.json` with the delta explained. The `--dataset` flags are required — omit them and the corpus metrics vanish from the baseline. Never widen `eval/gate.json` to dodge a real regression. Bump the iseval pin (`@vX.Y.Z`) + re-baseline when adopting a new iseval.

## Commands

Skills and key commands are in `.claude/rules/commands-reference.md` (auto-loaded when working in `scripts/` or `R/`).

## Known Friction

Documented limitations. Don't rediscover these — work around them or fix them.

- **Inline Python in SKILL.md breaks in delegated agents.** Subagents can't execute inline `python -c "..."` blocks due to Bash security scanner restrictions. Use standalone scripts in `scripts/` instead. If no script exists for a step, create one before delegating.
- **Icelandic `„"` quotes break JSON parsing.** Always use `from esbvaktin.utils.json_utils import extract_json` when parsing agent or MCP output. Never call `json.loads()` directly on text that may contain Icelandic quotes.
- **Batch processing requires phase-based orchestration.** Don't delegate the full `/analyse-article` pipeline to a single agent. Run phases from the main conversation: (1) dedup+inbox, (2) extraction agents in parallel, (3) assessment agents, (4) export. Each phase can use subagents.
- **Subagent output verification is manual.** After any agent writes a file, verify it exists with `Path(path).exists()` before proceeding. Agents report success without writing the file ~25% of the time.
- **`manage_inbox.py add-batch` breaks on Icelandic quotes.** Pre-sanitise the JSON scan file, or use `extract_json()` to parse it.
- **HTML form sentinel strings vs SQL NULL.** `<select>` dropdowns send `""` or `"none"` for "no value", but nullable DB columns need `NULL`. `update_entity()` normalises sentinels for nullable columns. New entity UI dropdowns must use `value=""` (not `value="none"`) for "None" options, and `saveEdit()` converts empties to `null` before PATCH.
- **Entity test fixtures use transaction rollback isolation.** `conn.commit` is neutered during tests so production entity data is never wiped. New entity test fixtures must follow this pattern — never `DELETE FROM entities` + `conn.commit()` in teardown.
- **`manage_inbox.py set-status` is not concurrency-safe.** The script reads, modifies, and rewrites the whole `data/inbox/inbox.json` file. Parallel invocations (e.g., from `ThreadPoolExecutor` in pipeline Phase 7) silently lose writes — each thread reports success while the last writer wins. **Always call `set-status` sequentially**, even when other Phase 7 steps (`write_capsule`, `register_sightings`) run in parallel. After parallel processing, do a single-threaded loop for `set-status` calls.
- **`assemble_report.py` requires `confidence` on every claim object.** If the assessor agent returns a claim dict without `confidence`, Pydantic validation fails and assembly aborts. Symptoms: `pydantic_core.ValidationError: claim.confidence Field required`. Workaround: patch the `_assessments.json` by copying `confidence` from the corresponding `_claims.json` entry before retrying. Long-term fix: default `confidence` to 0.7 in `parse_assessments()` or strengthen the assessor system prompt.
- **`reassess_claims.py prepare` doesn't clean old batches.** Old `_context_batch_N.md` and `_assessments_batch_N.json` files from prior `prepare` runs persist on disk. Subsequent `update` runs report "MISSING" for the orphans (harmless but noisy). Either clean `data/reassessment/` manually between unrelated reassess sessions or add `--clean` to the prepare script.
- **`extract_json()` returns a cleaned string, not parsed JSON.** The caller must still do `json.loads(extract_json(text))`. Easy to forget — `len(extract_json(text))` returns the string length, not the array length, which makes empty-data look like success.
- **Lightweight batched extraction is much more efficient than per-article.** For inbox processing without full assessment, concatenate ~15 article texts into one context file (`/tmp/lw_batches/batch_NN_context.md`) with `===ARTICLE===` separators. One `claim-extractor` agent processes all 15 and outputs `[{id, url, claims: []}, ...]`. ~5× less context vs 15 individual extractors. See `/tmp/build_batch_contexts.py` from 2026-05-25 sync for working template.
- **`manage_inbox.py next --limit N` doesn't return LOW priority by default.** It prefers HIGH/MEDIUM and stops when those are exhausted, even if `N` isn't reached. To process LOW priority, query separately with explicit filter or iterate through the inbox JSON directly.

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
- The Metill Obsidian vault (`ESB/` subfolder) is the source of truth for design decisions
- **Wiki operations:** After sessions, update [[ESB Handoff]], append to vault-root `log.md`, update `index.md` if structure changed. File reusable findings to `ESB/Knowledge/` — see `Vault Guide.md` for Ingest/Query/Lint workflows
