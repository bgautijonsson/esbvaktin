#!/usr/bin/env python3
"""Monthly high-decay evidence refresh sweep (fresh-01).

The fastest-decaying evidence topics — polling, party & org positions, currency —
go stale long before the generic 90-day `stale_evidence` view flags them. This sweep:

  1. collects the 90-day-stale evidence (all topics) AND the high-decay topics overdue
     by a shorter window,
  2. flags the published claims that cite that evidence for the next reassessment cycle
     (sets needs_reassessment — it does NOT reassess and NEVER publishes),
  3. prints a review note (which a human, or the scheduled-task agent, files to the
     vault) listing what to re-check and the human-gated next steps.

Nothing here changes a verdict or a publication state. Reassessment and any re-check of
source URLs are explicit, human-gated follow-ups (/reassess, link-check, evidence-hunt).

Usage:
    uv run python scripts/monthly_evidence_refresh.py            # flag + print note
    uv run python scripts/monthly_evidence_refresh.py --dry-run  # print note, flag nothing
"""

from __future__ import annotations

import sys
from datetime import date

# The four fastest-decaying topics (see CLAUDE.md / the monthly procedure).
HIGH_DECAY_TOPICS = ("polling", "party_positions", "org_positions", "currency")

# High-decay topics are refreshed on a tighter cadence than the 90-day stale view.
HIGH_DECAY_MAX_AGE_DAYS = 30

REASSESSMENT_REASON = "monthly_high_decay_refresh"


# ── Pure logic ───────────────────────────────────────────────────────


def _candidate(row: dict) -> dict:
    return {
        "evidence_id": row["evidence_id"],
        "topic": row.get("topic"),
        "days_stale": row.get("days_stale"),
    }


def merge_candidates(stale_rows: list[dict], high_decay_rows: list[dict]) -> list[dict]:
    """Combine the 90-day-stale sweep with the high-decay-topic sweep.

    Deduplicates by evidence_id and unions the reasons, so an entry that is both
    90-day-stale and in a high-decay topic carries both. Sorted most-stale first.
    """
    merged: dict[str, dict] = {}
    for rows, reason in ((stale_rows, "stale"), (high_decay_rows, "high_decay")):
        for row in rows:
            eid = row["evidence_id"]
            entry = merged.setdefault(eid, {**_candidate(row), "reasons": []})
            if reason not in entry["reasons"]:
                entry["reasons"].append(reason)
    return sorted(
        merged.values(),
        key=lambda c: (-(c.get("days_stale") or 0), c["evidence_id"]),
    )


def build_review_note(candidates: list[dict], queued_claim_count: int, today: date) -> str:
    """Render the markdown review note. Review-only: never frames anything as published."""
    high = [c for c in candidates if "high_decay" in c["reasons"]]
    stale_only = [c for c in candidates if "high_decay" not in c["reasons"]]

    def _line(c: dict) -> str:
        return f"- `{c['evidence_id']}` ({c.get('topic') or '?'}) — {c.get('days_stale', '?')} days since verified"

    lines = [
        f"# Evidence Refresh — {today.isoformat()}",
        "",
        f"{len(candidates)} evidence entries due for refresh "
        f"({len(high)} in high-decay topics, {len(stale_only)} other 90-day-stale). "
        f"{queued_claim_count} claims flagged for the next reassessment cycle.",
        "",
        "## High-decay topics (polling, party_positions, org_positions, currency)",
    ]
    lines += [
        _line(c) for c in sorted(high, key=lambda x: (x.get("topic") or "", x["evidence_id"]))
    ] or ["- none overdue"]
    lines += ["", "## Other stale evidence (90+ days)"]
    lines += [
        _line(c) for c in sorted(stale_only, key=lambda x: (x.get("topic") or "", x["evidence_id"]))
    ] or ["- none"]
    lines += [
        "",
        "## Next steps (human-gated — nothing changes automatically)",
        "1. Re-check the source URLs above: `uv run python scripts/check_evidence_urls.py check`",
        f"2. Review the {queued_claim_count} flagged claims and re-run verdicts: `/reassess`",
        "3. Refresh high-decay evidence where sources have moved on: `/evidence-hunt monthly`",
    ]
    return "\n".join(lines)


# ── Database I/O ─────────────────────────────────────────────────────


def fetch_stale_evidence(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT evidence_id, topic, source_name, last_verified, days_stale FROM stale_evidence"
    ).fetchall()
    return [
        {
            "evidence_id": r[0],
            "topic": r[1],
            "source_name": r[2],
            "last_verified": r[3],
            "days_stale": r[4],
        }
        for r in rows
    ]


def fetch_high_decay_overdue(conn, days: int = HIGH_DECAY_MAX_AGE_DAYS) -> list[dict]:
    rows = conn.execute(
        "SELECT evidence_id, topic, (CURRENT_DATE - last_verified) AS days_stale "
        "FROM evidence "
        "WHERE topic = ANY(%s) AND last_verified < CURRENT_DATE - make_interval(days => %s)",
        (list(HIGH_DECAY_TOPICS), days),
    ).fetchall()
    return [{"evidence_id": r[0], "topic": r[1], "days_stale": r[2]} for r in rows]


def claims_citing(conn, evidence_ids: list[str]) -> list[int]:
    """Published, non-hearsay claims that cite any of the given evidence IDs."""
    if not evidence_ids:
        return []
    ids = list(evidence_ids)
    rows = conn.execute(
        "SELECT id FROM claims "
        "WHERE (supporting_evidence && %s OR contradicting_evidence && %s) "
        "  AND published = TRUE AND epistemic_type != 'hearsay'",
        (ids, ids),
    ).fetchall()
    return [r[0] for r in rows]


def queue_reassessment(conn, claim_ids: list[int], reason: str = REASSESSMENT_REASON) -> int:
    """Flag claims for the next human-gated reassessment cycle.

    Sets needs_reassessment only — it never changes a verdict or the published flag.
    Returns the number of claims newly flagged.
    """
    if not claim_ids:
        return 0
    cur = conn.execute(
        "UPDATE claims SET needs_reassessment = TRUE, reassessment_reason = %s "
        "WHERE id = ANY(%s) AND needs_reassessment = FALSE",
        (reason, list(claim_ids)),
    )
    return cur.rowcount


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv

    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()
    try:
        candidates = merge_candidates(fetch_stale_evidence(conn), fetch_high_decay_overdue(conn))
        evidence_ids = [c["evidence_id"] for c in candidates]
        claim_ids = claims_citing(conn, evidence_ids)

        if dry_run:
            print("(dry-run: not flagging any claims)", file=sys.stderr)
            queued = len(claim_ids)
        else:
            queued = queue_reassessment(conn, claim_ids)
            conn.commit()

        print(build_review_note(candidates, queued, date.today()))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
