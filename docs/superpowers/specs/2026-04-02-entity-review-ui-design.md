# Entity Review UI — Browser-Based Interactive Review

**Date**: 2026-04-02
**Status**: Draft
**Purpose**: Interactive browser UI + Claude Code skill for reviewing, editing, and confirming entities in the canonical registry.
**Depends on**: Entity Registry Phase 1 (complete — `docs/superpowers/specs/2026-04-02-entity-registry-design.md`)

## Problem

The entity registry contains 609 entities migrated from the old merge-based system. 45 have stance conflicts, 9 have type mismatches, and all 609 are `auto_generated` — none have been human-reviewed. New articles will add more entities and flag disagreements. A terminal-only review workflow is too slow for 600+ entities; a browser UI with inline editing and a "discuss" bridge to the terminal gives the right balance of speed and depth.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Layout | Split panel: sidebar filters + entity card list | Start reviewing immediately, no extra click to enter a category |
| Card style | Full detail (no expand/collapse) | All info visible — stance breakdown, observations, aliases. No hidden state. |
| Edit depth | Two levels: inline for quick edits, detail panel for deep dives | Most edits are a single dropdown; complex edits (merge, relink, roles) need more space |
| Terminal bridge | "Discuss" button sends entity to `/entity-review` skill | Combines visual browsing with conversational reasoning for hard cases |
| Bulk operations | Via terminal chat, not browser UI | Natural language is better than building a complex bulk-action UI |
| Sync model | Manual refresh after terminal operations | Avoids polling/SSE complexity; I tell user when to refresh |
| Tech stack | Python `http.server` + vanilla HTML/JS | No new dependencies; single file frontend; project already uses Python for everything |
| Auth | None (localhost-only, ephemeral) | Single-user dev tool, server binds to 127.0.0.1 |

## Schema Changes

Two additions to existing tables:

### `entities` table — add `locked_fields`

```sql
ALTER TABLE entities ADD COLUMN IF NOT EXISTS locked_fields TEXT[] DEFAULT '{}';
```

When a field is manually overridden (e.g. stance set to "mixed"), it gets added to `locked_fields`. Future observations that disagree with a locked field are still recorded and flagged on the observation, but:
- The entity's `verification_status` is NOT changed to `needs_review`
- The matcher does NOT suggest changing the registry value
- The observation `disagreements` JSONB still records the disagreement for audit

### `entity_observations` table — add `dismissed`

```sql
ALTER TABLE entity_observations ADD COLUMN IF NOT EXISTS dismissed BOOLEAN DEFAULT FALSE;
```

Dismissed observations are kept for audit but excluded from:
- Stance computation (stance averaging should ignore dismissed observations)
- Observation counts displayed on entity cards
- Auto-link accuracy stats

## Architecture

Three components:

### 1. Python API server (`scripts/entity_review_server.py`)

Lightweight HTTP server using Python's built-in `http.server`. No framework dependency. Serves the static HTML page and handles JSON API requests. Talks to PostgreSQL via the existing `entity_registry.operations` module.

Binds to `127.0.0.1` only. Ephemeral — starts when `/entity-review` is invoked, stops when the session ends.

### 2. Static review app (`src/esbvaktin/entity_registry/review_app/index.html`)

Single self-contained HTML file with embedded CSS and JS. No build step, no npm, no framework. Vanilla JS with `fetch()` calls to the API. Uses DESIGN.md colour tokens and font stack.

### 3. `/entity-review` skill (`.claude/skills/entity-review.md`)

Orchestrates the session: launches server, opens browser, watches for discuss events, handles terminal commands for bulk operations and entity lookups.

### Data flow

```
Browser (HTML/JS) ←→ API server (Python) ←→ PostgreSQL
                          ↕
                    /entity-review skill (terminal)
                          ↕
                    discuss file (entity slug → terminal context)
```

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Serve the static HTML review app |
| `GET` | `/api/dashboard` | Counts by issue type, verification status breakdown, total entities |
| `GET` | `/api/entities` | Entity list with filters (see below) |
| `GET` | `/api/entities/:slug` | Full entity detail + observation list with article URLs |
| `PATCH` | `/api/entities/:slug` | Update entity fields. Returns updated entity. |
| `POST` | `/api/entities/:slug/confirm` | Set `verification_status=confirmed`, `verified_at=NOW()`. Returns updated entity. |
| `POST` | `/api/entities/:slug/delete` | Delete entity, unlink observations (`entity_id=NULL`). Returns `{ok: true}`. |
| `POST` | `/api/entities/merge` | Body: `{keep_slug, absorb_slug}`. Returns updated keep entity. |
| `PATCH` | `/api/observations/:id` | Update observation: `{dismissed: true}` or `{entity_id: N}` (relink). Returns updated observation. |
| `POST` | `/api/entities/:slug/aliases` | Body: `{add: ["name"]}` or `{remove: ["name"]}`. Returns updated entity. |
| `POST` | `/api/entities/:slug/roles` | Body: `{add: {role, from_date, to_date}}` or `{remove_index: N}`. Returns updated entity. |
| `POST` | `/api/discuss` | Body: `{slug}`. Writes entity context to discuss file. Returns `{ok: true}`. |

