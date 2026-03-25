# Epistemic Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `epistemic_type` as a new dimension on claims (factual/hearsay/counterfactual/prediction) that changes how claims are assessed — hearsay auto-unverifiable, predictions/counterfactuals assessed on reasoning quality.

**Architecture:** New `EpistemicType` StrEnum alongside existing `ClaimType`. The extractor tags it at extraction time, the pipeline gates on it (hearsay short-circuits before evidence retrieval), and the assessor uses type-specific reasoning. Display labels are nested by epistemic type in the site taxonomy.

**Tech Stack:** Python 3.12+, PostgreSQL, Pydantic, pytest, 11ty site (JS)

**Spec:** `docs/specs/2026-03-25-epistemic-type-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/esbvaktin/pipeline/models.py` | Modify | Add `EpistemicType` StrEnum, rename `ClaimType.PREDICTION` → `FORECAST`, add `epistemic_type` to `Claim` |
| `src/esbvaktin/claim_bank/models.py` | Modify | Add `epistemic_type` to `CanonicalClaim` and `ClaimBankMatch` |
| `src/esbvaktin/claim_bank/operations.py` | Modify | Schema, `add_claim()`, `search_claims()`, `update_claim_verdict()` |
| `src/esbvaktin/pipeline/parse_outputs.py` | Modify | Parse `epistemic_type`, `clamp_epistemic_confidence()`, `_normalise_assessment()` |
| `src/esbvaktin/pipeline/retrieve_evidence.py` | Modify | Hearsay short-circuit in `retrieve_evidence_for_claims()` |
| `src/esbvaktin/pipeline/prepare_context.py` | Modify | Extraction + assessment prompts |
| `src/esbvaktin/pipeline/register_sightings.py` | Modify | Pass `epistemic_type` through |
| `src/esbvaktin/speeches/register_sightings.py` | Modify | Pass `epistemic_type` through |
| `scripts/register_article_sightings.py` | Modify | Pass `epistemic_type` through, gate hearsay |
| `src/esbvaktin/pipeline/assemble_report.py` | Modify | Nested verdict labels |
| `.claude/agents/claim-extractor.md` | Modify | Add `epistemic_type` to checklist, rename prediction → forecast |
| `.claude/agents/claim-assessor.md` | Modify | Add reasoning-based rules |
| `scripts/export_claims.py` | Modify | Include `epistemic_type` in output |
| `scripts/export_topics.py` | Modify | Epistemic breakdown per topic |
| `scripts/prepare_site.py` | Modify | `_load_db_verdicts()` + pass-through |
| `scripts/reassess_claims.py` | Modify | Skip hearsay, confidence ceiling |
| `scripts/audit_claims.py` | Modify | Exclude hearsay |
| `scripts/fact_check_speeches.py` | Modify | Handle 3-tuple return from `retrieve_evidence_for_claims()` |
| `src/esbvaktin/ground_truth/schema.sql` | Modify | Update `claim_type` comment (prediction → forecast) |
| `.claude/skills/fact-check/SKILL.md` | Modify | Update `claim_type` valid values (prediction → forecast) |
| `scripts/backfill_epistemic_type.py` | Create | Phase 1 classification + Phase 2 hearsay correction |

---

### Task 1: Add EpistemicType enum and rename ClaimType.PREDICTION

**Files:**
- Modify: `src/esbvaktin/pipeline/models.py:9-14` (ClaimType enum), `:70-81` (Claim model)
- Test: `tests/test_models.py` (new test class)

- [ ] **Step 1: Write failing tests for new enum and renamed value**

```python
# tests/test_models.py — add new test class

class TestEpistemicType:
    def test_enum_values(self):
        from esbvaktin.pipeline.models import EpistemicType
        assert EpistemicType.FACTUAL == "factual"
        assert EpistemicType.HEARSAY == "hearsay"
        assert EpistemicType.COUNTERFACTUAL == "counterfactual"
        assert EpistemicType.PREDICTION == "prediction"

    def test_claim_type_forecast_replaces_prediction(self):
        from esbvaktin.pipeline.models import ClaimType
        assert ClaimType.FORECAST == "forecast"
        assert not hasattr(ClaimType, "PREDICTION")

    def test_claim_has_epistemic_type_field(self):
        from esbvaktin.pipeline.models import Claim, ClaimType, EpistemicType
        claim = Claim(
            claim_text="Test",
            original_quote="Test",
            category="fisheries",
            claim_type=ClaimType.STATISTIC,
            epistemic_type=EpistemicType.FACTUAL,
            confidence=0.9,
        )
        assert claim.epistemic_type == EpistemicType.FACTUAL

    def test_claim_epistemic_type_defaults_to_factual(self):
        from esbvaktin.pipeline.models import Claim, ClaimType, EpistemicType
        claim = Claim(
            claim_text="Test",
            original_quote="Test",
            category="fisheries",
            claim_type=ClaimType.STATISTIC,
            confidence=0.9,
        )
        assert claim.epistemic_type == EpistemicType.FACTUAL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev python -m pytest tests/test_models.py::TestEpistemicType -v`
