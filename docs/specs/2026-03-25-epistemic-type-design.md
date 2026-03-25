# Epistemic Type — Design Spec

**Date:** 2026-03-25
**Status:** Approved
**Author:** Brynjólfur Gauti Jónsson + Claude

## Problem

The pipeline currently assesses all claims on a single axis: factual accuracy against evidence. This produces incorrect verdicts for claims that are epistemically different from factual assertions:

- **Hearsay** — "Morgunblaðið greindi frá meintum ummælum ráðherra samkvæmt ónafngreindum heimildum" gets `partially_supported` because tangential evidence exists about the general topic, even though the quote itself cannot be verified.
- **Predictions** — "Ef aðild næðist myndi matvælaverð lækka" gets assessed as if it were a verifiable fact rather than a forward-looking claim whose quality depends on source agreement and reasoning.
- **Counterfactuals** — "Ef Ísland hefði gengið í ESB 2013 hefði..." gets assessed against current evidence rather than evaluated as a hypothetical about the past.

The core insight: **for hearsay, topical proximity is not source verification. For predictions and counterfactuals, the question is "how well-reasoned is this?" not "is this true?"**

## Solution

Add `epistemic_type` as a new field on claims, separate from the existing `claim_type` (which describes content form: statistic, legal_assertion, etc.). The epistemic type describes source reliability and determines how the assessor reasons about the claim.

### Enum Values

```python
class EpistemicType(StrEnum):
    FACTUAL = "factual"               # Direct assertion about the world
    HEARSAY = "hearsay"               # Attributed to unnamed/unverifiable sources
    COUNTERFACTUAL = "counterfactual"  # About the past — contrary to what happened
    PREDICTION = "prediction"          # About the future, including conditional scenarios
```

**Key distinctions:**
- `counterfactual` = past only, contrary to fact ("ef X hefði gerst...")
- `prediction` = future, including conditional ("ef aðild næðist myndi...")
- `hearsay` = unnamed/unverifiable source ("ónafngreindir viðmælendur segja...")
- `factual` = everything else (default)

A named, on-the-record quote is `factual`, not hearsay. If the source is verifiable, it's factual.

### ClaimType Rename: prediction → forecast

The existing `ClaimType` enum has `PREDICTION = "prediction"` which collides with `EpistemicType.PREDICTION`. To avoid confusion, rename:

```python
class ClaimType(StrEnum):
    STATISTIC = "statistic"
    LEGAL_ASSERTION = "legal_assertion"
    COMPARISON = "comparison"
    FORECAST = "forecast"         # was "prediction" — describes content form (a numerical/outcome forecast)
    OPINION = "opinion"
```

**Migration:** `UPDATE claims SET claim_type = 'forecast' WHERE claim_type = 'prediction';`

This also requires updating all extraction/assessment prompts that list valid `claim_type` values.

### Two Independent Dimensions

`claim_type` and `epistemic_type` are orthogonal:

|                    | factual | hearsay | counterfactual | prediction |
|--------------------|---------|---------|----------------|------------|
| **statistic**      | "Exports are 23%" | "Sources say exports are 23%" | "Exports would have been 23%" | "Exports will reach 23%" |
| **legal_assertion** | "Article 112 allows X" | "Minister reportedly said Article 112 allows X" | "If we had invoked Article 112..." | "Article 112 will be invoked" |
| **comparison**     | "Norway pays more" | "Officials claim Norway pays more" | "Norway would have paid more" | "Iceland will pay more than Norway" |

## Assessment Logic

### Pipeline Branching

```
Extract claims → tag epistemic_type
  ├── hearsay         → skip assessment, auto-verdict: unverifiable, published=False
  ├── factual         → assess normally (current logic, unchanged)
  └── counterfactual  → assess reasoning quality (different prompt framing)
  └── prediction      → assess reasoning quality (different prompt framing)
```

### Hearsay Short-Circuit

The short-circuit lives in `retrieve_evidence_for_claims()` in `src/esbvaktin/pipeline/retrieve_evidence.py` — the shared function used by all three pipeline paths (articles, speeches, fact-check skill). Hearsay claims are filtered out before evidence retrieval and receive a pre-built assessment:

- `verdict`: `unverifiable`
- `published`: `False`
- `substantive`: `False` (cannot contribute to credibility scoring)
- `explanation_is`: "Fullyrðingin byggir á ónafngreindum heimildum sem ekki er hægt að staðfesta."
- `confidence`: 0.0
- `supporting_evidence`: []
- `contradicting_evidence`: []

