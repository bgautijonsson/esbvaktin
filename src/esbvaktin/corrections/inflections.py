"""BÍN inflection validation — check word forms against the Icelandic dictionary.

Adapted from Þingfréttir. Skiplist adjusted for EU/EEA domain
(removed parliamentary abbreviations, added EU abbreviations).
"""

import re

try:
    from islenska import Bin

    _HAS_ISLENSKA = True
except ImportError:
    _HAS_ISLENSKA = False

# Words to skip in inflection checking: common English loanwords,
# abbreviations, and EU/EEA jargon not in BÍN
_INFLECTION_SKIPLIST = {
    # English loanwords common in EU text
    "spin", "status", "quo", "ok", "okay", "the", "of", "and",
    "acquis", "communautaire", "screening",
    # EU/EEA abbreviations
    "ESB", "EES", "CAP", "CFP", "EFTA", "NATO", "ETS",
    "CSDP", "CFSP", "OBR", "VLF", "MSY",
    "esb", "ees", "cap", "cfp", "efta", "nato", "ets",
    # Icelandic abbreviations
    "skv", "sbr", "nr", "gr", "mgr",
    # Common short words / interjections
    "já", "nei", "hér", "þar", "nú", "þá",
    "og", "en", "eð", "um", "af", "að", "frá", "til", "við", "sem", "er", "var", "sé",
}


def _extract_words(text: str) -> list[str]:
    """Extract Icelandic words from text, skipping punctuation and numbers."""
    return [w for w in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿÞþÐðÆæÖö]+", text) if len(w) > 1]


def check_inflections(
    sentences: list[tuple[str, int]],
) -> list[dict]:
    """Check word forms against BÍN. Flag forms not found."""
    if not _HAS_ISLENSKA:
        return []

    b = Bin()
    flagged = []
    seen: set[str] = set()

    for text, line_num in sentences:
        words = _extract_words(text)
        for i, word in enumerate(words):
            word_lower = word.lower()

            if (
                word_lower in seen
                or word_lower in _INFLECTION_SKIPLIST
                or len(word_lower) < 3
            ):
                continue
            seen.add(word_lower)

            # Skip capitalised words that aren't sentence-initial (likely proper nouns)
            if word[0].isupper() and i > 0:
                continue

            _, meanings = b.lookup(word_lower)
            if not meanings:
                _, meanings = b.lookup(word)
            if not meanings:
                flagged.append(
                    {
                        "line": line_num,
                        "word": word,
                        "context": text[:80] + "..." if len(text) > 80 else text,
                    }
                )

    return flagged


def format_inflection_results(flagged: list[dict], filename: str) -> int:
    """Print inflection check results. Returns count of flagged words."""
    if not flagged:
        print(f"  {filename}: All word forms found in BÍN")
        return 0

    for f in flagged:
        print(f'  L{f["line"]:3d} [INFLECTION] "{f["word"]}" not found in BÍN')
        print(f'        in: "{f["context"]}"')

    return len(flagged)
