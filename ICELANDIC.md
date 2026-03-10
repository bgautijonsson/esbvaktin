# Icelandic Text Quality — ESBvaktin

Master reference for generating high-quality Icelandic text in the ESBvaktin pipeline. Adapted from the Þingfréttir project's battle-tested patterns.

## The Problem

LLMs generating Icelandic face three failure modes:

1. **ASCII transliteration** — Writing "thjodaratkvaedagreidsla" instead of "þjóðaratkvæðagreiðsla". The most damaging: renders text unreadable.
2. **Translationese** — Sentences that parse as Icelandic but feel thought in English first. Unnatural word order, English calques, over-explanation of concepts any Icelander knows.
3. **Morphological errors** — Wrong case after prepositions, invented compounds, dative sickness, incorrect genitive forms. GreynirCorrect catches some but not all.

ESBvaktin's domain adds a fourth:
4. **EU terminology drift** — Inconsistent Icelandic terms for EU concepts (e.g., mixing "sameiginleg landbúnaðarstefna" and "sameiginlega landbúnaðarstefnan" for CAP, or using English abbreviations where Icelandic exists).

## Core Principles

### 1. Write Icelandic First

Subagents compose Icelandic directly from structured data and evidence. They never translate from English prose. The assessment context files provide evidence in English (as stored in the DB), but the subagent's output — `explanation_is`, `missing_context_is`, `claim_text` — must be composed as original Icelandic.

### 2. Unicode Always

**CRITICAL — All Icelandic text MUST use proper Unicode characters.** Never transliterate to ASCII.

This applies to:
- **All prose fields**: `explanation_is`, `missing_context_is`, `canonical_text_is`
- **Icelandic names**: Sjálfstæðisflokkurinn (not Sjalfstaedisflokkurinn), Sigmundur Davíð (not Sigmundur David)
- **EU terms in Icelandic**: þjóðaratkvæðagreiðsla, aðildarviðræður, sameiginleg sjávarútvegsstefna
- **Place names**: Brussel (not Brussels when writing in Icelandic), Lúxemborg, Strassborg
- **Quoted text**: Reproduce exactly as spoken/written

Characters that must appear naturally in any Icelandic paragraph: **þ, ð, á, é, í, ó, ú, ý, æ, ö** (and uppercase equivalents).

If a subagent's output contains none of these characters in a paragraph of 20+ words, the output is defective.

### 3. Pattern-Match Exemplars

Every subagent prompt that produces Icelandic text must reference the exemplar bank (`knowledge/exemplars_is.md`). This gives the LLM concrete targets for register, sentence rhythm, and terminology.

### 4. Self-Review Before Submission

Subagents must check their output against a self-review checklist before writing their final JSON. This catches translationese and structural monotony.

### 5. Post-Process Automatically

All Icelandic output passes through `correct_icelandic.py` before it reaches the database or the site. This catches what the LLM misses.

## Register: Analytical Icelandic

ESBvaktin's register differs from Þingfréttir's editorial voice. We write **clear, authoritative fact-check assessments** — not opinion journalism.

**Target register:** Kastljós (RÚV) explainer segments, Kjarninn fact-checks, Morgunblaðið analysis pieces. Informed, direct, accessible.

**Do:**
- State verdicts confidently: "Heimildir staðfesta þetta" not "Heimildir virðast benda til þess"
- Use precise references: "Samkvæmt AGRI-DATA-008" not "Samkvæmt gögnum"
- Surface caveats directly: "Þó ber að hafa í huga að..."
- Use natural Icelandic sentence rhythm — vary length, lead with the important element

