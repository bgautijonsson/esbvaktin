"""Test embedding retrieval quality for Icelandic claims.

Seeds ~10 evidence entries, then queries with 5 Icelandic claims
to verify that semantic search returns relevant results.

Usage:
    uv run python scripts/test_embeddings.py
"""

from dotenv import load_dotenv

load_dotenv()

from esbvaktin.ground_truth import (
    Confidence,
    Domain,
    EvidenceEntry,
    SourceType,
    get_connection,
    init_schema,
    insert_evidence,
    search_evidence,
)

# Test evidence entries covering key topics
TEST_EVIDENCE = [
    EvidenceEntry(
        evidence_id="FISH-DATA-001",
        domain=Domain.ECONOMIC,
        topic="fisheries",
        subtopic="catch_volume",
        statement="Iceland's total marine catch in 2024 was approximately 1.1 million tonnes, "
        "making it one of the largest fishing nations in the North Atlantic relative to population.",
        source_name="Hagstofa Íslands — Fisheries statistics",
        source_type=SourceType.OFFICIAL_STATISTICS,
        confidence=Confidence.HIGH,
    ),
    EvidenceEntry(
        evidence_id="FISH-LEGAL-001",
        domain=Domain.LEGAL,
        topic="fisheries",
        subtopic="cfp_rules",
        statement="The EU Common Fisheries Policy (CFP), Regulation 1380/2013, establishes a system "
        "of total allowable catches (TACs) and quotas allocated among member states based on the "
        "principle of relative stability, using historical catch records as the baseline.",
        source_name="EU Regulation 1380/2013",
        source_type=SourceType.LEGAL_TEXT,
        confidence=Confidence.HIGH,
        caveats="The relative stability principle has been criticised for locking in historical "
        "patterns and disadvantaging newer fishing nations.",
    ),
    EvidenceEntry(
        evidence_id="FISH-COMP-001",
        domain=Domain.ECONOMIC,
        topic="fisheries",
        subtopic="norway_comparison",
        statement="Norway, as a non-EU EEA member, maintains full sovereign control over its "
        "fisheries management, including the right to set its own quotas in Norwegian waters. "
        "Norway negotiates bilateral fisheries agreements with the EU annually.",
        source_name="Norwegian Ministry of Trade, Industry and Fisheries",
        source_type=SourceType.INTERNATIONAL_ORG,
        confidence=Confidence.HIGH,
    ),
    EvidenceEntry(
        evidence_id="EEA-LEGAL-001",
        domain=Domain.LEGAL,
        topic="eea_eu_law",
        subtopic="law_adoption",
        statement="As of 2025, Iceland has incorporated approximately 70% of EU internal market "
        "legislation into Icelandic law through the EEA Agreement. This includes directives and "
        "regulations on free movement of goods, services, capital, and persons.",
        source_name="EFTA Surveillance Authority",
        source_type=SourceType.INTERNATIONAL_ORG,
        confidence=Confidence.MEDIUM,
        caveats="The exact percentage varies depending on how 'EU legislation' is counted. "
        "Agriculture, fisheries, and justice/home affairs are largely excluded from the EEA.",
    ),
    EvidenceEntry(
        evidence_id="EEA-LEGAL-002",
        domain=Domain.LEGAL,
        topic="eea_eu_law",
        subtopic="democratic_deficit",
        statement="Under the EEA Agreement, Iceland must adopt EU internal market legislation "
        "but has no voting rights in the EU legislative process. Iceland participates in "
        "shaping legislation through EEA EFTA consultation mechanisms, but cannot vote in "
        "the Council or European Parliament.",
        source_name="EEA Agreement, Article 99–101",
        source_type=SourceType.LEGAL_TEXT,
        confidence=Confidence.HIGH,
    ),
    EvidenceEntry(
        evidence_id="TRADE-DATA-001",
        domain=Domain.ECONOMIC,
        topic="trade",
        subtopic="eu_trade_share",
        statement="The European Union is Iceland's largest trading partner, accounting for "
        "approximately 50% of Iceland's goods exports and 60% of goods imports by value (2024).",
        source_name="Hagstofa Íslands — External trade",
        source_type=SourceType.OFFICIAL_STATISTICS,
        confidence=Confidence.HIGH,
    ),
    EvidenceEntry(
        evidence_id="AGRI-DATA-001",
        domain=Domain.ECONOMIC,
        topic="agriculture",
        subtopic="food_prices",
        statement="Food and non-alcoholic beverage prices in Iceland are approximately 50-70% "
        "higher than the EU-27 average, according to Eurostat comparative price level indices.",
        source_name="Eurostat — Comparative price levels",
        source_type=SourceType.INTERNATIONAL_ORG,
        confidence=Confidence.HIGH,
        caveats="Price differences reflect multiple factors including transport costs, small "
        "market size, agricultural protection, and import tariffs — not solely EU membership status.",
    ),
    EvidenceEntry(
        evidence_id="SOV-LEGAL-001",
        domain=Domain.LEGAL,
        topic="sovereignty",
        subtopic="eu_withdrawal",
        statement="Article 50 of the Treaty on European Union provides that any member state "
        "may decide to withdraw from the Union in accordance with its own constitutional "
        "requirements. The withdrawal process involves a two-year negotiation period.",
        source_name="Treaty on European Union, Article 50",
        source_type=SourceType.LEGAL_TEXT,
        confidence=Confidence.HIGH,
        caveats="While withdrawal is legally possible, the Brexit process (2016-2020) demonstrated "
        "significant political, legal, and economic complexity in practice.",
    ),
    EvidenceEntry(
        evidence_id="PREC-HIST-001",
        domain=Domain.PRECEDENT,
        topic="precedents",
        subtopic="norway_referendums",
        statement="Norway held EU membership referendums in 1972 and 1994, both resulting in "
        "narrow 'No' votes (53.5% and 52.2% respectively). Key issues in both campaigns "
        "included fisheries policy, agricultural subsidies, and national sovereignty.",
        source_name="Norwegian Centre for Research Data",
        source_type=SourceType.ACADEMIC_PAPER,
        confidence=Confidence.HIGH,
    ),
    EvidenceEntry(
        evidence_id="PREC-HIST-002",
        domain=Domain.PRECEDENT,
        topic="precedents",
        subtopic="iceland_negotiations",
        statement="Iceland opened EU accession negotiations in July 2010, completing screening "
        "of 27 out of 33 chapters. Negotiations were suspended in 2013 after the new "
        "centre-right government took office, and Iceland formally withdrew its application "
        "in March 2015.",
        source_name="European Commission — Iceland accession",
        source_type=SourceType.INTERNATIONAL_ORG,
        confidence=Confidence.HIGH,
    ),
]

