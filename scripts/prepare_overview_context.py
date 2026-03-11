"""Prepare Icelandic context file for the editorial writer agent.

Reads data.json from a generated overview and assembles an all-Icelandic
markdown context file (_context_is.md) that the editorial-writer agent
uses as its sole input.

Usage:
    uv run python scripts/prepare_overview_context.py 2026-W11
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from esbvaktin.pipeline.models import TOPIC_LABELS_IS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OVERVIEWS_DIR = PROJECT_ROOT / "data" / "overviews"

# Icelandic verdict labels
VERDICT_LABELS_IS = {
    "supported": "Studd",
    "partially_supported": "Studd að hluta",
    "unsupported": "Óstudd",
    "misleading": "Villandi",
    "unverifiable": "Óstaðfestanleg",
}


def _format_date_is(iso_date: str) -> str:
    """Format ISO date to Icelandic style (e.g., '10. mars 2026')."""
    from datetime import date as date_cls

    MONTHS_IS = {
        1: "janúar", 2: "febrúar", 3: "mars", 4: "apríl",
        5: "maí", 6: "júní", 7: "júlí", 8: "ágúst",
        9: "september", 10: "október", 11: "nóvember", 12: "desember",
    }
    d = date_cls.fromisoformat(iso_date)
    return f"{d.day}. {MONTHS_IS[d.month]} {d.year}"


def _delta_arrow(current: float | int, previous: float | int) -> str:
    """Return an arrow indicator for change direction."""
    if current > previous:
        return f"↑ (úr {previous})"
    elif current < previous:
        return f"↓ (úr {previous})"
    return f"— (óbreytt)"


def _find_previous_editorial(current_slug: str) -> str | None:
    """Find the previous week's editorial opening (first 2 paragraphs).

    This lets the agent avoid repeating transition patterns.
    """
    # List all overview directories, sorted
    overview_dirs = sorted(
        d.name for d in OVERVIEWS_DIR.iterdir()
        if d.is_dir() and (d / "editorial.md").exists()
    )

    # Find the one before current_slug
    try:
        idx = overview_dirs.index(current_slug)
    except ValueError:
        # Current slug not yet generated — use the last one
        idx = len(overview_dirs)

    if idx <= 0:
        return None

    prev_slug = overview_dirs[idx - 1]
    editorial_path = OVERVIEWS_DIR / prev_slug / "editorial.md"
    text = editorial_path.read_text(encoding="utf-8").strip()

    # Extract first 2 paragraphs (skip heading)
    paragraphs = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para or para.startswith("#"):
            continue
        paragraphs.append(para)
        if len(paragraphs) >= 2:
            break

    return "\n\n".join(paragraphs) if paragraphs else None


def prepare_context(slug: str) -> str:
    """Assemble all-Icelandic context markdown from data.json."""
    data_path = OVERVIEWS_DIR / slug / "data.json"
    if not data_path.exists():
        print(f"Error: {data_path} not found. Run generate_overview.py first.")
        sys.exit(1)

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    kn = data["key_numbers"]
    prev = data.get("previous_period", {})
    start_is = _format_date_is(data["period_start"])
    end_is = _format_date_is(data["period_end"])

    lines = []

    # Header with instructions
    lines.append("> **Samhengsskjal:** Vikuyfirlitsgrein ESBvaktin. Skrifaðu 400–600 orða grein.")
    lines.append(">")
    lines.append('> Greinin birtist \u00e1 esbvaktin.is undir \u201eVikuyfirlit\u201c. H\u00fan \u00e1 a\u00f0 vera')
    lines.append("> upplýsandi, hlutlaus og byggð á gögnum. Nefndu einstaklinga og tölur.")
    lines.append("")
    lines.append(f"# Vikuyfirlit — {start_is} til {end_is}")
    lines.append("")

    # Key numbers
    lines.append("## Lykilstærðir")
    articles_delta = _delta_arrow(kn["articles_analysed"], prev.get("articles_analysed", 0))
    claims_delta = _delta_arrow(kn["new_claims_published"], prev.get("new_claims", 0))
    diversity_delta = _delta_arrow(kn["diversity_score"], prev.get("diversity_score", 0))

    lines.append(f"- Greiningar birtar: {kn['articles_analysed']} {articles_delta}")
    lines.append(f"- Nýjar fullyrðingar: {kn['new_claims']} ({kn['new_claims_published']} birtar) {claims_delta}")
    lines.append(f"- Virk efni: {kn['topics_active']}")
    lines.append(f"- Virkir aðilar: {kn['entities_active']}")
    lines.append(f"- Fjölbreytni umræðu: {kn['diversity_score']:.2f} {diversity_delta}")
    lines.append("")

    # Verdict breakdown
    vb = kn.get("verdict_breakdown", {})
    if vb:
        total_verdicts = sum(vb.values())
        lines.append("## Úrskurðardreifing nýrra fullyrðinga")
        for verdict_key in ["supported", "partially_supported", "misleading", "unsupported", "unverifiable"]:
            count = vb.get(verdict_key, 0)
            pct = round(100 * count / total_verdicts, 0) if total_verdicts else 0
            label = VERDICT_LABELS_IS.get(verdict_key, verdict_key)
            lines.append(f"- {label}: {count} ({pct:.0f}%)")
        lines.append("")

    # Topic activity
    topic_activity = data.get("topic_activity", [])
    if topic_activity:
        lines.append("## Efnisyfirlit")
        lines.append("| Efni | Tilvísanir | Nýjar fullyrðingar | Breyting |")
        lines.append("|------|-----------|--------------------|---------| ")
        for t in topic_activity:
            label = t.get("label_is", t["topic"])
            lines.append(f"| {label} | {t['sightings']} | {t['new_claims']} | {t.get('delta', '—')} |")
        lines.append("")

    # Top claims
    top_claims = data.get("top_claims", [])
    if top_claims:
        lines.append("## Athyglisverðustu fullyrðingar")
        for i, c in enumerate(top_claims[:8], 1):
            verdict_is = VERDICT_LABELS_IS.get(c["verdict"], c["verdict"])
            cat_is = c.get("category_is", TOPIC_LABELS_IS.get(c["category"], c["category"]))
            sources_str = ", ".join(c.get("sources", [])[:3])
            lines.append(f'{i}. „{c["canonical_text_is"]}" — {verdict_is} ({c["sighting_count"]} tilvísanir, {cat_is})')
            if sources_str:
                lines.append(f"   Heimildir: {sources_str}")
        lines.append("")

    # Active entities
    active_entities = data.get("active_entities", [])
    if active_entities:
        lines.append("## Virkustu raddirnar")
        for e in active_entities[:10]:
            topics_str = ", ".join(e.get("top_topics", []))
            lines.append(f"- {e['name']}: {e['claims_made']} fullyrðingar ({topics_str})")
        lines.append("")

    # Articles
    articles = data.get("articles", [])
    if articles:
        lines.append("## Greiningarnar")
        for i, a in enumerate(articles, 1):
            cat_is = TOPIC_LABELS_IS.get(a.get("dominant_category", ""), a.get("dominant_category", ""))
            lines.append(f'{i}. „{a["title"]}" — {a["source"]}, {_format_date_is(a["date"])} ({a["claim_count"]} fullyrðingar, {cat_is})')
        lines.append("")

    # Notable quotes
    notable = data.get("notable_quotes", [])
    if notable:
        lines.append("## Athyglisverð tilvitnun")
        for q in notable[:3]:
            verdict_is = VERDICT_LABELS_IS.get(q["verdict"], q["verdict"])
            lines.append(f'> „{q["text"]}"')
            lines.append(f'> — {q["speaker"]}, {q["source"]}')
            lines.append(f'> Úrskurður: {verdict_is}')
            lines.append("")

    # Source breakdown
    sources = data.get("source_breakdown", {})
    if sources:
        lines.append("## Heimildadreifing")
        for domain, count in sources.items():
            lines.append(f"- {domain}: {count} greining(ar)")
        lines.append("")

    # Previous editorial opening (for variety tracking)
    prev_editorial = _find_previous_editorial(slug)
    if prev_editorial:
        lines.append("## Síðasta vikuyfirlit (upphaf)")
        lines.append("> Forðastu sömu setningargerð í opnun og vendipunktum.")
        lines.append("")
        lines.append(prev_editorial)
        lines.append("")

    # Writing instructions
    lines.append("## Leiðbeiningar")
    lines.append("- Lestu knowledge/exemplars_editorial_is.md áður en þú byrjar að skrifa")
    lines.append("- Byrjaðu á áhrifamestu staðreyndinni")
    lines.append("- Nefndu einstaklinga og tölur — ekki skrifa almennt")
    lines.append("- Leggðu mat á hvort umræðan var fjölbreytt eða einsleit")
    lines.append("- Ef villandi fullyrðingar voru áberandi, nefndu þær sérstaklega")
    lines.append("- Gættu jafnvægis — ef villandi fullyrðing frá ESB-andstæðingi er nefnd, nefndu einnig villandi frá ESB-sinni (ef gögnin gefa tilefni)")
    lines.append('- Notaðu ekki orðalag eins og „Þessi vika var áhugaverð" eða „Umræðan var fjörleg"')
    lines.append('- BANNAÐAR opnanir: „Einnig var...", „Í vikunni sem leið...", „Hvað X varðar..."')
    lines.append("- Engin emoji, engin upphrópunarmerki")
    lines.append("- Skrifaðu eins og blaðamaður á fréttastofu — ekki eins og gervigreind")
    lines.append("- Textinn á að vera 400–600 orð")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: prepare_overview_context.py SLUG")
        print("       prepare_overview_context.py 2026-W11")
        sys.exit(1)

    slug = sys.argv[1]
    context = prepare_context(slug)

    # Write context file
    out_path = OVERVIEWS_DIR / slug / "_context_is.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(context)

    # Count words
    word_count = len(context.split())
    print(f"Context written to {out_path} ({word_count} words)")


if __name__ == "__main__":
    main()