**Don't:**
- Hedge when evidence is clear — if it's supported, say so plainly
- Over-explain concepts Icelanders know (what Alþingi is, what a þjóðaratkvæðagreiðsla is)
- Use English abbreviations when Icelandic exists (ESB is fine — it's the standard Icelandic abbreviation; but use "sameiginleg landbúnaðarstefna" not "Common Agricultural Policy" in Icelandic text)
- Stack multiple subordinate clauses — break into shorter sentences

## EU Terminology (Íslensk hugtök)

Consistent Icelandic terms for EU concepts. Use these in all subagent output.

| English | Icelandic | Notes |
|---------|-----------|-------|
| European Union (EU) | Evrópusambandið (ESB) | ESB is standard abbreviation |
| EU membership | ESB-aðild | Hyphenated |
| Accession negotiations | Aðildarviðræður | Not "inngöngu-" |
| Referendum | Þjóðaratkvæðagreiðsla | |
| Common Agricultural Policy (CAP) | Sameiginleg landbúnaðarstefna | |
| Common Fisheries Policy (CFP) | Sameiginleg sjávarútvegsstefna | |
| EEA Agreement | EES-samningurinn | |
| Acquis communautaire | Regluverkið (acquis) | Use "regluverkið" in plain text |
| Treaty of Lisbon | Lissabon-samningurinn | |
| Derogation/exemption | Undanþága | |
| Transitional period | Aðlögunartímabil | |
| Screening (chapters) | Athugun (viðræðukaflar) | |
| European Commission | Framkvæmdastjórn ESB | |
| European Parliament | Evrópuþingið | |
| Council of the EU | Ráðherraráð ESB | |
| Single market | Innri markaðurinn | |
| Eurozone | Evrusvæðið | |
| Schengen area | Schengen-svæðið | |
| Structural funds | Byggðasjóðir | |
| Subsidy | Styrkur / stuðningur | Context-dependent |
| Quota (fishing) | Kvóti | |
| Tariff | Tollur | |

## Morphology Verification

### MCP Tool (when available)
```
mcp__icelandic-morphology__lookup_word(word)       — verify compounds exist
mcp__icelandic-morphology__get_variant(word, class, form) — check inflection
mcp__icelandic-morphology__get_lemma(word)          — find lemma
```

### Pre-Flight Checklist

Before writing Icelandic output, verify:

**Case after prepositions:**
- við → þolfall (ÞF): "við Evrópusambandið"
- af → þágufall (ÞGF): "af sameiginlegri stefnu"
- til → eignarfall (EF): "til aðildar"
- um → þolfall (ÞF): "um þjóðaratkvæðagreiðslu"
- í → ÞF (motion) / ÞGF (location): "í viðræður" vs "í viðræðum"
- á → ÞF (motion) / ÞGF (location): "á fund" vs "á fundi"
- frá → ÞGF: "frá sameiginlegri stefnu"
- með → ÞF (accompaniment) / ÞGF (instrument): "með Evrópusambandinu"

**Impersonal verbs:**
- vanta → ÞF subject: "okkur vantar heimildir"
- finnast → ÞGF subject: "mér finnst"
- langa → ÞF: "mig langar"

**Dative sickness (ófagur þágufall):**
- Verify verb governance — don't over-apply dative
- Common trap: "mér líkar" (correct ÞGF) vs "mig vantar" (correct ÞF)

**Definite articles:**
- Suffixed: -inn/-in/-ið (landbúnaðarstefnan, sjávarútvegsstefnan)
- Not free-standing: "stefnan" not "hin stefna" (except in formal/archaic register)

**Genitive:**
- þess (masc/neut sg) vs þeirra (pl) vs hennar/hans (fem/masc sg personal)

## Known LLM Failure Patterns

Patterns that tools (GreynirCorrect, BÍN) parse as valid but no Icelandic writer would produce:

1. **ASCII transliteration** — "thjodaratkvaedagreidsla" for "þjóðaratkvæðagreiðsla". Most common in JSON output fields.
2. **English word order in subordinate clauses** — "sem ríkisstjórnin hefur ákveðið" should often be "sem ríkisstjórnin ákveður" depending on context.
3. **Invented compounds** — verify against BÍN before using unfamiliar compounds.
4. **bíða ≠ bjóða** — "bíður upp á" (waits for) vs "býður upp á" (offers). Common LLM confusion.
5. **á/í with time** — "í vikunni" not "á vikunni"; "í mars" not "á mars".
6. **Mechanical sentence openings** — repeating "Samkvæmt..." or "Heimildir staðfesta..." every sentence. Vary: start with the claim, the caveat, or the implication.
7. **Hedging when evidence is clear** — "virðist benda til" when evidence plainly supports. Be direct.
8. **Missing caveats when evidence is qualified** — evidence entries have a `caveats` field. Surface them.
9. **Mixing register** — switching between formal ("hér að ofan") and conversational within the same explanation.
10. **Singular verb + plural subject** — "var ákvarðanir" should be "voru ákvarðanir".

## Self-Review Checklist

Subagents must verify before submitting output:

1. **Unicode check**: Does every Icelandic paragraph contain characters from {þ, ð, á, é, í, ó, ú, ý, æ, ö}? If not, the output is defective — rewrite.
2. **Translationese check**: Does any sentence feel thought in English first? Rewrite it.
3. **Monotony check**: Are three consecutive sentences using the same opening pattern (e.g., "Samkvæmt...")?  Restructure.
4. **Verdict confidence**: Are verdicts stated as confident judgements or tentative hedges? Be direct.
5. **Evidence grounding**: Does every claim in the explanation cite at least one evidence ID?
6. **Caveats surfaced**: Are caveats from the evidence entries reflected in `missing_context_is`?
7. **EU terminology**: Are EU terms consistent with the terminology table above?

## Post-Processing Pipeline

All Icelandic text passes through `scripts/correct_icelandic.py` before reaching the database or site export. The pipeline runs these layers:

| Layer | Tool | Mode | What it catches |
|-------|------|------|-----------------|
| 1 | GreynirCorrect | Auto-fix | Spelling (S004), compounds (S001), phrases (P_afað) |
| 2 | Icegrams | Review | Translationese, unnatural phrasing (trigram probability) |
| 3 | BÍN | Review | Invalid word forms, invented compounds |
| 4 | Confusables | Review | LLM-specific word confusion patterns |
| 5 | EU Terms | Review | Terminology inconsistency (ESBvaktin-specific) |
| 6 | GreynirEngine | Review | Deep syntactic parse failures |

**Layer 1** auto-fixes safe corrections with a BÍN dual-lemma safety gate (prevents meaning-destroying changes). All other layers flag for human review.

### Usage

```bash
# Check and auto-fix Icelandic text
uv run python scripts/correct_icelandic.py check data/reassessment/_assessments_batch_1.json --fix

# Review only (no auto-fix)
uv run python scripts/correct_icelandic.py check data/analyses/*/

# After re-assessment, before DB update
uv run python scripts/correct_icelandic.py check data/reassessment/ --fix
```

## File Reference

| File | Purpose |
|------|---------|
| `ICELANDIC.md` | This file — master reference |
| `.claude/rules/icelandic-core.md` | Auto-loaded rules for all Icelandic generation |
| `.claude/skills/icelandic-shared/` | Shared prompt blocks for subagents |
| `knowledge/exemplars_is.md` | Gold-standard Icelandic assessment exemplars |
| `knowledge/eu_terms_is.md` | EU terminology glossary (Icelandic) |
| `scripts/correct_icelandic.py` | Post-processing pipeline entry point |
| `src/esbvaktin/corrections/` | Correction layer modules |
