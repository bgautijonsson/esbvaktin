"""Icegrams trigram probability scoring and heuristic naturalness detection.

Adapted from Þingfréttir. Two layers:
1. Trigram scoring (requires icegrams) — statistical outlier detection
2. Heuristic checks (no dependencies) — pattern-based anti-exemplar detection

The heuristic checks catch translationese patterns that trigram models miss:
monotonous sentence openings, over-hedging, missing Icelandic characters,
and over-formal register.
"""

import math
import re

try:
    from icegrams import Ngrams

    _HAS_ICEGRAMS = True
except ImportError:
    _HAS_ICEGRAMS = False

# Characters that must appear in any natural Icelandic paragraph
_ICELANDIC_CHARS = set("þðáéíóúýæöÞÐÁÉÍÓÚÝÆÖ")

# Hedging phrases that indicate translationese when evidence is clear
_HEDGING_PATTERNS = [
    (r"\bvirðist\s+benda\s+til\b", "virðist benda til"),
    (r"\bvirðast\s+benda\s+til\b", "virðast benda til"),
    (r"\bgæti\s+mögulega\b", "gæti mögulega"),
    (r"\bmá\s+kannski\s+benda\b", "má kannski benda"),
    (r"\ber\s+hugsanlegt\s+að\b", "er hugsanlegt að"),
    (r"\bþað\s+er\s+ekki\s+útilokað\b", "það er ekki útilokað"),
]

# Over-formal register markers inappropriate for Kastljós/Kjarninn tone
_OVERFORMAL_PATTERNS = [
    (r"\bhér\s+að\s+ofan\b", "hér að ofan"),
    (r"\bfyrrgreind(?:ur|s|ri|ra)?\b", "fyrrgreindur/fyrrgreint"),
    (r"\bofangreind(?:ur|s|ri|ra)?\b", "ofangreindur/ofangreint"),
    (r"\bhinsvegar\b", "hinsvegar (ætti að vera 'hins vegar')"),
]


def score_naturalness(
    sentences: list[tuple[str, int]],
    threshold_sigma: float = 2.0,
) -> list[dict]:
    """Score sentences using Icegrams trigram probability.

    Returns a list of flagged sentences (those scoring >threshold_sigma
    standard deviations below the mean log-probability).
    """
    if not _HAS_ICEGRAMS:
        return []

    ngrams = Ngrams()
    scored: list[tuple[str, int, float]] = []

    for text, line_num in sentences:
        words = text.split()
        if len(words) < 3:
            continue
        try:
            logprob = ngrams.logprob(text)
            norm_score = logprob / len(words)
            scored.append((text, line_num, norm_score))
        except Exception:
            continue

    if not scored:
        return []

    scores = [s[2] for s in scored]
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    stddev = math.sqrt(variance) if variance > 0 else 0.0

    if stddev == 0:
        return []

    threshold = mean - threshold_sigma * stddev
    flagged = []
    for text, line_num, score in scored:
        if score < threshold:
            sigma_below = (mean - score) / stddev
            flagged.append(
                {
                    "line": line_num,
                    "text": text,
                    "score": round(score, 4),
                    "mean": round(mean, 4),
                    "sigma_below": round(sigma_below, 2),
                }
            )

    flagged.sort(key=lambda x: x["score"])
    return flagged


def check_monotonous_openings(
    sentences: list[tuple[str, int]],
    window: int = 3,
) -> list[dict]:
    """Detect monotonous sentence openings (same first word in N consecutive sentences).

    Catches anti-exemplar patterns like "Samkvæmt... / Samkvæmt... / Samkvæmt..."
    or "Heimildir... / Heimildir... / Heimildir...".
    """
    if len(sentences) < window:
        return []

    flagged = []
    for i in range(len(sentences) - window + 1):
        group = sentences[i : i + window]
        first_words = []
        for text, _ in group:
            words = text.strip().split()
            if words:
                # Normalise: strip quotes, punctuation
                word = words[0].strip("\"'\u201E\u201C\u00AB\u00BB")
                first_words.append(word.lower())

        if len(first_words) == window and len(set(first_words)) == 1:
            flagged.append(
                {
                    "line": group[0][1],
                    "pattern": first_words[0],
                    "count": window,
                    "sentences": [t[:60] for t, _ in group],
                }
            )

    return flagged


