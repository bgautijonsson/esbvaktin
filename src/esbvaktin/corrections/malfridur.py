"""Málstaður API integration for Icelandic grammar correction.

Uses Miðeind's Málstaður API (api.malstadur.is) for grammar checking via the
/v1/grammar endpoint. This is a higher-quality alternative to the local
GreynirCorrect library and the older yfirlestur.is API.

Requires MALSTADUR_API_KEY environment variable.

API docs: https://mideind.is/is/greinar/forritaskil-api-a-malstad
"""

import os

import httpx

MALSTADUR_BASE = "https://api.malstadur.is/v1"


def _get_api_key() -> str:
    """Get API key from environment, raising if not set."""
    key = os.environ.get("MALSTADUR_API_KEY", "")
    if not key:
        raise RuntimeError(
            "MALSTADUR_API_KEY not set. "
            "Get one at https://malstadur.mideind.is/askrift"
        )
    return key


def check_with_malfridur(
    sentences: list[tuple[str, int]],
    *,
    batch_size: int = 10,
) -> list[dict]:
    """Check sentences using the Málstaður grammar API.

    Sends texts in batches to /v1/grammar and returns a list of correction
    dicts compatible with the existing pipeline format.

    Each result dict has:
        line: int — pseudo line number from input
        original: str — original sentence text
        corrected: str — corrected text (may equal original if no changes)
        annotations: list[dict] — individual change annotations
        auto_fixable: bool — True if corrections were found
    """
    api_key = _get_api_key()
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }

    results: list[dict] = []

    for batch_start in range(0, len(sentences), batch_size):
        batch = sentences[batch_start : batch_start + batch_size]
        texts = [s[0] for s in batch]

        resp = httpx.post(
            f"{MALSTADUR_BASE}/grammar",
            headers=headers,
            json={"texts": texts},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        for i, item in enumerate(data.get("results", [])):
            original = item.get("originalText", "")
            corrected = item.get("changedText", "")
            annotations = item.get("diffAnnotations", [])
            line_num = batch[i][1] if i < len(batch) else 0

            has_changes = bool(annotations) and original != corrected
            results.append({
                "line": line_num,
                "original": original,
                "corrected": corrected,
                "annotations": annotations,
                "auto_fixable": has_changes,
            })

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
    from pathlib import Path
    import shutil

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
                    print(f"{change_type}: \"{orig}\" → \"{changed}\"")
                else:
                    print(f"{change_type}")
        else:
            unchanged += 1

    if corrections == 0:
        print(f"  {filename}: No corrections needed")

    return corrections, unchanged
