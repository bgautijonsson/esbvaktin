# Entity Registry Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a canonical entity registry in PostgreSQL with automated name matching and observation tracking, replacing the fragile per-export merge logic.

**Architecture:** Two new DB tables (`entities`, `entity_observations`) form the canonical registry. A new `entity_registry` package provides models, DB operations, and a deterministic name matcher using BÍN lemmatisation + alias tables. A migration script bootstraps the registry from 541 existing entities. The matcher integrates into `register_article_sightings.py` to record observations on every analysis.

**Tech Stack:** Python 3.12, PostgreSQL 17, psycopg v3, Pydantic v2, islenska (BÍN), pytest

**Spec:** `docs/superpowers/specs/2026-04-02-entity-registry-design.md`

---

## File Structure

```
src/esbvaktin/entity_registry/       # NEW package
    __init__.py                       # Re-exports for convenience
    models.py                         # Pydantic models: Entity, EntityObservation
    operations.py                     # DB CRUD: insert, update, query, merge entities
    matcher.py                        # Name matching cascade + confidence scoring + BÍN

src/esbvaktin/ground_truth/
    schema.sql                        # MODIFY: add entities + entity_observations tables

scripts/
    migrate_entities.py               # NEW: big-bang migration from existing data
    register_article_sightings.py     # MODIFY: wire in entity observation recording

tests/
    test_entity_matcher.py            # NEW: matching cascade, confidence, disagreements
    test_entity_registry.py           # NEW: models, DB operations
```

---

### Task 1: Database Schema — Create `entities` and `entity_observations` Tables

**Files:**
- Modify: `src/esbvaktin/ground_truth/schema.sql`

- [ ] **Step 1: Add entity tables to schema.sql**

Append to the end of `src/esbvaktin/ground_truth/schema.sql`:

```sql
-- ═══════════════════════════════════════════════════════════════════════
-- Entity Registry: canonical entity profiles with observation tracking
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS entities (
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_slug ON entities(slug);
CREATE INDEX IF NOT EXISTS idx_entities_aliases ON entities USING GIN(aliases);
CREATE INDEX IF NOT EXISTS idx_entities_verification ON entities(verification_status);

DROP TRIGGER IF EXISTS entities_updated_at ON entities;
CREATE TRIGGER entities_updated_at
    BEFORE UPDATE ON entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();


CREATE TABLE IF NOT EXISTS entity_observations (
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

CREATE INDEX IF NOT EXISTS idx_observations_entity ON entity_observations(entity_id);
CREATE INDEX IF NOT EXISTS idx_observations_article ON entity_observations(article_slug);
CREATE INDEX IF NOT EXISTS idx_observations_flagged ON entity_observations(entity_id)
    WHERE disagreements IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_observations_unmatched ON entity_observations(entity_id)
    WHERE entity_id IS NULL;
```

- [ ] **Step 2: Apply schema to local database**

Run: `uv run python -c "from esbvaktin.ground_truth.operations import init_schema; init_schema()"`

Expected: No errors. The `init_schema()` function reads `schema.sql` and executes it. Since we use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`, this is safe to run on an existing database.

- [ ] **Step 3: Verify tables exist**

Run: `uv run python -c "from esbvaktin.ground_truth.operations import get_connection; c = get_connection(); print(c.execute(\"SELECT COUNT(*) FROM entities\").fetchone()); print(c.execute(\"SELECT COUNT(*) FROM entity_observations\").fetchone()); c.close()"`

Expected: `(0,)` printed twice (empty tables).

- [ ] **Step 4: Commit**

```bash
git add src/esbvaktin/ground_truth/schema.sql
git commit -m "feat: add entities and entity_observations tables to schema"
```

---

### Task 2: Entity Registry Package — Models

**Files:**
- Create: `src/esbvaktin/entity_registry/__init__.py`
- Create: `src/esbvaktin/entity_registry/models.py`
- Create: `tests/test_entity_registry.py`

- [ ] **Step 1: Create package init**

Create `src/esbvaktin/entity_registry/__init__.py`:

```python
"""Canonical entity registry — identity, stance, and observation tracking."""
```

- [ ] **Step 2: Write failing tests for models**

Create `tests/test_entity_registry.py`:

```python
"""Tests for entity registry models and operations."""

import pytest
from pydantic import ValidationError

from esbvaktin.entity_registry.models import (
    Entity,
    EntityObservation,
    MatchMethod,
    RoleEntry,
    VerificationStatus,
)


class TestEntity:
    def test_minimal(self):
        e = Entity(slug="bjarni-benediktsson", canonical_name="Bjarni Benediktsson", entity_type="individual")
        assert e.verification_status == VerificationStatus.AUTO_GENERATED
        assert e.aliases == []
        assert e.roles == []
        assert e.is_icelandic is True

    def test_full(self):
        e = Entity(
            slug="bjarni-benediktsson",
            canonical_name="Bjarni Benediktsson",
            entity_type="individual",
            subtype="politician",
            stance="pro_eu",
            stance_score=0.8,
            stance_confidence=0.9,
            party_slug="sjalfstaedisflokkurinn",
            althingi_id=123,
            aliases=["Bjarna Benediktssonar", "Bjarna Benediktssyni"],
            roles=[RoleEntry(role="forsætisráðherra", from_date="2024-01-01")],
            verification_status="confirmed",
        )
        assert e.stance == "pro_eu"
        assert len(e.aliases) == 2
        assert e.roles[0].role == "forsætisráðherra"

    def test_invalid_entity_type(self):
        with pytest.raises(ValidationError):
            Entity(slug="x", canonical_name="X", entity_type="alien")

    def test_invalid_stance(self):
        with pytest.raises(ValidationError):
            Entity(slug="x", canonical_name="X", entity_type="individual", stance="maybe")

    def test_stance_score_bounds(self):
        with pytest.raises(ValidationError):
            Entity(slug="x", canonical_name="X", entity_type="individual", stance_score=1.5)


class TestEntityObservation:
    def test_minimal(self):
        obs = EntityObservation(
            article_slug="test-article",
            observed_name="Bjarni Benediktsson",
        )
        assert obs.entity_id is None
        assert obs.attribution_types == []
        assert obs.match_confidence is None

    def test_with_match(self):
        obs = EntityObservation(
            entity_id=1,
            article_slug="test-article",
            article_url="https://example.com/article",
            observed_name="Bjarna Benediktssonar",
            observed_stance="pro_eu",
            observed_role="forsætisráðherra",
            attribution_types=["quoted", "asserted"],
            claim_indices=[0, 2, 5],
            match_confidence=0.95,
            match_method="exact",
        )
        assert obs.match_method == MatchMethod.EXACT
        assert obs.claim_indices == [0, 2, 5]

    def test_disagreements(self):
        obs = EntityObservation(
            entity_id=1,
            article_slug="test-article",
            observed_name="Test",
            disagreements={"stance": True, "role": True},
        )
        assert obs.disagreements["stance"] is True

    def test_invalid_match_method(self):
        with pytest.raises(ValidationError):
            EntityObservation(
                article_slug="x",
                observed_name="X",
                match_method="telepathy",
            )


class TestRoleEntry:
    def test_current_role(self):
        r = RoleEntry(role="þingmaður", from_date="2024-01-01")
        assert r.to_date is None

    def test_past_role(self):
        r = RoleEntry(role="ráðherra", from_date="2021-06-01", to_date="2023-12-31")
        assert r.to_date == "2023-12-31"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --extra dev python -m pytest tests/test_entity_registry.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'esbvaktin.entity_registry.models'`

- [ ] **Step 4: Write the models**

Create `src/esbvaktin/entity_registry/models.py`:

```python
"""Pydantic models for the canonical entity registry."""

from enum import StrEnum

from pydantic import BaseModel, Field


class VerificationStatus(StrEnum):
    AUTO_GENERATED = "auto_generated"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"


