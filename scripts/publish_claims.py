#!/usr/bin/env python3
"""Manage claim publishing — safety net for the auto-publish workflow.

Claims are now auto-published at registration time. This script handles
edge cases: viewing unpublished claims, manually publishing/unpublishing
specific claims, and running one-time backfills.

Usage:
    uv run python scripts/publish_claims.py status             # Show publishing summary
    uv run python scripts/publish_claims.py eligible           # Show unpublished claims eligible for publishing
    uv run python scripts/publish_claims.py publish <id> ...   # Publish specific claims
    uv run python scripts/publish_claims.py unpublish <id> ... # Unpublish specific claims
    uv run python scripts/publish_claims.py backfill [--dry-run]  # Publish all eligible unpublished claims
"""

from __future__ import annotations

import sys


def _get_conn():
    from esbvaktin.ground_truth.operations import get_connection

    return get_connection()


def status():
    """Show publishing summary."""
    conn = _get_conn()

    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE published = TRUE) AS published,
            COUNT(*) FILTER (WHERE published = FALSE) AS unpublished,
            COUNT(*) FILTER (WHERE published = FALSE AND substantive = TRUE
                             AND verdict != 'unverifiable') AS eligible
        FROM claims
        """
    ).fetchone()

    total, published, unpublished, eligible = row

    verdict_rows = conn.execute(
        """
        SELECT verdict, COUNT(*)
        FROM claims
        WHERE published = FALSE
        GROUP BY verdict
        ORDER BY COUNT(*) DESC
        """
    ).fetchall()

    conn.close()

    print(f"{'=' * 50}")
    print("CLAIM PUBLISHING STATUS")
    print(f"{'=' * 50}")
    print(f"  Total claims:     {total}")
    print(f"  Published:        {published}")
    print(f"  Unpublished:      {unpublished}")
    print(f"  Eligible to publish: {eligible}")

    if verdict_rows:
        print("\n  Unpublished by verdict:")
        for verdict, count in verdict_rows:
            print(f"    {verdict}: {count}")


def eligible():
    """Show unpublished claims that meet auto-publish criteria."""
    conn = _get_conn()

    rows = conn.execute(
        """
        SELECT c.id, c.claim_slug, c.verdict, c.category, c.confidence,
               COUNT(s.id) AS sighting_count,
               LEFT(c.canonical_text_is, 80) AS text_preview
        FROM claims c
        LEFT JOIN claim_sightings s ON c.id = s.claim_id
        WHERE c.published = FALSE
          AND c.substantive = TRUE
          AND c.verdict != 'unverifiable'
        GROUP BY c.id
        ORDER BY COUNT(s.id) DESC, c.confidence DESC
        """
    ).fetchall()

    conn.close()

    if not rows:
        print("No eligible unpublished claims.")
        return

    print(f"{'ID':>5}  {'Verdict':<22}  {'Cat':<14}  {'Sight':>5}  {'Conf':>4}  Text")
    print("-" * 100)
    for cid, slug, verdict, cat, conf, sightings, text in rows:
        print(f"{cid:>5}  {verdict:<22}  {cat:<14}  {sightings:>5}  {conf:>4.2f}  {text}")

    print(f"\n{len(rows)} eligible claims.")


def publish(ids: list[int]):
    """Publish specific claims by ID."""
    conn = _get_conn()

    result = conn.execute(
        "UPDATE claims SET published = TRUE, updated_at = NOW() WHERE id = ANY(%s) AND published = FALSE",
        (ids,),
    )
    count = result.rowcount
    conn.commit()
    conn.close()

    print(f"Published {count} claim(s).")
    if count < len(ids):
        print(f"  ({len(ids) - count} were already published or not found)")


def unpublish(ids: list[int]):
    """Unpublish specific claims by ID."""
    conn = _get_conn()

    result = conn.execute(
        "UPDATE claims SET published = FALSE, updated_at = NOW() WHERE id = ANY(%s) AND published = TRUE",
        (ids,),
    )
    count = result.rowcount
    conn.commit()
    conn.close()

    print(f"Unpublished {count} claim(s).")
    if count < len(ids):
        print(f"  ({len(ids) - count} were already unpublished or not found)")


def backfill(dry_run: bool = False):
    """Publish all eligible unpublished claims (one-time backfill)."""
    conn = _get_conn()

    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM claims
        WHERE published = FALSE
          AND substantive = TRUE
          AND verdict != 'unverifiable'
        """
    ).fetchone()
    count = row[0]

    if count == 0:
        print("No eligible unpublished claims to backfill.")
        conn.close()
        return

    if dry_run:
        print(f"DRY RUN: Would publish {count} claims.")
        # Show breakdown
        rows = conn.execute(
            """
            SELECT verdict, COUNT(*)
            FROM claims
            WHERE published = FALSE AND substantive = TRUE AND verdict != 'unverifiable'
            GROUP BY verdict ORDER BY COUNT(*) DESC
            """
        ).fetchall()
        for verdict, n in rows:
            print(f"  {verdict}: {n}")
        conn.close()
        return

    result = conn.execute(
        """
        UPDATE claims
        SET published = TRUE, updated_at = NOW()
        WHERE published = FALSE
          AND substantive = TRUE
          AND verdict != 'unverifiable'
        """
    )
    actual = result.rowcount
    conn.commit()

    # Verify
    row = conn.execute(
        "SELECT COUNT(*) FILTER (WHERE published), COUNT(*) FILTER (WHERE NOT published) FROM claims"
    ).fetchone()
    conn.close()

    print(f"Published {actual} claims.")
    print(f"  Now published: {row[0]}, still unpublished: {row[1]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        status()
    elif cmd == "eligible":
        eligible()
    elif cmd == "publish":
        if len(sys.argv) < 3:
            print("Usage: publish_claims.py publish <id> [<id> ...]")
            sys.exit(1)
        ids = [int(x) for x in sys.argv[2:]]
        publish(ids)
    elif cmd == "unpublish":
        if len(sys.argv) < 3:
            print("Usage: publish_claims.py unpublish <id> [<id> ...]")
            sys.exit(1)
        ids = [int(x) for x in sys.argv[2:]]
        unpublish(ids)
    elif cmd == "backfill":
        dry_run = "--dry-run" in sys.argv
        backfill(dry_run=dry_run)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
