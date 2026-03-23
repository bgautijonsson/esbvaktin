"""LLM confusable-word pattern scanner.

Adapted from Þingfréttir with significant additions for the EU domain.
The biggest addition is ASCII transliteration detection — the #1 problem
in ESBvaktin's subagent output. Also adds register patterns and EU
terminology patterns.
"""

import re

# Curated deny-list of word pairs/patterns that LLMs commonly confuse.
# Each entry: (regex_pattern, description, suggestion_or_None)
CONFUSABLE_PATTERNS = [
    # ── ASCII transliteration detection (ESBvaktin's #1 problem) ─────
    # These detect common ASCII-ified Icelandic words in subagent output
    (
        r"\b(?:thjodar|thjodaratkvaed|thjodalif)",
        "ASCII transliteration: 'thjodar...' should use 'þjóðar...' with proper Unicode",
        None,
    ),
    (
        r"\badild(?:ar)?(?:vidraed|samning)",
        "ASCII transliteration: 'adildar...' should use 'aðildar...' with proper Unicode",
        None,
    ),
    (
        r"\bundanth(?:ag|eg)",
        "ASCII transliteration: 'undanth...' should use 'undanþ...' with proper Unicode",
        None,
    ),
    (
        r"\blandbun(?:ad|adar)",
        "ASCII transliteration: 'landbun...' should use 'landbún...' with proper Unicode",
        None,
    ),
    (
        r"\bsjavarutv(?:eg|egs)",
        "ASCII transliteration: 'sjavarutv...' should use 'sjávarútv...' with proper Unicode",
        None,
    ),
    (
        r"\bstadfest(?:a|ir|i)\b",
        "ASCII transliteration: 'stadfest...' should use 'staðfest...' with proper Unicode",
        None,
    ),
    (
        r"\bsamkvaem[td]?\b",
        "ASCII transliteration: 'samkvaem...' should use 'samkvæm...' with proper Unicode",
        None,
    ),
    (
        r"\b(?:ad|af|vid|til)\b(?=\s+[a-z])",
        # Only flag 'ad' when followed by lowercase (to avoid false positives on English 'ad')
        None,  # Too many false positives — skip this one, rely on Unicode paragraph check
        None,
    ),
    (
        r"\btimaaetlun\b",
        "ASCII transliteration: 'timaaetlun' should be 'tímaáætlun'",
        "tímaáætlun",
    ),
    (
        r"\blogsogu\b",
        "ASCII transliteration: 'logsagu' → 'lögsögu' (or 'lögsaga')",
        "lögsögu",
    ),
    (
        r"\bfullyrding(?:ar|ina|una|in)?\b",
        "ASCII transliteration: 'fullyrding...' → 'fullyrðing...'",
        None,
    ),
    # ── Universal confusable patterns (from Þingfréttir) ────────────
    # bíða (wait) ≠ bjóða (offer)
    (
        r"\bbíður\s+upp\s+á\b",
        'bíða (wait) ≠ bjóða (offer): "bíður upp á" should be "býður upp á"',
        "býður upp á",
    ),
    # á/í with time expressions
    (
        r"\bá\s+vikunni\b",
        '"á vikunni" — usually should be "í vikunni" (during the week)',
        "í vikunni",
    ),
    (
        r"\bá\s+þessari\s+viku\b",
        '"á þessari viku" — usually should be "í þessari viku"',
        "í þessari viku",
    ),
    # Singular verb + plural subject
    (
        r"\bvar\s+ákvarðanir\b",
        "Singular verb + plural subject: 'var ákvarðanir' → 'voru ákvarðanir'",
        "voru ákvarðanir",
    ),
    # ── Register patterns (inappropriate formality) ─────────────────
    (
        r"\bhér\s+að\s+ofan\b",
        "Register: 'hér að ofan' is overly formal for assessments — just state the content",
        None,
    ),
    (
        r"\beins\s+og\s+áður\s+segir\b",
        "Self-reference: 'eins og áður segir' — state the content directly instead",
        None,
    ),
    (
        r"\bsem\s+fyrr\s+greinir\b",
        "Self-reference: 'sem fyrr greinir' — state the content directly instead",
        None,
    ),
    # ── EU terminology patterns ─────────────────────────────────────
    (
        r"[Hh]águ.?kjörgæð",
        "Wrong translation: 'Hágu-kjörgæðin' is a hallucination — correct term is 'Haag-viðmiðin' (Hague Preferences)",
        "Haag-viðmiðin",
    ),
    (
        r"\bCommon\s+(?:Agricultural|Fisheries)\s+Policy\b",
        "English EU term in Icelandic text: use 'sameiginleg landbúnaðar/sjávarútvegsstefna'",
        None,
    ),
    (
        r"\bSingle\s+[Mm]arket\b",
        "English EU term in Icelandic text: use 'innri markaðurinn'",
        "innri markaðurinn",
    ),
    (
        r"\bEuropean\s+(?:Commission|Parliament|Council)\b",
        "English EU term in Icelandic text: use Icelandic equivalent",
        None,
    ),
    (
        r"\binngöngu(?:samning|viðræð)",
        "Terminology: 'inngöngu-' → 'aðildar-' for EU accession context",
        None,
    ),
]

# Filter out entries where description is None (disabled patterns)
CONFUSABLE_PATTERNS = [(p, d, s) for p, d, s in CONFUSABLE_PATTERNS if d is not None]


def check_confusables(text: str) -> list[dict]:
    """Scan text for known LLM confusable-word patterns.

    Returns a list of warnings. These are NOT auto-fixed — they require
    human review because context determines correctness.
    """
    warnings = []
    lines = text.split("\n")
    for line_num, line in enumerate(lines, 1):
        for pattern, description, suggestion in CONFUSABLE_PATTERNS:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                warnings.append(
                    {
                        "line": line_num,
                        "match": match.group(),
                        "description": description,
                        "suggestion": suggestion,
                        "context": line.strip()[:100],
                    }
                )
    return warnings


def format_confusable_results(warnings: list[dict], filename: str) -> int:
    """Print confusable-word warnings. Returns count of warnings."""
    if not warnings:
        print(f"  {filename}: No confusable-word patterns found")
        return 0

    for w in warnings:
        print(f'  L{w["line"]:3d} [CONFUSABLE] "{w["match"]}"')
        print(f"        {w['description']}")
        if w["suggestion"]:
            print(f"        → {w['suggestion']}")

    return len(warnings)
