"""CLI entry point and orchestration for the ESBvaktin Icelandic correction pipeline.

Adapted from Þingfréttir's corrections/cli.py. Key difference: ESBvaktin
checks JSON fields (explanation_is, missing_context_is) rather than markdown files.

Input modes:
  check <path>           — if JSON, extract Icelandic fields; if directory, find all JSON
  check-claims <file>    — check exported claims file (data/export/claims.json)

Layer ordering (same as Þingfréttir):
  1. GreynirCorrect (auto-fix with --fix)
  2. Icegrams naturalness
  3. BÍN inflection validation
  4. Confusable-word scanner
  5. EU terminology checker
  6. GreynirEngine deep parse
"""

import argparse
import json
import re
import sys
from pathlib import Path

from esbvaktin.corrections.greynir import (
    check_with_library,
    check_with_api,
    apply_fixes,
    format_results,
)
from esbvaktin.corrections.naturalness import (
    score_naturalness,
    format_naturalness_results,
    _HAS_ICEGRAMS,
)
from esbvaktin.corrections.inflections import (
    check_inflections,
    format_inflection_results,
    _HAS_ISLENSKA,
)
from esbvaktin.corrections.confusables import (
    check_confusables,
    format_confusable_results,
)
from esbvaktin.corrections.eu_terms import (
    check_eu_terms,
    format_eu_term_results,
)
from esbvaktin.corrections.parsing import (
    deep_parse,
    format_deep_parse_results,
    _HAS_GREYNIR,
)

# Icelandic character set for the Unicode check
_ICE_CHARS = re.compile(r"[þðáéíóúýæöÞÐÁÉÍÓÚÝÆÖ]")

# Fields to extract from JSON for checking
_ICELANDIC_FIELDS = [
    "explanation_is",
    "missing_context_is",
    "canonical_text_is",
]


def _extract_icelandic_from_json(filepath: Path) -> list[tuple[str, int]]:
    """Extract Icelandic text from JSON file(s).

    For assessment JSON: extracts explanation_is and missing_context_is fields.
    For claims JSON: extracts from array of claim objects.

    Returns (text, pseudo_line_number) pairs where line_number is derived
    from the item index.
    """
    data = json.loads(filepath.read_text(encoding="utf-8"))

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = [data]
    else:
        return []

    sentences: list[tuple[str, int]] = []
    for i, item in enumerate(items):
        for field in _ICELANDIC_FIELDS:
            text = item.get(field)
            if text and isinstance(text, str) and len(text.strip()) > 5:
                # Split into sentences (simple heuristic: split on '. ' or '. ')
                for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
                    sent = sent.strip()
                    if sent and len(sent) > 5:
                        sentences.append((sent, i + 1))

    return sentences


def _check_unicode(sentences: list[tuple[str, int]], filename: str) -> int:
    """Check for ASCII-only Icelandic text (the #1 problem).

    Returns count of flagged sentences.
    """
    flagged = 0
    for text, line_num in sentences:
        words = text.split()
        if len(words) >= 10 and not _ICE_CHARS.search(text):
            flagged += 1
            display = text[:100] + "..." if len(text) > 100 else text
            print(f'  #{line_num:3d} [ASCII] No Icelandic characters in {len(words)}-word sentence')
            print(f'        "{display}"')

    if flagged == 0:
        print(f"  {filename}: All sentences contain proper Icelandic characters")

    return flagged


