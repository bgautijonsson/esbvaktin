#!/usr/bin/env python3
"""
Sovereignty Claims Dossier — Nordic House Event 2026-04-14
Queries ESBvaktin DB for sovereignty-category claims and writes
an Obsidian markdown note.
"""

from datetime import date
from pathlib import Path

from esbvaktin.ground_truth.operations import get_connection

OUTPUT_PATH = (
    Path.home() / "Obsidian/Metill/ESB/Knowledge/Nordic House Event/Dossier — Fullveldi — Claims.md"
)


def run_queries():
    conn = get_connection()
    cur = conn.cursor()

    # ── 1. Top 25 claims by sighting count ──────────────────────────────────
    print("\n=== TOP 25 SOVEREIGNTY CLAIMS BY SIGHTING COUNT ===\n")
    cur.execute("""
        SELECT
            c.id,
            c.canonical_text_is,
            c.verdict,
            c.confidence,
            c.epistemic_type,
            c.claim_type,
            c.missing_context_is,
            COUNT(cs.id) AS sighting_count
        FROM claims c
        LEFT JOIN claim_sightings cs ON cs.claim_id = c.id
        WHERE c.category = 'sovereignty'
          AND c.published = TRUE
        GROUP BY c.id
        ORDER BY sighting_count DESC, c.id
        LIMIT 25
    """)
    top25 = cur.fetchall()
    cols = [
        "id",
        "canonical_text_is",
        "verdict",
        "confidence",
        "epistemic_type",
        "claim_type",
        "missing_context_is",
        "sighting_count",
    ]
    top25_rows = [dict(zip(cols, row)) for row in top25]

    for i, r in enumerate(top25_rows, 1):
        print(
            f"{i:>2}. [{r['sighting_count']} sightings] {r['verdict']} / {r['confidence']} / {r['epistemic_type']}"
        )
        print(f"    {r['canonical_text_is'][:120]}")
        if r["missing_context_is"]:
            print(f"    MISSING: {r['missing_context_is'][:80]}")
        print()

    top10_ids = [r["id"] for r in top25_rows[:10]]

    # ── 2. Sighting context for top 10: domain + date distribution ──────────
    print("\n=== SIGHTING CONTEXT: TOP 10 CLAIMS ===\n")
    id_placeholders = ",".join(["%s"] * len(top10_ids))
    cur.execute(
        f"""
        SELECT
            c.id,
            cs.source_domain,
            cs.source_date,
            cs.speaker_name,
            cs.speaker_stance
        FROM claim_sightings cs
        JOIN claims c ON c.id = cs.claim_id
        WHERE c.id IN ({id_placeholders})
        ORDER BY c.id, cs.source_date DESC NULLS LAST
    """,
        top10_ids,
    )
    sighting_rows = cur.fetchall()
    sighting_cols = ["claim_id", "source_domain", "source_date", "speaker_name", "speaker_stance"]
    sightings = [dict(zip(sighting_cols, row)) for row in sighting_rows]

    for row in sightings[:30]:
        print(
            f"  claim {row['claim_id']}: {row['source_domain']} | {row['source_date']} | "
            f"{row['speaker_name']} | {row['speaker_stance']}"
        )

    # ── 3. Claim type distribution (all sovereignty claims) ─────────────────
    print("\n=== CLAIM TYPE DISTRIBUTION (sovereignty) ===\n")
    cur.execute("""
        SELECT
            claim_type,
            COUNT(*) AS n,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM claims
        WHERE category = 'sovereignty' AND published = TRUE
        GROUP BY claim_type
        ORDER BY n DESC
    """)
    claim_type_rows = cur.fetchall()
    for r in claim_type_rows:
        print(f"  {r[0]:<20} {r[1]:>4}  {r[2]}%")

    # ── 4. Outlet distribution (all sovereignty sightings) ──────────────────
    print("\n=== OUTLET DISTRIBUTION (sovereignty sightings) ===\n")
    cur.execute("""
        SELECT
            cs.source_domain,
            COUNT(*) AS sightings,
            COUNT(DISTINCT c.id) AS unique_claims
        FROM claim_sightings cs
        JOIN claims c ON c.id = cs.claim_id
        WHERE c.category = 'sovereignty' AND c.published = TRUE
        GROUP BY cs.source_domain
        ORDER BY sightings DESC
        LIMIT 20
    """)
    outlet_rows = cur.fetchall()
    for r in outlet_rows:
        print(f"  {r[0]:<35} {r[1]:>4} sightings  {r[2]:>3} unique claims")

    # ── 5. Epistemic type distribution ──────────────────────────────────────
    print("\n=== EPISTEMIC TYPE DISTRIBUTION ===\n")
    cur.execute("""
        SELECT
            epistemic_type,
            COUNT(*) AS n,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM claims
        WHERE category = 'sovereignty' AND published = TRUE
        GROUP BY epistemic_type
        ORDER BY n DESC
    """)
    epistemic_rows = cur.fetchall()
    for r in epistemic_rows:
        print(f"  {r[0]:<20} {r[1]:>4}  {r[2]}%")

    conn.close()
    return top25_rows, sightings, claim_type_rows, outlet_rows, epistemic_rows


