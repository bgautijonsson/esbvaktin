# Process Articles

Batch-analyse pending articles from the inbox using phase-based parallelism. Each article goes through the full `/analyse-article` pipeline (extract claims, retrieve evidence, assess, analyse omissions, assemble report, extract entities, write capsule).

This is the **full analysis pipeline**, not the lightweight claim harvesting of `/process-inbox`.

## Usage

```
/process-articles              # Process top 3 pending articles (default batch)
/process-articles 5            # Process top 5
/process-articles triage       # Show sorted triage table, wait for user selection
/process-articles ID1 ID2 ID3  # Process specific articles by inbox ID
```

Natural language triggers: "process articles", "analyse the pending articles", "process the top 5", "run batch analysis".

## Batch Size

Default: **3 articles** (= 6 concurrent agents in Phase 4, the bottleneck phase).
Maximum recommended: **5 articles** (= 10 concurrent agents). Never exceed 5 without user confirmation.

The bottleneck is Phase 4 (claim assessment via Opus + omission analysis via Sonnet). Each assessor takes 5-10 minutes. More concurrent agents don't speed up individual articles — they enable parallel processing of multiple articles.

## Steps

### Step 0: Select Articles

**If `triage` mode:**
```bash
uv run python scripts/manage_inbox.py triage
```
Present the table to the user. Wait for them to specify which articles to process (by number, by ID, or "top N"). Do not proceed until the user selects.

**If specific IDs given:** Use those IDs directly.

**If number or default:** Get the top N pending articles:
```bash
uv run python scripts/manage_inbox.py next --limit N --json
```

Parse the JSON output. These are the articles to process. Print a brief summary:

```
Processing N articles:
1. [HIGH] Source — Title (date)
2. [MEDIUM] Source — Title (date)
...
```

Queue all selected articles:
```bash
uv run python scripts/manage_inbox.py queue ID1 ID2 ID3
```

### Phase 1: Fetch and Prepare (Python, sequential)

For each article in the batch:

1. **Dedup check:**
   ```bash
   uv run python scripts/check_duplicate.py --url "URL"
   ```
   If exit code 0 (duplicate): skip this article, log it, continue with next. If exit code 2 (error): skip with warning.

2. **Fetch article:**
   ```bash
   uv run python scripts/pipeline/fetch_article.py --url "URL" --inbox-id ID
   ```
   Save the printed `Work dir:` path. If fetch fails, remove article from batch and continue.

3. **Content-based dedup:**
   ```bash
   uv run python scripts/check_duplicate.py --text-file $WORK_DIR/_article.md
   ```
   If exit code 0 (content match): skip this article, log the match.

4. **Prepare extraction context:**
   ```bash
   uv run python scripts/pipeline/prepare_extraction.py $WORK_DIR
   ```

After Phase 1, print a checkpoint:
```
Phase 1 complete: N/M articles ready for extraction.
[Skipped: X duplicate, Y fetch failed]
```

Track the batch as a list of `(inbox_id, work_dir, url, title)` tuples. Remove failed articles from the list.

### Phase 2: Extract Claims (Parallel Agents)

For each article in the batch, spawn a **claim-extractor** agent:

```
Agent: claim-extractor (subagent_type="claim-extractor")
Prompt: Read $WORK_DIR/_context_extraction.md and extract all factual claims.
        Write the JSON array to $WORK_DIR/_claims.json.
```

Spawn **all extractors in a single message** (parallel agent calls). Wait for all to complete.

**Verify:** For each article, check that `$WORK_DIR/_claims.json` exists (use Glob tool). If missing, resume that agent with: "You MUST use the Write tool to write the JSON array to $WORK_DIR/_claims.json NOW." One retry max — if still missing, remove from batch.

Print checkpoint:
```
Phase 2 complete: Extracted claims from N articles.
  - Article 1: 8 claims
  - Article 2: 12 claims
[Failed: Article 3 — extractor produced no output]
```

### Phase 3: Retrieve Evidence (Python, sequential)

For each article remaining in the batch:

```bash
uv run python scripts/pipeline/retrieve_evidence.py $WORK_DIR
```

This is the step that previously caused Bash security scanner issues as inline `python -c`. Now it's a clean script call.

If evidence retrieval fails for an article (DB connection issue, parse error), remove it from batch and continue.

Print checkpoint:
```
Phase 3 complete: Evidence retrieved for N articles.
```

### Phase 4: Assess Claims + Analyse Omissions (Parallel Agents — BOTTLENECK)

For each article in the batch, spawn **two agents in parallel**:

