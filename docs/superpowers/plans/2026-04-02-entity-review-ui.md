# Entity Review UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive browser-based entity review UI with a Python API server, a vanilla HTML/JS frontend, and a `/entity-review` Claude Code skill that bridges browser and terminal.

**Architecture:** Python `http.server` serves a single-file HTML/JS review app and JSON API endpoints. The app reads/writes entity data via `fetch()` to the API. A `/entity-review` skill launches the server and watches for "discuss" events from the browser. Two new schema columns (`locked_fields`, `dismissed`) support field locking and observation dismissal.

**Tech Stack:** Python 3.12, `http.server` (stdlib), vanilla HTML/CSS/JS, PostgreSQL, psycopg v3

**Spec:** `docs/superpowers/specs/2026-04-02-entity-review-ui-design.md`

---

## File Structure

```
src/esbvaktin/ground_truth/
    schema.sql                                # MODIFY: add locked_fields + dismissed columns

src/esbvaktin/entity_registry/
    models.py                                 # MODIFY: add locked_fields to Entity, dismissed to EntityObservation
    operations.py                             # MODIFY: add locked_fields to queries, add dashboard/filter queries, update _row_to helpers
    matcher.py                                # MODIFY: respect locked_fields in disagreement flow
    review_app/
        index.html                            # CREATE: single-file frontend (HTML + CSS + JS)

scripts/
    entity_review_server.py                   # CREATE: HTTP API server

.claude/skills/
    entity-review/
        SKILL.md                              # CREATE: /entity-review skill

tests/
    test_entity_review_api.py                 # CREATE: API endpoint tests
```

---

### Task 1: Schema Migration — `locked_fields` and `dismissed`

**Files:**
- Modify: `src/esbvaktin/ground_truth/schema.sql`
- Modify: `src/esbvaktin/entity_registry/models.py`
- Modify: `src/esbvaktin/entity_registry/operations.py`
- Modify: `tests/test_entity_registry.py`

- [ ] **Step 1: Add columns to schema.sql**

Append to end of `src/esbvaktin/ground_truth/schema.sql`:

```sql
-- ═══════════════════════════════════════════════════════════════════════
-- Migration: Entity review support (locked fields + observation dismissal)
-- ═══════════════════════════════════════════════════════════════════════

ALTER TABLE entities ADD COLUMN IF NOT EXISTS locked_fields TEXT[] DEFAULT '{}';
ALTER TABLE entity_observations ADD COLUMN IF NOT EXISTS dismissed BOOLEAN DEFAULT FALSE;
```

- [ ] **Step 2: Apply schema**

Run: `uv run python -c "from esbvaktin.ground_truth.operations import init_schema; init_schema()"`

- [ ] **Step 3: Add `locked_fields` to Entity model**

In `src/esbvaktin/entity_registry/models.py`, add after the `is_icelandic` field in the `Entity` class:

```python
    locked_fields: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add `dismissed` to EntityObservation model**

In `src/esbvaktin/entity_registry/models.py`, add after the `disagreements` field in the `EntityObservation` class:

```python
    dismissed: bool = False
```

- [ ] **Step 5: Update `_row_to_entity` in operations.py**

The `_row_to_entity` function reads 15 columns by index. Add `locked_fields` as column 15 (index 15, after `is_icelandic` at index 14). Update ALL SELECT statements in operations.py that read entity rows to include `locked_fields`:

Change every entity SELECT from:
```sql
SELECT id, slug, canonical_name, entity_type, subtype, stance, stance_score,
       stance_confidence, party_slug, althingi_id, aliases, roles, notes,
       verification_status, is_icelandic
```
to:
```sql
SELECT id, slug, canonical_name, entity_type, subtype, stance, stance_score,
       stance_confidence, party_slug, althingi_id, aliases, roles, notes,
       verification_status, is_icelandic, locked_fields
```

This affects: `get_entity_by_slug`, `get_all_entities`, `get_entities_by_status`, and `_row_to_entity`.

Update `_row_to_entity` to include:
```python
    return Entity(
        # ... existing fields ...
        is_icelandic=row[14],
        locked_fields=list(row[15] or []),
    )
```

- [ ] **Step 6: Update `_row_to_observation` in operations.py**

Add `dismissed` as column 14 (after `disagreements` at index 13). Update the observation SELECT in `get_observations_for_entity` to include `dismissed`:

```sql
SELECT id, entity_id, article_slug, article_url, observed_name, observed_stance,
       observed_role, observed_party, observed_type, attribution_types,
       claim_indices, match_confidence, match_method, disagreements, dismissed
```

Update `_row_to_observation`:
```python
    return EntityObservation(
        # ... existing fields ...
        disagreements=disagreements,
        dismissed=row[14],
    )
