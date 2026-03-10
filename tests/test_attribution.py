"""Tests for the attribution-type system (Speaker, ClaimAttribution, export logic)."""

import json
import pytest
from pydantic import ValidationError

from esbvaktin.pipeline.models import (
    ArticleEntities,
    Attribution,
    ClaimAttribution,
    EntityType,
    Speaker,
    Stance,
)


# ── Model tests ───────────────────────────────────────────────────────


class TestAttribution:
    def test_all_values(self):
        assert set(Attribution) == {"asserted", "quoted", "paraphrased", "mentioned"}

    def test_from_string(self):
        assert Attribution("quoted") == Attribution.QUOTED


class TestClaimAttribution:
    def test_valid(self):
        ca = ClaimAttribution(claim_index=3, attribution=Attribution.QUOTED)
        assert ca.claim_index == 3
        assert ca.attribution == Attribution.QUOTED

    def test_default_attribution(self):
        ca = ClaimAttribution(claim_index=0)
        assert ca.attribution == Attribution.ASSERTED

    def test_from_string(self):
        ca = ClaimAttribution(claim_index=1, attribution="paraphrased")
        assert ca.attribution == Attribution.PARAPHRASED

    def test_invalid_attribution(self):
        with pytest.raises(ValidationError):
            ClaimAttribution(claim_index=0, attribution="invented")


class TestSpeakerAttributions:
    def test_new_format(self):
        s = Speaker(
            name="Test",
            type=EntityType.INDIVIDUAL,
            attributions=[
                ClaimAttribution(claim_index=0, attribution=Attribution.QUOTED),
                ClaimAttribution(claim_index=2, attribution=Attribution.PARAPHRASED),
            ],
        )
        resolved = s.resolved_attributions()
        assert len(resolved) == 2
        assert resolved[0].attribution == Attribution.QUOTED
        assert resolved[1].claim_index == 2

    def test_legacy_fallback(self):
        """Legacy claim_indices should resolve to 'asserted' attributions."""
        s = Speaker(
            name="Test",
            type=EntityType.PARTY,
            claim_indices=[0, 1, 5],
        )
        resolved = s.resolved_attributions()
        assert len(resolved) == 3
        assert all(a.attribution == Attribution.ASSERTED for a in resolved)
        assert [a.claim_index for a in resolved] == [0, 1, 5]

    def test_new_format_takes_precedence(self):
        """When both fields are present, attributions wins."""
        s = Speaker(
            name="Test",
            type=EntityType.INDIVIDUAL,
            claim_indices=[0, 1],
            attributions=[
                ClaimAttribution(claim_index=0, attribution=Attribution.QUOTED),
            ],
        )
        resolved = s.resolved_attributions()
        assert len(resolved) == 1
        assert resolved[0].attribution == Attribution.QUOTED

    def test_claim_index_set(self):
        s = Speaker(
            name="Test",
            type=EntityType.INSTITUTION,
            attributions=[
                ClaimAttribution(claim_index=1, attribution=Attribution.MENTIONED),
                ClaimAttribution(claim_index=3, attribution=Attribution.QUOTED),
            ],
        )
        assert s.claim_index_set() == {1, 3}

    def test_claim_index_set_legacy(self):
        s = Speaker(
            name="Test",
            type=EntityType.UNION,
            claim_indices=[2, 4],
        )
        assert s.claim_index_set() == {2, 4}

    def test_empty_speaker(self):
        s = Speaker(name="Test", type=EntityType.INDIVIDUAL)
        assert s.resolved_attributions() == []
        assert s.claim_index_set() == set()


