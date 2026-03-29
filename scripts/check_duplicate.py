"""Check if an article has already been analysed.

Uses the unified article registry (data/article_registry.json) which merges
data/analyses/, site reports, and DB claim_sightings. Falls back to scanning
data/analyses/ directly if the registry doesn't exist.

Supports three matching strategies:
1. URL match (exact full-URL + path equality via urlparse — no substring)
2. Title match (exact + SequenceMatcher ratio >= 0.85)
3. Content match (body text similarity — catches cross-publication reposts
   where the same article appears on a news site and a party/blog site
   with a different title)

Usage:
    uv run python scripts/check_duplicate.py --url URL
    uv run python scripts/check_duplicate.py --title "Article Title"
    uv run python scripts/check_duplicate.py --text "Article body text..."
    uv run python scripts/check_duplicate.py --text-file path/to/article.md
    uv run python scripts/check_duplicate.py --frettasafn-id ARTICLE_ID
    uv run python scripts/check_duplicate.py --rebuild  # Rebuild registry first

Exit codes: 0 = duplicate found, 1 = not found, 2 = error
"""

import argparse
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

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
            age_hours = (time.time() - REGISTRY_PATH.stat().st_mtime) / 3600
            if age_hours > 24:
                print(
                    f"WARNING: article_registry.json is {age_hours:.0f}h old — "
                    f"run: uv run python scripts/build_article_registry.py",
                    file=sys.stderr,
                )
            for entry in registry:
                results.append(
                    {
                        "dir": entry.get("analysis_dir", entry.get("slug", "")),
                        "title": entry.get("title", ""),
                        "url": entry.get("url", ""),
                        "title_norm": normalise(entry.get("title", "")),
                        "on_site": entry.get("on_site", False),
                        "in_db": entry.get("in_db", False),
                    }
                )
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
            results.append(
                {
                    "dir": d.name,
                    "title": data.get("article_title", ""),
                    "url": data.get("article_url", ""),
                    "title_norm": normalise(data.get("article_title", "")),
                    "on_site": False,
                    "in_db": False,
                }
            )
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def _normalise_url_path(url: str) -> str:
    """Return netloc + path, lowercased and with trailing slash stripped."""
    parsed = urlparse(url.lower().strip())
    return parsed.netloc + parsed.path.rstrip("/")


def check_url(url: str, processed: list[dict]) -> str | None:
    """Check if URL matches any processed article."""
    url_clean = url.rstrip("/").lower()
    # Exact full-URL match first
    for p in processed:
        if p["url"] and p["url"].rstrip("/").lower() == url_clean:
            return p["dir"]
    # Path equality match (same netloc + path, ignoring query/fragment)
    url_path = _normalise_url_path(url)
    for p in processed:
        if p["url"] and _normalise_url_path(p["url"]) == url_path:
            return p["dir"]
    return None


def check_title(title: str, processed: list[dict]) -> tuple[str | None, float]:
    """Check if title matches any processed article (fuzzy).

    Returns (dir, ratio) where ratio is 1.0 for exact matches and the
    SequenceMatcher ratio for fuzzy matches. Returns (None, 0.0) if no match.
    """
    title_norm = normalise(title)
    if not title_norm:
        return None, 0.0
    for p in processed:
        if p["title_norm"] == title_norm:
            return p["dir"], 1.0
    # Fuzzy ratio match (>= 0.85 catches near-identical titles)
    for p in processed:
        if not p["title_norm"]:
            continue
        ratio = SequenceMatcher(None, title_norm, p["title_norm"]).ratio()
        if ratio >= 0.85:
            return p["dir"], ratio
    return None, 0.0


_META_PREFIXES = (
    "# ",  # Markdown title
    "**source:**",  # Fréttasafn metadata
    "**words:**",  # Pipeline word count
    "**date:**",  # Pipeline date
    "source:",  # Plain metadata
    "url:",  # Plain URL
    "article_id:",  # Fréttasafn ID
    "höfundur:",  # Icelandic "Author:"
    "dagsetning:",  # Icelandic "Date:"
    "heimild:",  # Icelandic "Source:"
)


def _strip_metadata_header(text: str) -> str:
    """Strip metadata headers from article text, keeping only body content.

    Articles are fetched via different paths (trafilatura, fréttasafn MCP,
    direct paste) and have different header formats. Strips all metadata-like
    lines from the first 15 lines regardless of position, then returns the rest.
    """
    lines = text.splitlines()
    body_lines = []
    header_zone = True

    for i, line in enumerate(lines):
        stripped = line.strip().lower()

        # After 15 lines, stop filtering — we're in the body
        if i >= 15:
            header_zone = False

        if header_zone:
            if not stripped:
                continue
            if any(stripped.startswith(p) for p in _META_PREFIXES):
                continue
            # **Bold** | date lines (fréttasafn format)
            if stripped.startswith("**") and "|" in stripped:
                continue
            # Short lines that look like dates or bylines (< 60 chars, no sentence structure)
            if len(stripped) < 60 and not stripped.endswith("."):
                # Could be a title or byline — skip it
                continue
            # First substantial line: end header zone
            header_zone = False

        body_lines.append(line)

    return "\n".join(body_lines).strip()


