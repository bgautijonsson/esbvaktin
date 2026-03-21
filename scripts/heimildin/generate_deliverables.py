"""Generate Heimildin deliverables from canonicalised claims.

Deliverable 1: Meta-claim frequency table (Markdown)
Deliverable 2: Meta-claim instance detail (Markdown, grouped by meta-claim)
Deliverable 3: Summary CSV (flat, one row per instance)

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


def load_data(era: str) -> tuple[list[dict], list[dict]]:
    """Load canonical claims and enriched instances for an era."""
    canonical_file = WORK_DIR / f"{era}_canonical.json"
    enriched_file = WORK_DIR / f"{era}_claims_enriched.json"

    if not canonical_file.exists() or not enriched_file.exists():
        print(f"Missing data for era '{era}'. Run canonicalise first.")
        sys.exit(1)

    canonical = json.loads(canonical_file.read_text(encoding="utf-8"))
    instances = json.loads(enriched_file.read_text(encoding="utf-8"))

    return canonical, instances


def _speakers_for(cc: dict, instances: list[dict]) -> list[str]:
    """Get unique speaker names for a canonical claim."""
    speakers = set()
    for idx in cc.get("instance_indices", []):
        if idx < len(instances):
            speakers.add(instances[idx].get("speaker", "?"))
    return sorted(speakers)


def _parties_for(cc: dict, instances: list[dict]) -> list[str]:
    """Get unique party names for a canonical claim."""
    parties = set()
    for idx in cc.get("instance_indices", []):
        if idx < len(instances):
            parties.add(instances[idx].get("party", "?"))
    return sorted(parties)


def generate_d1_frequency(
    eras: list[str],
    canonical_by_era: dict[str, list[dict]],
    instances_by_era: dict[str, list[dict]],
) -> str:
    """D1: Meta-claim frequency table — sorted by frequency, showing speakers."""
    lines = [
        "# Meginfullyrðingar í ESB-umræðu á Alþingi",
        "",
        "Hver lína er ein meginfullyrðing — röksemd sem einn eða fleiri þingmenn "
        "settu fram í umræðum. Raðað eftir tíðni (hversu margir þingmenn settu "
        "fullyrðinguna fram).",
        "",
    ]

    if len(eras) == 1:
        era = eras[0]
        era_label = "ESB (2024–2026)" if era == "esb" else "EES (1991–1993)"
        instances = instances_by_era[era]

        lines.append(
            f"| # | Meginfullyrðing | Efnisflokkur | Afstaða | Tíðni | "
            f"Þingmenn | Flokkar |"
        )
        lines.append(
            "|---|---------------|--------------|---------|-------|"
            "----------|---------|"
        )

        for i, cc in enumerate(canonical_by_era[era], 1):
            speakers = _speakers_for(cc, instances)
            parties = _parties_for(cc, instances)
            speaker_names = ", ".join(s.split()[-1] for s in speakers)
            party_names = ", ".join(parties)
            topic = _topic_label(cc["canonical_id"])
            lines.append(
                f"| {i} | {cc['canonical_text']} | {topic} | {cc['stance']} | "
                f"{cc['instance_count']}× | {speaker_names} | {party_names} |"
            )
    else:
        # Comparative mode
        lines.append(
            "| # | Meginfullyrðing | Afstaða | "
            "ESB (2024–2026) | EES (1991–1993) | Þingmenn (ESB) |"
        )
        lines.append(
            "|---|---------------|---------|"
            "-----------------|-----------------|----------------|"
        )

        esb_instances = instances_by_era.get("esb", [])
        for i, cc in enumerate(canonical_by_era.get("esb", []), 1):
            esb_count = cc["instance_count"]
            speakers = _speakers_for(cc, esb_instances)
            speaker_names = ", ".join(s.split()[-1] for s in speakers)
            # TODO: cross-era canonical matching
            ees_count = "—"
            lines.append(
                f"| {i} | {cc['canonical_text']} | {cc['stance']} | "
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

    return "\n".join(lines)


def generate_d2_detail(
    era: str,
    canonical: list[dict],
    instances: list[dict],
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
        speakers = _speakers_for(cc, instances)
        parties = _parties_for(cc, instances)

        topic = _topic_label(cc["canonical_id"])
        lines.append(f"## {cc['canonical_text']}")
        lines.append(
            f"*{n}× | {topic} | {cc['stance']} | "
            f"Flokkar: {', '.join(parties)}*"
        )
        lines.append("")

        # Get instances for this canonical claim
        claim_instances = [
            instances[idx] for idx in cc.get("instance_indices", [])
            if idx < len(instances)
        ]
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

    for era in eras:
        canonical, instances = load_data(era)
        canonical_by_era[era] = canonical
        instances_by_era[era] = instances

    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)

    # D1: Meta-claim frequency
    d1 = generate_d1_frequency(eras, canonical_by_era, instances_by_era)
    d1_file = DELIVERABLES_DIR / "D1_claim_frequency.md"
    d1_file.write_text(d1, encoding="utf-8")
    print(f"D1 written: {d1_file}")

    # D2 + D3: Per-era
    for era in eras:
        era_label = era.upper()

        d2 = generate_d2_detail(era, canonical_by_era[era], instances_by_era[era])
        d2_file = DELIVERABLES_DIR / f"D2_claim_detail_{era_label}.md"
        d2_file.write_text(d2, encoding="utf-8")
        print(f"D2 written: {d2_file}")

        d3 = generate_d3_csv(era, canonical_by_era[era], instances_by_era[era])
        d3_file = DELIVERABLES_DIR / f"D3_summary_{era_label}.csv"
        d3_file.write_text(d3, encoding="utf-8")
        print(f"D3 written: {d3_file}")

    print(f"\nAll deliverables in {DELIVERABLES_DIR}/")


if __name__ == "__main__":
    main()
