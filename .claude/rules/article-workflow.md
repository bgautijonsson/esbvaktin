---
description: Rules for article discovery, dedup, and analysis workflow
globs: ["scripts/check_duplicate.py", "scripts/build_article_registry.py", "data/analyses/**", ".claude/skills/find-articles/**", ".claude/skills/analyse-article/**"]
---

# Article Workflow

## Autonomy Model

- **HIGH priority** articles → auto-analyse after discovery. No user confirmation needed.
- **MEDIUM priority** → present to user, wait for selection.
- **Backlog** → always check `manage_inbox.py next --high-only` before scanning for new articles.
- `/find-articles` scans + analyses HIGH articles in one session. User only needs to approve MEDIUM.

## Dedup: Always check all three sources

Processed articles exist in THREE places that can diverge:

1. `data/analyses/*/_report_final.json` — local work directories
2. `~/esbvaktin-site/_data/reports/*.json` — site report exports
3. DB `claim_sightings` table — registered after pipeline completes

**Before marking an article as "new"**, rebuild the registry:
```bash
uv run python scripts/build_article_registry.py
```

Then check against it:
```bash
uv run python scripts/check_duplicate.py --url "URL" --title "TITLE"
```

Never rely on `claim_sightings` alone — the site is often ahead of the DB.

## Rejected URLs

`data/rejected_urls.txt` tracks false positives from `scan_eu`. When discovering articles, filter these out. When a user confirms an article is irrelevant, append its URL to this file.

## Article Inbox

`data/inbox/inbox.json` tracks discovered articles with status, priority, and metadata. Managed by `scripts/manage_inbox.py`. Articles persist between sessions.

```bash
uv run python scripts/manage_inbox.py status              # Backlog summary
uv run python scripts/manage_inbox.py list                 # Pending articles
uv run python scripts/manage_inbox.py list --priority high # High priority only
uv run python scripts/manage_inbox.py next --high-only     # Next articles ready for analysis
uv run python scripts/manage_inbox.py queue ID [ID ...]    # Queue for analysis
uv run python scripts/manage_inbox.py reject ID [ID ...]   # Reject (also adds to rejected_urls.txt)
uv run python scripts/manage_inbox.py skip ID [ID ...]     # Skip (not worth analysing)
```

Article texts cached at `data/inbox/texts/{id}.md` for high/medium priority items.

## Discovery → Analysis flow

1. `/find-articles` — discover, prioritise, save to inbox, **auto-analyse HIGH priority**
2. Claude presents MEDIUM articles for user selection (while HIGH analyses run)
3. `/analyse-article <url>` — runs the full pipeline (dedup + inbox status updates built in)
4. `/find-articles backlog` — skip scanning, just work pending HIGH priority articles
