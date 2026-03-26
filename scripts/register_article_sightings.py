"""Batch-register claim sightings for articles missing from the DB.

Reads the article registry to find articles with local analysis but no DB
sightings. For each, loads _report_final.json and registers each claim
using the same 3-branch logic as panel/speech registration:

  1. Semantic match >= 0.70 → insert sighting
  2. No match + non-unverifiable → create new unpublished claim + sighting
  3. No match + unverifiable → discard

Usage:
    uv run python scripts/register_article_sightings.py --status     # Preview
    uv run python scripts/register_article_sightings.py              # Register all
    uv run python scripts/register_article_sightings.py --dry-run    # Dry run
    uv run python scripts/register_article_sightings.py --dir 20260311_174823  # Single article
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from esbvaktin.utils.domain import extract_domain as _extract_domain

ANALYSES_DIR = Path("data/analyses")
REGISTRY_PATH = Path("data/article_registry.json")

SIGHTING_MATCH_THRESHOLD = 0.70

# Attribution types ordered by directness — prefer direct quotes
_ATTR_PRIORITY = {"quoted": 0, "asserted": 1, "paraphrased": 2, "mentioned": 3}


def _extract_primary_speaker(claim_entry: dict) -> str | None:
    """Pick the most directly attributed individual speaker from a claim.

    Prefers quoted > asserted > paraphrased > mentioned, and individuals
    over institutions/parties.  Returns None if no suitable speaker found.
    """
    speakers = claim_entry.get("speakers", [])
    if not speakers:
        return None

    def sort_key(s):
        # Individuals first, then by attribution directness
        type_priority = 0 if s.get("type") == "individual" else 1
        attr_priority = _ATTR_PRIORITY.get(s.get("attribution", ""), 9)
        return (type_priority, attr_priority)

    best = min(speakers, key=sort_key)
    name = best.get("name", "")
    # Skip generic institutional speakers and mentioned-only individuals
    if not name or best.get("attribution") == "mentioned":
        return None
    return name


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)


def _parse_date(val: str | None) -> date | None:
    """Parse a date string, returning None on failure."""
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def _determine_source_type(report: dict) -> str:
    """Determine sighting source_type from report metadata."""
    # Panel shows are already registered via their own pipeline
    # Check for opinion pieces (common patterns in Icelandic media)
    title = (report.get("article_title") or "").lower()
    url = (report.get("article_url") or "").lower()
    if any(kw in title for kw in ["skrifar:", "pistill", "leiðari"]):
        return "opinion"
    if "/pistlar/" in url or "/skolir/" in url or "/leidarar/" in url:
        return "opinion"
    return "news"


def load_unregistered_articles() -> list[dict]:
    """Load articles that have analysis dirs but no DB sightings."""
    if not REGISTRY_PATH.exists():
        logger.error("Registry not found. Run: uv run python scripts/build_article_registry.py")
        sys.exit(1)

    registry = json.loads(REGISTRY_PATH.read_text())
    return [a for a in registry if not a.get("in_db") and a.get("analysis_dir")]


def register_article(
    analysis_dir: str,
    report: dict,
    conn,
    dry_run: bool = False,
) -> dict[str, int]:
    """Register sightings for a single article's claims.

    Returns counts: {"matched": N, "new_claims": N, "discarded": N}.
    """
    from esbvaktin.claim_bank.models import CanonicalClaim
    from esbvaktin.claim_bank.operations import add_claim, generate_slug, search_claims

    source_url = report.get("article_url", "")
    source_title = report.get("article_title", "")
    source_date = _parse_date(report.get("article_date"))
    source_type = _determine_source_type(report)

    # Fallback: resolve missing metadata from inbox, URL patterns, and article text
    if (source_date is None or not source_title) and source_url:
        from esbvaktin.utils.metadata import resolve_metadata

        # Try to load article text for text-based date extraction (last resort)
        article_text = None
        article_path = ANALYSES_DIR / analysis_dir / "_article.md"
        if source_date is None and article_path.exists():
            try:
                article_text = article_path.read_text()
            except OSError:
                pass

        meta = resolve_metadata(source_url, article_text=article_text)
        if source_date is None and meta.date:
            source_date = meta.date
        if not source_title and meta.title:
            source_title = meta.title

    if source_date is None:
        logger.warning("NULL source_date for %s — invisible to overviews", source_url[:60])

    claims = report.get("claims", [])
    counts = {"matched": 0, "new_claims": 0, "discarded": 0}

    for claim_entry in claims:
        claim_data = claim_entry.get("claim", {})
        claim_text = claim_data.get("claim_text", "")
        verdict = claim_entry.get("verdict", "")

        if not claim_text or not verdict:
            continue

        speaker = _extract_primary_speaker(claim_entry)

        # Search claim bank for semantic match
        matches = search_claims(
            query=claim_text,
            threshold=SIGHTING_MATCH_THRESHOLD,
            top_k=1,
            conn=conn,
        )

        if matches:
            match = matches[0]
            if not dry_run:
                _insert_sighting(
                    conn=conn,
                    claim_id=match.claim_id,
                    source_url=source_url,
                    source_title=source_title,
                    source_date=source_date,
                    source_type=source_type,
                    original_text=claim_text,
                    similarity=match.similarity,
                    speech_verdict=verdict,
                    speaker_name=speaker,
                )
            counts["matched"] += 1
            logger.debug(
                "Match: %.3f '%s' → %s [%s] (%s)",
                match.similarity,
                claim_text[:50],
                match.claim_slug,
                speaker or "?",
                verdict,
            )

        elif verdict != "unverifiable":
            slug = generate_slug(claim_text[:80])
            if not dry_run:
                epistemic_type = claim_data.get("epistemic_type", "factual")
                is_hearsay = epistemic_type == "hearsay"
                new_claim = CanonicalClaim(
                    claim_slug=slug,
                    canonical_text_is=claim_text,
                    category=claim_data.get("category", ""),
                    claim_type=claim_data.get("claim_type", "opinion"),
                    epistemic_type=epistemic_type,
                    verdict="unverifiable" if is_hearsay else verdict,
                    explanation_is=claim_entry.get("explanation", ""),
                    missing_context_is=claim_entry.get("missing_context"),
                    supporting_evidence=claim_entry.get("supporting_evidence", []),
                    contradicting_evidence=claim_entry.get("contradicting_evidence", []),
                    confidence=claim_entry.get("confidence", 0.5),
                    published=False if is_hearsay else True,
                    substantive=False if is_hearsay else True,
                )
                try:
                    claim_id = add_claim(new_claim, conn=conn)
                    _insert_sighting(
                        conn=conn,
                        claim_id=claim_id,
                        source_url=source_url,
                        source_title=source_title,
                        source_date=source_date,
                        source_type=source_type,
                        original_text=claim_text,
                        similarity=1.0,
                        speech_verdict=verdict,
                        speaker_name=speaker,
                    )
                except Exception as e:
                    logger.warning("Failed to insert claim '%s': %s", slug, e)
                    continue
            counts["new_claims"] += 1
            logger.debug("New: '%s' → %s [%s] (%s)", claim_text[:50], slug, speaker or "?", verdict)

        else:
            counts["discarded"] += 1

    return counts


def _insert_sighting(
    conn,
    claim_id: int,
    source_url: str,
    source_title: str,
    source_date: date | None,
    source_type: str,
    original_text: str,
    similarity: float,
    speech_verdict: str,
    speaker_name: str | None = None,
) -> None:
    """Insert a claim sighting for an article."""
    source_domain = _extract_domain(source_url)

    conn.execute(
        """
        INSERT INTO claim_sightings (
            claim_id, source_url, source_title, source_date,
            source_type, original_text, similarity,
            speech_verdict, speaker_name, source_domain
        ) VALUES (
            %(claim_id)s, %(source_url)s, %(source_title)s, %(source_date)s,
            %(source_type)s, %(original_text)s, %(similarity)s,
            %(speech_verdict)s, %(speaker_name)s, %(source_domain)s
        ) ON CONFLICT (claim_id, source_url) DO UPDATE SET
            speech_verdict = EXCLUDED.speech_verdict,
            similarity = EXCLUDED.similarity,
            original_text = EXCLUDED.original_text,
            speaker_name = COALESCE(EXCLUDED.speaker_name, claim_sightings.speaker_name),
            source_domain = COALESCE(EXCLUDED.source_domain, claim_sightings.source_domain)
        """,
        {
            "claim_id": claim_id,
            "source_url": source_url,
            "source_title": source_title,
            "source_date": source_date,
            "source_type": source_type,
            "original_text": original_text,
            "similarity": similarity,
            "speech_verdict": speech_verdict,
            "speaker_name": speaker_name,
            "source_domain": source_domain,
        },
    )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Register article claim sightings in DB")
    parser.add_argument("--status", action="store_true", help="Show unregistered articles")
    parser.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    parser.add_argument("--dir", metavar="DIR", help="Register a single analysis dir")
    args = parser.parse_args()

    if args.status:
        articles = load_unregistered_articles()
        print(f"Unregistered articles: {len(articles)}")
        total_claims = 0
        for a in articles:
            report_path = ANALYSES_DIR / a["analysis_dir"] / "_report_final.json"
            n = 0
            if report_path.exists():
                data = json.loads(report_path.read_text())
                n = len(data.get("claims", []))
            total_claims += n
            print(f"  {a['analysis_dir']}  {n:2d} claims  {a['title'][:55]}")
        print(f"\nTotal claims to register: {total_claims}")
        return

    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()

    if args.dir:
        # Single article
        report_path = ANALYSES_DIR / args.dir / "_report_final.json"
        if not report_path.exists():
            logger.error("No _report_final.json in %s", args.dir)
            sys.exit(1)
        report = json.loads(report_path.read_text())
        counts = register_article(args.dir, report, conn, dry_run=args.dry_run)
        prefix = "[DRY RUN] " if args.dry_run else ""
        print(f"{prefix}{args.dir}: {counts}")
    else:
        # All unregistered
        articles = load_unregistered_articles()
        if not articles:
            print("All articles already registered.")
            conn.close()
            return

        print(f"Registering {len(articles)} articles...")
        totals = {"matched": 0, "new_claims": 0, "discarded": 0}

        for i, a in enumerate(articles, 1):
            report_path = ANALYSES_DIR / a["analysis_dir"] / "_report_final.json"
            if not report_path.exists():
                logger.warning("No report: %s", a["analysis_dir"])
                continue

            report = json.loads(report_path.read_text())
            counts = register_article(a["analysis_dir"], report, conn, dry_run=args.dry_run)

            for k in totals:
                totals[k] += counts[k]

            n_claims = len(report.get("claims", []))
            prefix = "[DRY RUN] " if args.dry_run else ""
            print(
                f"{prefix}[{i}/{len(articles)}] {a['analysis_dir']}: {n_claims} claims → {counts}"
            )

        print(f"\n{prefix if args.dry_run else ''}Totals: {totals}")

    conn.close()


if __name__ == "__main__":
    main()
