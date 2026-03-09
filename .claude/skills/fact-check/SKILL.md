# Fact-Check

Quick fact-check of one or more claims about Iceland's EU membership against the Ground Truth Database. Lighter alternative to `/analyse-article` — no article extraction, omission analysis, or translation.

## Usage

```
/fact-check <claim text>
/fact-check "Claim one" "Claim two"
```

## Steps

### Step 1: Build Claims and Retrieve Evidence (Python)

Parse the user's input into Claim objects, retrieve evidence, and prepare context for assessment.

For each claim provided, infer the most likely `category` from the text (fisheries, trade, sovereignty, eea_eu_law, agriculture, precedents, currency, labour, housing, polling, party_positions, org_positions, or other) and `claim_type` (statistic, legal_assertion, comparison, prediction, opinion).

```bash
ANALYSIS_ID=$(date +%Y%m%d_%H%M%S)_fc
WORK_DIR="data/analyses/${ANALYSIS_ID}"
mkdir -p "$WORK_DIR"
```

```bash
uv run python -c "
import json
from pathlib import Path
from esbvaktin.pipeline.models import Claim, ClaimType
from esbvaktin.pipeline.retrieve_evidence import retrieve_evidence_for_claims
from esbvaktin.pipeline.prepare_fact_check import prepare_fact_check_context

# Claims from user input — edit this list as needed
claims_raw = [
    {'claim_text': '<CLAIM_TEXT>', 'original_quote': '<CLAIM_TEXT>', 'category': '<CATEGORY>', 'claim_type': '<TYPE>', 'confidence': 0.9},
]
claims = [Claim.model_validate(c) for c in claims_raw]
print(f'Checking {len(claims)} claim(s)...')

claims_with_evidence = retrieve_evidence_for_claims(claims, top_k=5)
for cwe in claims_with_evidence:
    print(f'  {cwe.claim.claim_text[:60]}... — {len(cwe.evidence)} evidence matches')

work_dir = Path('$WORK_DIR')
ctx_path = prepare_fact_check_context(claims_with_evidence, work_dir)
print(f'Context written to {ctx_path}')
"
```

### Step 2: Assess Claims (Subagent)

Launch a subagent to assess the claims against evidence:

**Subagent task:** Read `$WORK_DIR/_context_fact_check.md` and follow its instructions. Write the output (a JSON array of assessments) to `$WORK_DIR/_assessments.json`.

**Critical principles for the subagent:**
- **Independence and balance**: assess pro-EU and anti-EU claims with equal rigour
- **Evidence-based**: every verdict MUST cite specific evidence_ids
- **Caveats matter**: always surface caveats from evidence entries
- **Humility**: if evidence is insufficient, use `unverifiable`
- Write raw JSON, no markdown wrapping

### Step 3: Parse and Display Results (Python)

```bash
uv run python -c "
from pathlib import Path
from esbvaktin.pipeline.parse_outputs import parse_assessments

work_dir = Path('$WORK_DIR')
assessments = parse_assessments(work_dir / '_assessments.json')

verdict_labels = {
    'supported': '✅ Supported',
    'partially_supported': '⚠️  Partially Supported',
    'unsupported': '❌ Unsupported',
    'misleading': '🔍 Misleading',
    'unverifiable': '❓ Unverifiable',
}

for i, a in enumerate(assessments, 1):
    label = verdict_labels.get(a.verdict.value, a.verdict.value)
    print(f'### Claim {i}: {label}')
    print(f'> {a.claim.claim_text}')
    print()
    print(a.explanation)
    print()
    if a.supporting_evidence:
        print(f'Supporting: {', '.join(a.supporting_evidence)}')
    if a.contradicting_evidence:
        print(f'Contradicting: {', '.join(a.contradicting_evidence)}')
    if a.missing_context:
        print(f'Missing context: {a.missing_context}')
    print(f'Confidence: {a.confidence:.0%}')
    print()
"
```

Print results directly to the terminal — this is a quick check, not a full report.

## Files Produced

| File | Description |
|------|-------------|
| `_context_fact_check.md` | Context for assessment subagent |
| `_assessments.json` | Claim assessments (JSON) |