Expected: FAIL — `EpistemicType` not defined, `ClaimType.FORECAST` not found

- [ ] **Step 3: Implement enum changes in models.py**

In `src/esbvaktin/pipeline/models.py`:

1. Rename `ClaimType.PREDICTION` to `ClaimType.FORECAST`:
```python
class ClaimType(StrEnum):
    STATISTIC = "statistic"
    LEGAL_ASSERTION = "legal_assertion"
    COMPARISON = "comparison"
    FORECAST = "forecast"
    OPINION = "opinion"
```

2. Add `EpistemicType` enum after `ClaimType`:
```python
class EpistemicType(StrEnum):
    FACTUAL = "factual"
    HEARSAY = "hearsay"
    COUNTERFACTUAL = "counterfactual"
    PREDICTION = "prediction"
```

3. Add field to `Claim` model (after `claim_type`, before `confidence`):
```python
    epistemic_type: EpistemicType = Field(
        default=EpistemicType.FACTUAL,
        description="Epistemic status: factual, hearsay, counterfactual, prediction",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev python -m pytest tests/test_models.py::TestEpistemicType -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Fix all references to ClaimType.PREDICTION across the codebase**

Run: `uv run --extra dev python -m pytest tests/ -v --tb=short 2>&1 | head -80`

Known files that reference `ClaimType.PREDICTION` or `claim_type="prediction"`:

- `tests/test_retrieve_evidence.py:57`
- `tests/test_icelandic_report.py:50`
- `src/esbvaktin/pipeline/prepare_context.py` — 6 prompt locations (lines ~128, ~192, ~913, ~987, ~1119, ~1195)
- `src/esbvaktin/pipeline/prepare_fact_check.py:108`
- `src/esbvaktin/ground_truth/schema.sql:85` (comment)
- `.claude/skills/fact-check/SKILL.md` (verdict_labels dict)
- `.claude/agents/claim-extractor.md:34`

Update all: `prediction` → `forecast` in claim_type contexts. Be careful NOT to change `epistemic_type` references to `prediction` — those stay as `prediction`.

- [ ] **Step 6: Run full test suite**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/esbvaktin/pipeline/models.py tests/test_models.py
# Plus any other files fixed in step 5
git commit -m "feat: add EpistemicType enum, rename ClaimType.PREDICTION → FORECAST"
```

---

### Task 2: Update claim bank models and DB schema

**Files:**
- Modify: `src/esbvaktin/claim_bank/models.py:8-65`
- Modify: `src/esbvaktin/claim_bank/operations.py:21-44` (CLAIMS_SCHEMA), `:138-200` (search_claims), `:206-278` (add_claim), `:284-330` (update_claim_verdict)
- Test: `tests/test_models.py` (extend)

- [ ] **Step 1: Write failing tests for updated models**

```python
# tests/test_models.py — add to TestEpistemicType or new class

class TestClaimBankEpistemicType:
    def test_canonical_claim_has_epistemic_type(self):
        from esbvaktin.claim_bank.models import CanonicalClaim
        claim = CanonicalClaim(
            claim_slug="test-claim",
            canonical_text_is="Test",
            category="fisheries",
            claim_type="statistic",
            epistemic_type="factual",
            verdict="supported",
            explanation_is="Test",
            confidence=0.9,
        )
        assert claim.epistemic_type == "factual"

    def test_canonical_claim_epistemic_type_defaults_to_factual(self):
        from esbvaktin.claim_bank.models import CanonicalClaim
        claim = CanonicalClaim(
            claim_slug="test-claim",
            canonical_text_is="Test",
            category="fisheries",
            claim_type="statistic",
            verdict="supported",
            explanation_is="Test",
            confidence=0.9,
        )
        assert claim.epistemic_type == "factual"

    def test_claim_bank_match_has_epistemic_type(self):
        from datetime import date
        from esbvaktin.claim_bank.models import ClaimBankMatch
        match = ClaimBankMatch(
            claim_id=1,
            claim_slug="test",
            canonical_text_is="Test",
            similarity=0.9,
            verdict="supported",
            explanation_is="Test",
            confidence=0.9,
            last_verified=date.today(),
            is_fresh=True,
            epistemic_type="prediction",
        )
        assert match.epistemic_type == "prediction"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev python -m pytest tests/test_models.py::TestClaimBankEpistemicType -v`
