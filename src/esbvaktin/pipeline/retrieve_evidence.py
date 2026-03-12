"""Evidence retrieval for extracted claims.

Pure Python — no LLM needed. Queries the Ground Truth Database
via semantic search for each claim. Optionally checks the Claim Bank
first for pre-processed assessments.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from esbvaktin.ground_truth import SearchResult, search_evidence

from .models import KNOWN_TOPICS, Claim, ClaimWithEvidence, EvidenceMatch

if TYPE_CHECKING:
    from esbvaktin.claim_bank.models import ClaimBankMatch

logger = logging.getLogger(__name__)

# Similarity thresholds for claim bank matching
BANK_EXACT_THRESHOLD = 0.85  # Reuse verdict directly (cache hit)
BANK_FUZZY_THRESHOLD = 0.70  # Show as context to assessment subagent


def _search_result_to_match(result: SearchResult) -> EvidenceMatch:
    return EvidenceMatch(
        evidence_id=result.evidence_id,
        statement=result.statement,
        similarity=result.similarity,
        source_name=result.source_name,
        source_url=result.source_url,
        caveats=result.caveats,
        statement_is=result.statement_is,
    )


def check_claim_bank(
    claim: Claim,
    conn=None,
) -> ClaimBankMatch | None:
    """Check if a similar claim exists in the claim bank.

    Returns the best match above BANK_FUZZY_THRESHOLD, or None.
    Caller decides whether to treat as cache hit (>= BANK_EXACT_THRESHOLD
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
    """Retrieve evidence for a single claim.

    Runs two searches:
    1. Filtered by topic (if the claim's category matches a known topic)
    2. Unfiltered (catches cross-topic evidence)

    Results are merged, deduplicated, and sorted by similarity.
    """
    results: dict[str, SearchResult] = {}

    # Filtered search if category matches a known topic
    topic_filter = claim.category if claim.category in KNOWN_TOPICS else None
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

    # Sort by similarity, take top_k
    sorted_results = sorted(results.values(), key=lambda r: r.similarity, reverse=True)[:top_k]

    return ClaimWithEvidence(
        claim=claim,
        evidence=[_search_result_to_match(r) for r in sorted_results],
    )


def retrieve_evidence_for_claims(
    claims: list[Claim],
    top_k: int = 5,
    use_claim_bank: bool = True,
    conn=None,
) -> tuple[list[ClaimWithEvidence], dict[int, ClaimBankMatch]]:
    """Retrieve evidence for multiple claims.

    If use_claim_bank is True, checks the claim bank first. Returns
    a tuple of:
    - claims_with_evidence: list for all claims (including bank hits)
    - bank_matches: dict mapping claim index → ClaimBankMatch for claims
      that had bank matches (for use in assessment context)

    For backward compatibility, if no bank matches are found, the second
    element will be an empty dict.
    """
    claims_with_evidence: list[ClaimWithEvidence] = []
    bank_matches: dict[int, ClaimBankMatch] = {}

    for i, claim in enumerate(claims):
        # Check claim bank first
        if use_claim_bank:
            bank_match = check_claim_bank(claim, conn=conn)
            if bank_match is not None:
                bank_matches[i] = bank_match
                # If exact match and fresh, we still retrieve evidence
                # (needed for report context) but mark for potential cache hit
                if (
                    bank_match.similarity >= BANK_EXACT_THRESHOLD
                    and bank_match.is_fresh
                ):
                    logger.info(
                        "Cache hit (%.3f, fresh) for claim %d: %s",
                        bank_match.similarity,
                        i,
                        bank_match.claim_slug,
                    )

        # Always retrieve evidence (needed for report even if bank hit)
        cwe = retrieve_evidence_for_claim(claim, top_k=top_k, conn=conn)
        claims_with_evidence.append(cwe)

    return claims_with_evidence, bank_matches