class TestArticleEntitiesValidation:
    def test_new_format_json_roundtrip(self):
        """Validate that the new format survives JSON serialisation."""
        entities = ArticleEntities(
            article_author=Speaker(
                name="Höfundur",
                type=EntityType.INDIVIDUAL,
                role="pistlahöfundur",
                stance=Stance.ANTI_EU,
                attributions=[
                    ClaimAttribution(claim_index=0, attribution=Attribution.ASSERTED),
                    ClaimAttribution(claim_index=3, attribution=Attribution.ASSERTED),
                ],
            ),
            speakers=[
                Speaker(
                    name="Viðreisn",
                    type=EntityType.PARTY,
                    stance=Stance.PRO_EU,
                    attributions=[
                        ClaimAttribution(claim_index=1, attribution=Attribution.QUOTED),
                        ClaimAttribution(claim_index=2, attribution=Attribution.PARAPHRASED),
                    ],
                ),
                Speaker(
                    name="Evrópusambandið",
                    type=EntityType.INSTITUTION,
                    stance=Stance.NEUTRAL,
                    attributions=[
                        ClaimAttribution(claim_index=4, attribution=Attribution.MENTIONED),
                    ],
                ),
            ],
        )
        raw = json.loads(entities.model_dump_json())
        parsed = ArticleEntities.model_validate(raw)
        assert len(parsed.speakers) == 2
        assert parsed.speakers[0].attributions[0].attribution == Attribution.QUOTED
        assert parsed.article_author.resolved_attributions()[0].attribution == Attribution.ASSERTED

    def test_legacy_format_still_parses(self):
        """Existing _entities.json files with bare claim_indices must still parse."""
        raw = {
            "article_author": {
                "name": "Old Author",
                "type": "individual",
                "stance": "neutral",
                "claim_indices": [0, 1, 2],
            },
            "speakers": [
                {
                    "name": "Old Party",
                    "type": "party",
                    "stance": "anti_eu",
                    "claim_indices": [3, 4],
                },
            ],
        }
        entities = ArticleEntities.model_validate(raw)
        author_attr = entities.article_author.resolved_attributions()
        assert len(author_attr) == 3
        assert all(a.attribution == Attribution.ASSERTED for a in author_attr)


# ── Export logic tests ────────────────────────────────────────────────


class TestResolveAttributionsDict:
    """Test the _resolve_attributions helper used in export_entities.py."""

    def test_new_format(self):
        from scripts.export_entities import _resolve_attributions

        speaker = {
            "name": "Test",
            "attributions": [
                {"claim_index": 0, "attribution": "quoted"},
                {"claim_index": 2, "attribution": "mentioned"},
            ],
        }
        result = _resolve_attributions(speaker)
        assert len(result) == 2
        assert result[0] == {"claim_index": 0, "attribution": "quoted"}
        assert result[1] == {"claim_index": 2, "attribution": "mentioned"}

    def test_legacy_format(self):
        from scripts.export_entities import _resolve_attributions

        speaker = {"name": "Test", "claim_indices": [1, 3]}
        result = _resolve_attributions(speaker)
        assert len(result) == 2
        assert result[0] == {"claim_index": 1, "attribution": "asserted"}

    def test_empty(self):
        from scripts.export_entities import _resolve_attributions

        speaker = {"name": "Test"}
        assert _resolve_attributions(speaker) == []


class TestMergeEntityAttributionCounts:
    """Test that _merge_entity correctly tracks attribution counts."""

    def test_attribution_counts_accumulated(self):
        from scripts.export_entities import _merge_entity

        entities: dict[str, dict] = {}
        speaker = {
            "name": "Test Person",
            "type": "individual",
            "stance": "neutral",
            "attributions": [
                {"claim_index": 0, "attribution": "quoted"},
                {"claim_index": 1, "attribution": "paraphrased"},
                {"claim_index": 2, "attribution": "mentioned"},
            ],
        }
        claim_data = [
            {"slug": "claim-0", "verdict": "supported"},
            {"slug": "claim-1", "verdict": "unsupported"},
            {"slug": "claim-2", "verdict": "misleading"},
        ]
        _merge_entity(entities, speaker, "article-1", claim_data)
        entity = entities["test-person"]
        assert entity["_attribution_counts"]["quoted"] == 1
        assert entity["_attribution_counts"]["paraphrased"] == 1
        assert entity["_attribution_counts"]["mentioned"] == 1
        assert entity["_attribution_counts"]["asserted"] == 0

    def test_mentioned_excluded_from_verdicts(self):
        """Claims linked via 'mentioned' should not count toward credibility."""
        from scripts.export_entities import _merge_entity

        entities: dict[str, dict] = {}
        speaker = {
            "name": "Only Mentioned",
            "type": "institution",
            "stance": "neutral",
            "attributions": [
                {"claim_index": 0, "attribution": "mentioned"},
            ],
        }
        claim_data = [{"slug": "claim-0", "verdict": "unsupported"}]
        _merge_entity(entities, speaker, "article-1", claim_data)
        entity = entities["only-mentioned"]
        # 'mentioned' should NOT add to _verdicts
        assert entity["_verdicts"] == []

    def test_active_attributions_count_verdicts(self):
        """Asserted/quoted/paraphrased claims should count toward credibility."""
        from scripts.export_entities import _merge_entity

        entities: dict[str, dict] = {}
        speaker = {
            "name": "Active Speaker",
            "type": "individual",
            "stance": "pro_eu",
            "attributions": [
                {"claim_index": 0, "attribution": "asserted"},
                {"claim_index": 1, "attribution": "quoted"},
                {"claim_index": 2, "attribution": "mentioned"},
            ],
        }
        claim_data = [
            {"slug": "c-0", "verdict": "supported"},
            {"slug": "c-1", "verdict": "unsupported"},
            {"slug": "c-2", "verdict": "unsupported"},
        ]
        _merge_entity(entities, speaker, "article-1", claim_data)
        entity = entities["active-speaker"]
        # Only asserted + quoted should be in _verdicts
        assert entity["_verdicts"] == ["supported", "unsupported"]


