"""Generate Heimildin deliverables from canonicalised claims.

Deliverable 1: Meta-claim frequency table (Markdown)
Deliverable 2: Meta-claim instance detail (Markdown, grouped by meta-claim)
Deliverable 3: Summary CSV (flat, one row per instance)
Deliverable 4: Cross-era comparison summary (Markdown)

Usage:
    uv run python scripts/heimildin/generate_deliverables.py --era esb
    uv run python scripts/heimildin/generate_deliverables.py --era esb --era ees  # comparative
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from io import StringIO
from pathlib import Path

from config import DELIVERABLES_DIR, WORK_DIR


def load_data(era: str) -> tuple[list[dict], list[dict], dict]:
    """Load canonical claims, enriched instances, and era stats."""
    canonical_file = WORK_DIR / f"{era}_canonical.json"
    enriched_file = WORK_DIR / f"{era}_claims_enriched.json"
    stats_file = WORK_DIR / f"{era}_stats.json"

    if not canonical_file.exists() or not enriched_file.exists():
        print(f"Missing data for era '{era}'. Run canonicalise first.")
        sys.exit(1)

    canonical = json.loads(canonical_file.read_text(encoding="utf-8"))
    instances = json.loads(enriched_file.read_text(encoding="utf-8"))
    stats = {}
    if stats_file.exists():
        stats = json.loads(stats_file.read_text(encoding="utf-8"))

    return canonical, instances, stats


def _build_id_lookup(instances: list[dict]) -> dict[str, dict]:
    """Build instance_id → claim dict lookup."""
    return {c["instance_id"]: c for c in instances if "instance_id" in c}


def _instances_for(cc: dict, lookup: dict) -> list[dict]:
    """Get claim instances for a canonical claim using stable IDs."""
    return [
        lookup[iid] for iid in cc.get("instance_ids", [])
        if iid in lookup
    ]


def _speakers_for(cc: dict, lookup: dict) -> list[str]:
    """Get unique speaker names for a canonical claim."""
    return sorted({
        lookup[iid].get("speaker", "?")
        for iid in cc.get("instance_ids", [])
        if iid in lookup
    })


def _parties_for(cc: dict, lookup: dict) -> list[str]:
    """Get unique party names for a canonical claim."""
    return sorted({
        lookup[iid].get("party", "?")
        for iid in cc.get("instance_ids", [])
        if iid in lookup
    })


def generate_d1_frequency(
    eras: list[str],
    canonical_by_era: dict[str, list[dict]],
    lookup_by_era: dict[str, dict],
    stats_by_era: dict[str, dict],
) -> str:
    """D1: Meta-claim frequency table — sorted by frequency, showing speakers."""
    lines = [
        "# Meginfullyrðingar í ESB/EES-umræðu á Alþingi",
        "",
        "Hver lína er ein meginfullyrðing — röksemd sem einn eða fleiri þingmenn "
        "settu fram í umræðum. Raðað eftir tíðni.",
        "",
    ]

    if len(eras) == 1:
        era = eras[0]
        era_label = "ESB (2024–2026)" if era == "esb" else "EES (1991–1993)"
        lookup = lookup_by_era[era]
        stats = stats_by_era.get(era, {})
        total_speeches = stats.get("speeches", "?")

        lines.append(
            f"| # | Meginfullyrðing | Efnisflokkur | Afstaða | Tíðni | "
            f"Þingmenn | Flokkar |"
        )
        lines.append(
            "|---|---------------|--------------|---------|-------|"
            "----------|---------|"
        )

        for i, cc in enumerate(canonical_by_era[era], 1):
            speakers = _speakers_for(cc, lookup)
            parties = _parties_for(cc, lookup)
            speaker_names = ", ".join(s.split()[-1] for s in speakers)
            party_names = ", ".join(parties)
            topic = _topic_label(cc["canonical_id"])
            lines.append(
                f"| {i} | {cc['canonical_text']} | {topic} | {cc['stance']} | "
                f"{cc['instance_count']}× | {speaker_names} | {party_names} |"
            )
    else:
        lines.append(
            "| # | Meginfullyrðing | Efnisflokkur | Afstaða | "
            "ESB (2026) | EES (1991–93) | Þingmenn (ESB) |"
        )
        lines.append(
            "|---|---------------|--------------|---------|"
            "------------|---------------|----------------|"
        )

        esb_lookup = lookup_by_era.get("esb", {})
        for i, cc in enumerate(canonical_by_era.get("esb", []), 1):
            esb_count = cc["instance_count"]
            speakers = _speakers_for(cc, esb_lookup)
            speaker_names = ", ".join(s.split()[-1] for s in speakers)
            topic = _topic_label(cc["canonical_id"])
            ees_count = "—"
            lines.append(
                f"| {i} | {cc['canonical_text']} | {topic} | {cc['stance']} | "
                f"{esb_count}× | {ees_count} | {speaker_names} |"
            )

    total = sum(
        cc["instance_count"]
        for era in eras
        for cc in canonical_by_era.get(era, [])
    )
    unique = sum(len(canonical_by_era.get(era, [])) for era in eras)
    lines.append("")
    lines.append(f"*{total} fullyrðingatilvik, {unique} aðgreindar meginfullyrðingar.*")

    # Add era stats if available
    for era in eras:
        stats = stats_by_era.get(era, {})
        if stats:
            era_label = "ESB" if era == "esb" else "EES"
            lines.append(
                f"*{era_label}: {stats.get('speeches', '?')} ræður, "
                f"{stats.get('total_words', 0):,} orð, "
                f"{stats.get('unique_speakers', '?')} þingmenn.*"
            )

    return "\n".join(lines)


def generate_d2_detail(
    era: str,
    canonical: list[dict],
    lookup: dict,
) -> str:
    """D2: Meta-claim instance detail — grouped by meta-claim, chronological."""
    era_label = "ESB-umræða (2024–2026)" if era == "esb" else "EES-umræða (1991–1993)"
    lines = [
        f"# Meginfullyrðingar og tilvik — {era_label}",
        "",
        "Yfirlit yfir allar meginfullyrðingar í umræðunni. Undir hverri "
        "meginfullyrðingu eru öll tilvik hennar — hvaða þingmaður setti hana "
        "fram, orðrétt tilvitnun, og tengill í ræðuna á althingi.is.",
        "",
    ]

    for cc in canonical:
        n = cc["instance_count"]
        parties = _parties_for(cc, lookup)

        topic = _topic_label(cc["canonical_id"])
        lines.append(f"## {cc['canonical_text']}")
        lines.append(
            f"*{n}× | {topic} | {cc['stance']} | "
            f"Flokkar: {', '.join(parties)}*"
        )
        lines.append("")

        claim_instances = _instances_for(cc, lookup)
        claim_instances.sort(key=lambda c: c.get("date", ""))

        for inst in claim_instances:
            lines.append(
                f"- **{inst['speaker']}** ({inst['party']}) — "
                f"{inst['date']}"
            )
            url = inst.get("speech_url", "")
            if url:
                lines.append(f"  {url}")
            quote = inst.get("exact_quote", "").replace("\n", " ")
            if quote:
                lines.append(f"  > {quote}")
            lines.append("")

    return "\n".join(lines)


def generate_d3_csv(
    era: str,
    canonical: list[dict],
    instances: list[dict],
) -> str:
    """D3: Flat CSV — one row per claim instance."""
    canon_lookup = {
        cc["canonical_id"]: cc["canonical_text"]
        for cc in canonical
    }

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "canonical_claim",
        "canonical_id",
        "instance_id",
        "exact_wording",
        "date",
        "speech_url",
        "mp_name",
        "party",
        "era",
        "topic",
        "stance",
    ])

    sorted_instances = sorted(instances, key=lambda c: c.get("date", ""))

    for inst in sorted_instances:
        cid = inst.get("canonical_id", "UNMAPPED")
        writer.writerow([
            canon_lookup.get(cid, inst.get("claim_summary", "")),
            cid,
            inst.get("instance_id", ""),
            inst.get("exact_quote", ""),
            inst.get("date", ""),
            inst.get("speech_url", ""),
            inst.get("speaker", ""),
            inst.get("party", ""),
            era.upper(),
            inst.get("topic", ""),
            inst.get("stance", ""),
        ])

    return output.getvalue()


def generate_cross_era_summary(
    canonical_by_era: dict[str, list[dict]],
    lookup_by_era: dict[str, dict],
    stats_by_era: dict[str, dict],
) -> str | None:
    """Generate cross-era comparison summary from theme matching."""
    themes_file = WORK_DIR / "canonicalise" / "cross_era_themes.json"
    if not themes_file.exists():
        return None

    themes = json.loads(themes_file.read_text(encoding="utf-8"))

    esb_lookup_cc = {c["canonical_id"]: c for c in canonical_by_era.get("esb", [])}
    ees_lookup_cc = {c["canonical_id"]: c for c in canonical_by_era.get("ees", [])}

    esb_stats = stats_by_era.get("esb", {})
    ees_stats = stats_by_era.get("ees", {})

    lines = [
        "# Samanburður á ESB- og EES-umræðu á Alþingi",
        "",
        "Hvaða röksemdafærslur lifðu af 30 ár? Hverjar hurfu? Hverjar eru nýjar?",
        "",
        "Greining á meginfullyrðingum í þingumræðum um Evrópska efnahagssvæðið "
        "(1991–1993) og þjóðaratkvæðagreiðslu um ESB-aðild (2024–2026).",
        "",
    ]

    # Add corpus stats
    if esb_stats or ees_stats:
        lines.append("### Gögn")
        lines.append("")
        lines.append("| | ESB (2026) | EES (1991–93) |")
        lines.append("|---|-----------|---------------|")
        lines.append(
            f"| Ræður | {esb_stats.get('speeches', '?')} | "
            f"{ees_stats.get('speeches', '?')} |"
        )
        lines.append(
            f"| Orð | {esb_stats.get('total_words', 0):,} | "
            f"{ees_stats.get('total_words', 0):,} |"
        )
        lines.append(
            f"| Þingmenn | {esb_stats.get('unique_speakers', '?')} | "
            f"{ees_stats.get('unique_speakers', '?')} |"
        )
        lines.append(
            f"| Fullyrðingatilvik | {esb_stats.get('total_claims', '?')} | "
            f"{ees_stats.get('total_claims', '?')} |"
        )
        lines.append("")

    for type_key, type_label, type_desc in [
        ("perennial", "Röksemdafærslur sem lifðu af 30 ár",
         "Þessar röksemdafærslur birtast í báðum umræðum — frá EES-samningnum "
         "1991–1993 og ESB-þjóðaratkvæðagreiðslunni 2026."),
        ("new_2026", "Nýjar röksemdafærslur 2026",
         "Þessar röksemdafærslur birtast aðeins í ESB-umræðunni 2026 — "
         "þær áttu sér enga hliðstæðu í EES-umræðunni."),
        ("disappeared", "Röksemdafærslur sem hurfu",
         "Þessar röksemdafærslur voru áberandi í EES-umræðunni 1991–1993 "
         "en birtast ekki í ESB-umræðunni 2026."),
    ]:
        type_themes = [t for t in themes if t.get("type") == type_key]
        if not type_themes:
            continue

        lines.append(f"## {type_label}")
        lines.append("")
        lines.append(type_desc)
        lines.append("")

        def _total(t):
            esb_n = sum(
                esb_lookup_cc[i]["instance_count"]
                for i in t.get("esb_ids", []) if i in esb_lookup_cc
            )
            ees_n = sum(
                ees_lookup_cc[i]["instance_count"]
                for i in t.get("ees_ids", []) if i in ees_lookup_cc
            )
            return esb_n + ees_n

        type_themes.sort(key=_total, reverse=True)

        lines.append(
            "| Meginfullyrðing | ESB (2026) | EES (1991–93) | Athugasemd |"
        )
        lines.append(
            "|---------------|------------|---------------|------------|"
        )

        for t in type_themes:
            theme = t.get("theme", "?")
            note = t.get("note", "")

            esb_n = sum(
                esb_lookup_cc[i]["instance_count"]
                for i in t.get("esb_ids", []) if i in esb_lookup_cc
            )
            ees_n = sum(
                ees_lookup_cc[i]["instance_count"]
                for i in t.get("ees_ids", []) if i in ees_lookup_cc
            )

            esb_str = f"{esb_n}×" if esb_n else "—"
            ees_str = f"{ees_n}×" if ees_n else "—"

            lines.append(
                f"| {theme} | {esb_str} | {ees_str} | {note} |"
            )

        lines.append("")

    # Summary
    perennial = [t for t in themes if t.get("type") == "perennial"]
    new_2026 = [t for t in themes if t.get("type") == "new_2026"]
    disappeared = [t for t in themes if t.get("type") == "disappeared"]

    lines.append("## Samantekt")
    lines.append("")
    lines.append(f"- **{len(perennial)}** röksemdafærslur birtast í báðum umræðum")
    lines.append(f"- **{len(new_2026)}** röksemdafærslur eru nýjar 2026")
    lines.append(f"- **{len(disappeared)}** röksemdafærslur hurfu frá 1993")

    return "\n".join(lines)


def _topic_label(canonical_id: str) -> str:
    """Extract topic from canonical_id prefix."""
    prefix = canonical_id.split("-")[0] if "-" in canonical_id else "OTH"
    labels = {
        "FIS": "sjávarútvegur", "TRA": "viðskipti", "SOV": "fullveldi",
        "EEA": "EES/ESB-löggjöf", "AGR": "landbúnaður", "PRE": "fordæmi",
        "CUR": "gjaldmiðill", "LAB": "vinnumarkaður", "ENE": "orkumál",
        "HOU": "húsnæðismál", "DEF": "varnarmál", "DEM": "lýðræði/ferli",
        "ENV": "umhverfismál", "OTH": "annað",
    }
    return labels.get(prefix, prefix)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Heimildin deliverables"
    )
    parser.add_argument("--era", action="append", default=[],
                        help="Era(s) to include (esb, ees). Can specify multiple.")

    args = parser.parse_args()
    eras = args.era if args.era else ["esb"]

    canonical_by_era = {}
    instances_by_era = {}
    lookup_by_era = {}
    stats_by_era = {}

    for era in eras:
        canonical, instances, stats = load_data(era)
        canonical_by_era[era] = canonical
        instances_by_era[era] = instances
        lookup_by_era[era] = _build_id_lookup(instances)
        stats_by_era[era] = stats

    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)

    # D1: Meta-claim frequency
    d1 = generate_d1_frequency(eras, canonical_by_era, lookup_by_era, stats_by_era)
    d1_file = DELIVERABLES_DIR / "D1_claim_frequency.md"
    d1_file.write_text(d1, encoding="utf-8")
    print(f"D1 written: {d1_file}")

    # D2 + D3: Per-era
    for era in eras:
        era_label = era.upper()

        d2 = generate_d2_detail(era, canonical_by_era[era], lookup_by_era[era])
        d2_file = DELIVERABLES_DIR / f"D2_claim_detail_{era_label}.md"
        d2_file.write_text(d2, encoding="utf-8")
        print(f"D2 written: {d2_file}")

        d3 = generate_d3_csv(era, canonical_by_era[era], instances_by_era[era])
        d3_file = DELIVERABLES_DIR / f"D3_summary_{era_label}.csv"
        d3_file.write_text(d3, encoding="utf-8")
        print(f"D3 written: {d3_file}")

    # D4: Cross-era summary (if matching data exists)
    if len(eras) > 1:
        cross = generate_cross_era_summary(
            canonical_by_era, lookup_by_era, stats_by_era
        )
        if cross:
            cross_file = DELIVERABLES_DIR / "D4_cross_era_summary.md"
            cross_file.write_text(cross, encoding="utf-8")
            print(f"D4 written: {cross_file}")
        else:
            print("D4 skipped: no cross_era_themes.json found")

    print(f"\nAll deliverables in {DELIVERABLES_DIR}/")


if __name__ == "__main__":
    main()