`scripts/reassess_claims.py` uses its own `_search_evidence_dual()` and needs a separate gate: skip claims where `epistemic_type = 'hearsay'`.

This saves ~5 minutes of Opus time per hearsay claim.

### Prediction/Counterfactual Assessment

The assessor receives type-specific instructions. Instead of "is this factually accurate?", the question becomes "how well-founded is this reasoning?" The assessor evaluates:

1. **Source agreement** — do multiple credible sources agree?
2. **Source credibility** — official institutions, recognised experts, or unnamed bloggers?
3. **Precedent** — evidence from other countries (Norway, Sweden, Croatia)?
4. **Reasoning quality** — is the cause-effect chain well-supported?

Confidence ceiling: **0.8** for predictions and counterfactuals. Enforced in a dedicated `clamp_epistemic_confidence()` function called after `parse_assessments()` but before report assembly. This function also sets the ceiling on the `Claim.confidence` field (extraction confidence), not just the assessment confidence.

### Verdict Meaning by Epistemic Type

Same 5 DB values, different semantics and display labels:

| DB verdict | Factual | Prediction/Counterfactual |
|---|---|---|
| `supported` | Evidence confirms | Broad source agreement, strong evidence base |
| `partially_supported` | Partially correct, missing nuance | Some basis but contested or limited |
| `unsupported` | No evidence supports | No credible basis, flawed reasoning |
| `misleading` | Correct but omits critical context | Oversimplified, omits key conditions |
| `unverifiable` | Insufficient evidence | Insufficient basis to assess reasoning |

## Extraction

The claim-extractor (sonnet) tags `epistemic_type` alongside the existing fields. Detection heuristics:

| Type | Icelandic signal patterns |
|---|---|
| `hearsay` | "ónafngreindir viðmælendur", "heimildir segja", "að sögn", "fregnir herma", "mun hafa sagt", "er sagður/sögð hafa", "samkvæmt heimildum" |
| `counterfactual` | "ef X hefði", "hefði í för með sér", "hefði orðið", "ef X væri búið" — past subjunctive, contrary to fact |
| `prediction` | "ef aðild næðist myndi", "mun verða", "verður", "stefnir í", "er líklegt", "innan X ára", "ef Ísland gengur í" |
| `factual` | Default — everything else |

**Boundary rules:**
- Named, on-the-record source → `factual` (even if attributed)
- Unnamed source → `hearsay`
- Past subjunctive ("ef X hefði") → `counterfactual`
- Future conditional ("ef aðild næðist myndi") → `prediction`

**Disambiguation note for prompts:** `claim_type` describes *what kind of content* the claim contains (a statistic, a legal assertion, a comparison, a forecast, an opinion). `epistemic_type` describes *how knowable* the claim is (a verifiable fact, hearsay from unnamed sources, a hypothetical about the past, a prediction about the future). A single claim has both: a `statistic` (claim_type) that is a `prediction` (epistemic_type) = "ESB-aðild mun lækka matvælaverð um 20%."

**Output format:**

```json
{
  "claim_text": "...",
  "original_quote": "...",
  "category": "fisheries",
  "claim_type": "statistic",
  "epistemic_type": "factual",
  "confidence": 0.9
}
```

## Data Model

### DB Migration

```sql
-- Add epistemic_type column
ALTER TABLE claims ADD COLUMN epistemic_type TEXT NOT NULL DEFAULT 'factual';
CREATE INDEX idx_claims_epistemic ON claims(epistemic_type);

-- Rename claim_type prediction → forecast
UPDATE claims SET claim_type = 'forecast' WHERE claim_type = 'prediction';
```

Default `'factual'` makes all ~1,500 existing claims valid without immediate migration.

### Schema Sync

Update the `CLAIMS_SCHEMA` string in `src/esbvaktin/claim_bank/operations.py` to include `epistemic_type TEXT NOT NULL DEFAULT 'factual'` in the CREATE TABLE definition, so fresh `init_db` runs create the column.

### Upsert Behaviour

In `add_claim()`, `epistemic_type` goes in both the INSERT and ON CONFLICT DO UPDATE clauses. If a claim is re-encountered, the epistemic type from the latest assessment wins (same as verdict, explanation, etc.). This handles the case where a hearsay claim is later encountered with a verified source — the type updates from `hearsay` to `factual`.

