"""Output parsers for Claude Code subagent results.

Reads subagent output files (markdown with JSON code blocks),
extracts the JSON, and validates it into Pydantic models.
"""

import json
import re
from pathlib import Path

from .models import (
    Claim,
    ClaimAssessment,
    OmissionAnalysis,
)


def _extract_json(text: str) -> str:
    """Extract JSON from a markdown code block, or treat the whole text as JSON."""
    # Try to find a ```json ... ``` block
    match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fall back to treating the entire text as JSON
    return text.strip()


def parse_claims(output_path: Path) -> list[Claim]:
    """Parse claim extraction output into Claim objects."""
    text = output_path.read_text(encoding="utf-8")
    raw = json.loads(_extract_json(text))
    return [Claim.model_validate(item) for item in raw]


def parse_assessments(output_path: Path) -> list[ClaimAssessment]:
    """Parse claim assessment output into ClaimAssessment objects."""
    text = output_path.read_text(encoding="utf-8")
    raw = json.loads(_extract_json(text))
    return [ClaimAssessment.model_validate(item) for item in raw]


def parse_omissions(output_path: Path) -> OmissionAnalysis:
    """Parse omission analysis output into OmissionAnalysis."""
    text = output_path.read_text(encoding="utf-8")
    raw = json.loads(_extract_json(text))
    return OmissionAnalysis.model_validate(raw)


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