# Icelandic test claims — these are what voters might encounter in articles
TEST_CLAIMS = [
    "Ísland myndi missa 80% af sjávarútvegnum ef það gengi í ESB",
    "Sameiginlega sjávarútvegsstefnan myndi eyðileggja íslenskan sjávarútveg",
    "Ísland innleiðir nú þegar 70% af löggjöf ESB í gegnum EES-samninginn",
    "Matvælaverð myndi lækka um 30% ef Ísland gengi í ESB",
    "Ísland myndi missa fullveldi sitt ef það gengi í Evrópusambandið",
]

EXPECTED_TOPICS = [
    "fisheries",       # Claim about losing fisheries
    "fisheries",       # Claim about CFP
    "eea_eu_law",      # Claim about EEA law adoption
    "agriculture",     # Claim about food prices
    "sovereignty",     # Claim about sovereignty
]


def main() -> None:
    conn = get_connection()
    init_schema(conn)

    # Clear any existing test data
    conn.execute("DELETE FROM evidence WHERE evidence_id LIKE 'FISH-%' OR evidence_id LIKE 'EEA-%' "
                 "OR evidence_id LIKE 'TRADE-%' OR evidence_id LIKE 'AGRI-%' "
                 "OR evidence_id LIKE 'SOV-%' OR evidence_id LIKE 'PREC-%'")
    conn.commit()

    # Seed test evidence
    print("Seeding test evidence entries...")
    for entry in TEST_EVIDENCE:
        insert_evidence(entry, conn=conn)
        print(f"  ✓ {entry.evidence_id}: {entry.statement[:60]}...")

    print(f"\nSeeded {len(TEST_EVIDENCE)} entries. Running retrieval tests...\n")
    print("=" * 80)

    # Test retrieval
    all_passed = True
    for i, (claim, expected_topic) in enumerate(zip(TEST_CLAIMS, EXPECTED_TOPICS)):
        results = search_evidence(claim, top_k=3, conn=conn)
        top_result = results[0]
        topic_match = any(r.topic == expected_topic for r in results)

        status = "✓" if topic_match else "✗"
        if not topic_match:
            all_passed = False

        print(f"\n{status} Claim {i + 1}: {claim}")
        for r in results:
            marker = "→" if r.topic == expected_topic else " "
            print(f"  {marker} [{r.similarity:.3f}] {r.evidence_id}: {r.statement[:70]}...")

    print("\n" + "=" * 80)
    if all_passed:
        print("✓ All retrieval tests passed — BGE-M3 works for Icelandic")
    else:
        print("✗ Some tests failed — review embedding model choice")

    conn.close()


if __name__ == "__main__":
    main()
