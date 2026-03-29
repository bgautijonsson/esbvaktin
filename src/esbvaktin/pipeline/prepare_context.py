"""Context preparation for Claude Code subagents.

Writes markdown context files to disk that subagents read for
claim extraction, assessment, omission analysis, and translation.
Each file embeds the full prompt instructions — the subagent just
reads the file and writes structured output.

Default language is Icelandic ("is"). English ("en") is available
as a fallback but the primary pipeline is Icelandic-first.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .models import Claim, ClaimWithEvidence

if TYPE_CHECKING:
    from esbvaktin.claim_bank.models import ClaimBankMatch

# ── Icelandic quality blocks ────────────────────────────────────────

_BLOCKS_PATH = (
    Path(__file__).resolve().parents[3]
    / ".claude"
    / "skills"
    / "icelandic-shared"
    / "assessment-blocks.md"
)


def _load_icelandic_blocks() -> str:
    """Load the shared Icelandic assessment prompt blocks.

    Returns the full content, or an empty string if the file is missing.
    """
    if _BLOCKS_PATH.exists():
        return _BLOCKS_PATH.read_text(encoding="utf-8")
    return ""


def _load_icelandic_blocks_subset(*block_names: str) -> str:
    """Load specific blocks (by header) from the assessment blocks file.

    block_names: e.g. "Block D", "Block F", "Block H"
    """
    full = _load_icelandic_blocks()
    if not full:
        return ""
    sections: list[str] = []
    current: list[str] = []
    current_match = False
    for line in full.split("\n"):
        if line.startswith("## Block "):
            if current_match and current:
                sections.append("\n".join(current))
            current = [line]
            current_match = any(bn in line for bn in block_names)
        else:
            current.append(line)
    if current_match and current:
        sections.append("\n".join(current))
    return "\n\n".join(sections)


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
   - `claim_type`: Eitt af: statistic, legal_assertion, comparison, forecast, opinion
   - `epistemic_type`: Eitt af: factual, hearsay, counterfactual, prediction
     - `factual`: Bein fullyrðing um heiminn (sjálfgefið)
     - `hearsay`: Byggt á ónafngreindum/óstaðfestanlegum heimildum («að sögn», «fregnir herma»)
     - `counterfactual`: Um fortíðina — andstætt því sem gerðist («ef X hefði gerst...»)
     - `prediction`: Um framtíðina, þ.m.t. skilyrtar spár («ef aðild næðist myndi...»)
     Athugið: Nafngreind heimild á opinberum vettvangi er `factual`, ekki hearsay.
   - `confidence`: Hversu viss þú ert um að þetta sé staðreyndaleg fullyrðing (0-1)

## Mikilvægt

- Vertu ítarleg/ur — dragðu út ALLAR staðreyndalegar fullyrðingar, ekki bara augljósar
- Haltu tilvitnunum á upprunalegu tungumáli greinarinnar
- Flokkaðu rétt — flokkun ákvarðar hvaða heimildir eru sóttar
- Merktu skoðanir sem innihalda óbeinar fullyrðingar með `claim_type: "opinion"`
  og lægra `confidence`
- Skrifaðu `claim_text` á íslensku — þetta er íslenskt verkefni

## Slepptu eftirfarandi — þetta eru EKKI fullyrðingar

- **Æviágrip og titlar**: „X er ráðherra/þingmaður/fréttamaður/sérfræðingur" —
  starfsheitin eru bakgrunnsupplýsingar, ekki fullyrðingar um ESB-málið
- **Aðferðafræði kannana**: Dagsetningar, úrtaksstærðir, þátttökuhlutföll og
  aðrar tæknilegar upplýsingar um kannanir — slepptu nema talan sjálf sé umdeild
- **Efni sem tengist ekki ESB**: Hjúkrunarrými, raforkuúnútur, Grænlandsmál og
  annað sem snertir ekki beint ESB-aðild, viðræður eða þjóðaratkvæðagreiðsluna
- **Heimildatilvísanir**: „Altinget.no birti grein", „RÚV greindi frá" —
  fréttatilvísanir eru ekki fullyrðingar
- **Almenn þekking**: „Vigdís var forseti 1980–1996" eða önnur staðreynd sem
  enginn deilir um og tengist ekki ESB-efninu beint

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
    "epistemic_type": "...",
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
   - `claim_type`: One of: statistic, legal_assertion, comparison, forecast, opinion
   - `epistemic_type`: One of: factual, hearsay, counterfactual, prediction
     - `factual`: Direct assertion about the world (default)
     - `hearsay`: Based on unnamed/unverifiable sources
     - `counterfactual`: About the past — contrary to what happened
     - `prediction`: About the future, including conditional scenarios
     Note: A named, on-the-record source is `factual`, not hearsay.
   - `confidence`: How confident you are this is a factual claim (0-1)

## Important

- Be thorough — extract ALL factual claims, not just obvious ones
- Preserve the original language of quotes
- Categorise accurately — this determines which evidence is retrieved
- Mark opinions that contain implicit factual claims as claims with
  `claim_type: "opinion"` and lower confidence

## Do NOT extract the following — these are NOT claims

- **Biographical/title statements**: "X is a minister/MP/journalist/expert" —
  job titles are background info, not claims about the EU question
- **Poll methodology**: Dates, sample sizes, response rates, and other
  technical survey details — skip unless the figure itself is contested
- **Non-EU content**: Nursing homes, energy grid, Greenland affairs, and
  anything not directly about EU membership, negotiations, or the referendum
- **Source attributions**: "Altinget.no published an article", "RÚV reported" —
  news references are not claims
- **Common knowledge**: "Vigdís was president 1980–1996" or other undisputed
  facts that do not directly relate to the EU question

## Output Format

Write a JSON array inside a code block:

```json
[
  {{
    "claim_text": "...",
    "original_quote": "...",
    "category": "...",
    "claim_type": "...",
    "epistemic_type": "...",
    "confidence": 0.9
  }}
]
```

{meta_section}## Article Text

{article_text}
"""
    # Append subset of Icelandic blocks for extraction (Unicode + terms + self-review)
    if language == "is":
        blocks = _load_icelandic_blocks_subset("Block D", "Block F", "Block H")
        if blocks:
            context += f"\n\n{blocks}\n"

    output_path = output_dir / "_context_extraction.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path