Expected: FAIL — `epistemic_type` field not on models

- [ ] **Step 3: Update CanonicalClaim and ClaimBankMatch models**

In `src/esbvaktin/claim_bank/models.py`:

Add to `CanonicalClaim` (after `claim_type`):
```python
    epistemic_type: str = Field(
        default="factual",
        description="factual | hearsay | counterfactual | prediction",
    )
```

Update `claim_type` description: `"statistic | legal_assertion | comparison | forecast | opinion"`

Add to `ClaimBankMatch` (after `verdict`):
```python
    epistemic_type: str = Field(
        default="factual",
        description="factual | hearsay | counterfactual | prediction",
    )
```

- [ ] **Step 4: Update CLAIMS_SCHEMA in operations.py**

Add `epistemic_type TEXT NOT NULL DEFAULT 'factual'` after `claim_type` in the CREATE TABLE statement.

- [ ] **Step 5: Update add_claim() SQL**

Add `epistemic_type` to the INSERT column list, VALUES, parameter dict, and ON CONFLICT DO UPDATE clause.

- [ ] **Step 6: Update search_claims() SQL and mapping**

Add `epistemic_type` to the SELECT, the `columns` list, and verify `ClaimBankMatch` receives it.

- [ ] **Step 7: Note on update_claim_verdict()**

`update_claim_verdict()` does NOT need `epistemic_type` — it updates verdict/evidence/confidence during reassessment, but epistemic type is set at extraction/backfill time and doesn't change. No modification needed.

- [ ] **Step 9: Run tests**

Run: `uv run --extra dev python -m pytest tests/test_models.py::TestClaimBankEpistemicType -v`
Expected: PASS

- [ ] **Step 10: Run full test suite**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 11: Commit**

```bash
git add src/esbvaktin/claim_bank/models.py src/esbvaktin/claim_bank/operations.py tests/test_models.py
git commit -m "feat: add epistemic_type to claim bank models and schema"
```

---

### Task 3: DB migration — add column + rename claim_type

**Files:**
- No code files — SQL migration only

- [ ] **Step 1: Run the migration**

```bash
uv run python -c "
from esbvaktin.ground_truth.operations import get_connection
conn = get_connection()
conn.execute('ALTER TABLE claims ADD COLUMN IF NOT EXISTS epistemic_type TEXT NOT NULL DEFAULT %s', ('factual',))
conn.execute('CREATE INDEX IF NOT EXISTS idx_claims_epistemic ON claims(epistemic_type)')
conn.execute(\"UPDATE claims SET claim_type = 'forecast' WHERE claim_type = 'prediction'\")
conn.commit()
print('Migration complete')
# Verify
row = conn.execute('SELECT COUNT(*) FROM claims WHERE epistemic_type = %s', ('factual',)).fetchone()
print(f'Claims with epistemic_type=factual: {row[0]}')
row2 = conn.execute('SELECT COUNT(*) FROM claims WHERE claim_type = %s', ('prediction',)).fetchone()
print(f'Claims with claim_type=prediction (should be 0): {row2[0]}')
conn.close()
"
```

Expected: All claims have `epistemic_type='factual'`, zero claims with `claim_type='prediction'`.

- [ ] **Step 2: Verify with a spot check**

```bash
uv run python -c "
from esbvaktin.ground_truth.operations import get_connection
conn = get_connection()
row = conn.execute('SELECT claim_slug, claim_type, epistemic_type FROM claims LIMIT 5').fetchall()
for r in row:
    print(r)
conn.close()
"
```

- [ ] **Step 3: No commit needed** (DB state, not code)

---

### Task 4: Parse epistemic_type from extractor output + confidence clamping

