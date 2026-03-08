"""Post-seeding verification for the Ground Truth Database.

Checks entry count, topic coverage, embedding completeness,
and runs semantic search smoke tests.

Usage:
    uv run python scripts/verify_db.py
"""

from dotenv import load_dotenv

load_dotenv()

from esbvaktin.ground_truth import (
    get_connection,
    get_topic_counts,
    get_total_count,
    search_evidence,
)


def main() -> None:
    conn = get_connection()

    # 1. Total count
    total = get_total_count(conn)
    print(f"Total entries: {total}")
    if total < 80:
        print(f"  ⚠ Expected >= 80 entries, got {total}")

    # 2. Coverage by topic
    topics = get_topic_counts(conn)
    print("\nCoverage by topic:")
    for topic, count in topics.items():
        print(f"  {topic}: {count}")

    # 3. All entries have embeddings
    null_embeddings = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE embedding IS NULL"
    ).fetchone()[0]
    if null_embeddings > 0:
        print(f"\n⚠ {null_embeddings} entries missing embeddings")
    else:
        print(f"\n✓ All {total} entries have embeddings")

    # 4. Semantic search smoke tests
    test_queries = [
        ("fisheries quota allocation Iceland", "fisheries"),
        ("EU membership budget contribution cost", "trade"),
        ("sovereignty parliament democratic deficit", "sovereignty"),
        ("Norway referendum EU membership", "precedents"),
        ("food prices agriculture CAP", "agriculture"),
        ("EEA agreement legislation adoption", "eea_eu_law"),
    ]

    print("\nSemantic search smoke tests:")
    passed = 0
    for query, expected_topic in test_queries:
        results = search_evidence(query, top_k=3, conn=conn)
        if not results:
            print(f"  ✗ '{query}' → no results")
            continue

        top = results[0]
        topic_match = any(r.topic == expected_topic for r in results)
        status = "✓" if topic_match else "✗"
        if topic_match:
            passed += 1
        print(
            f"  {status} '{query}' → {top.evidence_id} "
            f"(sim: {top.similarity:.3f}, topic: {top.topic})"
        )

    print(f"\n{'✓' if passed == len(test_queries) else '⚠'} "
          f"Passed {passed}/{len(test_queries)} smoke tests")

    # 5. Domain coverage targets
    targets = {
        "fisheries": 20,
        "eea_eu_law": 15,
        "trade": 15,
        "agriculture": 10,
        "sovereignty": 10,
        "precedents": 10,
    }
    print("\nDomain coverage vs targets:")
    for topic, target in targets.items():
        actual = topics.get(topic, 0)
        status = "✓" if actual >= target else "⚠"
        print(f"  {status} {topic}: {actual}/{target}")

    conn.close()


if __name__ == "__main__":
    main()
