# Analyse Article

Analyse an article about Iceland's EU membership referendum against the Ground Truth Database.
Pipeline is **Icelandic-first**: subagents extract, assess, and write in Icelandic. No translation step.

Supports both **articles** and **panel show transcripts** (e.g. Silfrið). Panel shows are auto-detected from fréttasafn source or transcript format.

## Usage

```
/analyse-article <url|file_path|"pasted text"|fréttasafn_article_id>
```

## Steps

### Step 0: Dedup Check

Before creating a working directory, check if this article has already been analysed:

```bash
# Check by URL, title, or fréttasafn ID (whichever is available)
uv run python scripts/check_duplicate.py --url "ARTICLE_URL" --title "ARTICLE_TITLE"
```

If the script exits with code 0 (duplicate found), **stop and inform the user**. Show which analysis directory already contains this article. Only proceed if the user explicitly requests re-analysis.

### Step 0a: Inbox Integration (optional)

If the article URL matches an inbox entry, update its status to `analysing`:
```bash
uv run python scripts/manage_inbox.py set-status <inbox_id> analysing
```

If the inbox entry has cached text (`has_text: true`), the text is at `data/inbox/texts/<inbox_id>.md` — use it in Step 1 instead of re-fetching.

### Step 0b: Panel Show Fast Path (optional)

If the input is a **fréttasafn article ID** for a panel show, use the fetch script to bypass MCP token limits:

```bash
uv run python scripts/fetch_panel_transcript.py <article_id> [--name NAME]
```

This creates a `panel_*` work directory with `_article.md` already written. Set `WORK_DIR` to the printed path and **skip to Step 1b** (panel detection).

### Step 1: Prepare Working Directory

```bash
ANALYSIS_ID=$(date +%Y%m%d_%H%M%S)
WORK_DIR="data/analyses/${ANALYSIS_ID}"
mkdir -p "$WORK_DIR"
```

Get the article text:
- If a **fréttasafn article ID** is provided: fetch via `get_article` MCP tool
- If a **URL** is provided: use `uv run python -c "import trafilatura; print(trafilatura.fetch_url('URL'))" | uv run python -c "import trafilatura, sys; print(trafilatura.extract(sys.stdin.read()))"` as a fallback. Prefer fréttasafn MCP if available.
- If a **file path** is provided: read the file
- If **pasted text** is provided: use it directly

Write the article text to `$WORK_DIR/_article.md`.

### Step 1b: Detect Panel Show and Prepare Extraction Context

Detect if this is a panel show transcript. Check for:
- Fréttasafn source is `silfrid`, `kastljos`, or similar panel show source
- Text contains multiple `Speaker Name (role):` patterns with different speakers
- Text has `**Source:** Silfrið` or similar panel show header

**If panel show detected:**

```bash
uv run python -c "
from pathlib import Path
from esbvaktin.pipeline.transcript import parse_transcript
from esbvaktin.pipeline.prepare_context import prepare_panel_extraction_context

work_dir = Path('$WORK_DIR')
article = (work_dir / '_article.md').read_text()
transcript = parse_transcript(article)

prepare_panel_extraction_context(transcript, work_dir, language='is')
print(f'Panel show detected: {transcript.show_name}')
print(f'Participants: {len(transcript.participants)}')
for p in transcript.participants:
    print(f'  - {p[\"name\"]} ({p[\"role\"]})')
print(f'Moderator turns: {sum(1 for t in transcript.turns if t.is_moderator)}')
print(f'Total word count: {transcript.word_count}')
print('Panel extraction context prepared (Icelandic).')
"
```

**If regular article:**

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

### Step 2: Extract Claims (Agent: `claim-extractor`)

Use the **claim-extractor** agent to extract claims from the article:

```
Agent: claim-extractor
Prompt: Read $WORK_DIR/_context_extraction.md and extract all factual claims.
        Write the JSON array to $WORK_DIR/_claims.json.
```

**Verify output:** Check that `$WORK_DIR/_claims.json` exists after the agent completes. If missing, resume the agent with: "You MUST use the Write tool to write the JSON array to $WORK_DIR/_claims.json NOW." One retry max — if it fails again, stop and report.

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

# Build parliamentary speech context for MPs mentioned in the article
speech_ctx = None
try:
    from esbvaktin.speeches.context import build_speech_context
    speech_ctx = build_speech_context(article_text, language='is')
    if speech_ctx:
        print(f'Found parliamentary speech context for MPs in article.')
except Exception as e:
    print(f'Speech context unavailable: {e}')

