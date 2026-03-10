"""Context preparation for the lightweight fact-check pipeline.

Builds a single context file containing the claim(s) and retrieved evidence,
ready for a subagent to assess. Simpler than the full article analysis pipeline.
Default language is Icelandic ("is").
"""

from pathlib import Path

from .models import ClaimWithEvidence, Verdict
from .prepare_context import _load_icelandic_blocks


def prepare_fact_check_context(
    claims_with_evidence: list[ClaimWithEvidence],
    output_dir: Path,
    language: str = "is",
) -> Path:
    """Write a fact-check context file for the assessment subagent.

    Returns the path to the written context file.
    """
    output_path = output_dir / "_context_fact_check.md"
    lines: list[str] = []

    if language == "is":
        lines.append("# Staðreyndakönnun")
        lines.append("")
        lines.append("Þú ert staðreyndaprófari fyrir ESBvaktin.is, óháðan vettvang um")
        lines.append("þjóðaratkvæðagreiðslu Íslands um ESB-aðild (29. ágúst 2026).")
        lines.append("Þú metur fullyrðingar jafnt hvort sem þær eru ESB-jákvæðar eða ESB-neikvæðar.")
        lines.append("")
        lines.append("## Fullyrðingar til mats")
        lines.append("")
    else:
        lines.append("# Fact-Check Assessment")
        lines.append("")
        lines.append("You are a fact-checker for ESBvaktin.is, an independent platform covering")
        lines.append("Iceland's EU membership referendum (29 August 2026). You assess claims with")
        lines.append("equal rigour regardless of whether they are pro-EU or anti-EU.")
        lines.append("")
        lines.append("## Claims to Assess")
        lines.append("")

    for i, cwe in enumerate(claims_with_evidence, 1):
        claim = cwe.claim
        if language == "is":
            lines.append(f"### Fullyrðing {i}")
            lines.append("")
            lines.append(f"**Texti:** {claim.claim_text}")
            lines.append(f"**Flokkur:** {claim.category}")
            lines.append(f"**Tegund:** {claim.claim_type.value}")
        else:
            lines.append(f"### Claim {i}")
            lines.append("")
            lines.append(f"**Text:** {claim.claim_text}")
            lines.append(f"**Category:** {claim.category}")
            lines.append(f"**Type:** {claim.claim_type.value}")
        lines.append("")

        if cwe.evidence:
            label = "**Heimildir úr staðreyndagrunni:**" if language == "is" else "**Retrieved Evidence:**"
            lines.append(label)
            lines.append("")
            for ev in cwe.evidence:
                lines.append(f"- **{ev.evidence_id}** (similarity: {ev.similarity:.3f})")
                lines.append(f"  {ev.statement}")
                lines.append(f"  *Source: {ev.source_name}*")
                if ev.caveats:
                    lines.append(f"  Caveats: {ev.caveats}")
                lines.append("")
        else:
            no_ev = (
                "**Engar heimildir fundust í staðreyndagrunni.**"
                if language == "is"
                else "**No evidence found in the Ground Truth Database.**"
            )
            lines.append(no_ev)
            lines.append("")

    # Output format (same JSON schema regardless of language)
    if language == "is":
        lines.append("## Úttakssnið")
        lines.append("")
        lines.append("Skrifaðu JSON-fylki í `_assessments.json` (hrátt JSON, engin markdown-umbúðir).")
        lines.append("Skrifaðu `explanation` og `missing_context` á **íslensku**.")
        lines.append("Hvert atriði:")
    else:
        lines.append("## Output Format")
        lines.append("")
        lines.append("Write a JSON array to `_assessments.json` (raw JSON, no markdown wrapping).")
        lines.append("Each element:")
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append('  "claim": {')
    lines.append('    "claim_text": "...",')
    lines.append('    "original_quote": "...",')
    lines.append('    "category": "...",')
    lines.append('    "claim_type": "...",')
    lines.append('    "confidence": 0.9')
    lines.append("  },")
    verdicts = ", ".join(f'"{v.value}"' for v in Verdict)
    lines.append(f'  "verdict": one of {verdicts},')
    if language == "is":
        lines.append('  "explanation": "2-3 setningar á íslensku sem útskýra matið með tilvísun í heimildir",')
        lines.append('  "supporting_evidence": ["EVIDENCE-ID-001"],')
        lines.append('  "contradicting_evidence": [],')
        lines.append('  "missing_context": "mikilvægt samhengi á íslensku, eða null",')
    else:
        lines.append('  "explanation": "2-3 sentences explaining the verdict with specific evidence references",')
        lines.append('  "supporting_evidence": ["EVIDENCE-ID-001"],')
        lines.append('  "contradicting_evidence": [],')
        lines.append('  "missing_context": "any important nuance not covered by evidence, or null",')
    lines.append('  "confidence": 0.85')
    lines.append("}")
    lines.append("```")
    lines.append("")

    # Critical principles
    if language == "is":
        lines.append("## Meginreglur")
        lines.append("")
        lines.append("- **Óhlutdrægni**: metið ESB-jákvæðar og ESB-neikvæðar fullyrðingar jafnt")
        lines.append("- **Heimildum háð**: sérhvert mat VERÐUR að vitna í tilteknar heimildir")
        lines.append("- **Fyrirvarar skipta máli**: komið á framfæri fyrirvörum úr heimildum")
        lines.append("- **Auðmýkt**: ef heimildir duga ekki, notið `unverifiable`")
        lines.append("- Haltu upprunalegu fullyrðingasviðum óbreyttum")
    else:
        lines.append("## Critical Principles")
        lines.append("")
        lines.append("- **Independence**: assess pro-EU and anti-EU claims with equal rigour")
        lines.append("- **Evidence-based**: every verdict MUST cite specific evidence_ids")
        lines.append("- **Caveats matter**: surface the caveats from evidence entries")
        lines.append("- **Humility**: if evidence is insufficient, use `unverifiable`")
        lines.append("- Preserve the original claim fields exactly as given above")

    # Append Icelandic quality blocks for fact-check assessment
    if language == "is":
        blocks = _load_icelandic_blocks()
        if blocks:
            lines.append("")
            lines.append(blocks)

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
