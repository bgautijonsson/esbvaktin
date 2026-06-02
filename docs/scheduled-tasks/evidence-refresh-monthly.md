# Scheduled task: evidence-refresh-monthly (fresh-01)

The monthly high-decay evidence refresh. Evidence freshness was previously entirely
manual; this task automates only the **sweep → flag → note** loop. Every consequential
action (re-checking URLs, re-running verdicts, re-harvesting sources) stays a
human-gated follow-up, and nothing is ever auto-published.

The substance lives in `scripts/monthly_evidence_refresh.py` (committed, tested). The
file below is the scheduled-task wrapper.

**Install:** create `~/.claude/scheduled-tasks/evidence-refresh-monthly/SKILL.md` with
the content below, and schedule it for the **first Monday of each month** (mirrors the
existing `link-check-weekly` / `source-health-weekly` routines).

```markdown
---
name: evidence-refresh-monthly
description: First-Monday monthly sweep of high-decay + 90-day-stale Ground Truth evidence. Flags affected claims for reassessment and surfaces a review note. Never auto-publishes.
---

Run the monthly high-decay evidence refresh for ESBvaktin. The fastest-decaying topics
(polling, party_positions, org_positions, currency) plus any 90-day-stale evidence are
swept; the published claims that cite them are flagged for the next human-gated
reassessment cycle; and a review note is filed to the vault. Nothing is auto-published.

Context: evidence freshness was previously entirely manual. This task automates only the
SWEEP + FLAG + NOTE — every consequential action (re-checking URLs, re-running verdicts,
re-harvesting sources) remains a human-gated follow-up.

Steps:

1. cd /Users/brynjolfurjonsson/esbvaktin

2. Run the refresh sweep (flags claims via needs_reassessment, prints the review note):
   uv run python scripts/monthly_evidence_refresh.py
   Capture the printed markdown — it is the review note for step 5.

3. Run link health on the evidence URLs so the note's "re-check URLs" step has fresh
   statuses (can take 10–20 min):
   uv run python scripts/check_evidence_urls.py check

4. Determine today's date in ISO format (YYYY-MM-DD).

5. Write the captured review note to:
   /Users/brynjolfurjonsson/Obsidian/Metill/ESB/Operations/Evidence Refresh {YYYY-MM-DD}.md
   Prepend frontmatter:
   ---
   date: {YYYY-MM-DD}
   type: evidence-refresh
   tags: [evidence, freshness, operations, action-needed]
   ---
   then the markdown printed by the script.

6. Do NOT push, commit, reassess, or publish anything. The script only flagged claims
   (needs_reassessment). Reassessment is the user's explicit /reassess step.

7. If monthly_evidence_refresh.py fails (DB down, lock), write the error to the vault note
   instead of a normal report so the failure is visible.
```
