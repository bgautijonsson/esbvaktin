#!/usr/bin/env python3
"""Improve Icelandic text quality on the claims table.

Mirrors scripts/improve_evidence_is.py but for the three public-facing
claim fields:

  - canonical_text_is   (shown in listings and scorecards)
  - explanation_is      (verdict body on detail pages)
  - missing_context_is  (amber "missing context" callout)

Uses a proofread hash (md5 over the three fields) to track which rows
have been corrected since their text last changed, so re-running is
safe and cheap.

Usage:
    uv run python scripts/improve_claims_is.py status
    uv run python scripts/improve_claims_is.py correct --dry-run
    uv run python scripts/improve_claims_is.py correct --since 2026-05-02
    uv run python scripts/improve_claims_is.py correct --limit 10
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # ensure MALSTADUR_API_KEY is available even when shell env is unset

from esbvaktin.utils.malstadur import (  # noqa: E402
    MalstadurAuthError,
    MalstadurClient,
    MalstadurError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FIELDS = ("canonical_text_is", "explanation_is", "missing_context_is")


def _get_connection():
    from esbvaktin.ground_truth.operations import get_connection

    return get_connection()


def _compute_hash(
    canonical_text_is: str | None,
    explanation_is: str | None,
    missing_context_is: str | None,
) -> str:
    """md5 of concatenated IS fields — used to detect text changes."""
    parts = (canonical_text_is or "") + (explanation_is or "") + (missing_context_is or "")
    return hashlib.md5(parts.encode("utf-8")).hexdigest()


# ── correct ───────────────────────────────────────────────────────────


def correct(args: argparse.Namespace) -> None:
    """Grammar-correct IS fields via Málstaður."""
    conn = _get_connection()

    where_clauses = ["published = TRUE", "canonical_text_is IS NOT NULL"]
    params: list = []
    if args.since:
        where_clauses.append("(created_at >= %s OR updated_at >= %s)")
        params.extend([args.since, args.since])
    where_sql = " AND ".join(where_clauses)

    sql = (
        "SELECT id, canonical_text_is, explanation_is, missing_context_is, "
        "is_proofread_hash "
        f"FROM claims WHERE {where_sql} ORDER BY id"
    )
    rows = conn.execute(sql, params).fetchall()

    # Filter to entries needing correction (hash mismatch or NULL)
    pending = []
    for cid, ctext, expl, mc, stored_hash in rows:
        current_hash = _compute_hash(ctext, expl, mc)
        if stored_hash != current_hash:
            pending.append(
                {
                    "id": cid,
                    "canonical_text_is": ctext,
                    "explanation_is": expl,
                    "missing_context_is": mc,
                }
            )

    if not pending:
        print("All claim IS text is up-to-date (hashes match). Nothing to correct.")
        conn.close()
        return

    limit = args.limit or len(pending)
    pending = pending[:limit]
    batch_chars = sum(len(entry.get(f) or "") for entry in pending for f in FIELDS)
    cost = batch_chars // 100

    print(f"Found {len(pending)} claims needing correction ({batch_chars:,} chars, ~{cost} kr)")
    if args.since:
        print(f"  Filter: created_at OR updated_at >= {args.since}")

    if args.dry_run:
        print("\n--dry-run: would correct these claims:")
        for entry in pending[:10]:
            fields = [f for f in FIELDS if entry.get(f)]
            chars = sum(len(entry[f]) for f in fields)
            print(f"  claim #{entry['id']:<6d} ({chars:5d} chars, fields: {', '.join(fields)})")
        if len(pending) > 10:
            print(f"  ... and {len(pending) - 10} more")
        conn.close()
        return

    try:
        client = MalstadurClient()
    except MalstadurError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    corrected_count = 0
    fields_fixed = 0
    chars_processed = 0
    errors: list[tuple[int, str]] = []
    smoke_logged = 0  # diff smoke check on the first few claims

    with client:
        for entry in pending:
            cid = entry["id"]
            # Build per-field text list for this entry (skip empties).
            field_texts: list[tuple[str, str]] = [
                (f, entry[f]) for f in FIELDS if entry.get(f) and entry[f].strip()
            ]
            if not field_texts:
                continue

            texts = [ft[1] for ft in field_texts]
            try:
                corrected_texts = client.correct_grammar(texts)
            except MalstadurAuthError as e:
                print(f"\nFATAL auth error — aborting run: {e}", file=sys.stderr)
                errors.append((cid, str(e)))
                break
            except MalstadurError as e:
                print(f"  Claim #{cid} API error: {e}")
                errors.append((cid, str(e)))
                continue
            except Exception as e:
                print(f"  Claim #{cid} unexpected error: {e}")
                errors.append((cid, str(e)))
                continue

            # Smoke check: print diff for the first few claims.
            if smoke_logged < 5:
                for (field, original), corrected in zip(field_texts, corrected_texts):
                    if corrected != original:
                        print(f"\n  [smoke] claim #{cid} {field}:")
                        print(f"    BEFORE: {original[:160]}")
                        print(f"    AFTER:  {corrected[:160]}")
                smoke_logged += 1

            # Apply corrections to entry dict.
            for (field, original), corrected in zip(field_texts, corrected_texts):
                if corrected != original:
                    entry[field] = corrected
                    fields_fixed += 1

            chars_processed += sum(len(t) for t in texts)

            new_hash = _compute_hash(
                entry.get("canonical_text_is"),
                entry.get("explanation_is"),
                entry.get("missing_context_is"),
            )
            try:
                conn.execute(
                    "UPDATE claims "
                    "SET canonical_text_is = %s, explanation_is = %s, "
                    "    missing_context_is = %s, is_proofread_hash = %s "
                    "WHERE id = %s",
                    (
                        entry.get("canonical_text_is"),
                        entry.get("explanation_is"),
                        entry.get("missing_context_is"),
                        new_hash,
                        cid,
                    ),
                )
                conn.commit()
                corrected_count += 1
            except Exception as e:
                print(f"  Claim #{cid} DB error: {e}")
                errors.append((cid, str(e)))

            if corrected_count % 25 == 0 and corrected_count > 0:
                print(
                    f"  [{corrected_count}/{len(pending)}] processed, "
                    f"{fields_fixed} fields changed, {chars_processed:,} chars"
                )

    conn.close()

    print(f"\n{'=' * 60}")
    print("Claim correction complete")
    print(f"  Claims processed:  {corrected_count}")
    print(f"  Fields changed:    {fields_fixed}")
    print(f"  Characters:        {chars_processed:,}")
    print(f"  Est. cost:         ~{chars_processed // 100} kr")
    if errors:
        print(f"  Errors:            {len(errors)}")
        for cid, err in errors[:20]:
            print(f"    claim #{cid}: {err}")
        if len(errors) > 20:
            print(f"    ... and {len(errors) - 20} more")
    print(f"{'=' * 60}")


# ── status ────────────────────────────────────────────────────────────


def status(args: argparse.Namespace) -> None:
    """Show what needs proofreading and estimated cost."""
    conn = _get_connection()

    total = conn.execute("SELECT COUNT(*) FROM claims WHERE published = TRUE").fetchone()[0]
    with_is = conn.execute(
        "SELECT COUNT(*) FROM claims WHERE published = TRUE AND canonical_text_is IS NOT NULL"
    ).fetchone()[0]
    with_hash = conn.execute(
        "SELECT COUNT(*) FROM claims WHERE published = TRUE AND is_proofread_hash IS NOT NULL"
    ).fetchone()[0]

    rows = conn.execute(
        "SELECT id, canonical_text_is, explanation_is, missing_context_is, "
        "       is_proofread_hash "
        "FROM claims WHERE published = TRUE AND canonical_text_is IS NOT NULL"
    ).fetchall()

    pending = 0
    pending_chars = 0
    for _cid, ctext, expl, mc, stored_hash in rows:
        if stored_hash != _compute_hash(ctext, expl, mc):
            pending += 1
            pending_chars += len(ctext or "") + len(expl or "") + len(mc or "")

    # Optional --since
    since_pending = since_chars = None
    if args.since:
        rows_since = conn.execute(
            "SELECT id, canonical_text_is, explanation_is, missing_context_is, "
            "       is_proofread_hash "
            "FROM claims "
            "WHERE published = TRUE AND canonical_text_is IS NOT NULL "
            "  AND (created_at >= %s OR updated_at >= %s)",
            (args.since, args.since),
        ).fetchall()
        since_pending = 0
        since_chars = 0
        for _cid, ctext, expl, mc, stored_hash in rows_since:
            if stored_hash != _compute_hash(ctext, expl, mc):
                since_pending += 1
                since_chars += len(ctext or "") + len(expl or "") + len(mc or "")

    conn.close()

    print(f"\n{'=' * 60}")
    print("CLAIM ICELANDIC QUALITY STATUS")
    print(f"{'=' * 60}")
    print(f"  Published claims:        {total}")
    print(f"  With IS text:            {with_is}/{total}")
    print(f"  Already proofread:       {with_hash}/{with_is}")
    print()
    print("Pending work:")
    print(
        f"  Total pending:           {pending:4d} claims ({pending_chars:,} chars, ~{pending_chars // 100} kr)"
    )
    if since_pending is not None:
        print(
            f"  Since {args.since}:    {since_pending:4d} claims "
            f"({since_chars:,} chars, ~{since_chars // 100} kr)"
        )
    print(f"{'=' * 60}")


# ── main ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Improve Icelandic text quality on the claims table"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    c_parser = subparsers.add_parser(
        "correct", help="Grammar-correct claim IS fields via Málstaður"
    )
    c_parser.add_argument("--dry-run", action="store_true", help="Preview without API calls")
    c_parser.add_argument("--limit", type=int, help="Max claims to process")
    c_parser.add_argument(
        "--since",
        help="Only process claims with created_at OR updated_at >= DATE (YYYY-MM-DD)",
    )

    s_parser = subparsers.add_parser("status", help="Show what needs work")
    s_parser.add_argument(
        "--since",
        help="Also show pending count restricted to created_at OR updated_at >= DATE",
    )

    args = parser.parse_args()

    if args.command == "correct":
        correct(args)
    elif args.command == "status":
        status(args)


if __name__ == "__main__":
    main()