### search_claims() Return Field

`search_claims()` must include `epistemic_type` in its SELECT and map it to `ClaimBankMatch`. This enables:
- Short-circuiting hearsay on bank hits
- Displaying epistemic type in reports for bank-matched claims
- The fact-check skill showing epistemic context for recurring claims

### Backfill Strategy

**Phase 1: Classification (no verdict changes)**

Sonnet agent pass over existing claims in batches of 30 (conservative — test first batch of 30, increase if quality is stable). Reads `canonical_text_is` and tags `epistemic_type`. Updates the column. No verdicts change.

Estimated distribution: ~70% factual, ~20% prediction, ~5% counterfactual, ~5% hearsay.

**Phase 2: Hearsay verdict correction**

Claims tagged `hearsay` with verdict ≠ `unverifiable` are automatically corrected:
- `verdict` → `unverifiable`
- `published` → `False`
- `substantive` → `False`
- `explanation_is` → standard hearsay explanation
- `version` incremented

Estimated ~50-75 claims affected.

**Important: Phase 2 must complete before any site export run.** During the gap between Phase 1 (hearsay tagged) and Phase 2 (verdicts corrected), hearsay claims may have non-unverifiable verdicts. The site taxonomy's hearsay labels only cover `unverifiable` — a hearsay claim with `supported` would fail the nested lookup. To prevent this, the backfill script runs Phase 1 + Phase 2 atomically.

**Phase 3: Prediction/counterfactual reassessment (deferred)**

Claims tagged `prediction` or `counterfactual` can be reassessed under the new reasoning-based criteria in a future reassessment cycle. Not urgent — their verdicts aren't wrong, just assessed with factual framing. The confidence ceiling (0.8) is applied immediately.

## Site Display

### Claim Tracker Page

1. **Epistemic type filter** — row of filter buttons above verdict counters: `Allar` | `Staðreyndir` | `Spár` | `Tilgátur` | `Orðsagnir`. Filters the claim list and updates verdict counters.

2. **Secondary badge per claim** — small muted badge for non-factual types:
   - Prediction: `Spá` (muted blue)
   - Counterfactual: `Tilgáta` (muted purple)
   - Hearsay: `Orðsögn` (grey)
   - Factual: no badge

3. **Verdict badge text** changes based on epistemic type (nested lookup).

### Claim Detail Page

One-line context for non-factual types:
- Prediction: "Þetta er spá — mat byggir á samstöðu heimilda og gæðum rökfærslu."
- Counterfactual: "Þetta er tilgáta um atburði sem gerðust ekki — mat byggir á rökstuðningi og fordæmum."
- Hearsay: "Þetta byggir á ónafngreindum heimildum sem ekki er hægt að staðfesta."

### Homepage Counters

No change to counter structure. Hearsay claims become unpublished so they naturally drop out of the counts. All published claims (factual + prediction + counterfactual) counted in the verdict boxes.

### Topic Pages

Add epistemic distribution per topic: "Sjávarútvegur: 45 staðreyndir, 23 spár, 3 tilgátur, 2 orðsagnir."

### Site Taxonomy

```javascript
verdictLabels: {
  factual: {
    supported: "Staðfest",
    partially_supported: "Að hluta staðfest",
    unsupported: "Óstutt",
    misleading: "Þarfnast samhengis",
    unverifiable: "Heimildir vantar",
  },
  prediction: {
    supported: "Víðtæk samstaða",
    partially_supported: "Nokkur stoð",
    unsupported: "Órökstudd",
    misleading: "Ofeinföldun",
    unverifiable: "Heimildir vantar",
  },
  counterfactual: {
    supported: "Víðtæk samstaða",
    partially_supported: "Nokkur stoð",
    unsupported: "Órökstudd",
    misleading: "Ofeinföldun",
    unverifiable: "Heimildir vantar",
  },
  hearsay: {
    unverifiable: "Óstaðfest heimild",
  },
},
epistemicTypeLabels: {
  factual: "Staðreynd",
  prediction: "Spá",
  counterfactual: "Tilgáta",
  hearsay: "Orðsögn",
},
```

## Files to Modify

### Backend (esbvaktin repo)

