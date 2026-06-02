# xrepo-01 — Retire article_registry.json (consumer_state as sole dedup truth)

**Date:** 2026-06-02
**Status:** approved (Option A: minimal safe retirement); implementing gate-first
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
`is_known_url`. Pure core: `uncovered_urls(source_urls, state_by_url) -> set` returns
URLs absent from `consumer_state`.
- **0 gaps ⇒ safe** — proceed with the deletions.
- **gaps ⇒ ABORT** — print the uncovered URLs; the operator backfills them into
  `consumer_state` (the existing additive `mark_urls` helper) and re-runs before any
  deletion. The gate never writes anything.

I run the gate on real data before the deletion commit; the result decides the path.

## Deletions (only after the gate passes)

- `check_duplicate.py`: drop the registry branch of `load_processed()` (keep the
  `data/analyses/` scan), remove `REGISTRY_PATH`, the `--rebuild` flag + its
  `build_registry` import, and the staleness warning. Keep `check_url`/`check_title`/
  `check_content`, the `consumer_state` check, and the frettasafn-id scan.
- Delete `scripts/build_article_registry.py` and `data/article_registry.json` (the
  latter is gitignored — a local cleanup).
- Update the module docstring to describe consumer_state + `data/analyses/` only.

Removes ~240 lines, the esbvaktin→site filesystem coupling, and the drift class.

## TDD plan (failing tests first)
1. `uncovered_urls`: every source URL present in consumer_state ⇒ empty set; a URL with
   `state=None` ⇒ in the returned gap set; an empty source set ⇒ empty.
2. `check_duplicate.load_processed` (importlib-loaded, ANALYSES_DIR pointed at a fixture,
   no registry file): scans `data/analyses/` and returns the fixture report's
   title/url — proving the registry-free path works.

## Out of scope / follow-ups
- Re-homing the content fallback to `frettasafn.articles.content` (Option B) — touches
  the shared frettasafn boundary; the non-local-repost edge case is rare and consumer_state
  covers exact URLs. Deferred.
- Auto-backfilling consumer_state gaps — the gate only reports; backfill stays a
  deliberate operator step via `mark_urls`.
