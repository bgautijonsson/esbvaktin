"""Confidence adjustment for canonical claims based on sighting agreement.

Shared logic used by pipeline, speech, and batch article sighting registration.

Graduated decay: penalty scales with verdict distance, not a flat rate.
Large disagreements (e.g., supported → misleading) decay more than small ones
(e.g., supported → partially_supported).
"""

from __future__ import annotations

# Confidence never drops below this floor, even with many disagreeing sightings.
# Prevents collapse to near-zero on high-volume claims (0.8 × 0.95^20 ≈ 0.29).
MIN_CONFIDENCE_FLOOR = 0.15

# Upper cap — confidence never exceeds this via agreement boosts.
MAX_CONFIDENCE_CAP = 0.95

# Base multiplicative factors
BASE_DECAY_FACTOR = 0.95  # 5% decay per "step" of disagreement
BOOST_FACTOR = 1.02  # 2% boost on agreement

# Verdict ordinal positions for distance calculation
_VERDICT_ORDER = {
    "supported": 0,
    "partially_supported": 1,
    "unsupported": 2,
    "misleading": 3,
}

# Threshold: if confidence drops below this after decay, flag for reassessment
REASSESSMENT_THRESHOLD = 0.50


def verdict_distance(v1: str, v2: str) -> int:
    """Return the ordinal distance between two verdicts (0-3).

    Unverifiable is treated as distance 1 from everything (mild uncertainty).
    """
    if v1 == v2:
        return 0
    if v1 == "unverifiable" or v2 == "unverifiable":
        return 1
    pos1 = _VERDICT_ORDER.get(v1)
    pos2 = _VERDICT_ORDER.get(v2)
    if pos1 is None or pos2 is None:
        return 1  # unknown verdict → minimal decay
    return abs(pos1 - pos2)


def adjust_confidence(
    conn,
    claim_id: int,
    current_confidence: float,
    canonical_verdict: str,
    sighting_verdict: str,
) -> None:
    """Decay or boost canonical claim confidence based on verdict agreement.

    Graduated decay: penalty = BASE_DECAY_FACTOR ^ distance.
      - Distance 0 (agree): boost by 2%, capped at 0.95
      - Distance 1 (e.g., supported ↔ partially_supported): 5% decay
      - Distance 2 (e.g., supported ↔ unsupported): ~10% decay
      - Distance 3 (e.g., supported ↔ misleading): ~14% decay

    Sets needs_reassessment=TRUE when confidence crosses below REASSESSMENT_THRESHOLD.
    """
    dist = verdict_distance(canonical_verdict, sighting_verdict)

    if dist == 0:
        # Agreement — small boost
        if current_confidence >= MAX_CONFIDENCE_CAP:
            return
        new_confidence = min(current_confidence * BOOST_FACTOR, MAX_CONFIDENCE_CAP)
        conn.execute(
            "UPDATE claims SET confidence = %(confidence)s WHERE id = %(claim_id)s",
            {"confidence": new_confidence, "claim_id": claim_id},
        )
    else:
        # Disagreement — graduated decay
        decay = BASE_DECAY_FACTOR**dist
        new_confidence = max(current_confidence * decay, MIN_CONFIDENCE_FLOOR)

        # Flag for reassessment if confidence crossed below threshold
        should_flag = (
            current_confidence >= REASSESSMENT_THRESHOLD and new_confidence < REASSESSMENT_THRESHOLD
        )

        if should_flag:
            conn.execute(
                """UPDATE claims
                SET confidence = %(confidence)s,
                    needs_reassessment = TRUE,
                    reassessment_reason = %(reason)s
                WHERE id = %(claim_id)s""",
                {
                    "confidence": new_confidence,
                    "claim_id": claim_id,
                    "reason": f"sighting_drift:{sighting_verdict}",
                },
            )
        else:
            conn.execute(
                "UPDATE claims SET confidence = %(confidence)s WHERE id = %(claim_id)s",
                {"confidence": new_confidence, "claim_id": claim_id},
            )

    conn.commit()
