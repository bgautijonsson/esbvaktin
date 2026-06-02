"""cost-02: the assessor context must lead with the invariant instruction + Icelandic
quality block as a contiguous, byte-identical PREFIX, so it can later become a prompt-cache
prefix (cost-01). The per-article claims/evidence are the variable suffix.

Reordering is behaviour-preserving — the claims are still presented after the rules; only
their position relative to the (invariant) quality block changes.
"""

from __future__ import annotations

import os

from esbvaktin.pipeline.models import Claim, ClaimType, ClaimWithEvidence
from esbvaktin.pipeline.prepare_context import _load_icelandic_blocks, prepare_assessment_context


def _cwe(text: str) -> ClaimWithEvidence:
    return ClaimWithEvidence(
        claim=Claim(
            claim_text=text,
            original_quote=text,
            category="fisheries",
            claim_type=ClaimType.STATISTIC,
            confidence=0.9,
        ),
        evidence=[],
    )


def test_invariant_blocks_precede_the_claims(tmp_path):
    blocks = _load_icelandic_blocks()
    assert blocks, "assessment-blocks.md must exist for this prefix to be worth caching"

    work = tmp_path / "a"
    work.mkdir()
    claim_text = "Ísland fiskar 30% af þorski Norðaustur-Atlantshafsins"
    ctx = prepare_assessment_context([_cwe(claim_text)], work).read_text(encoding="utf-8")

    assert blocks in ctx
    assert claim_text in ctx
    # The invariant quality block is part of the prefix: it appears before the claim.
    assert ctx.index(blocks) < ctx.index(claim_text)


def test_prefix_is_invariant_across_articles(tmp_path):
    blocks = _load_icelandic_blocks()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ctx_a = prepare_assessment_context(
        [_cwe("Fyrsta fullyrðing um sjávarútveg")], tmp_path / "a"
    ).read_text(encoding="utf-8")
    ctx_b = prepare_assessment_context(
        [_cwe("Önnur fullyrðing um upptöku evru")], tmp_path / "b"
    ).read_text(encoding="utf-8")

    common = os.path.commonprefix([ctx_a, ctx_b])
    # Caching the shared prefix must cache the entire invariant instruction + quality
    # block — i.e. the block lies wholly inside the part that does not vary by article.
    assert blocks in common
