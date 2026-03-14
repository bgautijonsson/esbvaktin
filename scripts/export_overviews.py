"""Export weekly overview data and editorials to site-ready JSON.

Reads pre-generated data.json + editorial.md from data/overviews/{slug}/
and produces a listing JSON and per-overview detail files for the site.

No DB access required — purely file-based.

Usage:
    uv run python scripts/export_overviews.py --site-dir ~/esbvaktin-site  # Export + copy to site
    uv run python scripts/export_overviews.py              # Export to data/export/ only
    uv run python scripts/export_overviews.py --status     # Show overview coverage
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OVERVIEWS_DIR = PROJECT_ROOT / "data" / "overviews"
EXPORT_DIR = PROJECT_ROOT / "data" / "export"

# Import icelandic_slugify from export_entities for entity slug resolution
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from export_entities import icelandic_slugify  # noqa: E402


def _load_overview(slug_dir: Path) -> dict | None:
    """Load data.json and editorial.md from an overview directory.

    Returns merged dict or None if essential files are missing.
    """
    data_path = slug_dir / "data.json"
    editorial_path = slug_dir / "editorial.md"

    if not data_path.exists():
        return None

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    editorial = ""
    if editorial_path.exists():
        editorial = editorial_path.read_text(encoding="utf-8").strip()

    data["editorial"] = editorial
    data["slug"] = slug_dir.name
    return data


def _editorial_excerpt(editorial: str, max_chars: int = 150) -> str:
    """Extract first ~150 chars of editorial body text (skip the heading)."""
    lines = editorial.strip().splitlines()
    body_lines = []
    for line in lines:
        # Skip headings and blank lines at the start
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        body_lines.append(stripped)

    body = " ".join(body_lines)
    if len(body) <= max_chars:
        return body
    # Cut at word boundary
    truncated = body[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.6:
        truncated = truncated[:last_space]
    return truncated + "…"


def _build_listing_entry(data: dict) -> dict:
    """Build a compact listing entry from full overview data."""
    kn = data.get("key_numbers", {})
    topic_activity = data.get("topic_activity", [])

    # Top topics by sighting count (slugs, not labels)
    top_topics = [t["topic"] for t in topic_activity[:3]]

    return {
        "slug": data["slug"],
        "period_start": data["period_start"],
        "period_end": data["period_end"],
        "period_type": data.get("period_type", "weekly"),
        "articles_analysed": kn.get("articles_analysed", 0),
        "new_claims": kn.get("new_claims", 0),
        "new_claims_published": kn.get("new_claims_published", 0),
        "diversity_score": kn.get("diversity_score", 0.0),
        "top_topics": top_topics,
        "editorial_excerpt": _editorial_excerpt(data.get("editorial", "")),
    }


def _load_entity_names() -> set[str]:
    """Load known entity names from the entities export (if available)."""
    entities_path = EXPORT_DIR / "entities.json"
    if not entities_path.exists():
        return set()
    with open(entities_path, encoding="utf-8") as f:
        entities = json.load(f)
    return {e["name"] for e in entities if "name" in e}


def _enrich_key_facts(facts: list[dict]) -> list[dict]:
    """Normalise category to hyphens for key facts."""
    enriched = []
    for f in facts:
        entry = {**f}
        if "category" in entry:
            entry["category"] = entry["category"].replace("_", "-")
        enriched.append(entry)
    return enriched


def _enrich_top_claims(claims: list[dict]) -> list[dict]:
    """Normalise category to hyphens and convert sources to objects."""
    enriched = []
    for c in claims:
        entry = {**c}
        # #4: normalise category to hyphens
        if "category" in entry:
            entry["category"] = entry["category"].replace("_", "-")
        # #3: convert sources from strings to {title, slug} objects
        raw_sources = c.get("sources", [])
        entry["sources"] = [
            {"title": s, "slug": icelandic_slugify(s)}
            for s in raw_sources
        ]
        enriched.append(entry)
    return enriched


def _build_detail(data: dict, known_entities: set[str] | None = None) -> dict:
    """Build per-overview detail JSON with resolved slugs for site linking."""
    if known_entities is None:
        known_entities = _load_entity_names()

    # Resolve entity slugs for linking to /raddirnar/ pages
    active_entities = []
    for entity in data.get("active_entities", []):
        active_entities.append({
            **entity,
            "slug": icelandic_slugify(entity["name"]),
        })

    # Resolve topic slugs for linking to /efni/ pages
    topic_activity = []
    for topic in data.get("topic_activity", []):
        topic_activity.append({
            **topic,
            "slug": topic["topic"].replace("_", "-"),
        })

    return {
        "slug": data["slug"],
        "period_start": data["period_start"],
        "period_end": data["period_end"],
        "period_type": data.get("period_type", "weekly"),
        "key_numbers": data.get("key_numbers", {}),
        "previous_period": data.get("previous_period", {}),
        "topic_activity": topic_activity,
        "top_claims": _enrich_top_claims(data.get("top_claims", [])),
        "active_entities": active_entities,
        "articles": [
            {**art, "slug": icelandic_slugify(art["title"])}
            for art in data.get("articles", [])
        ],
        "source_breakdown": data.get("source_breakdown", {}),
        "key_facts": _enrich_key_facts(data.get("key_facts", [])),
        "editorial": data.get("editorial", ""),
    }


def build_overviews() -> tuple[list[dict], dict[str, dict]]:
    """Build overviews.json listing and per-overview detail files.

    Returns (listing, details_dict) where details_dict is keyed by slug.
    """
    if not OVERVIEWS_DIR.exists():
        return [], {}

    known_entities = _load_entity_names()
    listing = []
    details = {}

    for slug_dir in sorted(OVERVIEWS_DIR.iterdir()):
        if not slug_dir.is_dir():
            continue

        data = _load_overview(slug_dir)
        if data is None:
            continue

        listing.append(_build_listing_entry(data))
        details[data["slug"]] = _build_detail(data, known_entities)

    # Sort by period_start descending (newest first)
    listing.sort(key=lambda o: o["period_start"], reverse=True)

    return listing, details


def _show_status() -> None:
    """Show overview export coverage."""
    if not OVERVIEWS_DIR.exists():
        print("No overviews directory found.")
        return

    print(f"{'Slug':<15} {'Period':>25} {'Articles':>10} {'Claims':>8} {'Editorial':>10}")
    print("-" * 72)

    total = 0
    with_editorial = 0

    for slug_dir in sorted(OVERVIEWS_DIR.iterdir()):
        if not slug_dir.is_dir():
            continue

        data = _load_overview(slug_dir)
        if data is None:
            print(f"{slug_dir.name:<15} {'(no data.json)':>25}")
            continue

        total += 1
        kn = data.get("key_numbers", {})
        has_editorial = bool(data.get("editorial", "").strip())
        if has_editorial:
            with_editorial += 1

        period = f"{data['period_start']} → {data['period_end']}"
        editorial_status = "yes" if has_editorial else "—"

        print(
            f"{data['slug']:<15} {period:>25} "
            f"{kn.get('articles_analysed', 0):>10} "
            f"{kn.get('new_claims', 0):>8} "
            f"{editorial_status:>10}"
        )

    print("-" * 72)
    print(f"Total: {total} overviews ({with_editorial} with editorial)")


def _write_json(path: Path, data) -> None:
    """Write JSON with utf-8 encoding and 2-space indent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_site_dir() -> Path | None:
    """Parse --site-dir argument."""
    if "--site-dir" in sys.argv:
        idx = sys.argv.index("--site-dir")
        if idx + 1 < len(sys.argv):
            return Path(sys.argv[idx + 1]).expanduser()
    return None


