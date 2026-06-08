"""Tests for the entity name matcher — matching cascade and confidence scoring."""

import pytest

from esbvaktin.entity_registry.matcher import (
    MATCH_THRESHOLDS,
    MatchResult,
    compute_disagreements,
    lemmatise_name,
    match_and_record_summary,
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
        assert isinstance(result, MatchResult)
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
    @pytest.fixture(autouse=True)
    def _skip_without_islenska(self):
        try:
            from islenska import Bin  # noqa: F401
        except ImportError:
            pytest.skip("islenska not installed")

    def test_lemmatise_known_name(self):
        lemma = lemmatise_name("Bjarna")
        assert lemma is not None


class TestSubsetMatch:
    def test_two_word_subset(self, registry):
        result = match_entity("Kristrún Frostadóttir forsætisráðherra", "individual", registry)
        assert result.entity_id == 3
        assert result.method == "fuzzy"
        assert result.confidence >= MATCH_THRESHOLDS["flag"]

    def test_single_word_is_low(self, registry):
        result = match_entity("Bjarni", "individual", registry)
        assert result.confidence < MATCH_THRESHOLDS["flag"]


class TestCorruptedNameMasking:
    """Pins why the corrupted `Daði Más Kristóferssonn` duplicate escaped the registry.

    Root cause of the spurious entity-details/dadi-mas-kristoferssonn.json on the site:
    the haiku entity-extractor transcribed "Daði Már Kristófersson" as
    "Daði Más Kristóferssonn" (two typos: Má*s* not Má*r*, and a doubled trailing *n*).
    The matcher behaved correctly — it must NOT fuzzy-merge a name that differs in two of
    three words to the canonical entity, or it would risk wrong merges. With two corrupted
    words the only overlap is the shared first name, which lands at the weak-fuzzy 0.30 tier
    (below the 0.5 flag threshold), so register_sightings minted a NEW entity instead of
    flagging it for review. A *single* typo would still subset-match above the flag line and
    be caught. The fix is upstream data correction, not a matcher change.
    """

    @pytest.fixture
    def dadi_registry(self) -> list[Entity]:
        return [
            Entity(
                id=42,
                slug="dadi-mar-kristofersson",
                canonical_name="Daði Már Kristófersson",
                entity_type="individual",
                stance="neutral",
                aliases=[],
            ),
        ]

    def test_double_typo_falls_below_flag_threshold(self, dadi_registry):
        # The corruption seen in the wild: matches only on the shared first name ->
        # weak fuzzy 0.30, below flag -> treated as a new (duplicate) entity.
        result = match_entity("Daði Más Kristóferssonn", "individual", dadi_registry)
        assert result.confidence < MATCH_THRESHOLDS["flag"]

    def test_clean_name_auto_links(self, dadi_registry):
        # The correct name exact-matches the canonical entity -> auto-link, no duplicate.
        result = match_entity("Daði Már Kristófersson", "individual", dadi_registry)
        assert result.entity_id == 42
        assert result.confidence >= MATCH_THRESHOLDS["auto_link"]


class TestNoMatch:
    def test_unknown_name(self, registry):
        result = match_entity("Guðmundur Sigurðsson", "individual", registry)
        assert result.entity_id is None
        assert result.confidence == 0.0

    def test_type_mismatch_lowers_confidence(self, registry):
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
        entity = Entity(id=1, slug="x", canonical_name="X", entity_type="individual")
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
            id=1,
            slug="x",
            canonical_name="X",
            entity_type="individual",
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


class TestLockedFields:
    def test_disagreement_on_locked_field_still_recorded(self):
        entity = Entity(
            id=1,
            slug="x",
            canonical_name="X",
            entity_type="individual",
            stance="pro_eu",
            locked_fields=["stance"],
        )
        disagreements = compute_disagreements(
            entity=entity,
            observed_stance="anti_eu",
            observed_role=None,
            observed_party=None,
            observed_type="individual",
        )
        assert disagreements is not None
        assert disagreements["stance"] is True

    def test_is_field_locked(self):
        from esbvaktin.entity_registry.matcher import is_field_locked

        entity = Entity(
            id=1,
            slug="x",
            canonical_name="X",
            entity_type="individual",
            locked_fields=["stance", "type"],
        )
        assert is_field_locked(entity, "stance") is True
        assert is_field_locked(entity, "party") is False


class TestMatchAndRecordSummary:
    def test_returns_summary(self):
        summary = match_and_record_summary(
            auto_linked=2, flagged=1, new_entities=0, disagreements=["stance"]
        )
        assert summary["auto_linked"] == 2
        assert summary["flagged"] == 1
        assert "stance" in summary["disagreements"]
