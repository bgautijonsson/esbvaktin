#!/usr/bin/env python3
"""Review published claims for substantiveness.

Flags trivial/common-knowledge claims that shouldn't count toward
entity credibility scores. These claims remain published (visible on
site) but are excluded from the credibility calculation.

Usage:
    # Step 1: Prepare context batches for review agent
    uv run python scripts/review_claims.py prepare

    # Step 2: Run review agent (Claude Code reads each batch context
    #         and writes _review_batch_N.json)
    # → see printed instructions after prepare

    # Step 3: Show flagged claims for human review
    uv run python scripts/review_claims.py report

    # Step 4: Apply approved flags to DB
    uv run python scripts/review_claims.py apply [--dry-run]

    # Check status
    uv run python scripts/review_claims.py status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORK_DIR = Path("data/review")
BATCH_SIZE = 30  # Larger batches — classification is lighter than assessment


def _fetch_published_claims(conn) -> list[dict]:
    """Fetch all published claims with sighting info for review."""
    rows = conn.execute(
        """
        SELECT
            c.id, c.claim_slug, c.canonical_text_is, c.canonical_text_en,
            c.category, c.claim_type, c.verdict, c.explanation_is,
            c.confidence, c.substantive,
            COUNT(s.id) AS sighting_count
        FROM claims c
        LEFT JOIN claim_sightings s ON c.id = s.claim_id
        WHERE c.published = TRUE
        GROUP BY c.id
        ORDER BY c.category, c.claim_slug
        """
    ).fetchall()

    columns = [
        "claim_id", "claim_slug", "canonical_text_is", "canonical_text_en",
        "category", "claim_type", "verdict", "explanation_is",
        "confidence", "substantive", "sighting_count",
    ]

    return [dict(zip(columns, row)) for row in rows]


def _write_batch_context(batch: list[dict], batch_num: int) -> Path:
    """Write a context file for a batch of claims to be reviewed by a subagent."""
    path = WORK_DIR / f"_context_batch_{batch_num}.md"

    lines = [
        f"# Claim Substantiveness Review — Batch {batch_num}\n",
        "You are reviewing published claims from ESBvaktin.is, an independent",
        "fact-checking platform for Iceland's EU membership referendum (29 August 2026).",
        "",
        "## Task",
        "",
        "Classify each claim as **substantive** or **non-substantive**.",
        "",
        "**Substantive claims** are claims that:",
        "- Make factual assertions about policy, economics, law, or trade-offs",
        "- Contain verifiable data points, statistics, or comparisons",
        "- Assert cause-effect relationships or predictions",
        "- Make claims about how EU systems work or would affect Iceland",
        "",
        "**Non-substantive claims** are claims that:",
        "- State common knowledge or easily verified procedural facts",
        '  (e.g. "Samfylkingin and Viðreisn put EU membership back on the agenda")',
        "- Report party positions without factual content",
        '  (e.g. "Sjálfstæðisflokkurinn is against EU membership")',
        "- Are tautological or definitional",
        '  (e.g. "EU membership requires joining the Common Fisheries Policy")',
        "- State undisputed historical facts everyone agrees on",
        '  (e.g. "Iceland applied for EU membership in 2009")',
        "- Are meta-procedural about the referendum itself",
        '  (e.g. "A referendum will be held on 29 August 2026")',
        "- Express vague opinions without implicit factual claims",
        "",
        "**Important nuances:**",
        "- A claim about HOW a policy works IS substantive (even if well-known to experts)",
        "- A claim about WHETHER a party supports EU membership is NOT substantive",
        "- Claims with specific numbers or data points are almost always substantive",
        "- When in doubt, mark as substantive — we only want to flag clear non-substantive cases",
        "",
        f"## Claims (batch {batch_num})\n",
    ]

    for i, claim in enumerate(batch, 1):
        lines.append(f"### Claim {i} (claim_id: {claim['claim_id']})")
        lines.append("")
        lines.append(f"- **Text (IS):** {claim['canonical_text_is']}")
        if claim["canonical_text_en"]:
            lines.append(f"- **Text (EN):** {claim['canonical_text_en']}")
        lines.append(f"- **Category:** {claim['category']}")
        lines.append(f"- **Type:** {claim['claim_type']}")
        lines.append(f"- **Verdict:** {claim['verdict']}")
        lines.append(f"- **Sightings:** {claim['sighting_count']}")
        lines.append("")

    lines.extend([
        "## Output Format",
        "",
        f"Write a flat JSON array to `_review_batch_{batch_num}.json` (raw JSON, no markdown).",
        "Include ALL claims from this batch. For each:",
        "",
        "```json",
        "{",
        '  "claim_id": 123,',
        '  "substantive": true,',
        '  "reason": "Short explanation of why this is/isn\'t substantive"',
        "}",
        "```",
        "",
        "**Rules:**",
        "- Include every claim — don't skip any",
        "- When in doubt, mark `substantive: true`",
        "- Keep reasons concise (one sentence)",
        "- Write raw JSON only — no markdown fences, no commentary",
    ])

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def prepare():
    """Prepare context files for subagent review."""
    from esbvaktin.ground_truth.operations import get_connection

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    claims = _fetch_published_claims(conn)
    conn.close()

    print(f"Found {len(claims)} published claims")

    # Only review claims that are currently substantive (haven't been flagged yet)
    to_review = [c for c in claims if c["substantive"]]
    already_flagged = len(claims) - len(to_review)
    if already_flagged:
        print(f"  ({already_flagged} already flagged as non-substantive, skipping)")

    if not to_review:
        print("Nothing to review.")
        return

    # Split into batches
    batches = [
        to_review[i: i + BATCH_SIZE]
        for i in range(0, len(to_review), BATCH_SIZE)
    ]

    manifest = []
    for batch_num, batch in enumerate(batches, 1):
        path = _write_batch_context(batch, batch_num)
        manifest.append({
            "batch": batch_num,
            "context_file": str(path),
            "claims": [c["claim_id"] for c in batch],
        })
        print(f"  Batch {batch_num}: {len(batch)} claims → {path}")

    # Write manifest
    manifest_path = WORK_DIR / "_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write flat claims data for report/apply
    claims_path = WORK_DIR / "_claims_data.json"
    claims_path.write_text(
        json.dumps(to_review, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nManifest: {manifest_path}")
    print(f"\n{'=' * 70}")
    print("NEXT STEP: Run review agent for each batch.")
    print(f"{'=' * 70}")
    for batch_num, batch in enumerate(batches, 1):
        ctx = WORK_DIR / f"_context_batch_{batch_num}.md"
        out = WORK_DIR / f"_review_batch_{batch_num}.json"
        print(f"\n  Batch {batch_num} ({len(batch)} claims):")
        print(f"    Read:  {ctx}")
        print(f"    Write: {out}")

    print(f"\nAfter all batches are reviewed:")
    print(f"  uv run python scripts/review_claims.py report")


def _load_reviews() -> list[dict]:
    """Load all review batch outputs, return flat list."""
    from esbvaktin.pipeline.parse_outputs import _extract_json

    manifest = json.loads(
        (WORK_DIR / "_manifest.json").read_text(encoding="utf-8")
    )

    all_reviews = []
    for batch_info in manifest:
        batch_num = batch_info["batch"]
        output_path = WORK_DIR / f"_review_batch_{batch_num}.json"

        if not output_path.exists():
            print(f"  Batch {batch_num}: MISSING — {output_path}")
            continue

        try:
            raw_text = output_path.read_text(encoding="utf-8")
            items = json.loads(_extract_json(raw_text))
            all_reviews.extend(items)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Batch {batch_num}: JSON PARSE ERROR — {e}")

    return all_reviews


def report():
    """Show flagged claims for human review before applying."""
    reviews = _load_reviews()
    if not reviews:
        print("No review data found. Run `prepare` and the review agent first.")
        return

    # Load original claims for context
    claims_path = WORK_DIR / "_claims_data.json"
    claims_data = json.loads(claims_path.read_text(encoding="utf-8"))
    claims_by_id = {c["claim_id"]: c for c in claims_data}

    non_substantive = [r for r in reviews if not r.get("substantive", True)]
    substantive = [r for r in reviews if r.get("substantive", True)]

    print(f"{'=' * 70}")
    print(f"SUBSTANTIVENESS REVIEW REPORT")
    print(f"{'=' * 70}")
    print(f"  Total reviewed:     {len(reviews)}")
    print(f"  Substantive:        {len(substantive)}")
    print(f"  Non-substantive:    {len(non_substantive)}")
    print()

    if non_substantive:
        # Group by category
        by_cat: dict[str, list[dict]] = {}
        for r in non_substantive:
            claim = claims_by_id.get(r["claim_id"], {})
            cat = claim.get("category", "unknown")
            by_cat.setdefault(cat, []).append((r, claim))

        for cat in sorted(by_cat):
            print(f"\n  [{cat}]")
            for review, claim in by_cat[cat]:
                text = claim.get("canonical_text_is", "?")[:80]
                verdict = claim.get("verdict", "?")
                reason = review.get("reason", "")
                print(f"    #{review['claim_id']:4d} [{verdict:25s}] {text}")
                if reason:
                    print(f"           → {reason}")

    print(f"\nTo apply these flags:")
    print(f"  uv run python scripts/review_claims.py apply")
    print(f"  uv run python scripts/review_claims.py apply --dry-run  # preview only")


def apply(*, dry_run: bool = False):
    """Apply substantiveness flags to the database."""
    from esbvaktin.ground_truth.operations import get_connection

    reviews = _load_reviews()
    if not reviews:
        print("No review data found.")
        return

    non_substantive = [r for r in reviews if not r.get("substantive", True)]

    if not non_substantive:
        print("No claims flagged as non-substantive. Nothing to apply.")
        return

    ids = [r["claim_id"] for r in non_substantive]

    if dry_run:
        print(f"DRY RUN: Would flag {len(ids)} claims as non-substantive:")
        for r in non_substantive:
            print(f"  #{r['claim_id']}: {r.get('reason', '')}")
        return

    conn = get_connection()
    for claim_id in ids:
        conn.execute(
            "UPDATE claims SET substantive = FALSE WHERE id = %(id)s",
            {"id": claim_id},
        )
    conn.commit()
    conn.close()

    print(f"Flagged {len(ids)} claims as non-substantive.")
    print(f"\nNext: re-export entities to update credibility scores:")
    print(f"  uv run python scripts/export_entities.py --site-dir ~/esbvaktin-site")


def status():
    """Show substantiveness distribution."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()

    row = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE published = TRUE) AS published,
            COUNT(*) FILTER (WHERE published = TRUE AND substantive = TRUE) AS substantive,
            COUNT(*) FILTER (WHERE published = TRUE AND substantive = FALSE) AS non_substantive,
            COUNT(*) FILTER (WHERE published = FALSE) AS unpublished
        FROM claims
        """
    ).fetchone()

    published, substantive, non_substantive, unpublished = row

    # Breakdown by verdict for non-substantive
    verdict_rows = conn.execute(
        """
        SELECT verdict, COUNT(*)
        FROM claims
        WHERE published = TRUE AND substantive = FALSE
        GROUP BY verdict
        ORDER BY COUNT(*) DESC
        """
    ).fetchall()

    conn.close()

    print(f"{'=' * 50}")
    print(f"SUBSTANTIVENESS STATUS")
    print(f"{'=' * 50}")
    print(f"  Published:        {published}")
    print(f"    Substantive:    {substantive}")
    print(f"    Non-substantive: {non_substantive}")
    print(f"  Unpublished:      {unpublished}")

    if verdict_rows:
        print(f"\n  Non-substantive by verdict:")
        for verdict, count in verdict_rows:
            print(f"    {verdict}: {count}")

    # Check for pending review batches
    if WORK_DIR.exists():
        manifest_path = WORK_DIR / "_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            done = sum(
                1 for b in manifest
                if (WORK_DIR / f"_review_batch_{b['batch']}.json").exists()
            )
            pending = len(manifest) - done
            if done or pending:
                print(f"\n  Review batches: {done} done, {pending} pending")


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/review_claims.py [prepare|report|apply|status]")
        print("  prepare              Prepare context files for review agent")
        print("  report               Show flagged claims for review")
        print("  apply [--dry-run]    Apply flags to DB")
        print("  status               Show substantiveness distribution")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare()
    elif cmd == "report":
        report()
    elif cmd == "apply":
        dry_run = "--dry-run" in sys.argv
        apply(dry_run=dry_run)
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
