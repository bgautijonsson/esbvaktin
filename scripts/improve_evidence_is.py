#!/usr/bin/env python3
"""Improve Icelandic text quality in the evidence database.

Two operations:
  translate-caveats  — translate English caveats to Icelandic via Málstaður
  correct            — grammar-correct statement_is, source_description_is,
                       caveats_is via Málstaður
  status             — show what needs work and estimated cost

Uses a proofread hash to track which entries have been corrected since their
text last changed. Re-running is safe and only processes new/changed text.

Usage:
    uv run python scripts/improve_evidence_is.py status
    uv run python scripts/improve_evidence_is.py translate-caveats --dry-run
    uv run python scripts/improve_evidence_is.py translate-caveats
    uv run python scripts/improve_evidence_is.py translate-caveats --limit 10
    uv run python scripts/improve_evidence_is.py correct --dry-run
    uv run python scripts/improve_evidence_is.py correct
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MALSTADUR_BASE = "https://api.malstadur.is/v1"

# Rate-limit: delay between API calls (increased to avoid 429s)
_CALL_DELAY = 0.5  # seconds
_MAX_RETRIES = 3
_BACKOFF_BASE = 10  # seconds — doubles each retry


# ── DB connection ─────────────────────────────────────────────────────

def _get_connection():
    from esbvaktin.ground_truth.operations import get_connection
    return get_connection()


# ── API helpers ───────────────────────────────────────────────────────

def _get_headers() -> dict[str, str]:
    key = os.environ.get("MALSTADUR_API_KEY", "")
    if not key:
        print("ERROR: MALSTADUR_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    return {
        "X-API-KEY": key,
        "Content-Type": "application/json",
    }


def _api_call_with_retry(
    client: httpx.Client,
    url: str,
    headers: dict,
    json_body: dict,
) -> dict:
    """Make an API call with exponential backoff on 429."""
    for attempt in range(_MAX_RETRIES + 1):
        resp = client.post(url, headers=headers, json=json_body, timeout=60)
        if resp.status_code in (429, 502, 503, 504):
            if attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE * (2 ** attempt)
                print(f"    {resp.status_code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()  # final attempt — let it raise
        resp.raise_for_status()
        return resp.json()
    return {}  # unreachable


def _translate(
    text: str, target_lang: str, headers: dict, client: httpx.Client
) -> str:
    """Translate text via Málstaður /v1/translate."""
    data = _api_call_with_retry(
        client,
        f"{MALSTADUR_BASE}/translate",
        headers,
        {"text": text, "targetLanguage": target_lang},
    )
    return data.get("text", "")


def _grammar_correct(
    texts: list[str], headers: dict, client: httpx.Client
) -> list[str]:
    """Correct texts via Málstaður /v1/grammar. Max 10 per call."""
    data = _api_call_with_retry(
        client,
        f"{MALSTADUR_BASE}/grammar",
        headers,
        {"texts": texts},
    )
    results = data.get("results", [])
    return [
        item.get("changedText", item.get("originalText", orig))
        for item, orig in zip(results, texts)
    ]


# ── Hash tracking ─────────────────────────────────────────────────────

def _compute_hash(
    statement_is: str | None,
    source_description_is: str | None,
    caveats_is: str | None,
) -> str:
    """md5 of concatenated IS fields — used to detect text changes."""
    parts = (statement_is or "") + (source_description_is or "") + (caveats_is or "")
    return hashlib.md5(parts.encode("utf-8")).hexdigest()


# ── translate-caveats ─────────────────────────────────────────────────

def translate_caveats(args: argparse.Namespace) -> None:
    """Translate English caveats to Icelandic."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT evidence_id, caveats "
        "FROM evidence "
        "WHERE caveats IS NOT NULL AND caveats != '' AND caveats_is IS NULL "
        "ORDER BY evidence_id"
    ).fetchall()

    if not rows:
        print("All caveats already translated. Nothing to do.")
        conn.close()
        return

    limit = args.limit or len(rows)
    rows = rows[:limit]
    batch_chars = sum(len(r[1]) for r in rows)
    cost = batch_chars // 100

    print(f"Found {len(rows)} caveats to translate ({batch_chars:,} chars, ~{cost} kr)")

    if args.dry_run:
        print("\n--dry-run: would translate these entries:")
        for eid, caveats in rows[:10]:
            print(f"  {eid:25s} ({len(caveats):4d} chars): {caveats[:80]}...")
        if len(rows) > 10:
            print(f"  ... and {len(rows) - 10} more")
        conn.close()
        return

    headers = _get_headers()
    client = httpx.Client()
    translated = 0
    chars_processed = 0
    errors: list[tuple[str, str]] = []

    for i, (eid, caveats) in enumerate(rows, 1):
        try:
            result = _translate(caveats, "is", headers, client)
            if not result.strip():
                print(f"  {eid}: empty translation, skipping")
                errors.append((eid, "empty translation"))
                continue

            # Update DB: set caveats_is, recompute hash
            cur = conn.execute(
                "SELECT statement_is, source_description_is FROM evidence WHERE evidence_id = %s",
                (eid,),
            )
            row = cur.fetchone()
            new_hash = _compute_hash(row[0], row[1], result)

            conn.execute(
                "UPDATE evidence SET caveats_is = %s, is_proofread_hash = %s "
                "WHERE evidence_id = %s",
                (result, new_hash, eid),
            )
            conn.commit()

            translated += 1
            chars_processed += len(caveats)

            if i % 20 == 0 or i == len(rows):
                print(f"  [{i}/{len(rows)}] {translated} translated, {chars_processed:,} chars")

            time.sleep(_CALL_DELAY)

        except Exception as e:
            print(f"  {eid}: ERROR — {e}")
            errors.append((eid, str(e)))

    client.close()
    conn.close()

    print(f"\n{'='*60}")
    print("Translation complete")
    print(f"  Translated:  {translated}")
    print(f"  Characters:  {chars_processed:,}")
    print(f"  Est. cost:   ~{chars_processed // 100} kr")
    if errors:
        print(f"  Errors:      {len(errors)}")
        for eid, err in errors:
            print(f"    {eid}: {err}")
    print(f"{'='*60}")


