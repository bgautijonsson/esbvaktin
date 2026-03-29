"""Shared JSON utilities for handling Icelandic quote characters.

Icelandic text uses „ (U+201E) and " (U+201C) as quotation marks.
When an LLM writes these inside JSON string values they appear as
unescaped double-quote characters, causing json.loads() to fail.
"""

import json
import re


def sanitise_icelandic_quotes(text: str) -> str:
    """Replace Icelandic/smart quotation marks that break JSON parsing.

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


def extract_json(text: str) -> str:
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
                repaired = repaired[:pos] + '\\"' + repaired[pos + 1 :]
            else:
                break
    return repaired
