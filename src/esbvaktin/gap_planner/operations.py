"""Gap identification and classification logic.

Analyses assessment outputs to identify unverifiable claims,
classify the type of evidence gap, and prepare context for
the research-planning subagent.
"""

from __future__ import annotations

import re
from collections import Counter

from ..pipeline.models import AnalysisReport, ClaimAssessment, Verdict
from .models import EvidenceGap, GapCategory


# ── Gap classification heuristics ─────────────────────────────────────

# Patterns that indicate the gap type (checked against explanation + missing_context)
_PATTERN_MAP: list[tuple[GapCategory, list[str]]] = [
    (GapCategory.RECENT_EVENT, [
        r"lagafrumvarp", r"frumvarp", r"bill\b", r"recent\b", r"2026",
        r"announced", r"introduced", r"voted\b", r"þingmál",
    ]),
    (GapCategory.MISSING_DATA, [
        r"no (?:data|evidence|statistics)", r"engin gögn", r"engar heimildir",
        r"not available", r"ekki til", r"no specific estimate",
        r"tölur vantar", r"no entry", r"database does not",
    ]),
    (GapCategory.CONTRADICTORY, [
        r"conflicting", r"contradictory", r"inconsistent",
        r"stangast á", r"misvísandi",
    ]),
    (GapCategory.SPECULATIVE, [
        r"would depend", r"speculative", r"predicted", r"could be",
        r"myndi ráðast", r"spágildi", r"hypothetical",
        r"if .+ were to", r"negotiations",
    ]),
    (GapCategory.SOURCE_NEEDED, [
        r"may .+ be accurate", r"cannot be verified",
        r"ekki hægt að sannreyna", r"according to .+ but",
        r"likely true", r"gæti verið rétt",
    ]),
]


def categorise_gap(explanation: str, missing_context: str | None = None) -> GapCategory:
    """Classify why a claim is unverifiable using text heuristics.

    Checks the explanation and missing_context against known patterns.
    Returns the first matching category, defaulting to SOURCE_NEEDED.
    """
    text = (explanation + " " + (missing_context or "")).lower()
    for category, patterns in _PATTERN_MAP:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return category
    return GapCategory.SOURCE_NEEDED


# ── Gap identification ────────────────────────────────────────────────


def identify_gaps(report: AnalysisReport) -> list[EvidenceGap]:
    """Extract evidence gaps from an analysis report.

    Filters for unverifiable claims and classifies each gap.
    """
    gaps: list[EvidenceGap] = []

    for i, ca in enumerate(report.claims):
        if ca.verdict != Verdict.UNVERIFIABLE:
            continue

        gap_category = categorise_gap(ca.explanation, ca.missing_context)

        gap = EvidenceGap(
            claim_index=i,
            claim_text=ca.claim.claim_text,
            original_quote=ca.claim.original_quote,
            category=ca.claim.category,
            explanation=ca.explanation,
            missing_context=ca.missing_context,
            gap_category=gap_category,
            evidence_ids_consulted=ca.supporting_evidence + ca.contradicting_evidence,
        )
        gaps.append(gap)

    return gaps


def summarise_gaps(gaps: list[EvidenceGap]) -> dict[str, int]:
    """Count gaps by category."""
    return dict(Counter(g.gap_category.value for g in gaps))