### Entity list filters (`GET /api/entities`)

| Parameter | Values | Default |
|---|---|---|
| `issue` | `stance_conflict`, `type_mismatch`, `new_entity`, `placeholder` | (none — show all) |
| `type` | `individual`, `party`, `institution`, `union` | (none — all types) |
| `status` | `auto_generated`, `needs_review`, `confirmed` | (none — all statuses) |
| `search` | Free text (matches canonical_name and aliases) | (none) |
| `sort` | `observations`, `stance_variance`, `alpha`, `recent` | `observations` |

### PATCH entity fields (`PATCH /api/entities/:slug`)

Accepts any combination of:

```json
{
  "canonical_name": "New Name",
  "stance": "mixed",
  "stance_score": 0.0,
  "entity_type": "individual",
  "subtype": "politician",
  "party_slug": "vidreisn",
  "is_icelandic": true,
  "notes": "Stance changed March 2026",
  "locked_fields": ["stance"],
  "althingi_id": 123
}
```

When a field is updated and the user checks "lock this field", the field name is added to `locked_fields`. The API handles this: if `locked_fields` is provided, it replaces the current array.

## Frontend Design

### Layout

- **Left sidebar** (fixed, ~240px): search input, issue category buttons with live counts, entity type filter tags, verification progress bar (% confirmed)
- **Right main area** (scrollable): entity cards in vertical list, "Showing N [category]" header with sort dropdown

### Entity Card (full detail)

```
┌──────────────────────────────────────────────────────────────┐
│ Kristrún Frostadóttir  [POLITICIAN]  [⚠ STANCE CONFLICT]    │
│ Samfylkingin · forsætisráðherra · 12 articles · 28 claims   │
│                                                              │
│ STANCE                                                       │
│ [pro_eu ×8] [anti_eu ×2] [mixed ×2]                         │
│ Current: mixed (score: +0.33)                                │
│                                                              │
│ RECENT OBSERVATIONS                                          │
│ ▎ pro_eu — „ESB-aðild er mikilvæg" · Vísir, 28 Mar  →      │
│ ▎ anti_eu — „Fullveldið er ekki..." · RÚV, 15 Mar   →      │
│ + 10 more                                                    │
│                                                              │
│ ALIASES                                                      │
│ [Kristrúnu Frostadóttur] [Kristrúnar Frostadóttur]          │
│                                                              │
│ [Confirm ✓]  [Edit]  [Details]  [💬 Discuss]  [Skip →]      │
└──────────────────────────────────────────────────────────────┘
```

- Article URLs in observations are clickable links (open in new tab)
- Issue flag badge colour: amber for stance conflict, red for type mismatch, teal for new entity
- Cards for confirmed entities show a green check instead of the action bar

### Inline Edit Mode

Triggered by "Edit" button. The card transforms:

- Name: text input (pre-filled)
- Stance: dropdown (pro_eu / anti_eu / mixed / neutral) + "🔒 Lock" checkbox
- Type: dropdown (individual / party / institution / union)
- Subtype: dropdown (politician / media / none)
- Party: dropdown (populated from party entities in registry)
- is_icelandic: toggle
- Action bar becomes: [Save] [Cancel]

On save: PATCH to API, card redraws with updated data, sidebar counts update.

### Detail Panel

Triggered by "Details" button. Slides in from the right as an overlay panel (position: fixed, width ~500px, with a semi-transparent backdrop). The card list remains scrollable underneath. Close button in the panel header returns to the card list.

Sections:

**Observations** — full list, each showing:
- Observed name, stance, role, party, type
- Attribution types
- Article title (clickable URL)
- Match confidence and method
- Disagreements highlighted
- [Dismiss] button (sets `dismissed=true`, greys out the row)
- [Relink] button (opens entity search, moves observation to different entity)

**Aliases** — editable tag list:
- Click × to remove
- Text input + "Add" to add new alias

**Roles** — editable list:
- Each role shows role text, from_date, to_date
- [Remove] button per role
- "Add role" form with three fields

**Notes** — text area, auto-saves on blur

**Althingi ID** — number input with [Clear] button

**Merge** — button that:
1. Opens entity search modal
2. Shows side-by-side comparison (keep vs absorb)
3. Preview: which aliases will be absorbed, how many observations move
4. [Confirm Merge] button

**Delete** — button with guard:
- Shows "Type the entity slug to confirm deletion"
- Text input must match slug exactly
- Deletes entity, sets `entity_id=NULL` on all observations

