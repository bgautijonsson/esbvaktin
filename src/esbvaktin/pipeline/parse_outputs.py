"""Output parsers for Claude Code subagent results.

Reads subagent output files (markdown with JSON code blocks),
extracts the JSON, and validates it into Pydantic models.
"""

import json
import logging
import re
from pathlib import Path

from esbvaktin.utils.json_utils import (  # noqa: E402
    extract_json as _extract_json,
)
from esbvaktin.utils.json_utils import (
    sanitise_icelandic_quotes,
)

from .models import (
    ArticleEntities,
    Claim,
    ClaimAssessment,
    EpistemicType,
    FramingAssessment,
    OmissionAnalysis,
)

# Re-export for backward compatibility
sanitise_icelandic_quotes = sanitise_icelandic_quotes


def parse_claims(output_path: Path) -> list[Claim]:
    """Parse claim extraction output into Claim objects."""
    text = output_path.read_text(encoding="utf-8")
    raw = json.loads(_extract_json(text))
    return [Claim.model_validate(item) for item in raw]


def _normalise_assessment(item: dict) -> dict:
    """Normalise flat subagent output into nested ClaimAssessment format.

    Subagents sometimes write claim fields at the top level instead of
    nesting them under a 'claim' key. They may also use different field
    names (e.g. 'evidence_ids' instead of 'supporting_evidence').
    """
    item = dict(item)  # shallow copy (also lets us safely set defaults on nested items)
    if "claim" not in item and "claim_text" in item:
        # Reconstruct nested claim from flat fields
        claim_dict = {
            "claim_text": item.pop("claim_text"),
            "original_quote": item.pop("quote", item.pop("original_quote", "")),
            "category": item.pop("category", "other"),
            "claim_type": item.pop("claim_type", "opinion"),
            "confidence": item.get("confidence", 0.5),
        }
        # Preserve speaker_name for panel show / transcript claims
        if "speaker_name" in item:
            claim_dict["speaker_name"] = item.pop("speaker_name")
        # Preserve epistemic_type for epistemic-aware assessment
        if "epistemic_type" in item:
            claim_dict["epistemic_type"] = item.pop("epistemic_type")
        item["claim"] = claim_dict
        # Map alternative field names
        if "evidence_ids" in item and "supporting_evidence" not in item:
            item["supporting_evidence"] = item.pop("evidence_ids")
        if "caveats" in item and "missing_context" not in item:
            item["missing_context"] = item.pop("caveats")
        # Remove extra fields not in the model
        item.pop("context", None)
        item.pop("quote", None)
    # ClaimAssessment.confidence is required, but the assessor agent sometimes omits the
    # top-level field (documented ~1-in-N occurrence). Inherit the claim's confidence if
    # present, else default to 0.7 — so a missing field no longer aborts the whole article.
    if "confidence" not in item:
        claim_conf = item.get("claim", {}).get("confidence")
        if claim_conf is not None:
            item["confidence"] = claim_conf
        else:
            item["confidence"] = 0.7
            logging.getLogger(__name__).warning(
                "Assessment missing top-level confidence; defaulted to 0.7"
            )
    return item


def parse_assessments(output_path: Path) -> list[ClaimAssessment]:
    """Parse claim assessment output into ClaimAssessment objects."""
    text = output_path.read_text(encoding="utf-8")
    raw = json.loads(_extract_json(text))
    normalised = [_normalise_assessment(item) for item in raw]
    assessments = [ClaimAssessment.model_validate(item) for item in normalised]
    # Enforce the 0.8 confidence ceiling for prediction/counterfactual claims on the article
    # path too (reassess_claims.py already clamps; this closes the single-article/batch gap).
    return clamp_epistemic_confidence(assessments)


_EPISTEMIC_CONFIDENCE_CEILING = 0.8
_CLAMPED_TYPES = {EpistemicType.PREDICTION, EpistemicType.COUNTERFACTUAL}


def clamp_epistemic_confidence(
    assessments: list[ClaimAssessment],
) -> list[ClaimAssessment]:
    """Clamp confidence for prediction/counterfactual claims to 0.8 ceiling.

    Predictions and counterfactuals are inherently uncertain — even well-
    supported reasoning cannot be as confident as verified facts.
    """
    result = []
    for a in assessments:
        if a.claim.epistemic_type in _CLAMPED_TYPES:
            clamped_claim = a.claim.model_copy(
                update={"confidence": min(a.claim.confidence, _EPISTEMIC_CONFIDENCE_CEILING)}
            )
            clamped = a.model_copy(
                update={
                    "claim": clamped_claim,
                    "confidence": min(a.confidence, _EPISTEMIC_CONFIDENCE_CEILING),
                }
            )
            result.append(clamped)
        else:
            result.append(a)
    return result


