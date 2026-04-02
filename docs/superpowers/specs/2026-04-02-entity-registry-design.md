# Entity Registry & Data Quality Pipeline

**Date**: 2026-04-02
**Status**: Draft
**Purpose**: Canonical entity registry with automated maintenance and interactive human review, ensuring correct names, stances, and no duplicates on `/raddirnar/`.

## Problem

The current entity system has no dedicated database table. Entities exist only in per-analysis `_entities.json` files (261 reports) and are reconstituted at export time by `export_entities.py` (1,034 lines). This causes:

- **Name duplication** from Icelandic morphology ("Bjarni Benediktsson" vs "Bjarna Benediktssonar") managed by a brittle 600-line hardcoded alias dict
- **Stance misattribution** from per-article LLM extraction averaged without validation — one wrong extraction can flip an entity's overall label
- **No authority** — entity metadata (stance, role, party) is not versioned, audited, or human-reviewed
- **Compounding errors** — duplicates, wrong types, stale roles, and attribution confusion only surface at export time when the full corpus is merged

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Architecture | Two tables: `entities` + `entity_observations` | Clean separation of canonical truth from per-article data points |
| Bootstrap | Big-bang migration of all 541 existing entities | Avoids running two parallel systems; entities and observations exist already |
| Auto-matching | Confidence-tiered (HIGH/MEDIUM/LOW) | Pipeline keeps flowing for common cases; uncertain cases queue for human review |
| Authority model | Registry wins; observations inform but don't override | Prevents LLM extraction errors from silently corrupting canonical data |
| Name matching | Hybrid: BIN lemmatisation + growing alias table | BIN handles inflections; alias table handles nicknames, abbreviations, foreign names |
| Review | Two modes: agent maintenance (automated) + interactive skill (human-in-the-loop) | Automated for the obvious, human for the judgment calls |

## Database Schema

### `entities` table (canonical registry)

```sql
CREATE TABLE entities (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('individual', 'party', 'institution', 'union')),
    subtype TEXT CHECK (subtype IN ('politician', 'media')),
    stance TEXT CHECK (stance IN ('pro_eu', 'anti_eu', 'mixed', 'neutral')),
    stance_score REAL CHECK (stance_score BETWEEN -1.0 AND 1.0),
    stance_confidence REAL CHECK (stance_confidence BETWEEN 0.0 AND 1.0),
    party_slug TEXT,
    althingi_id INTEGER,
    aliases TEXT[] DEFAULT '{}',
    roles JSONB DEFAULT '[]',
    notes TEXT,
    verification_status TEXT NOT NULL DEFAULT 'auto_generated'
        CHECK (verification_status IN ('auto_generated', 'needs_review', 'confirmed')),
    is_icelandic BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    verified_at TIMESTAMPTZ,
    verified_by TEXT
);

CREATE UNIQUE INDEX idx_entities_slug ON entities(slug);
CREATE INDEX idx_entities_aliases ON entities USING GIN(aliases);
CREATE INDEX idx_entities_verification ON entities(verification_status);
```

The `roles` JSONB column stores an array of role history entries:
```json
[
    {"role": "forsaetisradherra", "from": "2024-01-01", "to": null},
    {"role": "fjarmalaradherra", "from": "2021-06-01", "to": "2023-12-31"}
]
```

### `entity_observations` table (per-article extractions)

```sql
CREATE TABLE entity_observations (
    id SERIAL PRIMARY KEY,
    entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    article_slug TEXT NOT NULL,
    article_url TEXT,
    observed_name TEXT NOT NULL,
    observed_stance TEXT,
    observed_role TEXT,
    observed_party TEXT,
    observed_type TEXT,
    attribution_types TEXT[] DEFAULT '{}',
    claim_indices INTEGER[] DEFAULT '{}',
    match_confidence REAL,
    match_method TEXT CHECK (match_method IN ('exact', 'alias', 'lemma', 'fuzzy', 'manual')),
    disagreements JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_observations_entity ON entity_observations(entity_id);
CREATE INDEX idx_observations_article ON entity_observations(article_slug);
CREATE INDEX idx_observations_flagged ON entity_observations(entity_id)
    WHERE disagreements IS NOT NULL;
CREATE INDEX idx_observations_unmatched ON entity_observations(entity_id)
    WHERE entity_id IS NULL;
```

## Name Matching Pipeline

