# xrepo-01 — Retire article_registry.json (consumer_state as sole dedup truth)

**Date:** 2026-06-02
**Status:** Backfill **DONE + VERIFIED** (gate ① 2026-06-02): 57 URLs + 2 orphan
article_ids written to consumer_state; the read-only gate now reports **0 gaps**
("Safe to retire"). Deletion **DEFERRED** — verification found it is a **3-consumer
re-homing**, not the 1-file delete the spec first assumed (it would break
`register_article_sightings.py`). `build_article_registry.py` / `check_duplicate.py`
remain **unchanged**; nothing deleted. See "Deletion — DEFERRED" for the true scope.
**Branch:** `pipeline-optimisation`
**Plan ref:** `esbvaktin-pipeline-optimisation-2026-06.html` → H3 / xrepo-01 / fresh-08 (Phase 4)

## Goal

Execute the documented Phase-4 retirement: make frettasafn's `consumer_state` the
sole dedup source of truth and remove the local `article_registry.json` mirror — which
already drifts (consumer_state 986 ⊋ registry 704) and couples esbvaktin to the
site repo's filesystem. **Irreversible**, so gated on a one-shot coverage check.

## What the registry is (and why retiring it is safe)

`build_article_registry.py` (237 lines) merges three sources into `article_registry.json`:
`data/analyses/`, `~/esbvaktin-site/_data/reports/` (the site back-coupling), and DB
`claim_sightings`. `check_duplicate.py` consumes it, **falling back to scanning
`data/analyses/` directly when it's absent**.

Tracing the matching paths, the registry's unique value is narrow:
- **URL dedup** — already canonical in `consumer_state` (checked separately in
  `check_duplicate.main`, and `scan_eu` anti-joins it server-side).
- **Content matching** — already only works against local `data/analyses/` `_article.md`
  (site-only entries are skipped, line 258). Retiring the registry does **not** degrade it.
- **Title-fuzzy matching** — the *only* real loss: against site/DB-only articles not in
  local `data/analyses/`. Their exact URLs are still caught by `consumer_state`.

## The gate (irreversibility safeguard) — read-only

`scripts/retire_registry.py`: gather every URL across the three sources
(`data/analyses/` reports, site reports, DB `claim_sightings`) and check each via
`is_known_url`. Pure core: `uncovered_urls(source_urls, locally_covered, state_by_url) -> set`
returns URLs that are neither locally scanned (`data/analyses/`) nor in `consumer_state`.
- **0 gaps ⇒ safe** — proceed with the deletions.
- **gaps ⇒ ABORT** — print the uncovered URLs; the operator backfills them into
  `consumer_state` (the existing additive `mark_urls` helper) and re-runs before any
  deletion. The gate never writes anything.

I run the gate on real data before the deletion commit; the result decides the path.

## Gate result (2026-06-02) — BLOCKED

Running the gate corrected its own safety model first: `is_known_url` resolves a URL via
frettasafn `article_id`, so an article analysed from a non-scraped URL can never be in
consumer_state — but is still covered by `check_duplicate`'s `data/analyses/` scan. So
the at-risk set excludes locally-scanned URLs (the gate now does this).

