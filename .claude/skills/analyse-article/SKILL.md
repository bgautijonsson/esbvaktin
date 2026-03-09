# Analyse Article

Analyse an article about Iceland's EU membership referendum against the Ground Truth Database.
Pipeline is **Icelandic-first**: subagents extract, assess, and write in Icelandic. No translation step.

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
    language='is',
)
print('Extraction context prepared (Icelandic).')
"
```

### Step 2: Extract Claims (Subagent)

Launch a subagent to extract claims from the article:

**Subagent task:** Read `$WORK_DIR/_context_extraction.md` and follow its instructions. Write the output (a JSON array of claims) to `$WORK_DIR/_claims.json`.

The subagent should:
1. Read the context file carefully (instructions are in Icelandic)
2. Extract ALL factual claims from the article
3. Write `claim_text` in Icelandic
4. Write a JSON array to `_claims.json` (raw JSON, no markdown wrapping)

**Critical principles for the subagent:**
- Be thorough — extract every factual claim, not just obvious ones
- Categorise accurately using the known topics: fisheries, trade, sovereignty, eea_eu_law, agriculture, precedents, currency, labour, polling, party_positions, org_positions, other
- Distinguish between claim types: statistic, legal_assertion, comparison, prediction, opinion
- Preserve exact quotes from the article in `original_quote`
- Write `claim_text` in clear Icelandic
- **JSON safety**: escape any quotation marks inside string values. Icelandic „…" quotes must be written as `\"…\"` in JSON. Never use raw `„` or `"` inside JSON strings.
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

claims_with_evidence, bank_matches = retrieve_evidence_for_claims(claims, top_k=5)
print(f'Retrieved evidence for {len(claims_with_evidence)} claims.')
if bank_matches:
    print(f'Claim bank matches: {len(bank_matches)} (cache hits speed up assessment)')

article_text = (work_dir / '_article.md').read_text()
prepare_assessment_context(claims_with_evidence, work_dir, language='is')
prepare_omission_context(article_text, claims_with_evidence, work_dir, language='is')
print('Assessment and omission contexts prepared (Icelandic).')
"
```

### Step 4: Assess Claims (Subagent)

Launch a subagent to assess each claim against evidence:

**Subagent task:** Read `$WORK_DIR/_context_assessment.md` and follow its instructions. Write the output (a JSON array of assessments) to `$WORK_DIR/_assessments.json`.

**Critical principles for the subagent:**
- **Óhlutdrægni**: Metið ESB-jákvæðar og ESB-neikvæðar fullyrðingar jafnt. Never take a side.
- **Heimildum háð**: every assessment MUST cite specific evidence_ids from the Ground Truth DB
- **Fyrirvarar skipta máli**: always surface caveats from evidence entries — they often contain crucial qualifications
- **Auðmýkt**: if evidence is insufficient, use "unverifiable" — do not guess
- Write `explanation` and `missing_context` fields in **Icelandic**
- **JSON safety**: escape Icelandic quotation marks „…" as `\"…\"` in all JSON string values
- Write raw JSON, no markdown wrapping

### Step 5: Analyse Omissions (Subagent — can run in parallel with Step 4)

Launch a subagent to identify omissions and assess framing:

**Subagent task:** Read `$WORK_DIR/_context_omissions.md` and follow its instructions. Write the output (a JSON object) to `$WORK_DIR/_omissions.json`.

**Critical principles for the subagent:**
- Balance: an article can legitimately argue one side; omission analysis is about what **relevant facts** are missing
- Only flag omissions that would **materially change** a reader's understanding
- Reference specific evidence_ids for each omission
- Write `description` fields in **Icelandic**
- **JSON safety**: escape Icelandic quotation marks „…" as `\"…\"` in all JSON string values
- Write raw JSON, no markdown wrapping

### Step 6: Assemble Icelandic Report (Python)

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
from collections import Counter
vc = Counter(verdicts)

# Icelandic summary
verdict_names = {
    'supported': 'stutt af heimildum',
    'partially_supported': 'stutt að hluta',
    'unsupported': 'ekki stutt',
    'misleading': 'villandi',
    'unverifiable': 'ekki hægt að sannreyna',
}
parts = [f'{count} {verdict_names.get(v, v)}' for v, count in vc.most_common()]
summary = f'Greindar {len(assessments)} fullyrðingar. '
summary += 'Niðurstöður: ' + ', '.join(parts) + '. '