**Files:**
- Modify: `src/esbvaktin/pipeline/parse_outputs.py:118-163`
- Test: `tests/test_parse_outputs.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_parse_outputs.py — add new tests

def test_parse_claims_with_epistemic_type(tmp_path):
    """Claims with epistemic_type are parsed correctly."""
    claims_file = tmp_path / "_claims.json"
    claims_file.write_text(json.dumps([{
        "claim_text": "Test claim",
        "original_quote": "Test",
        "category": "fisheries",
        "claim_type": "statistic",
        "epistemic_type": "prediction",
        "confidence": 0.9,
    }]))
    claims = parse_claims(claims_file)
    assert claims[0].epistemic_type.value == "prediction"


def test_parse_claims_defaults_epistemic_type_to_factual(tmp_path):
    """Claims without epistemic_type default to factual."""
    claims_file = tmp_path / "_claims.json"
    claims_file.write_text(json.dumps([{
        "claim_text": "Test claim",
        "original_quote": "Test",
        "category": "fisheries",
        "claim_type": "statistic",
        "confidence": 0.9,
    }]))
    claims = parse_claims(claims_file)
    assert claims[0].epistemic_type.value == "factual"


def test_clamp_epistemic_confidence():
    """Prediction/counterfactual confidence clamped to 0.8."""
    from esbvaktin.pipeline.parse_outputs import clamp_epistemic_confidence
    from esbvaktin.pipeline.models import (
        Claim, ClaimType, EpistemicType, ClaimAssessment, Verdict,
    )

    claim = Claim(
        claim_text="Test",
        original_quote="Test",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        epistemic_type=EpistemicType.PREDICTION,
        confidence=0.95,
    )
    assessment = ClaimAssessment(
        claim=claim,
        verdict=Verdict.SUPPORTED,
        explanation="Test",
        confidence=0.95,
    )
    clamped = clamp_epistemic_confidence([assessment])
    assert clamped[0].confidence == 0.8
    assert clamped[0].claim.confidence == 0.8


def test_clamp_does_not_affect_factual():
    """Factual claims are not clamped."""
    from esbvaktin.pipeline.parse_outputs import clamp_epistemic_confidence
    from esbvaktin.pipeline.models import (
        Claim, ClaimType, EpistemicType, ClaimAssessment, Verdict,
    )

    claim = Claim(
        claim_text="Test",
        original_quote="Test",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        epistemic_type=EpistemicType.FACTUAL,
        confidence=0.95,
    )
    assessment = ClaimAssessment(
        claim=claim,
        verdict=Verdict.SUPPORTED,
        explanation="Test",
        confidence=0.95,
    )
    clamped = clamp_epistemic_confidence([assessment])
    assert clamped[0].confidence == 0.95


def test_normalise_assessment_preserves_epistemic_type():
    """_normalise_assessment preserves epistemic_type in flat format."""
    from esbvaktin.pipeline.parse_outputs import _normalise_assessment

    item = {
        "claim_text": "Test",
        "original_quote": "Test",
        "category": "fisheries",
        "claim_type": "statistic",
        "epistemic_type": "hearsay",
        "confidence": 0.5,
        "verdict": "unverifiable",
        "explanation": "Test",
        "supporting_evidence": [],
        "contradicting_evidence": [],
    }
    result = _normalise_assessment(item)
    assert result["claim"]["epistemic_type"] == "hearsay"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev python -m pytest tests/test_parse_outputs.py -k "epistemic" -v`
Expected: FAIL

- [ ] **Step 3: Implement changes in parse_outputs.py**

1. In `_normalise_assessment()`, add after the `speaker_name` preservation (line 143-144):
```python
        if "epistemic_type" in item:
            claim_dict["epistemic_type"] = item.pop("epistemic_type")
```

2. Add `clamp_epistemic_confidence()` function:
```python
_EPISTEMIC_CONFIDENCE_CEILING = 0.8
_CLAMPED_TYPES = {"prediction", "counterfactual"}


def clamp_epistemic_confidence(
    assessments: list[ClaimAssessment],
) -> list[ClaimAssessment]:
    """Clamp confidence for prediction/counterfactual claims to 0.8 ceiling."""
    result = []
    for a in assessments:
        if a.claim.epistemic_type in _CLAMPED_TYPES:
            clamped_claim = a.claim.model_copy(
                update={"confidence": min(a.claim.confidence, _EPISTEMIC_CONFIDENCE_CEILING)}
            )
            clamped = a.model_copy(update={
                "claim": clamped_claim,
                "confidence": min(a.confidence, _EPISTEMIC_CONFIDENCE_CEILING),
            })
            result.append(clamped)
        else:
            result.append(a)
    return result
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev python -m pytest tests/test_parse_outputs.py -k "epistemic" -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/esbvaktin/pipeline/parse_outputs.py tests/test_parse_outputs.py
git commit -m "feat: parse epistemic_type from extractor output, add confidence clamping"
```

---

### Task 5: Hearsay short-circuit in evidence retrieval

