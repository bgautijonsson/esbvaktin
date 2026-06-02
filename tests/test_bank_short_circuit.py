"""Tests for the cost-03 claim-bank short-circuit (Option A — strict).

No database — monkeypatch check_claim_bank / retrieve_evidence_for_claim / embed_texts
(following test_hearsay_short_circuit.py).
"""

from datetime import date

from esbvaktin.claim_bank.models import ClaimBankMatch


def _match(**over) -> ClaimBankMatch:
    base = dict(
        claim_id=1,
        claim_slug="fiskveidilogsaga",
        canonical_text_is="Ísland heldur yfirráðum yfir fiskveiðilögsögu.",
        similarity=0.92,
        verdict="supported",
        epistemic_type="factual",
        explanation_is="Heimildir styðja þetta.",
        supporting_evidence=["FISH-LEGAL-001"],
        contradicting_evidence=[],
        missing_context_is=None,
        confidence=0.88,
        last_verified=date.today(),
        is_fresh=True,
    )
    base.update(over)
    return ClaimBankMatch(**base)


def test_bank_match_carries_needs_reassessment_default_false():
    """ClaimBankMatch exposes needs_reassessment (default False) so the
    short-circuit can respect the system's verdict-revision flag."""
    assert _match().needs_reassessment is False
    assert _match(needs_reassessment=True).needs_reassessment is True


def test_is_reusable_requires_exact_fresh_factual_unflagged():
    """A verdict is reused only when similarity>=0.85 AND fresh AND not flagged
    AND factual — each guard alone blocks reuse."""
    from esbvaktin.pipeline.retrieve_evidence import is_reusable_bank_match

    assert is_reusable_bank_match(_match()) is True
    assert is_reusable_bank_match(_match(similarity=0.80)) is False  # below exact threshold
    assert is_reusable_bank_match(_match(is_fresh=False)) is False  # stale
    assert is_reusable_bank_match(_match(needs_reassessment=True)) is False  # flagged for revision
    assert is_reusable_bank_match(_match(epistemic_type="prediction")) is False  # non-factual


def test_bank_match_to_assessment_reuses_stored_verdict_and_evidence():
    """The reused assessment carries the bank's verdict, evidence IDs, confidence
    and explanation, bound to the article's claim — so the report stays evidence-rich
    with no Opus call."""
    from esbvaktin.pipeline.models import Claim, ClaimType, EpistemicType, Verdict
    from esbvaktin.pipeline.retrieve_evidence import bank_match_to_assessment

    claim = Claim(
        claim_text="Ísland heldur yfirráðum yfir fiskveiðilögsögu.",
        original_quote="Tilvitnun",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        epistemic_type=EpistemicType.FACTUAL,
        confidence=0.9,
    )
    match = _match(
        verdict="partially_supported",
        supporting_evidence=["FISH-LEGAL-001"],
        contradicting_evidence=["FISH-LEGAL-003"],
        confidence=0.82,
        explanation_is="Styðst að hluta.",
        missing_context_is="Vantar samhengi um undantekningar.",
    )

    a = bank_match_to_assessment(claim, match)

    assert a.claim is claim
    assert a.verdict == Verdict.PARTIALLY_SUPPORTED
    assert a.supporting_evidence == ["FISH-LEGAL-001"]
    assert a.contradicting_evidence == ["FISH-LEGAL-003"]
    assert a.confidence == 0.82
    assert a.explanation == "Styðst að hluta."
    assert a.missing_context == "Vantar samhengi um undantekningar."


def test_reusable_match_short_circuits_fuzzy_goes_to_opus(monkeypatch):
    """A reusable exact match skips retrieval + Opus (lands in bank_assessments); a
    fuzzy match stays Opus-bound with bank_matches re-keyed to its index in the
    (post-skip) claims_with_evidence list."""
    from esbvaktin.pipeline.models import Claim, ClaimType, ClaimWithEvidence, EpistemicType

    def _claim(text: str) -> Claim:
        return Claim(
            claim_text=text,
            original_quote="q",
            category="fisheries",
            claim_type=ClaimType.STATISTIC,
            epistemic_type=EpistemicType.FACTUAL,
            confidence=0.9,
        )

    exact_claim = _claim("EXACT reusable")
    fuzzy_claim = _claim("FUZZY borderline")

    retrieved: list[str] = []

    def mock_retrieve(claim, top_k=5, conn=None, embedding=None):
        retrieved.append(claim.claim_text)
        return ClaimWithEvidence(claim=claim, evidence=[])

    def mock_check_bank(claim, conn=None, embedding=None):
        if claim.claim_text == "EXACT reusable":
            return _match(similarity=0.95)  # reusable -> short-circuit
        if claim.claim_text == "FUZZY borderline":
            return _match(similarity=0.78)  # fuzzy -> Opus context only
        return None

    monkeypatch.setattr(
        "esbvaktin.pipeline.retrieve_evidence.retrieve_evidence_for_claim", mock_retrieve
    )
    monkeypatch.setattr("esbvaktin.pipeline.retrieve_evidence.check_claim_bank", mock_check_bank)
    monkeypatch.setattr(
        "esbvaktin.ground_truth.operations.embed_texts",
        lambda texts, batch_size=32: [[0.0] * 1024 for _ in texts],
    )

    from esbvaktin.pipeline.retrieve_evidence import retrieve_evidence_for_claims

    cwe, bank_matches, hearsay, bank_assessments = retrieve_evidence_for_claims(
        [exact_claim, fuzzy_claim]
    )

    # Exact reusable: short-circuited — in bank_assessments, never retrieved, absent from cwe.
    assert [a.claim.claim_text for a in bank_assessments] == ["EXACT reusable"]
    assert "EXACT reusable" not in retrieved
    assert [c.claim.claim_text for c in cwe] == ["FUZZY borderline"]
    # Fuzzy match recorded for Opus context, keyed by its index (0) in the Opus-bound list.
    assert 0 in bank_matches
    assert bank_matches[0].similarity == 0.78


def test_persist_and_parse_bank_assessments_round_trip(tmp_path):
    """Short-circuited assessments persist to _bank_assessments.json and load back
    (mirrors the cost-04 hearsay pair) so assemble_report can merge them."""
    from esbvaktin.pipeline.models import Claim, ClaimType, EpistemicType, Verdict
    from esbvaktin.pipeline.parse_outputs import (
        parse_bank_assessments,
        persist_bank_assessments,
    )
    from esbvaktin.pipeline.retrieve_evidence import bank_match_to_assessment

    claim = Claim(
        claim_text="Ísland heldur yfirráðum yfir fiskveiðilögsögu.",
        original_quote="q",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        epistemic_type=EpistemicType.FACTUAL,
        confidence=0.9,
    )
    assessment = bank_match_to_assessment(claim, _match(verdict="supported"))

    assert persist_bank_assessments(tmp_path, []) is None  # empty => no file written
    persist_bank_assessments(tmp_path, [assessment])
    loaded = parse_bank_assessments(tmp_path)

    assert len(loaded) == 1
    assert loaded[0].verdict == Verdict.SUPPORTED
    assert loaded[0].claim.claim_text == "Ísland heldur yfirráðum yfir fiskveiðilögsögu."


def test_parse_bank_assessments_absent_file_is_empty(tmp_path):
    from esbvaktin.pipeline.parse_outputs import parse_bank_assessments

    assert parse_bank_assessments(tmp_path) == []