```
Agent: claim-assessor (subagent_type="claim-assessor")
Prompt: Read $WORK_DIR/_context_assessment.md and assess all claims against evidence.
        Write the flat JSON array to $WORK_DIR/_assessments.json.

Agent: omissions-analyst (subagent_type="omissions-analyst")
Prompt: Read $WORK_DIR/_context_omissions.md and analyse omissions and framing.
        Write the JSON object to $WORK_DIR/_omissions.json.
```

Spawn **all agents for all articles in a single message** (e.g. 3 articles = 6 agents). This is the longest phase (~5-10 minutes).

Print before waiting:
```
Phase 4 starting: N assessors + N omissions analysts (2N agents).
This is the longest phase — expect ~5-10 minutes.
```

**Verify after completion:**
- `_assessments.json` must exist for each article. If missing, one retry. If still missing, remove from batch.
- `_omissions.json` should exist. If missing, one retry. If still missing after retry, continue WITHOUT omissions (assessment is more important).

Print checkpoint:
```
Phase 4 complete: N articles assessed.
[Failed: Article X — assessor timeout]
```

### Phase 5: Assemble Reports (Python, sequential)

For each article remaining in the batch:

```bash
uv run python scripts/pipeline/assemble_report.py $WORK_DIR
```

This writes `_report_is.md`, `_report.json`, and `_report_final.json`.

Print checkpoint with verdict summaries:
```
Phase 5 complete: N reports assembled.
  - Article 1: 3 supported, 2 partial, 1 misleading (completeness: 78%)
  - Article 2: 5 supported, 1 unverifiable (completeness: 85%)
```

### Phase 6: Post-processing (Python + Parallel Agents)

For each article, prepare contexts (Python, sequential — fast):
```bash
uv run python scripts/pipeline/prepare_entities.py $WORK_DIR
uv run python scripts/pipeline/prepare_capsule.py $WORK_DIR
```

Note: `prepare_entities.py` for panel shows generates `_entities.json` directly (no agent needed). Only spawn entity-extractor for articles where `_entities.json` does NOT already exist.

Then spawn agents for all articles in parallel:

```
Agent: entity-extractor (subagent_type="entity-extractor")
Prompt: Read $WORK_DIR/_context_entities.md and extract all entities/speakers.
        Write the JSON object to $WORK_DIR/_entities.json.

Agent: capsule-writer (subagent_type="capsule-writer")
Prompt: Lestu $WORK_DIR/_context_capsule.md og skrifaðu lesandanótu.
        Skrifaðu niðurstöðuna í $WORK_DIR/_capsule.txt.
```

Verify outputs. One retry per failed agent.

### Phase 7: Finalise (Python, sequential)

For each article:

1. **Write capsule into report:**
   ```bash
   uv run python scripts/pipeline/write_capsule.py $WORK_DIR
   ```

2. **Register sightings:**
   ```bash
   uv run python scripts/register_article_sightings.py --dir $(basename $WORK_DIR)
   ```

3. **Update inbox status:**
   ```bash
   uv run python scripts/manage_inbox.py set-status INBOX_ID processed
   ```

### Final Summary

Present a batch results table:

```markdown
## Batch Analysis Complete

| # | Title | Source | Verdicts | Completeness | Capsule |
|---|-------|--------|----------|--------------|---------|
| 1 | Article title... | RÚV | 3S 2P 1M | 78% | yes |
| 2 | Article title... | mbl.is | 5S 1U | 85% | yes |

Processed: N articles. Failed: M.
Total claims assessed: X.
```

If any articles failed, list them with the phase where they failed:
```
### Failed Articles
- "Title" — failed in Phase 4 (assessor timeout)
- "Title" — skipped in Phase 1 (duplicate of 20260319_142055)
```

## Error Handling Summary

| Phase | On failure | Action |
|-------|-----------|--------|
| 1 (fetch) | Fetch fails or duplicate | Skip article, continue batch |
| 2 (extraction) | No `_claims.json` | One retry, then skip article |
| 3 (evidence) | DB error or parse failure | Skip article, continue batch |
| 4 (assessment) | No `_assessments.json` | One retry, then skip article |
| 4 (omissions) | No `_omissions.json` | One retry, then continue WITHOUT omissions |
| 5 (assembly) | Assembly error | Skip article, continue batch |
| 6 (entities/capsule) | Agent timeout | One retry, then continue without (non-fatal) |
| 7 (finalise) | Registration error | Log warning, continue |

The batch always completes — individual failures don't block other articles.