def main() -> None:
    status_only = "--status" in sys.argv
    site_dir = _parse_site_dir()

    if status_only:
        _show_status()
        return

    listing, details = build_overviews()

    if not listing:
        print("No overviews found in data/overviews/. Run generate_overview.py first.")
        return

    # Write listing
    listing_path = EXPORT_DIR / "overviews.json"
    _write_json(listing_path, listing)

    # Write detail files
    details_dir = EXPORT_DIR / "overviews"
    details_dir.mkdir(parents=True, exist_ok=True)
    for slug, detail in details.items():
        _write_json(details_dir / f"{slug}.json", detail)

    print(f"Exported {len(listing)} overviews to {listing_path}")
    print(f"Exported {len(details)} overview details to {details_dir}")

    # Copy to site repo if --site-dir provided
    if site_dir:
        import shutil

        # Listing → assets/data/overviews.json
        site_listing = site_dir / "assets" / "data" / "overviews.json"
        site_listing.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(listing_path, site_listing)
        print(f"  {site_listing}")

        # Details → _data/overviews/*.json
        site_details = site_dir / "_data" / "overviews"
        site_details.mkdir(parents=True, exist_ok=True)
        for slug, detail in details.items():
            _write_json(site_details / f"{slug}.json", detail)
        print(f"  {len(details)} detail files → {site_details}")

    # Summary
    total_articles = sum(o["articles_analysed"] for o in listing)
    total_claims = sum(o["new_claims"] for o in listing)
    with_editorial = sum(1 for d in details.values() if d.get("editorial", "").strip())
    print(f"\n{len(listing)} overviews, {total_articles} articles, {total_claims} claims")
    print(f"{with_editorial} with editorial content")


if __name__ == "__main__":
    main()
