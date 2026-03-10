"""Icegrams trigram probability scoring for naturalness detection.

Adapted from Þingfréttir. Flags sentences whose normalised log-probability
is more than threshold_sigma standard deviations below the document mean.
"""

import math

try:
    from icegrams import Ngrams

    _HAS_ICEGRAMS = True
except ImportError:
    _HAS_ICEGRAMS = False


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
