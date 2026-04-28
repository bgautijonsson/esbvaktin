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

## Dedup: `consumer_state` is primary, registry is the safety net

Per-article processing state lives in **frettasafn's `consumer_state` table** (Phase 3):

```sql
consumer_state(consumer_id, article_id, state, updated_at, metadata)
-- state ∈ {processed, rejected, skipped, in_progress}
```

- `scan_eu` and `fetch_eu_articles` anti-join against this at the SQL level when called with `consumer_id="esbvaktin"` — already-processed and rejected articles never reach Python.
- `register_article_sightings.py` writes `state="processed"` through after each registration.
- `manage_inbox.py reject` writes `state="rejected"`; `manage_inbox.py skip` writes `state="skipped"`.
- The Python helpers live in `src/esbvaktin/utils/frettasafn_state.py` (`mark_urls`, `is_known_url`).

The local `data/article_registry.json` is now a **transitional safety net** — it merges three legacy sources (`data/analyses/`, `~/esbvaktin-site/_data/reports/`, DB `claim_sightings`). `check_duplicate.py` checks both consumer_state AND the registry; either saying "duplicate" is a duplicate. Phase 4 will retire the registry once consumer_state has been stable for a verification period.

When checking for duplicates manually:
```bash
uv run python scripts/check_duplicate.py --url "URL" --title "TITLE"
```

When the registry feels stale (long break, suspect drift):
```bash
uv run python scripts/build_article_registry.py
```

## Rejected URLs

`data/rejected_urls.txt` tracks false positives from `scan_eu`. `manage_inbox.py reject` appends to this file AND writes `state="rejected"` to consumer_state — the SQL anti-join then filters those URLs out of future scans server-side. The text file remains as a human-readable log; the consumer_state row is what actually drives dedup.

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
