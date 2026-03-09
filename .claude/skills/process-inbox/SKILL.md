# Process Inbox

Ingest articles from two sources — **Fréttasafn** (automated news corpus) and a **manual Obsidian inbox** — extract claims, match them against the claim bank, record sightings, and flag ground truth gaps.

This is a **lightweight claim harvesting** pipeline: it extracts and catalogues claims without full assessment. Verdicts for new claims are set to `unverifiable` until a full analysis is run.

## Usage

```
/process-inbox                       # Both sources: Fréttasafn + manual inbox
/process-inbox frettasafn            # Fréttasafn only
/process-inbox inbox                 # Manual inbox only
```

## Prerequisites

- PostgreSQL running with Ground Truth DB schema (including `claim_sightings` table)
- `BAAI/bge-m3` model available for embeddings
- Fréttasafn MCP tools available (for Fréttasafn mode)
- ESB Obsidian vault accessible via Obsidian MCP (for manual inbox mode)

## Steps

### Step 0: Prepare Working Directory

```bash
BATCH_ID=$(date +%Y%m%d_%H%M%S)
WORK_DIR="data/inbox/${BATCH_ID}"
mkdir -p "$WORK_DIR"
```

### Step 1: Gather Articles

#### Step 1a: Fréttasafn Search (if mode includes fréttasafn)

Search the Fréttasafn MCP for EU referendum-related articles not yet processed.

Use the Fréttasafn MCP tools to search for recent articles:

```
search_news("ESB aðild", date_from=<last_run_date>, limit=50)
search_news("Evrópusambandið", date_from=<last_run_date>, limit=50)
search_news("þjóðaratkvæðagreiðsla", date_from=<last_run_date>, limit=50)
search_news("sjávarútvegsstefna ESB", date_from=<last_run_date>, limit=30)
search_news("fullveldi Íslands ESB", date_from=<last_run_date>, limit=30)
```

**Finding last_run_date:** Check the ESB Obsidian vault for `Knowledge/Discourse Tracking/Log.md` — the most recent entry's date is the last run date. If no log exists, use 7 days ago as default.

For each article returned, call `get_article(article_id)` to get the full text. Deduplicate by URL against articles already in `$WORK_DIR`.

Write each article to `$WORK_DIR/{article_id}.md` with a YAML header:

```yaml
---
source: frettasafn
url: https://...
title: Article Title
date: 2026-03-09
source_id: ruv
---

Article text here...
```

#### Step 1b: Manual Inbox (if mode includes inbox)

Read the inbox note from the ESB Obsidian vault:

```
Obsidian MCP → read_note(vault="ESB", path="Knowledge/Discourse Tracking/Inbox.md")
```

Parse each line. Expected format:

```
- https://example.is/article #optional-tag
- https://example.is/another-article  (optional note)
```

For each URL:
1. Try Fréttasafn first: `search_news(url)` — if the article is already in the corpus, use `get_article()` to fetch it
2. Fallback: fetch with trafilatura:
   ```bash
   uv run python -c "
   import trafilatura
   downloaded = trafilatura.fetch_url('URL')
   text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
   print(text)
   "
   ```

Write each article to `$WORK_DIR/manual_{n}.md` with the same YAML header format, using `source: manual` and any tags from the inbox line.

### Step 2: Extract Claims (Subagent — per article batch)

For each article file in `$WORK_DIR/`, launch a subagent for claim extraction.

**Subagent context (write to `$WORK_DIR/_context_batch_extraction.md`):**

