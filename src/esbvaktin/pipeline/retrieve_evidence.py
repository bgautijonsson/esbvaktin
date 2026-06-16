"""Evidence retrieval for extracted claims.

Pure Python — no LLM needed. Queries the Ground Truth Database
via semantic search for each claim. Optionally checks the Claim Bank
first for pre-processed assessments.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from isretrieval import rrf_fuse

from esbvaktin.ground_truth import SearchResult, search_evidence

from .models import (
    KNOWN_TOPICS,
    Claim,
    ClaimAssessment,
    ClaimWithEvidence,
    EpistemicType,
    EvidenceMatch,
    Verdict,
)

if TYPE_CHECKING:
    from esbvaktin.claim_bank.models import ClaimBankMatch

logger = logging.getLogger(__name__)

# Similarity thresholds for claim bank matching
BANK_EXACT_THRESHOLD = 0.85  # Reuse verdict directly (strong prior)
BANK_FUZZY_THRESHOLD = 0.70  # Show as context to assessment subagent
MIN_SIMILARITY = 0.45  # Floor for evidence retrieval (filter noise)
MAX_EVIDENCE_PER_CLAIM = 7  # Hard cap per claim (primacy-recency ordering applied)


def _search_result_to_match(result: SearchResult) -> EvidenceMatch:
    return EvidenceMatch(
        evidence_id=result.evidence_id,
        statement=result.statement,
        similarity=result.similarity,
        source_name=result.source_name,
        source_url=result.source_url,
        source_date=result.source_date,
        caveats=result.caveats,
        confidence=result.confidence,
        statement_is=result.statement_is,
    )


def _reorder_primacy_recency(items: list) -> list:
    """Reorder evidence for primacy-recency effect.

    Best item first, second-best item last, remainder in the middle.
    Assumes input is already sorted descending by similarity.
    LLMs attend most to the beginning and end of context (SIGIR 2026).
    """
    if len(items) <= 2:
        return list(items)
    first = items[0]
    last = items[1]
    middle = items[2:]
    return [first, *middle, last]


RRF_K = 60  # Standard Reciprocal Rank Fusion constant


def _rrf_merge(
    vector_results: list[SearchResult],
    keyword_results: list[SearchResult],
    vector_weight: float = 1.0,
    keyword_weight: float = 1.0,
) -> list[tuple[SearchResult, float]]:
    """Reciprocal Rank Fusion of vector and keyword search results.

    Returns (SearchResult, rrf_score) tuples sorted by score descending.
    Documents appearing in both lists rank higher than either alone.

    Thin wrapper over the shared ``isretrieval.rrf_fuse`` (golden-tested to
    reproduce this fusion byte-identically): 1-based ranks, the RRF_K constant,
    and insertion-order tie-breaking (vector list before keyword list).
    """
    return rrf_fuse(
        vector_results,
        keyword_results,
        key=lambda r: r.evidence_id,
        weights=[vector_weight, keyword_weight],
        k=RRF_K,
    )


def is_reusable_bank_match(match: ClaimBankMatch) -> bool:
    """Whether a claim-bank match is strong enough to reuse its verdict directly,
    skipping the Opus assessor (cost-03, Option A — strict).

    All four guards must hold: an exact match (>= BANK_EXACT_THRESHOLD), a fresh
    verdict (verified within 30 days), no pending reassessment flag, and a factual
    claim (predictions/counterfactuals keep their reasoning-based assessment; hearsay
    is short-circuited upstream). Balance-neutral: it reuses whatever the prior
    assessment concluded, equally for every stance.
    """
    return (
        match.similarity >= BANK_EXACT_THRESHOLD
        and match.is_fresh
        and not match.needs_reassessment
        and match.epistemic_type == "factual"
    )


def bank_match_to_assessment(claim: Claim, match: ClaimBankMatch) -> ClaimAssessment:
    """Build a pre-built assessment that reuses a fresh bank verdict (cost-03), so a
    short-circuited claim reaches the report and sightings without an Opus call. The
    bank's stored evidence IDs ride along, so assemble_report resolves them to full
    statements and the report stays evidence-rich."""
    return ClaimAssessment(
        claim=claim,
        verdict=Verdict(match.verdict),
        explanation=match.explanation_is,
        supporting_evidence=list(match.supporting_evidence),
        contradicting_evidence=list(match.contradicting_evidence),
        missing_context=match.missing_context_is,
        confidence=match.confidence,
    )


def check_claim_bank(
    claim: Claim,
    conn=None,
    embedding: list[float] | None = None,
) -> ClaimBankMatch | None:
    """Check if a similar claim exists in the claim bank.

    Returns the best match above BANK_FUZZY_THRESHOLD, or None.
    Caller decides whether to treat as strong prior (>= BANK_EXACT_THRESHOLD
    and fresh) or just as context. Pass ``embedding`` to reuse a precomputed
    query vector (cost-07).
    """
    try:
        from esbvaktin.claim_bank.operations import search_claims

        matches = search_claims(
            query=claim.claim_text,
            threshold=BANK_FUZZY_THRESHOLD,
            top_k=1,
            conn=conn,
            embedding=embedding,
        )
        if matches:
            match = matches[0]
            logger.info(
                "Claim bank match: %.3f similarity for '%s' → '%s'",
                match.similarity,
                claim.claim_text[:50],
                match.claim_slug,
            )
            return match
    except Exception:
        # Claim bank not available (table doesn't exist, etc.)
        logger.debug("Claim bank not available, skipping lookup")
    return None


def retrieve_evidence_for_claim(
    claim: Claim,
    top_k: int = 5,
    conn=None,
    embedding: list[float] | None = None,
) -> ClaimWithEvidence:
    """Retrieve evidence for a single claim using hybrid BM25 + vector search.

    Runs three searches:
    1. Topic-filtered vector search (if the claim's category matches a known topic)
    2. Unfiltered vector search (catches cross-topic evidence)
    3. Keyword (BM25) search via PostgreSQL tsvector

    Vector results are merged by evidence_id (keeping highest similarity).
    Vector + keyword results are then fused with Reciprocal Rank Fusion (RRF).
    Falls back to pure vector with MIN_SIMILARITY filtering when keyword search
    returns nothing.

    If the embedding model fails to load (ImportError, OOM, or any exception),
    falls back to keyword-only search and logs a warning to stderr.
    """
    from esbvaktin.ground_truth.operations import embed_text, keyword_search

    results: dict[str, SearchResult] = {}
    _embedding_failed = False

    # Filtered search if category matches a known topic
    topic_filter = claim.category if claim.category in KNOWN_TOPICS else None
    try:
        # Embed the claim once and reuse for both vector searches (cost-07). When
        # the caller batched the article up front, the vector is passed in and we
        # skip re-embedding entirely. Done inside the try so a model-load failure
        # falls through to the keyword-only path below.
        if embedding is None:
            embedding = embed_text(claim.claim_text)
        if topic_filter:
            filtered = search_evidence(
                query=claim.claim_text,
                topic_filter=topic_filter,
                top_k=top_k,
                conn=conn,
                embedding=embedding,
            )
            for r in filtered:
                results[r.evidence_id] = r

        # Unfiltered search for cross-topic evidence
        unfiltered = search_evidence(
            query=claim.claim_text,
            top_k=top_k,
            conn=conn,
            embedding=embedding,
        )
        for r in unfiltered:
            if r.evidence_id not in results:
                results[r.evidence_id] = r
    except Exception as exc:
        print(
            f"WARNING: Embedding model unavailable, falling back to keyword-only: {exc}",
            file=sys.stderr,
        )
        _embedding_failed = True

    # Sort merged vector results by similarity (input for RRF)
    vector_merged = sorted(
        results.values(),
        key=lambda r: r.similarity,
        reverse=True,
    )

    # Keyword search
    keyword_results = keyword_search(
        query=claim.claim_text,
        topic_filter=topic_filter,
        top_k=20,
        conn=conn,
    )

    if keyword_results or _embedding_failed:
        # RRF fusion — no MIN_SIMILARITY floor (keyword hit already signals relevance)
        rrf_results = _rrf_merge(list(vector_merged), keyword_results)
        final_results = []
        keyword_rank = 0
        for r, rrf_score in rrf_results[:MAX_EVIDENCE_PER_CLAIM]:
            if r.similarity > 0:
                # Came from vector search — preserve original similarity
                final_results.append(r)
            else:
                # Keyword-only hit: assign rank-based similarity (0-based position
                # among keyword-only hits in this merged list). rank 0 → 0.90,
                # rank 1 → 0.86, rank 5 → 0.70, rank 10 → 0.50.
                final_results.append(
                    SearchResult(
                        evidence_id=r.evidence_id,
                        domain=r.domain,
                        topic=r.topic,
                        subtopic=r.subtopic,
                        statement=r.statement,
                        source_name=r.source_name,
                        source_url=r.source_url,
                        source_date=r.source_date,
                        source_type=r.source_type,
                        confidence=r.confidence,
                        caveats=r.caveats,
                        statement_is=r.statement_is,
                        similarity=max(0.50, 0.90 - (keyword_rank * 0.04)),
                    )
                )
                keyword_rank += 1
        ordered_results = _reorder_primacy_recency(final_results)
    else:
        # No keyword hits — fall back to pure vector (original behaviour)
        sorted_results = sorted(
            (r for r in results.values() if r.similarity >= MIN_SIMILARITY),
            key=lambda r: r.similarity,
            reverse=True,
        )[:MAX_EVIDENCE_PER_CLAIM]
        ordered_results = _reorder_primacy_recency(sorted_results)

    return ClaimWithEvidence(
        claim=claim,
        evidence=[_search_result_to_match(r) for r in ordered_results],
    )


def retrieve_evidence_for_claims(
    claims: list[Claim],
    top_k: int = 5,
    use_claim_bank: bool = True,
    conn=None,
) -> tuple[
    list[ClaimWithEvidence],
    dict[int, ClaimBankMatch],
    list[ClaimAssessment],
    list[ClaimAssessment],
]:
    """Retrieve evidence for multiple claims.

    If use_claim_bank is True, checks the claim bank first. Returns a tuple of:
    - claims_with_evidence: non-hearsay claims sent to the Opus assessor (EXCLUDES
      cost-03 short-circuited claims).
    - bank_matches: dict mapping each Opus-bound claim's 0-based index in
      claims_with_evidence → its (fuzzy) ClaimBankMatch, shown as "Fyrra mat" context.
    - hearsay_assessments: pre-built UNVERIFIABLE assessments for hearsay claims
      (no evidence retrieval performed).
    - bank_assessments: pre-built assessments reusing a strong, fresh, unflagged
      factual bank verdict (cost-03) — no evidence retrieval and no Opus call.

    Both pre-built lists are persisted and merged by assemble_report; if there are no
    matches the dict/lists are empty.
    """
    # Short-circuit hearsay claims — no evidence retrieval or assessment needed
    hearsay_assessments: list[ClaimAssessment] = []
    non_hearsay_claims: list[Claim] = []
    for claim in claims:
        if claim.epistemic_type == EpistemicType.HEARSAY:
            hearsay_assessments.append(
                ClaimAssessment(
                    claim=claim,
                    verdict=Verdict.UNVERIFIABLE,
                    explanation=(
                        "Fullyrðingin byggir á ónafngreindum heimildum"
                        " sem ekki er hægt að staðfesta."
                    ),
                    supporting_evidence=[],
                    contradicting_evidence=[],
                    missing_context=None,
                    confidence=0.0,
                )
            )
        else:
            non_hearsay_claims.append(claim)

    claims_with_evidence: list[ClaimWithEvidence] = []
    bank_matches: dict[int, ClaimBankMatch] = {}

    # Embed every claim for the article in one batched bge-m3 pass (cost-07/
    # latency-02), then thread each vector through bank lookup + evidence search so
    # no claim is embedded more than once. On model failure, fall back to None and
    # let each retrieval re-embed (and degrade to keyword-only) on its own.
    from esbvaktin.ground_truth.operations import embed_texts

    claim_embeddings: list[list[float] | None]
    if non_hearsay_claims:
        try:
            claim_embeddings = list(embed_texts([c.claim_text for c in non_hearsay_claims]))
        except Exception as exc:
            print(
                f"WARNING: batch embedding unavailable, falling back per-claim: {exc}",
                file=sys.stderr,
            )
            claim_embeddings = [None] * len(non_hearsay_claims)
    else:
        claim_embeddings = []

    bank_assessments: list[ClaimAssessment] = []
    for i, claim in enumerate(non_hearsay_claims):
        embedding = claim_embeddings[i]
        bank_match = (
            check_claim_bank(claim, conn=conn, embedding=embedding) if use_claim_bank else None
        )

        # cost-03: a strong, fresh, unflagged factual verdict is reused directly —
        # skip BOTH evidence retrieval and the Opus assessor. The pre-built assessment
        # carries the stored verdict + evidence IDs, so the report stays evidence-rich.
        if bank_match is not None and is_reusable_bank_match(bank_match):
            logger.info(
                "Reusing fresh bank verdict (%.3f) for claim %d: %s — skipping Opus",
                bank_match.similarity,
                i,
                bank_match.claim_slug,
            )
            bank_assessments.append(bank_match_to_assessment(claim, bank_match))
            continue

        # Opus-bound: retrieve evidence (needed for the report) and record any fuzzy
        # match as "Fyrra mat" context — keyed by the claim's index in the Opus-bound
        # list so prepare_assessment_context's bank_matches[i-1] stays aligned after skips.
        cwe = retrieve_evidence_for_claim(claim, top_k=top_k, conn=conn, embedding=embedding)
        if bank_match is not None:
            bank_matches[len(claims_with_evidence)] = bank_match
        claims_with_evidence.append(cwe)

    return claims_with_evidence, bank_matches, hearsay_assessments, bank_assessments
