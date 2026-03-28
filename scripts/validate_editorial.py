"""Validate an editorial against the claim database.

Cross-references entities and claims mentioned in the editorial against
the DB to flag hearsay attribution errors, low-confidence claims presented
as fact, and entity/claim mismatches.

Usage:
    uv run python scripts/validate_editorial.py data/overviews/2026-W13/editorial.md
    uv run python scripts/validate_editorial.py data/overviews/2026-W13/editorial.md --week 2026-W13
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Attribution markers that indicate proper hearsay handling
ATTRIBUTION_MARKERS_IS = [
    "sagt er",
    "sögðu",
    "sagði",
    "fullyrt var",
    "fullyrt er",
    "samkvæmt frásögn",
    "samkvæmt heimildum",
    "ónafngreindir",
    "ónafngreindur",
    "meintum",
    "meint ",
    "að sögn",
    "hafi sagt",
    "hafi látið falla",
    "sagt hafa",
    "var haldið fram",
    "er haldið fram",
]


def _parse_week(slug: str) -> tuple[date, date]:
    """Parse ISO week slug to date range."""
    year, wn = slug.split("-W")
    jan4 = date(int(year), 1, 4)
    week1_mon = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = week1_mon + timedelta(weeks=int(wn) - 1)
    return monday, monday + timedelta(days=6)


def _load_week_claims(start: date, end: date) -> list[dict]:
    """Load all claims sighted in the period with epistemic type and confidence."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT DISTINCT c.id, c.canonical_text_is, c.verdict, c.epistemic_type,
               c.confidence, c.category
        FROM claims c
        JOIN claim_sightings s ON c.id = s.claim_id
        WHERE c.published = TRUE AND s.source_date BETWEEN %s AND %s
        """,
        (start, end),
    ).fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "text": r[1],
            "verdict": r[2],
            "epistemic_type": r[3] or "factual",
            "confidence": r[4] or 0.5,
            "category": r[5],
        }
        for r in rows
    ]


def _load_week_entities(start: date, end: date) -> list[dict]:
    """Load entities active in the period."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT DISTINCT s.speaker_name
        FROM claim_sightings s
        WHERE s.source_date BETWEEN %s AND %s
          AND s.speaker_name IS NOT NULL
        """,
        (start, end),
    ).fetchall()
    conn.close()
    return [{"name": r[0]} for r in rows]


def _find_claim_references(editorial: str, claims: list[dict]) -> list[dict]:
    """Find claims whose text appears (partially) in the editorial.

    Uses a simple substring match on key phrases extracted from canonical text.
    """
    matches = []
    editorial_lower = editorial.lower()

    for claim in claims:
        text = claim["text"]
        if not text:
            continue

        # Extract key phrases (3+ word chunks) from the canonical text
        words = text.split()
        for start_idx in range(len(words) - 2):
            phrase = " ".join(words[start_idx : start_idx + 4]).lower()
            # Strip punctuation for matching
            phrase_clean = re.sub(r"[\u201e\u201c.,;:!?]", "", phrase).strip()
            if len(phrase_clean) > 15 and phrase_clean in editorial_lower:
                matches.append(claim)
                break

    return matches


def _check_hearsay_attribution(editorial: str, claim: dict) -> dict | None:
    """Check if a hearsay claim reference has proper attribution markers."""
    # Find where in the editorial this claim is referenced
    words = claim["text"].split()
    match_pos = -1
    for start_idx in range(len(words) - 2):
        phrase = " ".join(words[start_idx : start_idx + 4]).lower()
        phrase_clean = re.sub(r"[\u201e\u201c.,;:!?]", "", phrase).strip()
        if len(phrase_clean) > 15:
            pos = editorial.lower().find(phrase_clean)
            if pos >= 0:
                match_pos = pos
                break

    if match_pos < 0:
        return None

    # Check surrounding context (200 chars before and after) for attribution markers
    context_start = max(0, match_pos - 200)
    context_end = min(len(editorial), match_pos + 200)
    context = editorial[context_start:context_end].lower()

    has_attribution = any(marker in context for marker in ATTRIBUTION_MARKERS_IS)

    if not has_attribution:
        return {
            "claim_id": claim["id"],
            "claim_text": claim["text"][:80],
            "issue": "Hlustaðarsögn án tilvísunarorða",
            "severity": "HIGH",
        }
    return None


def _check_low_confidence(editorial: str, claim: dict) -> dict | None:
    """Check if a low-confidence claim is presented without uncertainty markers."""
    uncertainty_markers = [
        "hugsanleg",
        "mögule",
        "óvíst",
        "ekki ljóst",
        "heimildir gefa ekki",
        "erfitt að staðfesta",
        "vantar gögn",
        "ábending",
    ]
    editorial_lower = editorial.lower()
    context_start = max(0, editorial_lower.find(claim["text"][:30].lower()) - 150)
    context_end = min(len(editorial), context_start + 400)
    context = editorial_lower[context_start:context_end]

    has_uncertainty = any(m in context for m in uncertainty_markers)
    if not has_uncertainty:
        return {
            "claim_id": claim["id"],
            "claim_text": claim["text"][:80],
            "confidence": claim["confidence"],
            "issue": f"Lítið traust ({claim['confidence']:.2f}) án óvissumerkja",
            "severity": "MEDIUM",
        }
    return None


def validate(editorial_path: Path, week_slug: str | None = None) -> list[dict]:
    """Run all validation checks on an editorial."""
    editorial = editorial_path.read_text(encoding="utf-8")

    # Determine week from path if not provided
    if not week_slug:
        week_slug = editorial_path.parent.name

    start, end = _parse_week(week_slug)
    claims = _load_week_claims(start, end)

    flags: list[dict] = []

    # 1. Find claims referenced in the editorial
    referenced = _find_claim_references(editorial, claims)

    # 2. Check hearsay claims for proper attribution
    hearsay_referenced = [c for c in referenced if c["epistemic_type"] == "hearsay"]
    for claim in hearsay_referenced:
        flag = _check_hearsay_attribution(editorial, claim)
        if flag:
            flags.append(flag)

    # 3. Check low-confidence claims
    low_conf = [c for c in referenced if c["confidence"] < 0.6]
    for claim in low_conf:
        flag = _check_low_confidence(editorial, claim)
        if flag:
            flags.append(flag)

    # 4. Count hearsay claims in the week that might be newsworthy
    all_hearsay = [c for c in claims if c["epistemic_type"] == "hearsay"]
    hearsay_in_editorial = len(hearsay_referenced)

    # 5. Summary stats
    stats = {
        "week": week_slug,
        "editorial_words": len(editorial.split()),
        "claims_in_period": len(claims),
        "claims_referenced": len(referenced),
        "hearsay_in_period": len(all_hearsay),
        "hearsay_referenced": hearsay_in_editorial,
        "flags": flags,
    }

    return stats


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: validate_editorial.py EDITORIAL_PATH [--week SLUG]")
        sys.exit(1)

    editorial_path = Path(sys.argv[1])
    if not editorial_path.exists():
        print(f"Error: {editorial_path} not found")
        sys.exit(1)

    week_slug = None
    if "--week" in sys.argv:
        idx = sys.argv.index("--week")
        if idx + 1 < len(sys.argv):
            week_slug = sys.argv[idx + 1]

    stats = validate(editorial_path, week_slug)

    # Print results
    print(f"Editorial Validation — {stats['week']}")
    print(f"  Words: {stats['editorial_words']}")
    print(f"  Claims in period: {stats['claims_in_period']}")
    print(f"  Claims referenced: {stats['claims_referenced']}")
    print(
        f"  Hearsay: {stats['hearsay_in_period']} in period,"
        f" {stats['hearsay_referenced']} referenced"
    )
    print()

    flags = stats["flags"]
    if flags:
        print(f"⚠️  {len(flags)} FLAG(S) FOUND:")
        print()
        for f in flags:
            sev = f["severity"]
            print(f"  [{sev}] {f['issue']}")
            print(f"         Claim {f['claim_id']}: {f['claim_text']}...")
            print()
        sys.exit(1)
    else:
        print("✓ No flags — editorial passes validation")


if __name__ == "__main__":
    main()
