---
name: link-check
description: Check evidence source URLs for link rot, content drift, and soft 404s. Use when verifying that GT DB sources are still accessible, after long periods without checking, or when a specific topic's evidence URLs need re-validation. Also auto-populates source_excerpt fingerprints.
---

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

If excerpts are missing, populate them directly (the operation is idempotent — safe to re-run):

```bash
uv run python scripts/check_evidence_urls.py populate
```

This fetches each source URL via trafilatura, finds the best-matching sentence, and stores it as `source_excerpt` in the DB. Rate-limited at 0.5s between requests. **Do not run `--dry-run` first** — it adds an unnecessary confirmation step. Just run `populate` directly.

### Step 3: Run URL Checks

Based on user argument:

- **No argument:** `uv run python scripts/check_evidence_urls.py check`
- **Topic:** `uv run python scripts/check_evidence_urls.py check --topic TOPIC`
- **Force recheck:** `uv run python scripts/check_evidence_urls.py check --recheck`

This runs three-tier verification:
1. HTTP reachability (HEAD with identified UA → GET with identified UA → GET with browser headers on 4xx)
2. Redirect analysis (detect homepage redirects, domain migrations)
3. Content verification (search for source_excerpt in page text)

Bot-detection fallback (since 2026-05-26): if the identified UA gets 4xx/5xx, the checker retries GET with browser-fingerprint headers (Sec-Fetch-*, Accept-Language, etc.). If the 4xx body looks like Cloudflare's "Just a moment..." challenge, the URL is marked `ok` (functionally live, just unverifiable by bot). Sites are inconsistent: OECD/Consilium/island.is need browser headers; EFTA accepts the identified UA but rejects browser-only UAs.

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
- Many `redirect_homepage` results are intentional homepage URLs in the seed data (e.g., `https://www.fiskistofa.is/`), not broken — they're imprecise references. Treat them as a seed-data improvement task, not link rot.
- Known migrations: `enlargement.ec.europa.eu` → `neighbourhood-enlargement.ec.europa.eu`; `government.is/topics/*` → `stjornarradid.is/verkefni/*`; `sedlabanki.is/peningastefna/vaxtaakvardir/` → `/peningastefnunefnd/`; OECD `/agriculture/topics/*` → `/en/publications/*` with specific report IDs.

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
- **403/503 responses:** Many sites (OECD, EEAS, Cloudflare-fronted Althingi) reject bot UAs. The script falls back to browser headers and detects Cloudflare challenge pages. Some sites (EEAS, Reuters) block aggressively at the TLS/behavioural layer and will always false-positive — verify in a browser if in doubt. See `[[feedback_link_checker_dual_ua]]`.
- **Re-check interval:** URLs checked in the last 7 days are skipped by default. Use `--recheck` to force.
- **Excerpt quality:** Auto-populated excerpts should be reviewed. The algorithm finds the best-matching sentence but may pick generic text for generic URLs. Manual curation of excerpts for high-value evidence is worthwhile.
- **Content drift after URL replacement:** When you change `source_url`, clear `source_excerpt` to NULL too (the old fingerprint won't match the new page). Then re-run `populate` to fetch a fresh excerpt.
