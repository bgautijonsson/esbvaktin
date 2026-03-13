#!/usr/bin/env python3
"""Check which unverifiable claims now have matching evidence (read-only scout).

Queries each unverifiable claim against the evidence DB via semantic search
and reports which ones now have strong enough matches to be re-assessed.
This is a diagnostic tool — to actually run reassessment, use reassess_claims.py.

Usage:
    uv run python scripts/reassess_unverifiable.py           # Report only

See also:
    uv run python scripts/reassess_claims.py prepare         # Prepare full reassessment (unverifiable + partial)
"""


from esbvaktin.ground_truth.operations import get_connection, search_evidence

SIMILARITY_THRESHOLD = 0.45  # Minimum similarity to consider evidence relevant


def main():
    conn = get_connection()

    # Get all unverifiable claims
    rows = conn.execute(
        "SELECT id, canonical_text_is, canonical_text_en, category, claim_slug "
        "FROM claims WHERE verdict = 'unverifiable' "
        "ORDER BY category, claim_slug"
    ).fetchall()

    print(f"Found {len(rows)} unverifiable claims\n")

    now_assessable = []
    still_unverifiable = []

    for row in rows:
        claim_id, text_is, text_en, category, slug = row
        # Search with Icelandic text first, fall back to English
        query = text_is or text_en
        if not query:
            still_unverifiable.append((slug, category, []))
            continue

        # Search evidence
        results = search_evidence(query, top_k=5, conn=conn)
        # Also try with English text if available and different
        if text_en and text_en != text_is:
            results_en = search_evidence(text_en, top_k=5, conn=conn)
            # Merge and deduplicate
            seen_ids = {r.evidence_id for r in results}
            for r in results_en:
                if r.evidence_id not in seen_ids:
                    results.append(r)
                    seen_ids.add(r.evidence_id)

        # Filter by threshold
        strong_matches = [r for r in results if r.similarity >= SIMILARITY_THRESHOLD]

        if strong_matches:
            now_assessable.append((slug, category, strong_matches))
        else:
            best = max((r.similarity for r in results), default=0)
            still_unverifiable.append((slug, category, best))

    # Report
    print(f"{'='*70}")
    print(f"NOW ASSESSABLE ({len(now_assessable)} claims have matching evidence):")
    print(f"{'='*70}")
    for slug, cat, matches in now_assessable:
        top = matches[0]
        print(f"\n  [{cat}] {slug[:70]}")
        print(f"    Best match: {top.evidence_id} (sim={top.similarity:.3f})")
        print(f"    Evidence: {top.statement[:80]}...")
        if len(matches) > 1:
            print(f"    + {len(matches)-1} more match(es)")

    print(f"\n{'='*70}")
    print(f"STILL UNVERIFIABLE ({len(still_unverifiable)} claims lack evidence):")
    print(f"{'='*70}")
    for slug, cat, best_sim in still_unverifiable:
        sim_str = f"best={best_sim:.3f}" if isinstance(best_sim, float) else "no results"
        print(f"  [{cat}] {slug[:70]} ({sim_str})")

    # Summary
    total = len(rows)
    assessable = len(now_assessable)
    remaining = len(still_unverifiable)
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"  Total unverifiable: {total}")
    print(f"  Now assessable:     {assessable} ({assessable/total*100:.0f}%)")
    print(f"  Still unverifiable: {remaining} ({remaining/total*100:.0f}%)")

    # Overall claim bank impact
    total_claims = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    new_unverifiable = total - assessable
    old_rate = total / total_claims * 100
    new_rate = new_unverifiable / total_claims * 100
    print(f"\n  Claim bank: {total_claims} total claims")
    print(f"  Old unverifiable rate: {old_rate:.0f}% ({total}/{total_claims})")
    print(f"  Projected new rate:    {new_rate:.0f}% ({new_unverifiable}/{total_claims})")

    conn.close()


if __name__ == "__main__":
    main()
