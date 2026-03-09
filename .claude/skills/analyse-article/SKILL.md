# Analyse Article

Analyse an article about Iceland's EU membership referendum against the Ground Truth Database.

## Usage

```
/analyse-article <url|file_path|"pasted text">
```

## Steps

### Step 1: Prepare Working Directory

```bash
ANALYSIS_ID=$(date +%Y%m%d_%H%M%S)
WORK_DIR="data/analyses/${ANALYSIS_ID}"
mkdir -p "$WORK_DIR"
```

Get the article text:
- If a **URL** is provided: use `uv run python -c "import trafilatura; print(trafilatura.fetch_url('URL'))" | uv run python -c "import trafilatura, sys; print(trafilatura.extract(sys.stdin.read()))"` as a fallback. Prefer fréttasafn MCP if available.
- If a **file path** is provided: read the file
- If **pasted text** is provided: use it directly

Write the article text to `$WORK_DIR/_article.md`.

Then run the context preparation:

```bash
uv run python -c "
from pathlib import Path
from esbvaktin.pipeline.prepare_context import prepare_extraction_context

article = Path('$WORK_DIR/_article.md').read_text()
prepare_extraction_context(
    article_text=article,
    output_dir=Path('$WORK_DIR'),
    metadata={'title': None, 'source': None, 'date': None},
)
print('Extraction context prepared.')
"
```

### Step 2: Extract Claims (Subagent)

Launch a subagent to extract claims from the article:

**Subagent task:** Read `$WORK_DIR/_context_extraction.md` and follow its instructions. Write the output (a JSON array of claims) to `$WORK_DIR/_claims.json`.

The subagent should:
1. Read the context file carefully
2. Extract ALL factual claims from the article
3. Write a JSON array to `_claims.json` (raw JSON, no markdown wrapping)

**Critical principles for the subagent:**
- Be thorough — extract every factual claim, not just obvious ones
- Categorise accurately using the known topics: fisheries, trade, sovereignty, eea_eu_law, agriculture, precedents, currency, labour, polling, party_positions, org_positions, other
- Distinguish between claim types: statistic, legal_assertion, comparison, prediction, opinion
- Preserve exact quotes from the article
- Independence: do not favour either side

### Step 3: Retrieve Evidence and Prepare Assessment Context (Python)

```bash
uv run python -c "
from pathlib import Path
from esbvaktin.pipeline.parse_outputs import parse_claims
from esbvaktin.pipeline.retrieve_evidence import retrieve_evidence_for_claims
from esbvaktin.pipeline.prepare_context import prepare_assessment_context, prepare_omission_context

work_dir = Path('$WORK_DIR')
claims = parse_claims(work_dir / '_claims.json')
print(f'Parsed {len(claims)} claims.')

claims_with_evidence = retrieve_evidence_for_claims(claims, top_k=5)
print(f'Retrieved evidence for {len(claims_with_evidence)} claims.')

article_text = (work_dir / '_article.md').read_text()
prepare_assessment_context(claims_with_evidence, work_dir)
prepare_omission_context(article_text, claims_with_evidence, work_dir)
print('Assessment and omission contexts prepared.')
"
```

### Step 4: Assess Claims (Subagent)

Launch a subagent to assess each claim against evidence:

**Subagent task:** Read `$WORK_DIR/_context_assessment.md` and follow its instructions. Write the output (a JSON array of assessments) to `$WORK_DIR/_assessments.json`.

**Critical principles for the subagent:**
- **Independence and balance**: assess pro-EU and anti-EU claims with equal rigour. Never take a side.
- **Evidence-based**: every assessment MUST cite specific evidence_ids from the Ground Truth DB
- **Caveats matter**: always surface the caveats from evidence entries — they often contain crucial qualifications
- **Humility**: if evidence is insufficient, use "unverifiable" — do not guess
- Write raw JSON, no markdown wrapping

### Step 5: Analyse Omissions (Subagent — can run in parallel with Step 4)

Launch a subagent to identify omissions and assess framing:

**Subagent task:** Read `$WORK_DIR/_context_omissions.md` and follow its instructions. Write the output (a JSON object) to `$WORK_DIR/_omissions.json`.

**Critical principles for the subagent:**
- Balance: an article can legitimately argue one side; omission analysis is about what **relevant facts** are missing
- Only flag omissions that would **materially change** a reader's understanding
- Reference specific evidence_ids for each omission
- Write raw JSON, no markdown wrapping

