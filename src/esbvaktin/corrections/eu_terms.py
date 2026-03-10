"""EU terminology consistency checker for ESBvaktin.

Scans Icelandic text for:
1. English EU terms that should be in Icelandic
2. Inconsistent Icelandic terms (mixing variants)
3. Missing hyphenation in compound abbreviations
"""

import re
from pathlib import Path

# English → Icelandic term mappings (subset of most common errors)
_ENGLISH_TO_ICELANDIC = {
    "Common Agricultural Policy": "sameiginleg landbúnaðarstefna",
    "Common Fisheries Policy": "sameiginleg sjávarútvegsstefna",
    "European Commission": "Framkvæmdastjórn ESB",
    "European Parliament": "Evrópuþingið",
    "Single Market": "innri markaðurinn",
    "single market": "innri markaðurinn",
    "European Council": "Leiðtogaráð ESB",
    "Council of the EU": "Ráðherraráð ESB",
    "structural funds": "byggðasjóðir",
    "Structural Funds": "byggðasjóðir",
    "acquis communautaire": "regluverkið",
    "opt-out": "undanþága",
    "derogation": "undanþága",
    "transitional period": "aðlögunartímabil",
}

# Inconsistent Icelandic variant pairs (first is preferred)
_INCONSISTENT_PAIRS = [
    ("aðildarviðræður", "inngöngusamningar"),
    ("aðildarviðræður", "inngöngusamningaviðræður"),
    ("ESB-aðild", "ESB aðild"),
    ("EES-samningurinn", "EES samningurinn"),
    ("EES-samningurinn", "EEA-samningurinn"),
    ("Evrópusambandið", "Evrópubandalagið"),
]

# Missing hyphen patterns
_HYPHEN_PATTERNS = [
    (r"\bESB\s+aðild", "ESB-aðild (bandstrik vantar)"),
    (r"\bEES\s+samning", "EES-samningurinn (bandstrik vantar)"),
    (r"\bNATO\s+aðil", "NATO-aðili (bandstrik vantar)"),
    (r"\bEFTA\s+dómstól", "EFTA-dómstóllinn (bandstrik vantar)"),
    (r"\bETS\s+kerf", "ETS-kerfið (bandstrik vantar)"),
    (r"\bSchengen\s+svæð", "Schengen-svæðið (bandstrik vantar)"),
]


def check_eu_terms(text: str) -> list[dict]:
    """Scan Icelandic text for EU terminology issues.

    Returns a list of warnings with context.
    """
    warnings = []
    lines = text.split("\n")

    for line_num, line in enumerate(lines, 1):
        # Check for English terms in Icelandic text
        for eng_term, ice_term in _ENGLISH_TO_ICELANDIC.items():
            if eng_term in line:
                warnings.append(
                    {
                        "line": line_num,
                        "type": "english_term",
                        "found": eng_term,
                        "suggestion": ice_term,
                        "context": line.strip()[:100],
                    }
                )

        # Check for missing hyphens
        for pattern, description in _HYPHEN_PATTERNS:
            if re.search(pattern, line):
                warnings.append(
                    {
                        "line": line_num,
                        "type": "missing_hyphen",
                        "found": re.search(pattern, line).group(),
                        "suggestion": description,
                        "context": line.strip()[:100],
                    }
                )

    # Check for inconsistent variants across the whole text
    for preferred, variant in _INCONSISTENT_PAIRS:
        has_preferred = preferred.lower() in text.lower()
        has_variant = variant.lower() in text.lower()
        if has_preferred and has_variant:
            warnings.append(
                {
                    "line": 0,  # Document-level warning
                    "type": "inconsistent",
                    "found": f"Both '{preferred}' and '{variant}' used",
                    "suggestion": f"Prefer '{preferred}' consistently",
                    "context": "",
                }
            )

    return warnings


def format_eu_term_results(warnings: list[dict], filename: str) -> int:
    """Print EU term check results. Returns count of warnings."""
    if not warnings:
        print(f"  {filename}: EU terminology consistent")
        return 0

    for w in warnings:
        type_label = {
            "english_term": "EN TERM",
            "missing_hyphen": "HYPHEN",
            "inconsistent": "INCONSISTENT",
        }.get(w["type"], w["type"])

        if w["line"] > 0:
            print(f'  L{w["line"]:3d} [{type_label}] "{w["found"]}"')
        else:
            print(f"  [{type_label}] {w['found']}")
        print(f"        → {w['suggestion']}")

    return len(warnings)
