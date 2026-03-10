"""GreynirCorrect grammar and spelling checks.

Adapted from Þingfréttir's corrections/greynir.py for ESBvaktin's
fact-check assessment domain. Adds apply_fixes_to_text() for in-memory
string correction (used by the pipeline, not just files).
"""

import re
import shutil
import sys
from pathlib import Path

try:
    from islenska import Bin

    _HAS_ISLENSKA = True
except ImportError:
    _HAS_ISLENSKA = False

# Annotation codes that are safe to auto-apply
# S004 = spelling correction, S001 = compound word
AUTO_FIX_CODES = {"S004", "S001"}

# Codes that are phrase-level corrections (high confidence)
PHRASE_FIX_CODES = {"P_afað"}

# S004 words to never "correct" — valid compounds that GreynirCorrect misidentifies.
# EU-specific terms that GreynirCorrect may flag incorrectly.
S004_SUPPRESS = {
    "aðildarviðræður",
    "sjávarútvegsstefna",
    "landbúnaðarstefna",
    "aðlögunartímabil",
    "viðræðukaflar",
    "sáttmálabókun",
    "kvótakerfi",
    "byggðasjóðir",
    "regluverkið",
    "nálægðarreglan",
    "atkvæðagreiðsla",
}


_reynir_available: bool | None = None


def check_with_library(sentences: list[tuple[str, int]]) -> list[dict]:
    """Check sentences using local GreynirCorrect library."""
    global _reynir_available
    if _reynir_available is False:
        return []
    try:
        from reynir_correct import check_single
        _reynir_available = True
    except ImportError:
        _reynir_available = False
        print(
            "WARNING: reynir-correct not installed. Run: uv pip install reynir-correct",
            file=sys.stderr,
        )
        return []

    results = []
    for text, line_num in sentences:
        sent = check_single(text)
        for ann in sent.annotations:
            results.append(
                {
                    "line": line_num,
                    "code": ann.code,
                    "text": ann.text,
                    "detail": ann.detail or "",
                    "suggest": ann.suggest or "",
                    "original": text,
                    "corrected": sent.tidy_text,
                    "auto_fixable": ann.code in AUTO_FIX_CODES
                    or ann.code in PHRASE_FIX_CODES,
                }
            )
    return results


def check_with_api(sentences: list[tuple[str, int]]) -> list[dict]:
    """Check sentences using yfirlestur.is REST API."""
    import httpx

    results = []
    batch_size = 20
    all_sentences = list(sentences)

    for batch_start in range(0, len(all_sentences), batch_size):
        batch = all_sentences[batch_start : batch_start + batch_size]
        text = "\n".join(s[0] for s in batch)

        resp = httpx.post(
            "https://yfirlestur.is/correct.api",
            data={"text": text},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        for i, paragraph in enumerate(data.get("result", [])):
            for sent_data in paragraph:
                line_num = batch[min(i, len(batch) - 1)][1]
                for ann in sent_data.get("annotations", []):
                    results.append(
                        {
                            "line": line_num,
                            "code": ann["code"],
                            "text": ann["text"],
                            "detail": ann.get("detail", ""),
                            "suggest": ann.get("suggest", ""),
                            "original": sent_data.get("original", ""),
                            "corrected": sent_data.get("corrected", ""),
                            "auto_fixable": ann["code"] in AUTO_FIX_CODES
                            or ann["code"] in PHRASE_FIX_CODES,
                        }
                    )

    return results


def _apply_fix_to_content(content: str, r: dict) -> tuple[str, bool]:
    """Apply a single fix to content string. Returns (new_content, was_applied)."""
    if not r["auto_fixable"] or not r["suggest"]:
        return content, False

    code = r["code"]
    if code in AUTO_FIX_CODES:
        m = re.search(r"'([^']+)' var leiðrétt í '([^']+)'", r["text"])
        if m:
            old_word, new_word = m.group(1), m.group(2)
            if code == "S004" and old_word in S004_SUPPRESS:
                return content, False
            # Safety gate: BÍN dual-lemma check
            if _HAS_ISLENSKA and code == "S004":
                b = Bin()
                _, old_meanings = b.lookup(old_word)
                _, new_meanings = b.lookup(new_word)
                if old_meanings and new_meanings:
                    old_lemmas = {m_.ord for m_ in old_meanings}
                    new_lemmas = {m_.ord for m_ in new_meanings}
                    if old_lemmas != new_lemmas:
                        return content, False
            pattern = re.compile(re.escape(old_word))
            if pattern.search(content):
                content = pattern.sub(new_word, content, count=1)
                return content, True

    elif code in PHRASE_FIX_CODES:
        m = re.search(r"'([^']+)' var leiðrétt í '([^']+)'", r["text"])
        if m:
            old_phrase, new_phrase = m.group(1), m.group(2)
            if old_phrase in content:
                content = content.replace(old_phrase, new_phrase, 1)
                return content, True

    return content, False


def apply_fixes(filepath: Path, results: list[dict]) -> int:
    """Apply auto-fixable corrections to a file. Returns count of applied fixes."""
    content = filepath.read_text(encoding="utf-8")
    fixes_applied = 0

    for r in results:
        content, applied = _apply_fix_to_content(content, r)
        if applied:
            fixes_applied += 1

    if fixes_applied > 0:
        shutil.copy2(filepath, filepath.with_suffix(filepath.suffix + ".bak"))
        filepath.write_text(content, encoding="utf-8")

    return fixes_applied


def apply_fixes_to_text(text: str, results: list[dict]) -> tuple[str, int]:
    """Apply auto-fixable corrections to a string. Returns (corrected_text, count)."""
    fixes_applied = 0
    for r in results:
        text, applied = _apply_fix_to_content(text, r)
        if applied:
            fixes_applied += 1
    return text, fixes_applied


def format_results(results: list[dict], filename: str) -> tuple[int, int, int]:
    """Print formatted results. Returns (errors, warnings, auto_fixable)."""
    errors = 0
    warnings = 0
    auto_fixable = 0

    if not results:
        print(f"  {filename}: No issues found")
        return 0, 0, 0

    for r in results:
        code = r["code"]
        icon = "FIX" if r["auto_fixable"] else "CHECK"

        if r["auto_fixable"]:
            auto_fixable += 1
        elif code.startswith("P_"):
            errors += 1
        else:
            warnings += 1

        print(f"  L{r['line']:3d} [{icon}] {code}: {r['text']}")
        if r["suggest"]:
            print(f"        → {r['suggest']}")
        if r["detail"] and not r["auto_fixable"]:
            print(f"        ℹ {r['detail']}")

    return errors, warnings, auto_fixable