prepare_assessment_context(claims_with_evidence, work_dir, language='is', speech_context=speech_ctx)
prepare_omission_context(article_text, claims_with_evidence, work_dir, language='is')
print('Assessment and omission contexts prepared (Icelandic).')
"
```

### Step 4 + 5: Assess Claims and Analyse Omissions (Parallel Agents)

Launch **both agents in parallel** — they are independent and can run simultaneously:

```
Agent: claim-assessor
Prompt: Read $WORK_DIR/_context_assessment.md and assess all claims against evidence.
        Write the flat JSON array to $WORK_DIR/_assessments.json.

Agent: omissions-analyst  (run in parallel with claim-assessor)
Prompt: Read $WORK_DIR/_context_omissions.md and analyse omissions and framing.
        Write the JSON object to $WORK_DIR/_omissions.json.
```

Wait for both agents to complete, then **verify outputs:**
- Check `$WORK_DIR/_assessments.json` exists. If missing, resume claim-assessor with: "You MUST use the Write tool to write the JSON array to $WORK_DIR/_assessments.json NOW."
- Check `$WORK_DIR/_omissions.json` exists. If missing, resume omissions-analyst with: "You MUST use the Write tool to write the JSON object to $WORK_DIR/_omissions.json NOW."

One retry max per agent — if still missing after retry, stop and report.

### Step 6: Assemble Icelandic Report (Python)

```bash
uv run python -c "
import json
from pathlib import Path
from esbvaktin.pipeline.parse_outputs import parse_assessments, parse_omissions_safe
from esbvaktin.pipeline.assemble_report import assemble_report

work_dir = Path('$WORK_DIR')
assessments = parse_assessments(work_dir / '_assessments.json')
omissions = parse_omissions_safe(work_dir / '_omissions.json')

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
    article_url=None,    # Set from input URL if available
    language='is',
)

(work_dir / '_report_is.md').write_text(report.report_text_is)
(work_dir / '_report.json').write_text(report.model_dump_json(indent=2))
print('Icelandic report assembled.')
print()
print(report.report_text_is[:500])
"
```

### Step 7: Finalise Report (Python)

```bash
uv run python -c "
import json
from pathlib import Path

work_dir = Path('$WORK_DIR')

# Read report
report_data = json.loads((work_dir / '_report.json').read_text())

# Write Icelandic report text
report_is = report_data.get('report_text_is', '')
if report_is:
    (work_dir / '_report_is.md').write_text(report_is)

# Write final report
(work_dir / '_report_final.json').write_text(json.dumps(report_data, indent=2, ensure_ascii=False, default=str))
print(f'Final report written to {work_dir}/_report_final.json')
print()

# Print summary
print('=== GREINING LOKIÐ ===')
print(f'Vinnusvæði: {work_dir}')
print(f'Yfirlit: {report_data[\"summary\"]}')
capsule = report_data.get('capsule', '')
if capsule:
    print(f'Lesandanóta: {capsule}')
print(f'Fullyrðingar metnar: {len(report_data[\"claims\"])}')
print(f'Heimildir notaðar: {len(report_data[\"evidence_used\"])} færslur')
print(f'Íslensk skýrsla: {work_dir}/_report_is.md')
print()
print('Optional QA: uv run python scripts/correct_icelandic.py check $WORK_DIR --fix')
"
```

### Step 7b: Extract Entities

**If panel show:** Generate entities directly from transcript (no subagent needed):

```bash
uv run python -c "
import json
from pathlib import Path
from esbvaktin.pipeline.transcript import parse_transcript, generate_panel_entities
from esbvaktin.pipeline.parse_outputs import parse_assessments

work_dir = Path('$WORK_DIR')
transcript = parse_transcript((work_dir / '_article.md').read_text())
assessments = parse_assessments(work_dir / '_assessments.json')

entities = generate_panel_entities(transcript, assessments)
data = entities.model_dump(mode='json')
(work_dir / '_entities.json').write_text(json.dumps(data, indent=2, ensure_ascii=False))
print(f'Panel entities generated: {len(entities.speakers)} speakers')
for s in entities.speakers:
    print(f'  - {s.name} ({s.party or s.role}) — {len(s.attributions)} claims')
"
```

**If regular article:** Prepare the entity extraction context and launch a subagent:

```bash
uv run python -c "
from pathlib import Path
from esbvaktin.pipeline.models import Claim
from esbvaktin.pipeline.prepare_context import prepare_entity_context
import json

work_dir = Path('$WORK_DIR')
article_text = (work_dir / '_article.md').read_text()

# Load claims from the final report
report = json.loads((work_dir / '_report_final.json').read_text())
claims = []
for item in report.get('claims', []):
    c = item.get('claim', item)
    claims.append(Claim.model_validate(c))