```markdown
# Fullyrðingagreining — hópvinnsla

Þú ert fullyrðingagreiningarvél. Fyrir hverja grein skaltu greina allar staðhæfingar
sem varða ESB-aðild Íslands.

## Hvað telst fullyrðing?

Greindu aðeins **efnislegar fullyrðingar um afleiðingar, áhrif eða staðreyndir** sem varða
ESB-aðild Íslands og hægt er að bera saman við gögn eða heimildir.

### Taka með:
- Stefnuáhrif ESB-aðildar (sjávarútvegur, landbúnaður, viðskipti, fullveldi, o.s.frv.)
- Tölfræðilegar staðhæfingar (tölur, hundraðshlutfall, samanburður)
- Lagalegar fullyrðingar (hvað EES-samningurinn segir, hvað ESB-reglur krefjast)
- Samanburð við reynslu annarra ríkja (Noregur, Króatía, o.s.frv.)
- Spár um afleiðingar aðildar eða ekki-aðildar
- Staðhæfingar um afstöðu flokka eða stofnana til ESB-aðildar

### EKKI taka með:
- Ævisögulegar upplýsingar (hver er viðkomandi, hvar starfar hann/hún, hvaða flokk)
- Málsmeðferð (hvenær grein var birt, hver skrifaði, hvar fundur var haldinn)
- Hreinar skoðanir án efnislegs kjarni sem hægt er að sannreyna
- Lýsingar á því sem greinin fjallar um ("í þessari grein er fjallað um...")
- Almenn orðræða sem ekki inniheldur sannreynanlega staðhæfingu

Spurðu þig: **myndi þessi fullyrðing eiga heima á opinberum fullyrðingavaka?**
Ef ekki, slepptu henni.

## Reglur

- Skrifaðu `claim_text` á **íslensku**
- Flokkaðu eftir efni: fisheries, trade, sovereignty, eea_eu_law, agriculture,
  precedents, currency, labour, energy, housing, polling, party_positions,
  org_positions, other
- Tegund fullyrðingar: statistic, legal_assertion, comparison, prediction, opinion
- Vistaðu beina tilvitnun í `original_quote`
- **JSON safety**: Íslenskar gæsalappir „…" → \"…\" í JSON-strengjum
- Skrifaðu hrátt JSON, engin markdown-umbúðir

## Greinar

[Embed all article texts here, separated by --- with filename headers]

## Úttak

Skrifaðu JSON á þessu sniði í `$WORK_DIR/_extracted_claims.json`:

```json
[
  {
    "source_file": "article_id.md",
    "source_url": "https://...",
    "source_title": "...",
    "source_date": "2026-03-09",
    "claims": [
      {
        "claim_text": "...",
        "original_quote": "...",
        "category": "fisheries",
        "claim_type": "statistic"
      }
    ]
  }
]
```
```

**Subagent task:** Read `$WORK_DIR/_context_batch_extraction.md` and extract claims from all articles. Write JSON output to `$WORK_DIR/_extracted_claims.json`.

**Critical principles:**
- Extract substantive, verifiable claims about EU membership consequences — not biographical facts, procedural details, or pure opinion
- The test: "would this claim belong on a public claim tracker?" If not, skip it
- One article may contain 0 relevant claims if it's not about the referendum
- Independence: both pro-EU and anti-EU claims equally
- Prefer fewer, higher-quality claims over exhaustive extraction

### Step 3: Match Claims Against Claim Bank (Python)

```bash
uv run python -c "
import json
from pathlib import Path
from datetime import date
from esbvaktin.ground_truth.operations import get_connection, embed_text, search_evidence
from esbvaktin.claim_bank.operations import search_claims, add_claim, generate_slug
from esbvaktin.claim_bank.models import CanonicalClaim

work_dir = Path('$WORK_DIR')
extracted = json.loads((work_dir / '_extracted_claims.json').read_text())

conn = get_connection()

results = {
    'matched': [],      # existing claims with new sightings
    'new': [],          # brand new claims added to bank
    'no_evidence': [],  # claims lacking ground truth coverage
}

for article in extracted:
    url = article['source_url']
    title = article.get('source_title', '')
    article_date = article.get('source_date')

    for claim_data in article.get('claims', []):
        claim_text = claim_data['claim_text']
        category = claim_data.get('category', 'other')
        claim_type = claim_data.get('claim_type', 'opinion')

        # Search claim bank for semantic match
        matches = search_claims(claim_text, threshold=0.70, top_k=3, conn=conn)

        if matches and matches[0].similarity >= 0.70:
            # Existing claim — record sighting
            best = matches[0]
            conn.execute('''
                INSERT INTO claim_sightings
                    (claim_id, source_url, source_title, source_date,
                     original_text, similarity, source_type)
                VALUES (%(claim_id)s, %(url)s, %(title)s, %(date)s,
                        %(text)s, %(sim)s, %(type)s)
                ON CONFLICT (claim_id, source_url) DO NOTHING
            ''', {'claim_id': best.claim_id, 'url': url, 'title': title,
                  'date': article_date, 'text': claim_text,
                  'sim': best.similarity, 'type': 'news'})
            conn.commit()
            results['matched'].append({
                'claim': claim_text,
                'matched_to': best.canonical_text_is,
                'similarity': best.similarity,
                'slug': best.claim_slug,
            })
        else:
            # New claim — add as draft (unverifiable, unpublished)
            slug = generate_slug(claim_text)
            new_claim = CanonicalClaim(
                claim_slug=slug,
                canonical_text_is=claim_text,
                category=category,
                claim_type=claim_type,
                verdict='unverifiable',
                explanation_is='Sjálfvirk greining — fullyrðing ekki enn metin.',
                confidence=0.0,
                last_verified=date.today(),
                published=False,
                supporting_evidence=[],
                contradicting_evidence=[],
            )
            claim_id = add_claim(new_claim, conn=conn)

            # Record first sighting
            conn.execute('''
                INSERT INTO claim_sightings
                    (claim_id, source_url, source_title, source_date,
                     original_text, similarity, source_type)
                VALUES (%(claim_id)s, %(url)s, %(title)s, %(date)s,
                        %(text)s, %(sim)s, %(type)s)
                ON CONFLICT (claim_id, source_url) DO NOTHING
            ''', {'claim_id': claim_id, 'url': url, 'title': title,
                  'date': article_date, 'text': claim_text,
                  'sim': 1.0, 'type': 'news'})
            conn.commit()

            # Check ground truth coverage
            evidence = search_evidence(claim_text, top_k=3, conn=conn)
            has_evidence = any(e.similarity > 0.60 for e in evidence)

            entry = {
                'claim': claim_text,
                'slug': slug,
                'category': category,
            }
            results['new'].append(entry)
            if not has_evidence:
                results['no_evidence'].append(entry)

conn.close()

# Write results
(work_dir / '_match_results.json').write_text(
    json.dumps(results, indent=2, ensure_ascii=False, default=str)
)

print(f'=== INBOX PROCESSED ===')
print(f'Matched to existing claims: {len(results[\"matched\"])}')
print(f'New claims added (draft):   {len(results[\"new\"])}')
print(f'Missing ground truth:       {len(results[\"no_evidence\"])}')
"
```

