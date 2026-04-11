"""DB operations for the canonical entity registry."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from .models import Entity, EntityObservation, VerificationStatus

# ── Stance computation from observations ─────────────────────────────

_STANCE_SCORES = {
    "pro_eu": 1.0,
    "anti_eu": -1.0,
    "mixed": 0.0,
    "neutral": 0.0,
}

MIN_STANCE_OBSERVATIONS = 3


@dataclass
class ComputedStance:
    """Observation-derived stance for an entity."""

    label: str  # pro_eu | anti_eu | mixed | neutral | insufficient_data
    score: float  # [-1.0, 1.0]
    confidence: float  # [0.0, 1.0], linear ramp reaching 1.0 at 5 observations
    n_observations: int  # count of non-NULL stance observations


def _stance_label_from_score(score: float, n_observations: int) -> str:
    """Derive stance label from continuous score, gated by observation count."""
    if n_observations < MIN_STANCE_OBSERVATIONS:
        return "insufficient_data"
    if score >= 0.5:
        return "pro_eu"
    elif score <= -0.5:
        return "anti_eu"
    elif abs(score) < 0.1:
        return "neutral"
    else:
        return "mixed"


def compute_stance_from_observations(entity_id: int, conn: psycopg.Connection) -> ComputedStance:
    """Compute stance from non-dismissed observations for an entity.

    Returns a ComputedStance with the observation-derived label, score,
    confidence, and count. Returns insufficient_data with score 0.0 when
    fewer than MIN_STANCE_OBSERVATIONS non-NULL stances exist.
    """
    rows = conn.execute(
        """
        SELECT observed_stance FROM entity_observations
        WHERE entity_id = %(eid)s AND NOT dismissed AND observed_stance IS NOT NULL
        """,
        {"eid": entity_id},
    ).fetchall()

    stances = [r[0] for r in rows]
    n = len(stances)
    if n == 0:
        return ComputedStance(
            label="insufficient_data", score=0.0, confidence=0.0, n_observations=0
        )

    numeric = [_STANCE_SCORES.get(s, 0.0) for s in stances]
    score = round(sum(numeric) / len(numeric), 2)
    label = _stance_label_from_score(score, n)
    confidence = round(min(n / 5.0, 1.0), 2)
    return ComputedStance(label=label, score=score, confidence=confidence, n_observations=n)


def insert_entity(entity: Entity, conn: psycopg.Connection) -> int:
    """Insert an entity and return its ID."""
    row = conn.execute(
        """
        INSERT INTO entities (
            slug, canonical_name, entity_type, subtype, stance, stance_score,
            stance_confidence, party_slug, althingi_id, aliases, roles, notes,
            verification_status, is_icelandic, locked_fields
        ) VALUES (
            %(slug)s, %(canonical_name)s, %(entity_type)s, %(subtype)s, %(stance)s,
            %(stance_score)s, %(stance_confidence)s, %(party_slug)s, %(althingi_id)s,
            %(aliases)s, %(roles)s, %(notes)s, %(verification_status)s, %(is_icelandic)s,
            %(locked_fields)s
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
            "locked_fields": entity.locked_fields,
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
               verification_status, is_icelandic, locked_fields
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
               verification_status, is_icelandic, locked_fields
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
               verification_status, is_icelandic, locked_fields
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
               claim_indices, match_confidence, match_method, disagreements, dismissed
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
        "locked_fields",
        "verified_at",
        "verified_by",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return

    # Enforce locked_fields: reject updates to locked fields unless locks themselves are changing
    if "locked_fields" not in filtered:
        row = conn.execute(
            "SELECT locked_fields FROM entities WHERE id = %(id)s", {"id": entity_id}
        ).fetchone()
        if row and row[0]:
            locked = set(row[0])
            violations = locked & filtered.keys()
            if violations:
                raise ValueError(f"Cannot update locked fields: {', '.join(sorted(violations))}")

    # Normalise empty-string / "none" sentinels to NULL for nullable columns
    nullable = {"subtype", "party_slug", "althingi_id", "notes", "verified_at", "verified_by"}
    for key in nullable & filtered.keys():
        if filtered[key] in ("", "none", "None"):
            filtered[key] = None

    if "roles" in filtered and not isinstance(filtered["roles"], str):
        filtered["roles"] = json.dumps(filtered["roles"])

    set_clause = ", ".join(f"{k} = %({k})s" for k in filtered)
    filtered["id"] = entity_id
    conn.execute(f"UPDATE entities SET {set_clause} WHERE id = %(id)s", filtered)
    conn.commit()


def merge_entities(keep_id: int, absorb_id: int, conn: psycopg.Connection) -> None:
    """Merge absorb_id into keep_id: move observations, absorb aliases/roles/notes, delete absorbed."""
    keep = conn.execute(
        "SELECT aliases, canonical_name, roles, notes, stance_score FROM entities WHERE id = %(id)s",
        {"id": keep_id},
    ).fetchone()
    absorb = conn.execute(
        "SELECT aliases, canonical_name, slug, roles, notes, stance_score FROM entities WHERE id = %(id)s",
        {"id": absorb_id},
    ).fetchone()
    if not keep or not absorb:
        return

    # Merge aliases
    merged_aliases = list(keep[0] or [])
    for name in [absorb[1]] + list(absorb[0] or []):
        if name not in merged_aliases:
            merged_aliases.append(name)

    # Merge roles (additive, skip duplicates by role+from_date)
    keep_roles = keep[2] or []
    if isinstance(keep_roles, str):
        keep_roles = json.loads(keep_roles)
    absorb_roles = absorb[3] or []
    if isinstance(absorb_roles, str):
        absorb_roles = json.loads(absorb_roles)
    existing_keys = {(r.get("role"), r.get("from_date")) for r in keep_roles}
    for role in absorb_roles:
        if (role.get("role"), role.get("from_date")) not in existing_keys:
            keep_roles.append(role)

    # Merge notes (append with origin label)
    keep_notes = keep[3] or ""
    absorb_notes = absorb[4] or ""
    if absorb_notes:
        merged_notes = (
            f"{keep_notes}\n---\n[Merged from {absorb[2]}] {absorb_notes}"
            if keep_notes
            else absorb_notes
        )
    else:
        merged_notes = keep_notes or None

    # Carry over stance_score if keep has None
    stance_score_update = {}
    if keep[4] is None and absorb[5] is not None:
        stance_score_update["stance_score"] = absorb[5]

    conn.execute(
        """UPDATE entities
        SET aliases = %(aliases)s, roles = %(roles)s, notes = %(notes)s
        WHERE id = %(id)s""",
        {
            "aliases": merged_aliases,
            "roles": json.dumps(keep_roles),
            "notes": merged_notes,
            "id": keep_id,
        },
    )
    if stance_score_update:
        conn.execute(
            "UPDATE entities SET stance_score = %(stance_score)s WHERE id = %(id)s",
            {"stance_score": stance_score_update["stance_score"], "id": keep_id},
        )
    conn.execute(
        "UPDATE entity_observations SET entity_id = %(keep)s WHERE entity_id = %(absorb)s",
        {"keep": keep_id, "absorb": absorb_id},
    )
    conn.execute("DELETE FROM entities WHERE id = %(id)s", {"id": absorb_id})
    conn.commit()


def get_dashboard_stats(conn: psycopg.Connection) -> dict:
    """Return aggregate stats for the entity review dashboard."""
    # Total entities
    total_entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]

    # Total non-dismissed observations
    total_observations = conn.execute(
        "SELECT COUNT(*) FROM entity_observations WHERE NOT dismissed"
    ).fetchone()[0]

    # By verification status
    status_rows = conn.execute(
        "SELECT verification_status, COUNT(*) FROM entities GROUP BY verification_status"
    ).fetchall()
    by_status = {"auto_generated": 0, "needs_review": 0, "confirmed": 0}
    for status, count in status_rows:
        by_status[status] = count

    # Stance conflicts: unconfirmed entities with >1 distinct non-neutral observed stance
    stance_conflicts = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT o.entity_id
            FROM entity_observations o
            JOIN entities e ON e.id = o.entity_id
            WHERE NOT o.dismissed
              AND o.observed_stance IS NOT NULL
              AND o.observed_stance != 'neutral'
              AND e.verification_status != 'confirmed'
            GROUP BY o.entity_id
            HAVING COUNT(DISTINCT o.observed_stance) > 1
        ) sub
        """
    ).fetchone()[0]

    # Type mismatches: unconfirmed entities where observed_type != entity_type
    type_mismatches = conn.execute(
        """
        SELECT COUNT(DISTINCT e.id) FROM entities e
        JOIN entity_observations o ON o.entity_id = e.id
        WHERE NOT o.dismissed
          AND o.observed_type IS NOT NULL
          AND o.observed_type != e.entity_type
          AND e.verification_status != 'confirmed'
        """
    ).fetchone()[0]

    # Placeholders: unconfirmed entities with zero non-dismissed observations
    placeholders = conn.execute(
        """
        SELECT COUNT(*) FROM entities e
        WHERE e.verification_status != 'confirmed'
          AND NOT EXISTS (
            SELECT 1 FROM entity_observations o
            WHERE o.entity_id = e.id AND NOT o.dismissed
        )
        """
    ).fetchone()[0]

    return {
        "total_entities": total_entities,
        "total_observations": total_observations,
        "by_status": by_status,
        "stance_conflicts": stance_conflicts,
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
    """Return entity dicts with observation counts and stance breakdown.

    Filters:
        entity_type — match e.entity_type
        status — match e.verification_status
        search — ILIKE on canonical_name and aliases
        issue — post-aggregate filter: stance_conflict, type_mismatch, placeholder, new_entity

    Sort: observations (desc), alpha (asc), recent (desc), stance_variance (desc)
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
            "(e.canonical_name ILIKE %(search)s OR EXISTS ("
            "  SELECT 1 FROM unnest(e.aliases) AS a WHERE a ILIKE %(search)s"
            "))"
        )
        params["search"] = f"%{search}%"

    if issue == "new_entity":
        conditions.append("e.verification_status = 'auto_generated'")

    where = " AND ".join(conditions)
    where_clause = f"WHERE {where}" if where else ""

    # Fetch all matching entities with their fields
    rows = conn.execute(
        f"""
        SELECT e.id, e.slug, e.canonical_name, e.entity_type, e.subtype,
               e.stance, e.stance_score, e.party_slug, e.verification_status,
               e.locked_fields
        FROM entities e
        {where_clause}
        """,
        params,
    ).fetchall()

    if not rows:
        return []

    entity_ids = [r[0] for r in rows]

    # Fetch non-dismissed observation data for these entities in bulk
    obs_rows = conn.execute(
        """
        SELECT entity_id, observed_stance, observed_type
        FROM entity_observations
        WHERE entity_id = ANY(%(ids)s) AND NOT dismissed
        """,
        {"ids": entity_ids},
    ).fetchall()

    # Build per-entity aggregates
    obs_counts: Counter = Counter()
    stance_breakdowns: dict[int, Counter] = {}
    type_mismatches: set[int] = set()

    entity_types_map = {r[0]: r[3] for r in rows}

    for eid, stance, obs_type in obs_rows:
        obs_counts[eid] += 1
        if stance:
            stance_breakdowns.setdefault(eid, Counter())[stance] += 1
        if obs_type and obs_type != entity_types_map.get(eid):
            type_mismatches.add(eid)

    # Build stance_conflict set: entities with >1 distinct non-neutral stance
    stance_conflict_ids: set[int] = set()
    for eid, counter in stance_breakdowns.items():
        non_neutral = {k for k in counter if k != "neutral"}
        if len(non_neutral) > 1:
            stance_conflict_ids.add(eid)

    # Compute observation-derived stance per entity (mirrors export_entities logic)
    computed_stances: dict[int, ComputedStance] = {}
    for eid in entity_ids:
        stances_list = []
        for s, count in stance_breakdowns.get(eid, {}).items():
            stances_list.extend([s] * count)
        n = len(stances_list)
        if n == 0:
            computed_stances[eid] = ComputedStance(
                label="insufficient_data", score=0.0, confidence=0.0, n_observations=0
            )
        else:
            numeric = [_STANCE_SCORES.get(s, 0.0) for s in stances_list]
            score = round(sum(numeric) / len(numeric), 2)
            computed_stances[eid] = ComputedStance(
                label=_stance_label_from_score(score, n),
                score=score,
                confidence=round(min(n / 5.0, 1.0), 2),
                n_observations=n,
            )

    # Fetch recent observations (last 3 per entity) for card display
    recent_obs_rows = conn.execute(
        """
        SELECT entity_id, observed_stance, article_slug, article_url, observed_name
        FROM (
            SELECT entity_id, observed_stance, article_slug, article_url, observed_name,
                   ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY created_at DESC) AS rn
            FROM entity_observations
            WHERE entity_id = ANY(%(ids)s) AND NOT dismissed
        ) sub
        WHERE rn <= 3
        ORDER BY entity_id, rn
        """,
        {"ids": entity_ids},
    ).fetchall()

    recent_obs: dict[int, list[dict]] = {}
    for eid, stance, slug, url, name in recent_obs_rows:
        recent_obs.setdefault(eid, []).append(
            {
                "observed_stance": stance,
                "article_slug": slug,
                "article_url": url,
                "observed_name": name,
            }
        )

    results = []
    for r in rows:
        eid = r[0]
        breakdown = dict(stance_breakdowns.get(eid, {}))
        count = obs_counts.get(eid, 0)

        # Post-aggregate issue filters
        if issue == "stance_conflict" and eid not in stance_conflict_ids:
            continue
        if issue == "type_mismatch" and eid not in type_mismatches:
            continue
        if issue == "placeholder" and count > 0:
            continue
        if issue == "needs_attention":
            is_confirmed = r[8] == "confirmed"
            has_issue = eid in stance_conflict_ids or eid in type_mismatches or count == 0
            if not has_issue or is_confirmed:
                continue

        cs = computed_stances.get(eid)
        results.append(
            {
                "id": eid,
                "slug": r[1],
                "canonical_name": r[2],
                "entity_type": r[3],
                "subtype": r[4],
                "stance": r[5],
                "stance_score": r[6],
                "party_slug": r[7],
                "verification_status": r[8],
                "locked_fields": list(r[9] or []),
                "observation_count": count,
                "stance_breakdown": breakdown,
                "has_type_mismatch": eid in type_mismatches,
                "has_stance_conflict": eid in stance_conflict_ids,
                "recent_observations": recent_obs.get(eid, []),
                "computed_stance": cs.label if cs else None,
                "computed_stance_score": cs.score if cs else None,
                "computed_stance_confidence": cs.confidence if cs else None,
                "stance_observation_count": cs.n_observations if cs else 0,
            }
        )

    # Sort
    if sort == "alpha":
        results.sort(key=lambda r: r["canonical_name"].lower())
    elif sort == "recent":
        results.sort(key=lambda r: r["id"], reverse=True)
    elif sort == "stance_variance":

        def _variance(r: dict) -> int:
            bd = r["stance_breakdown"]
            non_neutral = {k: v for k, v in bd.items() if k != "neutral"}
            return len(non_neutral)

        results.sort(key=_variance, reverse=True)
    else:  # observations (default)
        results.sort(key=lambda r: r["observation_count"], reverse=True)

    return results