```

- [ ] **Step 7: Add `locked_fields` to `update_entity` allowlist**

In `operations.py`, add `"locked_fields"` to the `allowed` set in `update_entity()`.

- [ ] **Step 8: Add `locked_fields` to `insert_entity`**

In `operations.py`, update `insert_entity` to include `locked_fields` in the INSERT statement:

Add to the column list: `locked_fields`
Add to the VALUES: `%(locked_fields)s`
Add to the params dict: `"locked_fields": entity.locked_fields,`

- [ ] **Step 9: Write tests for new fields**

Append to `tests/test_entity_registry.py`:

```python
class TestLockedFields:
    def test_insert_with_locked_fields(self, db_conn):
        entity = Entity(
            slug="locked-test",
            canonical_name="Locked Test",
            entity_type="individual",
            stance="pro_eu",
            locked_fields=["stance"],
        )
        entity_id = insert_entity(entity, db_conn)
        retrieved = get_entity_by_slug("locked-test", db_conn)
        assert "stance" in retrieved.locked_fields

    def test_update_locked_fields(self, db_conn):
        entity_id = insert_entity(
            Entity(slug="lock-update", canonical_name="Lock", entity_type="individual"),
            db_conn,
        )
        update_entity(entity_id, {"locked_fields": ["stance", "type"]}, db_conn)
        updated = get_entity_by_slug("lock-update", db_conn)
        assert "stance" in updated.locked_fields
        assert "type" in updated.locked_fields


class TestDismissedObservation:
    def test_default_not_dismissed(self, db_conn):
        entity_id = insert_entity(
            Entity(slug="dismiss-test", canonical_name="D", entity_type="individual"),
            db_conn,
        )
        insert_observation(
            EntityObservation(entity_id=entity_id, article_slug="a1", observed_name="D"),
            db_conn,
        )
        obs = get_observations_for_entity(entity_id, db_conn)
        assert obs[0].dismissed is False
```

- [ ] **Step 10: Run tests**

Run: `uv run --extra dev python -m pytest tests/test_entity_registry.py -v`

Expected: All tests pass including new locked_fields and dismissed tests.

- [ ] **Step 11: Commit**

```bash
git add src/esbvaktin/ground_truth/schema.sql src/esbvaktin/entity_registry/models.py src/esbvaktin/entity_registry/operations.py tests/test_entity_registry.py
git commit -m "feat: add locked_fields and dismissed columns for entity review"
```

---

### Task 2: Extended Operations — Dashboard Queries and Filtered Entity Lists

**Files:**
- Modify: `src/esbvaktin/entity_registry/operations.py`
- Create: `tests/test_entity_review_api.py` (start with operations tests)

This task adds the query functions the API server will call: dashboard stats, filtered entity lists, observation dismissal, and observation relinking.

- [ ] **Step 1: Write tests for dashboard and filter queries**

Create `tests/test_entity_review_api.py`:

```python
"""Tests for entity review API operations."""

import pytest

from esbvaktin.entity_registry.models import Entity, EntityObservation
from esbvaktin.entity_registry.operations import (
    get_dashboard_stats,
    get_filtered_entities,
    get_entity_detail,
    dismiss_observation,
    relink_observation,
    confirm_entity,
    delete_entity,
    insert_entity,
    insert_observation,
    get_entity_by_slug,
    get_observations_for_entity,
)


@pytest.fixture
def db_conn():
    """Get a test DB connection."""
    from esbvaktin.ground_truth.operations import get_connection, init_schema

    conn = get_connection()
    init_schema(conn)
    conn.execute("DELETE FROM entity_observations")
    conn.execute("DELETE FROM entities")
    conn.commit()
    yield conn
    conn.rollback()
    conn.execute("DELETE FROM entity_observations")
    conn.execute("DELETE FROM entities")
    conn.commit()
    conn.close()


@pytest.fixture
def seeded_db(db_conn):
    """Seed DB with a few entities + observations for testing."""
    e1_id = insert_entity(
        Entity(
            slug="person-a",
            canonical_name="Person A",
            entity_type="individual",
            stance="pro_eu",
            verification_status="auto_generated",
        ),
        db_conn,
    )
    e2_id = insert_entity(
        Entity(
            slug="party-b",
            canonical_name="Party B",
            entity_type="party",
            stance="mixed",
            verification_status="needs_review",
        ),
        db_conn,
    )
    # Observations with stance conflict on person-a
    insert_observation(
        EntityObservation(
            entity_id=e1_id,
            article_slug="art-1",
            article_url="https://example.com/1",
            observed_name="Person A",
            observed_stance="pro_eu",
        ),
        db_conn,
    )
    insert_observation(
        EntityObservation(
            entity_id=e1_id,
            article_slug="art-2",
            article_url="https://example.com/2",
            observed_name="Person A",
            observed_stance="anti_eu",
            disagreements={"stance": True},
        ),
        db_conn,
    )
    insert_observation(
        EntityObservation(
            entity_id=e2_id,
            article_slug="art-3",
            observed_name="Party B",
            observed_stance="mixed",
        ),
        db_conn,
    )
    return {"person_a_id": e1_id, "party_b_id": e2_id}


class TestDashboardStats:
    def test_returns_counts(self, seeded_db, db_conn):
        stats = get_dashboard_stats(db_conn)
        assert stats["total_entities"] == 2
        assert stats["total_observations"] == 3
        assert stats["by_status"]["auto_generated"] == 1
        assert stats["by_status"]["needs_review"] == 1
        assert stats["stance_conflicts"] >= 1


