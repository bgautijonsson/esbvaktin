# Methodology / Aðferðafræði

This document describes how ESB Vaktin analyses public discourse about Iceland's EU membership referendum. The entire pipeline — including all AI prompts, evidence data, and assessment logic — is open source in this repository.

**Icelandic version**: [esbvaktin.is/adferdarfraedi](https://esbvaktin.is/adferdarfraedi/)

## Overview

ESB Vaktin monitors Icelandic media and parliamentary discourse for factual claims about EU membership. Each claim is assessed against a curated evidence database. The platform treats pro-EU and anti-EU claims identically.

```
Article/speech → Claim extraction → Evidence matching → Assessment → Publication
```

## 1. Ground Truth evidence database

The foundation is a curated database of **390+ evidence entries** covering fisheries, trade, sovereignty, agriculture, currency, labour, energy, and more. Each entry contains:

- A factual statement with source citation
- Source type (official statistics, legal text, academic paper, expert analysis, international organisation, parliamentary record)
- Confidence level and caveats
- Semantic embedding for search

Evidence entries are sourced from official statistics (Hagstofa, Eurostat), legal texts (EEA Agreement, EU treaties), academic papers, and international organisations. All seed data is committed in [`data/seeds/`](data/seeds/) under CC BY-SA 4.0.

**Anyone can inspect, verify, or challenge the evidence base.**

## 2. Claim extraction

When an article or speech is analysed, the first step is extracting factual claims. This is done by an AI agent ([`.claude/agents/claim-extractor.md`](.claude/agents/claim-extractor.md)) that:

- Reads the full article text
- Identifies statements that make factual assertions about EU membership
- Filters out opinions, biographical details, procedural matters, and common knowledge
- Outputs structured JSON with the claim text, category, and type

The extraction rules and filtering criteria are defined in the context preparation code ([`src/esbvaktin/pipeline/prepare_context.py`](src/esbvaktin/pipeline/prepare_context.py)).

### What gets filtered out

The pipeline explicitly excludes:
- Pure opinions without factual basis
- Biographical information about speakers
- Procedural/parliamentary matters
- Common knowledge ("Iceland is not in the EU")
- Claims unrelated to EU membership

## 3. Evidence matching

Each extracted claim is matched against the evidence database using semantic similarity search (BAAI/bge-m3 multilingual embeddings). The top matching evidence entries are retrieved and provided as context for assessment.

This is not keyword matching — the system understands that "kvótakerfið" (the quota system) relates to evidence about fisheries policy, even without exact word overlap.

## 4. Claim assessment

Assessment is the most critical step. An AI agent ([`.claude/agents/claim-assessor.md`](.claude/agents/claim-assessor.md)) evaluates each claim against the matched evidence using a five-point scale:

| Verdict | Meaning |
|---------|---------|
| **Supported** | Evidence clearly supports the claim |
| **Partially supported** | Some evidence supports it, but important context is missing or the claim oversimplifies |
| **Unsupported** | Evidence does not support the claim |
| **Misleading** | The claim uses real data but presents it in a way that creates a false impression |
| **Unverifiable** | Insufficient evidence in the database to assess |

### Assessment principles

These are enforced in the agent prompt:

1. **Impartiality**: Pro-EU and anti-EU claims are assessed with identical rigour
2. **Evidence-bound**: Every verdict must cite specific evidence entries. No assessment without sources
3. **Caveats matter**: If evidence has qualifications, they must appear in the assessment
4. **Epistemic humility**: When evidence is insufficient, the verdict is "unverifiable" — never a guess

### What the AI can and cannot do

The assessment agent:
- **Can** read the article, the matched evidence, and the assessment instructions
- **Cannot** access the internet, execute code, or use any tool except reading/writing files
- **Cannot** introduce information not in the evidence database
- **Does** write assessments in Icelandic, directly (not translated from English)

## 5. Omission and framing analysis

A separate agent ([`.claude/agents/omissions-analyst.md`](.claude/agents/omissions-analyst.md)) analyses what the article *doesn't* say — identifying missing context, one-sided framing, or important caveats that were omitted. This runs in parallel with assessment.

## 6. Human oversight

The pipeline is AI-assisted, not AI-autonomous:

- Evidence entries are human-curated and source-verified
- Published claims are reviewed before the `published` flag is set
- Verdicts can be updated as new evidence is added
- The entire codebase, including all prompts, is open for public scrutiny

## 7. Transparency guarantees

| What | Where | Licence |
|------|-------|---------|
| AI agent prompts | [`.claude/agents/`](.claude/agents/) | AGPL-3.0 |
| Context preparation (full instructions to AI) | [`src/esbvaktin/pipeline/prepare_context.py`](src/esbvaktin/pipeline/prepare_context.py) | AGPL-3.0 |
| Evidence database seed data | [`data/seeds/`](data/seeds/) | CC BY-SA 4.0 |
| Assessment logic and orchestration | [`src/esbvaktin/pipeline/`](src/esbvaktin/pipeline/) | AGPL-3.0 |
| Database schema | [`src/esbvaktin/ground_truth/schema.sql`](src/esbvaktin/ground_truth/schema.sql) | AGPL-3.0 |
| This methodology document | [METHODOLOGY.md](METHODOLOGY.md) | CC BY-SA 4.0 |

Every step of the analysis — from the exact instructions given to the AI, to the evidence it draws on, to the code that assembles the final report — is version-controlled and publicly auditable.

## Limitations

- **AI is not infallible**: The assessment agent can make errors. That's why evidence is cited — readers can verify.
- **Evidence gaps**: The database doesn't cover everything. Claims outside its scope are marked "unverifiable", not guessed at.
- **Language model bias**: We mitigate this through structured prompts, evidence-binding, and equal treatment of all political positions. But no system is perfectly neutral.
- **Timeliness**: Evidence entries have a `last_verified` date. Some data may become outdated between verification cycles.

## Reproducing the pipeline

See [CONTRIBUTING.md](CONTRIBUTING.md) for full setup instructions. In brief:

```bash
docker compose up -d                              # Start PostgreSQL
uv run python scripts/init_db.py --seed           # Create schema + seed evidence
# Then run the analysis pipeline on any article
```

The analysis pipeline requires Claude API access (via Claude Code). All other components — the database, evidence, embeddings, and export pipeline — run locally.