metadata = {
    'title': report.get('article_title'),
    'source': report.get('article_source'),
    'date': report.get('article_date'),
}
prepare_entity_context(article_text, claims, work_dir, metadata)
print(f'Entity context prepared ({len(claims)} claims).')
"
```

Use the **entity-extractor** agent:

```
Agent: entity-extractor
Prompt: Read $WORK_DIR/_context_entities.md and extract all entities/speakers.
        Write the JSON object to $WORK_DIR/_entities.json.
```

**Verify output:** Check that `$WORK_DIR/_entities.json` exists. If missing, resume with: "You MUST use the Write tool to write the JSON object to $WORK_DIR/_entities.json NOW." One retry max.

### Step 7c (Optional): Generate English Report

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

### Step 7d (Panel shows only): Register Sightings

For panel shows, register claim sightings with speaker attribution:

```bash
uv run python -c "
from pathlib import Path
from datetime import date
from esbvaktin.pipeline.parse_outputs import parse_assessments
from esbvaktin.pipeline.register_sightings import register_panel_sightings

work_dir = Path('$WORK_DIR')
assessments = parse_assessments(work_dir / '_assessments.json')

# Use transcript metadata for source info
from esbvaktin.pipeline.transcript import parse_transcript
transcript = parse_transcript((work_dir / '_article.md').read_text())

counts = register_panel_sightings(
    assessments=assessments,
    source_url=transcript.url or 'unknown',
    source_title=transcript.title,
    source_date=transcript.date,
)
print(f'Sightings registered: {counts}')
"
```

### Step 7d-articles: Register Article Sightings

For **regular articles** (not panel shows), register claim sightings after the report is finalised:

```bash
uv run python scripts/register_article_sightings.py --work-dir $WORK_DIR
```

This reads `_report_final.json` and registers all claim sightings with the article URL as source. If the script doesn't exist yet or fails, skip with a note — the batch script `register_article_sightings.py` can be run later.

### Step 7e: Write Reader's Note (Capsule)

Prepare the capsule context from the final report, then launch the capsule-writer agent:

```bash
uv run python -c "
import json
from pathlib import Path
from esbvaktin.pipeline.prepare_context import prepare_capsule_context

work_dir = Path('$WORK_DIR')
report_data = json.loads((work_dir / '_report_final.json').read_text())
prepare_capsule_context(report_data, work_dir)
print('Capsule context prepared.')
"
```

Use the **capsule-writer** agent:

```
Agent: capsule-writer
Prompt: Lestu $WORK_DIR/_context_capsule.md og skrifaðu lesandanótu.
        Skrifaðu niðurstöðuna í $WORK_DIR/_capsule.txt.
```

**Verify output:** Check that `$WORK_DIR/_capsule.txt` exists. If missing, resume with: "Skrifaðu lesandanótuna í $WORK_DIR/_capsule.txt STRAX." One retry max.

After the agent completes, write the capsule back into the final report:

```bash
uv run python -c "
import json
from pathlib import Path

work_dir = Path('$WORK_DIR')
capsule_path = work_dir / '_capsule.txt'
if capsule_path.exists():
    capsule = capsule_path.read_text().strip()
    report_path = work_dir / '_report_final.json'
    report_data = json.loads(report_path.read_text())
    report_data['capsule'] = capsule
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False, default=str))
    print(f'Capsule written: {capsule[:100]}...')
else:
    print('WARNING: _capsule.txt not found — skipping.')
"
```

### Step 8: Update Inbox Status

If the article was in the inbox, mark it as processed:
```bash
uv run python scripts/manage_inbox.py set-status <inbox_id> processed
```

## Files Produced

| File | Description |
|------|-------------|
| `_article.md` | Raw article/transcript text |
| `_context_extraction.md` | Context for claim extraction subagent (Icelandic) |
| `_claims.json` | Extracted claims (Icelandic claim_text, +speaker_name for panels) |
| `_context_assessment.md` | Context for claim assessment subagent (Icelandic) |
| `_context_omissions.md` | Context for omission analysis subagent (Icelandic) |
| `_assessments.json` | Claim assessments (Icelandic explanations) |
| `_omissions.json` | Omission analysis (Icelandic descriptions) |
| `_context_capsule.md` | Context for capsule-writer subagent |
| `_capsule.txt` | Reader's note — constructive Icelandic summary |
| `_report_is.md` | Icelandic report — primary output |
| `_report.json` | Structured report (JSON) |
| `_report_final.json` | Final complete report (JSON) |
| `_context_entities.md` | Context for entity extraction subagent (articles only) |
| `_entities.json` | Extracted entities/speakers (subagent for articles, generated for panels) |
| `_report_en.md` | English report (optional, Step 7c) |
