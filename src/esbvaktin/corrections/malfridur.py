"""Málstaður API integration for Icelandic grammar correction.

Uses Miðeind's Málstaður API (api.malstadur.is) for grammar checking via the
/v1/grammar endpoint. This is a higher-quality alternative to the local
GreynirCorrect library and the older yfirlestur.is API.

HTTP transport is delegated to esbvaktin.utils.malstadur.MalstadurClient,
which provides retry + rate-limit handling. This module wraps the result
shape into the malfridur format used by the Icelandic correction pipeline
(line numbers + auto_fixable flag).

Requires MALSTADUR_API_KEY environment variable.

API docs: https://mideind.is/is/greinar/forritaskil-api-a-malstad
"""

from esbvaktin.utils.malstadur import MalstadurClient


def check_with_malfridur(
    sentences: list[tuple[str, int]],
    *,
    batch_size: int = 10,
) -> list[dict]:
    """Check sentences using the Málstaður grammar API.

    Sends texts via the centralised MalstadurClient (with retry + 0.5s
    inter-call delay) and transforms results into the malfridur dict
    format used by the rest of the correction pipeline.

    Each result dict has:
        line: int — pseudo line number from input
        original: str — original sentence text
        corrected: str — corrected text (may equal original if no changes)
        annotations: list[dict] — individual change annotations
        auto_fixable: bool — True if corrections were found
    """
    if not sentences:
        return []

    texts = [s[0] for s in sentences]

    with MalstadurClient() as client:
        api_results = client.check_grammar(texts, batch_size=batch_size)

    results: list[dict] = []
    for i, item in enumerate(api_results):
        original = item.get("originalText", "")
        corrected = item.get("changedText", "")
        annotations = item.get("diffAnnotations", [])
        line_num = sentences[i][1] if i < len(sentences) else 0

        has_changes = bool(annotations) and original != corrected
        results.append(
            {
                "line": line_num,
                "original": original,
                "corrected": corrected,
                "annotations": annotations,
                "auto_fixable": has_changes,
            }
        )

    return results


def apply_malfridur_fixes(text: str, results: list[dict]) -> tuple[str, int]:
    """Apply Málstaður corrections to a string.

    Replaces each original sentence with its corrected version.
    Returns (corrected_text, count_of_fixes).
    """
    fixes = 0
    for r in results:
        if not r["auto_fixable"]:
            continue
        original = r["original"]
        corrected = r["corrected"]
        if original and corrected and original != corrected and original in text:
            text = text.replace(original, corrected, 1)
            fixes += 1
    return text, fixes


def apply_malfridur_fixes_to_file(filepath, results: list[dict]) -> int:
    """Apply Málstaður corrections to a file. Returns count of fixes."""
    import shutil
    from pathlib import Path

    filepath = Path(filepath)
    text = filepath.read_text(encoding="utf-8")
    text, fixes = apply_malfridur_fixes(text, results)

    if fixes > 0:
        shutil.copy2(filepath, filepath.with_suffix(filepath.suffix + ".bak"))
        filepath.write_text(text, encoding="utf-8")

    return fixes


def format_malfridur_results(results: list[dict], filename: str) -> tuple[int, int]:
    """Print formatted Málstaður results. Returns (corrections, unchanged)."""
    corrections = 0
    unchanged = 0

    for r in results:
        if r["auto_fixable"]:
            corrections += 1
            print(f"  L{r['line']:3d} [FIX] ", end="")
            for ann in r["annotations"]:
                change_type = ann.get("changeType", "?")
                orig = ann.get("origString", "")
                changed = ann.get("changedString", "")
                if orig or changed:
                    print(f'{change_type}: "{orig}" → "{changed}"')
                else:
                    print(f"{change_type}")
        else:
            unchanged += 1

    if corrections == 0:
        print(f"  {filename}: No corrections needed")

    return corrections, unchanged
