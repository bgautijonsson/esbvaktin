"""Context preparation for the gap analysis subagent.

Writes a markdown context file that a subagent reads to generate
targeted research tasks for each evidence gap.
"""

from pathlib import Path

from .models import EvidenceGap, GapCategory


_CATEGORY_DESCRIPTIONS = {
    GapCategory.MISSING_DATA: "Gögn eru til en vantar í staðreyndagrunn",
    GapCategory.SPECULATIVE: "Fullyrðingin er í eðli sínu óstaðfestanleg (spá/tilgáta)",
    GapCategory.RECENT_EVENT: "Vísar í nýlegan atburð sem ekki er enn skráður",
    GapCategory.SOURCE_NEEDED: "Fullyrðingin gæti verið rétt en heimild vantar",
    GapCategory.CONTRADICTORY: "Misvísandi heimildir — þarf nánari rannsókn",
}


def prepare_gap_context(
    gaps: list[EvidenceGap],
    output_dir: Path,
) -> Path:
    """Write context for the research-planning subagent.

    The subagent reads this and produces _research_tasks.json with
    specific research strategies for each gap.
    """
    lines: list[str] = []

    lines.append("# Rannsóknaráætlun — eyður í heimildum")
    lines.append("")
    lines.append("Þú ert að skipuleggja rannsóknaráætlun til að fylla eyður í")
    lines.append("staðreyndagrunni ESBvaktin.is. Fyrir hverja eyðu hér að neðan,")
    lines.append("stingdu upp á sérstakri rannsóknaraðferð.")
    lines.append("")
    lines.append(f"## {len(gaps)} eyður greindar")
    lines.append("")

    for i, gap in enumerate(gaps, 1):
        cat_desc = _CATEGORY_DESCRIPTIONS.get(gap.gap_category, gap.gap_category.value)
        lines.append(f"### Eyða {i}: {gap.claim_text[:80]}...")
        lines.append("")
        lines.append(f"- **Flokkur**: {gap.category}")
        lines.append(f"- **Tegund eyðu**: {cat_desc}")
        quote = gap.original_quote[:120] if gap.original_quote else ""
        lines.append(f"- **Upprunaleg tilvitnun**: \u201E{quote}...\u201C")
        lines.append(f"- **Af hverju ósannreynanleg**: {gap.explanation}")
        if gap.missing_context:
            lines.append(f"- **Samhengi sem vantar**: {gap.missing_context}")
        if gap.evidence_ids_consulted:
            lines.append(f"- **Heimildir sem voru skoðaðar**: {', '.join(gap.evidence_ids_consulted)}")
        lines.append("")

    lines.append("## Úttakssnið / Output Format")
    lines.append("")
    lines.append("Skrifaðu JSON-fylki í `_research_tasks.json`. Hvert atriði:")
    lines.append("")
    lines.append("```json")
    lines.append("[")
    lines.append("  {")
    lines.append('    "title": "Stutt lýsing á rannsóknarverkefni (á íslensku)",')
    lines.append('    "description": "Ítarlegri lýsing á hvað þarf að finna út (á íslensku)",')
    lines.append('    "gap_index": 1,')
    lines.append('    "research_type": "data_search | document_review | expert_contact | legislative_check",')
    lines.append('    "priority": "high | medium | low",')
    lines.append('    "suggested_sources": ["Hagstofa Íslands", "EU DG-MARE", "..."],')
    lines.append('    "estimated_effort_hours": 2.0,')
    lines.append('    "notes": "Viðbótarupplýsingar (valfrjálst)"')
    lines.append("  }")
    lines.append("]")
    lines.append("```")
    lines.append("")
    lines.append("## Leiðbeiningar")
    lines.append("")
    lines.append("- Vertu raunhæf/ur um mat á vinnutíma")
    lines.append("- Stingdu upp á sérstökum heimildum (nöfn stofnana, gagnabanka, sérfræðinga)")
    lines.append('- Fyrir „speculative\u201C eyður: metið hvort yfir höfuð sé hægt að fylla eyðuna')
    lines.append('  eða hvort merkja eigi fullyrðinguna sem ósannreynanlega til frambúðar')
    lines.append('- Forgangur (priority): „high\u201C ef eyðan snertir algeng umræðuefni,')
    lines.append('  „medium\u201C ef tiltölulega sérhæfð, „low\u201C ef mjög sértæk')

    output_path = output_dir / "_context_gap_analysis.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