class TestFilteredEntities:
    def test_filter_by_type(self, seeded_db, db_conn):
        results = get_filtered_entities(db_conn, entity_type="party")
        assert len(results) == 1
        assert results[0]["slug"] == "party-b"

    def test_filter_by_status(self, seeded_db, db_conn):
        results = get_filtered_entities(db_conn, status="needs_review")
        assert len(results) == 1

    def test_search(self, seeded_db, db_conn):
        results = get_filtered_entities(db_conn, search="person")
        assert len(results) == 1
        assert results[0]["slug"] == "person-a"

    def test_filter_stance_conflicts(self, seeded_db, db_conn):
        results = get_filtered_entities(db_conn, issue="stance_conflict")
        assert len(results) >= 1


class TestEntityDetail:
    def test_includes_observations(self, seeded_db, db_conn):
        detail = get_entity_detail("person-a", db_conn)
        assert detail is not None
        assert detail["slug"] == "person-a"
        assert len(detail["observations"]) == 2


class TestConfirmEntity:
    def test_sets_confirmed(self, seeded_db, db_conn):
        confirm_entity("person-a", db_conn)
        entity = get_entity_by_slug("person-a", db_conn)
        assert entity.verification_status == "confirmed"
        assert entity.verified_at is not None


class TestDeleteEntity:
    def test_deletes_and_unlinks(self, seeded_db, db_conn):
        delete_entity("party-b", db_conn)
        assert get_entity_by_slug("party-b", db_conn) is None
        # Observations should be unlinked (entity_id = NULL)
        orphans = db_conn.execute(
            "SELECT COUNT(*) FROM entity_observations WHERE entity_id IS NULL"
        ).fetchone()[0]
        assert orphans >= 1


class TestDismissObservation:
    def test_dismiss(self, seeded_db, db_conn):
        obs = get_observations_for_entity(seeded_db["person_a_id"], db_conn)
        obs_id = obs[0].id
        dismiss_observation(obs_id, db_conn)
        updated = get_observations_for_entity(seeded_db["person_a_id"], db_conn)
        dismissed = [o for o in updated if o.id == obs_id]
        assert dismissed[0].dismissed is True


class TestRelinkObservation:
    def test_relink(self, seeded_db, db_conn):
        obs = get_observations_for_entity(seeded_db["person_a_id"], db_conn)
        obs_id = obs[0].id
        relink_observation(obs_id, seeded_db["party_b_id"], db_conn)
        # Should no longer be linked to person_a
        obs_a = get_observations_for_entity(seeded_db["person_a_id"], db_conn)
        assert all(o.id != obs_id for o in obs_a)
        # Should be linked to party_b
        obs_b = get_observations_for_entity(seeded_db["party_b_id"], db_conn)
        assert any(o.id == obs_id for o in obs_b)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev python -m pytest tests/test_entity_review_api.py -v`

Expected: FAIL — `ImportError` for the new functions.

- [ ] **Step 3: Implement new operations**

Add these functions to `src/esbvaktin/entity_registry/operations.py`:

```python
def get_dashboard_stats(conn: psycopg.Connection) -> dict:
    """Get dashboard statistics for the review UI."""
    total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    total_obs = conn.execute("SELECT COUNT(*) FROM entity_observations").fetchone()[0]

    by_status = {}
    for row in conn.execute(
        "SELECT verification_status, COUNT(*) FROM entities GROUP BY verification_status"
    ).fetchall():
        by_status[row[0]] = row[1]

    # Stance conflicts: entities with >1 distinct non-neutral stance in observations
    stance_conflicts = conn.execute("""
        SELECT COUNT(DISTINCT eo.entity_id) FROM entity_observations eo
        WHERE eo.dismissed = FALSE AND eo.observed_stance IS NOT NULL
          AND eo.observed_stance != 'neutral' AND eo.entity_id IS NOT NULL
        GROUP BY eo.entity_id
        HAVING COUNT(DISTINCT eo.observed_stance) > 1
    """).fetchall()

    # Type mismatches: observations where observed_type != entity's type
    type_mismatches = conn.execute("""
        SELECT COUNT(DISTINCT eo.entity_id) FROM entity_observations eo
        JOIN entities e ON e.id = eo.entity_id
        WHERE eo.dismissed = FALSE AND eo.observed_type IS NOT NULL
          AND eo.observed_type != e.entity_type
    """).fetchone()[0]

    # Placeholders: entities with zero non-dismissed observations
    placeholders = conn.execute("""
        SELECT COUNT(*) FROM entities e
        WHERE NOT EXISTS (
            SELECT 1 FROM entity_observations eo
            WHERE eo.entity_id = e.id AND eo.dismissed = FALSE
        )
    """).fetchone()[0]

    return {
        "total_entities": total,
        "total_observations": total_obs,
        "by_status": by_status,
        "stance_conflicts": len(stance_conflicts),
        "type_mismatches": type_mismatches,
        "placeholders": placeholders,
    }


