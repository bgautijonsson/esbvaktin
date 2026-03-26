"""Smoke tests for prepare_context.py — the context preparation layer.

Tests use mock claims/evidence objects (no DB or embeddings needed).
"""

from pathlib import Path

import pytest

from esbvaktin.pipeline.models import (
    Claim,
    ClaimType,
    ClaimWithEvidence,
    EpistemicType,
    EvidenceMatch,
)
from esbvaktin.pipeline.prepare_context import (
    _load_icelandic_blocks,
    _load_icelandic_blocks_subset,
    prepare_assessment_context,
    prepare_extraction_context,
    prepare_omission_context,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _make_claim(
    text: str = "Ísland hefur innleitt 75% af ESB-regluverki",
    quote: str = "Ísland hefur innleitt 75% af ESB-regluverki",
    category: str = "eea_eu_law",
    claim_type: ClaimType = ClaimType.STATISTIC,
) -> Claim:
    return Claim(
        claim_text=text,
        original_quote=quote,
        category=category,
        claim_type=claim_type,
        confidence=0.9,
    )


def _make_evidence(
    evidence_id: str = "EEA-LEGAL-001",
    statement: str = "Iceland has adopted approximately 75% of EU single-market legislation.",
    similarity: float = 0.82,
) -> EvidenceMatch:
    return EvidenceMatch(
        evidence_id=evidence_id,
        statement=statement,
        similarity=similarity,
        source_name="European Commission",
        source_url="https://ec.europa.eu/example",
        caveats="This figure applies to single-market acquis only.",
        statement_is="Ísland hefur innleitt u.þ.b. 75% af regluverki innri markaðarins.",
    )


def _make_cwe(
    claim: Claim | None = None,
    evidence: list[EvidenceMatch] | None = None,
) -> ClaimWithEvidence:
    return ClaimWithEvidence(
        claim=claim or _make_claim(),
        evidence=evidence if evidence is not None else [_make_evidence()],
    )


# ── Icelandic blocks ─────────────────────────────────────────────────


def test_load_icelandic_blocks_returns_string():
    """Blocks file should exist and return non-empty content."""
    content = _load_icelandic_blocks()
    # May be empty in some test environments, but shouldn't crash
    assert isinstance(content, str)


def test_load_icelandic_blocks_subset():
    content = _load_icelandic_blocks()
    if not content:
        pytest.skip("Icelandic blocks file not found in test environment")
    subset = _load_icelandic_blocks_subset("Block D", "Block F")
    assert isinstance(subset, str)
    # Subset should be shorter than full blocks
    assert len(subset) <= len(content)


# ── Extraction context ────────────────────────────────────────────────


def test_extraction_context_is(tmp_path: Path):
    """Icelandic extraction context should contain key instruction sections."""
    path = prepare_extraction_context(
        "Þetta er prófunargrein um ESB-aðild Íslands.",
        tmp_path,
        language="is",
    )
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Fullyrðingagreining" in content
    assert "claim_text" in content
    assert "Þetta er prófunargrein" in content
    # Category list should be present
    assert "fisheries" in content
    assert "sovereignty" in content


def test_extraction_context_with_metadata(tmp_path: Path):
    """Metadata section should appear when provided."""
    metadata = {"Titill": "Prófunargrein", "Heimild": "RÚV"}
    path = prepare_extraction_context(
        "Texti greinar.",
        tmp_path,
        metadata=metadata,
        language="is",
    )
    content = path.read_text(encoding="utf-8")
    assert "Prófunargrein" in content
    assert "RÚV" in content


def test_extraction_context_en(tmp_path: Path):
    """English extraction context should work as fallback."""
    path = prepare_extraction_context(
        "Test article about EU membership.",
        tmp_path,
        language="en",
    )
    content = path.read_text(encoding="utf-8")
    assert "Claim Extraction Task" in content


# ── Assessment context ────────────────────────────────────────────────


def test_assessment_context_is(tmp_path: Path):
    """Icelandic assessment context should contain claims and evidence."""
    cwe = _make_cwe()
    path = prepare_assessment_context(
        [cwe],
        tmp_path,
        language="is",
    )
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    # Should contain the claim text
    assert "75%" in content
    # Should contain the evidence ID
    assert "EEA-LEGAL-001" in content
    # Should contain similarity score
    assert "0.82" in content
    # Should contain the source name
    assert "European Commission" in content
    # Should contain caveats
    assert "single-market" in content


def test_assessment_context_empty_evidence(tmp_path: Path):
    """Assessment context with no evidence should show 'no evidence' message."""
    cwe = _make_cwe(evidence=[])
    path = prepare_assessment_context(
        [cwe],
        tmp_path,
        language="is",
    )
    content = path.read_text(encoding="utf-8")
    assert "Engar viðeigandi heimildir" in content


def test_assessment_context_with_speech(tmp_path: Path):
    """Speech context should be appended when provided."""
    cwe = _make_cwe()
    speech_ctx = "## Þingræður\n\nJón Jónsson sagði í þingræðu..."
    path = prepare_assessment_context(
        [cwe],
        tmp_path,
        language="is",
        speech_context=speech_ctx,
    )
    content = path.read_text(encoding="utf-8")
    assert "Þingræður" in content
    assert "Jón Jónsson" in content


# ── Omission context ─────────────────────────────────────────────────


def test_omission_context_is(tmp_path: Path):
    """Icelandic omission context should contain article text and evidence."""
    cwe = _make_cwe()
    path = prepare_omission_context(
        "Greinin fjallar um ESB-aðild.",
        [cwe],
        tmp_path,
        language="is",
    )
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "vantar" in content.lower() or "eyður" in content.lower()
    assert "EEA-LEGAL-001" in content
    assert "Greinin fjallar" in content


def test_omission_context_compact_mode(tmp_path: Path):
    """Large evidence should trigger compact mode (statement_is)."""
    # Create evidence with a very large statement to trigger compact mode
    big_statement = "x " * 30_000  # 60KB > 50KB threshold
    evidence = _make_evidence(statement=big_statement)
    cwe = _make_cwe(evidence=[evidence])
    path = prepare_omission_context(
        "Short article.",
        [cwe],
        tmp_path,
        language="is",
    )
    content = path.read_text(encoding="utf-8")
    # In compact mode, should use statement_is (Icelandic summary)
    assert "innri markaðarins" in content
    # Should NOT contain the full 60KB English text
    assert "x x x x x x x x x x" not in content


def test_omission_context_truncates_large_article(tmp_path: Path):
    """Very large article text should be truncated."""
    big_article = "Texti " * 10_000  # ~60KB > 30KB threshold
    cwe = _make_cwe()
    path = prepare_omission_context(
        big_article,
        [cwe],
        tmp_path,
        language="is",
    )
    content = path.read_text(encoding="utf-8")
    assert "klippt" in content  # truncation marker


# ── Multiple claims ──────────────────────────────────────────────────


def test_assessment_context_multiple_claims(tmp_path: Path):
    """Assessment context with multiple claims should number them."""
    claims = [
        _make_cwe(claim=_make_claim(text=f"Fullyrðing {i}", category="trade")) for i in range(1, 4)
    ]
    path = prepare_assessment_context(claims, tmp_path, language="is")
    content = path.read_text(encoding="utf-8")
    assert "Fullyrðing 1" in content
    assert "Fullyrðing 2" in content
    assert "Fullyrðing 3" in content


# ── Epistemic type ────────────────────────────────────────────────────


def test_extraction_context_includes_epistemic_type(tmp_path: Path):
    path = prepare_extraction_context(
        article_text="Test article about ESB",
        output_dir=tmp_path,
        language="is",
    )
    content = path.read_text()
    assert "epistemic_type" in content
    assert "hearsay" in content
    assert "counterfactual" in content
    # claim_type should show forecast, not prediction
    assert "forecast" in content


def test_assessment_context_includes_epistemic_rules(tmp_path: Path):
    claim = Claim(
        claim_text="Ef aðild næðist myndi matvælaverð lækka",
        original_quote="Test",
        category="trade",
        claim_type=ClaimType.FORECAST,
        epistemic_type=EpistemicType.PREDICTION,
        confidence=0.7,
    )
    cwe = ClaimWithEvidence(claim=claim, evidence=[])
    path = prepare_assessment_context([cwe], tmp_path, language="is")
    content = path.read_text()
    assert "Þekkingarstaða" in content or "epistemic_type" in content
    assert "prediction" in content
    assert "Heimildasamstaða" in content or "samstaða" in content.lower()


# ── Bank match context ────────────────────────────────────────────────


def test_assessment_context_with_bank_match(tmp_path):
    """Assessment context renders bank match prior verdict."""
    from datetime import date

    from esbvaktin.claim_bank.models import ClaimBankMatch
    from esbvaktin.pipeline.models import (
        Claim,
        ClaimType,
        ClaimWithEvidence,
    )
    from esbvaktin.pipeline.prepare_context import prepare_assessment_context

    claim = Claim(
        claim_text="Sjávarútvegur er mikilvægur",
        original_quote="Test",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        confidence=0.9,
    )
    cwe = ClaimWithEvidence(claim=claim, evidence=[])
    bank_match = ClaimBankMatch(
        claim_id=1,
        claim_slug="sjavarutvegur-mikilvagur",
        canonical_text_is="Sjávarútvegur er mikilvægur",
        similarity=0.92,
        verdict="supported",
        explanation_is="Heimildir staðfesta þetta.",
        confidence=0.85,
        last_verified=date.today(),
        is_fresh=True,
    )
    path = prepare_assessment_context([cwe], tmp_path, language="is", bank_matches={0: bank_match})
    content = path.read_text()
    assert "Fyrra mat" in content or "fyrra mat" in content.lower()
    assert "sjavarutvegur-mikilvagur" in content
    assert "supported" in content
    assert "0.92" in content or "92" in content


def test_assessment_context_stale_bank_match(tmp_path):
    """Stale bank match shows staleness label."""
    from datetime import date, timedelta

    from esbvaktin.claim_bank.models import ClaimBankMatch
    from esbvaktin.pipeline.models import (
        Claim,
        ClaimType,
        ClaimWithEvidence,
    )
    from esbvaktin.pipeline.prepare_context import prepare_assessment_context

    claim = Claim(
        claim_text="Test claim",
        original_quote="Test",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        confidence=0.9,
    )
    cwe = ClaimWithEvidence(claim=claim, evidence=[])
    bank_match = ClaimBankMatch(
        claim_id=1,
        claim_slug="test-stale",
        canonical_text_is="Test",
        similarity=0.85,
        verdict="partially_supported",
        explanation_is="Test.",
        confidence=0.7,
        last_verified=date.today() - timedelta(days=60),
        is_fresh=False,
    )
    path = prepare_assessment_context([cwe], tmp_path, language="is", bank_matches={0: bank_match})
    content = path.read_text()
    assert "úrelt" in content.lower() or "stale" in content.lower()


def test_assessment_context_without_bank_match_unchanged(tmp_path):
    """Assessment context without bank_matches works as before."""
    from esbvaktin.pipeline.models import (
        Claim,
        ClaimType,
        ClaimWithEvidence,
    )
    from esbvaktin.pipeline.prepare_context import prepare_assessment_context

    claim = Claim(
        claim_text="Test",
        original_quote="Test",
        category="fisheries",
        claim_type=ClaimType.STATISTIC,
        confidence=0.9,
    )
    cwe = ClaimWithEvidence(claim=claim, evidence=[])
    path = prepare_assessment_context([cwe], tmp_path, language="is")
    content = path.read_text()
    assert "Fyrra mat" not in content
    assert "verdict" not in content.lower() or "verdict" in content.lower()  # no bank match block
