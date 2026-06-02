"""Anthropic-SDK harness with prompt caching for the claim-assessor (cost-01).

Pure helpers (no ``anthropic`` import here — the client is injected) plus a thin
``call_cached`` that drives an injected client. This lets the hot Opus assessor
reuse its ~3k-token invariant prefix across calls via ``cache_control``, which the
Task tool cannot do (each subagent run starts cold). The live measurement and the
pipeline cutover create a real ``anthropic.Anthropic`` client; tests inject a fake.
"""

from __future__ import annotations

from pathlib import Path

# The heading prepare_assessment_context inserts between the invariant instruction
# block (cacheable) and the per-article claims + evidence (variable). See
# prepare_context.py (cost-02).
_CLAIMS_MARKERS = {
    "is": "## Fullyrðingar og heimildir",
    "en": "## Claims and Evidence",
}


def split_assessment_context(md: str, language: str = "is") -> tuple[str, str]:
    """Split an assessment context into (invariant prefix, variable suffix).

    The prefix is the cacheable instruction + Icelandic-quality block; the suffix
    is the per-article claims/evidence/speeches, starting at the claims marker.
    """
    marker = _CLAIMS_MARKERS.get(language, _CLAIMS_MARKERS["is"])
    idx = md.find(marker)
    if idx == -1:
        return "", md
    return md[:idx].rstrip(), md[idx:]


def build_cached_messages(
    system: str,
    prefix: str,
    suffix: str,
    *,
    ttl: str | None = None,
) -> dict:
    """Build the system + messages payload with a cache breakpoint on the prefix.

    A single ``cache_control`` on the invariant prefix block makes the API cache
    everything before it (system + prefix); the variable suffix block follows
    uncached. An empty prefix caches nothing. ``ttl`` (e.g. "1h") opts into the
    extended cache lifetime (requires the extended-cache beta header at call time);
    the default is the 5-minute ephemeral cache.
    """
    cache_control: dict = {"type": "ephemeral"}
    if ttl:
        cache_control["ttl"] = ttl

    content: list[dict] = []
    if prefix:
        content.append({"type": "text", "text": prefix, "cache_control": cache_control})
    content.append({"type": "text", "text": suffix})

    return {"system": system, "messages": [{"role": "user", "content": content}]}


def parse_usage(usage: object) -> dict:
    """Extract the four token counts from an Anthropic usage object (duck-typed).

    Missing or None fields (the SDK omits cache_* when no cache is involved) read
    as 0, so the result is always a complete, summable record.
    """
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
    }


def call_cached(
    client: object,
    *,
    system: str,
    prefix: str,
    suffix: str,
    model: str,
    max_tokens: int = 4096,
    ttl: str | None = None,
) -> tuple[str, dict]:
    """Call an (injected) Anthropic client with the invariant prefix cached.

    Returns (response_text, parsed_usage). The client is injected so this is unit
    testable; production passes a real ``anthropic.Anthropic`` instance.
    """
    payload = build_cached_messages(system, prefix, suffix, ttl=ttl)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=payload["system"],
        messages=payload["messages"],
    )
    text = response.content[0].text
    return text, parse_usage(response.usage)


_DEFAULT_AGENT = Path(__file__).resolve().parents[3] / ".claude" / "agents" / "claim-assessor.md"

_JSON_RESPONSE_OVERRIDE = (
    "\n\n## Útgáfa fyrir beina köllun\n\n"
    "Þú hefur engin verkfæri og enga skrá til að lesa eða skrifa. Fullyrðingarnar og "
    "heimildirnar fylgja hér á eftir. Skilaðu matinu sem flötu JSON-fylki BEINT í svari "
    "þínu — ekkert annað og engan skýringartexta utan fylkisins."
)


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block (``---`` … ``---``) if present."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def assessor_system_prompt(agent_path: Path | None = None) -> str:
    """Build the SDK system prompt for the assessor from its agent definition.

    Loads the claim-assessor agent body (the assessment rules), strips the YAML
    frontmatter, and appends an Icelandic instruction to return the verdicts as a
    flat JSON array in the response — a bare SDK call has no Write tool or file to
    read, so the Task-flow "write _assessments.json" mechanics don't apply.
    """
    path = agent_path or _DEFAULT_AGENT
    body = _strip_frontmatter(path.read_text(encoding="utf-8"))
    return body.rstrip() + _JSON_RESPONSE_OVERRIDE
