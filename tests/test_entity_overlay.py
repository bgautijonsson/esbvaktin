"""Tests for fresh-07 — apply_registry_overlay (entity-registry Phase 3 overlay).

scripts/export_entities.py is a standalone script, loaded via importlib. The overlay
is a pure function (registry + observations injected), so these tests touch no DB.
Spec: docs/specs/2026-06-02-fresh-07-entity-registry-export-overlay-design.md
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from esbvaktin.entity_registry.models import (
    Entity,
    EntityObservation,
    VerificationStatus,
)

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "export_entities.py"


def _load():
    spec = importlib.util.spec_from_file_location("_export_entities_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # so `from __future__ import annotations` resolves
    spec.loader.exec_module(mod)
    return mod


def _entity(
    slug,
    *,
    eid=1,
    name=None,
    type="individual",
    subtype=None,
    stance=None,
    stance_score=None,
    party_slug=None,
    status=VerificationStatus.AUTO_GENERATED,
    locked=None,
):
    return Entity(
        id=eid,
        slug=slug,
        canonical_name=name or slug.replace("-", " ").title(),
        entity_type=type,
        subtype=subtype,
        stance=stance,
        stance_score=stance_score,
        party_slug=party_slug,
        verification_status=status,
        locked_fields=locked or [],
    )


def _export(slug, **kw):
    base = {
        "slug": slug,
        "name": slug,
        "type": "individual",
        "subtype": None,
        "stance": "insufficient_data",
        "stance_score": 0.0,
        "party": None,
        "role": None,
        "description": "",
        "articles": [],
        "claims": [],
        "mention_count": 0,
        "claim_count": 0,
        "credibility": None,
    }
    base.update(kw)
    return base


def _obs(article_slug, *, eid=1, dismissed=False, claim_indices=None):
    return EntityObservation(
        entity_id=eid,
        article_slug=article_slug,
        observed_name="x",
        dismissed=dismissed,
        claim_indices=claim_indices or [],
    )


# ── Rule 1: locked fields override unconditionally ─────────────────────


def test_locked_stance_overrides_label_and_score():
    mod = _load()
    exp = {"erna": _export("erna", stance="neutral", stance_score=0.1)}
    reg = [_entity("erna", stance="anti_eu", stance_score=-0.8, locked=["stance"])]

    out = mod.apply_registry_overlay(exp, reg, {})

    assert out["erna"]["stance"] == "anti_eu"
    assert out["erna"]["stance_score"] == -0.8


def test_unlocked_stance_is_left_untouched():
    """The 823 insufficient_data<->neutral label-diffs must NOT be replaced."""
    mod = _load()
    exp = {"x": _export("x", stance="insufficient_data")}
    reg = [_entity("x", stance="neutral", locked=[])]

    out = mod.apply_registry_overlay(exp, reg, {})

    assert out["x"]["stance"] == "insufficient_data"


def test_locked_field_overrides_only_that_field():
    mod = _load()
    exp = {"y": _export("y", type="party", stance="insufficient_data")}
    reg = [_entity("y", type="institution", stance="neutral", locked=["entity_type"])]

    out = mod.apply_registry_overlay(exp, reg, {})

    assert out["y"]["type"] == "institution"  # locked field overridden
    assert out["y"]["stance"] == "insufficient_data"  # non-locked field untouched


# ── Rule 2: confirmed honours registry type/subtype (non-None only) ────


def test_confirmed_type_override_and_unconfirmed_left_alone():
    mod = _load()
    exp = {
        "z": _export("z", type="institution"),
        "w": _export("w", type="institution"),
    }
    reg = [
        _entity("z", type="individual", status=VerificationStatus.CONFIRMED),
        _entity("w", type="individual", status=VerificationStatus.NEEDS_REVIEW),
    ]

    out = mod.apply_registry_overlay(exp, reg, {})

    assert out["z"]["type"] == "individual"  # confirmed -> honoured
    assert out["w"]["type"] == "institution"  # unconfirmed -> auto-guess ignored


def test_confirmed_none_subtype_does_not_wipe_computed_subtype():
    mod = _load()
    exp = {"m": _export("m", subtype="media")}
    reg = [_entity("m", subtype=None, status=VerificationStatus.CONFIRMED)]

    out = mod.apply_registry_overlay(exp, reg, {})

    assert out["m"]["subtype"] == "media"  # registry None must not clobber


# ── Rule 3: registry-only + confirmed + observed -> add ────────────────


def test_registry_only_confirmed_observed_is_added():
    mod = _load()
    exp: dict[str, dict] = {}
    reg = [
        _entity(
            "eva-bjork",
            eid=10,
            name="Eva Björk",
            type="individual",
            stance="pro_eu",
            stance_score=0.6,
            status=VerificationStatus.CONFIRMED,
        )
    ]
    obs_by_entity = {10: [_obs("art-1", eid=10, claim_indices=[0, 1])]}

    out = mod.apply_registry_overlay(exp, reg, obs_by_entity)

    assert "eva-bjork" in out
    added = out["eva-bjork"]
    assert added["name"] == "Eva Björk"
    assert added["type"] == "individual"
    assert added["stance"] == "pro_eu"
    assert added["articles"] == ["art-1"]
    assert added["mention_count"] == 1


def test_registry_only_needs_review_not_added():
    """vinstri-graen is a needs_review placeholder — adding it would double-publish VG."""
    mod = _load()
    reg = [_entity("vinstri-graen", eid=11, type="party", status=VerificationStatus.NEEDS_REVIEW)]
    obs_by_entity = {11: [_obs("art-2", eid=11)]}

    out = mod.apply_registry_overlay({}, reg, obs_by_entity)

    assert "vinstri-graen" not in out


def test_registry_only_confirmed_without_observations_not_added():
    mod = _load()
    reg = [_entity("ghost", eid=12, status=VerificationStatus.CONFIRMED)]
    # only a dismissed observation -> nothing to display
    obs_by_entity = {12: [_obs("art-3", eid=12, dismissed=True)]}

    out = mod.apply_registry_overlay({}, reg, obs_by_entity)

    assert "ghost" not in out


def test_matched_entity_not_duplicated_and_keeps_keys():
    mod = _load()
    exp = {"a": _export("a")}
    reg = [_entity("a", stance="neutral", locked=["stance"])]

    out = mod.apply_registry_overlay(exp, reg, {})

    assert list(out.keys()) == ["a"]  # no duplication
    for key in ("slug", "name", "type", "stance", "stance_score", "articles", "mention_count"):
        assert key in out["a"]
