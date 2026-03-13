#!/usr/bin/env python3
"""Fetch a panel show transcript from fréttasafn and write to a work directory.

Bypasses MCP tool token limits by reading the fréttasafn SQLite database
directly and writing _article.md to a new analysis work directory.

Usage:
    uv run python scripts/fetch_panel_transcript.py <article_id> [--name NAME]
    uv run python scripts/fetch_panel_transcript.py 996fc18244d00af3
    uv run python scripts/fetch_panel_transcript.py 996fc18244d00af3 --name vikulokin_07

The script will:
  1. Read the article from fréttasafn.db
  2. Check for duplicates via check_duplicate.py
  3. Create a panel_* work directory under data/analyses/
  4. Write _article.md in the fréttasafn header format
  5. Print the work directory path for use with /analyse-article
"""

import argparse
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

# fréttasafn DB location (sibling repo)
_FRETTASAFN_DB = Path.home() / "frettasafn" / "data" / "frettasafn.db"

# Known show name → directory prefix mapping
_SHOW_SLUGS: dict[str, str] = {
    "silfr": "silfrid",       # Silfrið, Silfurinn, etc.
    "vikulok": "vikulokin",   # Víkulokin / Vikulokin
    "spursm": "spursmal",    # Spursmál
    "kastlj": "kastljos",    # Kastljós
}


def _slugify_show(show_name: str) -> str:
    """Convert show name to a directory-safe slug."""
    lower = show_name.lower().strip()
    for name, slug in _SHOW_SLUGS.items():
        if name in lower:
            return slug
    # Fallback: basic ASCII slugification
    slug = re.sub(r"[^a-z0-9]+", "_", lower.replace("ð", "d").replace("þ", "th")
                  .replace("á", "a").replace("é", "e").replace("í", "i")
                  .replace("ó", "o").replace("ú", "u").replace("ý", "y")
                  .replace("ö", "o").replace("æ", "ae"))
    return slug.strip("_")


def _extract_episode_id(title: str, show_slug: str) -> str:
    """Try to extract an episode number or date identifier from the title."""
    # Look for episode numbers like "#115", "25.", "þáttur 25"
    m = re.search(r"#(\d+)", title)
    if m:
        return m.group(1)
    m = re.search(r"(\d+)\.\s*þátt", title)
    if m:
        return m.group(1)
    m = re.search(r"þátt\w*\s+(\d+)", title, re.IGNORECASE)
    if m:
        return m.group(1)
    # Fallback: use date from title or return empty
    m = re.search(r"(\d{1,2})\.\s*\w+\s+(\d{4})", title)
    if m:
        return f"{m.group(1)}_{m.group(2)}"
    return ""


def fetch_article(article_id: str) -> dict | None:
    """Fetch article from fréttasafn SQLite database."""
    if not _FRETTASAFN_DB.exists():
        print(f"ERROR: fréttasafn database not found at {_FRETTASAFN_DB}", file=sys.stderr)
        print("Expected sibling repo at ~/frettasafn/", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(_FRETTASAFN_DB))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT a.*, s.name AS source_name
           FROM articles a
           JOIN sources s ON a.source_id = s.source_id
           WHERE a.article_id = ?""",
        (article_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return dict(row)


def format_article_md(article: dict) -> str:
    """Format article as markdown in the fréttasafn header format."""
    return (
        f"# {article['title']}\n\n"
        f"**Source:** {article['source_name']} | "
        f"**Date:** {article['published_at'] or '?'} | "
        f"**URL:** {article['url']}\n"
        f"**Words:** {article['word_count'] or '?'} | "
        f"**Language:** {article['language']}\n\n"
        f"{article['content']}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Fetch panel show transcript from fréttasafn"
    )
    parser.add_argument("article_id", help="Fréttasafn article ID")
    parser.add_argument(
        "--name", help="Override directory name (e.g. vikulokin_07)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip duplicate check"
    )
    args = parser.parse_args()

    # 1. Fetch the article
    article = fetch_article(args.article_id)
    if not article:
        print(f"ERROR: Article {args.article_id} not found in fréttasafn", file=sys.stderr)
        sys.exit(1)

    title = article["title"]
    url = article["url"]
    source_name = article["source_name"]
    content = article["content"]
    word_count = article["word_count"] or len(content.split())

    print(f"Found: {title}")
    print(f"Source: {source_name}")
    print(f"URL: {url}")
    print(f"Words: {word_count}")

    # 2. Duplicate check
    if not args.force:
        result = subprocess.run(
            ["uv", "run", "python", "scripts/check_duplicate.py", "--url", url, "--title", title],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"\nDuplicate detected:\n{result.stdout.strip()}")
            print("Use --force to override.")
            sys.exit(1)

    # 3. Determine directory name
    if args.name:
        dir_name = f"panel_{args.name}"
    else:
        # Extract show name (before parenthesised broadcaster)
        show_part = re.sub(r"\s*\(.*\)", "", source_name).strip()
        show_slug = _slugify_show(show_part)
        episode_id = _extract_episode_id(title, show_slug)
        if episode_id:
            dir_name = f"panel_{show_slug}_{episode_id}"
        else:
            # Fallback: use date
            date_str = (article["published_at"] or "")[:10].replace("-", "")
            dir_name = f"panel_{show_slug}_{date_str}"

    work_dir = Path("data/analyses") / dir_name

    if work_dir.exists():
        print(f"\nERROR: Work directory already exists: {work_dir}", file=sys.stderr)
        sys.exit(1)

    # 4. Write _article.md
    work_dir.mkdir(parents=True)
    article_md = format_article_md(article)
    (work_dir / "_article.md").write_text(article_md, encoding="utf-8")

    print(f"\nCreated: {work_dir}/_article.md ({len(article_md):,} chars)")
    print("\nNext steps:")
    print(f"  /analyse-article {work_dir}/_article.md")


if __name__ == "__main__":
    main()