**Files:**
- Modify: `src/esbvaktin/pipeline/retrieve_evidence.py:124-140`
- Test: `tests/test_retrieve_evidence.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_retrieve_evidence.py — add new test

def test_hearsay_claims_short_circuit(monkeypatch):
    """Hearsay claims get auto-unverifiable without evidence retrieval."""
    from esbvaktin.pipeline.models import Claim, ClaimType, EpistemicType, Verdict
    from esbvaktin.pipeline.retrieve_evidence import retrieve_evidence_for_claims

    hearsay_claim = Claim(
        claim_text="Ónafngreindir segja X",
        original_quote="Test",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        epistemic_type=EpistemicType.HEARSAY,
        confidence=0.5,
    )
    factual_claim = Claim(
        claim_text="Útflutningur er 23%",
        original_quote="Test",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        epistemic_type=EpistemicType.FACTUAL,
        confidence=0.9,
    )

    # Mock evidence retrieval to track calls
    calls = []
    def mock_retrieve(claim, top_k=5, conn=None):
        calls.append(claim.claim_text)
        from esbvaktin.pipeline.models import ClaimWithEvidence
        return ClaimWithEvidence(claim=claim, evidence=[])

    monkeypatch.setattr(
        "esbvaktin.pipeline.retrieve_evidence.retrieve_evidence_for_claim",
        mock_retrieve,
    )
    # Mock claim bank to avoid DB
    monkeypatch.setattr(
        "esbvaktin.pipeline.retrieve_evidence.check_claim_bank",
        lambda claim, conn=None: None,
    )

    results, bank_matches, hearsay_assessments = retrieve_evidence_for_claims(
        [hearsay_claim, factual_claim],
        use_claim_bank=False,
    )

    # Hearsay should NOT trigger evidence retrieval
    assert len(calls) == 1
    assert calls[0] == "Útflutningur er 23%"

    # Hearsay should return pre-built assessment
    assert len(hearsay_assessments) == 1
    assert hearsay_assessments[0].verdict == Verdict.UNVERIFIABLE
    assert hearsay_assessments[0].confidence == 0.0

    # Factual claim should be in evidence results
    assert len(results) == 1
    assert results[0].claim.epistemic_type == EpistemicType.FACTUAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/test_retrieve_evidence.py::test_hearsay_claims_short_circuit -v`
Expected: FAIL

- [ ] **Step 3: Implement hearsay short-circuit**

Modify `retrieve_evidence_for_claims()` in `src/esbvaktin/pipeline/retrieve_evidence.py`:

1. Add import for `EpistemicType`, `ClaimAssessment`, `Verdict` at top
2. At the start of the function, separate hearsay claims:
```python
    # Short-circuit hearsay claims — no evidence retrieval needed
    hearsay_assessments: list[ClaimAssessment] = []
    non_hearsay_claims: list[Claim] = []
    for claim in claims:
        if claim.epistemic_type == EpistemicType.HEARSAY:
            hearsay_assessments.append(ClaimAssessment(
                claim=claim,
                verdict=Verdict.UNVERIFIABLE,
                explanation="Fullyrðingin byggir á ónafngreindum heimildum sem ekki er hægt að staðfesta.",
                supporting_evidence=[],
                contradicting_evidence=[],
                missing_context=None,
                confidence=0.0,
            ))
        else:
            non_hearsay_claims.append(claim)
```
3. Process only `non_hearsay_claims` through evidence retrieval
4. Update return type to include hearsay assessments: `tuple[list[ClaimWithEvidence], dict[int, ClaimBankMatch], list[ClaimAssessment]]`

- [ ] **Step 4: Run test**

Run: `uv run --extra dev python -m pytest tests/test_retrieve_evidence.py::test_hearsay_claims_short_circuit -v`
Expected: PASS

- [ ] **Step 5: Fix ALL callers of retrieve_evidence_for_claims**

The return type changed from 2-tuple to 3-tuple (added `hearsay_assessments`). All callers that unpack the return value will break:

- `scripts/pipeline/retrieve_evidence.py:66` — unpack 3 values, merge `hearsay_assessments` into the assessment list passed to the assessor context
- `scripts/fact_check_speeches.py:138` — unpack 3 values, merge hearsay assessments into final results
- `tests/test_retrieve_evidence.py:95` (`test_batch_retrieval`) — unpack 3 values
- `tests/test_retrieve_evidence.py:104` (`test_empty_list`) — unpack 3 values

**Important:** callers must merge `hearsay_assessments` back into the final assessment list before report assembly. Hearsay assessments skip the assessor agent but still need to appear in the report.