def get_filtered_entities(
    conn: psycopg.Connection,
    *,
    issue: str | None = None,
    entity_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    sort: str = "observations",
) -> list[dict]:
    """Get filtered entity list for the review UI.

    Returns dicts (not Entity models) with observation counts and stance breakdown.
    """
    conditions = []
    params: dict = {}

    if entity_type:
        conditions.append("e.entity_type = %(entity_type)s")
        params["entity_type"] = entity_type

    if status:
        conditions.append("e.verification_status = %(status)s")
        params["status"] = status

    if search:
        conditions.append(
            "(LOWER(e.canonical_name) LIKE %(search)s OR EXISTS "
            "(SELECT 1 FROM unnest(e.aliases) a WHERE LOWER(a) LIKE %(search)s))"
        )
        params["search"] = f"%{search.lower()}%"

    where = " AND ".join(conditions) if conditions else "TRUE"

    sort_map = {
        "observations": "obs_count DESC",
        "alpha": "e.canonical_name ASC",
        "recent": "last_obs DESC NULLS LAST",
        "stance_variance": "stance_var DESC NULLS LAST",
    }
    order_by = sort_map.get(sort, "obs_count DESC")

    sql = f"""
        SELECT e.id, e.slug, e.canonical_name, e.entity_type, e.subtype,
               e.stance, e.stance_score, e.party_slug, e.verification_status,
               e.locked_fields,
               COUNT(eo.id) FILTER (WHERE eo.dismissed = FALSE) AS obs_count,
               MAX(eo.created_at) AS last_obs,
               VARIANCE(CASE eo.observed_stance
                   WHEN 'pro_eu' THEN 1.0
                   WHEN 'anti_eu' THEN -1.0
                   WHEN 'mixed' THEN 0.0
                   WHEN 'neutral' THEN 0.0
               END) FILTER (WHERE eo.dismissed = FALSE AND eo.observed_stance IS NOT NULL) AS stance_var
        FROM entities e
        LEFT JOIN entity_observations eo ON eo.entity_id = e.id
        WHERE {where}
        GROUP BY e.id
        ORDER BY {order_by}
    """

    rows = conn.execute(sql, params).fetchall()
    results = []
    for row in rows:
        entity_id = row[0]
        # Get stance breakdown for this entity
        stance_rows = conn.execute(
            """
            SELECT observed_stance, COUNT(*) FROM entity_observations
            WHERE entity_id = %(eid)s AND dismissed = FALSE
              AND observed_stance IS NOT NULL
            GROUP BY observed_stance
            """,
            {"eid": entity_id},
        ).fetchall()
        stance_breakdown = {s: c for s, c in stance_rows}

        results.append({
            "id": row[0],
            "slug": row[1],
            "canonical_name": row[2],
            "entity_type": row[3],
            "subtype": row[4],
            "stance": row[5],
            "stance_score": row[6],
            "party_slug": row[7],
            "verification_status": row[8],
            "locked_fields": list(row[9] or []),
            "observation_count": row[10],
            "stance_breakdown": stance_breakdown,
        })

    # Post-filter by issue type (needs aggregate data)
    if issue == "stance_conflict":
        results = [r for r in results if len(r["stance_breakdown"]) > 1
                   and any(k != "neutral" for k in r["stance_breakdown"])]
    elif issue == "type_mismatch":
        # Re-query: entities with type-disagreeing observations
        mismatch_ids = {row[0] for row in conn.execute("""
            SELECT DISTINCT eo.entity_id FROM entity_observations eo
            JOIN entities e ON e.id = eo.entity_id
            WHERE eo.dismissed = FALSE AND eo.observed_type IS NOT NULL
              AND eo.observed_type != e.entity_type
        """).fetchall()}
        results = [r for r in results if r["id"] in mismatch_ids]
    elif issue == "placeholder":
        results = [r for r in results if r["observation_count"] == 0]
    elif issue == "new_entity":
        results = [r for r in results if r["verification_status"] == "auto_generated"]

    return results


def get_entity_detail(slug: str, conn: psycopg.Connection) -> dict | None:
    """Get full entity detail including all observations, for the detail panel."""
    entity = get_entity_by_slug(slug, conn)
    if not entity:
        return None

    observations = get_observations_for_entity(entity.id, conn)

    return {
        **entity.model_dump(),
        "observations": [obs.model_dump() for obs in observations],
    }


def confirm_entity(slug: str, conn: psycopg.Connection) -> Entity | None:
    """Set an entity to confirmed status."""
    entity = get_entity_by_slug(slug, conn)
    if not entity:
        return None
    conn.execute(
        """
        UPDATE entities
        SET verification_status = 'confirmed', verified_at = NOW(), verified_by = 'review_ui'
        WHERE slug = %(slug)s
        """,
        {"slug": slug},
    )
    conn.commit()
    return get_entity_by_slug(slug, conn)


def delete_entity(slug: str, conn: psycopg.Connection) -> bool:
    """Delete an entity and unlink its observations."""
    entity = get_entity_by_slug(slug, conn)
    if not entity:
        return False
    conn.execute(
        "UPDATE entity_observations SET entity_id = NULL WHERE entity_id = %(eid)s",
        {"eid": entity.id},
    )
    conn.execute("DELETE FROM entities WHERE id = %(eid)s", {"eid": entity.id})
    conn.commit()
    return True


def dismiss_observation(obs_id: int, conn: psycopg.Connection) -> bool:
    """Mark an observation as dismissed."""
    conn.execute(
        "UPDATE entity_observations SET dismissed = TRUE WHERE id = %(id)s",
        {"id": obs_id},
    )
    conn.commit()
    return True


