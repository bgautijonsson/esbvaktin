"""Generate Fullveldi (sovereignty) evidence dossier for Nordic House presentation."""

import pathlib

from esbvaktin.ground_truth.operations import get_connection

# Natural cluster groupings for sovereignty subtopics
SUBTOPIC_CLUSTERS = {
    "Referendum & Process": [
        "2012_constitutional_referendum",
        "advisory_referendum_political_weight",
        "referendum_advisory_nature_and_political_reality",
        "referendum_bill_parliamentary_procedure",
        "referendum_date_29_august_2026",
        "referendum_earlier_proposals",
        "referendum_government_position",
        "referendum_independence_party",
        "referendum_opposition_process",
        "article_24_parliamentary_procedure",
        "althingi_article_24_foreign_affairs_committee",
    ],
    "Constitutional Requirements": [
        "constitutional_amendment",
        "constitutional_council_2011_provisions",
        "constitutional_reform_inaction",
        "constitutional_society_natural_resources",
        "icelandic_constitutional_requirements",
        "iceland_constitutional_requirements_eu_accession",
        "althingi_sovereignty_transfer",
        "government_consultation_obligations",
    ],
    "Accession Negotiations & Process": [
        "iceland_accession_negotiations_2010_2013",
        "accession_opt_outs",
        "iceland_voting_weight_eu_council",
        "voting_weight",
        "eu_competence_categories",
        "subsidiarity_principle",
        "eu_legislative_volume",
    ],
    "Withdrawal & Reversibility": [
        "article_50_withdrawal_mechanism",
        "eu_withdrawal",
    ],
    "EU Law & Sovereignty Transfer": [
        "eu_acquis_supremacy_direct_effect",
        "efta_court_vs_cjeu",
        "eu_enhanced_cooperation",
        "eu_customs_union_trade_policy_sovereignty",
        "eu_fdi_screening_thresholds",
    ],
    "Opt-Outs (Precedents)": [
        "danish_opt_outs",
        "irish_opt_outs",
    ],
    "Foreign Policy & Security": [
        "common_foreign_security_policy",
        "foreign_security_policy",
        "defence_nato_relationship",
        "us_iceland_defence_relationship",
        "us_nato_eu_complementarity",
        "us_strategic_interests_iceland",
        "us_commercial_defence_interests_intertwined",
        "post_ukraine_strategic_significance",
        "trump_greenland_acquisition_statements",
    ],
    "Arctic & Northern Dimension": [
        "arctic_circle_rome_forum_2026",
        "arctic_northern_dimension",
    ],
    "Monetary Policy & Economic Sovereignty": [
        "monetary_policy",
        "euro_adoption",
        "iceland_2008_crisis_imf_eu_dynamics",
        "iceland_2008_emergency_legislation",
        "iceland_credit_rating_fiscal_position",
    ],
    "Democratic Legitimacy & Institutions": [
        "eu_parliament",
        "conference_future_europe_qmv_expansion",
        "snorri_masson_sovereignty_absolutism",
        "bjorn_bjarnason_mfa_critique",
    ],
    "Ethics, Revolving Door & Conflicts of Interest": [
        "eu_revolving_door_treaty_rules",
        "revolving_door_international_comparison",
        "nordic_revolving_door_comparison",
        "iceland_conflict_of_interest_rules",
        "icelandic_conflict_of_interest_act",
        "ministers_ethics_code_iceland",
        "billy_long_ambassador_nomination",
    ],
    "Other": [],  # catch-all
}


def cluster_for_subtopic(subtopic: str | None) -> str:
    if subtopic is None:
        return "Other"
    for cluster, subtopics in SUBTOPIC_CLUSTERS.items():
        if subtopic in subtopics:
            return cluster
    return "Other"