- [ ] **Step 6: Run full test suite**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/esbvaktin/pipeline/retrieve_evidence.py tests/test_retrieve_evidence.py
# Plus any caller fixes
git commit -m "feat: hearsay claims short-circuit before evidence retrieval"
```

---

### Task 6: Update extraction prompt with epistemic_type

**Files:**
- Modify: `src/esbvaktin/pipeline/prepare_context.py:120-174` (IS extraction prompt)
- Modify: `.claude/agents/claim-extractor.md`
- Test: `tests/test_prepare_context.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_prepare_context.py — add new test

def test_extraction_context_includes_epistemic_type(tmp_path):
    """Extraction context mentions epistemic_type field and valid values."""
    from esbvaktin.pipeline.prepare_context import prepare_extraction_context
    path = prepare_extraction_context(
        article_text="Test article about ESB",
        output_dir=tmp_path,
        language="is",
    )
    content = path.read_text()
    assert "epistemic_type" in content
    assert "factual" in content
    assert "hearsay" in content
    assert "counterfactual" in content
    assert "prediction" in content
    # claim_type should show forecast, not prediction
    assert "forecast" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/test_prepare_context.py::test_extraction_context_includes_epistemic_type -v`
Expected: FAIL

- [ ] **Step 3: Update extraction prompt in prepare_context.py**

In the Icelandic extraction template (around line 120-170):

1. Replace `prediction` with `forecast` in the `claim_type` list
2. Add `epistemic_type` field definition after `claim_type`:
```
   - `epistemic_type`: Eitt af: factual, hearsay, counterfactual, prediction
     - `factual`: Bein fullyrðing um heiminn (sjálfgefið)
     - `hearsay`: Byggt á ónafngreindum/óstaðfestanlegum heimildum ("að sögn", "fregnir herma")
     - `counterfactual`: Um fortíðina — andstætt því sem gerðist ("ef X hefði gerst...")
     - `prediction`: Um framtíðina, þ.m.t. skilyrtar spár ("ef aðild næðist myndi...")
     Athugið: Nafngreind heimild á opinberum vettvangi er `factual`, ekki hearsay.
```
3. Add `"epistemic_type": "..."` to the JSON output template
4. Add disambiguation note:
```
   Munur á `claim_type` og `epistemic_type`: `claim_type` lýsir FORMI fullyrðingarinnar
   (tala, lagaleg staðhæfing, samanburður, spá, skoðun). `epistemic_type` lýsir ÞEKKINGAR-
   STÖÐUNNI (staðfestanleg staðreynd, orðsögn, tilgáta um fortíð, spá um framtíð).
```

**All 6 prompt locations in `prepare_context.py` need these changes:**
- Line ~128 (IS article extraction)
- Line ~192 (EN article extraction)
- Line ~913 (IS speech extraction)
- Line ~987 (EN speech extraction)
- Line ~1119 (IS panel extraction)
- Line ~1195 (EN panel extraction)

Each needs: `prediction` → `forecast` in claim_type list, `epistemic_type` added to field definitions, `"epistemic_type": "..."` in JSON output template, and the disambiguation note.

- [ ] **Step 4: Update claim-extractor agent prompt**

In `.claude/agents/claim-extractor.md`, update the quality checklist (line 33-35):
- Change `prediction` to `forecast` in valid claim_type values
- Add: `6. Tegundir þekkingarstöðu eru gildar: factual, hearsay, counterfactual, prediction`

- [ ] **Step 5: Run test**

Run: `uv run --extra dev python -m pytest tests/test_prepare_context.py::test_extraction_context_includes_epistemic_type -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/esbvaktin/pipeline/prepare_context.py .claude/agents/claim-extractor.md tests/test_prepare_context.py
git commit -m "feat: extraction prompt includes epistemic_type field and heuristics"
```

---

### Task 7: Update assessment prompt with reasoning-based rules

**Files:**
- Modify: `src/esbvaktin/pipeline/prepare_context.py:250-370` (assessment context)
- Modify: `.claude/agents/claim-assessor.md`
- Test: `tests/test_prepare_context.py`

- [ ] **Step 1: Write failing test**

```python
def test_assessment_context_includes_epistemic_rules(tmp_path):
    """Assessment context includes reasoning-based rules for predictions."""
    from esbvaktin.pipeline.models import (
        Claim, ClaimType, EpistemicType, ClaimWithEvidence,
    )
    from esbvaktin.pipeline.prepare_context import prepare_assessment_context

    claim = Claim(
        claim_text="Ef aðild næðist myndi matvælaverð lækka",
        original_quote="Test",
        category="trade",
        claim_type=ClaimType.FORECAST,
        epistemic_type=EpistemicType.PREDICTION,
        confidence=0.7,
    )
    cwe = ClaimWithEvidence(claim=claim, evidence=[])
    path = prepare_assessment_context([cwe], tmp_path, language="is")
    content = path.read_text()
    assert "epistemic_type" in content
    assert "prediction" in content
    # Should contain reasoning-based assessment instructions
    assert "Heimildasamstaða" in content or "samstaða" in content.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/test_prepare_context.py::test_assessment_context_includes_epistemic_rules -v`
Expected: FAIL

- [ ] **Step 3: Update assessment context in prepare_context.py**

1. In `prepare_assessment_context()`, add `epistemic_type` to per-claim display:
```python
- **Þekkingarstaða**: {claim.epistemic_type.value}
```

2. Add a new section after the verdict definitions (around line 340):
```python
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
```

3. Update `claim_type` references: `prediction` → `forecast`

- [ ] **Step 4: Update claim-assessor agent prompt**

In `.claude/agents/claim-assessor.md`, add the reasoning-based rules after the existing quality checklist.

- [ ] **Step 5: Run test**

Run: `uv run --extra dev python -m pytest tests/test_prepare_context.py::test_assessment_context_includes_epistemic_rules -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/esbvaktin/pipeline/prepare_context.py .claude/agents/claim-assessor.md tests/test_prepare_context.py
git commit -m "feat: assessment prompt includes reasoning-based rules for predictions/counterfactuals"
```

---

### Task 8: Update sighting registration (all three paths)

**Files:**
- Modify: `src/esbvaktin/pipeline/register_sightings.py`
- Modify: `src/esbvaktin/speeches/register_sightings.py`
- Modify: `scripts/register_article_sightings.py`
- Test: `tests/test_panel_sightings.py`, `tests/test_speech_context.py`

- [ ] **Step 1: Write failing test for hearsay gating in sighting registration**

```python
# tests/test_panel_sightings.py — add new test

