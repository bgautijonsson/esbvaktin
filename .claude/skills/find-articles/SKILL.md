# Find Articles

Discover new EU referendum articles, filter out already-processed and irrelevant ones, and **automatically analyse HIGH priority articles**. Also surfaces backlog from previous sessions.

## Usage

```
/find-articles              # Scan last 7 days + check backlog
/find-articles 3            # Scan last 3 days + check backlog
/find-articles 2026-03-01   # Scan from specific date
/find-articles backlog      # Skip scanning, just work the backlog
```

## Autonomy Model

- **HIGH priority** articles (verified by full-text read) → auto-queue and auto-analyse. No user confirmation needed.
- **MEDIUM priority** articles → present to user, wait for selection.
- **LOW priority** → note in summary, leave as pending.
- **Backlog** → always check for pending HIGH priority articles from previous sessions before scanning.

The user can override by saying "stop after scanning" or "don't analyse yet".

## Steps

### Step 0: Check Backlog

Before scanning for new articles, check the existing inbox for unprocessed HIGH priority articles:

```bash
uv run python scripts/manage_inbox.py next --high-only --limit 10
```

Note any backlog articles. These will be included in the analysis batch alongside newly discovered HIGH articles.

If the argument is `backlog`, **skip Steps 1–7** and go directly to Step 8 with the backlog articles.

### Step 1: Refresh Article Registry (still consumed by other scripts)

```bash
uv run python scripts/build_article_registry.py --status
```

This merges `data/analyses/`, site reports, and DB sightings into `data/article_registry.json`. The registry is no longer used for `scan_eu` filtering — the SQL-side anti-join below replaces it — but it's still consumed by `check_duplicate.py` and `register_article_sightings.py`. Keep this step until Phase 3 retires those paths.

### Step 2: Show Inbox Status

```bash
uv run python scripts/manage_inbox.py status
```

Also load rejected URLs for URL-based filtering. **Use the Read tool** to read `data/rejected_urls.txt` (do NOT use shell commands like `wc`, `grep`, or input redirection — these trigger permission prompts). Parse the lines in your response: non-empty lines that don't start with `#` are rejected URLs.

### Step 3: Scan for EU Articles

Use the Fréttasafn MCP `scan_eu` tool with `consumer_id="esbvaktin"` so frettasafn anti-joins against its `consumer_state` table at the SQL level — already-processed and rejected articles are filtered out before they reach Python:

```
scan_eu(date_from=<start_date>, date_to=<today>, consumer_id="esbvaktin", limit=50)
```

Where `start_date` is determined by the argument (default: 7 days ago).

The `exclude_states` parameter defaults to `["processed", "rejected"]` when `consumer_id` is set; pass it explicitly only to override (e.g. `["processed", "rejected", "skipped"]` to also skip deferred articles).

If the scan returns many results, run a second pass with a narrower date range or higher limit if needed to ensure coverage.

### Step 4: Filter and Classify

For each article returned by `scan_eu` (already filtered server-side via consumer_state SQL anti-join):

1. **Skip if rejected** — URL (normalised) is in `rejected`
2. **Title-based false positive filter** — skip articles whose titles clearly have no EU/referendum content. Common false positive patterns from `scan_eu`:
   - Crime/accident reports (kynferðisbrot, slys, lögregla, eld)
   - Sports (ÓL, keppni, leikur)
   - Celebrity/entertainment news
   - Weather
   - Real estate listings

   The scan_eu tool over-matches because "ESB" and "Evrópusambandið" appear in sidebars and tag clouds. **Do not auto-reject based on title alone** — only filter obvious non-EU content.

4. **Classify remaining** into:
   - **HIGH**: Opinion pieces, interviews, analyses with factual claims about EU/referendum topics (fisheries, sovereignty, agriculture, trade, EEA, polling)
   - **MEDIUM**: News reports about the referendum process, parliamentary proceedings, party positions
   - **LOW**: Short items (<200 words), personnel news, tangential mentions, meta-commentary without verifiable claims

### Step 5: Fetch and Verify Candidates

For articles classified HIGH or MEDIUM, fetch the full text using `get_article(article_id)` from Fréttasafn MCP.

After reading, re-evaluate:
- Is this genuinely about the EU referendum? (Some articles mention ESB once in passing)
- Does it contain verifiable factual claims? (Not just process/meta commentary)
- Upgrade or downgrade classification based on actual content

### Step 6: Save to Inbox

Before presenting results, persist all discovered articles to the inbox.