def main():
    conn = get_connection()

    # 1. All sovereignty evidence
    sov_evidence = conn.execute("""
        SELECT
            evidence_id, statement, statement_is,
            source_name, source_type, confidence,
            caveats, caveats_is, subtopic, domain
        FROM evidence
        WHERE topic = 'sovereignty'
        ORDER BY evidence_id
    """).fetchall()

    # 2. Cross-topic evidence matching sovereignty-related terms
    cross_topic = conn.execute("""
        SELECT
            evidence_id, topic, statement, statement_is,
            source_name, source_type, confidence,
            caveats, caveats_is, subtopic
        FROM evidence
        WHERE topic != 'sovereignty'
          AND (
            statement ILIKE '%%sovereignty%%'
            OR statement ILIKE '%%constitutional%%'
            OR statement ILIKE '%%referendum%%'
            OR statement ILIKE '%%accession process%%'
            OR statement ILIKE '%%negotiat%%'
            OR statement ILIKE '%%reversib%%'
            OR statement ILIKE '%%withdraw%%'
            OR statement ILIKE '%%Article 50%%'
            OR statement ILIKE '%%exit%%'
            OR statement_is ILIKE '%%fullveldi%%'
            OR statement_is ILIKE '%%stjórnarskr%%'
            OR statement_is ILIKE '%%þjóðaratkvæðagreiðsl%%'
            OR statement_is ILIKE '%%aðildarviðræð%%'
            OR statement_is ILIKE '%%samningaviðræð%%'
          )
        ORDER BY topic, evidence_id
    """).fetchall()

    # 3. Evidence utilisation (how many claims cite each entry)
    evidence_usage = conn.execute("""
        SELECT unnest(supporting_evidence) AS eid, COUNT(*) AS cnt
        FROM claims
        WHERE published = TRUE
        GROUP BY eid
        UNION ALL
        SELECT unnest(contradicting_evidence) AS eid, COUNT(*) AS cnt
        FROM claims
        WHERE published = TRUE
        GROUP BY eid
    """).fetchall()
    usage_map: dict[str, int] = {}
    for r in evidence_usage:
        usage_map[r[0]] = usage_map.get(r[0], 0) + r[1]

    conn.close()

    # --- Group sovereignty entries by cluster ---
    clusters: dict[str, list] = {k: [] for k in SUBTOPIC_CLUSTERS}
    for r in sov_evidence:
        cluster = cluster_for_subtopic(r[8])
        clusters[cluster].append(r)

    # Remove empty clusters
    clusters = {k: v for k, v in clusters.items() if v}

    # Confidence breakdown
    conf_counts: dict[str, int] = {}
    for r in sov_evidence:
        c = r[5] or "unspecified"
        conf_counts[c] = conf_counts.get(c, 0) + 1

    # --- Build markdown ---
    lines = []
    lines.append("---")
    lines.append("type: dossier")
    lines.append("topic: sovereignty")
    lines.append("stage: evidence")
    lines.append("date: '2026-04-13'")
    lines.append("tags: [esb, nordic-house, dossier]")
    lines.append("---")
    lines.append("")
    lines.append("# Fullveldi — What We Can Know")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    conf_str = ", ".join(f"{k}: {v}" for k, v in sorted(conf_counts.items()))
    lines.append(
        f"The sovereignty topic has **{len(sov_evidence)} evidence entries** "
        f"across {len(clusters)} thematic clusters — the largest topic in the database. "
        f"Confidence breakdown: {conf_str}. "
        f"An additional **{len(cross_topic)} cross-topic entries** reference sovereignty-adjacent themes "
        f"(constitutional requirements, referendum, withdrawal, negotiations)."
    )
    lines.append("")
    lines.append(
        "Coverage is deepest on the referendum process, constitutional requirements, and EU law mechanics. "
        "Withdrawal/reversibility, opt-out precedents, and the defence/strategic dimension are covered but thinner. "
        "Key gaps: Iceland-specific negotiation scenarios, QMV exposure across acquis chapters, "
        "and updated 2025–26 political positions."
    )
    lines.append("")

    # Evidence by cluster
    lines.append("## Evidence by Subtopic")
    lines.append("")

    for cluster_name in SUBTOPIC_CLUSTERS:
        entries = clusters.get(cluster_name)
        if not entries:
            continue

        lines.append(f"### {cluster_name} ({len(entries)} entries)")
        lines.append("")

        for r in entries:
            eid, stmt, stmt_is, src_name, src_type, conf, caveats, caveats_is, subtopic, domain = r
            usage = usage_map.get(eid, 0)

            lines.append(f"#### {eid}")
            lines.append("")
            if stmt_is:
                lines.append(f"> **IS:** {stmt_is}")
                lines.append(">")
            lines.append(f"> **EN:** {stmt}")
            lines.append("")
            meta_parts = [
                f"**Source:** {src_name} ({src_type})",
                f"**Confidence:** {conf}",
            ]
            if domain:
                meta_parts.append(f"**Domain:** {domain}")
            if subtopic:
                meta_parts.append(f"**Subtopic:** {subtopic}")
            meta_parts.append(f"**Cited by:** {usage} claims")
            lines.append(" · ".join(meta_parts))
            if caveats_is:
                lines.append("")
                lines.append(f"**Fyrirvarar:** {caveats_is}")
            elif caveats:
                lines.append("")
                lines.append(f"**Caveats:** {caveats}")
            lines.append("")

    # Cross-topic evidence
    lines.append("## Cross-Topic Evidence")
    lines.append("")
    lines.append(
        f"**{len(cross_topic)} entries** from other topics reference sovereignty-adjacent themes "
        f"(constitutional, referendum, withdrawal, negotiations, reversibility)."
    )
    lines.append("")

    cross_by_topic: dict[str, list] = {}
    for r in cross_topic:
        cross_by_topic.setdefault(r[1], []).append(r)

    for topic in sorted(cross_by_topic.keys()):
        entries = cross_by_topic[topic]
        topic_label = topic.replace("_", " ").title()
        lines.append(f"### {topic_label} ({len(entries)} entries)")
        lines.append("")

        for r in entries:
            eid, _, stmt, stmt_is, src_name, src_type, conf, caveats, caveats_is, subtopic = r
            usage = usage_map.get(eid, 0)
            lines.append(f"#### {eid} ({conf}) — {src_name}")
            lines.append("")
            if stmt_is:
                lines.append(f"> **IS:** {stmt_is}")
                lines.append(">")
            lines.append(f"> **EN:** {stmt}")
            lines.append("")
            if subtopic:
                lines.append(f"**Subtopic:** {subtopic} · **Cited by:** {usage} claims")
            else:
                lines.append(f"**Cited by:** {usage} claims")
            if caveats_is:
                lines.append("")
                lines.append(f"**Fyrirvarar:** {caveats_is}")
            elif caveats:
                lines.append("")
                lines.append(f"**Caveats:** {caveats}")
            lines.append("")

    content = "\n".join(lines)

    out_path = (
        pathlib.Path.home()
        / "Obsidian/Metill/ESB/Knowledge/Nordic House Event/Dossier — Fullveldi — Evidence.md"
    )
    out_path.write_text(content, encoding="utf-8")

    # Stats
    print(f"Written {len(content):,} chars to {out_path}")
    print(f"\nSovereignty evidence: {len(sov_evidence)} entries")
    print(f"Cross-topic evidence: {len(cross_topic)} entries")
    print(f"\nConfidence breakdown: {conf_counts}")
    print("\nClusters and sizes:")
    for name, entries in clusters.items():
        print(f"  {name}: {len(entries)}")
    print("\nCross-topic by topic:")
    for topic, entries in sorted(cross_by_topic.items()):
        print(f"  {topic}: {len(entries)}")


if __name__ == "__main__":
    main()
