"""Context preparation for Claude Code subagents.

Writes markdown context files to disk that subagents read for
claim extraction, assessment, omission analysis, and translation.
Each file embeds the full prompt instructions — the subagent just
reads the file and writes structured output.

Default language is Icelandic ("is"). English ("en") is available
as a fallback but the primary pipeline is Icelandic-first.
"""

from pathlib import Path

from .models import ClaimWithEvidence

# ── Shared terminology glossary (used in Icelandic contexts) ──────────

_TERMINOLOGY_IS = """
## Hugtaskilyrði / Terminology

- ESB-aðild = EU membership
- EES-samningurinn = EEA Agreement
- sameiginleg sjávarútvegsstefna ESB = Common Fisheries Policy (CFP)
- fullveldi = sovereignty
- þjóðaratkvæðagreiðsla = referendum
- fullyrðing = claim
- heimild / gögn = evidence / data
- stutt af heimildum = supported
- ekki stutt af heimildum = unsupported
- villandi = misleading
- stutt að hluta = partially supported
- ekki hægt að sannreyna = unverifiable
- vanræksla / það sem vantar = omission
- sjávarútvegur = fisheries
- viðskipti = trade
- landbúnaður = agriculture
- gjaldmiðill = currency
- vinnumarkaður = labour market
- húsnæðismál = housing
- fordæmi = precedents
"""


# ── Extraction context ────────────────────────────────────────────────


def prepare_extraction_context(
    article_text: str,
    output_dir: Path,
    metadata: dict | None = None,
    language: str = "is",
) -> Path:
    """Write extraction context for the claim-extraction subagent.

    Returns path to the context file.
    """
    meta_section = ""
    if metadata:
        lines = [f"- **{k}**: {v}" for k, v in metadata.items() if v]
        if lines:
            meta_section = "## Article Metadata\n\n" + "\n".join(lines) + "\n\n"

    if language == "is":
        context = f"""# Fullyrðingagreining — Útdráttur fullyrðinga

Þú ert að greina grein sem tengist þjóðaratkvæðagreiðslu Íslands um ESB-aðild
(29. ágúst 2026). Verkefni þitt er að draga út allar **staðreyndalegar fullyrðingar**
sem hægt er að bera saman við heimildir.

## Leiðbeiningar

1. Lestu greinina vandlega
2. Finndu allar staðreyndalegar fullyrðingar (tölfræði, lagalegar fullyrðingar,
   samanburði, spár). Slepptu hreinum skoðunum nema þær feli í sér óbeinar
   staðreyndalegar fullyrðingar.
3. Fyrir hverja fullyrðingu, skráðu:
   - `claim_text`: Fullyrðingin sett fram á skýru íslensku
   - `original_quote`: Nákvæm tilvitnun úr greininni
   - `category`: Eitt af: fisheries, trade, sovereignty, eea_eu_law, agriculture,
     precedents, currency, labour, polling, party_positions, org_positions, other
   - `claim_type`: Eitt af: statistic, legal_assertion, comparison, prediction, opinion
   - `confidence`: Hversu viss þú ert um að þetta sé staðreyndaleg fullyrðing (0-1)

## Mikilvægt

- Vertu ítarleg/ur — dragðu út ALLAR staðreyndalegar fullyrðingar, ekki bara augljósar
- Haltu tilvitnunum á upprunalegu tungumáli greinarinnar
- Flokkaðu rétt — flokkun ákvarðar hvaða heimildir eru sóttar
- Merktu skoðanir sem innihalda óbeinar fullyrðingar með `claim_type: "opinion"`
  og lægra `confidence`
- Skrifaðu `claim_text` á íslensku — þetta er íslenskt verkefni

{_TERMINOLOGY_IS}

## Úttakssnið / Output Format

Skrifaðu JSON-fylki innan kóðablokkar:

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

{meta_section}## Greinin / Article Text

{article_text}
"""
    else:
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


