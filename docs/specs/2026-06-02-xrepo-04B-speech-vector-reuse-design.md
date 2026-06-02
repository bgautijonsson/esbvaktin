# xrepo-04B — Reuse althingi's embedded speech vectors in the assessment context

**Date:** 2026-06-02
**Status:** approved (design), implementing
**Branch:** `pipeline-optimisation`
**Plan ref:** `esbvaktin-pipeline-optimisation-2026-06.html` → H6 / xrepo-04B

## Goal

Give the claim-assessor *topically relevant* Alþingi speeches for the claims it is
assessing, retrieved by semantic similarity against the vectors **althingi.db already
holds** (`speech_vec`, bge-m3, refreshed daily) — read-only, zero new embedding compute
on the corpus. This complements, and does not replace, today's named-MP quote-fidelity
context.

## What the current path does (`speeches/context.py`)

`build_speech_context(article_text)` substring-matches MP names found in the article, then
pulls each named MP's **most recent** EU speeches (recency, not relevance). Wired in
`scripts/pipeline/retrieve_evidence.py:89`, the result is passed to
`prepare_assessment_context(..., speech_context=...)`.

## Corrections to the plan's assumptions (confirmed by probing althingi.db)

1. **`speech_vec` is NOT EU-only.** It holds 26,194 embedded speeches / 52,968 chunks;
   only ~1.4–2.4k are EU by issue-title. The plan's "2,426 EU speeches embedded" misreads
   this. ⇒ **A post-KNN EU-scope filter is mandatory**, reusing the canonical
   `EU_ISSUE_PATTERNS` (centralised in xrepo-08). Without it the assessor is flooded with
   non-EU speeches.
2. **`speech_chunks` is a clean join table** (`chunk_id, speech_id, chunk_idx, chunk_text,
   token_count`). Resolve chunks→speeches by JOIN, not by string-splitting `chunk_id`.
   `chunk_text` is the exact embedded text — a better excerpt than `substr(full_text)`.
3. **Metric.** `speech_vec` is a `vec0` virtual table with sqlite-vec's default **L2**
   metric. bge-m3 dense vectors are L2-normalised, so L2 ranking ≡ cosine ranking. fp16
   precision means distances are cosine-*equivalent*, not bit-identical — tests assert
   ranking, not distance values. Query vector normalised defensively.

## Architecture

Two new units, separated so the retrieval logic is testable without the heavy
`embeddings` extra:

### `speeches/speech_vectors.py` (new) — pure retrieval, depends on `sqlite-vec`
- `connect_with_vec(db_path=None) -> sqlite3.Connection | None` — opens althingi.db
  read-only (`mode=ro`), `enable_load_extension`, `sqlite_vec.load(conn)`. Returns `None`
  if the DB is absent or the extension can't load (graceful).
- `search_speeches_by_vectors(query_vectors, *, k_per_query=40, max_speeches=6, eu_only=True, db_path=None) -> list[dict]`
  — for each query vector run a KNN CTE, JOIN `speech_chunks`+`speeches`, apply the EU
  filter, then **merge across vectors** (a speech matching several claims ranks higher;
  keep its best/nearest chunk as the excerpt), dedupe to distinct speeches, cap at
  `max_speeches`. Returns `[{speech_id, name, date, issue_title, excerpt, distance}]`.

  KNN SQL (over-fetch `k`, filter in the outer query):
  ```sql
  WITH knn AS (
      SELECT chunk_id, distance FROM speech_vec
      WHERE embedding MATCH :q AND k = :k
  )
  SELECT sc.speech_id, s.name, s.date, s.issue_title, sc.chunk_text, knn.distance
  FROM knn
  JOIN speech_chunks sc ON sc.chunk_id = knn.chunk_id
  JOIN speeches s       ON s.speech_id = sc.speech_id
  WHERE ({eu_filter})
  ORDER BY knn.distance
  ```

### `speeches/context.py` (extend)
- `build_topical_speech_context(claim_texts, *, claim_embeddings=None, language="is", max_speeches=6) -> str | None`
  — if `claim_embeddings` is `None`, embed `claim_texts` via `embed_texts` (needs the
  `embeddings` extra); call `search_speeches_by_vectors`; format an Icelandic markdown
  block. `claim_embeddings` is an injection seam: it lets tests pass fake vectors (no
  FlagEmbedding) and lets a later change thread cost-07's already-computed claim vectors
  in without re-embedding.
- `_format_topical_speech_context(speeches, language)` — second block, distinct header.

### Wiring (`scripts/pipeline/retrieve_evidence.py`)
After the existing `build_speech_context(...)`, also call
`build_topical_speech_context([c.claim_text for c in claims], language=...)` and append
both blocks into `speech_ctx`. Both gated by `--no-speech-context`; both wrapped in the
existing try/except so any failure degrades to the other (or to none).

## Dependency

Add **`sqlite-vec`** to core `[project.dependencies]` (not the `embeddings` extra): it is
needed by `speech_vectors.py` and by the tests, independently of FlagEmbedding. v0.1.x is
well-established and old (it created the althingi table) — past any cooldown.

## Error handling / graceful degradation

`connect_with_vec` returns `None` (logged once) on: missing DB, 0-byte stub, extension
load failure, or `sqlite_vec` import error. `search_speeches_by_vectors` returns `[]` and
`build_topical_speech_context` returns `None` ⇒ the assessor still receives today's
quote-fidelity block. The new path can never *worsen* the assessor's input vs today.

## Editorial framing (constraint check)

Two blocks answer different, both-legitimate questions: *"did the article quote this MP
faithfully?"* (existing) and *"what has Alþingi actually said about this topic?"* (new).
Both are balance-neutral, curiosity-building context — never gotcha. New header is
Icelandic (e.g. "Þingræður — efnislega tengt efni greinarinnar"); excerpts are Icelandic.
No English enters the Icelandic-only assessor context.

## TDD plan (failing tests first)

Fixture: a tiny in-test althingi.db built with sqlite-vec — three speeches (fisheries-EU,
sovereignty-EU, a non-EU roads speech) each with a chunk + a crafted 1024-dim vector, plus
`speeches`, `speech_texts`, `speech_chunks`, `schema_version`.

1. **EU filter + ranking (the killer test):** craft the query so the *nearest neighbour is
   the non-EU speech*; assert it is excluded and the fisheries-EU speech is returned.
2. **Multi-chunk dedupe:** a speech with two chunks appears once, with its nearest chunk as
   the excerpt.
3. **Cross-claim merge:** a speech relevant to two query vectors out-ranks one relevant to
   one.
4. **Graceful fallback:** missing DB / unloadable extension ⇒ `[]` / `None`, no raise.
5. **Icelandic-only:** the formatted block contains the Icelandic header and no English.
6. **`build_topical_speech_context` with injected `claim_embeddings`** (no FlagEmbedding)
   produces the block via a monkeypatched/real fixture search.

## Out of scope / follow-ups

- Threading cost-07's precomputed claim vectors out of `retrieve_evidence_for_claims`
  (avoids the one extra `embed_texts` call) — the `claim_embeddings` seam is ready; the
  return-signature change is deferred.
- Promoting semantic speech search to an `esbvaktin-speeches` MCP tool for the weekly
  overview (Option C) — deferred until the overview wants it.
- xrepo-04A (shared bge-m3 package across repos) — explicitly out; touches althingi.
