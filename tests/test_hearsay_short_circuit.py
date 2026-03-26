"""Tests for hearsay short-circuit in evidence retrieval.

These tests do not require a database — they use monkeypatching.
"""

import pytest

from esbvaktin.pipeline.models import Claim, ClaimType, EpistemicType, Verdict
from esbvaktin.pipeline.retrieve_evidence import retrieve_evidence_for_claims


def test_hearsay_claims_short_circuit(monkeypatch):
    """Hearsay claims get auto-unverifiable without evidence retrieval."""
    hearsay_claim = Claim(
        claim_text="Ónafngreindir segja X",
        original_quote="Test",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        epistemic_type=EpistemicType.HEARSAY,
        confidence=0.5,
    )
    factual_claim = Claim(
        claim_text="Útflutningur er 23%",
        original_quote="Test",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        epistemic_type=EpistemicType.FACTUAL,
        confidence=0.9,
    )

    calls = []

    def mock_retrieve(claim, top_k=5, conn=None):
        calls.append(claim.claim_text)
        from esbvaktin.pipeline.models import ClaimWithEvidence

        return ClaimWithEvidence(claim=claim, evidence=[])

    monkeypatch.setattr(
        "esbvaktin.pipeline.retrieve_evidence.retrieve_evidence_for_claim",
        mock_retrieve,
    )
    monkeypatch.setattr(
        "esbvaktin.pipeline.retrieve_evidence.check_claim_bank",
        lambda claim, conn=None: None,
    )

    results, bank_matches, hearsay_assessments = retrieve_evidence_for_claims(
        [hearsay_claim, factual_claim],
        use_claim_bank=False,
    )

    # Hearsay should NOT trigger evidence retrieval
    assert len(calls) == 1
    assert calls[0] == "Útflutningur er 23%"

    # Hearsay should return pre-built assessment
    assert len(hearsay_assessments) == 1
    assert hearsay_assessments[0].verdict == Verdict.UNVERIFIABLE
    assert hearsay_assessments[0].confidence == 0.0

    # Factual claim should be in evidence results
    assert len(results) == 1
    assert results[0].claim.epistemic_type == EpistemicType.FACTUAL
