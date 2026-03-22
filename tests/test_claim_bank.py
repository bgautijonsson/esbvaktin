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