def get_entity_detail(slug: str, conn: psycopg.Connection) -> dict | None:
    """Return full entity detail with observations and computed stance, or None."""
    entity = get_entity_by_slug(slug, conn)
    if entity is None:
        return None

    observations = get_observations_for_entity(entity.id, conn)
    cs = compute_stance_from_observations(entity.id, conn)
    result = entity.model_dump()
    result["observations"] = [obs.model_dump() for obs in observations]
    result["computed_stance"] = cs.label
    result["computed_stance_score"] = cs.score
    result["computed_stance_confidence"] = cs.confidence
    result["stance_observation_count"] = cs.n_observations
    return result


def confirm_entity(slug: str, conn: psycopg.Connection) -> Entity | None:
    """Set entity verification_status to confirmed. Returns updated entity or None.

    Auto-populates stance fields from observations unless individually locked.
    Only sets stance labels when the observation gate is met (>= 3 non-NULL stances).
    """
    entity = get_entity_by_slug(slug, conn)
    if entity is None:
        return None

    updates: dict = {
        "verification_status": "confirmed",
        "verified_at": datetime.now(UTC),
        "verified_by": "review_ui",
    }

    # Auto-populate stance from observations (respects locked_fields)
    locked = set(entity.locked_fields)
    cs = compute_stance_from_observations(entity.id, conn)
    if cs.n_observations > 0:
        if "stance_score" not in locked:
            updates["stance_score"] = cs.score
        if "stance_confidence" not in locked:
            updates["stance_confidence"] = cs.confidence
        # Only set categorical stance when observation gate is met
        if "stance" not in locked and cs.label != "insufficient_data":
            updates["stance"] = cs.label

    update_entity(entity.id, updates, conn)
    return get_entity_by_slug(slug, conn)


