"""Export merged entity data from per-analysis _entities.json files.

Reads all data/analyses/*/_entities.json files, merges entities by name,
and produces a site-ready entities.json.

Usage:
    uv run python scripts/export_entities.py
    uv run python scripts/export_entities.py --site-dir ~/esbvaktin-site
    uv run python scripts/export_entities.py --status
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"
EXPORT_DIR = PROJECT_ROOT / "data" / "export"
DEFAULT_SITE_DIR = PROJECT_ROOT.parent / "esbvaktin-site"


def icelandic_slugify(text: str) -> str:
    """Create a URL-safe slug from Icelandic text."""
    replacements = {
        "þ": "th", "Þ": "th",
        "ð": "d", "Ð": "d",
        "æ": "ae", "Æ": "ae",
        "ö": "o", "Ö": "o",
        "á": "a", "Á": "a",
        "é": "e", "É": "e",
        "í": "i", "Í": "i",
        "ó": "o", "Ó": "o",
        "ú": "u", "Ú": "u",
        "ý": "y", "Ý": "y",
    }
    slug = text
    for orig, repl in replacements.items():
        slug = slug.replace(orig, repl)
    slug = unicodedata.normalize("NFKD", slug)
    slug = slug.encode("ascii", "ignore").decode("ascii")
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def _get_report_slug(report_path: Path) -> str:
    """Get the report slug from _report_final.json."""
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    title = report.get("article_title", report_path.parent.name)
    return icelandic_slugify(title)


def _get_claim_slugs(report_path: Path) -> list[str]:
    """Get claim slugs from a report (using claim_text as identifier)."""
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    slugs = []
    for item in report.get("claims", []):
        claim = item.get("claim", item)
        text = claim.get("claim_text", "")
        slugs.append(icelandic_slugify(text[:80]))
    return slugs


def load_all_entities() -> dict[str, dict]:
    """Load and merge entity data from all analyses.

    Returns a dict keyed by entity slug with merged data.
    """
    entities: dict[str, dict] = {}

    for analysis_dir in sorted(ANALYSES_DIR.iterdir()):
        if not analysis_dir.is_dir():
            continue

        entities_path = analysis_dir / "_entities.json"
        report_path = analysis_dir / "_report_final.json"

        if not entities_path.exists() or not report_path.exists():
            continue

        with open(entities_path, encoding="utf-8") as f:
            raw = json.load(f)

        report_slug = _get_report_slug(report_path)
        claim_slugs = _get_claim_slugs(report_path)

        # Process article author
        author = raw.get("article_author")
        if author and author.get("name"):
            _merge_entity(entities, author, report_slug, claim_slugs)

        # Process all speakers
        for speaker in raw.get("speakers", []):
            if speaker.get("name"):
                _merge_entity(entities, speaker, report_slug, claim_slugs)

    return entities


# Known name aliases — map variant names to canonical slugs
_NAME_ALIASES: dict[str, str] = {
    "bændasamtökin": "baendasamtok-islands",
    "bændasamtök íslands": "baendasamtok-islands",
    "ríkisstjórnin": "rikissjornin",
}

# Entries that are titles/roles, not actual entities — skip these
_SKIP_NAMES = {
    "formaður miðflokksins",
    "formaður sjálfstæðisflokksins",
    "utanríkisráðherra",
    "formenn ríkisstjórnarflokkanna",
}


def _merge_entity(
    entities: dict[str, dict],
    speaker: dict,
    report_slug: str,
    claim_slugs: list[str],
) -> None:
    """Merge a speaker into the entities dict, deduplicating by slug."""
    name = speaker["name"]

    # Skip title-based entries
    if name.lower() in _SKIP_NAMES:
        return

    # Apply name aliases
    slug = _NAME_ALIASES.get(name.lower(), icelandic_slugify(name))

    if slug not in entities:
        entities[slug] = {
            "slug": slug,
            "name": name,
            "type": speaker.get("type", "individual"),
            "description": "",
            "stance": speaker.get("stance", "neutral"),
            "role": speaker.get("role"),
            "party": speaker.get("party"),
            "mention_count": 0,
            "articles": [],
            "claims": [],
        }

    entity = entities[slug]

    # Update with richer data if available
    if speaker.get("role") and not entity.get("role"):
        entity["role"] = speaker["role"]
    if speaker.get("party") and not entity.get("party"):
        entity["party"] = speaker["party"]

    # Add article reference
    if report_slug not in entity["articles"]:
        entity["articles"].append(report_slug)

    # Map claim_indices to claim slugs
    for idx in speaker.get("claim_indices", []):
        if 0 <= idx < len(claim_slugs):
            cs = claim_slugs[idx]
            if cs not in entity["claims"]:
                entity["claims"].append(cs)

    # Update mention count (count of articles)
    entity["mention_count"] = len(entity["articles"])


def _generate_descriptions(entities: dict[str, dict]) -> None:
    """Generate basic Icelandic descriptions for entities that lack one."""
    type_labels = {
        "individual": "Einstaklingur",
        "party": "Stjórnmálaflokkur",
        "institution": "Stofnun",
        "union": "Samtök",
    }
    stance_labels = {
        "pro_eu": "hlynnt ESB-aðild",
        "anti_eu": "andvíg/ur ESB-aðild",
        "mixed": "blandað viðhorf til ESB-aðildar",
        "neutral": "hlutlaus um ESB-aðild",
    }

    for entity in entities.values():
        if entity.get("description"):
            continue

        parts = []
        type_label = type_labels.get(entity["type"], "")

        if entity["type"] == "individual":
            if entity.get("role"):
                parts.append(entity["role"].capitalize())
            if entity.get("party"):
                parts.append(f"({entity['party']})")
        else:
            if type_label:
                parts.append(type_label)

        stance_desc = stance_labels.get(entity["stance"], "")
        if stance_desc:
            if parts:
                parts.append(f"— {stance_desc}.")
            else:
                parts.append(stance_desc.capitalize() + ".")

        entity["description"] = " ".join(parts) if parts else ""


def export_entities(site_dir: Path | None = None) -> list[dict]:
    """Export merged entities to JSON files."""
    entities = load_all_entities()
    _generate_descriptions(entities)

    # Sort by mention count (descending), then name
    sorted_entities = sorted(
        entities.values(),
        key=lambda e: (-e["mention_count"], e["name"]),
    )

    # Export to data/export/
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = EXPORT_DIR / "entities.json"
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(sorted_entities, f, ensure_ascii=False, indent=2)
    print(f"Exported {len(sorted_entities)} entities to {export_path}")

    # Export to site _data/ if available
    if site_dir and site_dir.exists():
        site_path = site_dir / "_data" / "entities.json"
        with open(site_path, "w", encoding="utf-8") as f:
            json.dump(sorted_entities, f, ensure_ascii=False, indent=2)
        print(f"Copied to {site_path}")

    # Print summary
    by_type: dict[str, int] = {}
    by_stance: dict[str, int] = {}
    for e in sorted_entities:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        by_stance[e["stance"]] = by_stance.get(e["stance"], 0) + 1

    print(f"\nBy type: {by_type}")
    print(f"By stance: {by_stance}")
    print(f"Total articles covered: {len({a for e in sorted_entities for a in e['articles']})}")

    return sorted_entities


def main() -> None:
    if "--status" in sys.argv:
        entities = load_all_entities()
        print(f"Found {len(entities)} unique entities across analyses")
        for slug, e in sorted(entities.items(), key=lambda x: -x[1]["mention_count"]):
            print(f"  {e['name']} ({e['type']}, {e['stance']}) — {e['mention_count']} articles")
        return

    site_dir = (
        Path(sys.argv[sys.argv.index("--site-dir") + 1])
        if "--site-dir" in sys.argv
        else DEFAULT_SITE_DIR
    )

    export_entities(site_dir)


if __name__ == "__main__":
    main()