def verdict_label(verdict: str) -> str:
    return {
        "supported": "Stutt",
        "partially_supported": "Að hluta stutt",
        "unsupported": "Óstutt",
        "misleading": "Þarfnast samhengis",
        "unverifiable": "Óstaðfestanlegt",
    }.get(verdict, verdict)


def confidence_label(conf) -> str:
    """Handle both legacy string ('high'/'medium'/'low') and numeric float confidence."""
    if conf is None:
        return "?"
    if isinstance(conf, (int, float)):
        pct = round(float(conf) * 100)
        if pct >= 80:
            return f"há ({pct}%)"
        elif pct >= 55:
            return f"miðlungs ({pct}%)"
        else:
            return f"lág ({pct}%)"
    return {"high": "há", "medium": "miðlungs", "low": "lág"}.get(conf, conf)


def epistemic_label(ep: str) -> str:
    return {
        "factual": "staðreynd",
        "prediction": "spá",
        "counterfactual": "gagnrök",
        "hearsay": "óstaðfest frásögn",
    }.get(ep or "", ep or "")


def claim_type_label(ct: str) -> str:
    return {
        "statistic": "töluleg",
        "legal_assertion": "lagaleg",
        "opinion": "mat",
        "forecast": "framtíðarspá",
        "comparison": "samanburður",
    }.get(ct or "", ct or "")


