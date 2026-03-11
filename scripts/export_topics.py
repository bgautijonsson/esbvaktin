"""Export per-topic aggregations from PostgreSQL to JSON for the site.

Aggregates claims, sightings, entities, and evidence by topic (KNOWN_TOPICS).
Produces a listing JSON and 12 detail files (one per topic).

Usage:
    uv run python scripts/export_topics.py --site-dir ~/esbvaktin-site  # Export + copy to site
    uv run python scripts/export_topics.py              # Export to data/export/ only
    uv run python scripts/export_topics.py --status     # Show topic distribution table
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from esbvaktin.pipeline.models import TOPIC_LABELS_IS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = PROJECT_ROOT / "data" / "export"

# Import icelandic_slugify from export_entities to avoid duplication
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from export_entities import icelandic_slugify  # noqa: E402


def _get_connection():
    """Get a psycopg connection using standard project config."""
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")

    import psycopg

    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="esbvaktin",
        user="esb",
        password="localdev",
    )


def _domain_from_url(url: str | None) -> str | None:
    """Extract domain from a URL, stripping www. prefix."""
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


def diversity_score(topic_counts: dict[str, int]) -> float:
    """Shannon entropy normalised to [0,1]. 1 = perfectly diverse, 0 = single-topic."""
    total = sum(topic_counts.values())
    if total == 0:
        return 0.0
    n_topics = len(topic_counts)
    if n_topics <= 1:
        return 0.0
    entropy = -sum(
        (c / total) * math.log2(c / total)
        for c in topic_counts.values() if c > 0
    )
    max_entropy = math.log2(n_topics)
    return round(entropy / max_entropy, 4) if max_entropy > 0 else 0.0


def _fetch_verdict_breakdown(conn) -> dict[str, dict[str, int]]:
    """Per-topic verdict counts for published claims."""
    rows = conn.execute("""
        SELECT c.category, c.verdict, COUNT(*) AS n
        FROM claims c WHERE c.published = TRUE
        GROUP BY c.category, c.verdict
    """).fetchall()

    result: dict[str, dict[str, int]] = defaultdict(dict)
    for category, verdict, n in rows:
        result[category][verdict] = n
    return dict(result)


def _fetch_claim_counts(conn) -> dict[str, dict]:
    """Per-topic total and published claim counts."""
    rows = conn.execute("""
        SELECT c.category,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE c.published = TRUE) AS published
        FROM claims c
        GROUP BY c.category
    """).fetchall()

    return {cat: {"total": total, "published": pub} for cat, total, pub in rows}


def _fetch_sighting_counts(conn) -> dict[str, int]:
    """Per-topic sighting counts (published claims only)."""
    rows = conn.execute("""
        SELECT c.category, COUNT(*) AS n
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE
        GROUP BY c.category
    """).fetchall()

    return {cat: n for cat, n in rows}


def _fetch_date_range(conn) -> dict[str, dict]:
    """Per-topic first_seen and last_seen dates from sightings."""
    rows = conn.execute("""
        SELECT c.category,
               MIN(s.source_date) AS first_seen,
               MAX(s.source_date) AS last_seen
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.source_date IS NOT NULL
        GROUP BY c.category
    """).fetchall()

    result = {}
    for cat, first, last in rows:
        result[cat] = {
            "first_seen": first.isoformat() if isinstance(first, (date, datetime)) else first,
            "last_seen": last.isoformat() if isinstance(last, (date, datetime)) else last,
        }
    return result


def _fetch_top_entities(conn) -> dict[str, list[dict]]:
    """Per-topic top entities by sighting mention count."""
    rows = conn.execute("""
        SELECT c.category, s.speaker_name, COUNT(*) AS mentions
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.speaker_name IS NOT NULL
        GROUP BY c.category, s.speaker_name
        ORDER BY c.category, mentions DESC
    """).fetchall()

    result: dict[str, list[dict]] = defaultdict(list)
    for cat, name, mentions in rows:
        result[cat].append({"name": name, "claim_count": mentions})

    # Keep top 10 per topic
    return {cat: entities[:10] for cat, entities in result.items()}


def _fetch_source_breakdown(conn) -> dict[str, dict[str, int]]:
    """Per-topic source domain breakdown (distinct articles)."""
    rows = conn.execute("""
        SELECT c.category,
               s.source_url,
               COUNT(DISTINCT s.source_url) AS articles
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.source_url IS NOT NULL
        GROUP BY c.category, s.source_url
    """).fetchall()

    # Aggregate by domain
    result: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for cat, url, _articles in rows:
        domain = _domain_from_url(url)
        if domain:
            result[cat][domain] += 1

    return {cat: dict(domains) for cat, domains in result.items()}


def _fetch_weekly_timeline(conn) -> dict[str, list[dict]]:
    """Per-topic weekly sighting counts and new claims."""
    sighting_rows = conn.execute("""
        SELECT DATE_TRUNC('week', s.source_date)::date AS week,
               c.category, COUNT(*) AS sightings
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.source_date IS NOT NULL
        GROUP BY week, c.category ORDER BY week
    """).fetchall()

    new_claim_rows = conn.execute("""
        SELECT DATE_TRUNC('week', c.created_at)::date AS week,
               c.category, COUNT(*) AS new_claims
        FROM claims c
        WHERE c.published = TRUE
        GROUP BY week, c.category ORDER BY week
    """).fetchall()

    # Index new claims by (week, category)
    new_claims_idx: dict[tuple, int] = {}
    for week, cat, n in new_claim_rows:
        week_str = week.isoformat() if isinstance(week, (date, datetime)) else week
        new_claims_idx[(week_str, cat)] = n

    result: dict[str, list[dict]] = defaultdict(list)
    for week, cat, sightings in sighting_rows:
        week_str = week.isoformat() if isinstance(week, (date, datetime)) else week
        result[cat].append({
            "week": week_str,
            "sightings": sightings,
            "new_claims": new_claims_idx.get((week_str, cat), 0),
        })

    return dict(result)


def _fetch_evidence_counts(conn) -> dict[str, int]:
    """Per-topic evidence entry counts."""
    rows = conn.execute("""
        SELECT topic, COUNT(*) AS n
        FROM evidence
        GROUP BY topic
    """).fetchall()

    return {topic: n for topic, n in rows}


def _fetch_topic_claims(conn) -> dict[str, list[dict]]:
    """Per-topic published claims with sighting info."""
    rows = conn.execute("""
        SELECT c.claim_slug, c.canonical_text_is, c.verdict, c.category,
               COUNT(s.id) AS sighting_count,
               MAX(s.source_date) AS last_seen
        FROM claims c
        LEFT JOIN claim_sightings s ON c.id = s.claim_id
        WHERE c.published = TRUE
        GROUP BY c.id
        ORDER BY c.category, COUNT(s.id) DESC
    """).fetchall()

    result: dict[str, list[dict]] = defaultdict(list)
    for slug, text_is, verdict, cat, sighting_count, last_seen in rows:
        result[cat].append({
            "claim_slug": slug,
            "canonical_text_is": text_is,
            "verdict": verdict,
            "sighting_count": sighting_count,
            "last_seen": last_seen.isoformat() if isinstance(last_seen, (date, datetime)) else last_seen,
        })

    return dict(result)


def _fetch_topic_claim_speakers(conn) -> dict[str, dict[str, list[str]]]:
    """Per-claim speakers, grouped by topic."""
    rows = conn.execute("""
        SELECT c.category, c.claim_slug, s.speaker_name
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.speaker_name IS NOT NULL
        GROUP BY c.category, c.claim_slug, s.speaker_name
    """).fetchall()

    # topic → claim_slug → [speakers]
    result: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for cat, slug, speaker in rows:
        if speaker not in result[cat][slug]:
            result[cat][slug].append(speaker)

    return {cat: dict(claims) for cat, claims in result.items()}


def _fetch_topic_evidence(conn) -> dict[str, list[dict]]:
    """Per-topic evidence entries (id, statement_is, source_name)."""
    rows = conn.execute("""
        SELECT e.evidence_id, e.statement_is, e.source_name, e.topic
        FROM evidence e
        ORDER BY e.topic, e.evidence_id
    """).fetchall()

    result: dict[str, list[dict]] = defaultdict(list)
    for eid, stmt_is, source_name, topic in rows:
        result[topic].append({
            "evidence_id": eid,
            "statement_is": stmt_is,
            "source_name": source_name,
        })

    return dict(result)


def _fetch_entity_stances(conn) -> dict[str, dict[str, str]]:
    """Speaker name → stance from claim_sightings (most frequent stance wins)."""
    # We don't have stance in sightings, but we can get it from entities.json if available
    # For now, return empty — entity details come from export_entities
    return {}


def _fetch_entity_details_for_topic(conn) -> dict[str, list[dict]]:
    """Per-topic entity details with per-entity verdict breakdown.

    Returns topic → list of {name, slug, claim_count, verdict_breakdown}.
    """
    rows = conn.execute("""
        SELECT c.category, s.speaker_name,
               c.verdict, COUNT(*) AS n
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.speaker_name IS NOT NULL
        GROUP BY c.category, s.speaker_name, c.verdict
        ORDER BY c.category, s.speaker_name
    """).fetchall()

    # Build nested structure
    topic_entities: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
        "name": "", "claim_count": 0, "verdict_breakdown": defaultdict(int)
    }))

    for cat, name, verdict, n in rows:
        entry = topic_entities[cat][name]
        entry["name"] = name
        entry["claim_count"] += n
        entry["verdict_breakdown"][verdict] += n

    result: dict[str, list[dict]] = {}
    for cat, entities in topic_entities.items():
        sorted_entities = sorted(entities.values(), key=lambda e: -e["claim_count"])
        for e in sorted_entities:
            e["slug"] = icelandic_slugify(e["name"])
            e["verdict_breakdown"] = dict(e["verdict_breakdown"])
        result[cat] = sorted_entities[:20]  # Top 20 per topic

    return result


def _fetch_source_activity_for_topic(conn) -> dict[str, list[dict]]:
    """Per-topic source activity: domain, article count, claim count."""
    rows = conn.execute("""
        SELECT c.category, s.source_url, COUNT(*) AS claim_count
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.source_url IS NOT NULL
        GROUP BY c.category, s.source_url
    """).fetchall()

    # Aggregate by domain per topic
    topic_sources: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(
        lambda: {"articles": set(), "claims": 0}
    ))
    for cat, url, claim_count in rows:
        domain = _domain_from_url(url)
        if domain:
            topic_sources[cat][domain]["articles"].add(url)
            topic_sources[cat][domain]["claims"] += claim_count

    result: dict[str, list[dict]] = {}
    for cat, domains in topic_sources.items():
        source_list = [
            {"source": domain, "articles": len(data["articles"]), "claims": data["claims"]}
            for domain, data in domains.items()
        ]
        source_list.sort(key=lambda s: -s["claims"])
        result[cat] = source_list

    return result


def build_topics(conn) -> tuple[list[dict], dict[str, dict]]:
    """Build topics.json listing and per-topic detail files.

    Returns (listing, details_dict) where details_dict is keyed by slug.
    """
    # Fetch all aggregation data
    verdict_breakdown = _fetch_verdict_breakdown(conn)
    claim_counts = _fetch_claim_counts(conn)
    sighting_counts = _fetch_sighting_counts(conn)
    date_ranges = _fetch_date_range(conn)
    top_entities = _fetch_top_entities(conn)
    source_breakdown = _fetch_source_breakdown(conn)
    weekly_timeline = _fetch_weekly_timeline(conn)
    evidence_counts = _fetch_evidence_counts(conn)
    topic_claims = _fetch_topic_claims(conn)
    topic_claim_speakers = _fetch_topic_claim_speakers(conn)
    topic_evidence = _fetch_topic_evidence(conn)
    entity_details = _fetch_entity_details_for_topic(conn)
    source_activity = _fetch_source_activity_for_topic(conn)

    # Compute overall diversity score across all topics
    overall_diversity = diversity_score(sighting_counts)

    listing = []
    details = {}

    for topic, label_is in sorted(TOPIC_LABELS_IS.items()):
        slug = topic.replace("_", "-")
        counts = claim_counts.get(topic, {"total": 0, "published": 0})
        dates = date_ranges.get(topic, {})
        verdicts = verdict_breakdown.get(topic, {})

        # Build listing entry
        entry = {
            "slug": slug,
            "label_is": label_is,
            "label_en": topic.replace("_", " ").title(),
            "claim_count": counts["total"],
            "published_claim_count": counts["published"],
            "evidence_count": evidence_counts.get(topic, 0),
            "sighting_count": sighting_counts.get(topic, 0),
            "verdict_counts": verdicts,
            "first_seen": dates.get("first_seen"),
            "last_seen": dates.get("last_seen"),
            "top_entities": top_entities.get(topic, [])[:5],
            "source_breakdown": source_breakdown.get(topic, {}),
        }
        listing.append(entry)

        # Build claims list with speakers for detail page
        claims_with_speakers = []
        for claim in topic_claims.get(topic, []):
            speakers = topic_claim_speakers.get(topic, {}).get(claim["claim_slug"], [])
            claims_with_speakers.append({
                **claim,
                "speakers": speakers,
            })

        # Per-topic diversity (how varied are sources for this topic)
        topic_source_counts = source_breakdown.get(topic, {})
        topic_diversity = diversity_score(topic_source_counts) if topic_source_counts else 0.0

        # Build detail entry
        detail = {
            "slug": slug,
            "label_is": label_is,
            "label_en": topic.replace("_", " ").title(),
            "description_is": f"Yfirlit yfir umræðu um {label_is.lower()} í tengslum við ESB-aðild Íslands.",
            "claims": claims_with_speakers,
            "evidence": topic_evidence.get(topic, []),
            "timeline": weekly_timeline.get(topic, []),
            "entities": entity_details.get(topic, []),
            "source_activity": source_activity.get(topic, []),
            "diversity_score": topic_diversity,
        }
        details[slug] = detail

    # Sort listing by sighting count (most active topics first)
    listing.sort(key=lambda t: -t["sighting_count"])

    return listing, details


def _show_status(conn) -> None:
    """Print topic distribution table."""
    verdict_breakdown = _fetch_verdict_breakdown(conn)
    claim_counts = _fetch_claim_counts(conn)
    sighting_counts = _fetch_sighting_counts(conn)
    evidence_counts = _fetch_evidence_counts(conn)

    overall_diversity = diversity_score(sighting_counts)

    print(f"{'Topic':<20} {'Label':<30} {'Claims':>7} {'Pub':>5} {'Sght':>6} {'Evid':>5}")
    print("-" * 80)

    total_claims = 0
    total_pub = 0
    total_sightings = 0
    total_evidence = 0

    for topic, label in sorted(TOPIC_LABELS_IS.items(), key=lambda x: -(sighting_counts.get(x[0], 0))):
        counts = claim_counts.get(topic, {"total": 0, "published": 0})
        sightings = sighting_counts.get(topic, 0)
        evidence = evidence_counts.get(topic, 0)

        total_claims += counts["total"]
        total_pub += counts["published"]
        total_sightings += sightings
        total_evidence += evidence

        print(f"{topic:<20} {label:<30} {counts['total']:>7} {counts['published']:>5} {sightings:>6} {evidence:>5}")

        # Show verdict breakdown inline
        verdicts = verdict_breakdown.get(topic, {})
        if verdicts:
            parts = [f"{v}: {n}" for v, n in sorted(verdicts.items(), key=lambda x: -x[1])]
            print(f"{'':>20}   {', '.join(parts)}")

    print("-" * 80)
    print(f"{'TOTAL':<20} {'':<30} {total_claims:>7} {total_pub:>5} {total_sightings:>6} {total_evidence:>5}")
    print(f"\nDiversity score (overall): {overall_diversity:.4f}")


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

    conn = _get_connection()

    if status_only:
        _show_status(conn)
        conn.close()
        return

    listing, details = build_topics(conn)
    conn.close()

    # Write listing
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    listing_path = EXPORT_DIR / "topics.json"
    with open(listing_path, "w", encoding="utf-8") as f:
        json.dump(listing, f, ensure_ascii=False, indent=2)

    # Write detail files
    details_dir = EXPORT_DIR / "topic-details"
    details_dir.mkdir(parents=True, exist_ok=True)
    for slug, detail in details.items():
        detail_path = details_dir / f"{slug}.json"
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(listing)} topics to {listing_path}")
    print(f"Exported {len(details)} topic details to {details_dir}")

    # Copy to site repo if --site-dir provided
    if site_dir:
        import shutil

        # Listing → assets/data/topics.json
        site_listing = site_dir / "assets" / "data" / "topics.json"
        site_listing.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(listing_path, site_listing)
        print(f"  {site_listing}")

        # Details → _data/topic-details/*.json
        site_details = site_dir / "_data" / "topic-details"
        site_details.mkdir(parents=True, exist_ok=True)
        for slug, detail in details.items():
            detail_path = site_details / f"{slug}.json"
            with open(detail_path, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=2)
        print(f"  {len(details)} detail files → {site_details}")

    # Summary
    active_topics = [t for t in listing if t["sighting_count"] > 0]
    total_claims = sum(t["published_claim_count"] for t in listing)
    total_sightings = sum(t["sighting_count"] for t in listing)
    sighting_counts = {t["slug"]: t["sighting_count"] for t in listing if t["sighting_count"] > 0}
    ds = diversity_score(sighting_counts)
    print(f"\n{len(active_topics)} active topics, {total_claims} published claims, {total_sightings} sightings")
    print(f"Diversity score: {ds:.4f}")


if __name__ == "__main__":
    main()