### Step 4: Clear Inbox and Write Log

#### Clear the manual inbox (if used)

Replace the inbox note content with just the header (keep processed URLs out):

```
Obsidian MCP → write_note(
    vault="ESB",
    path="Knowledge/Discourse Tracking/Inbox.md",
    content="Paste URLs here for claim extraction. One per line.\n\nFormat: `- https://url #optional-tag`\n"
)
```

#### Append to discourse tracking log

```
Obsidian MCP → append_to_note(
    vault="ESB",
    path="Knowledge/Discourse Tracking/Log.md",
    content=<formatted summary — see below>
)
```

**Log entry format:**

```markdown

## YYYY-MM-DD HH:MM — Inbox Run

- **Articles processed:** N (M from Fréttasafn, K manual)
- **Claims extracted:** N total
- **Matched existing claims:** N
- **New claims (draft):** N
- **Missing ground truth:** N

### Ground Truth Gaps (priority)

| Claim | Category | Slug |
|---|---|---|
| ... | fisheries | ... |

### New Claims Added

| Claim | Category | Type |
|---|---|---|
| ... | trade | statistic |
```

### Step 5: Display Summary

Print a summary to the user showing:

1. How many articles were processed from each source
2. How many claims were extracted
3. How many matched existing canonical claims (with sighting counts)
4. How many new draft claims were created
5. **The prioritisation signal:** claims that appear frequently but lack ground truth coverage

Format the ground truth gaps as a prioritised list, sorted by category, highlighting which topics need evidence work.

## Files Produced

| File | Description |
|------|-------------|
| `$WORK_DIR/{article_id}.md` | Fetched article texts |
| `$WORK_DIR/_context_batch_extraction.md` | Subagent context for claim extraction |
| `$WORK_DIR/_extracted_claims.json` | Raw extracted claims per article |
| `$WORK_DIR/_match_results.json` | Matching results + gap analysis |

## Notes

- **Draft claims** are created with `verdict: unverifiable` and `published: false`. They need a full analysis run (`/analyse-article`) or manual review before publishing.
- **Sighting deduplication**: `UNIQUE(claim_id, source_url)` prevents counting the same article twice for the same claim.
- **Similarity threshold**: 0.70 for fuzzy matching (same as the claim bank's existing threshold). Claims between 0.70–0.85 are logged as matches but may warrant review for canonicalisation.
- **Fréttasafn search queries** can be extended. If new referendum topics emerge (e.g. defence policy), add search terms to Step 1a.
- The `claim_frequency` SQL view provides a quick dashboard: `SELECT * FROM claim_frequency ORDER BY sighting_count DESC LIMIT 20;`
