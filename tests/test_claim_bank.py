"""Tests for the Claim Bank module (unit tests, no DB required)."""

from esbvaktin.claim_bank.models import CanonicalClaim, ClaimBankMatch
from esbvaktin.claim_bank.operations import generate_slug


class TestSlugGeneration:
    """Tests for Icelandic text → URL slug conversion."""

    def test_basic_icelandic(self):
        assert generate_slug("Sjávarútvegur og kvótakerfi") == "sjavarutvegur-og-kvotakerfi"

    def test_thorn_and_eth(self):
        assert generate_slug("Þjóðaratkvæðagreiðsla um aðild") == "thjodaratkvaedagreidsla-um-adild"

    def test_ae_and_o_umlaut(self):
        result = generate_slug("Æðri menntun og öldrun")
        assert "ae" in result
        assert "o" in result

    def test_percentage(self):
        result = generate_slug("30% samdráttur í afla")
        assert "30" in result
        assert "percent" in result

    def test_em_dash(self):
        result = generate_slug("ESB — aðild Íslands")
        assert "--" not in result  # No double hyphens
        assert result == "esb-adild-islands"

    def test_strips_edges(self):
        result = generate_slug("  — Ísland — ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_empty_after_cleanup(self):
        result = generate_slug("--- ---")
        assert result == ""


class TestCanonicalClaimModel:
    """Tests for the CanonicalClaim Pydantic model."""

    def test_valid_claim(self):
        claim = CanonicalClaim(
            claim_slug="sjavarutvegur-kvotakerfi",
            canonical_text_is="Ísland myndi missa yfirráð yfir fiskveiðum",
            category="fisheries",
            claim_type="legal_assertion",
            verdict="partially_supported",
            explanation_is="FISH-LEGAL-002 staðfestir...",
            confidence=0.8,
        )
        assert claim.claim_slug == "sjavarutvegur-kvotakerfi"
        assert claim.published is True

    def test_slug_validation(self):
        """Slug must be lowercase alphanumeric with hyphens."""
        import pytest

        with pytest.raises(Exception):
            CanonicalClaim(
                claim_slug="Invalid Slug!",
                canonical_text_is="Test",
                category="fisheries",
                claim_type="statistic",
                verdict="supported",
                explanation_is="Test",
                confidence=0.9,
            )

    def test_confidence_bounds(self):
        import pytest

        with pytest.raises(Exception):
            CanonicalClaim(
                claim_slug="test-slug",
                canonical_text_is="Test",
                category="fisheries",
                claim_type="statistic",
                verdict="supported",
                explanation_is="Test",
                confidence=1.5,
            )


class TestVerdictDistance:
    """Tests for graduated verdict distance calculation."""

    def test_same_verdict(self):
        from esbvaktin.claim_bank.confidence import verdict_distance

        assert verdict_distance("supported", "supported") == 0

    def test_adjacent_verdicts(self):
        from esbvaktin.claim_bank.confidence import verdict_distance

        assert verdict_distance("supported", "partially_supported") == 1

    def test_far_verdicts(self):
        from esbvaktin.claim_bank.confidence import verdict_distance

        assert verdict_distance("supported", "misleading") == 3

    def test_medium_distance(self):
        from esbvaktin.claim_bank.confidence import verdict_distance

        assert verdict_distance("supported", "unsupported") == 2
        assert verdict_distance("partially_supported", "misleading") == 2

    def test_unverifiable_always_distance_1(self):
        from esbvaktin.claim_bank.confidence import verdict_distance

        assert verdict_distance("supported", "unverifiable") == 1
        assert verdict_distance("misleading", "unverifiable") == 1

    def test_symmetric(self):
        from esbvaktin.claim_bank.confidence import verdict_distance

        assert verdict_distance("supported", "misleading") == verdict_distance(
            "misleading", "supported"
        )


class TestGraduatedDecay:
    """Tests for graduated confidence decay logic."""

    def test_adjacent_decay_is_5pct(self):
        from esbvaktin.claim_bank.confidence import BASE_DECAY_FACTOR

        # Distance 1 → decay = BASE_DECAY_FACTOR^1 = 0.95
        assert BASE_DECAY_FACTOR**1 == 0.95

    def test_far_decay_is_stronger(self):
        from esbvaktin.claim_bank.confidence import BASE_DECAY_FACTOR

        # Distance 3 → decay = 0.95^3 ≈ 0.857
        d3 = BASE_DECAY_FACTOR**3
        assert d3 < 0.86
        assert d3 > 0.85

    def test_midrange_decay(self):
        from esbvaktin.claim_bank.confidence import BASE_DECAY_FACTOR

        # Distance 2 → 0.95^2 = 0.9025
        d2 = BASE_DECAY_FACTOR**2
        assert 0.90 < d2 < 0.91


class TestClaimBankMatchModel:
    """Tests for the ClaimBankMatch model."""

    def test_fresh_claim(self):
        from datetime import date

        match = ClaimBankMatch(
            claim_id=1,
            claim_slug="test-slug",
            canonical_text_is="Test",
            similarity=0.9,
            verdict="supported",
            explanation_is="Test explanation",
            confidence=0.85,
            last_verified=date.today(),
            is_fresh=True,
        )
        assert match.is_fresh is True
        assert match.similarity == 0.9