def check_hedging(sentences: list[tuple[str, int]]) -> list[dict]:
    """Flag hedging phrases that suggest translationese.

    These phrases are not always wrong — but in assessment text where
    evidence is being cited, they usually indicate unnecessary caution.
    """
    flagged = []
    for text, line_num in sentences:
        for pattern, label in _HEDGING_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                flagged.append(
                    {
                        "line": line_num,
                        "pattern": label,
                        "text": text[:100],
                    }
                )
    return flagged


def check_missing_icelandic_chars(
    sentences: list[tuple[str, int]],
    min_words: int = 20,
) -> list[dict]:
    """Flag Icelandic paragraphs with no Icelandic-specific characters.

    Any paragraph of 20+ words that contains none of {þ, ð, á, é, í, ó, ú, ý, æ, ö}
    is defective — it's likely ASCII-transliterated or not actually Icelandic.
    """
    flagged = []
    for text, line_num in sentences:
        words = text.split()
        if len(words) < min_words:
            continue
        if not any(c in _ICELANDIC_CHARS for c in text):
            flagged.append(
                {
                    "line": line_num,
                    "text": text[:100],
                    "word_count": len(words),
                }
            )
    return flagged


def check_overformal_register(sentences: list[tuple[str, int]]) -> list[dict]:
    """Flag overly formal phrases inappropriate for analytical Icelandic.

    The target register is Kastljós/Kjarninn — not academic or legal writing.
    """
    flagged = []
    for text, line_num in sentences:
        for pattern, label in _OVERFORMAL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                flagged.append(
                    {
                        "line": line_num,
                        "pattern": label,
                        "text": text[:100],
                    }
                )
    return flagged


def run_heuristic_checks(
    sentences: list[tuple[str, int]],
) -> dict[str, list[dict]]:
    """Run all heuristic naturalness checks. No external dependencies needed.

    Returns a dict keyed by check name, each containing a list of flagged items.
    """
    return {
        "monotonous_openings": check_monotonous_openings(sentences),
        "hedging": check_hedging(sentences),
        "missing_icelandic_chars": check_missing_icelandic_chars(sentences),
        "overformal_register": check_overformal_register(sentences),
    }


def format_naturalness_results(flagged: list[dict], filename: str) -> int:
    """Print naturalness scoring results. Returns count of flagged sentences."""
    if not flagged:
        print(f"  {filename}: All sentences within normal range")
        return 0

    for f in flagged:
        display = f["text"][:100] + "..." if len(f["text"]) > 100 else f["text"]
        print(
            f"  L{f['line']:3d} [NATURALNESS] score={f['score']} "
            f"({f['sigma_below']}σ below mean={f['mean']})"
        )
        print(f'        "{display}"')

    return len(flagged)


def format_heuristic_results(results: dict[str, list[dict]], filename: str) -> int:
    """Print heuristic check results. Returns total count of flagged items."""
    total = 0

    for check_name, flagged in results.items():
        if not flagged:
            continue

        label = check_name.upper().replace("_", " ")
        for f in flagged:
            line = f.get("line", 0)
            if check_name == "monotonous_openings":
                print(
                    f'  L{line:3d} [{label}] "{f["pattern"]}" '
                    f'repeated {f["count"]}× in consecutive sentences'
                )
                for s in f.get("sentences", []):
                    print(f"        → {s}...")
            elif check_name == "missing_icelandic_chars":
                print(
                    f"  L{line:3d} [{label}] {f['word_count']} words, "
                    f"no Icelandic characters"
                )
                display = f["text"][:80] + "..." if len(f["text"]) > 80 else f["text"]
                print(f'        "{display}"')
            else:
                print(f'  L{line:3d} [{label}] "{f["pattern"]}"')
                display = f["text"][:80] + "..." if len(f["text"]) > 80 else f["text"]
                print(f'        "{display}"')

            total += 1

    if total == 0:
        print(f"  {filename}: No heuristic issues found")

    return total
