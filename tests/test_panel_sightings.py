"""Tests for panel show sighting registration."""

from unittest.mock import MagicMock, patch

from esbvaktin.pipeline.models import Claim, ClaimAssessment, ClaimType, Verdict
from esbvaktin.pipeline.register_sightings import register_panel_sightings


def _make_assessment(
    claim_text: str,
    speaker_name: str,
    verdict: Verdict = Verdict.SUPPORTED,
    category: str = "other",
) -> ClaimAssessment:
    return ClaimAssessment(
        claim=Claim(
            claim_text=claim_text,
            original_quote=claim_text,
            category=category,
            claim_type=ClaimType.OPINION,
            confidence=0.8,
            speaker_name=speaker_name,
        ),
        verdict=verdict,
        explanation="Test",
        supporting_evidence=["TEST-001"],
        contradicting_evidence=[],
        confidence=0.8,
    )


class _FakeMatch:
    def __init__(self, claim_id: int, slug: str, sim: float):
        self.claim_id = claim_id
        self.claim_slug = slug
        self.similarity = sim


@patch("esbvaktin.pipeline.register_sightings.search_claims")
def test_matched_sighting_uses_panel_show_type(mock_search):
    """Matched claims create sightings with source_type='panel_show'."""
    mock_search.return_value = [_FakeMatch(42, "test-claim", 0.85)]
    conn = MagicMock()

    assessments = [_make_assessment("Test claim", "Sigmundur Davíð")]
    counts = register_panel_sightings(
        assessments=assessments,
        source_url="https://example.com",
        source_title="Test Show",
        conn=conn,
    )

    assert counts["matched"] == 1
    call_args = conn.execute.call_args
    params = call_args[0][1]
    assert params["source_type"] == "panel_show"
    assert params["speaker_name"] == "Sigmundur Davíð"


@patch("esbvaktin.pipeline.register_sightings.add_claim", return_value=99)
@patch("esbvaktin.pipeline.register_sightings.search_claims", return_value=[])
def test_new_claim_created_for_non_match(mock_search, mock_add):
    """Non-matching assessable claims create new unpublished claims."""
    conn = MagicMock()

    assessments = [_make_assessment("New claim", "Þorgerður Katrín")]
    counts = register_panel_sightings(
        assessments=assessments,
        source_url="https://example.com",
        source_title="Test Show",
        conn=conn,
    )

    assert counts["new_claims"] == 1
    mock_add.assert_called_once()
    new_claim = mock_add.call_args[0][0]
    assert new_claim.published is False


@patch("esbvaktin.pipeline.register_sightings.search_claims", return_value=[])
def test_unverifiable_discarded(mock_search):
    """Unverifiable claims with no match are discarded."""
    conn = MagicMock()

    assessments = [_make_assessment("Vague claim", "Lilja Dögg", Verdict.UNVERIFIABLE)]
    counts = register_panel_sightings(
        assessments=assessments,
        source_url="https://example.com",
        source_title="Test Show",
        conn=conn,
    )

    assert counts["discarded"] == 1
    assert counts["matched"] == 0
    assert counts["new_claims"] == 0


@patch("esbvaktin.pipeline.register_sightings.search_claims")
def test_speaker_name_preserved_through_sighting(mock_search):
    """Speaker name flows from claim through to the sighting INSERT."""
    mock_search.return_value = [_FakeMatch(1, "test", 0.9)]
    conn = MagicMock()

    register_panel_sightings(
        assessments=[_make_assessment("Claim X", "Guðrún Hafsteinsdóttir")],
        source_url="https://example.com",
        source_title="Test",
        conn=conn,
    )

    params = conn.execute.call_args[0][1]
    assert params["speaker_name"] == "Guðrún Hafsteinsdóttir"


@patch("esbvaktin.pipeline.register_sightings.add_claim", return_value=99)
@patch("esbvaktin.pipeline.register_sightings.search_claims")
def test_mixed_verdicts_counted_correctly(mock_search, mock_add):
    """Counts are correct across a mix of matched, new, and discarded."""
    mock_search.side_effect = [
        [_FakeMatch(1, "existing", 0.8)],  # match
        [],                                  # no match → new
        [],                                  # no match + unverifiable → discard
    ]
    conn = MagicMock()

    assessments = [
        _make_assessment("Matched claim", "A", Verdict.SUPPORTED),
        _make_assessment("New claim", "B", Verdict.PARTIALLY_SUPPORTED),
        _make_assessment("Vague claim", "C", Verdict.UNVERIFIABLE),
    ]
    counts = register_panel_sightings(
        assessments=assessments,
        source_url="https://example.com",
        source_title="Test",
        conn=conn,
    )

    assert counts == {"matched": 1, "new_claims": 1, "discarded": 1}
