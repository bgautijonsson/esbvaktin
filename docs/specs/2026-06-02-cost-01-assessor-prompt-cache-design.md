# cost-01 — Prompt-cache the claim-assessor's invariant prefix (measure-first)

**Date:** 2026-06-02
**Status:** MEASURED (2026-06-02) — caching win is <1% of total assessor cost; the
full cutover is **NOT recommended**. See "Measurement result" below. The harness +
measurement tool are retained as the instrument and an optional live confirmation.
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

### `scripts/measure_assessor_cache.py` (new) — the measurement
**Default (free, no API):** the structural cacheable-fraction analysis over all real
contexts — the decisive measurement (see "Measurement result"). **`--live <work-dir>`
(billable):** split the context, call the SDK **twice** (call 1 = cache write, call 2
= cache read within TTL) and report real `cache_creation`/`cache_read`/`input`/`output`
tokens. Requires `ANTHROPIC_API_KEY`; exits cleanly if absent. ~2 Opus calls (cents).

### Dependency
`anthropic` is **not** added — the module and its tests don't import it (the client is
injected). The opt-in `--live` confirmation lazy-imports it and instructs `uv add
anthropic` only if you choose to run the billable measurement.

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

## Measurement result (2026-06-02)

`scripts/measure_assessor_cache.py` (structural, free, over 596 real contexts):

| Metric | Value |
|---|---|
| Median context size | ~115,000 chars |
| Cacheable invariant prefix | 2.6–3.4 KB, **byte-identical** across files |
| Prefix as fraction of input | **median 2.6%**, mean 3.7%, max 23.2% |
| Best-case INPUT-token saving @100% hit | **median 2.3%**, max 20.9% |

The plan's "60–80% input-token reduction" was off by more than an order of
magnitude. It assumed the invariant block dominated the request; in reality the
per-article claims+evidence (median ~115 KB) dominate and are **variable, hence
uncacheable**. Output tokens (never cached, ~5× input price on Opus) dominate total
cost further, so caching the prefix saves **<1% of total assessor cost** — before
accounting for the <100% real hit rate (5-min TTL) and the 1.25× cache-write penalty
that makes one-off `/analyse-article` runs slightly *more* expensive.

## Cutover — NOT recommended

Moving the assessor off the Task tool onto an API-billed SDK harness (new dep, new
billing model, more operational surface) is **not justified** by a <1% saving. The
harness (`esbvaktin/llm/cached_call.py`, tested) and `measure_assessor_cache.py` are
kept as the measurement instrument; `--live <work_dir>` runs a billable two-call
confirmation if the exact token numbers are ever wanted.

## The real lever this surfaced (out of cost-01 scope)

The dominant assessor input is the **per-article evidence payload** (median ~115 KB;
`MAX_EVIDENCE_PER_CLAIM = 7`, full statements). If assessor input cost matters, the
lever is trimming that payload (fewer or compacted evidence statements, `statement_is`
over full English, dedupe shared evidence across claims) — a separate optimisation,
not prompt caching. Flagged for a future item; not pursued here without sign-off.

## Out of scope
- editorial-writer (MCP-blocked, low volume).
- The cutover itself until the measurement justifies it.