Even corrected, the gate **blocks**:
- 582 `data/analyses/` URLs — scan-covered, safe.
- 169 site/DB-only URLs need consumer_state; **59 are gaps** (not local, not in
  consumer_state):
  - **57 backfillable** — in `frettasafn.articles`, just missing a consumer_state row
    (pre-Phase-3 / write-through gaps). A `mark_urls(..., "processed")` fixes these.
  - **2 orphan** — visir.is URLs with a slug-form mismatch, not in `frettasafn.articles`
    (can't be backfilled by URL).

This disproves the plan's "986 > 704 ⇒ superset" assumption (more rows ≠ full coverage).
**Remediation before the deletions can proceed (operator decision):** backfill the 57
via `mark_urls` (writes to shared frettasafn consumer_state), and decide the 2 orphans
(accept the small re-analysis risk, or fix the URL-form mismatch). Re-run the gate to 0
gaps, then do the deletions below.

## Backfill design (resolved 2026-06-02) — user-approved

A read-only probe characterised the 2 orphans and **overturned a wrong assumption before
any code was written** (the value of probing real data).

### What the 2 orphans actually are

Both visir.is orphans DO exist in `frettasafn.articles`, under the same permanent
`/g/<id>/` but a drifted (re-published) slug:

| esbvaktin-stored URL | frettasafn URL (slug differs) | article_id |
|---|---|---|
| `…/g/20262853438d/thridjungur-and-vigur-at-kvaeda-greidslunni` | `…andvigur-atkvaedagreidslunni` | `c3f9a5f8dfaa91c9` |
| `…/g/20262859056d/gudrun-…-henni-radgjafi-` | `…-henni-godur-radgjafi-` | `ff54198e3b0a1c56` |

Visir re-slugs articles post-publish; with 9,497 visir articles in frettasafn this drift
class is recurring, not a one-off.

### Corrected coverage model (the assumption the probe overturned)

"Mark the 2 article_ids ⇒ gate reaches 0" is **WRONG**. The gate audits coverage via
`is_known_url(esbvaktin_url)`, which resolves URL→article_id by exact-then-prefix match —
a drifted slug structurally cannot resolve, so a `consumer_state` row keyed by article_id
is never connected to the esbvaktin-stored URL the gate checks.

Two distinct dedup truths follow:
- **Runtime/future protection** keys off *frettasafn's canonical* URL (future re-discovery
  comes through frettasafn's scan) → marking the `article_id` genuinely dedupes future
  reposts.
- **The gate** audits *esbvaktin's stored* URL form → a false-negative for slug-drifted
  articles. It must be *told* these 2 are accounted for (a committed allowlist), because no
  write reconciles a URL that cannot resolve.

So the orphans are handled on BOTH sides: mark the article_ids (real protection) AND
exclude the esbvaktin URLs in the gate (honest 0).

### Chosen approach — `--backfill` mode + orphan id-map

`scripts/retire_registry.py` gains a `--backfill` flag. Run without it, it stays the
read-only gate (unchanged behaviour).

```python
# Verified slug-drift orphans: esbvaktin-stored (normalised) URL → frettasafn article_id.
# Slug drifted post-publish so is_known_url can't resolve the stored URL; we mark the
# article_id (future reposts via frettasafn's canonical URL stay deduped) and the gate
# excludes these URLs from its candidate set.
ORPHAN_BACKFILL = {
    "https://www.visir.is/g/20262853438d/thridjungur-and-vigur-at-kvaeda-greidslunni":
        "c3f9a5f8dfaa91c9",
    "https://www.visir.is/g/20262859056d/gudrun-um-thorgerdi-yfirlaeti-hefur-ekki-reynst-henni-radgjafi-":
        "ff54198e3b0a1c56",
}
```

`--backfill`:
1. `mark_urls(sorted(gaps), "processed", metadata_per_url=…)` → writes the 57 that resolve,
   returns the 2 as `unmatched`.
2. **Assert** `set(unmatched) == set(ORPHAN_BACKFILL)` — if the gap set ever shifts, fail
   loudly rather than silently mis-backfill.
3. `mark_articles(list(ORPHAN_BACKFILL.values()), "processed", metadata=…)` for the 2.
4. Backfilled rows carry `metadata = {"backfilled_by": "xrepo-01", "reason":
   "pre-Phase-3 gap"}` for auditability.

Gate `main()`: subtract the normalised `ORPHAN_BACKFILL` keys from `candidates` so a
post-backfill run reports **0**.

### TDD plan (backfill — failing tests first)
1. `uncovered_urls` — unchanged, stays pure (existing tests still pass).
2. Gate excludes `ORPHAN_BACKFILL` URLs from `candidates` (they never count as gaps).
3. `--backfill` path with `mark_urls`/`mark_articles` **monkeypatched (NO real DB write)**:
   asserts it calls `mark_urls` with the gap set and `mark_articles` with the 2 orphan ids;
   asserts the `unmatched == ORPHAN_BACKFILL.keys()` guard raises on divergence.

### Execution gates (operator = user)
- Writing this spec + the TDD'd code involves **zero** real writes.
- **Gate ①** (explicit go-ahead): run `--backfill` against the real frettasafn DB
  (59 `consumer_state` rows) + re-run the plain gate → expect 0.
- **Gate ②** (explicit go-ahead): the irreversible deletions below.

## Deletion — DEFERRED (true scope: 3-consumer re-homing, found 2026-06-02)

The gate proved *data* coverage (consumer_state now has 0 gaps) but not *code* coverage.
A `grep` for registry references found **three** consumers, not one — so the original
"delete the builder + check_duplicate's branch + the json" plan is unsafe: it would break a
live batch script (`register_article_sightings.py` does `sys.exit(1)` if the registry is
absent). The full retirement is therefore a 3-consumer re-homing, deferred to its own
focused pass (user decision 2026-06-02: bank gate ①, defer the deletion).

**The three consumers to re-home (all off `data/article_registry.json`):**
1. `check_duplicate.py` — drop the registry branch of `load_processed()` (keep the
   `data/analyses/` scan), remove `REGISTRY_PATH`, the `--rebuild` flag + its
   `build_registry` import, the staleness warning, and the now-unused `time` import. Keep
   `check_url`/`check_title`/`check_content`, the `consumer_state` check, and the
   frettasafn-id scan. (It already has consumer_state + scan, so it loses only title-fuzzy
   matching against site/DB-only articles — the documented acceptable loss.)
2. `register_article_sightings.py` — `load_unregistered_articles()` uses the registry's
   `in_db`/`analysis_dir` flags and `sys.exit(1)`s if the file is absent. Re-home: scan
   `data/analyses/` for analysis dirs and recompute "analysed but not yet in DB" from a
   `claim_sightings` query (by `source_url`). **Load-bearing — a core post-analysis batch
   step; breaking it breaks registration.**
3. `manage_inbox.py` — `_load_processed_urls()` (two call sites) reads the registry for
   inbox dedup. Re-home to consumer_state via a new read-only
   `frettasafn_state.processed_urls(consumer_id)` helper. Likely partly vestigial: `scan_eu`
   already anti-joins consumer_state server-side, so confirm whether the manual-add path
   still needs it before re-homing vs removing.

**Only after all three are re-homed + verified:** delete `scripts/build_article_registry.py`
and `data/article_registry.json` (gitignored — local cleanup); update each module docstring.
Removes ~240 lines, the esbvaktin→site filesystem coupling, and the drift class.

Reversibility: the two tracked scripts stay in git history; `article_registry.json` is a
gitignored derived artifact (its only builder is removed in the same pass — acceptable, it
is no longer needed).

## TDD plan (gate + deletions — failing tests first)
1. `uncovered_urls`: every source URL present in consumer_state ⇒ empty set; a URL with
   `state=None` ⇒ in the returned gap set; an empty source set ⇒ empty. (Done — green.)
2. Deletion (deferred) — each re-homed consumer needs its own RED→GREEN:
   - `check_duplicate.load_processed` ignores a *present* registry file and returns the
     `data/analyses/` data — the meaningful failing test, since "no registry file present"
     passes trivially today (the existing scan fallback) and proves nothing.
   - `register_article_sightings.load_unregistered_articles` builds the worklist from
     `data/analyses/` + a `claim_sightings` query, with no registry.
   - `manage_inbox._load_processed_urls` reads consumer_state (via a new read-only
     `processed_urls` helper) instead of the registry.

## Out of scope / follow-ups
- Re-homing the content fallback to `frettasafn.articles.content` (Option B) — touches
  the shared frettasafn boundary; the non-local-repost edge case is rare and consumer_state
  covers exact URLs. Deferred.
- Auto-backfilling consumer_state gaps — the gate only reports; backfill stays a
  deliberate operator step via `mark_urls`.
