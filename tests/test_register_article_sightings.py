"""Regression tests for register_article_sightings.register_entity_observations.

Covers the 'mentioned'-only entity with a null claim_index — an entity referenced
in an article that makes no specific claim (e.g. the Heimssýn "Kíkt í pakkann"
article, where `utanríkisráðherra` and `Heimssýn` were both mentioned with
claim_index=null). The entity-extractor agent emits these legitimately; the
registration path must register the article mention, not abort the whole run on a
list[int] validation failure.
"""

import json
from unittest.mock import MagicMock, patch

import scripts.register_article_sightings as reg


class _FakeMatch:
    """Stand-in for a matcher.MatchResult — only the attributes the function reads."""

    def __init__(self, entity_id=None, confidence=0.0, method="none"):
        self.entity_id = entity_id
        self.confidence = confidence
        self.method = method
        self.matched_entity = None


def _write_entities(dir_path, speakers):
    dir_path.mkdir(parents=True, exist_ok=True)
    with open(dir_path / "_entities.json", "w", encoding="utf-8") as fh:
        json.dump({"speakers": speakers}, fh, ensure_ascii=False)


@patch("esbvaktin.entity_registry.operations.insert_observation")
@patch("esbvaktin.entity_registry.operations.get_all_entities", return_value=[])
@patch("esbvaktin.entity_registry.matcher.match_entity")
def test_mentioned_null_claim_index_registers(
    mock_match, mock_get_all, mock_insert_obs, tmp_path, monkeypatch
):
    """A 'mentioned'-only speaker with claim_index=null registers an observation with
    empty claim_indices instead of failing EntityObservation(list[int]) validation."""
    # High-confidence match → auto-link branch reaches the observation insert.
    mock_match.return_value = _FakeMatch(entity_id=7, confidence=0.95)

    analysis_dir = "20260621_000000"
    monkeypatch.setattr(reg, "ANALYSES_DIR", tmp_path)
    _write_entities(
        tmp_path / analysis_dir,
        [
            {
                "name": "Heimssýn",
                "type": "institution",
                "stance": "neutral",
                "attributions": [
                    {"claim_index": None, "attribution": "mentioned"},
                ],
            }
        ],
    )

    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = [1]  # entities table populated

    summary = reg.register_entity_observations(
        analysis_dir, {"article_url": "https://example.com/x"}, conn
    )

    # Did not raise; the mentioned entity was auto-linked.
    assert summary["auto_linked"] == 1
    # Observation inserted with NO claim indices (mentioned-only).
    mock_insert_obs.assert_called_once()
    obs = mock_insert_obs.call_args[0][0]
    assert obs.claim_indices == []
    assert obs.attribution_types == ["mentioned"]
    assert obs.observed_name == "Heimssýn"