# ── Assessment context ────────────────────────────────────────────────


def prepare_assessment_context(
    claims_with_evidence: list[ClaimWithEvidence],
    output_dir: Path,
    language: str = "is",
    speech_context: str | None = None,
    bank_matches: dict[int, ClaimBankMatch] | None = None,
) -> Path:
    """Write assessment context for the claim-assessment subagent.

    Args:
        speech_context: Optional formatted markdown with parliamentary speech
            excerpts for MPs mentioned in the article. Built by
            ``esbvaktin.speeches.context.build_speech_context()``.
        bank_matches: Optional dict mapping 0-based claim index to a
            ClaimBankMatch. When present, a prior verdict block is rendered
            before each claim's evidence section.

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
- **Þekkingarstaða**: {claim.epistemic_type.value}

"""
            # Bank match prior verdict (Icelandic)
            if bank_matches and (i - 1) in bank_matches:
                match = bank_matches[i - 1]
                freshness = "ferskt" if match.is_fresh else "úrelt"
                claims_section += (
                    f"**Fyrra mat úr fullyrðingabanka**"
                    f" (líkindi: {match.similarity:.3f},"
                    f" slug: `{match.claim_slug}`, {freshness}):\n"
                )
                claims_section += (
                    f"- Niðurstaða: `{match.verdict}` (öryggi: {match.confidence:.2f})\n"
                )
                claims_section += f"- Skýring: {match.explanation_is}\n"
                if match.missing_context_is:
                    claims_section += f"- Samhengi sem vantar: {match.missing_context_is}\n"
                claims_section += (
                    "> Þú getur fallist á þetta mat eða vikið frá því —"
                    " ef þú víkur frá, skýrðu hvers vegna.\n\n"
                )

            claims_section += "**Heimildir úr staðreyndagrunni:**\n\n"
        else:
            claims_section += f"""### Claim {i}

- **Claim**: {claim.claim_text}
- **Original quote**: "{claim.original_quote}"
- **Category**: {claim.category}
- **Type**: {claim.claim_type.value}
- **Epistemic type**: {claim.epistemic_type.value}

"""
            # Bank match prior verdict (English)
            if bank_matches and (i - 1) in bank_matches:
                match = bank_matches[i - 1]
                freshness = "fresh" if match.is_fresh else "stale"
                claims_section += (
                    f"**Prior verdict from claim bank**"
                    f" (similarity: {match.similarity:.3f},"
                    f" slug: `{match.claim_slug}`, {freshness}):\n"
                )
                claims_section += (
                    f"- Verdict: `{match.verdict}` (confidence: {match.confidence:.2f})\n"
                )
                claims_section += f"- Explanation: {match.explanation_is}\n"
                if match.missing_context_is:
                    claims_section += f"- Missing context: {match.missing_context_is}\n"
                claims_section += (
                    "> You may agree with or diverge from this prior verdict"
                    " — if you diverge, explain why.\n\n"
                )

            claims_section += "**Evidence from Ground Truth Database:**\n\n"
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
                date_str = f", {ev.source_date}" if ev.source_date else ""
                claims_section += (
                    f"- **{ev.evidence_id}** (similarity: {ev.similarity:.3f}): "
                    f"{ev.statement} — _Source: {ev.source_name}{date_str}_{caveats}\n"
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

## Reglur um þekkingarfræðilega tegund (epistemic_type)

- **factual**: Metið eins og hingað til — er fullyrðingin studd af heimildum?
- **counterfactual**: Þetta gerðist ekki. Metið rökin og heimildastuðning
  fyrir orsökum og afleiðingum. Hámarks confidence: 0.8.
- **prediction**: Þetta hefur ekki gerst enn. Metið á grundvelli:
  1. **Heimildasamstaða**: Eru margar trúverðugar heimildir sammála?
  2. **Trúverðugleiki heimilda**: Opinberar stofnanir, sérfræðingar, eða ónafngreindir?
  3. **Fordæmi**: Reynsla annarra ríkja (Noregur, Svíþjóð, Króatía)?
  4. **Rökfærsla**: Er orsök-afleiðing keðjan trúverðug?
  Hámarks confidence: 0.8.
- **hearsay**: Kemur ALDREI til mats — hefur þegar fengið unverifiable.

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
      "epistemic_type": "...",
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

## Epistemic Type Rules

- **factual**: Assess as usual — is the claim supported by evidence?
- **counterfactual**: This did not happen. Assess the reasoning and evidence
  for causes and consequences. Maximum confidence: 0.8.
- **prediction**: This has not happened yet. Assess based on:
  1. **Evidence consensus**: Do multiple credible sources agree?
  2. **Source credibility**: Official institutions, experts, or unnamed?
  3. **Precedents**: Experience of other countries (Norway, Sweden, Croatia)?
  4. **Reasoning**: Is the causal chain plausible?
  Maximum confidence: 0.8.
- **hearsay**: NEVER assessed — has already received unverifiable.

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
      "epistemic_type": "...",
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
    # Append parliamentary speech context if available
    if speech_context:
        context += f"\n\n{speech_context}\n"

    # Append full Icelandic quality blocks for assessment
    if language == "is":
        blocks = _load_icelandic_blocks()
        if blocks:
            context += f"\n\n{blocks}\n"

    output_path = output_dir / "_context_assessment.md"
    output_path.write_text(context, encoding="utf-8")

    import logging

    _logger = logging.getLogger(__name__)
    _logger.info("Assessment context: %.0f KB", output_path.stat().st_size / 1024)

    return output_path


# ── Omission context ─────────────────────────────────────────────────


def prepare_omission_context(
    article_text: str,
    claims_with_evidence: list[ClaimWithEvidence],
    output_dir: Path,
    language: str = "is",
) -> Path:
    """Write omission analysis context for the subagent.

    For large analyses (panel shows with 40-70+ claims), uses compact
    Icelandic summaries (statement_is) instead of full English statements
    to keep the context within agent limits.

    Returns path to the context file.
    """
    # Collect all unique evidence entries across claims
    all_evidence: dict[str, tuple[str, str | None, str | None]] = {}
    for cwe in claims_with_evidence:
        for ev in cwe.evidence:
            if ev.evidence_id not in all_evidence:
                all_evidence[ev.evidence_id] = (ev.statement, ev.statement_is, ev.caveats)

    # Decide whether to use compact mode: threshold on total evidence text
    evidence_size_threshold = 50_000  # 50KB
    full_evidence_text = "".join(stmt for stmt, _, _ in all_evidence.values())
    compact = len(full_evidence_text.encode("utf-8")) > evidence_size_threshold

    evidence_lines: list[str] = []
    for eid, (statement, statement_is, caveats) in sorted(all_evidence.items()):
        caveat_str = f" ⚠️ {caveats}" if caveats else ""
        if compact and statement_is:
            evidence_lines.append(f"- **{eid}**: {statement_is}{caveat_str}")
        elif compact:
            # Fallback: truncate English statement
            truncated = statement[:200] + "…" if len(statement) > 200 else statement
            evidence_lines.append(f"- **{eid}**: {truncated}{caveat_str}")
        else:
            full = f"{statement} (Caveats: {caveats})" if caveats else statement
            evidence_lines.append(f"- **{eid}**: {full}")
    evidence_section = "\n".join(evidence_lines)

    # Truncate article text for very large transcripts
    article_size_threshold = 30_000  # 30KB
    if len(article_text.encode("utf-8")) > article_size_threshold:
        article_text = (
            article_text[:5000] + "\n\n[…klippt — langur texti stytt…]\n\n" + article_text[-2000:]
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
    # Append Icelandic quality blocks — subset for compact mode
    if language == "is":
        if compact:
            blocks = _load_icelandic_blocks_subset("Block D", "Block H")
        else:
            blocks = _load_icelandic_blocks()
        if blocks:
            context += f"\n\n{blocks}\n"

    output_path = output_dir / "_context_omissions.md"
    output_path.write_text(context, encoding="utf-8")

    # Log context size and warn if still large
    size_kb = output_path.stat().st_size / 1024
    import logging

    _logger = logging.getLogger(__name__)
    _logger.info("Omission context: %.0f KB%s", size_kb, " (compact)" if compact else "")
    if size_kb > 150:
        _logger.warning("Omission context is %.0f KB — may exceed agent limits", size_kb)

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


# ── Entity extraction context ─────────────────────────────────────────


def prepare_entity_context(
    article_text: str,
    claims: list[Claim],
    output_dir: Path,
    metadata: dict | None = None,
) -> Path:
    """Write entity extraction context for the subagent.

    The subagent identifies who is quoted, who wrote the article,
    and which claims are attributed to each speaker.

    Returns path to the context file.
    """
    meta_section = ""
    if metadata:
        lines = [f"- **{k}**: {v}" for k, v in metadata.items() if v]
        if lines:
            meta_section = "## Lýsigögn greinar / Article Metadata\n\n" + "\n".join(lines) + "\n\n"

    # Build claims list for the subagent
    claims_section = ""
    for i, claim in enumerate(claims):
        quote = claim.original_quote
        claims_section += f"**Fullyrðing {i}**: {claim.claim_text}\n"
        claims_section += f"  Tilvitnun: {quote}\n\n"

    context = f"""# Aðilagreining — Entity/Speaker Extraction

You are extracting **entities** (people, parties, organisations) from an article
about Iceland's EU membership referendum. For each entity, identify their role,
affiliation, EU stance, and which claims they made — **and how**.

## Instructions

1. Read the article carefully
2. Identify the **article author** — the person who wrote the article
3. Identify all **speakers** — people, parties, unions, or institutions that are
   quoted, paraphrased, or whose positions are described
4. For each speaker, determine:
   - `name`: Full name in Icelandic (use the form that appears in the article)
   - `type`: One of `individual`, `party`, `institution`, `union`
   - `role`: Their role/title (e.g. "þingmaður", "framkvæmdastjóri", "sérfræðingur")
   - `party`: Political party affiliation (for individuals, if known from the article)
   - `stance`: Their EU membership stance: `pro_eu`, `anti_eu`, `mixed`, or `neutral`
   - `attributions`: Array linking the speaker to specific claims **with attribution type**

## Attribution Types

Each claim-speaker link must have one of these types:

| Type | Meaning | Example |
|------|---------|---------|
| `asserted` | Speaker directly states the claim as their own position | An opinion author writing "ESB-aðild myndi..." |
| `quoted` | Speaker is directly quoted (quotation marks in article) | „Við munum aldrei samþykkja þetta," sagði X |
| `paraphrased` | Article restates the speaker's position without a direct quote | Samkvæmt X þá sé þetta... |
| `mentioned` | Speaker is referenced in context of the claim but didn't make it | Fullyrðingin vísar til stefnu X |

### Attribution Guidelines

- **Journalists / fréttaritarar**: Usually get `asserted` only for editorial framing claims.
  Claims they *report* others making should be attributed to the original speaker, not the journalist.
- **Opinion authors / pistlahöfundar**: Get `asserted` for claims they present as their own view.
- **Direct quotes**: Always use `quoted` when the article uses quotation marks.
- **Paraphrased positions**: Use `paraphrased` when the article describes someone's view
  without a direct quote (e.g. "samkvæmt X", "að mati Y", "X telur að").
- **Mentioned in context**: Use `mentioned` when a speaker/org is referenced as context
  but isn't the one making the claim (e.g. "ESB hefur sett reglur um..." — the EU is
  mentioned but isn't actively making a claim in the article).
- A single claim can have multiple speakers with different attribution types.
- Only include entities that are relevant to the EU debate.

## Important

- **JSON safety**: Escape Icelandic quotation marks „…" as `\\"…\\"` in JSON strings

## Output Format

Write raw JSON (no markdown code block wrapping):

{{
  "article_author": {{
    "name": "...",
    "type": "individual",
    "role": "...",
    "party": "..." or null,
    "stance": "neutral",
    "attributions": [
      {{"claim_index": 0, "attribution": "asserted"}},
      {{"claim_index": 5, "attribution": "asserted"}}
    ]
  }},
  "speakers": [
    {{
      "name": "...",
      "type": "individual",
      "role": "...",
      "party": "..." or null,
      "stance": "pro_eu",
      "attributions": [
        {{"claim_index": 2, "attribution": "quoted"}},
        {{"claim_index": 4, "attribution": "paraphrased"}}
      ]
    }},
    {{
      "name": "...",
      "type": "institution",
      "role": "...",
      "party": null,
      "stance": "neutral",
      "attributions": [
        {{"claim_index": 3, "attribution": "mentioned"}}
      ]
    }}
  ]
}}

{meta_section}## Fullyrðingar / Claims (0-indexed)

{claims_section}## Greinin / Article Text

{article_text}
"""
    output_path = output_dir / "_context_entities.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path


# ── Speech extraction context ───────────────────────────────────────


def prepare_speech_extraction_context(
    speech_text: str,
    speaker_metadata: dict,
    output_dir: Path,
    language: str = "is",
) -> Path:
    """Write extraction context for claims from an Alþingi speech.

    Like the article extraction context but with speech-specific
    guardrails (filtering parliamentary rhetoric) and speaker metadata.

    Args:
        speech_text: Full speech text from althingi.db.
        speaker_metadata: Dict with name, party, speech_type, issue_title,
            date, session.
        output_dir: Work directory for this speech check.
        language: Output language (default "is").

    Returns path to the context file.
    """
    meta_block = f"""## Bakgrunnur ræðumanns

- Ræðumaður: {speaker_metadata.get("name", "?")}, {speaker_metadata.get("party", "?")}
- Tegund ræðu: {speaker_metadata.get("speech_type", "?")}
- Þingfundarheiti: {speaker_metadata.get("issue_title", "?")}
- Dagsetning: {speaker_metadata.get("date", "?")}, {speaker_metadata.get("session", "?")}. löggjafarþing
"""

    if language == "is":
        context = f"""# Fullyrðingagreining — Útdráttur úr þingræðu

Þú ert að greina ræðu frá Alþingi sem tengist þjóðaratkvæðagreiðslu Íslands um
ESB-aðild (29. ágúst 2026). Verkefni þitt er að draga út allar **staðreyndalegar
fullyrðingar** sem hægt er að bera saman við heimildir.

{meta_block}

## Leiðbeiningar

1. Lestu ræðuna vandlega
2. Finndu allar staðreyndalegar fullyrðingar (tölfræði, lagalegar fullyrðingar,
   samanburði, spár). Slepptu hreinum skoðunum nema þær feli í sér óbeinar
   staðreyndalegar fullyrðingar.
3. Fyrir hverja fullyrðingu, skráðu:
   - `claim_text`: Fullyrðingin sett fram á skýru íslensku
   - `original_quote`: Nákvæm tilvitnun úr ræðunni
   - `category`: Eitt af: fisheries, trade, sovereignty, eea_eu_law, agriculture,
     precedents, currency, labour, polling, party_positions, org_positions, other
   - `claim_type`: Eitt af: statistic, legal_assertion, comparison, forecast, opinion
   - `epistemic_type`: Eitt af: factual, hearsay, counterfactual, prediction
     - `factual`: Bein fullyrðing um heiminn (sjálfgefið)
     - `hearsay`: Byggt á ónafngreindum/óstaðfestanlegum heimildum («að sögn», «fregnir herma»)
     - `counterfactual`: Um fortíðina — andstætt því sem gerðist («ef X hefði gerst...»)
     - `prediction`: Um framtíðina, þ.m.t. skilyrtar spár («ef aðild næðist myndi...»)
     Athugið: Nafngreind heimild á opinberum vettvangi er `factual`, ekki hearsay.
   - `confidence`: Hversu viss þú ert um að þetta sé staðreyndaleg fullyrðing (0-1)

## Mikilvægt

- Vertu ítarleg/ur — dragðu út ALLAR staðreyndalegar fullyrðingar, ekki bara augljósar
- Haltu tilvitnunum á upprunalegu tungumáli ræðunnar
- Flokkaðu rétt — flokkun ákvarðar hvaða heimildir eru sóttar
- Merktu **afstöðulýsingar flokks** (t.d. "við í flokknum munum aldrei...")
  sem `claim_type: "opinion"` með `confidence` ≤ 0.6
- Skrifaðu `claim_text` á íslensku — þetta er íslenskt verkefni

## Slepptu eftirfarandi — þetta eru EKKI fullyrðingar

### Almenn útilokun (sama og greinagerð)

- **Æviágrip og titlar**: „X er ráðherra/þingmaður" — bakgrunnsupplýsingar
- **Efni sem tengist ekki ESB**: Hjúkrunarrými, raforkuúnútur og annað sem
  snertir ekki beint ESB-aðild, viðræður eða þjóðaratkvæðagreiðsluna
- **Almenn þekking**: Óumdeildar staðreyndir sem tengist ekki ESB-efninu beint

### Slepptu þingræðumálefnum — sérstakt fyrir ræður

- **Viljayfirlýsingar**: „Við munum...", „Við höfnum þessu", „Við krefjumst..." —
  pólitísk fyrirheit eru ekki fullyrðingar um staðreyndir
- **Þingskápur**: Tillögur, þingsályktanir, dagskráratriði, „ég legg til..." —
  málsmeðferð er ekki fullyrðing
- **Fyrirspurnir í eftirlitshlutverki**: Spurningar sem ráðherra er beint —
  spurningin sjálf er ekki fullyrðing
- **Dæmisögur og myndlíkingar**: Sögur og samlíkingar án tölugagna — ef engin
  staðreynd er í dæmisögunni, slepptu henni
- **Tilvísanir í aðra ræðumenn**: „Eins og þingmaðurinn X sagði..." —
  lýsing á afstöðu annarra er ekki fullyrðing frá þessum ræðumanni

{_TERMINOLOGY_IS}

## Úttakssnið / Output Format

Skrifaðu JSON-fylki innan kóðablokkar:

```json
[
  {{{{
    "claim_text": "...",
    "original_quote": "...",
    "category": "...",
    "claim_type": "...",
    "epistemic_type": "...",
    "confidence": 0.9
  }}}}
]
```

## Ræðan / Speech Text

{speech_text}
"""
    else:
        context = f"""# Claim Extraction — Parliamentary Speech

You are analysing an Alþingi speech related to Iceland's EU membership referendum
(29 August 2026). Extract all **factual claims** that can be checked against evidence.

{meta_block}

## Instructions

1. Read the speech carefully
2. Identify every factual claim (statistics, legal assertions, comparisons,
   predictions). Skip pure opinions unless they contain implicit factual claims.
3. For each claim, provide:
   - `claim_text`: The factual claim restated clearly
   - `original_quote`: The exact quote from the speech
   - `category`: One of: fisheries, trade, sovereignty, eea_eu_law, agriculture,
     precedents, currency, labour, polling, party_positions, org_positions, other
   - `claim_type`: One of: statistic, legal_assertion, comparison, forecast, opinion
   - `epistemic_type`: One of: factual, hearsay, counterfactual, prediction
     - `factual`: Direct assertion about the world (default)
     - `hearsay`: Based on unnamed/unverifiable sources
     - `counterfactual`: About the past — contrary to what happened
     - `prediction`: About the future, including conditional scenarios
     Note: A named, on-the-record source is `factual`, not hearsay.
   - `confidence`: How confident you are this is a factual claim (0-1)

## Important

- Be thorough — extract ALL factual claims
- Mark **party-position declarations** (e.g. "we will never accept...")
  as `claim_type: "opinion"` with `confidence` ≤ 0.6
- Preserve the original language of quotes

## Do NOT extract the following

### General exclusions (same as article analysis)

- **Biographical/title statements**: job titles are background info
- **Non-EU content**: anything not about EU membership, negotiations, or referendum
- **Common knowledge**: undisputed facts unrelated to the EU question

### Skip parliamentary rhetoric — specific to speeches

- **Intent expressions**: "við munum...", "við höfnum þessu", "við krefjumst..." —
  political pledges are not factual claims
- **Procedural language**: tillögur, þingsályktanir, dagskráratriði, "ég legg til..." —
  procedure is not a claim
- **Ministerial questions**: questions directed at a minister — the question itself
  is not a claim
- **Anecdotes without data**: stories and metaphors without numerical data
- **References to other speakers**: "eins og þingmaðurinn X sagði..." —
  descriptions of others' positions are not claims by this speaker

## Output Format

Write a JSON array inside a code block:

```json
[
  {{{{
    "claim_text": "...",
    "original_quote": "...",
    "category": "...",
    "claim_type": "...",
    "epistemic_type": "...",
    "confidence": 0.9
  }}}}
]
```

## Speech Text

{speech_text}
"""

    # Append Icelandic quality blocks for extraction
    if language == "is":
        blocks = _load_icelandic_blocks_subset("Block D", "Block F", "Block H")
        if blocks:
            context += f"\n\n{blocks}\n"

    output_path = output_dir / "_context_extraction.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path


# ── Panel show extraction context ─────────────────────────────────


def prepare_panel_extraction_context(
    transcript: ParsedTranscript,  # noqa: F821
    output_dir: Path,
    language: str = "is",
) -> Path:
    """Write extraction context for claims from a panel show transcript.

    Like article/speech extraction but with multi-speaker awareness:
    - Transcript formatted with speaker labels so the subagent sees who said what
    - Output includes ``speaker_name`` per claim for natural attribution
    - Debate-specific guardrails filter moderator procedural text and rhetoric

    Args:
        transcript: Parsed panel show transcript (from ``transcript.py``).
        output_dir: Work directory for this analysis.
        language: Output language (default "is").

    Returns path to the context file.
    """
    # Format participant list
    participants_block = "## Þátttakendur\n\n"
    for p in transcript.participants:
        role = p["role"] or "—"
        participants_block += f"- **{p['name']}** — {role}\n"

    # Format the debate as speaker-labelled segments (moderator excluded)
    debate_block = "## Umræðan / Debate Text\n\n"
    for turn in transcript.turns:
        if turn.is_moderator:
            continue
        role_hint = f" ({turn.speaker_role})" if turn.speaker_role else ""
        debate_block += f"### {turn.speaker_name}{role_hint}\n\n{turn.text}\n\n"

    meta_block = f"""## Lýsigögn þáttar

- **Þáttur**: {transcript.title}
- **Þáttaröð**: {transcript.show_name}
- **Dagsetning**: {transcript.date or "?"}
- **Útvarpsstöð**: {transcript.broadcaster or "?"}
- **Orðafjöldi**: {transcript.word_count}
- **Heimild**: {transcript.url or "?"}
"""

    if language == "is":
        context = f"""# Fullyrðingagreining — Útdráttur úr umræðuþætti

Þú ert að greina umræðuþátt þar sem fulltrúar stjórnmálaflokka ræða
þjóðaratkvæðagreiðslu Íslands um ESB-aðild (29. ágúst 2026). Verkefni þitt
er að draga út allar **staðreyndalegar fullyrðingar** sem hægt er að bera
saman við heimildir.

{meta_block}

{participants_block}

## Leiðbeiningar

1. Lestu umræðuna vandlega — athugaðu hver segir hvað
2. Finndu allar staðreyndalegar fullyrðingar (tölfræði, lagalegar fullyrðingar,
   samanburði, spár). Slepptu hreinum skoðunum nema þær feli í sér óbeinar
   staðreyndalegar fullyrðingar.
3. Fyrir hverja fullyrðingu, skráðu:
   - `claim_text`: Fullyrðingin sett fram á skýru íslensku
   - `original_quote`: Nákvæm tilvitnun úr umræðunni
   - `speaker_name`: **Nafn þess sem sagði þetta** — nákvæmt fullt nafn
   - `category`: Eitt af: fisheries, trade, sovereignty, eea_eu_law, agriculture,
     precedents, currency, labour, polling, party_positions, org_positions, other
   - `claim_type`: Eitt af: statistic, legal_assertion, comparison, forecast, opinion
   - `epistemic_type`: Eitt af: factual, hearsay, counterfactual, prediction
     - `factual`: Bein fullyrðing um heiminn (sjálfgefið)
     - `hearsay`: Byggt á ónafngreindum/óstaðfestanlegum heimildum («að sögn», «fregnir herma»)
     - `counterfactual`: Um fortíðina — andstætt því sem gerðist («ef X hefði gerst...»)
     - `prediction`: Um framtíðina, þ.m.t. skilyrtar spár («ef aðild næðist myndi...»)
     Athugið: Nafngreind heimild á opinberum vettvangi er `factual`, ekki hearsay.
   - `confidence`: Hversu viss þú ert um að þetta sé staðreyndaleg fullyrðing (0-1)

## Mikilvægt

- Vertu ítarleg/ur — dragðu út ALLAR staðreyndalegar fullyrðingar, ekki bara augljósar
- **`speaker_name` er nauðsynlegt** — tilgreindu alltaf hver sagði fullyrðinguna
- Haltu tilvitnunum á upprunalegu tungumáli umræðunnar
- Flokkaðu rétt — flokkun ákvarðar hvaða heimildir eru sóttar
- Merktu skoðanir sem innihalda óbeinar fullyrðingar með `claim_type: "opinion"`
  og lægra `confidence`
- Skrifaðu `claim_text` á íslensku — þetta er íslenskt verkefni

## Slepptu eftirfarandi — þetta eru EKKI fullyrðingar

### Almenn útilokun

- **Æviágrip og titlar**: „X er ráðherra/þingmaður" — bakgrunnsupplýsingar
- **Efni sem tengist ekki ESB**: Allt sem snertir ekki beint ESB-aðild,
  viðræður eða þjóðaratkvæðagreiðsluna
- **Almenn þekking**: Óumdeildar staðreyndir sem tengist ekki ESB-efninu beint

### Slepptu umræðustílbragðum — sérstakt fyrir umræðuþætti

- **Spurningar umsjónarmanns**: Spurningar og inngangssetningar frá umsjónarmanni —
  spurningin sjálf er ekki fullyrðing
- **Samþykki/ósamþykki án efnis**: „Ég er sammála/ósammála" án staðreyndalegrar
  fullyrðingar
- **Viljayfirlýsingar**: „Við munum...", „Við höfnum þessu" — pólitísk fyrirheit
  eru ekki fullyrðingar um staðreyndir
- **Tilvísanir í orð annarra**: „Eins og [nafn] sagði áðan..." — slepptu nema nýtt
  staðreyndalegt efni bætist við
- **Herferðarklisjur og málsháttir**: Slagorð og ómerk orðalag án efnis

{_TERMINOLOGY_IS}

## Úttakssnið / Output Format

Skrifaðu JSON-fylki innan kóðablokkar. **Athugið: `speaker_name` er skyldureitur.**

```json
[
  {{{{
    "claim_text": "...",
    "original_quote": "...",
    "speaker_name": "Fullt nafn ræðumanns",
    "category": "...",
    "claim_type": "...",
    "epistemic_type": "...",
    "confidence": 0.9
  }}}}
]
```

{debate_block}"""
    else:
        context = f"""# Claim Extraction — Panel Show Debate

You are analysing a panel show debate where political party representatives discuss
Iceland's EU membership referendum (29 August 2026). Extract all **factual claims**
that can be checked against evidence.

{meta_block}

{participants_block}

## Instructions

1. Read the debate carefully — note who says what
2. Identify every factual claim (statistics, legal assertions, comparisons,
   predictions). Skip pure opinions unless they contain implicit factual claims.
3. For each claim, provide:
   - `claim_text`: The factual claim restated clearly
   - `original_quote`: The exact quote from the debate
   - `speaker_name`: **Name of the person who made this claim** — exact full name
   - `category`: One of: fisheries, trade, sovereignty, eea_eu_law, agriculture,
     precedents, currency, labour, polling, party_positions, org_positions, other
   - `claim_type`: One of: statistic, legal_assertion, comparison, forecast, opinion
   - `epistemic_type`: One of: factual, hearsay, counterfactual, prediction
     - `factual`: Direct assertion about the world (default)
     - `hearsay`: Based on unnamed/unverifiable sources
     - `counterfactual`: About the past — contrary to what happened
     - `prediction`: About the future, including conditional scenarios
     Note: A named, on-the-record source is `factual`, not hearsay.
   - `confidence`: How confident you are this is a factual claim (0-1)

## Important

- Be thorough — extract ALL factual claims
- **`speaker_name` is required** — always specify who made the claim
- Preserve the original language of quotes
- Mark opinions with implicit factual claims as `claim_type: "opinion"` with lower confidence

## Do NOT extract the following

### General exclusions

- **Biographical/title statements**: job titles are background info
- **Non-EU content**: anything not about EU membership, negotiations, or referendum
- **Common knowledge**: undisputed facts unrelated to the EU question

### Skip debate rhetoric — specific to panel shows

- **Moderator questions**: questions and introductions from the host
- **Agreement/disagreement without substance**: "I agree/disagree" without a factual claim
- **Intent expressions**: "we will...", "we reject this" — political pledges, not factual claims
- **References to what others just said**: "as [name] said..." — skip unless new factual
  content is added
- **Campaign clichés and slogans**: empty rhetoric without factual substance

## Output Format

Write a JSON array inside a code block. **Note: `speaker_name` is a required field.**

```json
[
  {{{{
    "claim_text": "...",
    "original_quote": "...",
    "speaker_name": "Full name of speaker",
    "category": "...",
    "claim_type": "...",
    "epistemic_type": "...",
    "confidence": 0.9
  }}}}
]
```

{debate_block}"""

    # Append Icelandic quality blocks for extraction
    if language == "is":
        blocks = _load_icelandic_blocks_subset("Block D", "Block F", "Block H")
        if blocks:
            context += f"\n\n{blocks}\n"

    output_path = output_dir / "_context_extraction.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path


# ── Capsule context ──────────────────────────────────────────────────


def prepare_capsule_context(
    report_data: dict,
    output_dir: Path,
) -> Path:
    """Write capsule context for the capsule-writer subagent.

    Assembles a tight summary from the final report: what the article
    is about, what it gets right, and one interesting thing to explore.
    The capsule-writer uses this to produce a constructive reader's note.

    Returns path to the context file.
    """
    title = report_data.get("article_title", "")
    source = report_data.get("article_source", "")
    date = report_data.get("article_date", "")

    claims = report_data.get("claims", [])

    from collections import Counter

    vc = Counter(c.get("verdict", "") for c in claims)
    verdict_is = {
        "supported": "stutt af heimildum",
        "partially_supported": "stutt a\u00f0 hluta",
        "unsupported": "ekki stutt",
        "misleading": "villandi",
        "unverifiable": "ekki h\u00e6gt a\u00f0 sannreyna",
    }
    verdict_lines = [f"- {verdict_is.get(v, v)}: {count}" for v, count in vc.most_common()]

    # Supported and partially supported claims
    solid_claims: list[str] = []
    for c in claims:
        if c.get("verdict") in ("supported", "partially_supported"):
            claim_obj = c.get("claim", {})
            claim_text = claim_obj.get("claim_text", "") if isinstance(claim_obj, dict) else ""
            evidence = c.get("supporting_evidence", [])
            if claim_text:
                ev_str = ", ".join(evidence[:3]) if evidence else ""
                solid_claims.append(f"- {claim_text} [{ev_str}]")
    solid_section = "\n".join(solid_claims[:6])

    # Key omissions reframed as interesting context
    omissions = report_data.get("omissions", {})
    omission_list = omissions.get("omissions", []) if isinstance(omissions, dict) else []
    interesting: list[str] = []
    for om in omission_list[:3]:
        desc = om.get("description", "")
        ev = om.get("relevant_evidence", [])
        ev_str = ", ".join(ev[:2]) if ev else ""
        if desc:
            interesting.append(f"- {desc} [{ev_str}]")
    interesting_section = (
        "\n".join(interesting) if interesting else "Engar s\u00e9rstakar ey\u00f0ur greindar."
    )

    framing = omissions.get("framing_assessment", "") if isinstance(omissions, dict) else ""
    completeness = omissions.get("overall_completeness", 0) if isinstance(omissions, dict) else 0

    context = (
        "# Samhengi fyrir lesandan\u00f3tu\n\n"
        "## Um greinina\n\n"
        f"- **Titill:** {title}\n"
        f"- **Heimild:** {source}\n"
        f"- **Dagsetning:** {date}\n"
        f"- **Fj\u00f6ldi fullyr\u00f0inga:** {len(claims)}\n"
        f"- **Sj\u00f3narhorn:** {framing}\n"
        f"- **Heildst\u00e6\u00f0ni:** {completeness:.0%}\n\n"
        "## Ni\u00f0urst\u00f6\u00f0ur mats\n\n" + "\n".join(verdict_lines) + "\n\n"
        "## Fullyr\u00f0ingar sem standa \u2014 \u00fea\u00f0 sem greinin f\u00e6r r\u00e9tt\n\n"
        + (solid_section or "Engar studdar fullyr\u00f0ingar.")
        + "\n\n"
        "## \u00c1hugavert til vi\u00f0b\u00f3tar \u2014 ekki gagn"
        "r\u00fdni, heldur fr\u00f3\u00f0leikur\n\n"
        "Eftirfarandi eru atri\u00f0i sem greinin nefnir ekki en "
        "myndu au\u00f0ga skilning lesanda.\n"
        "N\u00f3tan \u00e1 a\u00f0 kynna eitt e\u00f0a tv\u00f6 "
        "\u00feessara sem forvitnileg vi\u00f0b\u00f3t, EKKI sem gagn"
        "r\u00fdni.\n\n" + interesting_section + "\n\n"
        "## Lei\u00f0beiningar\n\n"
        "Skrifaðu 2-3 setningar á íslensku. Tónninn á að vera "
        "uppbyggilegur og forvitnilegur.\n"
        "Dragðu fram það sem greinin fær rétt og bættu við einu "
        "áhugaverðu atriði sem lesandinn getur kannað nánar. "
        "Ekki nota heimildakóða (evidence IDs) — skrifaðu léttlesinn texta.\n\n"
        "**ALDREI byrja á «Rétt er að»** — notaðu fjölbreyttar opnanir.\n\n"
        "**Nákvæmni:** Ekki einfalda tölur eða staðreyndir. "
        "EES-samningurinn nær yfir innri markaðsreglur ESB "
        "(um 70–75% miðað við fjölda lagagerða) en EKKI "
        "sjávarútveg, landbúnað, tollabandalag, utanríkisstefnu "
        "eða gjaldmiðil. Segðu aldrei «X% af ESB-lögum gilda á "
        "Íslandi» — þetta er of einföld alhæfing.\n\n"
        f"Skrifaðu niðurstöðuna í `{output_dir}/_capsule.txt`.\n"
    )

    output_path = output_dir / "_context_capsule.md"
    output_path.write_text(context, encoding="utf-8")
    return output_path