def test_hearsay_claim_registered_as_unpublished(monkeypatch):
    """Hearsay claims are registered with published=False, substantive=False."""
    from esbvaktin.pipeline.models import (
        Claim, ClaimType, EpistemicType, ClaimAssessment, Verdict,
    )
    from esbvaktin.claim_bank.models import CanonicalClaim

    captured_claims = []
    def mock_add_claim(claim, conn=None):
        captured_claims.append(claim)
        return 1

    monkeypatch.setattr("esbvaktin.pipeline.register_sightings.add_claim", mock_add_claim)
    # ... set up hearsay assessment and call registration
    # Assert: captured_claims[0].published is False
    # Assert: captured_claims[0].epistemic_type == "hearsay"
```

- [ ] **Step 2: Update panel show sighting registration**

In `src/esbvaktin/pipeline/register_sightings.py`, find where `CanonicalClaim` is constructed and add `epistemic_type=assessment.claim.epistemic_type.value`.

- [ ] **Step 2: Update speech sighting registration**

In `src/esbvaktin/speeches/register_sightings.py`, same change.

- [ ] **Step 3: Update article sighting registration**

In `scripts/register_article_sightings.py`, find where `CanonicalClaim` is constructed. Add `epistemic_type=claim_data.get("epistemic_type", "factual")`.

Also add hearsay gate: if `epistemic_type == "hearsay"`, set `published=False` and `verdict="unverifiable"`.

- [ ] **Step 4: Run relevant tests**

Run: `uv run --extra dev python -m pytest tests/test_panel_sightings.py tests/test_speech_context.py -v`
Expected: All pass

- [ ] **Step 5: Run full test suite**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/esbvaktin/pipeline/register_sightings.py src/esbvaktin/speeches/register_sightings.py scripts/register_article_sightings.py
git commit -m "feat: pass epistemic_type through all three sighting registration paths"
```

---

### Task 9: Update export pipeline

**Files:**
- Modify: `scripts/export_claims.py`
- Modify: `scripts/export_topics.py`
- Modify: `scripts/prepare_site.py`
- Modify: `src/esbvaktin/pipeline/assemble_report.py`

- [ ] **Step 1: Update export_claims.py**

Add `epistemic_type` to the SELECT query and include it in the Parquet schema and JSON output.

- [ ] **Step 2: Update export_topics.py**

Add epistemic type distribution per topic: count claims by `epistemic_type` alongside the existing verdict breakdown.

- [ ] **Step 3: Update prepare_site.py**

Add `epistemic_type` to `_load_db_verdicts()` SELECT and pass it through to report JSON.

