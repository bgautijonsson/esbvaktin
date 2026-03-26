#!/usr/bin/env python3
"""Audit claim verdicts for internal consistency.

Detects four patterns where verdicts may not match their own evidence:

  Pattern 1 — Overconfident verdicts:
    Explanation acknowledges significant caveats (long missing_context)
    but verdict is 'supported' with high confidence.

  Pattern 2 — Denominator confusion:
    Claims using scope-broadening language ("megnið", "flest", "öll")
    that may apply evidence about a subset to a claim about the whole.

  Pattern 3 — Sighting verdict drift:
    The same claim gets different verdicts when assessed in different
    article/speech contexts. Signals that the canonical verdict may
    not reflect the full picture.

  Pattern 4 — Contradicting evidence ignored:
    Claims that list contradicting_evidence entries but still have
    a 'supported' verdict.

Usage:
    uv run python scripts/audit_claims.py report            # Full audit report
    uv run python scripts/audit_claims.py candidates        # Priority reassessment list
    uv run python scripts/audit_claims.py candidates --json # Machine-readable
    uv run python scripts/audit_claims.py status            # Quick summary
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Pattern 1 thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.85
MIN_MISSING_CONTEXT_LEN = 80  # chars — below this, caveats are likely trivial

# Pattern 2 — Icelandic scope-broadening words
SCOPE_WORDS_PATTERN = r"(megnið|flest|langflest|meirihlut|allra|öll |alls )"

# Pattern 3 — minimum mismatch count to flag
MIN_SIGHTING_MISMATCHES = 1

# Candidate scoring weights
WEIGHT_PATTERN_1 = 1.0
WEIGHT_PATTERN_3 = 2.0  # Sighting drift is strongest signal
WEIGHT_PATTERN_4 = 1.5
WEIGHT_PUBLISHED = 1.5  # Published claims are higher priority


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ClaimFlag:
    claim_id: int
    claim_slug: str
    canonical_text_is: str
    verdict: str
    confidence: float
    published: bool
    patterns: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    score: float = 0.0


# ---------------------------------------------------------------------------
# Pattern detection queries
# ---------------------------------------------------------------------------


def _pattern_1_overconfident(conn) -> list[ClaimFlag]:
    """Supported claims with high confidence but substantial missing context."""
    rows = conn.execute(
        """
        SELECT id, claim_slug, canonical_text_is, verdict, confidence, published,
               length(missing_context_is) as ctx_len,
               left(missing_context_is, 300) as ctx_preview
        FROM claims
        WHERE verdict = 'supported'
          AND confidence >= %(threshold)s
          AND missing_context_is IS NOT NULL
          AND length(missing_context_is) >= %(min_len)s
          AND epistemic_type != 'hearsay'
        ORDER BY confidence DESC, length(missing_context_is) DESC
        """,
        {"threshold": HIGH_CONFIDENCE_THRESHOLD, "min_len": MIN_MISSING_CONTEXT_LEN},
    ).fetchall()

    flags = []
    for r in rows:
        flag = ClaimFlag(
            claim_id=r[0],
            claim_slug=r[1],
            canonical_text_is=r[2],
            verdict=r[3],
            confidence=r[4],
            published=r[5],
            patterns=["overconfident"],
            details={
                "missing_context_length": r[6],
                "missing_context_preview": r[7],
            },
        )
        flags.append(flag)

    return flags


def _pattern_2_denominator(conn) -> list[ClaimFlag]:
    """Supported claims with scope-broadening language — denominator confusion risk."""
    rows = conn.execute(
        f"""
        SELECT id, claim_slug, canonical_text_is, verdict, confidence, published,
               left(missing_context_is, 300) as ctx_preview,
               (regexp_matches(canonical_text_is, '{SCOPE_WORDS_PATTERN}', 'i'))[1] as matched_word
        FROM claims
        WHERE verdict = 'supported'
          AND canonical_text_is ~* '{SCOPE_WORDS_PATTERN}'
          AND epistemic_type != 'hearsay'
        ORDER BY confidence DESC
        """,
    ).fetchall()

    flags = []
    for r in rows:
        flag = ClaimFlag(
            claim_id=r[0],
            claim_slug=r[1],
            canonical_text_is=r[2],
            verdict=r[3],
            confidence=r[4],
            published=r[5],
            patterns=["denominator_confusion"],
            details={
                "scope_word": r[7],
                "missing_context_preview": r[6],
            },
        )
        flags.append(flag)

    return flags


def _pattern_3_sighting_drift(conn) -> list[ClaimFlag]:
    """Claims where sighting verdicts disagree with canonical verdict."""
    rows = conn.execute(
        """
        SELECT c.id, c.claim_slug, c.canonical_text_is, c.verdict, c.confidence,
               c.published,
               COUNT(*) as total_sightings,
               COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END) as mismatches,
               array_agg(DISTINCT cs.speech_verdict) FILTER (WHERE cs.speech_verdict != c.verdict)
                 as divergent_verdicts
        FROM claims c
        JOIN claim_sightings cs ON c.id = cs.claim_id
        WHERE cs.speech_verdict IS NOT NULL
          AND c.epistemic_type != 'hearsay'
        GROUP BY c.id, c.claim_slug, c.canonical_text_is, c.verdict, c.confidence, c.published
        HAVING COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END) >= %(min)s
        ORDER BY COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END) DESC
        """,
        {"min": MIN_SIGHTING_MISMATCHES},
    ).fetchall()

    flags = []
    for r in rows:
        flag = ClaimFlag(
            claim_id=r[0],
            claim_slug=r[1],
            canonical_text_is=r[2],
            verdict=r[3],
            confidence=r[4],
            published=r[5],
            patterns=["sighting_drift"],
            details={
                "total_sightings": r[6],
                "mismatches": r[7],
                "divergent_verdicts": r[8],
            },
        )
        flags.append(flag)

    return flags


def _pattern_4_contradicting_ignored(conn) -> list[ClaimFlag]:
    """Supported claims that list contradicting evidence."""
    rows = conn.execute(
        """
        SELECT id, claim_slug, canonical_text_is, verdict, confidence, published,
               contradicting_evidence,
               array_length(contradicting_evidence, 1) as contra_count,
               array_length(supporting_evidence, 1) as support_count
        FROM claims
        WHERE verdict = 'supported'
          AND contradicting_evidence IS NOT NULL
          AND array_length(contradicting_evidence, 1) > 0
          AND epistemic_type != 'hearsay'
        ORDER BY array_length(contradicting_evidence, 1) DESC
        """,
    ).fetchall()

    flags = []
    for r in rows:
        flag = ClaimFlag(
            claim_id=r[0],
            claim_slug=r[1],
            canonical_text_is=r[2],
            verdict=r[3],
            confidence=r[4],
            published=r[5],
            patterns=["contradicting_ignored"],
            details={
                "contradicting_evidence": r[6],
                "contra_count": r[7],
                "support_count": r[8],
            },
        )
        flags.append(flag)

    return flags


# ---------------------------------------------------------------------------
# Scoring and merging
# ---------------------------------------------------------------------------


def _merge_flags(all_flags: list[list[ClaimFlag]]) -> list[ClaimFlag]:
    """Merge flags from multiple patterns into a single list, combining patterns
    for the same claim and computing a composite risk score."""
    by_id: dict[int, ClaimFlag] = {}

    for pattern_flags in all_flags:
        for flag in pattern_flags:
            if flag.claim_id in by_id:
                existing = by_id[flag.claim_id]
                existing.patterns.extend(flag.patterns)
                existing.details.update(flag.details)
            else:
                by_id[flag.claim_id] = flag

    # Score each claim
    for flag in by_id.values():
        score = 0.0
        if "overconfident" in flag.patterns:
            # Scale by context length and confidence
            ctx_len = flag.details.get("missing_context_length", 0)
            score += WEIGHT_PATTERN_1 * (ctx_len / 200) * flag.confidence
        if "denominator_confusion" in flag.patterns:
            score += WEIGHT_PATTERN_1  # Fixed weight — needs manual review
        if "sighting_drift" in flag.patterns:
            mismatches = flag.details.get("mismatches", 0)
            total = flag.details.get("total_sightings", 1)
            drift_ratio = mismatches / max(total, 1)
            score += WEIGHT_PATTERN_3 * drift_ratio * (1 + mismatches)
        if "contradicting_ignored" in flag.patterns:
            contra = flag.details.get("contra_count", 0)
            score += WEIGHT_PATTERN_4 * contra
        if flag.published:
            score *= WEIGHT_PUBLISHED
        flag.score = round(score, 2)

    return sorted(by_id.values(), key=lambda f: -f.score)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def report():
    """Full audit report with all four patterns."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()

    p1 = _pattern_1_overconfident(conn)
    p2 = _pattern_2_denominator(conn)
    p3 = _pattern_3_sighting_drift(conn)
    p4 = _pattern_4_contradicting_ignored(conn)

    conn.close()

    merged = _merge_flags([p1, p2, p3, p4])

    # Summary
    print(f"\n{'=' * 70}")
    print("CLAIM VERDICT AUDIT REPORT")
    print(f"{'=' * 70}")
    print(f"  Pattern 1 — Overconfident verdicts:     {len(p1)} claims")
    print(f"  Pattern 2 — Denominator confusion:      {len(p2)} claims")
    print(f"  Pattern 3 — Sighting verdict drift:     {len(p3)} claims")
    print(f"  Pattern 4 — Contradicting evidence:     {len(p4)} claims")
    print(f"  Unique claims flagged:                  {len(merged)}")

    multi = [f for f in merged if len(f.patterns) > 1]
    print(f"  Claims with multiple patterns:          {len(multi)}")

    published = [f for f in merged if f.published]
    print(f"  Published claims flagged:               {len(published)}")

    # Pattern 3 detail — most actionable
    print(f"\n{'─' * 70}")
    print("PATTERN 3: SIGHTING VERDICT DRIFT (highest signal)")
    print(f"{'─' * 70}")

    # Focus on supported → partially_supported drift
    drift_down = [
        f
        for f in p3
        if f.verdict == "supported"
        and "partially_supported" in (f.details.get("divergent_verdicts") or [])
    ]
    print(f"\n  Supported claims with partially_supported sightings: {len(drift_down)}")

    for f in sorted(drift_down, key=lambda x: -x.details.get("mismatches", 0))[:15]:
        mis = f.details.get("mismatches", 0)
        total = f.details.get("total_sightings", 0)
        dvs = f.details.get("divergent_verdicts", [])
        print(f"\n  [{f.claim_id}] {f.canonical_text_is[:100]}...")
        print(f"    Canonical: {f.verdict} ({f.confidence})")
        print(f"    Sightings: {mis}/{total} disagree → {dvs}")
        print(f"    Published: {'yes' if f.published else 'no'}")

    # Pattern 4 detail
    print(f"\n{'─' * 70}")
    print("PATTERN 4: CONTRADICTING EVIDENCE PRESENT BUT STILL SUPPORTED")
    print(f"{'─' * 70}")
    for f in p4:
        contra = f.details.get("contradicting_evidence", [])
        support = f.details.get("support_count", 0)
        print(f"\n  [{f.claim_id}] {f.canonical_text_is[:100]}...")
        print(f"    Supporting: {support}, Contradicting: {contra}")
        print(f"    Confidence: {f.confidence}, Published: {'yes' if f.published else 'no'}")

    # Multi-pattern claims — highest risk
    if multi:
        print(f"\n{'─' * 70}")
        print("MULTI-PATTERN FLAGS (highest risk)")
        print(f"{'─' * 70}")
        for f in multi[:20]:
            print(f"\n  [{f.claim_id}] score={f.score} patterns={f.patterns}")
            print(f"    {f.canonical_text_is[:100]}...")
            print(
                f"    Verdict: {f.verdict} ({f.confidence}), "
                f"Published: {'yes' if f.published else 'no'}"
            )

    print("\nFor reassessment candidates: uv run python scripts/audit_claims.py candidates")


