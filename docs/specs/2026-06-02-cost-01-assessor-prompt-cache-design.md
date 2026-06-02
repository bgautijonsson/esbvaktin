# cost-01 — Prompt-cache the claim-assessor's invariant prefix (measure-first)

**Date:** 2026-06-02
**Status:** approved (approach A: measure-first); measurement increment implementing
**Branch:** `pipeline-optimisation`
**Plan ref:** `esbvaktin-pipeline-optimisation-2026-06.html` → H1 / cost-01 (depends on cost-02, done)

## Goal

Stop re-billing the assessor's ~3k-token invariant prefix on every Opus call by
caching it. The plan's cost estimate is structural, not measured — so the **first
increment is a measurement**, not a cutover: prove the cache works on real
contexts and surface the real token/cost (and billing) reality before changing
the pipeline.

## Findings that reshape cost-01 (investigation, 2026-06-02)

- **The Task tool won't cache the block.** `claude-code-guide` (citing the
  subagents + prompt-caching docs): each Task invocation gets a fresh isolated
  context; the 12 KB block enters as a Read tool *result*, not a stable prefix;
  the Task tool exposes no `cache_control`; 5-min TTL ⇒ separate runs start cold.
  Caching requires a **direct Anthropic-SDK call**.
- **Assessor-only.** The other hot agent, `editorial-writer`, depends on MCP
  tools (morphology, mideind) a bare SDK call can't reach, and runs ~once/week.
  Out of scope. `claim-assessor` has no MCP deps and is the volume/cost sink.
- **Billing caveat (decides the payoff).** A direct SDK call bills via the
  Anthropic API (`ANTHROPIC_API_KEY`), separate from the Claude Code session that
  runs the assessor today. The measurement reveals the real cost; the cutover is
  gated on it.
- **The win is batch-clustered.** A one-off `/analyse-article` gets no benefit
  (pays the cache write, no reads). Savings come from clustered calls (the
  overnight batch) and/or the 1-hour extended TTL keeping the batch warm.
- **Reliability bonus.** The SDK harness writes `_assessments.json` itself ⇒ the
  ~25% "subagent forgot to write" failure mode vanishes for the assessor; the
  guard becomes a post-write JSON assertion (reuse `validate_workdir`) + SDK retry.

## Context split (cost-02 already made this clean)

`prepare_assessment_context` assembles: `[invariant instruction + Icelandic
quality blocks]` + `\n\n## Fullyrðingar og heimildir\n\n` + `[per-article claims,
evidence, speeches]`. The heading marker (`## Fullyrðingar og heimildir` for `is`,
`## Claims and Evidence` for `en`) is the **cache split point**:
- **cached prefix** = system prompt + everything before the marker (byte-identical
  across runs);
- **variable suffix** = the marker onward (per-article).

## Architecture

### `esbvaktin/llm/cached_call.py` (new) — pure, no `anthropic` import
- `split_assessment_context(md, language="is") -> (prefix, suffix)` — split on the
  marker; if absent, treat the whole text as suffix (no cached prefix).
- `build_cached_messages(system, prefix, suffix, *, ttl="1h") -> dict` — returns
  `{system, messages}` with `cache_control` on the prefix content block (and the
  system block) and none on the suffix. Plain dicts the SDK accepts.
- `parse_usage(usage) -> dict` — duck-typed read of `input_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`.
- `call_cached(client, system, prefix, suffix, *, model, max_tokens, ttl) -> (text, usage_dict)`
  — calls `client.messages.create(**payload)`; **client injected** (real
  `anthropic.Anthropic` in production, fake in tests).
- `assessor_system_prompt() -> str` — load the claim-assessor agent body and adapt
  the output instruction: **return the flat JSON array as the response** (no Write
  tool in a bare SDK call). Icelandic-only — no English leaks.

### `scripts/measure_assessor_cache.py` (new) — the measurement (integration)
Given a real work-dir: split the context, build the request, call the SDK **twice**
(call 1 = cache write, call 2 = cache read within TTL), print + log real
`cache_creation`/`cache_read`/`input`/`output` tokens and the cost delta (Opus
pricing: cache write 1.25×, read 0.1× of base input). Append to the cost-09
telemetry — finally real tokens, not the byte proxy. Requires `ANTHROPIC_API_KEY`;
exits cleanly if absent. ~2 Opus calls (a few cents).

### Dependency
Add `anthropic` (only needed to run the script; the module + its tests don't import
it — the client is injected).

## TDD plan (failing tests first; no API calls in tests)
1. `split_assessment_context`: prefix ends before the marker, suffix begins at it;
   marker-absent ⇒ ("", whole text).
2. `build_cached_messages`: `cache_control` present on the prefix block (and
   system), absent on the suffix block; suffix text intact.
3. `parse_usage`: maps a duck-typed usage object to the four counts (missing fields
   default to 0).
4. `call_cached` with an injected fake client: forwards the built payload and
   returns (text, parsed-usage). No real network.
5. `assessor_system_prompt`: returns Icelandic text instructing a JSON-array
   response, with no English and no "_assessments.json"/Write-tool wording.

The live two-call measurement is run manually (billable) — not a unit test.

## Cutover (provisional — gated on the measurement, separate increment)
If the measured win justifies it: replace the pipeline's `Agent: claim-assessor`
dispatch with `scripts/pipeline/assess_claims.py` calling `call_cached` + writing
`_assessments.json` (parsed via `extract_json`), with a post-write
`validate_workdir`-style assertion + one SDK retry. omissions-analyst stays on Task
(parallel). TTL and per-article-vs-batched call shape finalised from the numbers.

## Out of scope
- editorial-writer (MCP-blocked, low volume).
- The cutover itself until the measurement justifies it.
