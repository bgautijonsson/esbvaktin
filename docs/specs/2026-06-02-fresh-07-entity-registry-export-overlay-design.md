# fresh-07 — Entity registry as export overlay (entity-registry Phase 3)

**Date:** 2026-06-02
**Status:** DESIGN — user-approved (Option A, full overlay incl. adds). No code yet.
**Branch:** `pipeline-optimisation`
**Plan ref:** `esbvaktin-pipeline-optimisation-2026-06.html` → fresh-07. Also the
entity-registry project's documented-but-unstarted **Phase 3** (see
`docs/superpowers/specs/2026-04-02-entity-registry-design.md`).

## Goal

Make `export_entities.py` honour the curated registry (`entities` + `entity_observations`)
so human `/entity-review` decisions reach the public Raddirnar page — without dropping the
entities the registry does not yet contain. An **overlay**: the export still computes the
full set; the registry then corrects it.

## Reframe — what the real data says (read-only probe, 2026-06-02)

The plan's premise ("~140 curated records never reach the 1,106-entity export") is
**inverted** by the data:

| metric | value |
|---|---|
| export entities (heuristic) | 1105 |
| registry entities (curated) | 966 |
| export-only (registry lacks) | **141** — low-mention noise (`anonymous`, `blog-is`, …) |
| registry-only (export lacks) | **2** (1 real + `vinstri-graen` placeholder) |
| matched | 964 |
| with `locked_fields` | **1** — `erna-bjarnadottir` (`locked=['stance']`, `anti_eu`) |
| confirmed | 491 |
| stance-disagree | 823 — but mostly `insufficient_data`↔`neutral`, all `locked=[]` |
| type-disagree | 4 — all `confirmed` |

So the registry is a near-**subset**, hard curation is tiny today (1 lock), and the
divergence is export-HAS-MORE (registry incomplete), not export-MISSING-curation.
Registry-primary is therefore **unsafe** (it would drop 141). The overlay's value is
forward-looking: every future lock/confirm then flows to the site automatically.

## Design — `apply_registry_overlay()` (functional core) + I/O shell

Insert in `export_entities()` after the enrich steps (`_ensure_party_entities`) and
**before** `_generate_descriptions` — so corrections + adds flow into descriptions and the
final sort includes adds.

`apply_registry_overlay(export_entities: dict[str, dict], registry: list[Entity],
obs_by_entity: dict[int, list[EntityObservation]]) -> dict` — pure (registry + observations
injected), TDD'd with fixtures, no DB. Authority:

1. **Locked fields → always override** (unconditional — independent of `verification_status`;
   erna is `needs_review` yet stance-locked). For each matched entity, copy each field in
   `entity.locked_fields` from the registry via a field map (registry → export key):
   `canonical_name→name`, `entity_type→type`, `subtype→subtype`, `stance→stance`,
   `party_slug→party`. **Non-`None` registry values only** — a lock never wipes a computed
   value with `None`. A `stance` lock overrides **both** `stance` and `stance_score` (kept
   consistent). [today: erna's stance → `anti_eu`.]
2. **Confirmed → honour registry `type`/`subtype`** (non-`None` only) where they differ from
   the export's.
   [today: the 4 — `evropuhreyfing`, `fjarmalaradherra`, `samtok-verslunar-og-thjonustu-svth`,
   `utanrikisradherra-islands`.] Structural identity a human vetted; not applied to
   unconfirmed entities (their type-diff is the registry's own auto-guess).
3. **Registry-only + `confirmed` + ≥1 non-dismissed observation → add.** Reconstruct the
   export dict from the Entity + its observations:
   - `slug←slug`, `name←canonical_name`, `type←entity_type`, `subtype←subtype`,
     `stance←stance`, `stance_score←stance_score`, `party←party_slug`,
   - `articles` = distinct non-dismissed `obs.article_slug`; `mention_count` = len(articles),
   - `claim_count` = total `len(obs.claim_indices)` (best-effort — the observation carries
     indices, not resolved claim slugs/verdicts), `credibility` = None,
   - `description` = "" (filled by the subsequent `_generate_descriptions`).
   [today: `eva-bjork-benediktsdottir` (confirmed, 1 obs). `vinstri-graen` is `needs_review`
   → auto-skipped, avoiding a duplicate VG.]
4. **No blanket stance replacement.** The 823 `insufficient_data`↔`neutral` label-diffs stay
   as the export computes (honest for low-mention). Stance changes **only** via rule 1.
5. **Alias/merge folding → deferred.** Collapsing export duplicates via registry aliases is
   the fiddly part and is not needed to honour stored curation. Out of scope.

### Slug contract
Both sides key by `icelandic_slugify` (single-sourced in xrepo-05). The shell logs any
registry slug that neither matches an export entity nor is added (drift visibility); the
overlay never invents slugs.

### I/O shell (in `export_entities()`)
```python
from esbvaktin.entity_registry.models import VerificationStatus
from esbvaktin.entity_registry.operations import get_all_entities, get_observations_for_entity
from esbvaktin.ground_truth.operations import get_connection

export_slugs = set(entities)
with get_connection() as conn:
    registry = get_all_entities(conn)
    add_candidates = [
        e for e in registry
        if e.slug not in export_slugs and e.verification_status == VerificationStatus.CONFIRMED
    ]
    obs_by_entity = {e.id: get_observations_for_entity(e.id, conn) for e in add_candidates}
entities = apply_registry_overlay(entities, registry, obs_by_entity)
```
Observations are fetched only for the handful of registry-only-confirmed add candidates, not
all 966 (avoids 966 round-trips). If the DB is unreachable, the overlay is skipped with a
logged warning — the export degrades to its current heuristic output rather than failing
(consistent with the existing `_load_db_verdict_map` try/except posture).

## TDD plan (failing tests first)

Pure-function tests on `apply_registry_overlay` with fixture export dicts + `Entity` /
`EntityObservation` objects (no DB):
1. Locked `stance` → overrides export's `stance` **and** `stance_score`; an unlocked entity's
   stance is left untouched (the `insufficient_data`↔`neutral` case).
2. Locked non-stance field (e.g. `type`) → overridden; a different non-locked field on the
   same entity is left untouched.
3. Confirmed entity with a differing `type` → overridden; an **unconfirmed** entity with a
   differing `type` → left untouched.
4. Registry-only + confirmed + observations → added with reconstructed fields
   (name/type/stance/articles/mention_count); a registry-only **needs_review** entity
   (`vinstri-graen`) → **not** added; a confirmed registry-only entity with **no**
   non-dismissed observations → not added.
5. A matched entity present in both is not duplicated; the returned dicts keep the keys the
   rest of the pipeline expects (`slug`/`name`/`type`/`stance`/`stance_score`/`articles`/…).

A real-data check (read-only) after GREEN: run the export and assert the overlaid set is the
heuristic set + 1 add, with erna's stance = `anti_eu` and the 4 type corrections applied.

## Out of scope / follow-ups
- **Registry completeness** (the 141 export-only): a future reconcile (register their
  observations) would let the export flip to registry-**primary** (the plan's end-state) and
  shed the heuristic recompute + `_NAME_ALIASES`. Deferred — needs a noise-vs-real triage
  policy.
- **Alias/merge folding** (rule 5) — collapse export duplicates via registry aliases.
- **Stance for confirmed-but-unlocked** entities — deliberately NOT overridden; revisit only
  if `/entity-review` starts locking stances at volume.