### Styling

Follows DESIGN.md:
- Background: `--bg` (#F5F0E8), surfaces: `--bg-surface` (#E8E2D5)
- Text: `--text` (#1C1A17), muted: `--text-muted` (#6B6358)
- Accent: `--accent` (#0D6A63) for buttons and links
- Rules: `--rule` (#D5CFC5) for borders
- Verdict palette for stance pills: supported green for pro_eu, unsupported red for anti_eu, partial amber for mixed, muted for neutral
- Fonts: Source Serif 4 (headings), Source Sans 3 (UI), DM Sans (data/counts)
- Dark mode via `prefers-color-scheme` using DESIGN.md dark tokens
- Labels: 0.6875rem, weight 700, uppercase, letter-spacing 0.06em

## `/entity-review` Skill

### Default mode: `/entity-review`

1. Start API server: `uv run python scripts/entity_review_server.py`
2. Print URL, tell user to open it
3. Enter interactive loop:
   - Watch for discuss file changes (entity slug written by browser)
   - Accept terminal input for lookups and bulk operations
4. On discuss event: load entity from DB, present full context (all observations with article links, current fields, issue flags, notes)
5. Terminal commands:
   - `look up <name or slug>` — show entity context
   - `confirm all <type> where <condition>` — bulk confirm
   - `set <slug> stance to <value> and lock` — direct edit
   - `show entities with no observations` — query
   - `refresh` — remind user to refresh browser
6. On exit: stop server, print session summary (N confirmed, N edited, N merged, N deleted)

### Status mode: `/entity-review status`

No server. Queries DB directly, prints to terminal:
- Queue depth by issue type (stance conflicts, type mismatches, new entities, placeholders)
- Verification breakdown (confirmed / needs_review / auto_generated with counts)
- Auto-link accuracy (last 30 days: HIGH/MEDIUM matches later corrected)
- Progress since last session

Integrate into `/health` skill as "Entity review queue: N items".

### Discuss event mechanism

- Browser POSTs `{slug}` to `/api/discuss`
- Server writes `{slug, timestamp}` as JSON to `data/entity_review_discuss.json`
- Skill checks this file each loop iteration
- On new event: reads entity + observations from DB, presents in terminal
- File is cleared after reading

## Matcher Update

The `entity_matcher.py` needs a small update to respect `locked_fields`:

When computing disagreements, if the disagreeing field is in the entity's `locked_fields`:
- Still record the disagreement on the observation (for audit)
- Do NOT bump the entity to `needs_review`
- Do NOT change the entity's `verification_status`

This prevents confirmed entities with locked stances from re-entering the review queue every time a new article tags them differently.

## Error → Edit Mapping

21 identified error types mapped to edit primitives:

### Inline edits (on card)
| Error | Edit |
|---|---|
| Wrong canonical name | Edit name (text input) |
| Wrong stance label | Override stance (dropdown + lock) |
| Stance changed over time | Override stance + lock + add note via detail panel |
| Party stance ≠ members | Override to "mixed" + lock |
| Wrong entity_type | Edit type (dropdown) |
| Wrong/missing subtype | Edit subtype (dropdown) |
| Wrong party | Edit party (dropdown) |
| Wrong is_icelandic | Toggle flag |
| Placeholder entity (keep) | Confirm |
| Low-value entity (keep) | Skip |

### Detail panel edits
| Error | Edit |
|---|---|
| Missing alias | Add alias |
| Spurious alias | Remove alias |
| Wrong/missing role | Add/edit/remove role |
| Missing notes | Add note |
| Wrong Alþingi linkage | Edit/clear althingi_id |
| Contextual misattribution | Dismiss observation |
| Observation linked wrong | Relink observation |
| Not a real entity | Delete entity |
| Low-value entity (remove) | Delete entity |
| Duplicate entity | Merge entities |
| Placeholder entity (remove) | Delete entity |

### Bulk operations (terminal)
| Operation | Example command |
|---|---|
| Bulk confirm | "confirm all individuals where pro observations outnumber anti 3:1" |
| Bulk confirm by type | "confirm all party entities" |
| Bulk confirm by status | "confirm all auto_generated entities with 0 disagreements" |

## Success Criteria

- All 21 error types have a clear edit path in the UI
- Review session can be started with `/entity-review` and stopped cleanly
- Entity edits persist immediately to DB
- "Discuss" bridge works: browser click → terminal context in <2 seconds
- Bulk terminal operations update DB, user refreshes browser to see results
- `/entity-review status` shows accurate queue counts
- After a full review pass: all 609 entities reach `confirmed` or deliberate `auto_generated`
- Frontend matches DESIGN.md (colours, fonts, spacing)
- No new dependencies in `pyproject.toml`