class MatchMethod(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    LEMMA = "lemma"
    FUZZY = "fuzzy"
    MANUAL = "manual"


class RoleEntry(BaseModel):
    """A role held by an entity over a time period."""

    role: str
    from_date: str | None = None
    to_date: str | None = None


class Entity(BaseModel):
    """Canonical entity in the registry."""

    id: int | None = None
    slug: str
    canonical_name: str
    entity_type: str = Field(..., pattern=r"^(individual|party|institution|union)$")
    subtype: str | None = Field(None, pattern=r"^(politician|media)$")
    stance: str | None = Field(None, pattern=r"^(pro_eu|anti_eu|mixed|neutral)$")
    stance_score: float | None = Field(None, ge=-1.0, le=1.0)
    stance_confidence: float | None = Field(None, ge=0.0, le=1.0)
    party_slug: str | None = None
    althingi_id: int | None = None
    aliases: list[str] = Field(default_factory=list)
    roles: list[RoleEntry] = Field(default_factory=list)
    notes: str | None = None
    verification_status: VerificationStatus = VerificationStatus.AUTO_GENERATED
    is_icelandic: bool = True


class EntityObservation(BaseModel):
    """A per-article entity extraction linked to the registry."""

    id: int | None = None
    entity_id: int | None = None
    article_slug: str
    article_url: str | None = None
    observed_name: str
    observed_stance: str | None = None
    observed_role: str | None = None
    observed_party: str | None = None
    observed_type: str | None = None
    attribution_types: list[str] = Field(default_factory=list)
    claim_indices: list[int] = Field(default_factory=list)
    match_confidence: float | None = None
    match_method: MatchMethod | None = None
    disagreements: dict[str, bool] | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --extra dev python -m pytest tests/test_entity_registry.py -v`

Expected: All 10 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/esbvaktin/entity_registry/__init__.py src/esbvaktin/entity_registry/models.py tests/test_entity_registry.py
git commit -m "feat: add entity registry models (Entity, EntityObservation)"
```

---

### Task 3: Entity Registry — DB Operations

**Files:**
- Create: `src/esbvaktin/entity_registry/operations.py`
- Modify: `tests/test_entity_registry.py`

- [ ] **Step 1: Write failing tests for DB operations**

Append to `tests/test_entity_registry.py`:

```python
from esbvaktin.entity_registry.operations import (
    insert_entity,
    insert_observation,
    get_entity_by_slug,
    get_entities_by_status,
    get_observations_for_entity,
    get_review_queue,
    update_entity,
    merge_entities,
)


@pytest.fixture
def db_conn():
    """Get a test DB connection (uses real local DB)."""
    from esbvaktin.ground_truth.operations import get_connection, init_schema

    conn = get_connection()
    init_schema(conn)
    # Clean entity tables for test isolation
    conn.execute("DELETE FROM entity_observations")
    conn.execute("DELETE FROM entities")
    conn.commit()
    yield conn
    # Clean up after tests
    conn.execute("DELETE FROM entity_observations")
    conn.execute("DELETE FROM entities")
    conn.commit()
    conn.close()


class TestInsertEntity:
    def test_insert_and_retrieve(self, db_conn):
        entity = Entity(
            slug="test-person",
            canonical_name="Test Person",
            entity_type="individual",
            stance="pro_eu",
            stance_score=0.8,
            aliases=["Test Personu", "Test Persons"],
        )
        entity_id = insert_entity(entity, db_conn)
        assert entity_id > 0

        retrieved = get_entity_by_slug("test-person", db_conn)
        assert retrieved is not None
        assert retrieved.canonical_name == "Test Person"
        assert retrieved.stance == "pro_eu"
        assert "Test Personu" in retrieved.aliases

    def test_insert_duplicate_slug_raises(self, db_conn):
        entity = Entity(slug="dupe", canonical_name="Dupe", entity_type="individual")
        insert_entity(entity, db_conn)
        with pytest.raises(Exception):
            insert_entity(entity, db_conn)

    def test_returns_none_for_missing_slug(self, db_conn):
        assert get_entity_by_slug("nonexistent", db_conn) is None


class TestInsertObservation:
    def test_insert_linked(self, db_conn):
        entity_id = insert_entity(
            Entity(slug="obs-test", canonical_name="Obs Test", entity_type="individual"),
            db_conn,
        )
        obs = EntityObservation(
            entity_id=entity_id,
            article_slug="article-1",
            article_url="https://example.com/1",
            observed_name="Obs Test",
            observed_stance="pro_eu",
            attribution_types=["quoted"],
            match_confidence=0.95,
            match_method="exact",
        )
        obs_id = insert_observation(obs, db_conn)
        assert obs_id > 0

        observations = get_observations_for_entity(entity_id, db_conn)
        assert len(observations) == 1
        assert observations[0].observed_stance == "pro_eu"

    def test_insert_unlinked(self, db_conn):
        obs = EntityObservation(
            article_slug="article-2",
            observed_name="Unknown Person",
        )
        obs_id = insert_observation(obs, db_conn)
        assert obs_id > 0


class TestReviewQueue:
    def test_queue_includes_needs_review(self, db_conn):
        insert_entity(
            Entity(
                slug="review-me",
                canonical_name="Review Me",
                entity_type="individual",
                verification_status="needs_review",
            ),
            db_conn,
        )
        insert_entity(
            Entity(
                slug="confirmed-one",
                canonical_name="Confirmed",
                entity_type="individual",
                verification_status="confirmed",
            ),
            db_conn,
        )
        queue = get_review_queue(db_conn)
        slugs = [e.slug for e in queue]
        assert "review-me" in slugs
        assert "confirmed-one" not in slugs

    def test_queue_includes_unlinked_observations(self, db_conn):
        insert_observation(
            EntityObservation(article_slug="a", observed_name="Mystery"),
            db_conn,
        )
        queue = get_review_queue(db_conn)
        # Returns entities needing review + unlinked observations
        assert queue.unlinked_count > 0


class TestUpdateEntity:
    def test_update_stance(self, db_conn):
        entity_id = insert_entity(
            Entity(slug="updatable", canonical_name="Updatable", entity_type="individual", stance="neutral"),
            db_conn,
        )
        update_entity(entity_id, {"stance": "pro_eu", "stance_score": 0.7}, db_conn)
        updated = get_entity_by_slug("updatable", db_conn)
        assert updated.stance == "pro_eu"
        assert updated.stance_score == 0.7


class TestMergeEntities:
    def test_merge_absorbs_aliases(self, db_conn):
        keep_id = insert_entity(
            Entity(slug="keep", canonical_name="Keep", entity_type="individual", aliases=["Keeps"]),
            db_conn,
        )
        absorb_id = insert_entity(
            Entity(slug="absorb", canonical_name="Absorb", entity_type="individual", aliases=["Absorbs"]),
            db_conn,
        )
        # Add observations to the absorbed entity
        insert_observation(
            EntityObservation(entity_id=absorb_id, article_slug="a1", observed_name="Absorb"),
            db_conn,
        )

        merge_entities(keep_id=keep_id, absorb_id=absorb_id, conn=db_conn)

        # Absorbed entity should be gone
        assert get_entity_by_slug("absorb", db_conn) is None
        # Keep entity should have absorbed aliases + observations
        keep = get_entity_by_slug("keep", db_conn)
        assert "Absorb" in keep.aliases
        assert "Absorbs" in keep.aliases
        obs = get_observations_for_entity(keep_id, db_conn)
        assert len(obs) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev python -m pytest tests/test_entity_registry.py::TestInsertEntity -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'esbvaktin.entity_registry.operations'`

- [ ] **Step 3: Write the operations module**

Create `src/esbvaktin/entity_registry/operations.py`:

```python
"""DB operations for the canonical entity registry."""

from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg

from .models import Entity, EntityObservation, MatchMethod, VerificationStatus


def insert_entity(entity: Entity, conn: psycopg.Connection) -> int:
    """Insert an entity and return its ID."""
    row = conn.execute(
        """
        INSERT INTO entities (
            slug, canonical_name, entity_type, subtype, stance, stance_score,
            stance_confidence, party_slug, althingi_id, aliases, roles, notes,
            verification_status, is_icelandic
        ) VALUES (
            %(slug)s, %(canonical_name)s, %(entity_type)s, %(subtype)s, %(stance)s,
            %(stance_score)s, %(stance_confidence)s, %(party_slug)s, %(althingi_id)s,
            %(aliases)s, %(roles)s, %(notes)s, %(verification_status)s, %(is_icelandic)s
        ) RETURNING id
        """,
        {
            "slug": entity.slug,
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "subtype": entity.subtype,
            "stance": entity.stance,
            "stance_score": entity.stance_score,
            "stance_confidence": entity.stance_confidence,
            "party_slug": entity.party_slug,
            "althingi_id": entity.althingi_id,
            "aliases": entity.aliases,
            "roles": json.dumps([r.model_dump() for r in entity.roles]),
            "notes": entity.notes,
            "verification_status": entity.verification_status.value,
            "is_icelandic": entity.is_icelandic,
        },
    ).fetchone()
    conn.commit()
    return row[0]


def insert_observation(obs: EntityObservation, conn: psycopg.Connection) -> int:
    """Insert an entity observation and return its ID."""
    row = conn.execute(
        """
        INSERT INTO entity_observations (
            entity_id, article_slug, article_url, observed_name, observed_stance,
            observed_role, observed_party, observed_type, attribution_types,
            claim_indices, match_confidence, match_method, disagreements
        ) VALUES (
            %(entity_id)s, %(article_slug)s, %(article_url)s, %(observed_name)s,
            %(observed_stance)s, %(observed_role)s, %(observed_party)s, %(observed_type)s,
            %(attribution_types)s, %(claim_indices)s, %(match_confidence)s,
            %(match_method)s, %(disagreements)s
        ) RETURNING id
        """,
        {
            "entity_id": obs.entity_id,
            "article_slug": obs.article_slug,
            "article_url": obs.article_url,
            "observed_name": obs.observed_name,
            "observed_stance": obs.observed_stance,
            "observed_role": obs.observed_role,
            "observed_party": obs.observed_party,
            "observed_type": obs.observed_type,
            "attribution_types": obs.attribution_types,
            "claim_indices": obs.claim_indices,
            "match_confidence": obs.match_confidence,
            "match_method": obs.match_method.value if obs.match_method else None,
            "disagreements": json.dumps(obs.disagreements) if obs.disagreements else None,
        },
    ).fetchone()
    conn.commit()
    return row[0]


def get_entity_by_slug(slug: str, conn: psycopg.Connection) -> Entity | None:
    """Look up an entity by slug. Returns None if not found."""
    row = conn.execute(
        """
        SELECT id, slug, canonical_name, entity_type, subtype, stance, stance_score,
               stance_confidence, party_slug, althingi_id, aliases, roles, notes,
               verification_status, is_icelandic
        FROM entities WHERE slug = %(slug)s
        """,
        {"slug": slug},
    ).fetchone()
    if not row:
        return None
    return _row_to_entity(row)


def get_all_entities(conn: psycopg.Connection) -> list[Entity]:
    """Load all entities from the registry."""
    rows = conn.execute(
        """
        SELECT id, slug, canonical_name, entity_type, subtype, stance, stance_score,
               stance_confidence, party_slug, althingi_id, aliases, roles, notes,
               verification_status, is_icelandic
        FROM entities ORDER BY canonical_name
        """
    ).fetchall()
    return [_row_to_entity(row) for row in rows]


def get_entities_by_status(
    status: VerificationStatus, conn: psycopg.Connection
) -> list[Entity]:
    """Get all entities with a given verification status."""
    rows = conn.execute(
        """
        SELECT id, slug, canonical_name, entity_type, subtype, stance, stance_score,
               stance_confidence, party_slug, althingi_id, aliases, roles, notes,
               verification_status, is_icelandic
        FROM entities WHERE verification_status = %(status)s
        ORDER BY canonical_name
        """,
        {"status": status.value},
    ).fetchall()
    return [_row_to_entity(row) for row in rows]


def get_observations_for_entity(
    entity_id: int, conn: psycopg.Connection
) -> list[EntityObservation]:
    """Get all observations linked to an entity."""
    rows = conn.execute(
        """
        SELECT id, entity_id, article_slug, article_url, observed_name, observed_stance,
               observed_role, observed_party, observed_type, attribution_types,
               claim_indices, match_confidence, match_method, disagreements
        FROM entity_observations WHERE entity_id = %(entity_id)s
        ORDER BY created_at
        """,
        {"entity_id": entity_id},
    ).fetchall()
    return [_row_to_observation(row) for row in rows]


@dataclass
class ReviewQueue:
    """Summary of items needing review."""

    entities: list[Entity]
    unlinked_count: int


def get_review_queue(conn: psycopg.Connection) -> ReviewQueue:
    """Get entities needing review + count of unlinked observations."""
    entities = get_entities_by_status(VerificationStatus.NEEDS_REVIEW, conn)

    row = conn.execute(
        "SELECT COUNT(*) FROM entity_observations WHERE entity_id IS NULL"
    ).fetchone()
    unlinked_count = row[0] if row else 0

    return ReviewQueue(entities=entities, unlinked_count=unlinked_count)


def update_entity(
    entity_id: int, updates: dict, conn: psycopg.Connection
) -> None:
    """Update specific fields on an entity.

    Allowed keys: stance, stance_score, stance_confidence, canonical_name,
    entity_type, subtype, party_slug, althingi_id, aliases, roles, notes,
    verification_status, is_icelandic, verified_at, verified_by.
    """
    allowed = {
        "stance", "stance_score", "stance_confidence", "canonical_name",
        "entity_type", "subtype", "party_slug", "althingi_id", "aliases",
        "roles", "notes", "verification_status", "is_icelandic",
        "verified_at", "verified_by",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return

    # Serialise complex types
    if "roles" in filtered and not isinstance(filtered["roles"], str):
        filtered["roles"] = json.dumps(filtered["roles"])
    if "aliases" in filtered:
        # psycopg handles list → TEXT[] natively
        pass

    set_clause = ", ".join(f"{k} = %({k})s" for k in filtered)
    filtered["id"] = entity_id
    conn.execute(f"UPDATE entities SET {set_clause} WHERE id = %(id)s", filtered)
    conn.commit()


def merge_entities(
    keep_id: int, absorb_id: int, conn: psycopg.Connection
) -> None:
    """Merge absorb_id into keep_id: move observations, absorb aliases, delete absorbed entity."""
    # Get both entities
    keep = conn.execute(
        "SELECT aliases, canonical_name FROM entities WHERE id = %(id)s", {"id": keep_id}
    ).fetchone()
    absorb = conn.execute(
        "SELECT aliases, canonical_name, slug FROM entities WHERE id = %(id)s", {"id": absorb_id}
    ).fetchone()
    if not keep or not absorb:
        return

    # Merge aliases: keep's aliases + absorb's name + absorb's aliases (deduplicated)
    merged_aliases = list(keep[0] or [])
    for name in [absorb[1]] + list(absorb[0] or []):
        if name not in merged_aliases:
            merged_aliases.append(name)

    # Update keep entity's aliases
    conn.execute(
        "UPDATE entities SET aliases = %(aliases)s WHERE id = %(id)s",
        {"aliases": merged_aliases, "id": keep_id},
    )

    # Reassign observations from absorbed → keep
    conn.execute(
        "UPDATE entity_observations SET entity_id = %(keep)s WHERE entity_id = %(absorb)s",
        {"keep": keep_id, "absorb": absorb_id},
    )

    # Delete absorbed entity
    conn.execute("DELETE FROM entities WHERE id = %(id)s", {"id": absorb_id})
    conn.commit()


def _row_to_entity(row: tuple) -> Entity:
    """Convert a DB row tuple to an Entity model."""
    from .models import RoleEntry

    roles_raw = row[11]  # JSONB → dict/list
    if isinstance(roles_raw, str):
        roles_raw = json.loads(roles_raw)
    roles = [RoleEntry(**r) for r in (roles_raw or [])]

    return Entity(
        id=row[0],
        slug=row[1],
        canonical_name=row[2],
        entity_type=row[3],
        subtype=row[4],
        stance=row[5],
        stance_score=row[6],
        stance_confidence=row[7],
        party_slug=row[8],
        althingi_id=row[9],
        aliases=list(row[10] or []),
        roles=roles,
        notes=row[12],
        verification_status=row[13],
        is_icelandic=row[14],
    )


def _row_to_observation(row: tuple) -> EntityObservation:
    """Convert a DB row tuple to an EntityObservation model."""
    disagreements = row[13]
    if isinstance(disagreements, str):
        disagreements = json.loads(disagreements)

    return EntityObservation(
        id=row[0],
        entity_id=row[1],
        article_slug=row[2],
        article_url=row[3],
        observed_name=row[4],
        observed_stance=row[5],
        observed_role=row[6],
        observed_party=row[7],
        observed_type=row[8],
        attribution_types=list(row[9] or []),
        claim_indices=list(row[10] or []),
        match_confidence=row[11],
        match_method=row[12],
        disagreements=disagreements,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev python -m pytest tests/test_entity_registry.py -v`

Expected: All tests PASS (requires local PostgreSQL running — `docker compose up -d`).

- [ ] **Step 5: Commit**

```bash
git add src/esbvaktin/entity_registry/operations.py tests/test_entity_registry.py
git commit -m "feat: add entity registry DB operations (CRUD, merge, review queue)"
```

---

### Task 4: Name Matcher — Matching Cascade with BÍN

**Files:**
- Create: `src/esbvaktin/entity_registry/matcher.py`
- Create: `tests/test_entity_matcher.py`

- [ ] **Step 1: Write failing tests for matcher**

Create `tests/test_entity_matcher.py`:

```python
"""Tests for the entity name matcher — matching cascade and confidence scoring."""

import pytest

from esbvaktin.entity_registry.matcher import (
    MATCH_THRESHOLDS,
    MatchResult,
    compute_disagreements,
    lemmatise_name,
    match_entity,
)
from esbvaktin.entity_registry.models import Entity


@pytest.fixture
def registry() -> list[Entity]:
    """A small entity registry for testing."""
    return [
        Entity(
            id=1,
            slug="bjarni-benediktsson",
            canonical_name="Bjarni Benediktsson",
            entity_type="individual",
            stance="pro_eu",
            party_slug="sjalfstaedisflokkurinn",
            aliases=["Bjarna Benediktssonar"],
        ),
        Entity(
            id=2,
            slug="vidreisn",
            canonical_name="Viðreisn",
            entity_type="party",
            stance="pro_eu",
            aliases=["Viðreisnar"],
        ),
        Entity(
            id=3,
            slug="kristrun-frostadottir",
            canonical_name="Kristrún Frostadóttir",
            entity_type="individual",
            stance="pro_eu",
            aliases=["Kristrúnu Frostadóttur", "Kristrúnar Frostadóttur"],
        ),
    ]


class TestExactMatch:
    def test_exact_canonical(self, registry):
        result = match_entity("Bjarni Benediktsson", "individual", registry)
        assert result.entity_id == 1
        assert result.method == "exact"
        assert result.confidence >= MATCH_THRESHOLDS["auto_link"]

    def test_exact_alias(self, registry):
        result = match_entity("Bjarna Benediktssonar", "individual", registry)
        assert result.entity_id == 1
        assert result.method == "alias"
        assert result.confidence >= MATCH_THRESHOLDS["auto_link"]

    def test_case_insensitive(self, registry):
        result = match_entity("bjarni benediktsson", "individual", registry)
        assert result.entity_id == 1


class TestLemmaMatch:
    """These tests rely on BÍN being available (islenska package).

    They are skipped if islenska is not installed.
    """

    @pytest.fixture(autouse=True)
    def _skip_without_islenska(self):
        try:
            from islenska import Bin  # noqa: F401
        except ImportError:
            pytest.skip("islenska not installed")

    def test_lemmatise_known_name(self):
        # "Bjarna" is accusative/dative of "Bjarni"
        lemma = lemmatise_name("Bjarna")
        # Should return nominative form(s)
        assert lemma is not None


class TestSubsetMatch:
    def test_two_word_subset(self, registry):
        result = match_entity("Kristrún Frostadóttir forsætisráðherra", "individual", registry)
        assert result.entity_id == 3
        assert result.method == "fuzzy"
        assert result.confidence >= MATCH_THRESHOLDS["flag"]

    def test_single_word_is_low(self, registry):
        result = match_entity("Bjarni", "individual", registry)
        # Single word match should be LOW confidence
        assert result.confidence < MATCH_THRESHOLDS["flag"]


class TestNoMatch:
    def test_unknown_name(self, registry):
        result = match_entity("Guðmundur Sigurðsson", "individual", registry)
        assert result.entity_id is None
        assert result.confidence == 0.0

    def test_type_mismatch_lowers_confidence(self, registry):
        # "Viðreisn" exists as party, but searching as individual
        result = match_entity("Viðreisn", "individual", registry)
        assert result.confidence < MATCH_THRESHOLDS["flag"]


class TestDisagreements:
    def test_stance_disagreement(self):
        entity = Entity(
            id=1, slug="x", canonical_name="X", entity_type="individual", stance="pro_eu"
        )
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance="anti_eu",
            observed_role=None,
            observed_party=None,
            observed_type="individual",
        )
        assert disagreements["stance"] is True
        assert "role" not in disagreements

    def test_neutral_observation_no_disagreement(self):
        entity = Entity(
            id=1, slug="x", canonical_name="X", entity_type="individual", stance="pro_eu"
        )
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance="neutral",
            observed_role=None,
            observed_party=None,
            observed_type="individual",
        )
        assert disagreements is None

    def test_type_disagreement(self):
        entity = Entity(
            id=1, slug="x", canonical_name="X", entity_type="individual"
        )
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance=None,
            observed_role=None,
            observed_party=None,
            observed_type="institution",
        )
        assert disagreements["type"] is True

    def test_party_disagreement(self):
        entity = Entity(
            id=1, slug="x", canonical_name="X", entity_type="individual",
            party_slug="vidreisn",
        )
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance=None,
            observed_role=None,
            observed_party="Samfylkingin",
            observed_type="individual",
        )
        assert disagreements["party"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev python -m pytest tests/test_entity_matcher.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'esbvaktin.entity_registry.matcher'`

- [ ] **Step 3: Write the matcher module**

Create `src/esbvaktin/entity_registry/matcher.py`:

```python
"""Entity name matcher — confidence-tiered matching cascade with BÍN lemmatisation."""

from __future__ import annotations

from dataclasses import dataclass

from esbvaktin.utils.slugify import icelandic_slugify

from .models import Entity

try:
    from islenska import Bin

    _HAS_ISLENSKA = True
except ImportError:
    _HAS_ISLENSKA = False


MATCH_THRESHOLDS = {
    "auto_link": 0.9,  # above: silent auto-link
    "flag": 0.5,  # above: auto-link + flag for review
    # below flag: queue for review, don't auto-link
}

# Cache for BÍN lemma lookups within a pipeline run
_lemma_cache: dict[str, str | None] = {}


@dataclass
class MatchResult:
    """Result of matching an observed name against the entity registry."""

    entity_id: int | None
    confidence: float
    method: str  # exact, alias, lemma, fuzzy
    matched_entity: Entity | None = None


def lemmatise_name(word: str) -> str | None:
    """Look up the nominative (lemma) form of an Icelandic word via BÍN.

    Returns the lemma if found, None if the word is not in BÍN.
    Caches results for the duration of the process.
    """
    if not _HAS_ISLENSKA:
        return None

    key = word.lower()
    if key in _lemma_cache:
        return _lemma_cache[key]

    b = Bin()
    _, meanings = b.lookup(key)
    if meanings:
        # Take the first nominative form (nefnifall)
        lemma = meanings[0].stofn
        _lemma_cache[key] = lemma
        return lemma

    # Try original casing (proper nouns)
    _, meanings = b.lookup(word)
    if meanings:
        lemma = meanings[0].stofn
        _lemma_cache[key] = lemma
        return lemma

    _lemma_cache[key] = None
    return None


def _lemmatise_full_name(name: str) -> str:
    """Lemmatise each word in a full name, returning space-joined result.

    Words not found in BÍN are kept as-is.
    """
    parts = []
    for word in name.split():
        lemma = lemmatise_name(word)
        parts.append(lemma if lemma else word)
    return " ".join(parts)


def _normalise(name: str) -> str:
    """Lowercase and strip whitespace for comparison."""
    return name.lower().strip()


def _words(name: str) -> set[str]:
    """Split a name into a set of lowercase words."""
    return set(name.lower().split())


def match_entity(
    observed_name: str,
    observed_type: str,
    registry: list[Entity],
) -> MatchResult:
    """Match an observed entity name against the registry using the matching cascade.

    Steps (first match wins):
    1. Exact match on canonical_name → HIGH (0.95)
    2. Exact match on any alias → HIGH (0.95)
    3. Lemmatise + match canonical → HIGH (0.90)
    4. Lemmatise + match aliases → MEDIUM (0.75)
    5. Subset match (2+ words, same type) → MEDIUM (0.60)
    6. Weak subset (1 word or type mismatch) → LOW (0.30)
    7. No match → NEW (0.0)
    """
    norm_observed = _normalise(observed_name)

    # Step 1: Exact match on canonical_name
    for entity in registry:
        if _normalise(entity.canonical_name) == norm_observed:
            return MatchResult(entity.id, 0.95, "exact", entity)

    # Step 2: Exact match on any alias
    for entity in registry:
        for alias in entity.aliases:
            if _normalise(alias) == norm_observed:
                return MatchResult(entity.id, 0.95, "alias", entity)

    # Step 3: Lemmatise observed name, match against lemmatised canonical
    if _HAS_ISLENSKA:
        lemma_observed = _lemmatise_full_name(observed_name)
        norm_lemma_observed = _normalise(lemma_observed)

        for entity in registry:
            lemma_canonical = _lemmatise_full_name(entity.canonical_name)
            if _normalise(lemma_canonical) == norm_lemma_observed:
                return MatchResult(entity.id, 0.90, "lemma", entity)

        # Step 4: Lemmatise observed, match against lemmatised aliases
        for entity in registry:
            for alias in entity.aliases:
                lemma_alias = _lemmatise_full_name(alias)
                if _normalise(lemma_alias) == norm_lemma_observed:
                    return MatchResult(entity.id, 0.75, "lemma", entity)

    # Step 5: Subset match (2+ shared words, same entity type)
    obs_words = _words(observed_name)
    best_subset: MatchResult | None = None

    for entity in registry:
        # Check canonical name and all aliases
        all_names = [entity.canonical_name] + entity.aliases
        for name in all_names:
            name_words = _words(name)
            short, long_ = (
                (obs_words, name_words)
                if len(obs_words) <= len(name_words)
                else (name_words, obs_words)
            )
            overlap = short & long_

            if len(overlap) >= 2 and short.issubset(long_):
                same_type = entity.entity_type == observed_type
                if same_type:
                    # Step 5: MEDIUM
                    return MatchResult(entity.id, 0.60, "fuzzy", entity)
                elif best_subset is None:
                    # Step 6: LOW (type mismatch)
                    best_subset = MatchResult(entity.id, 0.30, "fuzzy", entity)

            elif len(overlap) == 1 and len(short) <= 2:
                # Step 6: Weak single-word overlap → LOW
                if best_subset is None:
                    best_subset = MatchResult(entity.id, 0.30, "fuzzy", entity)

    if best_subset:
        return best_subset

    # Step 7: No match
    return MatchResult(None, 0.0, "exact", None)


def compute_disagreements(
    entity: Entity,
    observed_stance: str | None,
    observed_role: str | None,
    observed_party: str | None,
    observed_type: str | None,
) -> dict[str, bool] | None:
    """Compare observation fields against the registry entity.

    Returns a dict of disagreeing fields, or None if no disagreements.
    Neutral observations are ignored for stance comparison.
    """
    disagreements: dict[str, bool] = {}

    # Stance: ignore neutral observations
    if observed_stance and observed_stance != "neutral" and entity.stance:
        if observed_stance != entity.stance:
            disagreements["stance"] = True

    # Role: check if observed role appears in any role entry
    if observed_role and entity.roles:
        role_names = {r.role.lower() for r in entity.roles}
        if observed_role.lower() not in role_names:
            disagreements["role"] = True

    # Party: compare against party_slug (normalised)
    if observed_party and entity.party_slug:
        obs_slug = icelandic_slugify(observed_party)
        if obs_slug != entity.party_slug:
            disagreements["party"] = True

    # Type
    if observed_type and observed_type != entity.entity_type:
        disagreements["type"] = True

    return disagreements if disagreements else None


def clear_lemma_cache() -> None:
    """Clear the BÍN lemma cache (call between pipeline runs)."""
    _lemma_cache.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev python -m pytest tests/test_entity_matcher.py -v`

Expected: All non-BÍN tests PASS. BÍN tests pass if `uv sync --extra icelandic` was run, otherwise they are skipped.

- [ ] **Step 5: Run all tests to check for regressions**

Run: `uv run --extra dev python -m pytest -v`

Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/esbvaktin/entity_registry/matcher.py tests/test_entity_matcher.py
git commit -m "feat: add entity name matcher with confidence-tiered cascade and BÍN"
```

---

### Task 5: Migration Script — Big-Bang Import

**Files:**
- Create: `scripts/migrate_entities.py`

This script reuses the merge logic from `export_entities.py` to bootstrap the registry. It runs once, is idempotent, and produces a migration report.

- [ ] **Step 1: Create the migration script**

Create `scripts/migrate_entities.py`:

```python
"""Migrate existing entities into the canonical entity registry.

Big-bang migration: loads all _entities.json files via export_entities.py merge
logic, inserts into entities + entity_observations tables, and generates a
migration report.

Usage:
    uv run python scripts/migrate_entities.py --status      # Preview
    uv run python scripts/migrate_entities.py               # Run migration
    uv run python scripts/migrate_entities.py --report      # Show migration report
    uv run python scripts/migrate_entities.py --dry-run     # Preview without DB writes
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"
REPORT_PATH = PROJECT_ROOT / "data" / "export" / "entity_migration_report.json"

sys.path.insert(0, str(PROJECT_ROOT))

# Import export_entities functions via importlib (it's a script, not a package)
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "export_entities", PROJECT_ROOT / "scripts" / "export_entities.py"
)
_export_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_export_mod)

from esbvaktin.entity_registry.matcher import clear_lemma_cache
from esbvaktin.entity_registry.models import Entity, EntityObservation, VerificationStatus
from esbvaktin.entity_registry.operations import (
    get_all_entities,
    get_entity_by_slug,
    insert_entity,
    insert_observation,
)
from esbvaktin.utils.slugify import icelandic_slugify

# Re-bind names from the dynamically loaded export module
_CANONICAL_NAMES = _export_mod._CANONICAL_NAMES
_NAME_ALIASES = _export_mod._NAME_ALIASES
_ROLE_OVERRIDES = _export_mod._ROLE_OVERRIDES
_SKIP_NAMES = _export_mod._SKIP_NAMES
_compute_scores = _export_mod._compute_scores
_enrich_althingi_stats = _export_mod._enrich_althingi_stats
_enrich_party_affiliations = _export_mod._enrich_party_affiliations
_classify_media_outlets = _export_mod._classify_media_outlets
_classify_subtypes = _export_mod._classify_subtypes
_load_mp_roster = _export_mod._load_mp_roster
load_all_entities = _export_mod.load_all_entities

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def _build_entity_row(slug: str, data: dict) -> Entity:
    """Convert a merged entity dict from export_entities into an Entity model."""
    aliases = []
    # Collect aliases from _NAME_ALIASES that point to this slug
    for variant, target_slug in _NAME_ALIASES.items():
        if target_slug == slug and variant.lower() != data["name"].lower():
            aliases.append(variant)

    # Canonical name override
    canonical_name = _CANONICAL_NAMES.get(slug, data["name"])

    # Role history (current role only — no historical data in old system)
    from esbvaktin.entity_registry.models import RoleEntry

    roles = []
    role = _ROLE_OVERRIDES.get(slug, data.get("role"))
    if role:
        roles = [RoleEntry(role=role)]

    # Althingi ID from enriched stats
    althingi_id = None  # Not tracked in old system — will be backfilled in Phase 2

    return Entity(
        slug=slug,
        canonical_name=canonical_name,
        entity_type=data["type"],
        subtype=data.get("subtype"),
        stance=data.get("stance"),
        stance_score=data.get("stance_score"),
        party_slug=data.get("party_slug"),
        althingi_id=althingi_id,
        aliases=aliases,
        roles=roles,
        notes=None,
        verification_status=VerificationStatus.AUTO_GENERATED,
        is_icelandic=data.get("icelandic", True),
    )


def _load_observations_from_analyses(slug_map: dict[str, int]) -> list[EntityObservation]:
    """Load per-article entity observations from all _entities.json files.

    slug_map: {slug: entity_id} for linking observations to entities.
    """
    observations = []
    for analysis_dir in sorted(ANALYSES_DIR.iterdir()):
        if not analysis_dir.is_dir():
            continue

        entities_path = analysis_dir / "_entities.json"
        report_path = analysis_dir / "_report_final.json"
        if not entities_path.exists():
            continue

        raw = json.loads(entities_path.read_text())
        article_url = None
        article_slug = analysis_dir.name
        if report_path.exists():
            report = json.loads(report_path.read_text())
            article_url = report.get("article_url")
            title = report.get("article_title", analysis_dir.name)
            article_slug = icelandic_slugify(title)

        all_speakers = []
        author = raw.get("article_author")
        if author and author.get("name"):
            all_speakers.append(author)
        for speaker in raw.get("speakers", []):
            if speaker.get("name"):
                all_speakers.append(speaker)

        for speaker in all_speakers:
            name = speaker["name"]
            if name.lower() in _SKIP_NAMES:
                continue

            # Resolve slug the same way export_entities does
            speaker_slug = _NAME_ALIASES.get(name.lower(), icelandic_slugify(name))
            entity_id = slug_map.get(speaker_slug)

            # Attribution types from this speaker
            attr_types = []
            claim_indices = []
            attributions = speaker.get("attributions", [])
            if attributions:
                for a in attributions:
                    attr_type = a.get("attribution", "asserted")
                    if attr_type not in attr_types:
                        attr_types.append(attr_type)
                    claim_indices.append(a["claim_index"])
            else:
                # Legacy: bare claim_indices → all asserted
                claim_indices = speaker.get("claim_indices", [])
                if claim_indices:
                    attr_types = ["asserted"]

            observations.append(EntityObservation(
                entity_id=entity_id,
                article_slug=article_slug,
                article_url=article_url,
                observed_name=name,
                observed_stance=speaker.get("stance"),
                observed_role=speaker.get("role"),
                observed_party=speaker.get("party"),
                observed_type=speaker.get("type"),
                attribution_types=attr_types,
                claim_indices=claim_indices,
                match_confidence=0.95 if entity_id else None,
                match_method="exact" if entity_id else None,
            ))

    return observations


def _generate_report(entities: list[Entity], observations: list[EntityObservation]) -> dict:
    """Generate a migration report flagging potential issues."""
    # Group observations by entity
    obs_by_entity: dict[int | None, list[EntityObservation]] = defaultdict(list)
    for obs in observations:
        obs_by_entity[obs.entity_id].append(obs)

    report = {
        "total_entities": len(entities),
        "total_observations": len(observations),
        "orphan_observations": len(obs_by_entity.get(None, [])),
        "potential_duplicates": [],
        "stance_conflicts": [],
        "type_mismatches": [],
        "placeholder_entities": [],
    }

    # Check for potential duplicates (overlapping aliases or similar names)
    entity_names: dict[str, list[str]] = {}  # lowered name → [slugs]
    for e in entities:
        names = [e.canonical_name.lower()] + [a.lower() for a in e.aliases]
        for n in names:
            entity_names.setdefault(n, []).append(e.slug)
    for name, slugs in entity_names.items():
        if len(slugs) > 1:
            report["potential_duplicates"].append({"name": name, "slugs": slugs})

    # Stance conflicts: entities where observations disagree
    for e in entities:
        if e.id is None:
            continue
        stances = {o.observed_stance for o in obs_by_entity.get(e.id, []) if o.observed_stance}
        non_neutral = stances - {"neutral", None}
        if len(non_neutral) > 1:
            report["stance_conflicts"].append({
                "slug": e.slug,
                "name": e.canonical_name,
                "observed_stances": list(non_neutral),
                "registry_stance": e.stance,
            })

    # Placeholder entities (zero observations)
    for e in entities:
        if e.id and not obs_by_entity.get(e.id):
            report["placeholder_entities"].append({"slug": e.slug, "name": e.canonical_name})

    return report


def migrate(dry_run: bool = False) -> dict:
    """Run the big-bang entity migration.

    Returns the migration report dict.
    """
    logger.info("Loading and merging existing entities via export_entities logic...")
    merged = load_all_entities()
    _compute_scores(merged)
    _enrich_althingi_stats(merged)
    _classify_subtypes(merged)
    _classify_media_outlets(merged)
    roster = _load_mp_roster()
    _enrich_party_affiliations(merged, roster)

    logger.info("Found %d merged entities", len(merged))

    if dry_run:
        logger.info("[DRY RUN] Would insert %d entities", len(merged))
        return {"total_entities": len(merged), "dry_run": True}

    from esbvaktin.ground_truth.operations import get_connection, init_schema

    conn = get_connection()
    init_schema(conn)

    # Check if already migrated
    existing = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    if existing > 0:
        logger.info("Registry already has %d entities. Use --force to re-migrate.", existing)
        if "--force" not in sys.argv:
            conn.close()
            return {"skipped": True, "existing_count": existing}
        logger.info("--force: clearing existing data for re-migration")
        conn.execute("DELETE FROM entity_observations")
        conn.execute("DELETE FROM entities")
        conn.commit()

    # Insert entities
    slug_map: dict[str, int] = {}
    entities: list[Entity] = []
    for slug, data in merged.items():
        entity = _build_entity_row(slug, data)
        entity_id = insert_entity(entity, conn)
        slug_map[slug] = entity_id
        entity.id = entity_id
        entities.append(entity)

    logger.info("Inserted %d entities", len(entities))

    # Backfill observations from _entities.json files
    observations = _load_observations_from_analyses(slug_map)
    for obs in observations:
        insert_observation(obs, conn)

    logger.info("Inserted %d observations", len(observations))

    # Generate and save report
    report = _generate_report(entities, observations)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    logger.info("Migration report saved to %s", REPORT_PATH)

    conn.close()
    clear_lemma_cache()

    return report


def show_status():
    """Show current registry status."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()
    entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    obs_count = conn.execute("SELECT COUNT(*) FROM entity_observations").fetchone()[0]
    by_status = conn.execute(
        "SELECT verification_status, COUNT(*) FROM entities GROUP BY verification_status"
    ).fetchall()
    unlinked = conn.execute(
        "SELECT COUNT(*) FROM entity_observations WHERE entity_id IS NULL"
    ).fetchone()[0]
    conn.close()

    print(f"Entity registry: {entity_count} entities, {obs_count} observations")
    for status, count in by_status:
        print(f"  {status}: {count}")
    if unlinked:
        print(f"  Unlinked observations: {unlinked}")


def show_report():
    """Show the migration report."""
    if not REPORT_PATH.exists():
        print("No migration report found. Run migration first.")
        return

    report = json.loads(REPORT_PATH.read_text())
    print(f"Entities: {report['total_entities']}")
    print(f"Observations: {report['total_observations']}")
    print(f"Orphan observations: {report['orphan_observations']}")

    dupes = report.get("potential_duplicates", [])
    if dupes:
        print(f"\nPotential duplicates ({len(dupes)}):")
        for d in dupes:
            print(f"  '{d['name']}' → {d['slugs']}")

    conflicts = report.get("stance_conflicts", [])
    if conflicts:
        print(f"\nStance conflicts ({len(conflicts)}):")
        for c in conflicts:
            print(f"  {c['name']}: registry={c['registry_stance']}, observed={c['observed_stances']}")

    placeholders = report.get("placeholder_entities", [])
    if placeholders:
        print(f"\nPlaceholder entities ({len(placeholders)}):")
        for p in placeholders:
            print(f"  {p['slug']} ({p['name']})")


def main():
    if "--status" in sys.argv:
        show_status()
    elif "--report" in sys.argv:
        show_report()
    else:
        dry_run = "--dry-run" in sys.argv
        report = migrate(dry_run=dry_run)
        if not dry_run and not report.get("skipped"):
            print(f"\nMigration complete: {report['total_entities']} entities, "
                  f"{report['total_observations']} observations")
            show_report()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test migration in dry-run mode**

Run: `uv run python scripts/migrate_entities.py --dry-run`

Expected: Prints "Would insert N entities" without touching DB.

- [ ] **Step 3: Run the actual migration**

Run: `uv run python scripts/migrate_entities.py`

Expected: Inserts ~541 entities and ~2000+ observations. Prints migration report with any flagged issues.

- [ ] **Step 4: Verify migration results**

Run: `uv run python scripts/migrate_entities.py --status`

Expected: Shows entity count matching the merged count, all with `auto_generated` status.

- [ ] **Step 5: Review the migration report**

Run: `uv run python scripts/migrate_entities.py --report`

Expected: Shows potential duplicates, stance conflicts, and any placeholder entities. Review these — they'll be the starting queue for `/entity-review`.

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_entities.py
git commit -m "feat: add entity migration script (big-bang import from existing analyses)"
```

---

### Task 6: Integration — Wire Matcher into Article Registration

**Files:**
- Modify: `scripts/register_article_sightings.py`

This wires the entity matcher into the existing sighting registration flow so that every new article analysis records entity observations.

- [ ] **Step 1: Write a test for the integration function**

Append to `tests/test_entity_matcher.py`:

```python
class TestMatchAndRecord:
    """Test the high-level match_and_record_entities function."""

    def test_returns_summary(self):
        from esbvaktin.entity_registry.matcher import match_and_record_summary

        # Verify the summary structure
        summary = match_and_record_summary(auto_linked=2, flagged=1, new_entities=0, disagreements=["stance"])
        assert summary["auto_linked"] == 2
        assert summary["flagged"] == 1
        assert "stance" in summary["disagreements"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/test_entity_matcher.py::TestMatchAndRecord -v`

Expected: FAIL — `ImportError`

- [ ] **Step 3: Add the summary helper to matcher.py**

Add to the end of `src/esbvaktin/entity_registry/matcher.py`:

```python
def match_and_record_summary(
    auto_linked: int = 0,
    flagged: int = 0,
    new_entities: int = 0,
    disagreements: list[str] | None = None,
) -> dict:
    """Build a summary dict for pipeline output."""
    return {
        "auto_linked": auto_linked,
        "flagged": flagged,
        "new_entities": new_entities,
        "disagreements": disagreements or [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/test_entity_matcher.py::TestMatchAndRecord -v`

Expected: PASS

- [ ] **Step 5: Add `register_entity_observations` function to register_article_sightings.py**

Add the following function to `scripts/register_article_sightings.py`, after the existing `register_article` function (around line 242):

```python
def register_entity_observations(
    analysis_dir: str,
    report: dict,
    conn,
    dry_run: bool = False,
) -> dict[str, int]:
    """Register entity observations for a single article's entities.

    Loads _entities.json, matches each speaker against the entity registry,
    and inserts observations with disagreement tracking.

    Returns summary: {"auto_linked": N, "flagged": N, "new_entities": N, "disagreements": [...]}.
    """
    entities_path = ANALYSES_DIR / analysis_dir / "_entities.json"
    if not entities_path.exists():
        return {"auto_linked": 0, "flagged": 0, "new_entities": 0, "disagreements": []}

    from esbvaktin.entity_registry.matcher import (
        MATCH_THRESHOLDS,
        compute_disagreements,
        match_and_record_summary,
        match_entity,
    )
    from esbvaktin.entity_registry.models import Entity, EntityObservation, VerificationStatus
    from esbvaktin.entity_registry.operations import (
        get_all_entities,
        insert_entity,
        insert_observation,
        update_entity,
    )

    raw = json.loads(entities_path.read_text())
    article_url = report.get("article_url", "")
    article_title = report.get("article_title", analysis_dir)
    article_slug = icelandic_slugify(article_title)

    registry = get_all_entities(conn)
    auto_linked = 0
    flagged = 0
    new_entities = 0
    disagreement_types: list[str] = []

    all_speakers = []
    author = raw.get("article_author")
    if author and author.get("name"):
        all_speakers.append(author)
    for speaker in raw.get("speakers", []):
        if speaker.get("name"):
            all_speakers.append(speaker)

    for speaker in all_speakers:
        name = speaker["name"]
        if name.lower() in _ENTITY_SKIP_NAMES:
            continue

        observed_type = speaker.get("type", "individual")
        result = match_entity(name, observed_type, registry)

        # Build attribution types list
        attr_types = []
        claim_indices = []
        attributions = speaker.get("attributions", [])
        if attributions:
            for a in attributions:
                attr_type = a.get("attribution", "asserted")
                if attr_type not in attr_types:
                    attr_types.append(attr_type)
                claim_indices.append(a["claim_index"])
        else:
            claim_indices = speaker.get("claim_indices", [])
            if claim_indices:
                attr_types = ["asserted"]

        # Compute disagreements if matched
        disagreements = None
        if result.matched_entity:
            disagreements = compute_disagreements(
                entity=result.matched_entity,
                observed_stance=speaker.get("stance"),
                observed_role=speaker.get("role"),
                observed_party=speaker.get("party"),
                observed_type=observed_type,
            )
            if disagreements:
                for key in disagreements:
                    if key not in disagreement_types:
                        disagreement_types.append(key)
                # Bump to at least MEDIUM if disagreements found
                if result.confidence >= MATCH_THRESHOLDS["auto_link"]:
                    result.confidence = max(result.confidence, MATCH_THRESHOLDS["flag"])

        entity_id = result.entity_id

        if result.confidence >= MATCH_THRESHOLDS["auto_link"] and not disagreements:
            auto_linked += 1
        elif result.confidence >= MATCH_THRESHOLDS["flag"]:
            flagged += 1
            # Flag the matched entity for review if not already
            if entity_id and result.matched_entity:
                if result.matched_entity.verification_status != VerificationStatus.NEEDS_REVIEW:
                    if not dry_run:
                        update_entity(entity_id, {"verification_status": "needs_review"}, conn)
        else:
            # LOW or no match — create new auto_generated entity
            if not dry_run:
                slug = icelandic_slugify(name)
                new_entity = Entity(
                    slug=slug,
                    canonical_name=name,
                    entity_type=observed_type,
                    stance=speaker.get("stance"),
                    verification_status=VerificationStatus.NEEDS_REVIEW,
                )
                try:
                    entity_id = insert_entity(new_entity, conn)
                    new_entities += 1
                except Exception:
                    # Slug collision — entity already exists, link to it
                    from esbvaktin.entity_registry.operations import get_entity_by_slug
                    existing = get_entity_by_slug(slug, conn)
                    if existing:
                        entity_id = existing.id
                        flagged += 1
                    else:
                        entity_id = None
                        new_entities += 1

        if not dry_run:
            obs = EntityObservation(
                entity_id=entity_id,
                article_slug=article_slug,
                article_url=article_url,
                observed_name=name,
                observed_stance=speaker.get("stance"),
                observed_role=speaker.get("role"),
                observed_party=speaker.get("party"),
                observed_type=observed_type,
                attribution_types=attr_types,
                claim_indices=claim_indices,
                match_confidence=result.confidence,
                match_method=result.method,
                disagreements=disagreements,
            )
            insert_observation(obs, conn)

    return match_and_record_summary(auto_linked, flagged, new_entities, disagreement_types)
```

- [ ] **Step 6: Wire into the main registration flow**

In `scripts/register_article_sightings.py`, modify the `main()` function's registration loop (around line 348). After the `register_article()` call, add the entity observation call.

Find this block in `main()`:

```python
            report = json.loads(report_path.read_text())
            counts = register_article(a["analysis_dir"], report, conn, dry_run=args.dry_run)
```

Add after it:

```python
            # Register entity observations
            entity_summary = register_entity_observations(
                a["analysis_dir"], report, conn, dry_run=args.dry_run,
            )
            if entity_summary.get("flagged") or entity_summary.get("new_entities"):
                logger.info(
                    "  Entities: %d auto-linked, %d flagged, %d new%s",
                    entity_summary["auto_linked"],
                    entity_summary["flagged"],
                    entity_summary["new_entities"],
                    f" (disagreements: {entity_summary['disagreements']})"
                    if entity_summary["disagreements"] else "",
                )
```

Also add the same call for the single-article path (around line 334):

Find:

```python
        counts = register_article(args.dir, report, conn, dry_run=args.dry_run)
        prefix = "[DRY RUN] " if args.dry_run else ""
        print(f"{prefix}{args.dir}: {counts}")
```

Add after:

```python
        entity_summary = register_entity_observations(args.dir, report, conn, dry_run=args.dry_run)
        print(f"{prefix}Entities: {entity_summary}")
```

- [ ] **Step 7: Add missing import**

Add to the imports at the top of `scripts/register_article_sightings.py`:

```python
from esbvaktin.utils.slugify import icelandic_slugify
```

Also import `_SKIP_NAMES` from export_entities at the top of `register_entity_observations` or add it as a module-level constant. The simplest approach is to define it locally:

```python
# At module level, after existing _ATTR_PRIORITY
_ENTITY_SKIP_NAMES = {
    "formaður miðflokksins",
    "formaður sjálfstæðisflokksins",
    "utanríkisráðherra",
    "formenn ríkisstjórnarflokkanna",
    "talsmenn esb-aðildar",
    "mbl.is fréttaritari",
    "ritstjórn mbl.is",
}
```

And use `_ENTITY_SKIP_NAMES` instead of `_SKIP_NAMES` in `register_entity_observations`.

- [ ] **Step 8: Run all tests**

Run: `uv run --extra dev python -m pytest -v`

Expected: All tests pass. No regressions.

- [ ] **Step 9: Test with a single article (dry run)**

Run: `uv run python scripts/register_article_sightings.py --dir <any_analysis_dir> --dry-run`

Replace `<any_analysis_dir>` with an actual directory name from `data/analyses/`. Expected: prints claim counts plus entity summary.

- [ ] **Step 10: Commit**

```bash
git add scripts/register_article_sightings.py tests/test_entity_matcher.py src/esbvaktin/entity_registry/matcher.py
git commit -m "feat: wire entity matcher into article sighting registration"
```

---

### Task 7: Update Schema Documentation and CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/rules/db-schema.md`

- [ ] **Step 1: Add entity tables to db-schema.md**

Add to `.claude/rules/db-schema.md` after the `article_claims` row:

```markdown
| `entities` | `slug` (unique), `canonical_name`, `entity_type`, `subtype`, `stance`, `stance_score REAL`, `stance_confidence REAL`, `party_slug`, `althingi_id INT`, `aliases TEXT[]`, `roles JSONB`, `verification_status` (auto_generated/needs_review/confirmed) | Canonical entity registry. `aliases` has GIN index for containment queries. |
| `entity_observations` | `entity_id` FK, `article_slug`, `article_url`, `observed_name`, `observed_stance`, `observed_role`, `observed_party`, `observed_type`, `attribution_types TEXT[]`, `claim_indices INT[]`, `match_confidence REAL`, `match_method`, `disagreements JSONB` | Per-article entity extractions linked to registry. `entity_id = NULL` means unmatched. |
```

- [ ] **Step 2: Add entity registry commands to CLAUDE.md**

Add to the `Key Commands` section in CLAUDE.md under a new `# Entity registry` heading:

```bash
# Entity registry
uv run python scripts/migrate_entities.py --status     # Registry status (counts, verification breakdown)
uv run python scripts/migrate_entities.py              # Run big-bang migration
uv run python scripts/migrate_entities.py --report     # Show migration report (duplicates, conflicts)
uv run python scripts/migrate_entities.py --force      # Re-run migration (clears existing data)
```

- [ ] **Step 3: Add entity_registry to Project Structure in CLAUDE.md**

Add under `src/esbvaktin/`:

```
  entity_registry/        # Canonical entity registry (identity, stance, observations)
    models.py             # Entity, EntityObservation, VerificationStatus
    operations.py         # DB CRUD (insert, update, merge, query)
    matcher.py            # Name matching cascade (BÍN lemmatisation + aliases)
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md .claude/rules/db-schema.md
git commit -m "docs: add entity registry to schema reference and CLAUDE.md"
```

---

### Task 8: Run Full Test Suite and Verify

**Files:** None (verification only)

- [ ] **Step 1: Run lint**

Run: `uv run --extra dev ruff check src/esbvaktin/entity_registry/ scripts/migrate_entities.py tests/test_entity_matcher.py tests/test_entity_registry.py`

Expected: No lint errors.

- [ ] **Step 2: Run all tests**

Run: `uv run --extra dev python -m pytest -v`

Expected: All tests pass, including new entity registry tests.

- [ ] **Step 3: Verify migration report is useful**

Run: `uv run python scripts/migrate_entities.py --report`

Expected: Report shows actionable items — duplicates to merge, stance conflicts to review, placeholders to clean up. These will be the starting queue for Phase 2's `/entity-review` skill.

- [ ] **Step 4: Verify existing export still works**

Run: `uv run python scripts/export_entities.py --status`

Expected: Same output as before migration — no regression. The old export path is completely untouched.

- [ ] **Step 5: Commit any fixes**

If any fixes were needed from the above checks, commit them:

```bash
git add -u
git commit -m "fix: address lint and test issues from entity registry integration"
```