1. **Use the Write tool** (not Bash heredoc/cat) to write the classified articles as a JSON array to `data/inbox/_scan_YYYYMMDD.json`. Fields: `url`, `title`, `source`, `date`, `word_count`, `article_type`, `topics` (array), `priority`, `frettasafn_id`, `notes`.

2. Import the batch:
```bash
uv run python scripts/manage_inbox.py add-batch data/inbox/_scan_YYYYMMDD.json
```

3. For HIGH and MEDIUM articles where full text was fetched, **use the Write tool** to save the text to `data/inbox/texts/<inbox_id>.md`, then mark it:
```bash
uv run python scripts/manage_inbox.py set-status <inbox_id> pending
```
(The `has_text` flag is set by `save-text`, but since we wrote the file directly, update the inbox entry manually if needed.)

**Never use shell heredocs, `cat >`, or `echo >` to write data files** — these trigger permission prompts.

### Step 7: Present Summary

Display a brief summary (not a full table for HIGH — those are about to be analysed):

```markdown
## Scan Results — [date range]

Registry: X processed | Inbox: Y pending (Z high) | W rejected

**Proceeding to analyse N HIGH priority articles** (M new + K backlog):
1. [source] Title (date) — key topics
2. ...

### MEDIUM (awaiting your selection)
| # | ID | Title | Source | Date | Topics |
|---|-----|-------|--------|------|--------|

### LOW (skipped)
- N articles noted, left as pending
```

If there are MEDIUM articles, note them but do not wait — proceed with HIGH articles first. The user can queue MEDIUM articles while HIGH analyses run.

### Step 8: Auto-Analyse HIGH Priority Articles

**Do not stop and wait.** For each HIGH priority article (both newly discovered and backlog), automatically:

1. Queue it: `uv run python scripts/manage_inbox.py queue <id>`
2. Launch `/analyse-article <url>` with the article URL

**Ordering:** Analyse articles from the most recent date first — current news has higher time-sensitivity than backlog. Within the same date, prefer articles with cached text (faster start).

**Parallelisation:** Run analyses **sequentially** (each analysis spawns parallel subagents internally). This avoids context window pressure and makes error recovery simpler.

After each analysis completes:
- Note the verdict summary
- Continue to the next article

After all HIGH articles are analysed, present a batch summary:

```markdown
## Analysis Batch Complete

| # | Title | Verdicts | Completeness |
|---|-------|----------|-------------|
| 1 | ... | 3 supported, 1 partial | 78% |
| 2 | ... | 2 supported, 2 misleading | 65% |

Remaining: N MEDIUM articles pending your selection.
```

### Step 9: Handle MEDIUM Articles (if user responds)

When the user picks MEDIUM articles to analyse:

1. Queue them: `uv run python scripts/manage_inbox.py queue <id> [<id> ...]`
2. For each selected article, launch `/analyse-article <url>`

When the user marks articles as irrelevant/skip:

1. Reject them: `uv run python scripts/manage_inbox.py reject <id> [<id> ...]`
   (This sets status to "rejected" AND appends URLs to `rejected_urls.txt`)

When articles are neither picked nor rejected, they remain `pending` in the inbox for next session.

## Notes

- **Fréttasafn false positives**: The `scan_eu` tool searches keyword groups (EU general, referendum, accession, EEA/Schengen, fisheries, agriculture). It returns many articles where these keywords only appear in sidebars, tag clouds, or "related articles" sections. Always fetch full text before final classification.
- **Parallel fetching**: Fetch multiple articles in parallel using concurrent MCP calls to speed up Step 5.
- **Date range**: Default 7 days balances thoroughness with speed. For catch-up after a break, use a longer range.
- **The registry is the authority**: Never check only `data/analyses/` or only the DB. Always use the registry.
- **Backlog priority**: Articles older than 7 days are flagged as backlog in `manage_inbox.py next` output. They are still analysed — age does not reduce importance, only time-sensitivity.
- **Session efficiency**: A typical session should be: run `/find-articles` → Claude scans, finds 2–4 HIGH articles, analyses them all, presents results + MEDIUM list. User reviews MEDIUM, optionally queues some. Minimal keyboard time.
- **Avoid permission prompts**: Use dedicated tools (Read, Write, Grep, Glob) instead of shell commands for all file I/O. Never use input redirection (`<`), heredocs (`<< EOF`), `cat >`, `echo >`, `wc`, or `grep` on data files — these trigger security prompts that require user interaction. Only use Bash for `uv run python` commands.
