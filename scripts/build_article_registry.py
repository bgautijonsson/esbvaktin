"""Build a unified article registry from all sources of processed articles.

Merges three sources:
  1. data/analyses/*/_report_final.json (local work dirs)
  2. ~/esbvaktin-site/_data/reports/*.json (site reports)
  3. DB claim_sightings table (PostgreSQL)

Writes data/article_registry.json — the single source of truth for dedup.

Usage:
    uv run python scripts/build_article_registry.py          # Build registry
    uv run python scripts/build_article_registry.py --check URL  # Check a URL
    uv run python scripts/build_article_registry.py --status  # Show summary
"""

import argparse
import json
import sys
from pathlib import Path

ANALYSES_DIR = Path("data/analyses")
SITE_REPORTS_DIR = Path.home() / "esbvaktin-site" / "_data" / "reports"
REGISTRY_PATH = Path("data/article_registry.json")



def _normalise_url(url: str) -> str:
    """Normalise URL for comparison."""
    return url.rstrip("/").lower()


def _load_analyses() -> dict[str, dict]:
    """Load processed articles from data/analyses/ work dirs."""
    entries: dict[str, dict] = {}
    if not ANALYSES_DIR.exists():
        return entries
    for d in ANALYSES_DIR.iterdir():
        report = d / "_report_final.json"
        if not report.exists():
            continue
        try:
            data = json.loads(report.read_text())
            url = data.get("article_url", "")
            if not url:
                continue
            key = _normalise_url(url)
            entries[key] = {
                "url": url,
                "title": data.get("article_title", ""),
                "slug": data.get("slug", ""),
                "source": data.get("article_source", ""),
                "date": data.get("article_date", ""),
                "analysis_dir": d.name,
            }
        except (json.JSONDecodeError, KeyError):
            continue
    return entries


def _load_site_reports() -> dict[str, dict]:
    """Load processed articles from site report JSONs."""
    entries: dict[str, dict] = {}
    if not SITE_REPORTS_DIR.exists():
        return entries
    for f in SITE_REPORTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            url = data.get("article_url", "")
            if not url:
                continue
            key = _normalise_url(url)
            entries[key] = {
                "url": url,
                "title": data.get("article_title", ""),
                "slug": data.get("slug", f.stem),
                "source": data.get("article_source", ""),
                "date": data.get("article_date", ""),
            }
        except (json.JSONDecodeError, KeyError):
            continue
    return entries


def _load_db_sightings() -> dict[str, dict]:
    """Load distinct source URLs from claim_sightings table."""
    entries: dict[str, dict] = {}
    try:
        from esbvaktin.ground_truth.operations import get_connection

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT source_url, source_title, source_date "
            "FROM claim_sightings ORDER BY source_url"
        )
        for url, title, sdate in cur.fetchall():
            if not url:
                continue
            key = _normalise_url(url)
            entries[key] = {
                "url": url,
                "title": title or "",
                "date": str(sdate) if sdate else "",
            }
        conn.close()
    except Exception as e:
        print(f"Warning: could not read DB claim_sightings: {e}", file=sys.stderr)
    return entries


def build_registry() -> list[dict]:
    """Merge all sources into a unified registry."""
    analyses = _load_analyses()
    site = _load_site_reports()
    db = _load_db_sightings()

    # Collect all unique URLs
    all_keys = set(analyses) | set(site) | set(db)
    registry = []

    for key in sorted(all_keys):
        a = analyses.get(key, {})
        s = site.get(key, {})
        d = db.get(key, {})

        # Merge: prefer site data, then analyses, then DB
        entry = {
            "url": s.get("url") or a.get("url") or d.get("url", ""),
            "title": s.get("title") or a.get("title") or d.get("title", ""),
            "slug": s.get("slug") or a.get("slug", ""),
            "source": s.get("source") or a.get("source", ""),
            "date": s.get("date") or a.get("date") or d.get("date", ""),
            "analysis_dir": a.get("analysis_dir", ""),
            "in_analyses": key in analyses,
            "on_site": key in site,
            "in_db": key in db,
        }
        registry.append(entry)

    return registry


def check_url(url: str, registry: list[dict]) -> dict | None:
    """Check if a URL is in the registry."""
    key = _normalise_url(url)
    for entry in registry:
        if _normalise_url(entry["url"]) == key:
            return entry
    # Partial match
    for entry in registry:
        entry_key = _normalise_url(entry["url"])
        if key in entry_key or entry_key in key:
            return entry
    return None


def main():
    parser = argparse.ArgumentParser(description="Build unified article registry")
    parser.add_argument("--check", metavar="URL", help="Check if a URL is processed")
    parser.add_argument("--status", action="store_true", help="Show registry summary")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Don't write registry file (dry run)",
    )
    args = parser.parse_args()

    registry = build_registry()

    if not args.no_write:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY_PATH.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False, default=str)
        )

    if args.check:
        match = check_url(args.check, registry)
        if match:
            print(f"FOUND: {match['title']}")
            print(f"  slug: {match['slug']}")
            print(f"  in_analyses: {match['in_analyses']}")
            print(f"  on_site: {match['on_site']}")
            print(f"  in_db: {match['in_db']}")
            sys.exit(0)
        else:
            print("NOT FOUND: Article has not been processed")
            sys.exit(1)
    elif args.status:
        in_analyses = sum(1 for e in registry if e["in_analyses"])
        on_site = sum(1 for e in registry if e["on_site"])
        in_db = sum(1 for e in registry if e["in_db"])
        all_three = sum(
            1
            for e in registry
            if e["in_analyses"] and e["on_site"] and e["in_db"]
        )
        print(f"Total unique articles: {len(registry)}")
        print(f"  in data/analyses/:   {in_analyses}")
        print(f"  on site:             {on_site}")
        print(f"  in DB sightings:     {in_db}")
        print(f"  in all three:        {all_three}")

        # Show gaps
        site_only = [
            e for e in registry if e["on_site"] and not e["in_analyses"]
        ]
        if site_only:
            print(f"\nOn site but missing local analysis dir ({len(site_only)}):")
            for e in site_only:
                print(f"  {e['title'][:60]}")

        no_db = [e for e in registry if not e["in_db"]]
        if no_db:
            print(f"\nNot in DB sightings ({len(no_db)}):")
            for e in no_db:
                print(f"  {e['title'][:60]}")
    else:
        print(f"Registry built: {len(registry)} articles → {REGISTRY_PATH}")


if __name__ == "__main__":
    main()
