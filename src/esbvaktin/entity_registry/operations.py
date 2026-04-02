"""DB operations for the canonical entity registry."""

from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg

from .models import Entity, EntityObservation, VerificationStatus


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


def get_entities_by_status(status: VerificationStatus, conn: psycopg.Connection) -> list[Entity]:
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


def update_entity(entity_id: int, updates: dict, conn: psycopg.Connection) -> None:
    """Update specific fields on an entity."""
    allowed = {
        "stance",
        "stance_score",
        "stance_confidence",
        "canonical_name",
        "entity_type",
        "subtype",
        "party_slug",
        "althingi_id",
        "aliases",
        "roles",
        "notes",
        "verification_status",
        "is_icelandic",
        "verified_at",
        "verified_by",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return

    if "roles" in filtered and not isinstance(filtered["roles"], str):
        filtered["roles"] = json.dumps(filtered["roles"])

    set_clause = ", ".join(f"{k} = %({k})s" for k in filtered)
    filtered["id"] = entity_id
    conn.execute(f"UPDATE entities SET {set_clause} WHERE id = %(id)s", filtered)
    conn.commit()


def merge_entities(keep_id: int, absorb_id: int, conn: psycopg.Connection) -> None:
    """Merge absorb_id into keep_id: move observations, absorb aliases, delete absorbed entity."""
    keep = conn.execute(
        "SELECT aliases, canonical_name FROM entities WHERE id = %(id)s", {"id": keep_id}
    ).fetchone()
    absorb = conn.execute(
        "SELECT aliases, canonical_name, slug FROM entities WHERE id = %(id)s", {"id": absorb_id}
    ).fetchone()
    if not keep or not absorb:
        return

    merged_aliases = list(keep[0] or [])
    for name in [absorb[1]] + list(absorb[0] or []):
        if name not in merged_aliases:
            merged_aliases.append(name)

    conn.execute(
        "UPDATE entities SET aliases = %(aliases)s WHERE id = %(id)s",
        {"aliases": merged_aliases, "id": keep_id},
    )
    conn.execute(
        "UPDATE entity_observations SET entity_id = %(keep)s WHERE entity_id = %(absorb)s",
        {"keep": keep_id, "absorb": absorb_id},
    )
    conn.execute("DELETE FROM entities WHERE id = %(id)s", {"id": absorb_id})
    conn.commit()


def _row_to_entity(row: tuple) -> Entity:
    """Convert a DB row tuple to an Entity model."""
    from .models import RoleEntry

    roles_raw = row[11]
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