# ── correct ───────────────────────────────────────────────────────────

def correct(args: argparse.Namespace) -> None:
    """Grammar-correct IS fields via Málstaður."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT evidence_id, statement_is, source_description_is, caveats_is, is_proofread_hash "
        "FROM evidence "
        "WHERE statement_is IS NOT NULL "
        "ORDER BY evidence_id"
    ).fetchall()

    # Filter to entries needing correction (hash mismatch or NULL)
    pending = []
    for eid, stmt_is, desc_is, cav_is, stored_hash in rows:
        current_hash = _compute_hash(stmt_is, desc_is, cav_is)
        if stored_hash != current_hash:
            pending.append({
                "evidence_id": eid,
                "statement_is": stmt_is,
                "source_description_is": desc_is,
                "caveats_is": cav_is,
            })

    if not pending:
        print("All IS text is up-to-date (hashes match). Nothing to correct.")
        conn.close()
        return

    limit = args.limit or len(pending)
    pending = pending[:limit]
    is_fields = ("statement_is", "source_description_is", "caveats_is")
    batch_chars = sum(
        len(entry.get(f) or "") for entry in pending for f in is_fields
    )
    cost = batch_chars // 100

    print(
        f"Found {len(pending)} entries needing correction"
        f" ({batch_chars:,} chars, ~{cost} kr)"
    )

    if args.dry_run:
        print("\n--dry-run: would correct these entries:")
        for entry in pending[:10]:
            fields = [f for f in is_fields if entry.get(f)]
            chars = sum(len(entry[f]) for f in fields)
            print(
                f"  {entry['evidence_id']:25s}"
                f" ({chars:4d} chars, fields: {', '.join(fields)})"
            )
        if len(pending) > 10:
            print(f"  ... and {len(pending) - 10} more")
        conn.close()
        return

    headers = _get_headers()
    client = httpx.Client()
    corrected_count = 0
    fields_fixed = 0
    chars_processed = 0
    errors: list[tuple[str, str]] = []

    # Process entries — collect texts into batches of 10 for the grammar API
    # Each entry can have up to 3 fields, so we batch field-by-field
    i = 0
    while i < len(pending):
        # Build a batch of up to 10 texts with their metadata
        batch_items: list[tuple[dict, str, str]] = []  # (entry, field_name, text)
        for entry in pending[i:]:
            for field in ("statement_is", "source_description_is", "caveats_is"):
                val = entry.get(field)
                if val and val.strip():
                    batch_items.append((entry, field, val))
                    if len(batch_items) >= 10:
                        break
            if len(batch_items) >= 10:
                break

        if not batch_items:
            break

        texts = [item[2] for item in batch_items]

        try:
            corrected_texts = _grammar_correct(texts, headers, client)

            # Apply corrections back to entries
            entries_touched: set[str] = set()
            for (entry, field, original), corrected in zip(batch_items, corrected_texts):
                if corrected != original:
                    entry[field] = corrected
                    fields_fixed += 1
                entries_touched.add(entry["evidence_id"])

            chars_processed += sum(len(t) for t in texts)
            time.sleep(_CALL_DELAY)

        except Exception as e:
            eids = {item[0]["evidence_id"] for item in batch_items}
            print(f"  Batch error ({', '.join(eids)}): {e}")
            for eid in eids:
                errors.append((eid, str(e)))

        # Find entries fully processed in this batch and write them
        # An entry is fully processed when all its fields have been sent
        batch_eids = {item[0]["evidence_id"] for item in batch_items}
        for eid in batch_eids:
            entry = next(e for e in pending if e["evidence_id"] == eid)
            # Check if all fields for this entry were in this batch
            remaining_fields = [
                f for f in ("statement_is", "source_description_is", "caveats_is")
                if entry.get(f) and not any(
                    bi[0]["evidence_id"] == eid and bi[1] == f for bi in batch_items
                )
            ]
            if not remaining_fields:
                # All fields processed — write to DB
                new_hash = _compute_hash(
                    entry.get("statement_is"),
                    entry.get("source_description_is"),
                    entry.get("caveats_is"),
                )
                try:
                    conn.execute(
                        "UPDATE evidence "
                        "SET statement_is = %s, source_description_is = %s, "
                        "    caveats_is = %s, is_proofread_hash = %s "
                        "WHERE evidence_id = %s",
                        (
                            entry.get("statement_is"),
                            entry.get("source_description_is"),
                            entry.get("caveats_is"),
                            new_hash,
                            eid,
                        ),
                    )
                    conn.commit()
                    corrected_count += 1
                except Exception as e:
                    print(f"  DB error for {eid}: {e}")
                    errors.append((eid, str(e)))

        # Advance past all entries that were in this batch
        processed_eids = batch_eids
        while i < len(pending) and pending[i]["evidence_id"] in processed_eids:
            i += 1

        if corrected_count % 20 == 0 and corrected_count > 0:
            print(
                f"  [{corrected_count}/{len(pending)}] corrected,"
                f" {fields_fixed} fields fixed, {chars_processed:,} chars"
            )

    client.close()
    conn.close()

    print(f"\n{'='*60}")
    print("Correction complete")
    print(f"  Entries processed: {corrected_count}")
    print(f"  Fields corrected:  {fields_fixed}")
    print(f"  Characters:        {chars_processed:,}")
    print(f"  Est. cost:         ~{chars_processed // 100} kr")
    if errors:
        print(f"  Errors:            {len(errors)}")
        for eid, err in errors:
            print(f"    {eid}: {err}")
    print(f"{'='*60}")


# ── status ────────────────────────────────────────────────────────────

def status(args: argparse.Namespace) -> None:
    """Show what needs translation/correction and estimated cost."""
    conn = _get_connection()

    total = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    with_caveats = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE caveats IS NOT NULL AND caveats != ''"
    ).fetchone()[0]
    with_caveats_is = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE caveats_is IS NOT NULL"
    ).fetchone()[0]
    with_statement_is = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE statement_is IS NOT NULL"
    ).fetchone()[0]

    # Caveats needing translation
    caveats_pending = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(caveats)), 0) "
        "FROM evidence WHERE caveats IS NOT NULL AND caveats != '' AND caveats_is IS NULL"
    ).fetchone()

    # Entries needing proofreading (hash mismatch or NULL)
    rows = conn.execute(
        "SELECT evidence_id, statement_is, source_description_is, caveats_is, is_proofread_hash "
        "FROM evidence WHERE statement_is IS NOT NULL"
    ).fetchall()

    proofread_pending = 0
    proofread_chars = 0
    for eid, stmt_is, desc_is, cav_is, stored_hash in rows:
        current_hash = _compute_hash(stmt_is, desc_is, cav_is)
        if stored_hash != current_hash:
            proofread_pending += 1
            proofread_chars += len(stmt_is or "")
            proofread_chars += len(desc_is or "")
            proofread_chars += len(cav_is or "")

    conn.close()

    print(f"\n{'='*60}")
    print("EVIDENCE ICELANDIC QUALITY STATUS")
    print(f"{'='*60}")
    print(f"  Total evidence:      {total}")
    print(f"  With statement_is:   {with_statement_is}/{total}")
    print(f"  With caveats (EN):   {with_caveats}")
    print(f"  With caveats_is:     {with_caveats_is}/{with_caveats}")
    print()
    cav_count, cav_chars = caveats_pending
    cav_cost = cav_chars // 100
    proof_cost = proofread_chars // 100

    print("Pending work:")
    print(f"  Caveats to translate:  {cav_count:3d} entries"
          f" ({cav_chars:,} chars, ~{cav_cost} kr)")
    print(f"  Entries to proofread:  {proofread_pending:3d} entries"
          f" ({proofread_chars:,} chars, ~{proof_cost} kr)")
    print(f"  Total est. cost:       ~{cav_cost + proof_cost} kr")
    print(f"{'='*60}")


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Improve Icelandic text quality in the evidence database"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # translate-caveats
    tc_parser = subparsers.add_parser(
        "translate-caveats", help="Translate English caveats to Icelandic"
    )
    tc_parser.add_argument("--dry-run", action="store_true", help="Preview without API calls")
    tc_parser.add_argument("--limit", type=int, help="Max entries to process")

    # correct
    c_parser = subparsers.add_parser(
        "correct", help="Grammar-correct IS fields via Málstaður"
    )
    c_parser.add_argument("--dry-run", action="store_true", help="Preview without API calls")
    c_parser.add_argument("--limit", type=int, help="Max entries to process")

    # status
    subparsers.add_parser("status", help="Show what needs work")

    args = parser.parse_args()

    if args.command == "translate-caveats":
        translate_caveats(args)
    elif args.command == "correct":
        correct(args)
    elif args.command == "status":
        status(args)


if __name__ == "__main__":
    main()
