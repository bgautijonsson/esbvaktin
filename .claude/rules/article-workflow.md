---
description: Rules for article discovery, dedup, and analysis workflow
globs: ["scripts/check_duplicate.py", "scripts/build_article_registry.py", "data/analyses/**", ".claude/skills/find-articles/**", ".claude/skills/analyse-article/**"]
---

# Article Workflow

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

## Discovery → Analysis flow

1. `/find-articles` — discover and prioritise new articles
2. User picks articles from the list
3. `/analyse-article <url>` — runs the full pipeline (dedup check is built in)