def candidates(as_json: bool = False):
    """Priority list of claims for reassessment, sorted by risk score."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()
    p1 = _pattern_1_overconfident(conn)
    p2 = _pattern_2_denominator(conn)
    p3 = _pattern_3_sighting_drift(conn)
    p4 = _pattern_4_contradicting_ignored(conn)
    conn.close()

    merged = _merge_flags([p1, p2, p3, p4])

    # Focus on multi-pattern + high-score claims
    # Threshold: score >= 2.0 OR multiple patterns
    priority = [f for f in merged if f.score >= 2.0 or len(f.patterns) > 1]

    if as_json:
        output = [
            {
                "claim_id": f.claim_id,
                "claim_slug": f.claim_slug,
                "canonical_text_is": f.canonical_text_is,
                "verdict": f.verdict,
                "confidence": f.confidence,
                "published": f.published,
                "patterns": f.patterns,
                "score": f.score,
                "details": {k: v for k, v in f.details.items() if k != "missing_context_preview"},
            }
            for f in priority
        ]
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    print(f"\n{'=' * 70}")
    print(f"PRIORITY REASSESSMENT CANDIDATES ({len(priority)} claims)")
    print(f"{'=' * 70}")
    print(
        f"  Scoring: sighting drift (×{WEIGHT_PATTERN_3}) > contradicting evidence "
        f"(×{WEIGHT_PATTERN_4}) > overconfident (×{WEIGHT_PATTERN_1})"
    )
    print(f"  Published claims get ×{WEIGHT_PUBLISHED} multiplier")

    for i, f in enumerate(priority[:30], 1):
        print(f"\n  {i}. [{f.claim_id}] score={f.score}  patterns={','.join(f.patterns)}")
        print(f"     {f.canonical_text_is[:110]}")
        print(f"     Verdict: {f.verdict} ({f.confidence}) {'📢 PUBLISHED' if f.published else ''}")
        if "sighting_drift" in f.patterns:
            mis = f.details.get("mismatches", 0)
            total = f.details.get("total_sightings", 0)
            dvs = f.details.get("divergent_verdicts", [])
            print(f"     Drift: {mis}/{total} sightings disagree → {dvs}")
        if "contradicting_ignored" in f.patterns:
            print(f"     Contradicting: {f.details.get('contradicting_evidence', [])}")

    if len(priority) > 30:
        print(f"\n  ... and {len(priority) - 30} more. Use --json for full list.")


def status():
    """Quick summary of verdict distribution and audit signals."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()

    # Verdict distribution
    rows = conn.execute(
        "SELECT verdict, COUNT(*) FROM claims GROUP BY verdict ORDER BY COUNT(*) DESC"
    ).fetchall()
    print("Verdict distribution:")
    for verdict, count in rows:
        print(f"  {verdict}: {count}")

    total = sum(r[1] for r in rows)
    supported = next((r[1] for r in rows if r[0] == "supported"), 0)

    # Quick pattern counts
    p1_count = conn.execute(
        """
        SELECT COUNT(*) FROM claims
        WHERE verdict = 'supported' AND confidence >= %(t)s
          AND missing_context_is IS NOT NULL AND length(missing_context_is) >= %(m)s
          AND epistemic_type != 'hearsay'
        """,
        {"t": HIGH_CONFIDENCE_THRESHOLD, "m": MIN_MISSING_CONTEXT_LEN},
    ).fetchone()[0]

    p3_count = conn.execute(
        """
        SELECT COUNT(DISTINCT c.id)
        FROM claims c JOIN claim_sightings cs ON c.id = cs.claim_id
        WHERE c.verdict = 'supported' AND cs.speech_verdict = 'partially_supported'
          AND c.epistemic_type != 'hearsay'
        """,
    ).fetchone()[0]

    p4_count = conn.execute(
        """
        SELECT COUNT(*) FROM claims
        WHERE verdict = 'supported'
          AND contradicting_evidence IS NOT NULL
          AND array_length(contradicting_evidence, 1) > 0
          AND epistemic_type != 'hearsay'
        """,
    ).fetchone()[0]

    conn.close()

    print(f"\nTotal claims: {total}")
    print(f"Supported: {supported} ({100 * supported / total:.1f}%)")
    print("\nAudit signals:")
    print(f"  P1 — Overconfident (supported + caveats + high conf): {p1_count}")
    print(f"  P3 — Sighting drift (supported→partial):              {p3_count}")
    print(f"  P4 — Contradicting evidence but supported:            {p4_count}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/audit_claims.py [report|candidates|status]")
        print("  report       Full audit report with all four patterns")
        print("  candidates   Priority reassessment list (add --json for machine-readable)")
        print("  status       Quick summary")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "report":
        report()
    elif cmd == "candidates":
        candidates(as_json="--json" in sys.argv)
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
