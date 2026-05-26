"""Generate Landbúnaður (agriculture) evidence dossier for Nordic House presentation."""

import pathlib

from esbvaktin.ground_truth.operations import get_connection


def main():
    conn = get_connection()

    # 1. All agriculture evidence
    agri_evidence = conn.execute("""
        SELECT
            evidence_id, statement, statement_is,
            source_name, source_type, confidence,
            caveats, caveats_is, subtopic, domain
        FROM evidence
        WHERE topic = 'agriculture'
        ORDER BY evidence_id
    """).fetchall()

    # 2. Cross-topic evidence (food price, tariff, CAP, agricultural, dairy, transition, rural)
    cross_topic = conn.execute("""
        SELECT
            evidence_id, topic, statement, statement_is,
            source_name, source_type, confidence,
            caveats, caveats_is, subtopic
        FROM evidence
        WHERE topic != 'agriculture'
          AND (
            statement ILIKE '%%food price%%'
            OR statement ILIKE '%%tariff%%'
            OR statement ILIKE '%%Common Agricultural%%'
            OR statement ILIKE '%%CAP %%'
            OR statement ILIKE '%%agricultural%%'
            OR statement ILIKE '%%dairy%%'
            OR statement ILIKE '%%transition period%%'
            OR statement ILIKE '%%rural%%'
            OR statement_is ILIKE '%%matvælaverð%%'
            OR statement_is ILIKE '%%toll%%'
            OR statement_is ILIKE '%%landbúnað%%'
            OR statement_is ILIKE '%%bændum%%'
            OR statement_is ILIKE '%%aðlögunartím%%'
          )
        ORDER BY topic, evidence_id
    """).fetchall()

    # 3. How many claims cite each evidence entry (for utilisation context)
    evidence_usage = conn.execute("""
        SELECT unnest(supporting_evidence) AS eid, COUNT(*) AS cnt
        FROM claims
        WHERE category = 'agriculture' AND published = TRUE
        GROUP BY eid
        UNION ALL
        SELECT unnest(contradicting_evidence) AS eid, COUNT(*) AS cnt
        FROM claims
        WHERE category = 'agriculture' AND published = TRUE
        GROUP BY eid
    """).fetchall()
    usage_map: dict[str, int] = {}
    for r in evidence_usage:
        usage_map[r[0]] = usage_map.get(r[0], 0) + r[1]

    conn.close()

    # --- Cluster agriculture evidence by subtopic ---
    clusters: dict[str, list] = {}
    for r in agri_evidence:
        subtopic = r[8] or "general"
        clusters.setdefault(subtopic, []).append(r)

    # --- Build markdown ---
    lines = []
    lines.append("---")
    lines.append("type: dossier")
    lines.append("topic: agriculture")
    lines.append("stage: evidence")
    lines.append("date: '2026-04-13'")
    lines.append("tags: [esb, nordic-house, dossier]")
    lines.append("---")
    lines.append("")
    lines.append("# Landbúnaður — What We Can Know")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    conf_counts = {}
    for r in agri_evidence:
        c = r[5] or "unspecified"
        conf_counts[c] = conf_counts.get(c, 0) + 1

    lines.append(
        f"The agriculture topic has **{len(agri_evidence)} evidence entries** "
        f"across {len(clusters)} subtopics. "
        f"Confidence breakdown: {', '.join(f'{k}: {v}' for k, v in sorted(conf_counts.items()))}. "
        f"An additional **{len(cross_topic)} cross-topic entries** reference agricultural themes."
    )
    lines.append("")
    lines.append(
        "The evidence covers food prices, tariff structure, CAP mechanics, "
        "transition period precedents, and rural economy impacts. "
        "Gaps remain around specific negotiation scenarios and Iceland-specific "
        "adjustment cost modelling."
    )
    lines.append("")

    # Evidence by subtopic
    lines.append("## Evidence by Subtopic")
    lines.append("")

    for subtopic in sorted(clusters.keys()):
        entries = clusters[subtopic]
        lines.append(f"### {subtopic.replace('_', ' ').title()} ({len(entries)} entries)")
        lines.append("")

        for r in entries:
            eid, stmt, stmt_is, src_name, src_type, conf, caveats, caveats_is, _, domain = r
            usage = usage_map.get(eid, 0)

            lines.append(f"#### {eid}")
            lines.append("")
            if stmt_is:
                lines.append(f"> **IS:** {stmt_is}")
                lines.append(">")
            lines.append(f"> **EN:** {stmt}")
            lines.append("")
            lines.append(
                f"**Source:** {src_name} ({src_type}) · "
                f"**Confidence:** {conf} · "
                f"**Domain:** {domain} · "
                f"**Cited by:** {usage} claims"
            )
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
    lines.append(f"**{len(cross_topic)} entries** from other topics reference agricultural themes.")
    lines.append("")

    cross_by_topic: dict[str, list] = {}
    for r in cross_topic:
        cross_by_topic.setdefault(r[1], []).append(r)

    for topic in sorted(cross_by_topic.keys()):
        entries = cross_by_topic[topic]
        lines.append(f"### {topic.replace('_', ' ').title()} ({len(entries)} entries)")
        lines.append("")

        for r in entries:
            eid, _, stmt, stmt_is, src_name, src_type, conf, caveats, caveats_is, subtopic = r
            lines.append(f"**{eid}** ({conf}) — {src_name}")
            if stmt_is:
                lines.append(f"> {stmt_is}")
            else:
                lines.append(f"> {stmt}")
            if caveats_is or caveats:
                lines.append(f"> *Fyrirvari: {caveats_is or caveats}*")
            lines.append("")

    # The trade-off in evidence
    lines.append("## The Trade-off in Evidence")
    lines.append("")
    lines.append("*(To be refined after reviewing the evidence above. Structure:)*")
    lines.append("")
    lines.append("### Consumer side")
    lines.append("")
    lines.append("- Food price premium evidence (Eurostat comparisons)")
    lines.append("- Tariff structure analysis (effective rates on dairy, meat)")
    lines.append("- Cross-country consumer impact data")
    lines.append("")
    lines.append("### Producer side")
    lines.append("")
    lines.append("- Rural employment and community dependence data")
    lines.append("- Cost structure of Icelandic farming (scale, geography)")
    lines.append("- CAP transition precedents (Croatia, Sweden)")
    lines.append("- Food safety and standards convergence")
    lines.append("")

    # Key caveats
    lines.append("## Key Caveats and Uncertainties")
    lines.append("")
    all_caveats = []
    for r in agri_evidence:
        c = r[7] or r[6]  # caveats_is preferred, fall back to caveats
        if c:
            all_caveats.append((r[0], c))

    for eid, caveat in all_caveats:
        lines.append(f"- **{eid}:** {caveat}")
    lines.append("")

    # Evidence vs debate
    lines.append("## Evidence vs. Debate")
    lines.append("")
    lines.append("*(To be refined. Key questions:)*")
    lines.append("")
    lines.append("- Where does the evidence answer debate questions directly?")
    lines.append("- Where does the evidence answer questions nobody in the debate is asking?")
    lines.append("- Does the debate engage with transition period precedents at all?")
    lines.append(
        "- Are specific CAP eligibility conditions discussed, "
        "or just 'we would/wouldn't get EU subsidies'?"
    )
    lines.append("")

    content = "\n".join(lines)

    out_path = (
        pathlib.Path.home()
        / "Obsidian/Metill/ESB/Knowledge/Nordic House Event/Dossier — Landbúnaður — Evidence.md"
    )
    out_path.write_text(content, encoding="utf-8")
    print(f"Written {len(content)} chars to {out_path}")
    print(f"Agriculture evidence: {len(agri_evidence)} entries")
    print(f"Cross-topic evidence: {len(cross_topic)} entries")
    print(f"Subtopics: {sorted(clusters.keys())}")


if __name__ == "__main__":
    main()
