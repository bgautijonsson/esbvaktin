"""Generate weekly/daily overview data from PostgreSQL.

Pure SQL data extraction — no LLM involved. Produces a structured JSON file
with all metrics needed for the editorial agent and site export.

Usage:
    uv run python scripts/generate_overview.py 2026-03-04 2026-03-10
    uv run python scripts/generate_overview.py --week 2026-W11
    uv run python scripts/generate_overview.py --status
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from esbvaktin.pipeline.models import TOPIC_LABELS_IS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OVERVIEWS_DIR = PROJECT_ROOT / "data" / "overviews"
SITE_DIR = PROJECT_ROOT.parent / "esbvaktin-site"
ENTITY_DETAILS_DIR = SITE_DIR / "_data" / "entity-details"


def _get_connection():
    from esbvaktin.ground_truth.operations import get_connection
    return get_connection()


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


def _parse_iso_week(week_str: str) -> tuple[date, date]:
    """Parse ISO week string (e.g., '2026-W11') to (Monday, Sunday) date range."""
    # Parse YYYY-Www format
    year, week_num = week_str.split("-W")
    year = int(year)
    week_num = int(week_num)

    # ISO week 1 starts on the Monday of the week containing Jan 4
    jan4 = date(year, 1, 4)
    # Monday of ISO week 1
    week1_monday = jan4 - timedelta(days=jan4.isoweekday() - 1)
    # Monday of requested week
    monday = week1_monday + timedelta(weeks=week_num - 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _fetch_period_articles(conn, start: date, end: date) -> list[dict]:
    """Articles analysed in the period (distinct source URLs from sightings)."""
    rows = conn.execute("""
        WITH per_url_cat AS (
            SELECT s.source_url,
                   MAX(s.source_title) AS source_title,
                   c.category,
                   COUNT(*) AS cat_count,
                   MIN(s.source_date) AS article_date,
                   SUM(COUNT(*)) OVER (PARTITION BY s.source_url) AS claim_count
            FROM claim_sightings s
            JOIN claims c ON c.id = s.claim_id
            WHERE c.published = TRUE
              AND s.source_date BETWEEN %s AND %s
              AND s.source_url IS NOT NULL
            GROUP BY s.source_url, c.category
        ),
        dominant AS (
            SELECT DISTINCT ON (source_url)
                   source_url, source_title, category AS dominant_category,
                   claim_count, article_date
            FROM per_url_cat
            ORDER BY source_url, cat_count DESC
        )
        SELECT source_url, source_title, dominant_category, claim_count, article_date
        FROM dominant
        ORDER BY article_date
    """, (start, end)).fetchall()

    # Look up source_domain from DB for each URL
    url_to_domain: dict[str, str] = {}
    if rows:
        domain_rows = conn.execute(
            "SELECT DISTINCT source_url, source_domain FROM claim_sightings "
            "WHERE source_domain IS NOT NULL"
        ).fetchall()
        url_to_domain = {u: d for u, d in domain_rows}

    return [
        {
            "title": title or url,
            "source": url_to_domain.get(url, "unknown"),
            "url": url,
            "date": article_date.isoformat() if isinstance(article_date, (date, datetime)) else article_date,
            "claim_count": int(claim_count),
            "dominant_category": dominant_category,
        }
        for url, title, dominant_category, claim_count, article_date in rows
    ]


def _fetch_new_claims(conn, start: date, end: date) -> dict:
    """Claims sighted in the period with verdict breakdown.

    Uses source_date (article publication) not created_at (DB insertion),
    so claim counts align with the article counts for the same period.
    """
    rows = conn.execute("""
        SELECT c.verdict, c.published, COUNT(DISTINCT c.id) AS n
        FROM claims c
        JOIN claim_sightings s ON c.id = s.claim_id
        WHERE s.source_date BETWEEN %s AND %s
        GROUP BY c.verdict, c.published
    """, (start, end)).fetchall()

    total = 0
    published = 0
    verdict_breakdown: dict[str, int] = defaultdict(int)

    for verdict, is_published, n in rows:
        total += n
        if is_published:
            published += n
            verdict_breakdown[verdict] += n

    return {
        "total": total,
        "published": published,
        "verdict_breakdown": dict(verdict_breakdown),
    }


def _fetch_topic_activity(conn, start: date, end: date) -> list[dict]:
    """Per-topic sighting counts and new claims in the period."""
    sighting_rows = conn.execute("""
        SELECT c.category, COUNT(*) AS sightings
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE
          AND s.source_date BETWEEN %s AND %s
        GROUP BY c.category
        ORDER BY sightings DESC
    """, (start, end)).fetchall()

    new_claim_rows = conn.execute("""
        SELECT c.category, COUNT(DISTINCT c.id) AS new_claims
        FROM claims c
        JOIN claim_sightings s ON c.id = s.claim_id
        WHERE c.published = TRUE
          AND s.source_date BETWEEN %s AND %s
        GROUP BY c.category
    """, (start, end)).fetchall()

    new_claims_map = {cat: n for cat, n in new_claim_rows}

    result = []
    for cat, sightings in sighting_rows:
        result.append({
            "topic": cat,
            "label_is": TOPIC_LABELS_IS.get(cat, cat),
            "sightings": sightings,
            "new_claims": new_claims_map.get(cat, 0),
        })

    return result


def _fetch_topic_activity_with_delta(
    conn, start: date, end: date, prev_start: date, prev_end: date
) -> list[dict]:
    """Topic activity with delta compared to previous period."""
    current = _fetch_topic_activity(conn, start, end)

    prev_rows = conn.execute("""
        SELECT c.category, COUNT(*) AS sightings
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE
          AND s.source_date BETWEEN %s AND %s
        GROUP BY c.category
    """, (prev_start, prev_end)).fetchall()

    prev_map = {cat: n for cat, n in prev_rows}

    for item in current:
        prev_count = prev_map.get(item["topic"], 0)
        delta = item["sightings"] - prev_count
        item["delta"] = f"+{delta}" if delta > 0 else str(delta)

    return current


def _fetch_active_entities(conn, start: date, end: date) -> list[dict]:
    """Most active entities (speakers) in the period.

    Uses the site's entity-detail JSONs (same source as /raddirnar/ pages)
    rather than claim_sightings, so counts match what entity pages show.
    Falls back to DB sightings if entity-details dir is missing.
    """
    if ENTITY_DETAILS_DIR.is_dir():
        return _active_entities_from_site(start, end)
    # Fallback: DB sightings (may undercount — see commit message)
    return _active_entities_from_db(conn, start, end)


def _active_entities_from_site(start: date, end: date) -> list[dict]:
    """Count claims per entity from site entity-detail JSONs, filtered by date."""
    results: list[dict] = []

    for detail_path in ENTITY_DETAILS_DIR.glob("*.json"):
        try:
            detail = json.loads(detail_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        # Only include individuals (skip parties, organisations)
        if detail.get("type") != "individual":
            continue

        # Count claims whose article_date falls within the period
        topic_counts: dict[str, int] = defaultdict(int)
        claims_in_period = 0

        for claim in detail.get("claims", []):
            article_date_str = claim.get("article_date")
            if not article_date_str:
                continue
            try:
                article_date = date.fromisoformat(article_date_str)
            except ValueError:
                continue

            if start <= article_date <= end:
                claims_in_period += 1
                cat = claim.get("category", "")
                if cat:
                    topic_counts[cat] += 1

        if claims_in_period == 0:
            continue

        results.append({
            "name": detail["name"],
            "claims_made": claims_in_period,
            "top_topics": [
                TOPIC_LABELS_IS.get(cat, cat)
                for cat, _ in sorted(topic_counts.items(), key=lambda x: -x[1])[:3]
            ],
        })

    # Sort by claims descending, take top 15
    results.sort(key=lambda x: -x["claims_made"])
    return results[:15]


def _active_entities_from_db(conn, start: date, end: date) -> list[dict]:
    """Fallback: active entities from claim_sightings (may undercount)."""
    speaker_rows = conn.execute("""
        SELECT s.speaker_name, COUNT(*) AS claims_made
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE s.source_date BETWEEN %s AND %s
          AND s.speaker_name IS NOT NULL
        GROUP BY s.speaker_name
        ORDER BY claims_made DESC
        LIMIT 15
    """, (start, end)).fetchall()

    topic_rows = conn.execute("""
        SELECT s.speaker_name, c.category, COUNT(*) AS n
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE s.source_date BETWEEN %s AND %s
          AND s.speaker_name IS NOT NULL
        GROUP BY s.speaker_name, c.category
    """, (start, end)).fetchall()

    speaker_topics: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for name, cat, n in topic_rows:
        speaker_topics[name].append((cat, n))

    return [
        {
            "name": name,
            "claims_made": claims_made,
            "top_topics": [
                TOPIC_LABELS_IS.get(cat, cat)
                for cat, _ in sorted(speaker_topics.get(name, []), key=lambda x: -x[1])[:3]
            ],
        }
        for name, claims_made in speaker_rows
    ]


def _fetch_top_claims(conn, start: date, end: date) -> list[dict]:
    """Most-sighted claims in the period, focusing on notable verdicts."""
    rows = conn.execute("""
        SELECT c.canonical_text_is, c.claim_slug, c.verdict, c.category,
               COUNT(s.id) AS sighting_count,
               ARRAY_AGG(DISTINCT s.source_title) FILTER (WHERE s.source_title IS NOT NULL) AS sources
        FROM claims c
        JOIN claim_sightings s ON c.id = s.claim_id
        WHERE c.published = TRUE
          AND s.source_date BETWEEN %s AND %s
        GROUP BY c.id
        ORDER BY
            CASE c.verdict
                WHEN 'misleading' THEN 0
                WHEN 'unsupported' THEN 1
                WHEN 'partially_supported' THEN 2
                WHEN 'unverifiable' THEN 3
                WHEN 'supported' THEN 4
            END,
            sighting_count DESC
        LIMIT 10
    """, (start, end)).fetchall()

    return [
        {
            "canonical_text_is": text,
            "claim_slug": slug,
            "verdict": verdict,
            "category": cat,
            "category_is": TOPIC_LABELS_IS.get(cat, cat),
            "sighting_count": count,
            "sources": sources or [],
        }
        for text, slug, verdict, cat, count, sources in rows
    ]


def _fetch_source_breakdown(conn, start: date, end: date) -> dict[str, int]:
    """Source domain breakdown (distinct articles) in the period."""
    rows = conn.execute("""
        SELECT s.source_domain, COUNT(DISTINCT s.source_url) AS articles
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE
          AND s.source_date BETWEEN %s AND %s
          AND s.source_domain IS NOT NULL
        GROUP BY s.source_domain
        ORDER BY articles DESC
    """, (start, end)).fetchall()

    return {domain: articles for domain, articles in rows}


def _fetch_key_facts(conn, start: date, end: date) -> list[dict]:
    """Key facts — well-supported, non-political claims seen this week.

    Selects verifiable facts (statistics, legal assertions, comparisons)
    that are supported or partially supported, with caveats (missing_context),
    spread across different topic categories.  Excludes political/polling
    categories to focus on substantive material readers can learn from.
    """
    rows = conn.execute("""
        SELECT DISTINCT ON (c.category)
               c.canonical_text_is,
               c.claim_slug,
               c.category,
               c.claim_type,
               c.verdict,
               c.explanation_is,
               c.missing_context_is,
               c.confidence,
               c.supporting_evidence,
               c.contradicting_evidence
        FROM claims c
        JOIN claim_sightings s ON c.id = s.claim_id
        WHERE c.published = TRUE
          AND s.source_date BETWEEN %s AND %s
          AND c.verdict IN ('supported', 'partially_supported')
          AND c.claim_type IN ('statistic', 'legal_assertion', 'comparison')
          AND c.category NOT IN ('party_positions', 'polling', 'org_positions')
          AND c.missing_context_is IS NOT NULL
          AND LENGTH(c.missing_context_is) > 10
          AND c.confidence >= 0.7
        ORDER BY c.category,
                 CASE c.claim_type
                     WHEN 'statistic' THEN 0
                     WHEN 'comparison' THEN 1
                     ELSE 2
                 END,
                 c.confidence DESC
    """, (start, end)).fetchall()

    return [
        {
            "claim_text": text,
            "claim_slug": slug,
            "category": cat,
            "category_is": TOPIC_LABELS_IS.get(cat, cat),
            "claim_type": ctype,
            "verdict": verdict,
            "explanation": explanation or "",
            "caveat": caveat or "",
            "confidence": conf,
            "supporting_evidence": sup or [],
            "contradicting_evidence": contra or [],
        }
        for text, slug, cat, ctype, verdict, explanation, caveat, conf, sup, contra
        in rows
    ]


def _fetch_previous_period_metrics(
    conn, prev_start: date, prev_end: date
) -> dict:
    """Key metrics for the previous period (for comparison deltas)."""
    # Articles analysed
    article_count = conn.execute("""
        SELECT COUNT(DISTINCT s.source_url)
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE s.source_date BETWEEN %s AND %s
          AND s.source_url IS NOT NULL
          AND c.published = TRUE
    """, (prev_start, prev_end)).fetchone()[0]

    # Published claims sighted in the period (aligned with _fetch_new_claims)
    claim_count = conn.execute("""
        SELECT COUNT(DISTINCT c.id)
        FROM claims c
        JOIN claim_sightings s ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.source_date BETWEEN %s AND %s
    """, (prev_start, prev_end)).fetchone()[0]

    # Topic sighting counts for diversity
    topic_rows = conn.execute("""
        SELECT c.category, COUNT(*) AS sightings
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.source_date BETWEEN %s AND %s
        GROUP BY c.category
    """, (prev_start, prev_end)).fetchall()

    topic_counts = {cat: n for cat, n in topic_rows}

    return {
        "articles_analysed": article_count,
        "new_claims_published": claim_count,
        "diversity_score": diversity_score(topic_counts),
    }


def generate_overview(start: date, end: date) -> dict:
    """Generate full overview data for a date range.

    Returns structured dict matching the contract in the implementation plan.
    """
    conn = _get_connection()

    period_length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_length - 1)

    # Determine period type
    period_type = "weekly" if period_length == 7 else "daily" if period_length == 1 else "custom"

    # Fetch all data
    articles = _fetch_period_articles(conn, start, end)
    new_claims = _fetch_new_claims(conn, start, end)
    topic_activity = _fetch_topic_activity_with_delta(conn, start, end, prev_start, prev_end)
    active_entities = _fetch_active_entities(conn, start, end)
    top_claims = _fetch_top_claims(conn, start, end)
    source_breakdown = _fetch_source_breakdown(conn, start, end)
    key_facts = _fetch_key_facts(conn, start, end)
    previous_period = _fetch_previous_period_metrics(conn, prev_start, prev_end)

    # Compute diversity
    topic_sighting_counts = {t["topic"]: t["sightings"] for t in topic_activity}
    current_diversity = diversity_score(topic_sighting_counts)

    overview = {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "period_type": period_type,
        "key_numbers": {
            "articles_analysed": len(articles),
            "new_claims": new_claims["total"],
            "new_claims_published": new_claims["published"],
            "verdict_breakdown": new_claims["verdict_breakdown"],
            "entities_active": len(active_entities),
            "topics_active": len(topic_activity),
            "diversity_score": current_diversity,
        },
        "previous_period": previous_period,
        "topic_activity": topic_activity,
        "top_claims": top_claims,
        "active_entities": active_entities,
        "articles": articles,
        "source_breakdown": source_breakdown,
        "key_facts": key_facts,
    }

    conn.close()
    return overview


def _show_status() -> None:
    """Show available overview data and coverage."""
    conn = _get_connection()

    # Date range of all sightings
    row = conn.execute("""
        SELECT MIN(s.source_date), MAX(s.source_date), COUNT(DISTINCT s.source_url)
        FROM claim_sightings s
        WHERE s.source_date IS NOT NULL
    """).fetchone()

    min_date, max_date, total_articles = row

    # Weekly breakdown
    weeks = conn.execute("""
        SELECT DATE_TRUNC('week', s.source_date)::date AS week,
               COUNT(DISTINCT s.source_url) AS articles,
               COUNT(*) AS sightings
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.source_date IS NOT NULL
        GROUP BY week ORDER BY week
    """).fetchall()

    # Check which overviews already exist
    existing = set()
    if OVERVIEWS_DIR.exists():
        for d in OVERVIEWS_DIR.iterdir():
            if d.is_dir() and (d / "data.json").exists():
                existing.add(d.name)

    print(f"Sighting date range: {min_date} → {max_date}")
    print(f"Total distinct articles: {total_articles}")
    print()
    print(f"{'Week':<15} {'Articles':>10} {'Sightings':>10} {'Overview':>10}")
    print("-" * 50)

    for week, articles, sightings in weeks:
        week.isoformat()
        # Convert to ISO week label
        iso_cal = week.isocalendar()
        iso_label = f"{iso_cal[0]}-W{iso_cal[1]:02d}"
        status = "done" if iso_label in existing else "—"
        print(f"{iso_label:<15} {articles:>10} {sightings:>10} {status:>10}")

    conn.close()


def main() -> None:
    if "--status" in sys.argv:
        _show_status()
        return

    # Parse date range
    if "--week" in sys.argv:
        idx = sys.argv.index("--week")
        if idx + 1 >= len(sys.argv):
            print("Usage: --week YYYY-Www (e.g., --week 2026-W11)")
            sys.exit(1)
        start, end = _parse_iso_week(sys.argv[idx + 1])
        slug = sys.argv[idx + 1]
    elif len(sys.argv) >= 3:
        # Positional: start_date end_date
        args = [a for a in sys.argv[1:] if not a.startswith("-")]
        if len(args) < 2:
            print("Usage: generate_overview.py START_DATE END_DATE")
            print("       generate_overview.py --week 2026-W11")
            print("       generate_overview.py --status")
            sys.exit(1)
        start = date.fromisoformat(args[0])
        end = date.fromisoformat(args[1])
        # Derive slug from ISO week of the start date
        iso_cal = start.isocalendar()
        slug = f"{iso_cal[0]}-W{iso_cal[1]:02d}"
    else:
        print("Usage: generate_overview.py START_DATE END_DATE")
        print("       generate_overview.py --week 2026-W11")
        print("       generate_overview.py --status")
        sys.exit(1)

    print(f"Generating overview for {start} → {end} (slug: {slug})")
    overview = generate_overview(start, end)

    # Write output
    out_dir = OVERVIEWS_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "data.json"

    # Warn if editorial already exists (data/editorial drift risk)
    editorial_path = out_dir / "editorial.md"
    if editorial_path.exists() and out_path.exists():
        print(f"\n⚠  editorial.md already exists for {slug}.")
        print("   Overwriting data.json will make the editorial stale.")
        print("   The editorial references numbers from the previous data.json.")
        if "--force" not in sys.argv:
            print("   Use --force to overwrite, or delete editorial.md first.")
            sys.exit(1)
        print("   --force specified, overwriting.")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(overview, f, ensure_ascii=False, indent=2)

    # Summary
    kn = overview["key_numbers"]
    print(f"\nOverview written to {out_path}")
    print(f"  Articles: {kn['articles_analysed']}")
    print(f"  New claims: {kn['new_claims']} ({kn['new_claims_published']} published)")
    print(f"  Active entities: {kn['entities_active']}")
    print(f"  Active topics: {kn['topics_active']}")
    print(f"  Diversity score: {kn['diversity_score']:.4f}")
    print(f"  Top claims: {len(overview['top_claims'])}")
    print(f"  Key facts: {len(overview['key_facts'])}")


if __name__ == "__main__":
    main()
