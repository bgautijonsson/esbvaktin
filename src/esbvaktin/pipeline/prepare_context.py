"""Context preparation for Claude Code subagents.

Writes markdown context files to disk that subagents read for
claim extraction, assessment, omission analysis, and translation.
Each file embeds the full prompt instructions — the subagent just
reads the file and writes structured output.
"""

from pathlib import Path

from .models import ClaimWithEvidence


def prepare_extraction_context(
    article_text: str,
    output_dir: Path,
    metadata: dict | None = None,
) -> Path:
    """Write extraction context for the claim-extraction subagent.

    Returns path to the context file.
    """
    meta_section = ""
    if metadata:
        lines = [f"- **{k}**: {v}" for k, v in metadata.items() if v]
        if lines:
            meta_section = "## Article Metadata\n\n" + "\n".join(lines) + "\n\n"

    context = f"""# Claim Extraction Task

You are analysing an article related to Iceland's EU membership referendum
(29 August 2026). Your job is to extract all **factual claims** from the
article that can be checked against evidence.

## Instructions

1. Read the article carefully
2. Identify every factual claim (statistics, legal assertions, comparisons,
   predictions). Skip pure opinions unless they contain implicit factual claims.
3. For each claim, provide:
   - `claim_text`: The factual claim restated clearly
   - `original_quote`: The exact quote from the article
   - `category`: One of: fisheries, trade, sovereignty, eea_eu_law, agriculture,
     precedents, currency, labour, polling, party_positions, org_positions, other
   - `claim_type`: One of: statistic, legal_assertion, comparison, prediction, opinion
   - `confidence`: How confident you are this is a factual claim (0-1)

## Important

- Be thorough — extract ALL factual claims, not just obvious ones
- Preserve the original language of quotes
- Categorise accurately — this determines which evidence is retrieved
- Mark opinions that contain implicit factual claims as claims with
  `claim_type: "opinion"` and lower confidence

## Output Format

Write a JSON array inside a code block:

```json
[
  {{
    "claim_text": "...",
    "original_quote": "...",
    "category": "...",
    "claim_type": "...",
    "confidence": 0.9
  }}
]
```

{meta_section}## Article Text

{article_text}
"""
    output_path = output_dir / "_context_extraction.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path


def prepare_assessment_context(
    claims_with_evidence: list[ClaimWithEvidence],
    output_dir: Path,
) -> Path:
    """Write assessment context for the claim-assessment subagent.

    Returns path to the context file.
    """
    claims_section = ""
    for i, cwe in enumerate(claims_with_evidence, 1):
        claim = cwe.claim
        claims_section += f"""### Claim {i}

- **Claim**: {claim.claim_text}
- **Original quote**: "{claim.original_quote}"
- **Category**: {claim.category}
- **Type**: {claim.claim_type.value}

**Evidence from Ground Truth Database:**

"""
        if not cwe.evidence:
            claims_section += "_No relevant evidence found in database._\n\n"
        else:
            for ev in cwe.evidence:
                caveats = f" ⚠️ Caveats: {ev.caveats}" if ev.caveats else ""
                claims_section += (
                    f"- **{ev.evidence_id}** (similarity: {ev.similarity:.3f}): "
                    f"{ev.statement} — _Source: {ev.source_name}_{caveats}\n"
                )
            claims_section += "\n"

    context = f"""# Claim Assessment Task

You are assessing factual claims from an article about Iceland's EU membership
referendum against curated evidence from the Ground Truth Database.

## Instructions

For each claim below, provide an assessment:

1. **verdict**: One of:
   - `supported` — evidence confirms the claim
   - `partially_supported` — claim is broadly correct but misses nuances
   - `unsupported` — no evidence supports this claim
   - `misleading` — claim is technically true but omits critical context
   - `unverifiable` — insufficient evidence to assess

2. **explanation**: 2-3 sentences explaining the verdict. Reference specific
   evidence IDs.

3. **supporting_evidence**: List of evidence IDs that support the claim

4. **contradicting_evidence**: List of evidence IDs that contradict or
   complicate the claim

5. **missing_context**: Important context the claim omits (or null)

6. **confidence**: How confident you are in the assessment (0-1)

## Critical Principles

- **Independence**: Assess pro-EU and anti-EU claims with equal rigour
- **Evidence-based**: Every assessment must cite specific evidence IDs
- **Caveats matter**: Always surface the caveats from evidence entries
- **Humility**: If evidence is insufficient, say so — do not guess

## Output Format

Write a JSON array inside a code block. Each item includes the original
claim fields plus the assessment fields:

```json
[
  {{
    "claim": {{
      "claim_text": "...",
      "original_quote": "...",
      "category": "...",
      "claim_type": "...",
      "confidence": 0.9
    }},
    "verdict": "partially_supported",
    "explanation": "...",
    "supporting_evidence": ["FISH-DATA-001"],
    "contradicting_evidence": ["FISH-LEGAL-003"],
    "missing_context": "...",
    "confidence": 0.8
  }}
]
```

## Claims and Evidence

{claims_section}"""
    output_path = output_dir / "_context_assessment.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path


