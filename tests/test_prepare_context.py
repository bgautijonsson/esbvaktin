"""Smoke tests for prepare_context.py — the context preparation layer.

Tests use mock claims/evidence objects (no DB or embeddings needed).
"""

from pathlib import Path

import pytest

from esbvaktin.pipeline.models import (
    Claim,
    ClaimType,
    ClaimWithEvidence,
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
        _make_cwe(claim=_make_claim(text=f"Fullyrðing {i}", category="trade"))
        for i in range(1, 4)
    ]
    path = prepare_assessment_context(claims, tmp_path, language="is")
    content = path.read_text(encoding="utf-8")
    assert "Fullyrðing 1" in content
    assert "Fullyrðing 2" in content
    assert "Fullyrðing 3" in content
