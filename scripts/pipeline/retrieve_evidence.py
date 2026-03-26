"""Retrieve evidence for extracted claims and prepare assessment contexts.

Parses _claims.json, queries the Ground Truth database via pgvector semantic
search, optionally builds parliamentary speech context, and writes
_context_assessment.md + _context_omissions.md.

This is the step that most often triggered Bash security scanner issues when
run as inline `python -c` — it has DB connections, multiple imports, and
complex function calls.

Usage:
    uv run python scripts/pipeline/retrieve_evidence.py WORK_DIR

Exit codes: 0 = success, 1 = failure
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve evidence and prepare assessment/omission contexts"
    )
    parser.add_argument("work_dir", type=Path, help="Pipeline working directory")
    parser.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="Number of evidence items per claim (default: 8)",
    )
    parser.add_argument(
        "--language",
        default="is",
        choices=["is", "en"],
        help="Context language (default: is)",
    )
    parser.add_argument(
        "--no-speech-context",
        action="store_true",
        help="Skip parliamentary speech context",
    )
    args = parser.parse_args()

    work_dir: Path = args.work_dir
    claims_path = work_dir / "_claims.json"
    article_path = work_dir / "_article.md"

    if not claims_path.exists():
        print(f"ERROR: {claims_path} not found", file=sys.stderr)
        sys.exit(1)
    if not article_path.exists():
        print(f"ERROR: {article_path} not found", file=sys.stderr)
        sys.exit(1)

    # ── Parse claims ────────────────────────────────────────────────────
    from esbvaktin.pipeline.parse_outputs import parse_claims

    claims = parse_claims(claims_path)
    print(f"Parsed {len(claims)} claims.")

    # ── Retrieve evidence ───────────────────────────────────────────────
    from esbvaktin.pipeline.retrieve_evidence import retrieve_evidence_for_claims

    claims_with_evidence, bank_matches, hearsay_assessments = retrieve_evidence_for_claims(
        claims, top_k=args.top_k
    )
    print(f"Retrieved evidence for {len(claims_with_evidence)} claims.")
    if bank_matches:
        print(f"Claim bank matches: {len(bank_matches)} (cache hits speed up assessment)")

    # ── Build speech context (optional) ─────────────────────────────────
    article_text = article_path.read_text(encoding="utf-8")
    speech_ctx = None

    if not args.no_speech_context:
        try:
            from esbvaktin.speeches.context import build_speech_context

            speech_ctx = build_speech_context(article_text, language=args.language)
            if speech_ctx:
                print("Found parliamentary speech context for MPs in article.")
        except Exception as e:
            print(f"Speech context unavailable: {e}")

    # ── Prepare assessment and omission contexts ────────────────────────
    from esbvaktin.pipeline.prepare_context import (
        prepare_assessment_context,
        prepare_omission_context,
    )

    prepare_assessment_context(
        claims_with_evidence,
        work_dir,
        language=args.language,
        speech_context=speech_ctx,
        bank_matches=bank_matches or None,
    )
    prepare_omission_context(
        article_text,
        claims_with_evidence,
        work_dir,
        language=args.language,
    )
    print(f"Assessment and omission contexts prepared ({args.language}).")


if __name__ == "__main__":
    main()
