#!/usr/bin/env python3
"""Backfill epistemic_type on existing claims.

Phase 1 (classify): Heuristic pattern matching on canonical_text_is
Phase 2 (correct): Fix hearsay claims with non-unverifiable verdicts

Usage:
    uv run python scripts/backfill_epistemic_type.py status
    uv run python scripts/backfill_epistemic_type.py classify
    uv run python scripts/backfill_epistemic_type.py classify --apply
    uv run python scripts/backfill_epistemic_type.py correct
    uv run python scripts/backfill_epistemic_type.py correct --apply
"""

from __future__ import annotations

import re
import sys

from esbvaktin.ground_truth.operations import get_connection

# ---------------------------------------------------------------------------
# Heuristic patterns (Icelandic)
# ---------------------------------------------------------------------------

HEARSAY_PATTERNS = [
    r"ónafngreind\w*\s+(viðmælend|heimild)",
    r"(?:að|samkvæmt)\s+sögn",
    r"fregnir\s+herma",
    r"mun\s+hafa\s+sagt",
    r"er\s+(?:sagður|sögð|sagt)\s+hafa",
    r"samkvæmt\s+heimildum(?!\s+(?:ESB|staðreyndagrunns))",
    r"meint\w*\s+ummæl",
]

COUNTERFACTUAL_PATTERNS = [
    r"(?:ef|hefði)\s+\w+\s+hefði",
    r"hefði\s+(?:í\s+för\s+með\s+sér|orðið|leitt\s+til)",
    r"ef\s+\w+\s+væri\s+búi[ðn]",
    r"hefði\s+(?:getað|mátt|átt)",
]

PREDICTION_PATTERNS = [
    r"ef\s+(?:Ísland\s+)?(?:gengur|gengi|aðild\w*\s+næðist)\s+í",
    r"ef\s+aðild\s+(?:næðist|verður)",
    r"(?:myndi|mundi)\s+(?:þýða|leiða|hafa|verða)",
    r"mun\s+(?:verða|leiða|hafa)",
    r"(?:kæmi|koma)\s+til\s+með\s+að",
    r"ef\s+\w+\s+(?:myndi|mundi)",
    r"við\s+inngöngu\s+(?:myndi|mundi|mun)",
]


def classify_claim(text: str) -> str:
    """Classify epistemic type from claim text using heuristics."""
    text_lower = text.lower()
    for pattern in HEARSAY_PATTERNS:
        if re.search(pattern, text_lower):
            return "hearsay"
    for pattern in COUNTERFACTUAL_PATTERNS:
        if re.search(pattern, text_lower):
            return "counterfactual"
    for pattern in PREDICTION_PATTERNS:
        if re.search(pattern, text_lower):
            return "prediction"
    return "factual"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_status() -> None:
    conn = get_connection()
    rows = conn.execute("""
        SELECT epistemic_type, COUNT(*) as n,
               COUNT(*) FILTER (WHERE published) as published
        FROM claims
        GROUP BY epistemic_type
        ORDER BY n DESC
    """).fetchall()

    print("Epistemic type distribution:")
    for etype, n, pub in rows:
        print(f"  {etype:20s} {n:5d} ({pub} published)")

    hearsay_wrong = conn.execute("""
        SELECT COUNT(*) FROM claims
        WHERE epistemic_type = 'hearsay' AND verdict != 'unverifiable'
    """).fetchone()[0]
    if hearsay_wrong:
        print(
            f"\n  {hearsay_wrong} hearsay claims with non-unverifiable verdicts (need correction)"
        )

    conn.close()


def cmd_classify(apply: bool = False) -> None:
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, claim_slug, canonical_text_is, epistemic_type, verdict
        FROM claims
        WHERE epistemic_type = 'factual'
        ORDER BY id
    """).fetchall()

    changes: dict[int, tuple[str, str, str, str]] = {}
    for cid, slug, text, current, verdict in rows:
        new_type = classify_claim(text or "")
        if new_type != "factual":
            changes[cid] = (slug, (text or "")[:80], new_type, verdict)

    print(f"Scanned {len(rows)} factual claims. Proposed reclassifications: {len(changes)}")

    counts: dict[str, int] = {}
    for cid, (slug, text, new_type, verdict) in changes.items():
        counts[new_type] = counts.get(new_type, 0) + 1
        print(f"  [{new_type:15s}] {slug}: {text}...")

    print(f"\nSummary: {counts}")

    if not apply:
        print("\nDry run — use --apply to update the database")
        conn.close()
        return

    for cid, (slug, text, new_type, verdict) in changes.items():
        conn.execute(
            "UPDATE claims SET epistemic_type = %s, updated_at = NOW() WHERE id = %s",
            (new_type, cid),
        )
    conn.commit()
    print(f"\nUpdated {len(changes)} claims")
    conn.close()


def cmd_correct(apply: bool = False) -> None:
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, claim_slug, canonical_text_is, verdict, published
        FROM claims
        WHERE epistemic_type = 'hearsay' AND verdict != 'unverifiable'
    """).fetchall()

    if not rows:
        print("No hearsay claims need correction")
        conn.close()
        return

    print(f"Hearsay claims needing verdict correction: {len(rows)}")
    for cid, slug, text, verdict, published in rows:
        status = "published" if published else "unpublished"
        print(f"  {slug}: {verdict} -> unverifiable (was {status})")

    if not apply:
        print("\nDry run — use --apply to correct")
        conn.close()
        return

    conn.execute("""
        UPDATE claims SET
            verdict = 'unverifiable',
            published = TRUE,
            substantive = FALSE,
            explanation_is = 'Fullyrðingin byggir á ónafngreindum heimildum sem ekki er hægt að staðfesta.',
            version = version + 1,
            updated_at = NOW()
        WHERE epistemic_type = 'hearsay' AND verdict != 'unverifiable'
    """)
    conn.commit()
    total_hearsay = conn.execute(
        "SELECT COUNT(*) FROM claims WHERE epistemic_type = 'hearsay'"
    ).fetchone()[0]
    print(f"\nCorrected {len(rows)} hearsay claims (total hearsay: {total_hearsay})")
    conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: backfill_epistemic_type.py {status|classify|correct}")
        print("  status              Show epistemic type distribution")
        print("  classify [--apply]  Classify claims by epistemic type (heuristic)")
        print("  correct [--apply]   Fix hearsay claims with wrong verdicts")
        sys.exit(1)

    cmd = sys.argv[1]
    apply = "--apply" in sys.argv

    if cmd == "status":
        cmd_status()
    elif cmd == "classify":
        cmd_classify(apply=apply)
    elif cmd == "correct":
        cmd_correct(apply=apply)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
