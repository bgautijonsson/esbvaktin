"""Entity name matcher — deterministic matching cascade with BÍN lemmatisation."""

from __future__ import annotations

from dataclasses import dataclass

from esbvaktin.entity_registry.models import Entity
from esbvaktin.utils.slugify import icelandic_slugify

MATCH_THRESHOLDS: dict[str, float] = {
    "auto_link": 0.9,
    "flag": 0.5,
}

_lemma_cache: dict[str, str | None] = {}

# Lazy-loaded BÍN instance
_bin_instance = None
_bin_available: bool | None = None


def _get_bin():
    """Get or create the BÍN instance, returning None if islenska is not installed."""
    global _bin_instance, _bin_available  # noqa: PLW0603
    if _bin_available is None:
        try:
            from islenska import Bin

            _bin_instance = Bin()
            _bin_available = True
        except ImportError:
            _bin_available = False
    return _bin_instance


@dataclass
class MatchResult:
    """Result of matching an observed name against the entity registry."""

    entity_id: int | None
    confidence: float
    method: str
    matched_entity: Entity | None


def lemmatise_name(word: str) -> str | None:
    """Look up the nominative (lemma) form of a word via BÍN.

    Tries lowercase first, then original casing for proper nouns.
    Returns the stem form if found, else None.
    """
    if word in _lemma_cache:
        return _lemma_cache[word]

    b = _get_bin()
    if b is None:
        _lemma_cache[word] = None
        return None

    # Try lowercase first
    _, meanings = b.lookup(word.lower())
    if not meanings:
        # Try original casing (proper nouns)
        _, meanings = b.lookup(word)
    if meanings:
        result = meanings[0].ord
        _lemma_cache[word] = result
        return result

    _lemma_cache[word] = None
    return None


def clear_lemma_cache() -> None:
    """Clear the module-level lemma cache."""
    _lemma_cache.clear()


def _normalise(name: str) -> str:
    """Lowercase and strip a name."""
    return name.lower().strip()


def _words(name: str) -> set[str]:
    """Split a name into a set of lowercase words."""
    return set(name.lower().split())


def _lemmatise_full_name(name: str) -> str:
    """Lemmatise each word in a name, keeping originals for words not in BÍN."""
    parts = name.split()
    result = []
    for part in parts:
        lemma = lemmatise_name(part)
        result.append(lemma if lemma is not None else part)
    return " ".join(result).lower()


def match_entity(
    observed_name: str,
    observed_type: str,
    registry: list[Entity],
) -> MatchResult:
    """Match an observed name against the entity registry using a 7-step cascade.

    Steps:
        1. Exact match on canonical_name -> 0.95, "exact"
        2. Exact match on any alias -> 0.95, "alias"
        3. Lemmatise observed + canonical, compare -> 0.90, "lemma"
        4. Lemmatise observed + aliases, compare -> 0.75, "lemma"
        5. Subset match (all words of shorter in longer), min 2 words, same type -> 0.60, "fuzzy"
        6. Weak subset (1 overlapping word) or type mismatch -> 0.30, "fuzzy"
        7. No match -> 0.0, entity_id=None
    """
    obs_norm = _normalise(observed_name)
    obs_words = _words(observed_name)

    # Step 1: Exact match on canonical_name
    for entity in registry:
        if _normalise(entity.canonical_name) == obs_norm:
            if entity.entity_type == observed_type:
                return MatchResult(
                    entity_id=entity.id,
                    confidence=0.95,
                    method="exact",
                    matched_entity=entity,
                )
            # Exact name match but type mismatch — step 6 territory
            return MatchResult(
                entity_id=entity.id,
                confidence=0.30,
                method="fuzzy",
                matched_entity=entity,
            )

    # Step 2: Exact match on any alias
    for entity in registry:
        for alias in entity.aliases:
            if _normalise(alias) == obs_norm:
                return MatchResult(
                    entity_id=entity.id,
                    confidence=0.95,
                    method="alias",
                    matched_entity=entity,
                )

    # Steps 3-4: Lemma matching (only if BÍN is available)
    b = _get_bin()
    if b is not None:
        obs_lemma = _lemmatise_full_name(observed_name)

        # Step 3: Lemmatise observed + canonical, compare
        for entity in registry:
            canon_lemma = _lemmatise_full_name(entity.canonical_name)
            if obs_lemma == canon_lemma:
                return MatchResult(
                    entity_id=entity.id,
                    confidence=0.90,
                    method="lemma",
                    matched_entity=entity,
                )

        # Step 4: Lemmatise observed + aliases, compare
        for entity in registry:
            for alias in entity.aliases:
                alias_lemma = _lemmatise_full_name(alias)
                if obs_lemma == alias_lemma:
                    return MatchResult(
                        entity_id=entity.id,
                        confidence=0.75,
                        method="lemma",
                        matched_entity=entity,
                    )

    # Step 5: Subset match — all words of shorter name in longer, min 2, same type
    best_subset: MatchResult | None = None
    for entity in registry:
        canon_words = _words(entity.canonical_name)
        shorter, longer = (
            (canon_words, obs_words)
            if len(canon_words) <= len(obs_words)
            else (obs_words, canon_words)
        )
        overlap = shorter & longer
        if overlap == shorter and len(shorter) >= 2 and entity.entity_type == observed_type:
            candidate = MatchResult(
                entity_id=entity.id,
                confidence=0.60,
                method="fuzzy",
                matched_entity=entity,
            )
            if best_subset is None or len(shorter) > len(
                _words(best_subset.matched_entity.canonical_name)
            ):
                best_subset = candidate

    if best_subset is not None:
        return best_subset

    # Step 6: Weak subset (1 overlapping word) or type mismatch — 0.30
    for entity in registry:
        canon_words = _words(entity.canonical_name)
        overlap = obs_words & canon_words
        if overlap and len(overlap) >= 1:
            return MatchResult(
                entity_id=entity.id,
                confidence=0.30,
                method="fuzzy",
                matched_entity=entity,
            )

    # Step 7: No match
    return MatchResult(entity_id=None, confidence=0.0, method="none", matched_entity=None)


def compute_disagreements(
    entity: Entity,
    observed_stance: str | None,
    observed_role: str | None,
    observed_party: str | None,
    observed_type: str | None,
) -> dict[str, bool] | None:
    """Compare observation against registry entity and return disagreements.

    Returns None if no disagreements are found.
    """
    disagreements: dict[str, bool] = {}

    # Stance: disagree if observed != registry AND observed != "neutral"
    if (
        observed_stance is not None
        and observed_stance != "neutral"
        and entity.stance is not None
        and observed_stance != entity.stance
    ):
        disagreements["stance"] = True

    # Role: disagree if observed_role not in any entity.roles[].role (lowercased)
    if observed_role is not None and entity.roles:
        registry_roles = {r.role.lower() for r in entity.roles}
        if observed_role.lower() not in registry_roles:
            disagreements["role"] = True

    # Party: disagree if icelandic_slugify(observed_party) != entity.party_slug
    if observed_party is not None and entity.party_slug is not None:
        if icelandic_slugify(observed_party) != entity.party_slug:
            disagreements["party"] = True

    # Type: disagree if observed_type != entity.entity_type
    if observed_type is not None and observed_type != entity.entity_type:
        disagreements["type"] = True

    return disagreements if disagreements else None


def match_and_record_summary(
    auto_linked: int,
    flagged: int,
    new_entities: int,
    disagreements: list[str],
) -> dict:
    """Return a summary dict of match results."""
    return {
        "auto_linked": auto_linked,
        "flagged": flagged,
        "new_entities": new_entities,
        "disagreements": disagreements,
    }