framing_names = {
    'balanced': 'jafnvæg',
    'leans_pro_eu': 'hallar á ESB-jákvæða hlið',
    'leans_anti_eu': 'hallar á ESB-neikvæða hlið',
    'strongly_pro_eu': 'mjög ESB-jákvæð',
    'strongly_anti_eu': 'mjög ESB-neikvæð',
    'neutral_but_incomplete': 'hlutlaus en ófullnægjandi',
}
framing = framing_names.get(omissions.framing_assessment.value, omissions.framing_assessment.value)
summary += f'Sjónarhorn: {framing}. '
summary += f'Heildstæðni: {omissions.overall_completeness:.0%}.'

report = assemble_report(
    claims=assessments,
    omissions=omissions,
    summary=summary,
    article_title=None,  # Set from metadata if available
    language='is',
)

(work_dir / '_report_is.md').write_text(report.report_text_is)
(work_dir / '_report.json').write_text(report.model_dump_json(indent=2))
print('Icelandic report assembled.')
print()
print(report.report_text_is[:500])
"
```

### Step 7: Finalise + GreynirCorrect (Python)

```bash
uv run python -c "
import json
from pathlib import Path

work_dir = Path('$WORK_DIR')

# Read report
report_data = json.loads((work_dir / '_report.json').read_text())

# Try GreynirCorrect if available
report_is = report_data.get('report_text_is', '')
try:
    from reynir_correct import check_single
    # Light correction pass — only fix obvious errors
    lines = report_is.split('\n')
    corrected = []
    for line in lines:
        if line.startswith('#') or line.startswith('*') or line.startswith('-') or line.startswith('>') or line.startswith('|'):
            corrected.append(line)
        elif line.strip():
            result = check_single(line)
            corrected.append(str(result))
        else:
            corrected.append(line)
    report_data['report_text_is'] = '\n'.join(corrected)
    (work_dir / '_report_is.md').write_text('\n'.join(corrected))
    print('GreynirCorrect applied.')
except ImportError:
    print('GreynirCorrect not available — skipping correction.')

# Write final report
(work_dir / '_report_final.json').write_text(json.dumps(report_data, indent=2, ensure_ascii=False, default=str))
print(f'Final report written to {work_dir}/_report_final.json')
print()

# Print summary
print('=== GREINING LOKIÐ ===')
print(f'Vinnusvæði: {work_dir}')
print(f'Yfirlit: {report_data[\"summary\"]}')
print(f'Fullyrðingar metnar: {len(report_data[\"claims\"])}')
print(f'Heimildir notaðar: {len(report_data[\"evidence_used\"])} færslur')
print(f'Íslensk skýrsla: {work_dir}/_report_is.md')
"
```

### Step 7b (Optional): Generate English Report

Only if English report is explicitly requested:

```bash
uv run python -c "
from pathlib import Path
from esbvaktin.pipeline.prepare_context import prepare_translation_context

work_dir = Path('$WORK_DIR')
report_is = (work_dir / '_report_is.md').read_text()
prepare_translation_context(report_is, work_dir, direction='is_to_en')
print('Translation context prepared (IS → EN).')
"
```

Then launch a subagent to translate Icelandic → English:

**Subagent task:** Read `$WORK_DIR/_context_translation.md` and translate to English. Write to `$WORK_DIR/_report_en.md`.

### Step 8: Export to Obsidian

Always export the final report to the ESB Obsidian vault using the MCP `write_note` tool:

- **Path:** `Reports/YYYY-MM-DD — Article Title.md`
- **Frontmatter:** Include `type: article-analysis`, `date`, `source`, `author`, `url`, `claims` (count), `verdicts` (breakdown), `framing`, `completeness`, `evidence_used` (count), `analysis_dir`, and `tags`
- **Formatting:** Add a `> [!tip] Lykilniðurstaða` callout after the summary highlighting the most important finding. Use a `> [!warning]` callout for the omissions section. Add `[[ESBvaktin]]` wikilink in the footer.
- **Tags:** Include `greining` plus topic-specific tags (e.g. `landbúnaður`, `sjávarútvegur`, `skoðanakannanir`)

Print a brief confirmation to terminal with the vault path.

## Files Produced

| File | Description |
|------|-------------|
| `_article.md` | Raw article text |
| `_context_extraction.md` | Context for claim extraction subagent (Icelandic) |
| `_claims.json` | Extracted claims (Icelandic claim_text) |
| `_context_assessment.md` | Context for claim assessment subagent (Icelandic) |
| `_context_omissions.md` | Context for omission analysis subagent (Icelandic) |
| `_assessments.json` | Claim assessments (Icelandic explanations) |
| `_omissions.json` | Omission analysis (Icelandic descriptions) |
| `_report_is.md` | Icelandic report — primary output |
| `_report.json` | Structured report (JSON) |
| `_report_final.json` | Final complete report (JSON) |
| `_report_en.md` | English report (optional, Step 7b) |
