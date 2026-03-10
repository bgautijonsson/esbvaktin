"""Register claim sightings from speech fact-checking.

After assessment, each claim is matched against the claim bank:
- Match >= 0.70 → insert sighting with speech_verdict + speech_id
- No match + non-unverifiable → insert new CanonicalClaim(published=False)
- No match + unverifiable → discard (speculative statements have no canonical value)
"""

from __future__ import annotations

import logging
from datetime import date

from esbvaktin.claim_bank.models import CanonicalClaim
from esbvaktin.claim_bank.operations import add_claim, generate_slug, search_claims
from esbvaktin.pipeline.models import ClaimAssessment

logger = logging.getLogger(__name__)

SIGHTING_MATCH_THRESHOLD = 0.70


def register_speech_sightings(
    assessments: list[ClaimAssessment],
    speech_id: str,
    source_url: str,
    source_title: str,
    source_date: date | None = None,
    conn=None,
) -> dict[str, int]:
    """Register sightings from assessed speech claims.

    Returns counts: {"matched": N, "new_claims": N, "discarded": N}.
    """
    from esbvaktin.ground_truth.operations import get_connection

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    counts = {"matched": 0, "new_claims": 0, "discarded": 0}

    for assessment in assessments:
        claim_text = assessment.claim.claim_text
        verdict = assessment.verdict.value

        # Try to match against existing claim bank
        matches = search_claims(
            query=claim_text,
            threshold=SIGHTING_MATCH_THRESHOLD,
            top_k=1,
            conn=conn,
        )

        if matches:
            # Match found — insert sighting
            match = matches[0]
            _insert_sighting(
                conn=conn,
                claim_id=match.claim_id,
                source_url=source_url,
                source_title=source_title,
                source_date=source_date,
                source_type="althingi",
                original_text=claim_text,
                similarity=match.similarity,
                speech_verdict=verdict,
                speech_id=speech_id,
            )
            counts["matched"] += 1
            logger.info(
                "Sighting: %.3f match '%s' → claim %s (%s)",
                match.similarity,
                claim_text[:50],
                match.claim_slug,
                verdict,
            )

        elif verdict != "unverifiable":
            # No match, assessable claim → create new unpublished canonical claim
            slug = generate_slug(claim_text[:80])
            new_claim = CanonicalClaim(
                claim_slug=slug,
                canonical_text_is=claim_text,
                category=assessment.claim.category,
                claim_type=assessment.claim.claim_type.value,
                verdict=verdict,
                explanation_is=assessment.explanation,
                missing_context_is=assessment.missing_context,
                supporting_evidence=assessment.supporting_evidence,
                contradicting_evidence=assessment.contradicting_evidence,
                confidence=assessment.confidence,
                published=False,
            )
            try:
                claim_id = add_claim(new_claim, conn=conn)
                # Also insert the initial sighting
                _insert_sighting(
                    conn=conn,
                    claim_id=claim_id,
                    source_url=source_url,
                    source_title=source_title,
                    source_date=source_date,
                    source_type="althingi",
                    original_text=claim_text,
                    similarity=1.0,
                    speech_verdict=verdict,
                    speech_id=speech_id,
                )
                counts["new_claims"] += 1
                logger.info(
                    "New claim: '%s' → %s (%s)",
                    claim_text[:50],
                    slug,
                    verdict,
                )
            except Exception as e:
                logger.warning("Failed to insert claim '%s': %s", slug, e)

        else:
            # Unverifiable + no match → discard
            counts["discarded"] += 1
            logger.debug("Discarded unverifiable: '%s'", claim_text[:50])

    if close:
        conn.close()

    return counts


def _insert_sighting(
    conn,
    claim_id: int,
    source_url: str,
    source_title: str,
    source_date: date | None,
    source_type: str,
    original_text: str,
    similarity: float,
    speech_verdict: str,
    speech_id: str,
) -> None:
    """Insert a claim sighting row."""
    conn.execute(
        """
        INSERT INTO claim_sightings (
            claim_id, source_url, source_title, source_date,
            source_type, original_text, similarity,
            speech_verdict, speech_id
        ) VALUES (
            %(claim_id)s, %(source_url)s, %(source_title)s, %(source_date)s,
            %(source_type)s, %(original_text)s, %(similarity)s,
            %(speech_verdict)s, %(speech_id)s
        ) ON CONFLICT (claim_id, source_url) DO UPDATE SET
            speech_verdict = EXCLUDED.speech_verdict,
            similarity = EXCLUDED.similarity,
            original_text = EXCLUDED.original_text
        """,
        {
            "claim_id": claim_id,
            "source_url": source_url,
            "source_title": source_title,
            "source_date": source_date,
            "source_type": source_type,
            "original_text": original_text,
            "similarity": similarity,
            "speech_verdict": speech_verdict,
            "speech_id": speech_id,
        },
    )
    conn.commit()
