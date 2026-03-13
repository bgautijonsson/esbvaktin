"""Migrate claim bank entries from English to Icelandic.

Reads report_text_is from each analysis report, parses per-claim Icelandic
text, and updates the corresponding claims in the DB.

Usage:
    uv run python scripts/migrate_claims_icelandic.py --dry-run   # Preview changes
    uv run python scripts/migrate_claims_icelandic.py              # Apply changes
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"


def _get_connection():
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


def _parse_icelandic_claims(report_text_is: str) -> list[dict]:
    """Parse per-claim Icelandic text from report_text_is markdown."""
    claims = []
    if not report_text_is:
        return claims

    sections = re.split(r"### Fullyrðing \d+:", report_text_is)
    # First element is everything before claim 1
    for section in sections[1:]:
        data: dict = {}

        claim_match = re.search(
            r"\*\*Fullyrðing:\*\*\s*(.+?)(?=\n\n|\n\*\*)", section, re.DOTALL
        )
        if claim_match:
            data["claim_text_is"] = claim_match.group(1).strip()

        mat_match = re.search(
            r"\*\*Mat:\*\*\s*(.+?)(?=\n\*\*|\n\n---|\Z)", section, re.DOTALL
        )
        if mat_match:
            data["explanation_is"] = mat_match.group(1).strip()

        context_match = re.search(
            r"\*\*(?:Vantar samhengi|Samhengi sem vantar):\*\*\s*(.+?)(?=\n\*\*|\n\n---|\Z)",
            section,
            re.DOTALL,
        )
        if context_match:
            data["missing_context_is"] = context_match.group(1).strip()

        claims.append(data)

    return claims


def migrate(dry_run: bool = True) -> None:
    conn = _get_connection()

    report_files = sorted(ANALYSES_DIR.glob("*/_report_final.json"))
    if not report_files:
        print("No analysis reports found.")
        return

    updated = 0
    skipped = 0

    for report_path in report_files:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)

        title = report.get("article_title", "untitled")
        report_text_is = report.get("report_text_is", "")
        claims_en = report.get("claims", [])
        claims_is = _parse_icelandic_claims(report_text_is)

        if len(claims_en) != len(claims_is):
            print(f"  Warning: {title}: {len(claims_en)} EN claims vs {len(claims_is)} IS claims")

        print(f"\n--- {title} ({len(claims_en)} claims) ---")

        for i, ca in enumerate(claims_en):
            claim_text_en = ca.get("claim", {}).get("claim_text", "")
            if not claim_text_en:
                continue

            is_data = claims_is[i] if i < len(claims_is) else {}
            claim_text_is = is_data.get("claim_text_is")
            explanation_is = is_data.get("explanation_is")
            missing_context_is = is_data.get("missing_context_is")

            if not claim_text_is and not explanation_is:
                skipped += 1
                continue

            # Find the claim in the DB by matching the English text stored in canonical_text_is
            # (since that's what was originally stored there)
            row = conn.execute(
                "SELECT id, canonical_text_is, explanation_is FROM claims WHERE canonical_text_is = %s",
                (claim_text_en,),
            ).fetchone()

            if not row:
                # Try fuzzy match — the slug might have been truncated
                from esbvaktin.claim_bank.operations import generate_slug

                slug = generate_slug(claim_text_en)
                row = conn.execute(
                    "SELECT id, canonical_text_is, explanation_is FROM claims WHERE claim_slug = %s",
                    (slug,),
                ).fetchone()

            if not row:
                print(f"  ? Not found in DB: {claim_text_en[:60]}...")
                skipped += 1
                continue

            claim_id = row[0]

            # Build update fields
            updates = {}
            if claim_text_is:
                updates["canonical_text_is"] = claim_text_is
                updates["canonical_text_en"] = claim_text_en  # Store English in _en field
            if explanation_is:
                updates["explanation_is"] = explanation_is
                updates["explanation_en"] = ca.get("explanation", "")
            if missing_context_is:
                updates["missing_context_is"] = missing_context_is

            if not updates:
                skipped += 1
                continue

            if dry_run:
                print(f"  ~ Would update claim {claim_id}: {claim_text_en[:50]}...")
                if claim_text_is:
                    print(f"    canonical_text_is: {claim_text_is[:60]}...")
                if explanation_is:
                    print(f"    explanation_is: {explanation_is[:60]}...")
            else:
                set_clause = ", ".join(f"{k} = %s" for k in updates)
                values = list(updates.values()) + [claim_id]
                conn.execute(
                    f"UPDATE claims SET {set_clause} WHERE id = %s",
                    values,
                )
                print(f"  ✓ Updated claim {claim_id}: {(claim_text_is or claim_text_en)[:50]}...")

            updated += 1

    if not dry_run:
        conn.commit()

    conn.close()

    action = "Would update" if dry_run else "Updated"
    print("\n=== Done ===")
    print(f"{action}: {updated} claims")
    print(f"Skipped: {skipped} claims")

    if dry_run:
        print("\nRun without --dry-run to apply changes.")


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    migrate(dry_run=dry_run)


if __name__ == "__main__":
    main()
