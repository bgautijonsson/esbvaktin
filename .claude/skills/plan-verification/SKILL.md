# Plan Verification

Analyse an article analysis report for unverifiable claims and generate
a research task plan to fill evidence gaps in the Ground Truth Database.

## Usage

```
/plan-verification <analysis_dir>
```

Where `<analysis_dir>` is the path to a completed analysis (e.g. `data/analyses/20260309_123421`).

## Steps

### Step 1: Load Analysis and Identify Gaps (Python)

```bash
uv run python -c "
import json
from pathlib import Path
from esbvaktin.pipeline.models import AnalysisReport
from esbvaktin.gap_planner.operations import identify_gaps, summarise_gaps
from esbvaktin.gap_planner.prepare_context import prepare_gap_context

work_dir = Path('<ANALYSIS_DIR>')
report_data = json.loads((work_dir / '_report_final.json').read_text())
report = AnalysisReport.model_validate(report_data)

gaps = identify_gaps(report)
print(f'Found {len(gaps)} evidence gaps out of {len(report.claims)} claims')

if not gaps:
    print('No unverifiable claims — nothing to plan.')
    exit(0)

gap_summary = summarise_gaps(gaps)
for cat, count in gap_summary.items():
    print(f'  {cat}: {count}')

# Prepare context for research-planning subagent
ctx = prepare_gap_context(gaps, work_dir)
print(f'Gap analysis context written to {ctx}')
"
```

If no gaps are found, stop here — there's nothing to plan.

### Step 2: Plan Research (Subagent)

Launch a subagent to design research strategies for each gap:

**Subagent task:** Read `<ANALYSIS_DIR>/_context_gap_analysis.md` and follow its instructions.
Write a JSON array of research tasks to `<ANALYSIS_DIR>/_research_tasks.json`.

**Critical principles for the subagent:**
- Be realistic about effort estimates
- Suggest specific sources (institutions, databases, experts)
- For speculative/prediction claims: assess whether the gap CAN be filled or
  should be marked permanently unverifiable
- Write titles and descriptions in Icelandic
- Write raw JSON, no markdown wrapping

### Step 3: Create Obsidian Research Tasks (Python + Obsidian MCP)

Parse the research tasks and write them to the ESB Obsidian vault:

```bash
uv run python -c "
import json
from pathlib import Path

work_dir = Path('<ANALYSIS_DIR>')
tasks = json.loads((work_dir / '_research_tasks.json').read_text())

print(f'Parsed {len(tasks)} research tasks')

# Format for Obsidian next-actions append
checklist_lines = []
for task in tasks:
    priority = task.get('priority', 'medium')
    emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(priority, '⚪')
    title = task.get('title', 'Untitled')
    sources = ', '.join(task.get('suggested_sources', [])[:3])
    effort = task.get('estimated_effort_hours', 0)
    checklist_lines.append(f'- [ ] {emoji} {title} — _{sources}_ (~{effort:.0f} klst)')

print('\nResearch tasks for Obsidian:')
for line in checklist_lines:
    print(line)

# Write to temporary file for Obsidian MCP append
(work_dir / '_obsidian_tasks.md').write_text('\n'.join(checklist_lines))
print(f'\nReady to append to Obsidian vault.')
"
```

Then use the Obsidian MCP to append the research tasks:

1. Read `<ANALYSIS_DIR>/_obsidian_tasks.md`
2. Append its contents to `ESB/Knowledge/Ground Truth Database/next-actions.md`
   under a new heading: `## Eyður frá greiningu <date>`

For high-priority gaps, also create individual notes in
`ESB/Knowledge/Ground Truth Database/` with:
- Frontmatter: `status: todo`, `priority: <high|medium|low>`, `tags: [research-gap, <category>]`
- Full gap description, suggested sources, and research approach

## Files Produced

| File | Description |
|------|-------------|
| `_context_gap_analysis.md` | Context for research-planning subagent |
| `_research_tasks.json` | Structured research tasks |
| `_obsidian_tasks.md` | Formatted checklist for Obsidian append |