When a new entity is extracted from an article, it goes through a matching cascade. Each step is tried in order; the first match wins.

### Matching cascade

| Step | Method | Confidence |
|---|---|---|
| 1 | Exact match on `canonical_name` | HIGH (0.95) |
| 2 | Exact match on any entry in `aliases[]` | HIGH (0.95) |
| 3 | Lemmatise via BIN, match against lemmatised `canonical_name` | HIGH (0.90) |
| 4 | Lemmatise via BIN, match against lemmatised `aliases[]` | MEDIUM (0.75) |
| 5 | Subset match: all words of shorter name in longer, minimum 2 words, same `entity_type` | MEDIUM (0.60) |
| 6 | Weak subset (1 overlapping word) or type mismatch | LOW (0.30) |
| 7 | No match | NEW (0.0) |

### Confidence tiers and actions

| Tier | Threshold | Action |
|---|---|---|
| **HIGH** | >= 0.9 | Auto-link silently. Observation recorded. No flag raised. |
| **MEDIUM** | 0.5 - 0.9 | Auto-link but flag `needs_review`. Observation records any disagreements. |
| **LOW** | < 0.5 | `entity_id = NULL` on observation. New entity created as `auto_generated` + `needs_review`. Queued for interactive review. |

### Disagreement detection

After matching, the observation is compared against the registry entry. Disagreement on any of these fields is logged in the `disagreements` JSONB column:

- **stance**: observation stance != registry stance (ignoring `neutral` observations)
- **role**: observation role not found in any registry `roles[]` entry
- **party**: observation party != registry `party_slug` (after normalisation)
- **type**: observation type != registry `entity_type`

Any disagreement bumps the observation to at least MEDIUM (flagged) even if the name match was HIGH confidence.

### BIN integration

- Use `get_lemma` from the `icelandic-morphology` MCP server for lemmatisation
- Cache lemma lookups in a local dict during each pipeline run (names repeat across claims)
- Names not in BIN (foreign names, organisation names): fall back to exact/subset matching only
- When an entity is confirmed during review, all observed name variants are added to `aliases[]`

### Confidence threshold config

```python
MATCH_THRESHOLDS = {
    "auto_link": 0.9,   # above: silent auto-link
    "flag": 0.5,         # above: auto-link + flag for review
    # below flag: queue for review, don't auto-link
}
```

Adjustable. The review skill reports hit rates to inform threshold tuning.

## Migration & Bootstrap

### Big-bang migration script (`scripts/migrate_entities.py`)

1. **Run current merge logic** — loads all `_entities.json` files, deduplicates by slug, enriches with Althingi roster and media classification (reuses existing `export_entities.py` logic)
2. **Insert into `entities` table** — each merged entity becomes a row with `verification_status = 'auto_generated'`
3. **Consume hardcoded dicts** — `_NAME_ALIASES` entries become `aliases[]`, `_CANONICAL_NAMES` become `canonical_name`, `_ROLE_OVERRIDES` become `roles[]` entries
4. **Backfill observations** — for each source `_entities.json`, create `entity_observations` rows linking to the entity, preserving per-article stance/role/attribution data
5. **Run matching pipeline** on observations to populate `match_confidence`, `match_method`, and `disagreements`
6. **Generate migration report** — summary plus flagged issues

### Migration report categories

| Category | What it flags |
|---|---|
| Potential duplicates | Entities whose aliases or lemmatised names overlap with another entity |
| Stance conflicts | Entities where per-article observations disagree with computed stance |
| Role inconsistencies | Same entity with contradictory roles across articles |
| Type mismatches | Observations where entity_type differs from merged value |
| Orphan observations | Observations that couldn't be confidently linked |
| Placeholder entities | Party/institution entities with zero claims |

### Properties

- **Idempotent** — checks for existing data before inserting; safe to re-run during development
- **Non-destructive** — current export pipeline continues to work unchanged
- **Auditable** — every decision recorded with confidence scores and match methods

## Maintenance Modes

### Mode 1: Agent maintenance (automated)

A new module `src/esbvaktin/pipeline/entity_matcher.py` — deterministic Python code (BIN lookups, string matching, confidence scoring). No LLM involved.

Called by `register_article_sightings.py` after claim registration:

```
_entities.json → entity_matcher.match_entities()
    → HIGH: auto-link, record observation
    → MEDIUM: auto-link, flag, record observation with disagreements
    → LOW/NEW: create unmatched observation, create auto_generated entity if new
    → return summary: {"auto_linked": 3, "flagged": 1, "new_entities": 0, "disagreements": ["stance"]}
```

