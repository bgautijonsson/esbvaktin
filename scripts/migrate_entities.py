"""One-time migration: bootstrap the entity registry from existing analysis data.

Loads all merged entities from export_entities.py, inserts them into the
entities DB table, then backfills observations from per-article _entities.json
files. Generates a migration report flagging potential issues.

Usage:
    uv run python scripts/migrate_entities.py --status      # Show registry status
    uv run python scripts/migrate_entities.py               # Run migration
    uv run python scripts/migrate_entities.py --report      # Show migration report
    uv run python scripts/migrate_entities.py --dry-run     # Preview without DB writes
    uv run python scripts/migrate_entities.py --force       # Re-run (clears existing data first)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

from esbvaktin.entity_registry.models import (
    Entity,
    EntityObservation,
    MatchMethod,
    RoleEntry,
    VerificationStatus,
)
from esbvaktin.entity_registry.operations import (
    get_all_entities,
    insert_entity,
    insert_observation,
)
from esbvaktin.ground_truth.operations import get_connection
from esbvaktin.utils.slugify import icelandic_slugify

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"
EXPORT_DIR = PROJECT_ROOT / "data" / "export"
REPORT_PATH = EXPORT_DIR / "entity_migration_report.json"


# ── Import from export_entities.py ──────────────────────────────────────


def _load_export_module():
    """Load export_entities.py as a module via importlib."""
    script_path = PROJECT_ROOT / "scripts" / "export_entities.py"
    spec = importlib.util.spec_from_file_location("export_entities", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_export_mod = None


def _get_export_mod():
    global _export_mod
    if _export_mod is None:
        _export_mod = _load_export_module()
    return _export_mod


# ── Entity building ─────────────────────────────────────────────────────


def _build_entity(slug: str, data: dict, mod) -> Entity:
    """Build an Entity model from a merged entity dict."""
    canonical_name = mod._CANONICAL_NAMES.get(slug, data["name"])
    entity_type = data["type"]
    subtype = data.get("subtype")
    stance = data.get("stance")
    stance_score = data.get("stance_score")
    party_slug = data.get("party_slug")

    # Build aliases: all _NAME_ALIASES entries that map to this slug,
    # excluding variants that match the canonical name (case-insensitive)
    aliases = []
    canonical_lower = canonical_name.lower()
    for variant, target_slug in mod._NAME_ALIASES.items():
        if target_slug == slug and variant != canonical_lower:
            aliases.append(variant)

    # Build roles from _ROLE_OVERRIDES or from data
    roles = []
    if slug in mod._ROLE_OVERRIDES:
        roles.append(RoleEntry(role=mod._ROLE_OVERRIDES[slug]))
    elif data.get("role"):
        roles.append(RoleEntry(role=data["role"]))

    # Icelandic flag — check entity-specific flag or default True
    is_icelandic = data.get("icelandic", True)

    return Entity(
        slug=slug,
        canonical_name=canonical_name,
        entity_type=entity_type,
        subtype=subtype,
        stance=stance,
        stance_score=stance_score,
        party_slug=party_slug,
        aliases=aliases,
        roles=roles,
        verification_status=VerificationStatus.AUTO_GENERATED,
        is_icelandic=is_icelandic,
    )


# ── Observation backfilling ──────────────────────────────────────────────


def _backfill_observations(
    slug_to_id: dict[str, int],
    mod,
    dry_run: bool = False,
    conn=None,
) -> tuple[list[EntityObservation], list[dict]]:
    """Backfill observations from all _entities.json files.

    Returns (observations, orphans) where orphans are observations
    that could not be matched to a registered entity.
    """
    observations: list[EntityObservation] = []
    orphans: list[dict] = []

    for analysis_dir in sorted(ANALYSES_DIR.iterdir()):
        if not analysis_dir.is_dir():
            continue

        entities_path = analysis_dir / "_entities.json"
        if not entities_path.exists():
            continue

        # Get article slug from _report_final.json if available
        report_path = analysis_dir / "_report_final.json"
        article_url = None
        article_slug = analysis_dir.name

        if report_path.exists():
            try:
                with open(report_path, encoding="utf-8") as f:
                    report = json.load(f)
                title = report.get("article_title", analysis_dir.name)
                article_slug = icelandic_slugify(title)
                article_url = report.get("article_url") or report.get("url")
            except (json.JSONDecodeError, KeyError):
                pass

        # Load raw entities
        try:
            with open(entities_path, encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, KeyError):
            continue

        # Process author + speakers
        speakers = []
        author = raw.get("article_author")
        if author and author.get("name"):
            speakers.append(author)

        for speaker in raw.get("speakers", []):
            if speaker.get("name"):
                speakers.append(speaker)

        for speaker in speakers:
            name = speaker["name"]

            # Skip known title-based entries
            if name.lower() in mod._SKIP_NAMES:
                continue

            # Resolve slug via aliases then slugify
            resolved_slug = mod._NAME_ALIASES.get(name.lower(), icelandic_slugify(name))
            entity_id = slug_to_id.get(resolved_slug)

            # Extract attribution types and claim indices
            attributions = speaker.get("attributions", [])
            attribution_types = []
            claim_indices = []
            if attributions:
                for a in attributions:
                    attr_type = a.get("attribution", "asserted")
                    if attr_type not in attribution_types:
                        attribution_types.append(attr_type)
                    claim_indices.append(a["claim_index"])
            else:
                # Legacy format
                claim_indices = speaker.get("claim_indices", [])
                attribution_types = ["asserted"]

            # Determine match method and confidence
            if entity_id is not None:
                if name.lower() in mod._NAME_ALIASES:
                    match_method = MatchMethod.ALIAS
                    match_confidence = 0.95
                else:
                    match_method = MatchMethod.EXACT
                    match_confidence = 0.95
            else:
                match_method = None
                match_confidence = None

            # Check for disagreements between observed and canonical data
            disagreements = None
            if entity_id is not None:
                d = {}
                # Look up canonical entity data for comparison
                canonical_slug = resolved_slug
                if canonical_slug in slug_to_id:
                    # We could compare stance, type, etc. but for migration
                    # we just flag if the observed type differs
                    pass
                if d:
                    disagreements = d

            obs = EntityObservation(
                entity_id=entity_id,
                article_slug=article_slug,
                article_url=article_url,
                observed_name=name,
                observed_stance=speaker.get("stance"),
                observed_role=speaker.get("role"),
                observed_party=speaker.get("party"),
                observed_type=speaker.get("type"),
                attribution_types=attribution_types,
                claim_indices=claim_indices,
                match_confidence=match_confidence,
                match_method=match_method,
                disagreements=disagreements,
            )

            if entity_id is None:
                orphans.append(
                    {
                        "observed_name": name,
                        "resolved_slug": resolved_slug,
                        "article_slug": article_slug,
                        "article_url": article_url,
                    }
                )

            if not dry_run and conn:
                insert_observation(obs, conn)

            observations.append(obs)

    return observations, orphans


# ── Report generation ────────────────────────────────────────────────────


def _generate_report(
    entities: list[Entity],
    observations: list[EntityObservation],
    orphans: list[dict],
) -> dict:
    """Generate a migration quality report."""
    # Potential duplicates: entities whose lowercased canonical_name or aliases overlap
    name_to_slugs: dict[str, list[str]] = defaultdict(list)
    for entity in entities:
        name_to_slugs[entity.canonical_name.lower()].append(entity.slug)
        for alias in entity.aliases:
            name_to_slugs[alias.lower()].append(entity.slug)

    potential_duplicates = []
    seen_pairs: set[tuple[str, str]] = set()
    for name, slugs in name_to_slugs.items():
        unique_slugs = list(set(slugs))
        if len(unique_slugs) > 1:
            for i, s1 in enumerate(unique_slugs):
                for s2 in unique_slugs[i + 1 :]:
                    pair = tuple(sorted([s1, s2]))
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        potential_duplicates.append(
                            {
                                "slugs": list(pair),
                                "shared_name": name,
                            }
                        )

    # Stance conflicts: entities where observations have different non-neutral stances
    entity_stances: dict[int, set[str]] = defaultdict(set)
    for obs in observations:
        if obs.entity_id and obs.observed_stance and obs.observed_stance != "neutral":
            entity_stances[obs.entity_id].add(obs.observed_stance)

    stance_conflicts = []
    id_to_entity = {e.id: e for e in entities if e.id is not None}
    for entity_id, stances in entity_stances.items():
        if len(stances) > 1:
            entity = id_to_entity.get(entity_id)
            stance_conflicts.append(
                {
                    "entity_slug": entity.slug if entity else f"id:{entity_id}",
                    "entity_name": entity.canonical_name if entity else "unknown",
                    "observed_stances": sorted(stances),
                }
            )

    # Type mismatches: observations where observed_type differs from entity's type
    type_mismatches = []
    entity_id_to_slug = {e.id: e for e in entities if e.id is not None}
    for obs in observations:
        if obs.entity_id and obs.observed_type:
            entity = entity_id_to_slug.get(obs.entity_id)
            if entity and obs.observed_type != entity.entity_type:
                type_mismatches.append(
                    {
                        "entity_slug": entity.slug,
                        "entity_type": entity.entity_type,
                        "observed_type": obs.observed_type,
                        "article_slug": obs.article_slug,
                        "observed_name": obs.observed_name,
                    }
                )

    # Placeholder entities: entities with zero observations
    entity_ids_with_obs = {obs.entity_id for obs in observations if obs.entity_id}
    placeholder_entities = [
        {"slug": e.slug, "name": e.canonical_name, "type": e.entity_type}
        for e in entities
        if e.id is not None and e.id not in entity_ids_with_obs
    ]

    # Deduplicate orphans by slug
    unique_orphan_slugs = set()
    unique_orphans = []
    for o in orphans:
        if o["resolved_slug"] not in unique_orphan_slugs:
            unique_orphan_slugs.add(o["resolved_slug"])
            unique_orphans.append(o)

    return {
        "summary": {
            "total_entities": len(entities),
            "total_observations": len(observations),
            "orphan_observations": len(orphans),
            "unique_orphan_slugs": len(unique_orphan_slugs),
            "potential_duplicate_pairs": len(potential_duplicates),
            "stance_conflicts": len(stance_conflicts),
            "type_mismatches": len(type_mismatches),
            "placeholder_entities": len(placeholder_entities),
        },
        "potential_duplicates": potential_duplicates,
        "stance_conflicts": stance_conflicts,
        "type_mismatches": type_mismatches[:50],  # Cap to avoid huge reports
        "placeholder_entities": placeholder_entities,
        "orphan_observations": unique_orphans[:50],  # Cap
    }


# ── CLI commands ─────────────────────────────────────────────────────────


def cmd_status(conn) -> None:
    """Show current registry status."""
    entities = get_all_entities(conn)
    if not entities:
        print("Entity registry is empty — migration has not been run.")
        return

    by_type: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    for e in entities:
        by_type[e.entity_type] += 1
        by_status[e.verification_status.value] += 1

    obs_count = conn.execute("SELECT COUNT(*) FROM entity_observations").fetchone()[0]
    unlinked = conn.execute(
        "SELECT COUNT(*) FROM entity_observations WHERE entity_id IS NULL"
    ).fetchone()[0]

    print(f"Entity registry: {len(entities)} entities, {obs_count} observations")
    print(f"  By type: {dict(by_type)}")
    print(f"  By status: {dict(by_status)}")
    if unlinked:
        print(f"  Unlinked observations: {unlinked}")


def cmd_report() -> None:
    """Show the migration report."""
    if not REPORT_PATH.exists():
        print(f"No migration report found at {REPORT_PATH}")
        print("Run the migration first: uv run python scripts/migrate_entities.py")
        return

    with open(REPORT_PATH, encoding="utf-8") as f:
        report = json.load(f)

    summary = report["summary"]
    print("Migration Report")
    print("=" * 50)
    print(f"  Total entities:       {summary['total_entities']}")
    print(f"  Total observations:   {summary['total_observations']}")
    print(f"  Orphan observations:  {summary['orphan_observations']}")
    print(f"  Unique orphan slugs:  {summary['unique_orphan_slugs']}")
    print(f"  Duplicate pairs:      {summary['potential_duplicate_pairs']}")
    print(f"  Stance conflicts:     {summary['stance_conflicts']}")
    print(f"  Type mismatches:      {summary['type_mismatches']}")
    print(f"  Placeholder entities: {summary['placeholder_entities']}")

    if report["potential_duplicates"]:
        print(f"\nPotential Duplicates ({len(report['potential_duplicates'])}):")
        for dup in report["potential_duplicates"][:20]:
            print(f"  {dup['slugs']} — shared: {dup['shared_name']!r}")

    if report["stance_conflicts"]:
        print(f"\nStance Conflicts ({len(report['stance_conflicts'])}):")
        for sc in report["stance_conflicts"][:20]:
            print(f"  {sc['entity_name']} — stances: {sc['observed_stances']}")

    if report["placeholder_entities"]:
        print(f"\nPlaceholder Entities ({len(report['placeholder_entities'])}):")
        for pe in report["placeholder_entities"][:20]:
            print(f"  {pe['slug']} ({pe['type']}): {pe['name']}")


def cmd_migrate(dry_run: bool = False, force: bool = False) -> None:
    """Run the entity migration."""
    mod = _get_export_mod()
    conn = get_connection()

    # Check if entities already exist
    existing = get_all_entities(conn)
    if existing and not force:
        print(f"Entity registry already has {len(existing)} entities.")
        print("Use --force to clear and re-run the migration.")
        conn.close()
        return

    if existing and force:
        print(f"Clearing {len(existing)} existing entities (--force)...")
        if not dry_run:
            conn.execute("DELETE FROM entity_observations")
            conn.execute("DELETE FROM entities")
            conn.commit()
            print("  Cleared.")

    # Step 1: Load and merge all entities using export_entities logic
    print("\nStep 1: Loading and merging entities from analyses...")
    entities_dict = mod.load_all_entities()
    mod._compute_scores(entities_dict)
    althingi_count = mod._enrich_althingi_stats(entities_dict)
    politician_count = mod._classify_subtypes(entities_dict)
    media_count = mod._classify_media_outlets(entities_dict)
    roster = mod._load_mp_roster()
    party_enriched = mod._enrich_party_affiliations(entities_dict, roster)
    mod._ensure_party_entities(entities_dict)

    # Apply canonical name overrides (same as export_entities)
    for slug, canonical in mod._CANONICAL_NAMES.items():
        if slug in entities_dict:
            entities_dict[slug]["name"] = canonical

    # Flag Icelandic entities (same as export_entities)
    for slug, entity in entities_dict.items():
        if entity["type"] == "party":
            entity["icelandic"] = slug in mod._ICELANDIC_PARTIES
        elif entity.get("subtype") == "media":
            entity["icelandic"] = slug in mod._ICELANDIC_OUTLETS

    print(f"  Found {len(entities_dict)} unique entities")
    if althingi_count:
        print(f"  Althingi stats: {althingi_count} entities enriched")
    if politician_count:
        print(f"  Politicians: {politician_count} classified")
    if media_count:
        print(f"  Media outlets: {media_count} classified")
    if party_enriched:
        print(f"  Party affiliations: {party_enriched} enriched")

    # Step 2: Insert entities into DB
    print("\nStep 2: Inserting entities into registry...")
    slug_to_id: dict[str, int] = {}
    entity_models: list[Entity] = []

    for slug, data in sorted(entities_dict.items()):
        entity = _build_entity(slug, data, mod)
        entity_models.append(entity)

        if not dry_run:
            entity_id = insert_entity(entity, conn)
            entity.id = entity_id
            slug_to_id[slug] = entity_id
        else:
            # Assign fake IDs for dry-run reporting
            fake_id = len(slug_to_id) + 1
            entity.id = fake_id
            slug_to_id[slug] = fake_id

    print(f"  {'Would insert' if dry_run else 'Inserted'} {len(entity_models)} entities")

    # Step 3: Backfill observations
    print("\nStep 3: Backfilling observations from analysis directories...")
    observations, orphans = _backfill_observations(slug_to_id, mod, dry_run=dry_run, conn=conn)
    matched = sum(1 for o in observations if o.entity_id is not None)
    print(f"  {'Would create' if dry_run else 'Created'} {len(observations)} observations")
    print(f"  Matched: {matched}, Orphaned: {len(orphans)}")

    # Step 4: Generate migration report
    print("\nStep 4: Generating migration report...")
    report = _generate_report(entity_models, observations, orphans)

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  Report saved to {REPORT_PATH}")

    # Print summary
    s = report["summary"]
    print(f"\n{'DRY RUN ' if dry_run else ''}Migration Complete")
    print("=" * 50)
    print(f"  Entities:             {s['total_entities']}")
    print(f"  Observations:         {s['total_observations']}")
    print(f"  Orphan observations:  {s['orphan_observations']}")
    print(f"  Potential duplicates: {s['potential_duplicate_pairs']}")
    print(f"  Stance conflicts:     {s['stance_conflicts']}")
    print(f"  Type mismatches:      {s['type_mismatches']}")
    print(f"  Placeholder entities: {s['placeholder_entities']}")

    conn.close()


def main() -> None:
    if "--status" in sys.argv:
        conn = get_connection()
        cmd_status(conn)
        conn.close()
        return

    if "--report" in sys.argv:
        cmd_report()
        return

    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    cmd_migrate(dry_run=dry_run, force=force)


if __name__ == "__main__":
    main()