_FRAMING_ALIASES = {
    "strongly_anti": "strongly_anti_eu",
    "strongly_pro": "strongly_pro_eu",
    "leans_anti": "leans_anti_eu",
    "leans_pro": "leans_pro_eu",
}


def _normalise_omissions(raw: dict) -> dict:
    """Normalise subagent omission output to match OmissionAnalysis schema."""
    raw = dict(raw)
    # Map framing aliases
    framing = raw.get("framing_assessment", "")
    raw["framing_assessment"] = _FRAMING_ALIASES.get(framing, framing)
    # Normalise omission field names
    for omission in raw.get("omissions", []):
        if "evidence_ids" in omission and "relevant_evidence" not in omission:
            omission["relevant_evidence"] = omission.pop("evidence_ids")
        omission.pop("impact", None)
    return raw


def parse_omissions(output_path: Path) -> OmissionAnalysis:
    """Parse omission analysis output into OmissionAnalysis."""
    text = output_path.read_text(encoding="utf-8")
    raw = json.loads(_extract_json(text))
    return OmissionAnalysis.model_validate(_normalise_omissions(raw))


def parse_omissions_safe(output_path: Path) -> OmissionAnalysis:
    """Parse omission analysis output, returning a default if the file is missing.

    Use this instead of ``parse_omissions()`` when the omissions agent may
    have silently failed (e.g. context too large for the agent tier).
    """
    if not output_path.exists():
        import logging

        logging.getLogger(__name__).warning(
            "Omissions file missing (%s) — using default (neutral_but_incomplete, 0.0)",
            output_path,
        )
        return OmissionAnalysis(
            omissions=[],
            framing_assessment=FramingAssessment.NEUTRAL_BUT_INCOMPLETE,
            overall_completeness=0.0,
        )
    return parse_omissions(output_path)


def parse_assessments_safe(output_path: Path) -> list[ClaimAssessment]:
    """Parse claim assessment output, returning an empty list if the file is missing.

    Use this instead of ``parse_assessments()`` when the assessment agent may
    have silently failed or timed out.
    """
    if not output_path.exists():
        import logging

        logging.getLogger(__name__).warning(
            "Assessments file missing (%s) — returning empty list",
            output_path,
        )
        return []
    return parse_assessments(output_path)


_HEARSAY_ASSESSMENTS_FILE = "_hearsay_assessments.json"


def persist_hearsay_assessments(
    work_dir: Path, hearsay_assessments: list[ClaimAssessment]
) -> Path | None:
    """Write pre-built hearsay assessments to ``_hearsay_assessments.json``.

    Hearsay claims are short-circuited to UNVERIFIABLE during evidence retrieval
    and never reach the assessor, so they are absent from ``_assessments.json``
    (which the assessor overwrites). Persisting them in a separate file lets
    ``assemble_report`` merge them back — honouring the documented contract that
    hearsay is published with an amber warning rather than silently dropped.

    Returns the path written, or ``None`` if there were no hearsay assessments.
    """
    if not hearsay_assessments:
        return None
    path = work_dir / _HEARSAY_ASSESSMENTS_FILE
    payload = [a.model_dump(mode="json") for a in hearsay_assessments]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_hearsay_assessments(work_dir: Path) -> list[ClaimAssessment]:
    """Load hearsay assessments persisted during evidence retrieval.

    Returns an empty list when no ``_hearsay_assessments.json`` is present (the
    common case — most articles contain no hearsay claims).
    """
    path = work_dir / _HEARSAY_ASSESSMENTS_FILE
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    raw = json.loads(_extract_json(text))
    normalised = [_normalise_assessment(item) for item in raw]
    return [ClaimAssessment.model_validate(item) for item in normalised]


def parse_entities(output_path: Path) -> ArticleEntities:
    """Parse entity extraction output into ArticleEntities."""
    text = output_path.read_text(encoding="utf-8")
    raw = json.loads(_extract_json(text))
    return ArticleEntities.model_validate(raw)


def parse_translation(output_path: Path) -> str:
    """Parse translation output — returns the raw markdown text.

    The translation subagent writes plain markdown, not JSON.
    Strips any wrapping code blocks if present.
    """
    text = output_path.read_text(encoding="utf-8")
    # If wrapped in a code block, unwrap it
    match = re.search(r"```(?:markdown)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()
