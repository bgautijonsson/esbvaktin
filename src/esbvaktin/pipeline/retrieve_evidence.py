"""Evidence retrieval for extracted claims.

Pure Python — no LLM needed. Queries the Ground Truth Database
via semantic search for each claim. Optionally checks the Claim Bank
first for pre-processed assessments.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

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
    """
    scores: dict[str, float] = {}
    result_map: dict[str, SearchResult] = {}

    for rank, r in enumerate(vector_results, 1):
        scores[r.evidence_id] = scores.get(r.evidence_id, 0) + vector_weight / (RRF_K + rank)
        result_map[r.evidence_id] = r

    for rank, r in enumerate(keyword_results, 1):
        scores[r.evidence_id] = scores.get(r.evidence_id, 0) + keyword_weight / (RRF_K + rank)
        if r.evidence_id not in result_map:
            result_map[r.evidence_id] = r

    return sorted(
        [(result_map[eid], score) for eid, score in scores.items()],
        key=lambda x: x[1],
        reverse=True,
    )


def check_claim_bank(
    claim: Claim,
    conn=None,
) -> ClaimBankMatch | None:
    """Check if a similar claim exists in the claim bank.

    Returns the best match above BANK_FUZZY_THRESHOLD, or None.
    Caller decides whether to treat as strong prior (>= BANK_EXACT_THRESHOLD
    and fresh) or just as context.
    """
    try:
        from esbvaktin.claim_bank.operations import search_claims

        matches = search_claims(
            query=claim.claim_text,
            threshold=BANK_FUZZY_THRESHOLD,
            top_k=1,
            conn=conn,
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
    from esbvaktin.ground_truth.operations import keyword_search

    results: dict[str, SearchResult] = {}
    _embedding_failed = False

    # Filtered search if category matches a known topic
    topic_filter = claim.category if claim.category in KNOWN_TOPICS else None
    try:
        if topic_filter:
            filtered = search_evidence(
                query=claim.claim_text,
                topic_filter=topic_filter,
                top_k=top_k,
                conn=conn,
            )
            for r in filtered:
                results[r.evidence_id] = r

        # Unfiltered search for cross-topic evidence
        unfiltered = search_evidence(
            query=claim.claim_text,
            top_k=top_k,
            conn=conn,
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
) -> tuple[list[ClaimWithEvidence], dict[int, ClaimBankMatch], list[ClaimAssessment]]:
    """Retrieve evidence for multiple claims.

    If use_claim_bank is True, checks the claim bank first. Returns
    a tuple of:
    - claims_with_evidence: list for non-hearsay claims (including bank hits)
    - bank_matches: dict mapping claim index → ClaimBankMatch for claims
      that had bank matches (for use in assessment context)
    - hearsay_assessments: pre-built UNVERIFIABLE assessments for hearsay
      claims (no evidence retrieval performed for these)

    For backward compatibility, if no bank matches are found, the second
    element will be an empty dict.
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

    for i, claim in enumerate(non_hearsay_claims):
        # Check claim bank first
        if use_claim_bank:
            bank_match = check_claim_bank(claim, conn=conn)
            if bank_match is not None:
                bank_matches[i] = bank_match
                # If exact match and fresh, we still retrieve evidence
                # (needed for report context) but mark for potential strong prior
                if bank_match.similarity >= BANK_EXACT_THRESHOLD and bank_match.is_fresh:
                    logger.info(
                        "Strong prior (%.3f, fresh) for claim %d: %s",
                        bank_match.similarity,
                        i,
                        bank_match.claim_slug,
                    )

        # Always retrieve evidence (needed for report even if bank hit)
        cwe = retrieve_evidence_for_claim(claim, top_k=top_k, conn=conn)
        claims_with_evidence.append(cwe)

    return claims_with_evidence, bank_matches, hearsay_assessments