def prepare_omission_context(
    article_text: str,
    claims_with_evidence: list[ClaimWithEvidence],
    output_dir: Path,
) -> Path:
    """Write omission analysis context for the subagent.

    Returns path to the context file.
    """
    # Collect all unique evidence entries across claims
    all_evidence: dict[str, str] = {}
    for cwe in claims_with_evidence:
        for ev in cwe.evidence:
            if ev.evidence_id not in all_evidence:
                caveats = f" (Caveats: {ev.caveats})" if ev.caveats else ""
                all_evidence[ev.evidence_id] = f"{ev.statement}{caveats}"

    evidence_section = "\n".join(
        f"- **{eid}**: {stmt}" for eid, stmt in sorted(all_evidence.items())
    )

    # List categories covered by the article's claims
    covered_topics = {cwe.claim.category for cwe in claims_with_evidence}
    covered_str = ", ".join(sorted(covered_topics)) if covered_topics else "none identified"

    context = f"""# Omission Analysis Task

You are analysing what an article about Iceland's EU membership referendum
**leaves out**. The article's claims have been extracted and matched against
evidence. Your job is to identify significant omissions and assess framing.

## Instructions

1. Compare the article's coverage against the evidence retrieved from the
   Ground Truth Database
2. Identify **significant omissions** — important facts, context, or
   perspectives that the article does not mention
3. Assess the article's **framing**: does it present a balanced view, or
   does it lean towards one side?
4. Rate **overall completeness**: how much of the relevant evidence does
   the article address?

## Output Format

```json
{{
  "omissions": [
    {{
      "topic": "fisheries",
      "description": "Article claims Iceland would lose fishing rights but does not mention...",
      "relevant_evidence": ["FISH-DATA-003", "FISH-LEGAL-002"]
    }}
  ],
  "framing_assessment": "leans_anti_eu",
  "overall_completeness": 0.4
}}
```

- `framing_assessment`: one of `balanced`, `leans_pro_eu`, `leans_anti_eu`,
  `neutral_but_incomplete`
- `overall_completeness`: 0.0 (covers nothing) to 1.0 (comprehensive)

## Critical Principles

- **Balance**: An article can legitimately argue one side. Omission analysis
  is about what **relevant facts** are missing, not about requiring neutrality.
- **Significance**: Only flag omissions that would materially change a
  reader's understanding
- **Evidence-based**: Reference specific evidence IDs for each omission

## Article Topics Covered

{covered_str}

## Evidence Retrieved from Ground Truth Database

{evidence_section}

## Article Text

{article_text}
"""
    output_path = output_dir / "_context_omissions.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path


def prepare_translation_context(
    report_en: str,
    output_dir: Path,
) -> Path:
    """Write translation context for the Icelandic translation subagent.

    Returns path to the context file.
    """
    context = f"""# Translation Task: English → Icelandic

Translate the following analysis report into Icelandic.

## Guidelines

- Use formal but accessible Icelandic (not bureaucratic)
- Preserve all evidence IDs as-is (e.g. FISH-DATA-001)
- Preserve markdown formatting
- Use Icelandic terminology for EU/EEA concepts:
  - EU membership = ESB-aðild
  - EEA Agreement = EES-samningurinn
  - Common Fisheries Policy = sameiginleg sjávarútvegsstefna ESB
  - sovereignty = fullveldi
  - referendum = þjóðaratkvæðagreiðsla
  - claim = fullyrðing
  - evidence = heimild / gögn
  - supported = stutt af heimildum
  - unsupported = ekki stutt af heimildum
  - misleading = villandi
  - partially supported = stutt að hluta
  - omission = vanræksla / það sem vantar
- Translate verdict names in parentheses, keep original as well:
  e.g. "Stutt af heimildum (supported)"
- Do NOT translate source names or URLs

## Output

Write the full translated report in markdown. No JSON wrapping needed —
just the translated markdown text.

## English Report

{report_en}
"""
    output_path = output_dir / "_context_translation.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path
