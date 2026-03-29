"""Confidence adjustment for canonical claims based on sighting agreement.

Shared logic used by pipeline, speech, and batch article sighting registration.
"""

from __future__ import annotations

# Confidence never drops below this floor, even with many disagreeing sightings.
# Prevents collapse to near-zero on high-volume claims (0.8 × 0.95^20 ≈ 0.29).
MIN_CONFIDENCE_FLOOR = 0.15

# Upper cap — confidence never exceeds this via agreement boosts.
MAX_CONFIDENCE_CAP = 0.95

# Multiplicative factors
DECAY_FACTOR = 0.95  # 5% decay on disagreement
BOOST_FACTOR = 1.02  # 2% boost on agreement


def adjust_confidence(
    conn,
    claim_id: int,
    current_confidence: float,
    canonical_verdict: str,
    sighting_verdict: str,
) -> None:
    """Decay or boost canonical claim confidence based on verdict agreement.

    Decay: sighting verdict disagrees → multiply by 0.95 (5% decay).
    Boost: sighting verdict agrees → multiply by 1.02, capped at 0.95 (2% boost).
    Floor: confidence never drops below MIN_CONFIDENCE_FLOOR (0.15).
    Disagreement intentionally weighs more than agreement.
    """
    if sighting_verdict != canonical_verdict:
        new_confidence = max(current_confidence * DECAY_FACTOR, MIN_CONFIDENCE_FLOOR)
    elif current_confidence < MAX_CONFIDENCE_CAP:
        new_confidence = min(current_confidence * BOOST_FACTOR, MAX_CONFIDENCE_CAP)
    else:
        return  # Already at cap, no update needed

    conn.execute(
        "UPDATE claims SET confidence = %(confidence)s WHERE id = %(claim_id)s",
        {"confidence": new_confidence, "claim_id": claim_id},
    )
    conn.commit()
