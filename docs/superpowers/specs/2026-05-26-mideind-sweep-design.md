# Miðeind sweep — surface IS fields since 2026-05-02

**Date:** 2026-05-26
**Status:** Approved, in implementation

## Goal

Apply Miðeind grammar correction to Icelandic prose that has been added or updated since the last site push (2026-05-02), focusing on user-visible surface fields.

The pipeline writes new IS text continuously but never routes it through Málstaður on the way to the DB/site. This sweep closes the gap retroactively for everything added since the last sync, and introduces the missing tooling so future sweeps are incremental.

## Scope

| Source | Rows / files | Chars | Cost |
|---|---:|---:|---:|
| New claims (`canonical_text_is` + `explanation_is` + `missing_context_is`) | 286 | 253k | ~2,534 kr |
| Updated claims (`canonical_text_is` only) | 295 | 32k | ~319 kr |
| New evidence (`statement_is` + `source_description_is` + `caveats_is`) | 10 | 6k | ~62 kr |
| New capsules (`_report_final.json["capsule"]`) | 116 | 63k | ~628 kr |
| New editorials (W16, W18, W19, W20) | 4 | ~12k | ~120 kr |
| **Total** | | **~366k** | **~3,663 kr** |

Out of scope: pre-2026-05-02 prose (already on site; revisit if a follow-up pass is wanted), claim `epistemic_explanation`/other non-public IS fields, debate summaries (separate sweep if needed).

## Architecture

Two patterns, picked to match where each text lives.

### DB-backed text — hash-tracked correction

Mirror the existing `scripts/improve_evidence_is.py correct` recipe:

1. Schema migration — add `claims.is_proofread_hash TEXT NULL`.
2. New script `scripts/improve_claims_is.py` with `status` / `correct` subcommands.
3. Hash = `md5(canonical_text_is || explanation_is || missing_context_is)`.
4. Filter pending = `stored_hash IS NULL OR stored_hash != current_hash`.
5. Initial run filtered to `created_at >= '2026-05-02' OR updated_at >= '2026-05-02'` to scope cost; later runs default to "everything pending" so reassessments are picked up automatically.

Evidence: no code change. Re-running `improve_evidence_is.py correct` picks up the 10 new + 22 stale rows via existing hash-mismatch detection.

### File-backed text — file walker

- **Capsules**: `scripts/correct_capsules.py --since 2026-05-02`. Walks `data/analyses/*/_report_final.json` with mtime newer than cutoff, reads the `capsule` field, applies `MalstadurClient.correct_grammar`, writes the file back. Also updates `_capsule.txt` so the two stay in sync.
- **Editorials**: existing `scripts/correct_icelandic.py check-editorial --fix --malfridur path` invoked for the 4 new weeks.

## Components

- `migrations/2026-05-26_claims_is_proofread_hash.sql` (or inline migration via Python)
- `scripts/improve_claims_is.py` (~150 LOC; mirror evidence script)
- `scripts/correct_capsules.py` (~80 LOC; file walker)

## Safety

- **Idempotence via hash tracking.** Re-runs after correction are free no-ops (no API calls).
- **Smoke check on first run.** Log diff between original and corrected for the first 5 entries; abort the rest if Miðeind misbehaves (e.g. wholesale rewrites or empty results).
- **Per-entry transactions.** Each row commits atomically; a mid-run failure leaves the DB in a consistent state.
- **DB backups.** Daily launchd backup covers rollback if a bad run lands.
- **Rate limits.** Sequential calls with 0.5s delay + retry/backoff already baked into `MalstadurClient`.
- **Cost-aware.** `--dry-run` mode on both scripts; `--limit N` to cap a run.

## Execution sequence

1. Apply schema migration.
2. `uv run python scripts/improve_evidence_is.py correct` — picks up evidence delta via hash.
3. `uv run python scripts/improve_claims_is.py correct --since 2026-05-02` — first run on claims.
4. `uv run python scripts/correct_capsules.py --since 2026-05-02` — sweep capsules.
5. `uv run python scripts/correct_icelandic.py check-editorial --fix --malfridur data/overviews/2026-W{16,18,19,20}/editorial.md` (four invocations).
6. `./scripts/run_export.sh --site-dir ~/esbvaktin-site` — re-export the 7 bundles.
7. `cd ~/esbvaktin-site && python3 scripts/validate_export.py && npm run build` — validate and local build.
8. Commit and push to deploy.

## Out of scope / follow-ups

- Pre-2026-05-02 corpus sweep (separate decision; ~22k kr if ever wanted).
- Pipeline integration so future writes go through Málstaður at write time (write hooks on `register_claim`, `assemble_report`, etc.). Out of scope here — the retroactive sweep is the immediate need; build-time correction is a design conversation of its own.