- [ ] **Step 4: Update assemble_report.py**

Add nested verdict labels. Create a `_verdict_label_for_epistemic()` function or modify `_verdict_label()` to accept epistemic type.

- [ ] **Step 5: Run full test suite**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add scripts/export_claims.py scripts/export_topics.py scripts/prepare_site.py src/esbvaktin/pipeline/assemble_report.py
git commit -m "feat: include epistemic_type in export pipeline and report assembly"
```

---

### Task 10: Update audit and reassessment scripts

**Files:**
- Modify: `scripts/reassess_claims.py`
- Modify: `scripts/audit_claims.py`

- [ ] **Step 1: Update reassess_claims.py**

1. In `_search_evidence_dual()` or the prepare step, skip claims where `epistemic_type = 'hearsay'`
2. After parsing reassessment output, apply confidence ceiling for prediction/counterfactual
3. Update valid `claim_type` values in any prompt text: `prediction` → `forecast`

- [ ] **Step 2: Update audit_claims.py**

Exclude hearsay claims from all audit patterns (they're unverifiable by definition, no audit needed).

Add `WHERE epistemic_type != 'hearsay'` to relevant queries.

- [ ] **Step 3: Run full test suite**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add scripts/reassess_claims.py scripts/audit_claims.py
git commit -m "feat: skip hearsay in reassessment and audit, add confidence ceiling"
```

---

### Task 11: Create backfill script

**Files:**
- Create: `scripts/backfill_epistemic_type.py`

- [ ] **Step 1: Write the backfill script**

The script has two subcommands:

`classify` — Phase 1: Pull claims in batches of 30, write context files for sonnet agent to classify `epistemic_type`. Parse output and update DB.

`correct` — Phase 2: Find hearsay claims with non-unverifiable verdicts. Automatically correct to unverifiable, published=False, substantive=False.

`status` — Show current epistemic type distribution.

Follow the same pattern as `scripts/reassess_claims.py` for batch context generation and subagent invocation.

Key details:
- `classify` and `correct` run atomically when called together (`backfill_epistemic_type.py run`)
- Phase 2 only runs after Phase 1 completes
- `status` can be called independently

- [ ] **Step 2: Test status subcommand**

```bash
uv run python scripts/backfill_epistemic_type.py status
```

Expected: Shows all claims as `factual` (pre-backfill state).

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_epistemic_type.py
git commit -m "feat: add backfill script for epistemic type classification"
```

---

### Task 12: Update site taxonomy and claim tracker

**Files:**
- Modify: `~/esbvaktin-site/assets/js/site-taxonomy.js`
- Modify: Claim tracker JS + CSS (in esbvaktin-site)

- [ ] **Step 1: Update site-taxonomy.js**

Replace flat `verdictLabels` with nested lookup by epistemic type. Add `epistemicTypeLabels` object. See spec for exact values.

Ensure backward compatibility: if code accesses `verdictLabels.supported` directly (flat lookup), add a compatibility shim or update all callers to use `verdictLabels[epistemicType].verdict`.

- [ ] **Step 2: Update claim tracker**

Add epistemic type filter buttons, secondary badges, and nested label lookup. Update CSS for badge colours.

- [ ] **Step 3: Test locally**

```bash
cd ~/esbvaktin-site && npm run build && npm start
```

Verify claim tracker page renders, filters work, badges display.

- [ ] **Step 4: Commit (in site repo)**

```bash
cd ~/esbvaktin-site
git add assets/js/site-taxonomy.js
# Plus claim tracker files
git commit -m "feat: epistemic type filters, badges, and nested verdict labels"
```

---

### Task 13: Run backfill and verify

**Files:** None (operational step)

- [ ] **Step 1: Run backfill classification**

```bash
uv run python scripts/backfill_epistemic_type.py classify
```

Review output — spot-check a sample of classifications.

- [ ] **Step 2: Run hearsay correction**

```bash
uv run python scripts/backfill_epistemic_type.py correct
```

Note how many claims were corrected.

- [ ] **Step 3: Verify distribution**

```bash
uv run python scripts/backfill_epistemic_type.py status
```

Expected: ~70% factual, ~20% prediction, ~5% counterfactual, ~5% hearsay.

- [ ] **Step 4: Run export to verify end-to-end**

```bash
uv run python scripts/export_claims.py --site-dir ~/esbvaktin-site
```

Verify `epistemic_type` appears in the exported JSON/Parquet.

- [ ] **Step 5: Run full test suite one final time**

Run: `uv run --extra dev python -m pytest tests/ -v`
Expected: All pass