The summary is printed at the end of analysis.

### Mode 2: Interactive review skill (`/entity-review`)

**`/entity-review`** — work the review queue:

1. Query flagged observations and `needs_review` entities
2. Group by issue type (duplicates, stance conflicts, new entities, disagreements)
3. Present items with full context: observation data, registry entry, article excerpt, clickable URL
4. User decides: confirm, merge, edit, reject
5. Decisions applied to DB immediately
6. Confirmed entities get `verification_status = 'confirmed'`, `verified_at = NOW()`

**`/entity-review status`** — dashboard:

- Review queue depth by issue type
- Auto-link accuracy stats (last N days: HIGH/MEDIUM matches later corrected)
- Coverage: % of entities at each verification status
- Surfaced in `/health` as queue depth

### Phase 2: Browser review UI

The `/entity-review` skill generates a local HTML page served by a Python HTTP server:

- Entity cards with all fields, aliases, observation history
- Side-by-side comparison for potential duplicates
- Inline editing for name, stance, role, type
- Merge button for duplicates (pick canonical, absorb aliases)
- Stance timeline (observations plotted over time)
- Filter/sort by issue type, entity type, confidence tier
- Decisions POST to local API endpoint, DB updated in real time

## Export Pipeline Integration (Phase 3)

### What the registry owns (static, from review)

`canonical_name`, `slug`, `entity_type`, `subtype`, `stance`, `stance_score`, `stance_confidence`, `party_slug`, `althingi_id`, `aliases`, `roles`, `is_icelandic`, `verification_status`

### What's still computed at export time (dynamic)

| Field | Source |
|---|---|
| `mention_count` | `COUNT(entity_observations)` |
| `claim_count` | Active attributions (asserted/quoted/paraphrased) from observations |
| `articles` | Distinct `article_slug` from observations |
| `attribution_counts` | Aggregate `attribution_type` from observations |
| `credibility` | Verdict distribution from `claim_sightings` (existing logic) |
| `althingi_stats` | Read from `althingi.db` (speech counts change as debates are indexed) |
| `outlet_stats` | For media entities: computed from article corpus |

### Transition

- `export_entities.py --from-registry` flag during Phases 1-2 for testing
- Old merge path remains default until Phase 3 is validated
- Phase 3: registry path becomes default, old merge code and hardcoded dicts removed
- Output JSON format unchanged — site needs zero modifications

### Validation

A diff test confirms `--from-registry` output matches old export output before the switchover.

## Phases & Success Criteria

### Phase 1: Registry + Migration + Maintenance

**Deliverables**:
- `entities` and `entity_observations` tables
- `scripts/migrate_entities.py` — big-bang migration
- `src/esbvaktin/pipeline/entity_matcher.py` — matching cascade with BIN integration
- Wired into `register_article_sightings.py`
- Migration report
- Tests for matching, confidence tiers, disagreement detection

**Success criteria**:
- All 541 entities migrated with observations backfilled
- Migration report identifies duplicate candidates and stance conflicts
- New analyses produce observations with correct confidence tiers
- Zero regression in current export pipeline

### Phase 2: Browser Review UI + Skill

**Deliverables**:
- `/entity-review` skill (terminal mode)
- `/entity-review status` dashboard
- Local HTTP review app (Python server + HTML/JS)
- Entity cards, inline editing, merge UI, stance timeline, duplicate comparison
- Integration with `/health`

**Success criteria**:
- All migration-flagged items reviewed and resolved
- All 541 entities reach `confirmed` or deliberate `auto_generated`
- Review decisions persist immediately to DB
- Auto-link accuracy stats tracked and visible

### Phase 3: Export Rewire

**Deliverables**:
- `export_entities.py --from-registry` validated
- Simplified export (~200-300 lines, down from ~1,034)
- Removal of `_NAME_ALIASES`, `_CANONICAL_NAMES`, `_ROLE_OVERRIDES`
- Removal of old merge logic

**Success criteria**:
- Registry export output identical to old export (diff test)
- Site renders identically
- Old code removed, no dual paths

### North star

Every entity on `/raddirnar/` has been human-reviewed, has the correct stance, and has no duplicates. The system maintains this quality automatically as new articles flow in, surfacing only uncertain cases for review.
