"""Tests for output normalisation functions in parse_outputs.py.

Covers the field alias variants that agents actually produce.
"""

from esbvaktin.pipeline.parse_outputs import _normalise_assessment, _normalise_omissions

# ── Assessment normalisation ──────────────────────────────────────────


def test_normalise_nested_claim_passthrough():
    """Already-nested format should pass through unchanged."""
    item = {
        "claim": {
            "claim_text": "Test claim",
            "original_quote": "Test quote",
            "category": "trade",
            "claim_type": "statistic",
            "confidence": 0.9,
        },
        "verdict": "supported",
        "explanation": "Evidence confirms.",
        "supporting_evidence": ["TRADE-DATA-001"],
        "contradicting_evidence": [],
        "missing_context": None,
        "confidence": 0.85,
    }
    result = _normalise_assessment(item)
    assert "claim" in result
    assert result["claim"]["claim_text"] == "Test claim"


def test_normalise_flat_assessment():
    """Flat format (claim fields at top level) should be restructured."""
    item = {
        "claim_text": "ESB-aðild kostar peninga",
        "original_quote": "ESB-aðild kostar peninga",
        "category": "trade",
        "claim_type": "statistic",
        "verdict": "supported",
        "explanation": "Heimildir staðfesta.",
        "supporting_evidence": ["TRADE-DATA-001"],
        "contradicting_evidence": [],
        "missing_context": None,
        "confidence": 0.85,
    }
    result = _normalise_assessment(item)
    assert "claim" in result
    assert result["claim"]["claim_text"] == "ESB-aðild kostar peninga"
    assert result["verdict"] == "supported"


def test_normalise_evidence_ids_alias():
    """'evidence_ids' should be mapped to 'supporting_evidence'."""
    item = {
        "claim_text": "Test",
        "original_quote": "Test",
        "verdict": "supported",
        "explanation": "Yes.",
        "evidence_ids": ["FISH-DATA-001", "FISH-DATA-002"],
        "contradicting_evidence": [],
        "confidence": 0.9,
    }
    result = _normalise_assessment(item)
    assert result["supporting_evidence"] == ["FISH-DATA-001", "FISH-DATA-002"]
    assert "evidence_ids" not in result


def test_normalise_caveats_alias():
    """'caveats' should be mapped to 'missing_context'."""
    item = {
        "claim_text": "Test",
        "original_quote": "Test",
        "verdict": "partially_supported",
        "explanation": "Partially.",
        "supporting_evidence": [],
        "contradicting_evidence": [],
        "caveats": "Vantar nýjustu gögnin.",
        "confidence": 0.7,
    }
    result = _normalise_assessment(item)
    assert result["missing_context"] == "Vantar nýjustu gögnin."
    assert "caveats" not in result


def test_normalise_quote_alias():
    """'quote' should be mapped to 'original_quote'."""
    item = {
        "claim_text": "Test",
        "quote": "Direct quote from article",
        "verdict": "supported",
        "explanation": "Yes.",
        "supporting_evidence": [],
        "contradicting_evidence": [],
        "confidence": 0.9,
    }
    result = _normalise_assessment(item)
    assert result["claim"]["original_quote"] == "Direct quote from article"


def test_normalise_speaker_name_preserved():
    """Speaker name should be passed through to the nested claim."""
    item = {
        "claim_text": "Test",
        "original_quote": "Test",
        "speaker_name": "Bjarni Benediktsson",
        "verdict": "supported",
        "explanation": "Yes.",
        "supporting_evidence": [],
        "contradicting_evidence": [],
        "confidence": 0.9,
    }
    result = _normalise_assessment(item)
    assert result["claim"]["speaker_name"] == "Bjarni Benediktsson"


# ── Omission normalisation ───────────────────────────────────────────


def test_normalise_omissions_framing_alias():
    """Short framing aliases should be expanded."""
    raw = {
        "framing_assessment": "strongly_anti",
        "overall_completeness": 0.3,
        "omissions": [],
    }
    result = _normalise_omissions(raw)
    assert result["framing_assessment"] == "strongly_anti_eu"


def test_normalise_omissions_evidence_ids_alias():
    """'evidence_ids' in omissions should be mapped to 'relevant_evidence'."""
    raw = {
        "framing_assessment": "balanced",
        "overall_completeness": 0.8,
        "omissions": [
            {
                "topic": "fisheries",
                "description": "Vantar umfjöllun um sjávarútveg.",
                "evidence_ids": ["FISH-DATA-001"],
            }
        ],
    }
    result = _normalise_omissions(raw)
    assert result["omissions"][0]["relevant_evidence"] == ["FISH-DATA-001"]
    assert "evidence_ids" not in result["omissions"][0]


def test_normalise_omissions_valid_framing_passthrough():
    """Valid full framing names should pass through unchanged."""
    raw = {
        "framing_assessment": "leans_pro_eu",
        "overall_completeness": 0.6,
        "omissions": [],
    }
    result = _normalise_omissions(raw)
    assert result["framing_assessment"] == "leans_pro_eu"
