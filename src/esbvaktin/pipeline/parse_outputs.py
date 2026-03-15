"""Output parsers for Claude Code subagent results.

Reads subagent output files (markdown with JSON code blocks),
extracts the JSON, and validates it into Pydantic models.
"""

import json
import re
from pathlib import Path

from .models import (
    ArticleEntities,
    Claim,
    ClaimAssessment,
    FramingAssessment,
    OmissionAnalysis,
)


def sanitise_icelandic_quotes(text: str) -> str:
    """Replace Icelandic/smart quotation marks that break JSON parsing.

    Icelandic text uses „ (U+201E) and " (U+201C) as quotation marks.
    When an LLM writes these inside JSON string values they appear as
    unescaped double-quote characters, causing json.loads() to fail.

    The trickiest pattern is „word" where the opening „ is U+201E but
    the closing " is a plain ASCII double-quote — indistinguishable from
    a JSON delimiter.  We handle this by finding „...ASCII-" pairs and
    escaping both ends before falling back to blanket replacement.
    """
    # Phase 1: fix paired „...ASCII " patterns.
    # Find each „ and its matching closing ASCII " within the same line.
    result = list(text)
    i = 0
    while i < len(result):
        ch = result[i]
        if ch == "\u201e":
            # Find the next ASCII " on the same line
            j = i + 1
            while j < len(result) and result[j] != "\n":
                if result[j] == '"':
                    # Check it's not already escaped
                    if j == 0 or result[j - 1] != "\\":
                        result[j] = '\\"'
                    break
                j += 1
            result[i] = '\\"'
        i += 1
    text = "".join(result)

    # Phase 2: blanket-replace any remaining smart quotes
    replacements = {
        "\u201e": '\\"',  # „ — double low-9 quotation mark
        "\u201c": '\\"',  # " — left double quotation mark
        "\u201d": '\\"',  # " — right double quotation mark
        "\u201a": "\\'",  # ‚ — single low-9 quotation mark
        "\u2018": "\\'",  # ' — left single quotation mark
        "\u2019": "\\'",  # ' — right single quotation mark
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def _extract_json(text: str) -> str:
    """Extract JSON from a markdown code block, or treat the whole text as JSON.

    Tries to parse without sanitisation first; only applies Icelandic
    quote sanitisation if the initial parse would fail.
    """
    # Try to find a ```json ... ``` block
    match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    else:
        # Fall back to treating the entire text as JSON
        raw = text.strip()
    # Try parsing as-is first — sanitisation can corrupt valid Unicode quotes
    try:
        json.loads(raw)
        return raw
    except (json.JSONDecodeError, ValueError):
        pass
    # Sanitise smart/Icelandic quotes before parsing
    sanitised = sanitise_icelandic_quotes(raw)

    # Try parsing after sanitisation; if it still fails, attempt
    # iterative repair of unescaped ASCII quotes at error positions.
    try:
        json.loads(sanitised)
        return sanitised
    except json.JSONDecodeError:
        pass

    # Phase 3: iterative positional repair.
    # When an agent writes \"word" the closer is a bare ASCII " that
    # JSONDecodeError points to. Escape it and retry (up to 10 fixes).
    repaired = sanitised
    for _ in range(10):
        try:
            json.loads(repaired)
            return repaired
        except json.JSONDecodeError as e:
            pos = e.pos
            if pos is None or pos >= len(repaired) or repaired[pos] != '"':
                break
            # Check the quote at error position looks like content, not structure:
            # preceded by a word char or punctuation (not a JSON delimiter)
            if pos > 0 and repaired[pos - 1] not in (",", ":", "[", "{", " ", "\n", "\t"):
                repaired = repaired[:pos] + '\\"' + repaired[pos + 1:]
            else:
                break
    return repaired


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
    if "claim" not in item and "claim_text" in item:
        # Reconstruct nested claim from flat fields
        item = dict(item)  # shallow copy
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
        item["claim"] = claim_dict
        # Map alternative field names
        if "evidence_ids" in item and "supporting_evidence" not in item:
            item["supporting_evidence"] = item.pop("evidence_ids")
        if "caveats" in item and "missing_context" not in item:
            item["missing_context"] = item.pop("caveats")
        # Remove extra fields not in the model
        item.pop("context", None)
        item.pop("quote", None)
    return item


def parse_assessments(output_path: Path) -> list[ClaimAssessment]:
    """Parse claim assessment output into ClaimAssessment objects."""
    text = output_path.read_text(encoding="utf-8")
    raw = json.loads(_extract_json(text))
    normalised = [_normalise_assessment(item) for item in raw]
    return [ClaimAssessment.model_validate(item) for item in normalised]


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
