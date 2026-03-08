"""Evidence retrieval for extracted claims.

Pure Python — no LLM needed. Queries the Ground Truth Database
via semantic search for each claim.
"""

from esbvaktin.ground_truth import SearchResult, search_evidence

from .models import KNOWN_TOPICS, Claim, ClaimWithEvidence, EvidenceMatch


def _search_result_to_match(result: SearchResult) -> EvidenceMatch:
    return EvidenceMatch(
        evidence_id=result.evidence_id,
        statement=result.statement,
        similarity=result.similarity,
        source_name=result.source_name,
        caveats=result.caveats,
    )


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
    conn=None,
) -> list[ClaimWithEvidence]:
    """Retrieve evidence for multiple claims."""
    return [retrieve_evidence_for_claim(c, top_k=top_k, conn=conn) for c in claims]
