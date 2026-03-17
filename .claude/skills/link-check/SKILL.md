# Link Check

Check evidence source URLs for link rot, content drift, and soft 404s. Maintains source_excerpt fingerprints to verify that URLs still point to the actual evidence content.

## Usage

```
/link-check                    # Full check (all URLs without recent checks)
/link-check fisheries          # Check one topic only
/link-check populate           # Auto-populate excerpt fingerprints
/link-check report             # Show link health report
/link-check status             # Quick summary
```

## Steps

### Step 1: Check Excerpt Coverage

```bash
uv run python scripts/check_evidence_urls.py status
```

If excerpt coverage is low (<50%), suggest running populate first to build fingerprints before checking.

### Step 2: Populate Excerpts (if needed)

If excerpts are missing, populate them by fetching source pages and extracting the sentence most similar to the evidence statement:

```bash
uv run python scripts/check_evidence_urls.py populate --dry-run
```

Review the dry run output. If the excerpts look reasonable:

```bash
uv run python scripts/check_evidence_urls.py populate
```

This fetches each source URL via trafilatura, finds the best-matching sentence, and stores it as `source_excerpt` in the DB. Rate-limited at 0.5s between requests.

### Step 3: Run URL Checks

Based on user argument:

- **No argument:** `uv run python scripts/check_evidence_urls.py check`
- **Topic:** `uv run python scripts/check_evidence_urls.py check --topic TOPIC`
- **Force recheck:** `uv run python scripts/check_evidence_urls.py check --recheck`

This runs three-tier verification:
1. HTTP reachability (HEAD, then GET fallback)
2. Redirect analysis (detect homepage redirects, domain migrations)
3. Content verification (search for source_excerpt in page text)

Results are stored in `source_url_status` and `source_url_checked` columns.

### Step 4: Show Report

```bash
uv run python scripts/check_evidence_urls.py report
```

This shows:
- Status breakdown (ok, redirect, error, content_drift, etc.)
- Problem URLs grouped by failure type
- Unchecked URL count
- Excerpt coverage

### Step 5: Fix Problems

For each problem URL, help the user find the correct URL:

**Dead links (404, DNS error):**
- Search the Wayback Machine: `https://web.archive.org/web/*/URL`
- Search the institution's current site for the content
- If permanently gone, note it in caveats and update `source_url`

**Homepage redirects (institutional reorganisation):**
- The institution likely restructured. Search their site for the specific content.
- Common: `enlargement.ec.europa.eu` → `neighbourhood-enlargement.ec.europa.eu`

**Content drift (excerpt missing from page):**
- The page exists but content has changed
- Check if it moved to a different URL on the same site
- Verify the evidence statement is still accurate given the new content
- Update both `source_url` and `source_excerpt` if needed

Apply fixes via `fix_evidence_urls.py`:
```bash
uv run python scripts/fix_evidence_urls.py apply data/seeds/url_fixes.json
```

## Notes

- **Rate limiting:** 0.5s delay between requests. A full check of 374 URLs takes ~3-4 minutes.
- **Non-HTML sources** (px.hagstofa.is, data.worldbank.org) are checked for HTTP status only — no excerpt extraction.
- **403 responses:** Some sites (althingi.is) reject HEAD requests. The script falls back to GET automatically.
- **Re-check interval:** URLs checked in the last 7 days are skipped by default. Use `--recheck` to force.
- **Excerpt quality:** Auto-populated excerpts should be reviewed. The algorithm finds the best-matching sentence but may pick generic text for generic URLs. Manual curation of excerpts for high-value evidence is worthwhile.
