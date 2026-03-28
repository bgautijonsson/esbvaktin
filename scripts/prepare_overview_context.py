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

    months_is = {
        1: "janúar",
        2: "febrúar",
        3: "mars",
        4: "apríl",
        5: "maí",
        6: "júní",
        7: "júlí",
        8: "ágúst",
        9: "september",
        10: "október",
        11: "nóvember",
        12: "desember",
    }
    d = date_cls.fromisoformat(iso_date)
    return f"{d.day}. {months_is[d.month]} {d.year}"


def _delta_arrow(current: float | int, previous: float | int) -> str:
    """Return an arrow indicator for change direction."""
    if current > previous:
        return f"↑ (úr {previous})"
    elif current < previous:
        return f"↓ (úr {previous})"
    return "— (óbreytt)"


def _find_previous_editorial(current_slug: str) -> str | None:
    """Find the previous week's editorial opening (first 2 paragraphs).

    This lets the agent avoid repeating transition patterns.
    """
    # List all overview directories, sorted
    overview_dirs = sorted(
        d.name for d in OVERVIEWS_DIR.iterdir() if d.is_dir() and (d / "editorial.md").exists()
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


def _truncate_caveat(text: str, max_chars: int = 200) -> str:
    """Truncate caveat at word boundary."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.6:
        truncated = truncated[:last_space]
    return truncated + "…"


def prepare_context(slug: str) -> str:
    """Assemble all-Icelandic context markdown from data.json.

    Structured as a news digest: what was discussed, what context readers need,
    how the rhetoric has evolved, and what's missing from the debate.
    """
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
    lines.append("> Greinin er fréttayfirlit — hún hjálpar lesendum að skilja hvað var rætt,")
    lines.append("> hvaða samhengi skiptir máli, og hvað vantar í umræðuna.")
    lines.append(
        "> Ekki merkja fullyrðingar sem \u201evillandi\u201c eða \u201eósannar\u201c — sýndu samhengið"
    )
    lines.append("> og láttu lesandann draga ályktanir.")
    lines.append("")
    lines.append(f"# Tímabil: {start_is} til {end_is}")
    lines.append("")

    # ── Section 1: Key numbers ──
    lines.append("## Lykilstærðir")
    articles_delta = _delta_arrow(kn["articles_analysed"], prev.get("articles_analysed", 0))
    claims_delta = _delta_arrow(
        kn["new_claims_published"],
        prev.get("new_claims_published", prev.get("new_claims", 0)),
    )
    diversity_delta = _delta_arrow(kn["diversity_score"], prev.get("diversity_score", 0))

    lines.append(f"- Greiningar: {kn['articles_analysed']} {articles_delta}")
    lines.append(f"- Fullyrðingar í umræðunni: {kn['new_claims_published']} birtar {claims_delta}")
    lines.append(f"- Virk málefni: {kn['topics_active']}")
    lines.append(f"- Virkir aðilar: {kn['entities_active']}")
    lines.append(f"- Fjölbreytni umræðu: {kn['diversity_score']:.2f} {diversity_delta}")
    lines.append("")

    # ── Section 2: Topic activity with evolution ──
    topic_activity = data.get("topic_activity", [])
    if topic_activity:
        lines.append("## Hvað var rætt? — Efnisþróun")
        lines.append("| Efni | Tilvísanir | Breyting frá síðustu viku |")
        lines.append("|------|-----------|--------------------------|")
        for t in topic_activity:
            label = t.get("label_is", t["topic"])
            lines.append(f"| {label} | {t['sightings']} | {t.get('delta', '—')} |")
        lines.append("")

    # Epistemic type labels for the context
    epistemic_labels_is = {
        "factual": "staðreynd",
        "prediction": "spá",
        "counterfactual": "tilgáta",
        "hearsay": "HLUSTAÐARSÖGN",
    }

    # ── Section 3: Most-discussed claims with context ──
    top_claims = data.get("top_claims", [])
    if top_claims:
        # Separate hearsay claims for a dedicated warning section
        hearsay_claims = [c for c in top_claims if c.get("epistemic_type") == "hearsay"]
        verified_claims = [c for c in top_claims if c.get("epistemic_type") != "hearsay"]

        if hearsay_claims:
            lines.append("## ⚠️ Hlustaðarsagnir — ekki setja fram sem staðreyndir")
            lines.append("> Þessar fullyrðingar byggja á óstaðfestum heimildum (ónafngreindir")
            lines.append("> aðilar, óbeinar tilvísanir). Ef þú nefnir þær í greininni VERÐUR þú")
            lines.append(
                '> að nota tilvísunarorð: „sagt er að", „ónafngreindir fundargestir sögðu",'
            )
            lines.append('> „fullyrt var". Aldrei setja fram sem staðfesta afstöðu viðkomandi.')
            lines.append("")
            for i, c in enumerate(hearsay_claims, 1):
                cat_is = c.get(
                    "category_is",
                    TOPIC_LABELS_IS.get(c["category"], c["category"]),
                )
                lines.append(f'{i}. ⚠️ „{c["canonical_text_is"]}"')
                lines.append(
                    f"   Tegund: HLUSTAÐARSÖGN · Efni: {cat_is} · Tilvísanir: {c['sighting_count']}"
                )
                if c.get("explanation"):
                    ctx = _truncate_caveat(c["explanation"], 250)
                    lines.append(f"   Hvað vitum við: {ctx}")
                lines.append("")

        lines.append("## Umræðuefni vikunnar — helstu fullyrðingar")
        lines.append(
            "> Ekki nota úrskurðarorð eins og \u201evillandi\u201c eða \u201eóstudd\u201c í greininni."
        )
        lines.append("> Segðu í staðinn hvað heimildir sýna og hvaða samhengi lesandinn þarf.")
        lines.append("")
        for i, c in enumerate(verified_claims[:8], 1):
            cat_is = c.get(
                "category_is",
                TOPIC_LABELS_IS.get(c["category"], c["category"]),
            )
            ep_type = c.get("epistemic_type", "factual")
            ep_label = epistemic_labels_is.get(ep_type, ep_type)
            conf = c.get("confidence", 0.5)
            sources_str = ", ".join(c.get("sources", [])[:3])

            lines.append(f'{i}. „{c["canonical_text_is"]}"')
            type_str = f"   Tegund: {ep_label} · Efni: {cat_is} · Tilvísanir: {c['sighting_count']}"
            if conf < 0.6:
                type_str += " · ⚠️ Lítið traust"
            lines.append(type_str)
            if c.get("missing_context"):
                ctx = _truncate_caveat(c["missing_context"], 250)
                lines.append(f"   Samhengi sem skiptir máli: {ctx}")
            elif c.get("explanation"):
                ctx = _truncate_caveat(c["explanation"], 250)
                lines.append(f"   Hvað heimildir segja: {ctx}")
            if sources_str:
                lines.append(f"   Heimildir: {sources_str}")
            lines.append("")

    # ── Section 4: Active entities ──
    active_entities = data.get("active_entities", [])
    if active_entities:
        lines.append("## Virkustu raddirnar")
        for e in active_entities[:10]:
            topics_str = ", ".join(e.get("top_topics", []))
            lines.append(f"- {e['name']}: {e['claims_made']} fullyrðingar ({topics_str})")
        lines.append("")

    # ── Section 5: Articles ──
    articles = data.get("articles", [])
    if articles:
        lines.append("## Greiningarnar")
        for i, a in enumerate(articles, 1):
            cat_is = TOPIC_LABELS_IS.get(
                a.get("dominant_category", ""),
                a.get("dominant_category", ""),
            )
            lines.append(
                f'{i}. „{a["title"]}" — {a["source"]},'
                f" {_format_date_is(a['date'])} ({a['claim_count']} fullyrðingar, {cat_is})"
            )
        lines.append("")

    # ── Section 6: Key facts — learnable context ──
    key_facts = data.get("key_facts", [])
    if key_facts:
        lines.append("## Staðreyndir sem gott er að þekkja")
        lines.append("> Veldu 1–2 af þessum staðreyndum til að útskýra í greininni —")
        lines.append("> þær hjálpa lesendum að skilja umræðuna betur.")
        lines.append("")
        for f in key_facts[:4]:
            cat_is = f.get("category_is", f.get("category", ""))
            lines.append(f"- **{cat_is}**: {f['claim_text']}")
            if f.get("caveat"):
                lines.append(f"  - Gott að vita: {_truncate_caveat(f['caveat'])}")
            lines.append("")

    # ── Section 7: Under-discussed topics ──
    under_discussed = data.get("under_discussed", [])
    if under_discussed:
        lines.append("## Hvað vantar í umræðuna?")
        lines.append("> Þessi efni hafa mikilvægar heimildir í gagnagrunni ESBvaktin")
        lines.append("> en komu varla við sögu í umræðunni þessa viku.")
        lines.append("")
        for ud in under_discussed[:5]:
            sightings = ud["sightings_this_period"]
            sighting_str = f"{sightings} tilvísun(ir)" if sightings else "ekkert rætt"
            lines.append(
                f"- **{ud['label_is']}**: {ud['evidence_entries']} heimildir"
                f" í gagnagrunni, {sighting_str} þessa viku"
            )
        lines.append("")

    # ── Previous editorial opening (for variety tracking) ──
    prev_editorial = _find_previous_editorial(slug)
    if prev_editorial:
        lines.append("## Síðasta vikuyfirlit (upphaf)")
        lines.append("> Forðastu sömu setningargerð í opnun og vendipunktum.")
        lines.append("")
        lines.append(prev_editorial)
        lines.append("")

    # ── Writing instructions ──
    lines.append("## Leiðbeiningar")
    lines.append("- Lestu knowledge/exemplars_editorial_is.md áður en þú byrjar")
    lines.append("- Greinin er fréttayfirlit, ekki staðreyndamat — hjálpaðu lesendum að skilja")
    lines.append("- Byrjaðu á áhugaverðasta atriðinu — staðreynd, spurning eða þróun")
    lines.append("- Nefndu einstaklinga og tölur — ekki skrifa almennt")
    lines.append(
        "- Segðu hvað heimildir sýna frekar en að merkja fullyrðingar sem réttar eða rangar"
    )
    lines.append("- Nefndu hvort umræðan þéttist eða breikkist — samanborið við fyrri vikur")
    lines.append(
        "- Nefndu ef mikilvæg málefni fá lítið rými (sjá \u201eHvað vantar í umræðuna?\u201c)"
    )
    lines.append('- BANNAÐAR opnanir: „Einnig var...", „Í vikunni sem leið...", „Hvað X varðar..."')
    lines.append(
        "- BANNAÐ: orðin \u201evillandi\u201c, \u201eóstudd\u201c, \u201eósönn\u201c um fullyrðingar einstaklinga"
    )
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
