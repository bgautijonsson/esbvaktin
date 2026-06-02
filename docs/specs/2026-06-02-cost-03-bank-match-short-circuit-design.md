# cost-03 — Short-circuit Opus on exact + fresh claim-bank matches

**Date:** 2026-06-02
**Status:** approved (Option A: strict); implementing
**Branch:** `pipeline-optimisation`
**Plan ref:** `esbvaktin-pipeline-optimisation-2026-06.html` → H8 / cost-03 (reuses cost-04 merge path)

## Goal

When a claim already has a **strong, fresh, unflagged** verdict in the claim bank,
reuse it instead of paying a full Opus assessment. Unlike cost-01 (caching a 2.6%
prefix), this removes the **whole Opus call — input *and* output — plus the pgvector
retrieval**, which is where the real assessor cost is. Balance-neutral by
construction: it reuses whatever the prior assessment concluded, equally for pro-
and anti-EU claims, only for exact/fresh/unflagged factual matches.

## Current behaviour (the waste)

`retrieve_evidence_for_claims` (retrieve_evidence.py:325–344) detects a bank match,
logs "Strong prior (≥0.85, fresh)" — then **retrieves evidence and falls through to
the Opus assessor anyway**. The hearsay short-circuit (281–301) + the cost-04 persist
path (`persist_hearsay_assessments` → `assemble_report` merge at line 56) is the
pattern to mirror.

## Why it's clean

A `ClaimBankMatch` already carries the full stored assessment — `verdict`,
`explanation_is`, `supporting_evidence`/`contradicting_evidence` IDs, `confidence`,
`epistemic_type`, `is_fresh`. `assemble_report` resolves evidence IDs → full
statements independently, so a reused verdict stays **evidence-rich** with no fresh
retrieval. A short-circuited claim therefore mirrors hearsay exactly: build a
`ClaimAssessment`, persist it, merge it — skipping Opus *and* retrieval.

## Skip criteria (Option A — strict)

Short-circuit iff **all** hold (`is_reusable_bank_match`):
- `similarity >= BANK_EXACT_THRESHOLD` (0.85)
- `is_fresh` (last_verified ≤ 30 days)
- `not needs_reassessment` (the system's own "this verdict needs revisiting" flag)
- `epistemic_type == "factual"` (predictions/counterfactuals keep their 0.8-ceiling
  reasoning-based assessment; hearsay is already short-circuited upstream)

`needs_reassessment` is **not** currently on `ClaimBankMatch` — add it to the model
and the `search_claims` SELECT (the `claims` table has the column via the GT
migration).

## Changes

**claim_bank** — `ClaimBankMatch.needs_reassessment: bool = False`; add it to the
`search_claims` SELECT + columns list.

**retrieve_evidence.py (pure helpers, testable):**
- `is_reusable_bank_match(match) -> bool` — the four-part predicate above.
- `bank_match_to_assessment(claim, match) -> ClaimAssessment` — reuse verdict,
  explanation_is, supporting/contradicting evidence, missing_context_is, confidence.

**retrieve_evidence.py (`retrieve_evidence_for_claims`):** restructure the loop —
reusable match ⇒ append to `bank_assessments` and `continue` (skip retrieval + Opus);
otherwise retrieve evidence, record any fuzzy match as `bank_matches[len(claims_with_evidence)]`
(**re-keyed by the Opus-bound index** so `prepare_assessment_context`'s `bank_matches[i-1]`
stays aligned), and append. Return a **4-tuple**:
`(claims_with_evidence, bank_matches, hearsay_assessments, bank_assessments)`.

**parse_outputs.py:** `persist_bank_assessments` / `parse_bank_assessments` mirroring
the hearsay pair (file `_bank_assessments.json`). cost-04's hearsay code is untouched
(additive).

**Callers (mechanical 4-tuple unpack):** `scripts/pipeline/retrieve_evidence.py`
(also persists bank + prints the count), `scripts/fact_check_speeches.py`,
`tests/test_retrieve_evidence.py`, `tests/test_hearsay_short_circuit.py`.

**assemble_report.py:** merge `+ parse_bank_assessments(work_dir)`.

## TDD plan (failing tests first)
1. `is_reusable_bank_match`: True for exact+fresh+factual+unflagged; False if
   similarity < 0.85 / not fresh / `needs_reassessment` / non-factual epistemic_type
   (one assertion per guard).
2. `bank_match_to_assessment`: produces a `ClaimAssessment` carrying the reused
   verdict + evidence IDs + confidence + explanation, bound to the article's claim.
3. `ClaimBankMatch` round-trips `needs_reassessment` (default False).
4. `retrieve_evidence_for_claims` (mock conn + `check_claim_bank`, following
   test_hearsay_short_circuit/test_embed_once): a reusable match lands in
   `bank_assessments` and **not** in `claims_with_evidence`; a fuzzy (0.70–0.85)
   match stays in `claims_with_evidence` with `bank_matches` keyed to its Opus-list
   index; a stale/flagged exact match is **not** short-circuited.
5. `persist_bank_assessments`/`parse_bank_assessments`: round-trip + empty ⇒ no file.

## Out of scope / follow-ups
- `article_claims.cache_hit = TRUE` for short-circuited claims (the schema has the
  flag) — deferred; the script logs the count for now, so the hit rate is visible
  without the registration change.
- Tiering fuzzy 0.70–0.85 matches differently (they still go to Opus, as today).
