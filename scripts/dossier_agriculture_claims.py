"""Generate Landbúnaður (agriculture) claims dossier for Nordic House presentation."""

from collections import Counter

from esbvaktin.ground_truth.operations import get_connection


def main():
    conn = get_connection()

    # 1. Top 20 claims by sighting count
    top_claims = conn.execute("""
        SELECT
            c.id,
            c.canonical_text_is,
            c.verdict,
            c.confidence,
            c.epistemic_type,
            c.claim_type,
            c.missing_context_is,
            c.supporting_evidence,
            c.contradicting_evidence,
            COUNT(s.id) AS sighting_count
        FROM claims c
        LEFT JOIN claim_sightings s ON c.id = s.claim_id
        WHERE c.category = 'agriculture' AND c.published = TRUE
        GROUP BY c.id
        ORDER BY sighting_count DESC
        LIMIT 20
    """).fetchall()

    # 2. Sighting context for top 10
    top_10_ids = [r[0] for r in top_claims[:10]]
    sightings = conn.execute(
        """
        SELECT
            s.claim_id,
            s.source_domain,
            s.source_date,
            s.source_title
        FROM claim_sightings s
        WHERE s.claim_id = ANY(%s)
        ORDER BY s.claim_id, s.source_date DESC
    """,
        [top_10_ids],
    ).fetchall()

    # Group sightings by claim_id
    sightings_by_claim: dict[int, list] = {}
    for s in sightings:
        sightings_by_claim.setdefault(s[0], []).append(s)

    # 3. Claim type distribution (full category)
    type_dist = conn.execute("""
        SELECT claim_type, COUNT(*) AS cnt
        FROM claims
        WHERE category = 'agriculture' AND published = TRUE
        GROUP BY claim_type
        ORDER BY cnt DESC
    """).fetchall()

    epistemic_dist = conn.execute("""
        SELECT epistemic_type, COUNT(*) AS cnt
        FROM claims
        WHERE category = 'agriculture' AND published = TRUE
        GROUP BY epistemic_type
        ORDER BY cnt DESC
    """).fetchall()

    verdict_dist = conn.execute("""
        SELECT verdict, COUNT(*) AS cnt
        FROM claims
        WHERE category = 'agriculture' AND published = TRUE
        GROUP BY verdict
        ORDER BY cnt DESC
    """).fetchall()

    # 4. Outlet distribution
    outlet_dist = conn.execute("""
        SELECT s.source_domain, COUNT(DISTINCT s.claim_id) AS claim_count, COUNT(s.id) AS sighting_count
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.category = 'agriculture' AND c.published = TRUE
        GROUP BY s.source_domain
        ORDER BY sighting_count DESC
        LIMIT 15
    """).fetchall()

    # Total counts
    total_claims = conn.execute("""
        SELECT COUNT(*) FROM claims WHERE category = 'agriculture' AND published = TRUE
    """).fetchone()[0]

    total_sightings = conn.execute("""
        SELECT COUNT(s.id)
        FROM claim_sightings s
        JOIN claims c ON c.id = s.claim_id
        WHERE c.category = 'agriculture' AND c.published = TRUE
    """).fetchone()[0]

    conn.close()

    # --- Build markdown ---
    lines = []
    lines.append("---")
    lines.append("type: dossier")
    lines.append("topic: agriculture")
    lines.append("stage: claims")
    lines.append("date: '2026-04-13'")
    lines.append("tags: [esb, nordic-house, dossier]")
    lines.append("---")
    lines.append("")
    lines.append("# Landbúnaður — What People Are Saying")
    lines.append("")

    # Summary
    verdict_counts = {r[0]: r[1] for r in verdict_dist}
    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"The agriculture category contains **{total_claims} published claims** "
        f"with **{total_sightings} sightings** across the discourse. "
    )

    # Verdict summary
    v_parts = []
    for v, c in sorted(verdict_counts.items(), key=lambda x: -x[1]):
        pct = c / total_claims * 100 if total_claims else 0
        v_parts.append(f"{v}: {c} ({pct:.0f}%)")
    lines.append(f"Verdict distribution: {', '.join(v_parts)}.")
    lines.append("")

    # Top claim themes (texts available in top_claims[:5] if needed)
    lines.append(
        "The most-repeated claims centre on food prices, tariff protection, "
        "CAP eligibility, and the impact on rural communities. "
        "See the trade-off audit below for consumer vs. producer framing."
    )
    lines.append("")

    # Top 20 claims
    lines.append("## Top Claims by Repetition")
    lines.append("")

    for i, r in enumerate(top_claims, 1):
        claim_id, text_is, verdict, confidence, ep_type, cl_type, missing, supp, contra, sc = r
        lines.append(f"### {i}. (ID {claim_id}, {sc} sightings)")
        lines.append("")
        lines.append(f"> {text_is}")
        lines.append("")
        lines.append(
            f"**Verdict:** {verdict} · **Confidence:** {confidence:.2f} · "
            f"**Type:** {cl_type} · **Epistemic:** {ep_type or 'factual'}"
        )
        if missing:
            lines.append("")
            lines.append(f"**Missing context:** {missing}")
        # Evidence links
        supp_list = supp or []
        contra_list = contra or []
        if supp_list or contra_list:
            parts = []
            if supp_list:
                parts.append(f"Supporting: {', '.join(supp_list)}")
            if contra_list:
                parts.append(f"Contradicting: {', '.join(contra_list)}")
            lines.append("")
            lines.append(f"**Evidence:** {' | '.join(parts)}")

        # Sighting detail for top 10
        if claim_id in sightings_by_claim:
            lines.append("")
            lines.append("| Source | Date |")
            lines.append("|--------|------|")
            for s in sightings_by_claim[claim_id]:
                domain = s[1] or "unknown"
                date = str(s[2]) if s[2] else "—"
                lines.append(f"| {domain} | {date} |")

        lines.append("")

    # Outlet distribution
    lines.append("## Outlet Distribution")
    lines.append("")
    lines.append("| Outlet | Distinct claims | Total sightings |")
    lines.append("|--------|----------------|-----------------|")
    for r in outlet_dist:
        lines.append(f"| {r[0] or 'unknown'} | {r[1]} | {r[2]} |")
    lines.append("")

    # Claim type distribution
    lines.append("## Claim Type Distribution")
    lines.append("")
    lines.append("### By claim type")
    lines.append("")
    lines.append("| Type | Count | % |")
    lines.append("|------|-------|---|")
    for r in type_dist:
        pct = r[1] / total_claims * 100 if total_claims else 0
        lines.append(f"| {r[0]} | {r[1]} | {pct:.1f}% |")
    lines.append("")

    lines.append("### By epistemic type")
    lines.append("")
    lines.append("| Type | Count | % |")
    lines.append("|------|-------|---|")
    for r in epistemic_dist:
        pct = r[1] / total_claims * 100 if total_claims else 0
        lines.append(f"| {r[0] or 'factual'} | {r[1]} | {pct:.1f}% |")
    lines.append("")

    lines.append("### By verdict")
    lines.append("")
    lines.append("| Verdict | Count | % |")
    lines.append("|---------|-------|---|")
    for r in verdict_dist:
        pct = r[1] / total_claims * 100 if total_claims else 0
        lines.append(f"| {r[0]} | {r[1]} | {pct:.1f}% |")
    lines.append("")

    # Trade-off audit — classify claims
    lines.append("## Trade-off Audit")
    lines.append("")
    lines.append(
        "Each of the top 20 claims classified as primarily **consumer-framed** "
        "(lower prices, market access, consumer choice, tariff criticism) or "
        "**producer-framed** (farmer protection, rural communities, adjustment costs, "
        "food safety, sovereignty over food production)."
    )
    lines.append("")

    consumer_keywords = [
        "verð",
        "neytend",
        "dýr",
        "toll",
        "innflutn",
        "ódýr",
        "matvælaverð",
        "lægra",
        "hækk",
        "kostnaður neytenda",
        "verðlag",
        "val neytenda",
    ]
    producer_keywords = [
        "bændu",
        "búvöru",
        "landbúnað",
        "dreifbýl",
        "matvælaöryggi",
        "sjálfbærni",
        "framleiðsl",
        "vernd",
        "niðurgreiðsl",
        "stuðning",
        "byggð",
        "atvinn",
        "íslenskra bænda",
        "innlend",
        "varðveita",
    ]

    consumer_claims = []
    producer_claims = []
    ambiguous_claims = []

    for r in top_claims:
        text = (r[1] or "").lower()
        c_score = sum(1 for kw in consumer_keywords if kw in text)
        p_score = sum(1 for kw in producer_keywords if kw in text)
        entry = {
            "id": r[0],
            "text": r[1],
            "verdict": r[2],
            "confidence": r[3],
            "sightings": r[9],
        }
        if c_score > p_score:
            consumer_claims.append(entry)
        elif p_score > c_score:
            producer_claims.append(entry)
        else:
            ambiguous_claims.append(entry)

    lines.append(
        f"**Consumer-framed:** {len(consumer_claims)} · "
        f"**Producer-framed:** {len(producer_claims)} · "
        f"**Ambiguous/both:** {len(ambiguous_claims)}"
    )
    lines.append("")

    def avg_conf(claims_list):
        confs = [c["confidence"] for c in claims_list if c["confidence"]]
        return sum(confs) / len(confs) if confs else 0

    def verdict_summary(claims_list):
        counts = Counter(c["verdict"] for c in claims_list)
        return ", ".join(f"{v}: {n}" for v, n in counts.most_common())

    if consumer_claims:
        lines.append("### Consumer-framed")
        lines.append("")
        lines.append(
            f"Average confidence: {avg_conf(consumer_claims):.2f} · "
            f"Verdicts: {verdict_summary(consumer_claims)}"
        )
        lines.append("")
        for c in consumer_claims:
            lines.append(f"- (ID {c['id']}, {c['sightings']}×) {c['text'][:120]}...")
        lines.append("")

    if producer_claims:
        lines.append("### Producer-framed")
        lines.append("")
        lines.append(
            f"Average confidence: {avg_conf(producer_claims):.2f} · "
            f"Verdicts: {verdict_summary(producer_claims)}"
        )
        lines.append("")
        for c in producer_claims:
            lines.append(f"- (ID {c['id']}, {c['sightings']}×) {c['text'][:120]}...")
        lines.append("")

    if ambiguous_claims:
        lines.append("### Ambiguous / both sides")
        lines.append("")
        for c in ambiguous_claims:
            lines.append(f"- (ID {c['id']}, {c['sightings']}×) {c['text'][:120]}...")
        lines.append("")

    # Observations
    lines.append("## Observations")
    lines.append("")
    lines.append("*(To be refined after reviewing the data above. Key questions to address:)*")
    lines.append("")
    lines.append("- What questions does the debate ask? What doesn't it ask?")
    lines.append(
        "- Which claims present negotiable terms as settled "
        "(e.g. 'market would open' without discussing transition timelines)?"
    )
    lines.append(
        "- Does the debate engage with the genuine trade-off "
        "(consumer prices vs. producer livelihoods)?"
    )
    lines.append(
        "- Are there claims about CAP subsidies that ignore eligibility "
        "conditions or transition schedules?"
    )
    lines.append("")

    content = "\n".join(lines)

    # Write to filesystem (may be too large for MCP)
    import pathlib

    out_path = (
        pathlib.Path.home()
        / "Obsidian/Metill/ESB/Knowledge/Nordic House Event/Dossier — Landbúnaður — Claims.md"
    )
    out_path.write_text(content, encoding="utf-8")
    print(f"Written {len(content)} chars to {out_path}")
    print(f"Total claims: {total_claims}, Total sightings: {total_sightings}")
    print("Top 20 claims exported with sighting details for top 10")


if __name__ == "__main__":
    main()
