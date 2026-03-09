#!/usr/bin/env python3
"""Bootstrap the claim bank from existing article analyses.

Reads _report_final.json from all completed analyses, extracts
ClaimAssessment entries, deduplicates by semantic similarity,
and inserts into the claims table.

Usage:
    uv run python scripts/seed_claim_bank.py                  # Seed from all analyses
    uv run python scripts/seed_claim_bank.py status            # Show claim bank stats
    uv run python scripts/seed_claim_bank.py data/analyses/X/  # Seed from one analysis
"""

import json
import sys
from pathlib import Path

from esbvaktin.claim_bank.models import CanonicalClaim
from esbvaktin.claim_bank.operations import (
    add_claim,
    generate_slug,
    get_claim_counts,
    get_total_claims,
    init_claims_schema,
    search_claims,
)
from esbvaktin.ground_truth.operations import get_connection


def load_analyses(base_dir: Path) -> list[dict]:
    """Load all _report_final.json files from analysis directories."""
    reports = []
    for report_path in sorted(base_dir.glob("*/_report_final.json")):
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            data["_source_dir"] = str(report_path.parent)
            reports.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ⚠ Skipping {report_path}: {e}")
    return reports


def seed_from_report(report: dict, conn, dry_run: bool = False) -> int:
    """Extract claims from one analysis report and add to claim bank.

    Returns the number of claims added.
    """
    claims = report.get("claims", [])
    source_dir = report.get("_source_dir", "unknown")
    added = 0

    for ca in claims:
        claim = ca.get("claim", {})
        claim_text = claim.get("claim_text", "")
        if not claim_text:
            continue

        verdict = ca.get("verdict", "")
        explanation = ca.get("explanation", "")
        if not verdict or not explanation:
            continue

        # Generate slug
        slug = generate_slug(claim_text)
        if not slug or len(slug) < 3:
            slug = generate_slug(claim_text[:80])

        # Check for existing similar claim (avoid duplicates)
        try:
            existing = search_claims(claim_text, threshold=0.85, top_k=1, conn=conn)
            if existing:
                print(f"  ≈ Similar claim exists: {existing[0].claim_slug} "
                      f"(similarity: {existing[0].similarity:.3f}), skipping")
                continue
        except Exception:
            pass  # Table might not exist yet on first run

        canonical = CanonicalClaim(
            claim_slug=slug,
            canonical_text_is=claim_text,
            canonical_text_en=None,
            category=claim.get("category", "other"),
            claim_type=claim.get("claim_type", "opinion"),
            verdict=verdict,
            explanation_is=explanation,
            missing_context_is=ca.get("missing_context"),
            supporting_evidence=ca.get("supporting_evidence", []),
            contradicting_evidence=ca.get("contradicting_evidence", []),
            confidence=ca.get("confidence", 0.5),
        )

        if dry_run:
            print(f"  + Would add: {slug} ({verdict})")
        else:
            try:
                claim_id = add_claim(canonical, conn=conn)
                print(f"  ✓ Added: {slug} (id={claim_id}, {verdict})")
                added += 1
            except Exception as e:
                print(f"  ✗ Failed: {slug}: {e}")

    return added


def show_status():
    """Display claim bank statistics."""
    conn = get_connection()
    try:
        total = get_total_claims(conn=conn)
        counts = get_claim_counts(conn=conn)
        print(f"\n=== Claim Bank Status ===")
        print(f"Total claims: {total}")
        print(f"\nBy verdict:")
        for verdict, count in counts.items():
            print(f"  {verdict}: {count}")
    except Exception as e:
        print(f"Error: {e}")
        print("(Has the claims table been created? Run without 'status' first.)")
    finally:
        conn.close()


def main():
    args = sys.argv[1:]

    if args and args[0] == "status":
        show_status()
        return

    # Determine source directory
    if args:
        base = Path(args[0])
        if base.is_dir() and (base / "_report_final.json").exists():
            # Single analysis directory
            reports = [json.loads((base / "_report_final.json").read_text(encoding="utf-8"))]
            reports[0]["_source_dir"] = str(base)
        elif base.is_dir():
            reports = load_analyses(base)
        else:
            print(f"Error: {base} is not a valid directory")
            sys.exit(1)
    else:
        base = Path("data/analyses")
        if not base.exists():
            print(f"Error: {base} not found. Run from project root.")
            sys.exit(1)
        reports = load_analyses(base)

    if not reports:
        print("No analysis reports found.")
        sys.exit(0)

    print(f"Found {len(reports)} analysis report(s)")

    # Initialise schema
    conn = get_connection()
    init_claims_schema(conn=conn)
    print("Claims schema initialised.")

    # Seed from each report
    total_added = 0
    for report in reports:
        source = report.get("_source_dir", "unknown")
        title = report.get("article_title", "untitled")
        n_claims = len(report.get("claims", []))
        print(f"\n--- {title or source} ({n_claims} claims) ---")
        added = seed_from_report(report, conn=conn)
        total_added += added

    conn.close()

    print(f"\n=== Done ===")
    print(f"Total claims added: {total_added}")
    show_status()


if __name__ == "__main__":
    main()
