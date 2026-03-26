"""Prepare the extraction context for the claim-extractor subagent.

Auto-detects panel show transcripts vs regular articles and calls the
appropriate context preparation function.

Usage:
    uv run python scripts/pipeline/prepare_extraction.py WORK_DIR

Writes _context_extraction.md to the work directory.
Exit codes: 0 = success, 1 = failure
"""

import argparse
import json
import sys
from pathlib import Path

from esbvaktin.pipeline.detection import is_panel_show as _is_panel_show_impl


def _is_panel_show(article_text: str, metadata: dict) -> bool:
    """Detect whether the article is a panel show transcript."""
    return _is_panel_show_impl(metadata, article_text)


def main():
    parser = argparse.ArgumentParser(
        description="Prepare extraction context for claim-extractor subagent"
    )
    parser.add_argument("work_dir", type=Path, help="Pipeline working directory")
    parser.add_argument(
        "--language",
        default="is",
        choices=["is", "en"],
        help="Context language (default: is)",
    )
    args = parser.parse_args()

    work_dir: Path = args.work_dir
    article_path = work_dir / "_article.md"
    meta_path = work_dir / "_metadata.json"

    if not article_path.exists():
        print(f"ERROR: {article_path} not found", file=sys.stderr)
        sys.exit(1)

    article_text = article_path.read_text(encoding="utf-8")
    metadata = {}
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    if _is_panel_show(article_text, metadata):
        # Panel show path
        from esbvaktin.pipeline.prepare_context import prepare_panel_extraction_context
        from esbvaktin.pipeline.transcript import parse_transcript

        transcript = parse_transcript(article_text)
        prepare_panel_extraction_context(transcript, work_dir, language=args.language)
        print(f"Panel show detected: {transcript.show_name}")
        print(f"Participants: {len(transcript.participants)}")
        for p in transcript.participants:
            print(f"  - {p['name']} ({p['role']})")
        print(f"Moderator turns: {sum(1 for t in transcript.turns if t.is_moderator)}")
        print(f"Total word count: {transcript.word_count}")
    else:
        # Regular article path
        from esbvaktin.pipeline.prepare_context import prepare_extraction_context

        prepare_extraction_context(
            article_text=article_text,
            output_dir=work_dir,
            metadata=metadata,
            language=args.language,
        )
        print("Regular article detected.")

    print(f"Extraction context prepared ({args.language}).")


if __name__ == "__main__":
    main()