# Characters to compare for content matching. Enough to catch reposts
# without being expensive. Most cross-publication reposts are identical
# after the first paragraph.
_CONTENT_COMPARE_CHARS = 800

# Similarity threshold for content matching. 0.85 catches reposts with
# minor edits (source attribution, formatting) while avoiding false
# positives from articles on the same topic.
_CONTENT_SIMILARITY_THRESHOLD = 0.85


def _extract_body(text: str) -> str:
    """Extract article body, aggressively skipping all header/metadata formats.

    Uses a two-pass approach:
    1. Strip known metadata lines
    2. Find the first "long sentence" (>80 chars ending in period/question/exclamation)
       and start from there — this reliably skips titles and bylines
    """
    stripped = _strip_metadata_header(text)
    # Find first sentence-like line (body content, not a title or byline)
    for i, line in enumerate(stripped.splitlines()):
        s = line.strip()
        if len(s) > 80 and s[-1] in ".?!":
            return "\n".join(stripped.splitlines()[i:]).strip()
    # Fallback: use everything after header strip
    return stripped


def check_content(
    text: str,
    processed: list[dict],
    threshold: float = _CONTENT_SIMILARITY_THRESHOLD,
) -> tuple[str | None, float]:
    """Check if article body text matches any already-analysed article.

    Compares the body text (after stripping metadata and headers) against
    _article.md files in analysis directories. Returns (dir, similarity)
    if a match is found above the threshold, else (None, 0).
    """
    # Check for explicit cross-publication footer (e.g., "Birtist fyrst á visir.is")
    footer_match = re.search(
        r"[Bb]irtist fyrst (?:á|í|hjá|í)\s+(\S+\.(?:is|com|net))",
        text[-500:] if len(text) > 500 else text,
    )
    if footer_match:
        canonical_source = footer_match.group(1).lower()
        for p in processed:
            if canonical_source in p.get("url", "").lower():
                return p["url"], 1.0  # Perfect match — explicit repost attribution

    candidate = _extract_body(text)[:_CONTENT_COMPARE_CHARS]
    if len(candidate) < 100:
        return None, 0.0

    best_match = None
    best_ratio = 0.0

    for p in processed:
        analysis_dir = p.get("dir", "")
        if not analysis_dir:
            continue
        article_path = ANALYSES_DIR / analysis_dir / "_article.md"
        if not article_path.exists():
            continue
        try:
            existing = _extract_body(article_path.read_text()[: _CONTENT_COMPARE_CHARS + 1000])[
                :_CONTENT_COMPARE_CHARS
            ]
        except OSError:
            continue

        ratio = SequenceMatcher(None, candidate, existing).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = analysis_dir

    if best_ratio >= threshold:
        return best_match, best_ratio
    return None, best_ratio


def main():
    parser = argparse.ArgumentParser(description="Check for duplicate analyses")
    parser.add_argument("--url", help="Article URL to check")
    parser.add_argument("--title", help="Article title to check")
    parser.add_argument("--text", help="Article body text to compare")
    parser.add_argument("--text-file", help="Path to article text file to compare")
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
        REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False, default=str))
        print(f"Registry rebuilt: {len(registry)} articles", file=sys.stderr)

    if not any([args.url, args.title, args.text, args.text_file, args.frettasafn_id]):
        if args.rebuild:
            sys.exit(0)
        parser.error("Provide --url, --title, --text, --text-file, or --frettasafn-id")

    processed = load_processed()

    if args.url:
        match = check_url(args.url, processed)
        if match:
            print(f"DUPLICATE: Already processed → {match}")
            sys.exit(0)

    if args.title:
        match, ratio = check_title(args.title, processed)
        if match:
            print(f"DUPLICATE: Already processed → {match} (title match, {ratio:.0%})")
            sys.exit(0)

    # Content-based dedup: catches cross-publication reposts
    text_to_check = args.text
    if not text_to_check and args.text_file:
        try:
            text_to_check = Path(args.text_file).read_text()
        except OSError as e:
            print(f"ERROR: Cannot read {args.text_file}: {e}", file=sys.stderr)
            sys.exit(2)

    if text_to_check:
        match, similarity = check_content(text_to_check, processed)
        if match:
            print(f"DUPLICATE: Content match ({similarity:.0%} similar) → {match}")
            sys.exit(0)

    if args.frettasafn_id:
        if ANALYSES_DIR.exists():
            for d in ANALYSES_DIR.iterdir():
                article = d / "_article.md"
                if article.exists():
                    text = article.read_text()[:500]
                    if args.frettasafn_id in text:
                        print(f"DUPLICATE: Already analysed in {d.name} (fréttasafn ID)")
                        sys.exit(0)

    print("NOT FOUND: Article has not been processed yet")
    sys.exit(1)


if __name__ == "__main__":
    main()