# ── Assessment context ────────────────────────────────────────────────


def prepare_assessment_context(
    claims_with_evidence: list[ClaimWithEvidence],
    output_dir: Path,
    language: str = "is",
) -> Path:
    """Write assessment context for the claim-assessment subagent.

    Returns path to the context file.
    """
    claims_section = ""
    for i, cwe in enumerate(claims_with_evidence, 1):
        claim = cwe.claim
        if language == "is":
            claims_section += f"""### Fullyrðing {i}

- **Fullyrðing**: {claim.claim_text}
- **Upprunaleg tilvitnun**: „{claim.original_quote}"
- **Flokkur**: {claim.category}
- **Tegund**: {claim.claim_type.value}

**Heimildir úr staðreyndagrunni:**

"""
        else:
            claims_section += f"""### Claim {i}

- **Claim**: {claim.claim_text}
- **Original quote**: "{claim.original_quote}"
- **Category**: {claim.category}
- **Type**: {claim.claim_type.value}

**Evidence from Ground Truth Database:**

"""
        if not cwe.evidence:
            no_evidence = (
                "_Engar viðeigandi heimildir fundust í gagnagrunni._\n\n"
                if language == "is"
                else "_No relevant evidence found in database._\n\n"
            )
            claims_section += no_evidence
        else:
            for ev in cwe.evidence:
                caveats = f" ⚠️ Caveats: {ev.caveats}" if ev.caveats else ""
                claims_section += (
                    f"- **{ev.evidence_id}** (similarity: {ev.similarity:.3f}): "
                    f"{ev.statement} — _Source: {ev.source_name}_{caveats}\n"
                )
            claims_section += "\n"

    if language == "is":
        context = f"""# Fullyrðingamat

Þú ert að meta staðreyndalegar fullyrðingar úr grein um þjóðaratkvæðagreiðslu
Íslands um ESB-aðild, bornar saman við heimildir úr staðreyndagrunni.

## Leiðbeiningar

Fyrir hverja fullyrðingu hér að neðan, gefðu mat:

1. **verdict**: Eitt af:
   - `supported` — heimildir staðfesta fullyrðinguna
   - `partially_supported` — fullyrðingin er í meginatriðum rétt en vantar blæbrigði
   - `unsupported` — engar heimildir styðja fullyrðinguna
   - `misleading` — tæknilega rétt en sleppur mikilvægu samhengi
   - `unverifiable` — ófullnægjandi heimildir til að meta

2. **explanation**: 2-3 setningar á **íslensku** sem útskýra matið. Vísaðu í
   tilteknar heimildir (evidence IDs).

3. **supporting_evidence**: Listi yfir evidence IDs sem styðja fullyrðinguna

4. **contradicting_evidence**: Listi yfir evidence IDs sem stangast á við eða
   flækja fullyrðinguna

5. **missing_context**: Mikilvægt samhengi sem fullyrðingin sleppur (á íslensku),
   eða null

6. **confidence**: Hversu viss þú ert um matið (0-1)

## Meginreglur

- **Óhlutdrægni**: Metið ESB-jákvæðar og ESB-neikvæðar fullyrðingar jafnt
- **Heimildum háð**: Sérhvert mat verður að vitna í tilteknar heimildir
- **Fyrirvarar skipta máli**: Komið alltaf á framfæri fyrirvörum úr heimildum
- **Auðmýkt**: Ef heimildir duga ekki, segið frá — ekki giska

## Úttakssnið / Output Format

Skrifaðu JSON-fylki innan kóðablokkar. Hvert atriði inniheldur upprunalegu
fullyrðinguna ásamt matinu:

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
    "explanation": "Íslensk útskýring hér...",
    "supporting_evidence": ["FISH-DATA-001"],
    "contradicting_evidence": ["FISH-LEGAL-003"],
    "missing_context": "Íslenskt samhengi hér...",
    "confidence": 0.8
  }}
]
```

{_TERMINOLOGY_IS}

## Fullyrðingar og heimildir

{claims_section}"""
    else:
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