def relink_observation(
    obs_id: int, new_entity_id: int, conn: psycopg.Connection
) -> bool:
    """Move an observation to a different entity."""
    conn.execute(
        "UPDATE entity_observations SET entity_id = %(eid)s WHERE id = %(id)s",
        {"eid": new_entity_id, "id": obs_id},
    )
    conn.commit()
    return True
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev python -m pytest tests/test_entity_review_api.py -v`

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/esbvaktin/entity_registry/operations.py tests/test_entity_review_api.py
git commit -m "feat: add review UI query operations (dashboard, filters, confirm, dismiss)"
```

---

### Task 3: Matcher Update — Respect `locked_fields`

**Files:**
- Modify: `src/esbvaktin/entity_registry/matcher.py`
- Modify: `tests/test_entity_matcher.py`

- [ ] **Step 1: Write test for locked field behaviour**

Append to `tests/test_entity_matcher.py`:

```python
class TestLockedFields:
    def test_disagreement_on_locked_field_still_recorded(self):
        entity = Entity(
            id=1, slug="x", canonical_name="X", entity_type="individual",
            stance="pro_eu", locked_fields=["stance"],
        )
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance="anti_eu",
            observed_role=None,
            observed_party=None,
            observed_type="individual",
        )
        # Disagreement is still recorded
        assert disagreements is not None
        assert disagreements["stance"] is True

    def test_is_field_locked(self):
        from esbvaktin.entity_registry.matcher import is_field_locked

        entity = Entity(
            id=1, slug="x", canonical_name="X", entity_type="individual",
            locked_fields=["stance", "type"],
        )
        assert is_field_locked(entity, "stance") is True
        assert is_field_locked(entity, "party") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/test_entity_matcher.py::TestLockedFields -v`

Expected: FAIL — `ImportError` for `is_field_locked`.

- [ ] **Step 3: Add `is_field_locked` to matcher.py**

Add to `src/esbvaktin/entity_registry/matcher.py`:

```python
def is_field_locked(entity: Entity, field: str) -> bool:
    """Check if a field is locked on an entity (manual override takes precedence)."""
    return field in entity.locked_fields
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev python -m pytest tests/test_entity_matcher.py -v`

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/esbvaktin/entity_registry/matcher.py tests/test_entity_matcher.py
git commit -m "feat: add is_field_locked helper for locked_fields support"
```

---

### Task 4: API Server

**Files:**
- Create: `scripts/entity_review_server.py`

This is the HTTP server that serves the review app and handles JSON API requests. It uses Python's built-in `http.server` with custom request handlers. Each API route maps to an operations function from Task 2.

- [ ] **Step 1: Create the API server**

Create `scripts/entity_review_server.py`:

```python
"""Entity Review API Server.

Lightweight HTTP server for the browser-based entity review UI.
Serves the static HTML app and handles JSON API requests.

Usage:
    uv run python scripts/entity_review_server.py              # Start on port 8477
    uv run python scripts/entity_review_server.py --port 9000  # Custom port
"""

from __future__ import annotations

import json
import sys
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REVIEW_APP_PATH = PROJECT_ROOT / "src" / "esbvaktin" / "entity_registry" / "review_app" / "index.html"
DISCUSS_FILE = PROJECT_ROOT / "data" / "entity_review_discuss.json"

DEFAULT_PORT = 8477


def _get_conn():
    """Get a fresh DB connection."""
    from esbvaktin.ground_truth.operations import get_connection
    return get_connection()


class ReviewHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the entity review API."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "" or path == "/":
            self._serve_html()
        elif path == "/api/dashboard":
            self._handle_dashboard()
        elif path == "/api/entities":
            self._handle_entity_list(params)
        elif path.startswith("/api/entities/"):
            slug = path.split("/api/entities/")[1]
            if slug:
                self._handle_entity_detail(slug)
            else:
                self._json_response({"error": "Missing slug"}, 400)
        else:
            self._json_response({"error": "Not found"}, 404)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body()

        if path.startswith("/api/observations/"):
            obs_id_str = path.split("/api/observations/")[1]
            self._handle_patch_observation(int(obs_id_str), body)
        elif path.startswith("/api/entities/"):
            slug = path.split("/api/entities/")[1]
            self._handle_patch_entity(slug, body)
        else:
            self._json_response({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body()

        if path == "/api/discuss":
            self._handle_discuss(body)
        elif path == "/api/entities/merge":
            self._handle_merge(body)
        elif path.endswith("/confirm"):
            slug = path.replace("/api/entities/", "").replace("/confirm", "")
            self._handle_confirm(slug)
        elif path.endswith("/delete"):
            slug = path.replace("/api/entities/", "").replace("/delete", "")
            self._handle_delete(slug)
        elif path.endswith("/aliases"):
            slug = path.replace("/api/entities/", "").replace("/aliases", "")
            self._handle_aliases(slug, body)
        elif path.endswith("/roles"):
            slug = path.replace("/api/entities/", "").replace("/roles", "")
            self._handle_roles(slug, body)
        else:
            self._json_response({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    # ── Handlers ─────────────────────────────────────────────

    def _serve_html(self):
        if not REVIEW_APP_PATH.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Review app not found. Build it first.")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(REVIEW_APP_PATH.read_bytes())

    def _handle_dashboard(self):
        from esbvaktin.entity_registry.operations import get_dashboard_stats
        conn = _get_conn()
        try:
            stats = get_dashboard_stats(conn)
            self._json_response(stats)
        finally:
            conn.close()

    def _handle_entity_list(self, params: dict):
        from esbvaktin.entity_registry.operations import get_filtered_entities
        conn = _get_conn()
        try:
            results = get_filtered_entities(
                conn,
                issue=params.get("issue", [None])[0],
                entity_type=params.get("type", [None])[0],
                status=params.get("status", [None])[0],
                search=params.get("search", [None])[0],
                sort=params.get("sort", ["observations"])[0],
            )
            self._json_response(results)
        finally:
            conn.close()

    def _handle_entity_detail(self, slug: str):
        from esbvaktin.entity_registry.operations import get_entity_detail
        conn = _get_conn()
        try:
            detail = get_entity_detail(slug, conn)
            if detail:
                self._json_response(detail)
            else:
                self._json_response({"error": "Entity not found"}, 404)
        finally:
            conn.close()

    def _handle_patch_entity(self, slug: str, body: dict):
        from esbvaktin.entity_registry.operations import (
            get_entity_by_slug,
            get_entity_detail,
            update_entity,
        )
        conn = _get_conn()
        try:
            entity = get_entity_by_slug(slug, conn)
            if not entity:
                self._json_response({"error": "Entity not found"}, 404)
                return
            update_entity(entity.id, body, conn)
            detail = get_entity_detail(slug, conn)
            self._json_response(detail)
        finally:
            conn.close()

    def _handle_confirm(self, slug: str):
        from esbvaktin.entity_registry.operations import confirm_entity, get_entity_detail
        conn = _get_conn()
        try:
            result = confirm_entity(slug, conn)
            if result:
                detail = get_entity_detail(slug, conn)
                self._json_response(detail)
            else:
                self._json_response({"error": "Entity not found"}, 404)
        finally:
            conn.close()

    def _handle_delete(self, slug: str):
        from esbvaktin.entity_registry.operations import delete_entity
        conn = _get_conn()
        try:
            if delete_entity(slug, conn):
                self._json_response({"ok": True})
            else:
                self._json_response({"error": "Entity not found"}, 404)
        finally:
            conn.close()

    def _handle_merge(self, body: dict):
        from esbvaktin.entity_registry.operations import (
            get_entity_by_slug,
            get_entity_detail,
            merge_entities,
        )
        keep_slug = body.get("keep_slug")
        absorb_slug = body.get("absorb_slug")
        if not keep_slug or not absorb_slug:
            self._json_response({"error": "keep_slug and absorb_slug required"}, 400)
            return
        conn = _get_conn()
        try:
            keep = get_entity_by_slug(keep_slug, conn)
            absorb = get_entity_by_slug(absorb_slug, conn)
            if not keep or not absorb:
                self._json_response({"error": "Entity not found"}, 404)
                return
            merge_entities(keep.id, absorb.id, conn)
            detail = get_entity_detail(keep_slug, conn)
            self._json_response(detail)
        finally:
            conn.close()

    def _handle_patch_observation(self, obs_id: int, body: dict):
        from esbvaktin.entity_registry.operations import (
            dismiss_observation,
            relink_observation,
        )
        conn = _get_conn()
        try:
            if body.get("dismissed"):
                dismiss_observation(obs_id, conn)
            elif "entity_id" in body:
                relink_observation(obs_id, body["entity_id"], conn)
            self._json_response({"ok": True})
        finally:
            conn.close()

    def _handle_aliases(self, slug: str, body: dict):
        from esbvaktin.entity_registry.operations import get_entity_by_slug, get_entity_detail, update_entity
        conn = _get_conn()
        try:
            entity = get_entity_by_slug(slug, conn)
            if not entity:
                self._json_response({"error": "Entity not found"}, 404)
                return
            aliases = list(entity.aliases)
            for name in body.get("add", []):
                if name not in aliases:
                    aliases.append(name)
            for name in body.get("remove", []):
                if name in aliases:
                    aliases.remove(name)
            update_entity(entity.id, {"aliases": aliases}, conn)
            detail = get_entity_detail(slug, conn)
            self._json_response(detail)
        finally:
            conn.close()

    def _handle_roles(self, slug: str, body: dict):
        from esbvaktin.entity_registry.operations import get_entity_by_slug, get_entity_detail, update_entity
        conn = _get_conn()
        try:
            entity = get_entity_by_slug(slug, conn)
            if not entity:
                self._json_response({"error": "Entity not found"}, 404)
                return
            roles = [r.model_dump() for r in entity.roles]
            if "add" in body:
                roles.append(body["add"])
            if "remove_index" in body:
                idx = body["remove_index"]
                if 0 <= idx < len(roles):
                    roles.pop(idx)
            update_entity(entity.id, {"roles": roles}, conn)
            detail = get_entity_detail(slug, conn)
            self._json_response(detail)
        finally:
            conn.close()

    def _handle_discuss(self, body: dict):
        slug = body.get("slug")
        if not slug:
            self._json_response({"error": "slug required"}, 400)
            return
        import time
        DISCUSS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DISCUSS_FILE.write_text(json.dumps({"slug": slug, "timestamp": time.time()}))
        self._json_response({"ok": True})

    # ── Helpers ──────────────────────────────────────────────

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _json_response(self, data, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        """Suppress default access log noise. Only log errors."""
        if args and isinstance(args[0], str) and args[0].startswith("4"):
            super().log_message(format, *args)


def main():
    port = DEFAULT_PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])

    server = HTTPServer(("127.0.0.1", port), ReviewHandler)
    print(f"Entity Review server running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test server starts and responds**

Run: `uv run python scripts/entity_review_server.py &; sleep 2; curl -s http://localhost:8477/api/dashboard | python -m json.tool; kill %1`

Expected: JSON with dashboard stats. Server starts and stops cleanly.

- [ ] **Step 3: Commit**

```bash
git add scripts/entity_review_server.py
git commit -m "feat: add entity review API server (http.server + JSON endpoints)"
```

---

### Task 5: Frontend — Review App HTML

**Files:**
- Create: `src/esbvaktin/entity_registry/review_app/index.html`

This is the largest single file. It contains all HTML, CSS, and JS in one self-contained page. The implementation should follow the DESIGN.md colour tokens, fonts, and aesthetic. The file will be approximately 800-1200 lines.

**Important:** This task produces a complete, working frontend. The implementer should read `docs/superpowers/specs/2026-04-02-entity-review-ui-design.md` sections "Frontend Design" and "Styling" for full requirements. Key features:

1. **Split-panel layout:** fixed sidebar (~240px) + scrollable main area
2. **Sidebar:** search input, issue category buttons with counts from `/api/dashboard`, entity type filter tags, progress bar
3. **Entity cards:** full detail with name, badges, stance breakdown pills, recent observations with article links, aliases, action buttons
4. **Inline edit mode:** triggered by Edit button, dropdowns for stance/type/subtype/party, lock checkbox, Save/Cancel
5. **Detail panel:** fixed overlay from right (~500px), full observation list with dismiss/relink, alias management, role management, notes textarea, althingi_id, merge, delete
6. **Discuss button:** POSTs to `/api/discuss`, shows toast
7. **Styling:** DESIGN.md tokens (--bg #F5F0E8, --bg-surface #E8E2D5, --accent #0D6A63, etc.), Source Serif 4 + Source Sans 3 + DM Sans fonts, dark mode support

- [ ] **Step 1: Create the review_app directory**

Run: `mkdir -p src/esbvaktin/entity_registry/review_app`

- [ ] **Step 2: Create index.html**

Create `src/esbvaktin/entity_registry/review_app/index.html` — a complete single-file HTML application. This file is large (~1000 lines) and must be written in full by the implementer following the spec. Key sections:

- `<style>` block: CSS variables from DESIGN.md, split-panel layout, card styles, inline edit styles, detail panel styles, dark mode `@media (prefers-color-scheme: dark)`
- `<div id="app">`: sidebar + main area structure
- `<script>` block: state management, API fetch functions, render functions for cards/sidebar/detail panel, event handlers for all actions

The JS should follow this architecture:
```javascript
// State
let state = { entities: [], dashboard: {}, filters: {}, editingSlug: null, detailSlug: null };

// API functions
async function fetchDashboard() { ... }
async function fetchEntities() { ... }
async function fetchEntityDetail(slug) { ... }
async function patchEntity(slug, data) { ... }
async function confirmEntity(slug) { ... }
async function deleteEntity(slug) { ... }
async function mergeEntities(keepSlug, absorbSlug) { ... }
async function dismissObservation(obsId) { ... }
async function relinkObservation(obsId, entityId) { ... }
async function updateAliases(slug, add, remove) { ... }
async function updateRoles(slug, add, removeIndex) { ... }
async function discussEntity(slug) { ... }

// Render functions
function renderSidebar() { ... }
function renderEntityList() { ... }
function renderEntityCard(entity) { ... }
function renderEditMode(entity) { ... }
function renderDetailPanel(detail) { ... }
function renderObservation(obs) { ... }

// Init
fetchDashboard().then(renderSidebar);
fetchEntities().then(renderEntityList);
```

- [ ] **Step 3: Test in browser**

Run: `uv run python scripts/entity_review_server.py` and open http://localhost:8477

Expected: Split-panel layout with sidebar showing issue counts and entity cards in the main area. Clicking Confirm/Edit/Details/Discuss should work.

- [ ] **Step 4: Commit**

```bash
git add src/esbvaktin/entity_registry/review_app/index.html
git commit -m "feat: add entity review browser UI (single-file HTML/JS app)"
```

---

### Task 6: `/entity-review` Skill

**Files:**
- Create: `.claude/skills/entity-review/SKILL.md`

- [ ] **Step 1: Create the skill file**

Create `.claude/skills/entity-review/SKILL.md`:

```markdown
# Entity Review

Interactive browser-based entity review with terminal discussion bridge.

## Usage

```
/entity-review              # Start review session (launches browser UI)
/entity-review status       # Show review queue status (no server)
```

## Status Mode

Query entity registry directly. No server needed.

### Step 1: Query dashboard stats

```bash
uv run python -c "
from esbvaktin.entity_registry.operations import get_dashboard_stats
from esbvaktin.ground_truth.operations import get_connection
conn = get_connection()
stats = get_dashboard_stats(conn)
conn.close()
print(f'''Entity Registry Status
{'='*50}
  Total entities:       {stats['total_entities']}
  Total observations:   {stats['total_observations']}

  By verification status:''')
for status, count in stats.get('by_status', {}).items():
    pct = round(100 * count / max(stats['total_entities'], 1), 1)
    print(f'    {status}: {count} ({pct}%)')
print(f'''
  Review queue:
    Stance conflicts:   {stats['stance_conflicts']}
    Type mismatches:    {stats['type_mismatches']}
    Placeholders:       {stats['placeholders']}''')
"
```

### Step 2: Present results to user

Show the output. Highlight any non-zero queue items.

---

## Interactive Mode

### Step 1: Start the API server

```bash
uv run python scripts/entity_review_server.py &
```

Save the PID. Tell the user: "Entity review server running at http://localhost:8477 — open this in your browser."

### Step 2: Enter interactive loop

Watch for two input sources:

1. **Discuss events** — check `data/entity_review_discuss.json` for new events. When a new slug appears:
   - Load the entity from DB via operations
   - Present full context: name, type, stance (locked?), all observations with article URLs, aliases, roles, notes
   - Ask the user what they want to do

2. **Terminal commands** — the user may type:
   - **Entity lookup**: "look up Bjarni Benediktsson" or "show me person-a" → load and present entity context
   - **Bulk confirm**: "confirm all individuals where pro observations outnumber anti 3:1" → query DB, confirm matching entities, report count
   - **Direct edit**: "set sjalfstaedisflokkurinn stance to mixed and lock it" → PATCH via operations, report result
   - **Query**: "show entities with no observations" → query and present
   - **Refresh reminder**: after any terminal operation that changes data, tell user "Changes saved — refresh the browser to see updates"

### Step 3: Handle discuss events

When `data/entity_review_discuss.json` exists and has a newer timestamp than last check:

```bash
uv run python -c "
import json
from esbvaktin.entity_registry.operations import get_entity_detail
from esbvaktin.ground_truth.operations import get_connection
slug = json.loads(open('data/entity_review_discuss.json').read())['slug']
conn = get_connection()
detail = get_entity_detail(slug, conn)
conn.close()
print(json.dumps(detail, indent=2, ensure_ascii=False, default=str))
"
```

Present the entity context conversationally. Include:
- Entity name, type, subtype, stance (+ whether locked)
- Observation count and stance breakdown
- Each observation: observed_stance, article_url, attribution_types
- Current aliases and roles
- Any notes
- Flagged issues

Ask: "What would you like to do with this entity?"

### Step 4: Apply decisions

Based on user response, execute via Python:

- **Confirm**: `confirm_entity(slug, conn)`
- **Edit stance**: `update_entity(entity.id, {"stance": "mixed", "locked_fields": ["stance"]}, conn)`
- **Dismiss observation**: `dismiss_observation(obs_id, conn)`
- **Other edits**: use appropriate operations function

Always remind user to refresh browser after terminal changes.

### Step 5: Exit

When user says "done", "exit", or "quit":

```bash
kill $SERVER_PID
```

Print session summary: how many entities were confirmed, edited, merged, deleted during this session.
Clean up `data/entity_review_discuss.json` if it exists.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/entity-review/SKILL.md
git commit -m "feat: add /entity-review skill for interactive browser review sessions"
```

---

### Task 7: Documentation Updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/rules/db-schema.md`

- [ ] **Step 1: Add `/entity-review` to skills list in CLAUDE.md**

In the `## Skills (Slash Commands)` section, add:

```
/entity-review             # Interactive browser-based entity review
/entity-review status      # Entity registry queue status
```

- [ ] **Step 2: Update db-schema.md with new columns**

Add to the `entities` row notes: `locked_fields TEXT[]` for manual override protection.
Add to the `entity_observations` row notes: `dismissed BOOLEAN` for extraction error flagging.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md .claude/rules/db-schema.md
git commit -m "docs: add /entity-review skill and new schema columns to documentation"
```

---

### Task 8: Integration Test — Full Workflow Verification

**Files:** None (verification only)

- [ ] **Step 1: Run lint**

Run: `uv run --extra dev ruff check src/esbvaktin/entity_registry/ scripts/entity_review_server.py tests/test_entity_review_api.py`

Expected: No lint errors.

- [ ] **Step 2: Run all tests**

Run: `uv run --extra dev python -m pytest --ignore=tests/test_heimildin.py -v`

Expected: All tests pass, no regressions.

- [ ] **Step 3: Start server and verify browser loads**

Run: `uv run python scripts/entity_review_server.py`

Open http://localhost:8477 in browser. Verify:
- Sidebar shows correct issue counts (45 stance conflicts, 9 type mismatches, etc.)
- Entity cards render with correct data
- Click "Confirm" on an entity → card updates with green check
- Click "Edit" → inline form appears, change stance, save → card updates
- Click "Details" → detail panel slides in with observations
- Click "Discuss" → toast appears, check `data/entity_review_discuss.json` has the slug

- [ ] **Step 4: Test discuss bridge**

With server running, invoke `/entity-review` and verify that clicking "Discuss" in the browser surfaces the entity context in the terminal.

- [ ] **Step 5: Commit any fixes**

```bash
git add -u
git commit -m "fix: address lint and test issues from entity review UI integration"
```