### Step 6: Assemble English Report (Python)

```bash
uv run python -c "
import json
from pathlib import Path
from esbvaktin.pipeline.parse_outputs import parse_assessments, parse_omissions
from esbvaktin.pipeline.assemble_report import assemble_report

work_dir = Path('$WORK_DIR')
assessments = parse_assessments(work_dir / '_assessments.json')
omissions = parse_omissions(work_dir / '_omissions.json')

# Generate summary from assessments
verdicts = [a.verdict.value for a in assessments]
summary = f'Analysed {len(assessments)} claims. '
from collections import Counter
vc = Counter(verdicts)
parts = [f'{count} {verdict}' for verdict, count in vc.most_common()]
summary += 'Verdicts: ' + ', '.join(parts) + '. '
summary += f'Framing: {omissions.framing_assessment.value}. '
summary += f'Completeness: {omissions.overall_completeness:.0%}.'

report = assemble_report(
    claims=assessments,
    omissions=omissions,
    summary=summary,
    article_title=None,  # Set from metadata if available
)

(work_dir / '_report_en.md').write_text(report.report_text_en)
(work_dir / '_report.json').write_text(report.model_dump_json(indent=2))
print('English report assembled.')
print()
print(report.report_text_en[:500])
"
```

### Step 7: Translate to Icelandic (Subagent)

First prepare translation context:

```bash
uv run python -c "
from pathlib import Path
from esbvaktin.pipeline.prepare_context import prepare_translation_context

work_dir = Path('$WORK_DIR')
report_en = (work_dir / '_report_en.md').read_text()
prepare_translation_context(report_en, work_dir)
print('Translation context prepared.')
"
```

Then launch a subagent:

**Subagent task:** Read `$WORK_DIR/_context_translation.md` and follow its instructions. Write the translated Icelandic report to `$WORK_DIR/_report_is.md`.

**Translation guidelines:**
- Use formal but accessible Icelandic
- Preserve all evidence IDs as-is
- Follow Icelandic terminology conventions from the context file
- Translate verdict names with both Icelandic and English: "Stutt af heimildum (supported)"
- Do NOT translate source names or URLs

### Step 8: Finalise (Python)

```bash
uv run python -c "
import json
from pathlib import Path

work_dir = Path('$WORK_DIR')

# Read existing report
report_data = json.loads((work_dir / '_report.json').read_text())

# Add Icelandic translation
report_is = (work_dir / '_report_is.md').read_text()
report_data['report_text_is'] = report_is

# Try GreynirCorrect if available
try:
    from reynir_correct import check_single
    # Light correction pass — only fix obvious errors
    lines = report_is.split('\n')
    corrected = []
    for line in lines:
        if line.startswith('#') or line.startswith('*') or line.startswith('-') or line.startswith('>'):
            corrected.append(line)
        elif line.strip():
            result = check_single(line)
            corrected.append(str(result))
        else:
            corrected.append(line)
    report_data['report_text_is'] = '\n'.join(corrected)
    print('GreynirCorrect applied.')
except ImportError:
    print('GreynirCorrect not available — skipping correction.')

# Write final report
(work_dir / '_report_final.json').write_text(json.dumps(report_data, indent=2, ensure_ascii=False, default=str))
print(f'Final report written to {work_dir}/_report_final.json')
print()

# Print summary
print('=== ANALYSIS COMPLETE ===')
print(f'Working directory: {work_dir}')
print(f'Summary: {report_data[\"summary\"]}')
print(f'Claims assessed: {len(report_data[\"claims\"])}')
print(f'Evidence used: {len(report_data[\"evidence_used\"])} entries')
print(f'English report: {work_dir}/_report_en.md')
print(f'Icelandic report: {work_dir}/_report_is.md')
"
```

## Files Produced

| File | Description |
|------|-------------|
| `_article.md` | Raw article text |
| `_context_extraction.md` | Context for claim extraction subagent |
| `_claims.json` | Extracted claims |
| `_context_assessment.md` | Context for claim assessment subagent |
| `_context_omissions.md` | Context for omission analysis subagent |
| `_assessments.json` | Claim assessments |
| `_omissions.json` | Omission analysis |
| `_report_en.md` | English report (markdown) |
| `_report.json` | Structured report (JSON) |
| `_context_translation.md` | Context for translation subagent |
| `_report_is.md` | Icelandic report (markdown) |
| `_report_final.json` | Final complete report (JSON) |