def delete_entity(slug: str, conn: psycopg.Connection) -> bool:
    """Unlink all observations and delete the entity. Returns True if found and deleted."""
    entity = get_entity_by_slug(slug, conn)
    if entity is None:
        return False

    conn.execute(
        "UPDATE entity_observations SET entity_id = NULL WHERE entity_id = %(id)s",
        {"id": entity.id},
    )
    conn.execute("DELETE FROM entities WHERE id = %(id)s", {"id": entity.id})
    conn.commit()
    return True


def dismiss_observation(obs_id: int, conn: psycopg.Connection) -> bool:
    """Mark an observation as dismissed. Returns True if the observation existed."""
    result = conn.execute(
        "UPDATE entity_observations SET dismissed = TRUE WHERE id = %(id)s RETURNING id",
        {"id": obs_id},
    ).fetchone()
    conn.commit()
    return result is not None


def relink_observation(obs_id: int, new_entity_id: int, conn: psycopg.Connection) -> bool:
    """Move an observation to a different entity. Returns True if the observation existed."""
    result = conn.execute(
        "UPDATE entity_observations SET entity_id = %(new_id)s WHERE id = %(obs_id)s RETURNING id",
        {"new_id": new_entity_id, "obs_id": obs_id},
    ).fetchone()
    conn.commit()
    return result is not None


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
        locked_fields=list(row[15] or []),
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
        dismissed=row[14],
    )