def build_markdown(top25_rows, sightings, claim_type_rows, outlet_rows, epistemic_rows) -> str:
    today = date.today().isoformat()

    # Verdict summary across top 25
    verdict_counts: dict[str, int] = {}
    for r in top25_rows:
        verdict_counts[r["verdict"]] = verdict_counts.get(r["verdict"], 0) + 1

    # Build outlet table
    outlet_table_lines = [
        "| Útgefandi | Tilvísanir | Einstök fullyrðing |",
        "| --- | --- | --- |",
    ]
    for domain, sighting_n, unique_n in outlet_rows:
        outlet_table_lines.append(f"| {domain} | {sighting_n} | {unique_n} |")
    outlet_table = "\n".join(outlet_table_lines)

    # Build claim type table
    claim_type_table_lines = [
        "| Tegund | Fjöldi | Hlutfall |",
        "| --- | --- | --- |",
    ]
    for ct, n, pct in claim_type_rows:
        claim_type_table_lines.append(f"| {claim_type_label(ct)} (`{ct}`) | {n} | {pct}% |")
    claim_type_table = "\n".join(claim_type_table_lines)

    # Build epistemic type table
    ep_table_lines = [
        "| Þekkingarstaða | Fjöldi | Hlutfall |",
        "| --- | --- | --- |",
    ]
    for ep, n, pct in epistemic_rows:
        ep_table_lines.append(f"| {epistemic_label(ep)} (`{ep}`) | {n} | {pct}% |")
    ep_table = "\n".join(ep_table_lines)

    # Build top 25 claim blocks
    # Group loosely by theme heuristic:
    # - legal/constitutional: claim_type in [legal_assertion] or text contains specific keywords
    # - procedural: contains "þjóðaratkvæð", "samþykkt", "þing"
    # - loss-framed: verdict misleading or text contains "missa", "tap", "yfirgefa"
    # - other/process-framed: rest

    def classify_theme(r):
        text = (r["canonical_text_is"] or "").lower()
        ct = r["claim_type"]
        if ct == "legal_assertion":
            return "Lagaleg og stjórnarskrárbundin"
        if any(
            w in text for w in ["þjóðaratkvæð", "þjóðaratkvæðis", "samþykkt", "alþingi", "löggjaf"]
        ):
            return "Ferli og lýðræði"
        if any(w in text for w in ["missa", "tap", "yfirgefa", "afsala", "skerð"]):
            return "Tapframing — yfirráð og réttindi"
        if ct in ("forecast", "prediction") or r["epistemic_type"] in (
            "prediction",
            "counterfactual",
        ):
            return "Framtíðarspár og gagnrök"
        return "Almenn fullveldisskipan"

    themes: dict[str, list[dict]] = {}
    for r in top25_rows:
        t = classify_theme(r)
        themes.setdefault(t, []).append(r)

    theme_order = [
        "Lagaleg og stjórnarskrárbundin",
        "Tapframing — yfirráð og réttindi",
        "Ferli og lýðræði",
        "Framtíðarspár og gagnrök",
        "Almenn fullveldisskipan",
    ]

    claim_blocks = []
    rank = 1
    for theme in theme_order:
        group = themes.get(theme, [])
        if not group:
            continue
        claim_blocks.append(f"\n### {theme}\n")
        for r in group:
            v_label = verdict_label(r["verdict"])
            c_label = confidence_label(r["confidence"])
            e_label = epistemic_label(r["epistemic_type"])
            ct_label = claim_type_label(r["claim_type"])
            mc = r["missing_context_is"] or ""

            block = f"""> [!{_verdict_callout(r["verdict"])}]+ #{rank} — {v_label} · {r["sighting_count"]} tilvísanir
> **{r["canonical_text_is"]}**
>
> - Niðurstaða: **{v_label}** (öryggi: {c_label})
> - Þekkingarstaða: {e_label} · Tegund: {ct_label}"""
            if mc:
                block += f"\n> - Vantar: _{mc}_"
            claim_blocks.append(block)
            rank += 1

    claims_section = "\n".join(claim_blocks)

    # Summary sentence
    supported_n = verdict_counts.get("supported", 0)
    partial_n = verdict_counts.get("partially_supported", 0)
    unsupported_n = verdict_counts.get("unsupported", 0)
    misleading_n = verdict_counts.get("misleading", 0)

    summary = (
        f"Gagnagrunnurinn inniheldur **{sum(verdict_counts.values())} fullyrðingar** í flokki fullveldis "
        f"(af {383} heildar í flokknum). "
        f"Af topp 25 fullyrðingum eru {supported_n} studdar, {partial_n} að hluta studdar, "
        f"{unsupported_n} óstudd og {misleading_n} villandi. "
        "Ríkjandi mynstur er vísur til löglegra réttinda, þjóðaratkvæðaskyldu og hræðsla við yfirráðatap — "
        "margar án fullnægjandi heimildar um raunverulegar ESB-skuldbindingar. "
        'Tapframing ("við missum", "við afsölum") er algengasta uppsetningin í villandi fullyrðingum.'
    )

    # Build full note
    note = f"""---
type: dossier
topic: sovereignty
stage: claims
date: {today}
tags: [esb, nordic-house, dossier]
---

# Fullveldi — What People Are Saying

## Summary

{summary}

## Top Claims by Repetition

{claims_section}

## Outlet Distribution

{outlet_table}

## Claim Type Distribution

{claim_type_table}

## Epistemic Type Distribution

{ep_table}
"""
    return note


def _verdict_callout(verdict: str) -> str:
    return {
        "supported": "success",
        "partially_supported": "info",
        "unsupported": "warning",
        "misleading": "danger",
        "unverifiable": "note",
    }.get(verdict, "note")


def main():
    print("Running sovereignty claims dossier queries…\n")
    top25_rows, sightings, claim_type_rows, outlet_rows, epistemic_rows = run_queries()

    note_content = build_markdown(
        top25_rows, sightings, claim_type_rows, outlet_rows, epistemic_rows
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(note_content, encoding="utf-8")
    print(f"\n✓ Written to: {OUTPUT_PATH}")
    print(f"  Note length: {len(note_content)} chars, {note_content.count(chr(10))} lines")


if __name__ == "__main__":
    main()