| File | Change |
|---|---|
| `src/esbvaktin/pipeline/models.py` | Add `EpistemicType` StrEnum. Rename `ClaimType.PREDICTION` → `FORECAST`. Add `epistemic_type` field to `Claim`. |
| `src/esbvaktin/claim_bank/operations.py` | Add `epistemic_type` to `CLAIMS_SCHEMA` CREATE TABLE, `add_claim()` INSERT + ON CONFLICT, `update_claim_verdict()`, `search_claims()` SELECT + `ClaimBankMatch` mapping |
| `src/esbvaktin/claim_bank/models.py` | Add `epistemic_type` to `CanonicalClaim` |
| `src/esbvaktin/pipeline/prepare_context.py` | Extraction prompt: add `epistemic_type` field, heuristic patterns, disambiguation note. Assessment prompt: reasoning-based rules for prediction/counterfactual, show `epistemic_type` per claim. Update `claim_type` valid values (prediction → forecast). |
| `src/esbvaktin/pipeline/parse_outputs.py` | Parse `epistemic_type` from extractor output, default to `"factual"`. Add `clamp_epistemic_confidence()`. Handle `epistemic_type` in `_normalise_assessment()` (preserve field like `speaker_name`). |
| `src/esbvaktin/pipeline/retrieve_evidence.py` | Filter hearsay claims in `retrieve_evidence_for_claims()`, return pre-built assessments |
| `src/esbvaktin/pipeline/register_sightings.py` | Pass `epistemic_type` to `add_claim()` |
| `src/esbvaktin/speeches/register_sightings.py` | Same |
| `scripts/register_article_sightings.py` | Pass `epistemic_type` to `add_claim()`, gate hearsay (unpublished, unverifiable) |
| `src/esbvaktin/pipeline/assemble_report.py` | Use nested verdict labels in `_VERDICT_LABELS_IS` based on epistemic type |
| `.claude/agents/claim-extractor.md` | Add `epistemic_type` to quality checklist, update `claim_type` valid values (prediction → forecast) |
| `.claude/agents/claim-assessor.md` | Add reasoning-based assessment rules for prediction/counterfactual |
| `scripts/export_claims.py` | Include `epistemic_type` in Parquet + JSON output |
| `scripts/export_topics.py` | Epistemic breakdown per topic |
| `scripts/prepare_site.py` | Add `epistemic_type` to `_load_db_verdicts()` SELECT, pass through to report JSON, nested verdict labels |
| `scripts/reassess_claims.py` | Skip hearsay claims in `_search_evidence_dual()`. Respect confidence ceiling for prediction/counterfactual. Update valid `claim_type` values. |
| `scripts/audit_claims.py` | Exclude hearsay from verdict audit patterns |
| `scripts/seed_claim_bank.py` | Handle `epistemic_type` (default `"factual"` for seeded claims) |

### New scripts

| Script | Purpose |
|---|---|
| `scripts/backfill_epistemic_type.py` | Phase 1 classification + Phase 2 hearsay correction (atomic — both phases in one run) |

### Site repo (esbvaktin-site)

| File | Change |
|---|---|
| `assets/js/site-taxonomy.js` | Nested `verdictLabels` by epistemic type, add `epistemicTypeLabels` |
| Claim tracker JS + CSS | Epistemic filter buttons, secondary badges, nested label lookup |
| Topic detail template | Epistemic distribution line |
| Claim detail template | Epistemic context line |

## Tests

| Test | Validates |
|---|---|
| `test_models.py` | `EpistemicType` enum, `ClaimType.FORECAST` rename, `Claim` with epistemic_type |
| `test_parse_outputs.py` | Parse epistemic_type, default to factual, `clamp_epistemic_confidence()`, `_normalise_assessment()` preserves field |
| `test_retrieve_evidence.py` | Hearsay short-circuit in `retrieve_evidence_for_claims()`, auto-unverifiable assessment returned |
| `test_register_sightings.py` | Hearsay → published=False + substantive=False, epistemic_type flows to DB |
| `test_prepare_context.py` | Epistemic type in extraction + assessment context, claim_type shows "forecast" not "prediction" |
| `test_export_claims.py` | `epistemic_type` present in output |
| `test_backfill.py` | Classification accuracy on known examples, hearsay verdict correction, atomic Phase 1+2 |

## Out of Scope

- Weekly editorial pipeline (describes debate, doesn't need epistemic tags)
- Omissions-analyst (analyses missing coverage, not epistemic status)
- Evidence DB (curated facts, no epistemic dimension)
- Phase 3 reassessment (deferred to future cycle)
