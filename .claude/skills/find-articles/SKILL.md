# Find Articles

Discover new EU referendum articles, filter out already-processed and irrelevant ones, and present a prioritised list for analysis.

## Usage

```
/find-articles              # Scan last 7 days
/find-articles 3            # Scan last 3 days
/find-articles 2026-03-01   # Scan from specific date
```

## Steps

### Step 1: Rebuild Article Registry

```bash
uv run python scripts/build_article_registry.py --status
```

This merges `data/analyses/`, site reports, and DB sightings into `data/article_registry.json`. Note the total count for the user.

### Step 2: Load Filters + Inbox

Load filter sets and existing inbox:

**Processed URLs** — read `data/article_registry.json`:
```python
import json
registry = json.loads(open("data/article_registry.json").read())
processed_urls = {entry["url"].rstrip("/").lower() for entry in registry}
```

**Rejected URLs** — read `data/rejected_urls.txt`:
```python
rejected = set()
for line in open("data/rejected_urls.txt"):
    line = line.strip()
    if line and not line.startswith("#"):
        rejected.add(line.rstrip("/").lower())
```

**Inbox URLs** — read `data/inbox/inbox.json` to avoid re-discovering articles already in the inbox:
```python
from pathlib import Path
inbox_path = Path("data/inbox/inbox.json")
inbox_urls = set()
if inbox_path.exists():
    inbox = json.loads(inbox_path.read_text())
    inbox_urls = {entry["url"].rstrip("/").lower() for entry in inbox}
```

Also show current inbox status:
```bash
uv run python scripts/manage_inbox.py status
```

### Step 3: Scan for EU Articles

Use the Fréttasafn MCP `scan_eu` tool:

```
scan_eu(date_from=<start_date>, date_to=<today>, limit=50)
```

Where `start_date` is determined by the argument (default: 7 days ago).

If the scan returns many results, also run a second pass with a narrower date range or higher limit if needed to ensure coverage.

### Step 4: Filter and Classify

For each article returned by `scan_eu`:

1. **Skip if processed** — URL (normalised) is in `processed_urls`
2. **Skip if rejected** — URL (normalised) is in `rejected`
2b. **Skip if already in inbox** — URL (normalised) is in `inbox_urls`
3. **Title-based false positive filter** — skip articles whose titles clearly have no EU/referendum content. Common false positive patterns from `scan_eu`:
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

Before presenting results, persist all discovered articles to the inbox. Write a JSON file and import it:

```bash
# Write classified articles to a batch file, then import
uv run python scripts/manage_inbox.py add-batch data/inbox/_scan_YYYYMMDD.json
```

The batch JSON is an array of objects with fields: `url`, `title`, `source`, `date`, `word_count`, `article_type`, `topics` (array), `priority`, `frettasafn_id`, `notes`.

For HIGH and MEDIUM articles where full text was fetched, save it:
```bash
# Write the fetched text to a temp file, then:
uv run python scripts/manage_inbox.py save-text <inbox_id> /path/to/text.md
```

### Step 7: Present Results

Display a table to the user, now including inbox IDs:

```markdown
## New Articles — [date range]

Registry: X processed articles | Inbox: Y pending | Z rejected URLs

### HIGH PRIORITY
| # | ID | Title | Source | Words | Type | Key Topics |
|---|-----|-------|--------|-------|------|------------|
| 1 | vsir-abc123 | ... | Vísir | 2100 | Opinion (anti-EU) | fisheries, sovereignty |

### MEDIUM PRIORITY
| # | ID | Title | Source | Words | Type | Key Topics |
|---|-----|-------|--------|-------|------|------------|

### LOW PRIORITY (probably skip)
| # | ID | Title | Source | Words | Type | Key Topics |
|---|-----|-------|--------|-------|------|------------|

### Filtered Out
- X already processed
- Y rejected (known false positives)
- Z already in inbox
- W title-filtered (clearly irrelevant)
```

For HIGH priority articles, include a one-line summary of the main claims/arguments.

### Step 8: Handle User Selection

When the user picks articles to analyse:

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
