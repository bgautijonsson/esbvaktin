---
paths:
  - "**/*_is.*"
  - "data/reassessment/**"
  - "data/analyses/**"
---

# Icelandic Writing: Grammar & Morphology

Activated when editing Icelandic text fields or assessment files.

## Pre-Flight Checklist

Verify these before writing Icelandic output. Most common LLM errors, ordered by frequency.

### 1. Case after prepositions

| Preposition | Case | Common LLM error |
|-------------|------|-------------------|
| *við* | ÞF (accusative) | Using dative |
| *af* | ÞGF (dative) | Using accusative |
| *til* | EF (genitive) | Using dative |
| *frá* | ÞGF (dative) | Using accusative |
| *í* | ÞF (motion) / ÞGF (location) | Confusing the two |
| *á* | ÞF (motion) / ÞGF (location) | Confusing the two |
| *um* | ÞF (accusative) | Using dative |
| *með* | ÞF (accompaniment) / ÞGF (instrument) | Confusing the two |

### 2. Impersonal verbs (non-nominative subjects)

| Verb | Subject case | Correct | LLM error |
|------|-------------|---------|-----------|
| *vanta* | ÞF | *Mig vantar* | *Ég vanta* |
| *finnast* | ÞGF | *Mér finnst* | *Ég finnst* |
| *langa* | ÞF | *Mig langar* | *Ég langar* |
| *líka* | ÞGF | *Mér líkar* | *Ég líka* |

### 3. Dative sickness (*þágufallssýki*)

LLMs over-apply dative where accusative is correct. Look up verb governance when uncertain. Common traps: *hjálpa*→ÞGF, *kenna*→ÞGF, *trúa*→ÞGF.

### 4. Definite article suffixes

Icelandic suffixes the article (*-inn/-in/-ið*). Use suffixed forms: *landbúnaðarstefnan*, *sjávarútvegsstefnan*, *samningurinn*.

### 5. Genitive forms

*þess* (masc/neut sg) vs *þeirra* (pl). Feminine indefinite genitive plural: *kvenna*, not *kvennanna*.

## Known LLM Failure Patterns

These errors are **not caught** by GreynirCorrect, GreynirEngine, Icegrams, or BÍN.

| # | Pattern | Error | Correct |
|---|---------|-------|---------|
| 1 | ASCII transliteration | "thjodaratkvaedagreidsla" | "þjóðaratkvæðagreiðsla" |
| 2 | `bíður upp á` | bíða (wait) ≠ bjóða (offer) | `býður upp á` |
| 3 | `á vikunni` | Wrong prep. with time | `í vikunni` |
| 4 | `var ákvarðanir` | Singular verb + plural subject | `voru ákvarðanir` |
| 5 | Mechanical openings | "Samkvæmt..." × 3 in a row | Vary: claim, caveat, implication |
| 6 | Hedging w/ clear evidence | "virðist benda til" | "staðfestir", "sýnir" |
| 7 | English EU terms in IS | "Common Agricultural Policy" | "sameiginleg landbúnaðarstefna" |
| 8 | Missing caveats | Ignoring evidence caveats field | Surface them in missing_context |
| 9 | Mixed register | "hér að ofan" + conversational | Keep consistent analytical tone |
| 10 | Self-reference | "eins og áður segir" | State the content directly |

## Register: Analytical Icelandic

- **Register:** Clear, authoritative fact-check assessments. References: Kastljós explainers, Kjarninn fact-checks, Morgunblaðið analysis.
- **Directness:** State verdicts as confident judgements. "Heimildir staðfesta þetta" not "Heimildir virðast benda til þess."
- **No term explanations.** Readers know ESB, EES, Alþingi, þjóðaratkvæðagreiðsla.
- **No translations.** EU institutional names in Icelandic only.
- **Caveats direct:** "Þó ber að hafa í huga..." not "Einnig má kannski benda á..."
