"""Check if an article has already been analysed.

Uses the unified article registry (data/article_registry.json) which merges
data/analyses/, site reports, and DB claim_sightings. Falls back to scanning
data/analyses/ directly if the registry doesn't exist.

Usage:
    uv run python scripts/check_duplicate.py --url URL
    uv run python scripts/check_duplicate.py --title "Article Title"
    uv run python scripts/check_duplicate.py --frettasafn-id ARTICLE_ID
    uv run python scripts/check_duplicate.py --rebuild  # Rebuild registry first

Exit codes: 0 = duplicate found, 1 = not found, 2 = error
"""

import argparse
import json
import re
import sys
from pathlib import Path

ANALYSES_DIR = Path("data/analyses")
REGISTRY_PATH = Path("data/article_registry.json")


def normalise(s: str) -> str:
    """Normalise title for fuzzy matching."""
    s = s.lower().strip()
    s = re.sub(r'[„""\'\'«»\-–—:?!.,]', "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def load_processed() -> list[dict]:
    """Load processed articles from registry, falling back to analyses dir."""
    results = []

    # Try registry first (unified source of truth)
    if REGISTRY_PATH.exists():
        try:
            registry = json.loads(REGISTRY_PATH.read_text())
            for entry in registry:
                results.append({
                    "dir": entry.get("analysis_dir", entry.get("slug", "")),
                    "title": entry.get("title", ""),
                    "url": entry.get("url", ""),
                    "title_norm": normalise(entry.get("title", "")),
                    "on_site": entry.get("on_site", False),
                    "in_db": entry.get("in_db", False),
                })
            return results
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: scan data/analyses/ directly
    if not ANALYSES_DIR.exists():
        return results
    for d in ANALYSES_DIR.iterdir():
        report = d / "_report_final.json"
        if not report.exists():
            continue
        try:
            data = json.loads(report.read_text())
            results.append({
                "dir": d.name,
                "title": data.get("article_title", ""),
                "url": data.get("article_url", ""),
                "title_norm": normalise(data.get("article_title", "")),
                "on_site": False,
                "in_db": False,
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def check_url(url: str, processed: list[dict]) -> str | None:
    """Check if URL matches any processed article."""
    url_clean = url.rstrip("/").lower()
    for p in processed:
        if p["url"] and p["url"].rstrip("/").lower() == url_clean:
            return p["dir"]
    # Partial match (same path, different domain params)
    for p in processed:
        if p["url"] and url_clean in p["url"].lower():
            return p["dir"]
    return None


def check_title(title: str, processed: list[dict]) -> str | None:
    """Check if title matches any processed article (fuzzy)."""
    title_norm = normalise(title)
    if not title_norm:
        return None
    for p in processed:
        if p["title_norm"] == title_norm:
            return p["dir"]
    # Substring match (one contains the other)
    for p in processed:
        if title_norm in p["title_norm"] or p["title_norm"] in title_norm:
            if len(title_norm) > 10 and len(p["title_norm"]) > 10:
                return p["dir"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Check for duplicate analyses")
    parser.add_argument("--url", help="Article URL to check")
    parser.add_argument("--title", help="Article title to check")
    parser.add_argument("--frettasafn-id", help="Fréttasafn article ID")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild article registry before checking",
    )
    args = parser.parse_args()

    if args.rebuild:
        from build_article_registry import build_registry

        registry = build_registry()
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY_PATH.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False, default=str)
        )
        print(f"Registry rebuilt: {len(registry)} articles", file=sys.stderr)

    if not any([args.url, args.title, args.frettasafn_id]):
        if args.rebuild:
            sys.exit(0)
        parser.error("Provide --url, --title, or --frettasafn-id")

    processed = load_processed()

    if args.url:
        match = check_url(args.url, processed)
        if match:
            print(f"DUPLICATE: Already processed → {match}")
            sys.exit(0)

    if args.title:
        match = check_title(args.title, processed)
        if match:
            print(f"DUPLICATE: Already processed → {match} (title match)")
            sys.exit(0)

    if args.frettasafn_id:
        if ANALYSES_DIR.exists():
            for d in ANALYSES_DIR.iterdir():
                article = d / "_article.md"
                if article.exists():
                    text = article.read_text()[:500]
                    if args.frettasafn_id in text:
                        print(
                            f"DUPLICATE: Already analysed in {d.name} (fréttasafn ID)"
                        )
                        sys.exit(0)

    print("NOT FOUND: Article has not been processed yet")
    sys.exit(1)


if __name__ == "__main__":
    main()