# ── Omission context ─────────────────────────────────────────────────


def prepare_omission_context(
    article_text: str,
    claims_with_evidence: list[ClaimWithEvidence],
    output_dir: Path,
    language: str = "is",
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

    if language == "is":
        context = f"""# Greining á því sem vantar

Þú ert að greina hvað grein um þjóðaratkvæðagreiðslu Íslands um ESB-aðild
**sleppir**. Fullyrðingar greinarinnar hafa verið dregnar út og bornar saman
við heimildir. Verkefni þitt er að bera kennsl á mikilvægar eyður og meta
sjónarhorn greinarinnar.

## Leiðbeiningar

1. Berðu umfjöllun greinarinnar saman við heimildir úr staðreyndagrunni
2. Bera kennsl á **mikilvægar eyður** — mikilvægar staðreyndir, samhengi eða
   sjónarhorn sem greinin nefnir ekki
3. Metið **sjónarhorn** greinarinnar: er hún jafnvæg eða hallar á aðra hlið?
4. Gefið einkunn fyrir **heildstæðni**: hversu mikið af viðeigandi heimildum
   fjallar greinin um?

## Úttakssnið / Output Format

Skrifaðu á íslensku. Lýsingarnar (description) skulu vera á íslensku.

```json
{{
  "omissions": [
    {{
      "topic": "fisheries",
      "description": "Greinin fullyrðir að Ísland myndi missa veiðiréttindi en nefnir ekki...",
      "relevant_evidence": ["FISH-DATA-003", "FISH-LEGAL-002"]
    }}
  ],
  "framing_assessment": "leans_anti_eu",
  "overall_completeness": 0.4
}}
```

- `framing_assessment`: eitt af `balanced`, `leans_pro_eu`, `leans_anti_eu`,
  `strongly_pro_eu`, `strongly_anti_eu`, `neutral_but_incomplete`
- `overall_completeness`: 0.0 (fjallar um ekkert) til 1.0 (heildstæð umfjöllun)

## Meginreglur

- **Jafnvægi**: Grein má rökræða aðra hliðina. Eyðugreining snýst um hvaða
  **viðeigandi staðreyndir** vantar, ekki um að krefjast hlutleysis.
- **Mikilvægi**: Merktu aðeins eyður sem myndu verulega breyta skilningi lesanda
- **Heimildum háð**: Vísaðu í tilteknar heimildir fyrir hverja eyðu

{_TERMINOLOGY_IS}

## Efnisflokkar í greininni

{covered_str}

## Heimildir úr staðreyndagrunni

{evidence_section}

## Greinin / Article Text

{article_text}
"""
    else:
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
  `strongly_pro_eu`, `strongly_anti_eu`, `neutral_but_incomplete`
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


# ── Translation context (now optional — for English derivative) ───────


def prepare_translation_context(
    report_text: str,
    output_dir: Path,
    direction: str = "is_to_en",
) -> Path:
    """Write translation context for optional translation subagent.

    Default direction is Icelandic→English (since pipeline is now
    Icelandic-first). Set direction="en_to_is" for legacy behaviour.

    Returns path to the context file.
    """
    if direction == "is_to_en":
        context = f"""# Translation Task: Icelandic → English

Translate the following analysis report from Icelandic to English.

## Guidelines

- Use clear, professional English
- Preserve all evidence IDs as-is (e.g. FISH-DATA-001)
- Preserve markdown formatting
- Do NOT translate source names or URLs
- Keep verdict enum values in English (supported, partially_supported, etc.)

## Output

Write the full translated report in markdown. No JSON wrapping needed —
just the translated markdown text.

## Icelandic Report

{report_text}
"""
    else:
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

{report_text}
"""
    output_path = output_dir / "_context_translation.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path