# ── prepare_site.py speaker resolution tests ──────────────────────────


class TestSpeakersForClaim:
    def test_new_format_with_attribution(self):
        from scripts.prepare_site import _speakers_for_claim

        entities_data = {
            "article_author": {
                "name": "Author",
                "type": "individual",
                "stance": "neutral",
                "attributions": [
                    {"claim_index": 0, "attribution": "asserted"},
                ],
            },
            "speakers": [
                {
                    "name": "Quoted Person",
                    "type": "individual",
                    "stance": "pro_eu",
                    "attributions": [
                        {"claim_index": 0, "attribution": "quoted"},
                        {"claim_index": 1, "attribution": "paraphrased"},
                    ],
                },
            ],
        }
        result = _speakers_for_claim(entities_data, 0)
        assert len(result) == 2
        assert result[0]["name"] == "Author"
        assert result[0]["attribution"] == "asserted"
        assert result[1]["name"] == "Quoted Person"
        assert result[1]["attribution"] == "quoted"

    def test_legacy_format_defaults_to_asserted(self):
        from scripts.prepare_site import _speakers_for_claim

        entities_data = {
            "article_author": None,
            "speakers": [
                {
                    "name": "Old Speaker",
                    "type": "party",
                    "stance": "anti_eu",
                    "claim_indices": [0, 1],
                },
            ],
        }
        result = _speakers_for_claim(entities_data, 0)
        assert len(result) == 1
        assert result[0]["attribution"] == "asserted"

    def test_no_match(self):
        from scripts.prepare_site import _speakers_for_claim

        entities_data = {
            "article_author": None,
            "speakers": [
                {
                    "name": "Speaker",
                    "type": "individual",
                    "stance": "neutral",
                    "attributions": [
                        {"claim_index": 5, "attribution": "quoted"},
                    ],
                },
            ],
        }
        assert _speakers_for_claim(entities_data, 0) == []

    def test_none_entities(self):
        from scripts.prepare_site import _speakers_for_claim

        assert _speakers_for_claim(None, 0) == []


# ── Alþingi name matching tests ──────────────────────────────────────


class TestNameMatches:
    """Test _name_matches fuzzy matching for Alþingi speaker names."""

    def test_exact_match(self):
        from scripts.export_entities import _name_matches

        assert _name_matches(
            "Sigmundur Davíð Gunnlaugsson",
            "Sigmundur Davíð Gunnlaugsson",
        )

    def test_case_insensitive(self):
        from scripts.export_entities import _name_matches

        assert _name_matches(
            "sigmundur davíð gunnlaugsson",
            "Sigmundur Davíð Gunnlaugsson",
        )

    def test_partial_name_matches_full(self):
        from scripts.export_entities import _name_matches

        assert _name_matches(
            "Sigmundur Davíð",
            "Sigmundur Davíð Gunnlaugsson",
        )

    def test_single_word_no_match(self):
        from scripts.export_entities import _name_matches

        # Single-word names should not fuzzy-match (too many false positives)
        assert not _name_matches("Sigmundur", "Sigmundur Davíð Gunnlaugsson")

    def test_no_overlap(self):
        from scripts.export_entities import _name_matches

        assert not _name_matches("Katrín Jakobsdóttir", "Bergþór Ólason")

    def test_enrichment_skips_non_individuals(self):
        from scripts.export_entities import _enrich_althingi_stats

        entities = {
            "esb": {
                "slug": "esb",
                "name": "Evrópusambandið",
                "type": "institution",
            },
        }
        # Should skip institutions even if name somehow matched
        result = _enrich_althingi_stats(entities)
        assert result == 0
        assert "althingi_stats" not in entities["esb"]
