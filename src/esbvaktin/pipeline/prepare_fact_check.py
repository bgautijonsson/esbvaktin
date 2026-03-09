"""Context preparation for the lightweight fact-check pipeline.

Builds a single context file containing the claim(s) and retrieved evidence,
ready for a subagent to assess. Simpler than the full article analysis pipeline.
"""

from pathlib import Path

from .models import ClaimWithEvidence, Verdict


def prepare_fact_check_context(
    claims_with_evidence: list[ClaimWithEvidence],
    output_dir: Path,
) -> Path:
    """Write a fact-check context file for the assessment subagent.

    Returns the path to the written context file.
    """
    output_path = output_dir / "_context_fact_check.md"
    lines: list[str] = []

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
        lines.append(f"### Claim {i}")
        lines.append("")
        lines.append(f"**Text:** {claim.claim_text}")
        lines.append(f"**Category:** {claim.category}")
        lines.append(f"**Type:** {claim.claim_type.value}")
        lines.append("")

        if cwe.evidence:
            lines.append("**Retrieved Evidence:**")
            lines.append("")
            for ev in cwe.evidence:
                lines.append(f"- **{ev.evidence_id}** (similarity: {ev.similarity:.3f})")
                lines.append(f"  {ev.statement}")
                lines.append(f"  *Source: {ev.source_name}*")
                if ev.caveats:
                    lines.append(f"  Caveats: {ev.caveats}")
                lines.append("")
        else:
            lines.append("**No evidence found in the Ground Truth Database.**")
            lines.append("")

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
    lines.append('  "explanation": "2-3 sentences explaining the verdict with specific evidence references",')
    lines.append('  "supporting_evidence": ["EVIDENCE-ID-001"],')
    lines.append('  "contradicting_evidence": [],')
    lines.append('  "missing_context": "any important nuance not covered by evidence, or null",')
    lines.append('  "confidence": 0.85')
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append("## Critical Principles")
    lines.append("")
    lines.append("- **Independence**: assess pro-EU and anti-EU claims with equal rigour")
    lines.append("- **Evidence-based**: every verdict MUST cite specific evidence_ids")
    lines.append("- **Caveats matter**: surface the caveats from evidence entries")
    lines.append("- **Humility**: if evidence is insufficient, use `unverifiable`")
    lines.append("- Preserve the original claim fields exactly as given above")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