def _find_json_files(path: Path) -> list[Path]:
    """Find JSON files to check in a path (file or directory)."""
    if path.is_file() and path.suffix == ".json":
        return [path]
    elif path.is_dir():
        return sorted(path.glob("**/*.json"))
    else:
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Check/correct Icelandic text in ESBvaktin assessments"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # check command
    check_parser = subparsers.add_parser(
        "check", help="Check JSON file(s) or directory for Icelandic issues"
    )
    check_parser.add_argument("path", type=Path, help="JSON file or directory to check")
    check_parser.add_argument("--fix", action="store_true", help="Auto-apply safe fixes")
    check_parser.add_argument("--json", action="store_true", help="Machine-readable output")
    check_parser.add_argument(
        "--api", action="store_true", help="Use yfirlestur.is REST API"
    )
    check_parser.add_argument(
        "--no-deep", action="store_true", help="Skip GreynirEngine deep parsing"
    )
    check_parser.add_argument(
        "--threshold", type=float, default=2.0,
        help="Naturalness threshold in σ (default: 2.0)"
    )

    # check-claims command
    claims_parser = subparsers.add_parser(
        "check-claims", help="Check exported claims file"
    )
    claims_parser.add_argument(
        "path", type=Path, nargs="?",
        default=Path("data/export/claims.json"),
        help="Claims JSON file (default: data/export/claims.json)"
    )

    args = parser.parse_args()

    if args.command == "check-claims":
        _run_claims_check(args.path)
        return

    # check command
    files = _find_json_files(args.path)
    if not files:
        print(f"ERROR: No JSON files found at {args.path}", file=sys.stderr)
        sys.exit(1)

    check_fn = check_with_api if args.api else check_with_library
    run_deep = not args.no_deep and _HAS_GREYNIR

    # Print available layers
    layers = ["Unicode", "GreynirCorrect"]
    if _HAS_ICEGRAMS:
        layers.append("Icegrams")
    if _HAS_ISLENSKA:
        layers.append("BÍN")
    layers.extend(["Confusables", "EU Terms"])
    if run_deep:
        layers.append("GreynirEngine")
    print(f"Layers: {', '.join(layers)}")
    print()

    total_unicode = 0
    total_errors = 0
    total_warnings = 0
    total_fixes = 0
    total_naturalness = 0
    total_inflections = 0
    total_confusables = 0
    total_eu_terms = 0
    total_parse_failures = 0
    all_results: dict[str, dict] = {}

    for filepath in files:
        filename = filepath.name
        sentences = _extract_icelandic_from_json(filepath)

        if not sentences:
            print(f"  {filename}: No Icelandic text found")
            continue

        file_results: dict = {}

        print(f"  === {filename} ({len(sentences)} sentences) ===")

        # Layer 0: Unicode check (ESBvaktin-specific)
        print("  ── Unicode Check ──")
        unicode_flags = _check_unicode(sentences, filename)
        total_unicode += unicode_flags
        file_results["unicode"] = unicode_flags
        print()

        # Layer 1: GreynirCorrect
        try:
            results = check_fn(sentences)
            file_results["greynircorrect"] = results
            print("  ── GreynirCorrect ──")
            errors, warnings, auto_fixable = format_results(results, filename)
            total_errors += errors
            total_warnings += warnings

            if args.fix and auto_fixable > 0 and filepath.suffix == ".json":
                applied = apply_fixes(filepath, results)
                total_fixes += applied
                print(f"  → Applied {applied} auto-fix(es)")
            print()
        except Exception:
            print("  ── GreynirCorrect ── (skipped, not installed)")
            print()

        # Layer 2: Icegrams naturalness
        if _HAS_ICEGRAMS:
            nat_flagged = score_naturalness(sentences, threshold_sigma=args.threshold)
            file_results["naturalness"] = nat_flagged
            print("  ── Naturalness (Icegrams) ──")
            total_naturalness += format_naturalness_results(nat_flagged, filename)
            print()

        # Layer 3: BÍN inflection check
        if _HAS_ISLENSKA:
            inf_flagged = check_inflections(sentences)
            file_results["inflections"] = inf_flagged
            print("  ── Inflection Check (BÍN) ──")
            total_inflections += format_inflection_results(inf_flagged, filename)
            print()

        # Layer 4: Confusable-word scanner
        full_text = "\n".join(s[0] for s in sentences)
        conf_warnings = check_confusables(full_text)
        file_results["confusables"] = conf_warnings
        print("  ── Confusable Words ──")
        total_confusables += format_confusable_results(conf_warnings, filename)
        print()

        # Layer 5: EU terminology checker
        eu_warnings = check_eu_terms(full_text)
        file_results["eu_terms"] = eu_warnings
        print("  ── EU Terminology ──")
        total_eu_terms += format_eu_term_results(eu_warnings, filename)
        print()

        # Layer 6: GreynirEngine deep parse
        if run_deep:
            parse_flagged = deep_parse(sentences)
            file_results["deep_parse"] = parse_flagged
            print("  ── Deep Parse (GreynirEngine) ──")
            total_parse_failures += format_deep_parse_results(parse_flagged, filename)
            print()

        all_results[filename] = file_results

    if args.json if hasattr(args, "json") and args.json else False:
        json.dump(all_results, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    # Summary
    print("=" * 60)
    print(f"Unicode:        {total_unicode} ASCII-only sentence(s)")
    print(f"GreynirCorrect: {total_errors} errors, {total_warnings} warnings", end="")
    if args.fix:
        print(f", {total_fixes} auto-fixed")
    else:
        print()
    if _HAS_ICEGRAMS:
        print(f"Naturalness:    {total_naturalness} flagged")
    if _HAS_ISLENSKA:
        print(f"Inflections:    {total_inflections} not in BÍN")
    print(f"Confusables:    {total_confusables} pattern(s)")
    print(f"EU Terms:       {total_eu_terms} issue(s)")
    if run_deep:
        print(f"Deep Parse:     {total_parse_failures} unparseable")
    print("=" * 60)

    # Exit codes: 2 = blocking (ASCII), 1 = warnings, 0 = clean
    if total_unicode > 0:
        sys.exit(2)
    elif total_errors > 0 or total_confusables > 0 or total_eu_terms > 0:
        sys.exit(1)


def _run_claims_check(path: Path):
    """Quick ASCII-only check on the exported claims file."""
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)

    claims = json.loads(path.read_text(encoding="utf-8"))
    ascii_claims = []

    for c in claims:
        for field in _ICELANDIC_FIELDS:
            text = c.get(field, "") or ""
            if len(text) > 50 and not _ICE_CHARS.search(text):
                ascii_claims.append(
                    {
                        "slug": c.get("claim_slug", "?"),
                        "field": field,
                        "sample": text[:80],
                    }
                )

    if not ascii_claims:
        print(f"All {len(claims)} claims have proper Icelandic Unicode text.")
        sys.exit(0)
    else:
        print(f"Found {len(ascii_claims)} ASCII-only Icelandic fields in {len(claims)} claims:\n")
        for ac in ascii_claims:
            print(f"  [{ac['field']}] {ac['slug']}")
            print(f"    {ac['sample']}...")
            print()
        sys.exit(2)
