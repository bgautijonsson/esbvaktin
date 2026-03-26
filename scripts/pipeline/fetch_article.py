"""Fetch an article and create a pipeline working directory.

Creates the timestamped work directory, fetches article text via trafilatura
(or reads from inbox cache / local file), resolves metadata, and writes
_article.md + _metadata.json.

Usage:
    uv run python scripts/pipeline/fetch_article.py --url URL
    uv run python scripts/pipeline/fetch_article.py --url URL --inbox-id ID
    uv run python scripts/pipeline/fetch_article.py --file path/to/article.md
    uv run python scripts/pipeline/fetch_article.py --file path/to/article.md --url URL

Exit codes: 0 = success (prints WORK_DIR path), 1 = failure, 2 = skipped (too short)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Fetch article and create pipeline working directory"
    )
    parser.add_argument("--url", help="Article URL to fetch via trafilatura")
    parser.add_argument("--file", help="Path to local article text file")
    parser.add_argument("--inbox-id", help="Inbox entry ID (uses cached text if available)")
    parser.add_argument(
        "--work-dir",
        help="Use this directory instead of creating a new timestamped one",
    )
    parser.add_argument("--title", help="Override article title (otherwise resolved from metadata)")
    parser.add_argument(
        "--source", help="Override article source (otherwise resolved from metadata)"
    )
    parser.add_argument(
        "--date", help="Override article date as YYYY-MM-DD (otherwise resolved from metadata)"
    )
    args = parser.parse_args()

    if not args.url and not args.file and not args.inbox_id:
        parser.error("At least one of --url, --file, or --inbox-id is required")

    # ── Create or reuse work directory ──────────────────────────────────
    if args.work_dir:
        work_dir = Path(args.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"
        work_dir = Path("data/analyses") / timestamp
        work_dir.mkdir(parents=True, exist_ok=True)

    # ── Get article text ────────────────────────────────────────────────
    article_text = None

    # Priority 1: inbox cached text
    if args.inbox_id:
        cache_path = Path("data/inbox/texts") / f"{args.inbox_id}.md"
        if cache_path.exists():
            article_text = cache_path.read_text(encoding="utf-8")
            print(f"Using cached text from inbox ({len(article_text)} chars)")

    # Priority 2: local file
    if article_text is None and args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"ERROR: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        article_text = file_path.read_text(encoding="utf-8")
        print(f"Read article from {args.file} ({len(article_text)} chars)")

    # Priority 3: fetch via trafilatura
    if article_text is None and args.url:
        try:
            import trafilatura

            downloaded = trafilatura.fetch_url(args.url)
            if downloaded:
                article_text = trafilatura.extract(downloaded) or ""
            if not article_text:
                print(f"ERROR: trafilatura returned no text for {args.url}", file=sys.stderr)
                sys.exit(1)
            print(f"Fetched via trafilatura ({len(article_text)} chars)")
        except ImportError:
            print("ERROR: trafilatura not installed. Run: uv sync", file=sys.stderr)
            sys.exit(1)

    if not article_text:
        print("ERROR: No article text obtained", file=sys.stderr)
        sys.exit(1)

    # ── Word-count gate ──────────────────────────────────────────────────
    word_count = len(article_text.split())
    if word_count < 100:
        print(
            f"Article too short ({word_count} words, minimum 100). Skipping.",
            file=sys.stderr,
        )
        sys.exit(2)

    # ── Write _article.md ───────────────────────────────────────────────
    (work_dir / "_article.md").write_text(article_text, encoding="utf-8")

    # ── Resolve metadata ────────────────────────────────────────────────
    url = args.url or ""
    meta_title = args.title
    meta_source = args.source
    meta_date = args.date

    if url and (meta_title is None or meta_source is None or meta_date is None):
        try:
            from esbvaktin.utils.metadata import resolve_metadata

            resolved = resolve_metadata(url, article_text=article_text)
            if meta_title is None and resolved.title:
                meta_title = resolved.title
            if meta_source is None and resolved.source:
                meta_source = resolved.source
            if meta_date is None and resolved.date:
                meta_date = str(resolved.date)
        except Exception as e:
            print(f"Metadata resolution warning: {e}", file=sys.stderr)

    metadata = {
        "title": meta_title,
        "date": meta_date,
        "source": meta_source,
        "url": url or None,
    }

    (work_dir / "_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # ── Print results ───────────────────────────────────────────────────
    print(f"Work dir: {work_dir}")
    print(
        f"Metadata: date={metadata.get('date')}, "
        f"title={(metadata.get('title') or '?')[:50]}, "
        f"source={metadata.get('source')}"
    )


if __name__ == "__main__":
    main()
