"""cost-07 / latency-02: embed each claim once, batch the article up front.

Each claim previously hit bge-m3 2-3× — topic-filtered vector search, unfiltered
vector search, and the claim-bank lookup each embedded the same text. These tests
pin the optimised behaviour: one embedding per claim, threaded into every search,
and a single batched embed_texts call for the whole article.

No DB or model needed — the embedding layer is monkeypatched with counters and the
connection is faked, so the search functions run their real query-building code but
return no rows.
"""

from __future__ import annotations

from esbvaktin.claim_bank import operations as bank_ops
from esbvaktin.ground_truth import operations as ops
from esbvaktin.pipeline import retrieve_evidence
from esbvaktin.pipeline.models import Claim, ClaimType
from tests.conftest import requires_embeddings


class _FakeResult:
    def fetchall(self):
        return []


class _FakeConn:
    """Returns no rows for any query — keeps the search functions DB-free."""

    def execute(self, sql, params=None):
        return _FakeResult()

    def close(self):
        pass


def _claim(text="Ísland myndi missa yfirráð yfir fiskimiðum", category="fisheries"):
    return Claim(
        claim_text=text,
        original_quote=text,
        category=category,
        claim_type=ClaimType.LEGAL_ASSERTION,
        confidence=0.9,
    )


def _patch_counters(monkeypatch):
    calls = {"text": 0, "texts": 0, "batch_sizes": []}

    def fake_embed_text(t):
        calls["text"] += 1
        return [0.0] * 1024

    def fake_embed_texts(texts, batch_size=32):
        calls["texts"] += 1
        calls["batch_sizes"].append(len(texts))
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(ops, "embed_text", fake_embed_text)
    monkeypatch.setattr(ops, "embed_texts", fake_embed_texts)
    return calls


# ── retrieve_evidence orchestration ──────────────────────────────────


def test_single_claim_embeds_once_across_filtered_and_unfiltered(monkeypatch):
    calls = _patch_counters(monkeypatch)
    retrieve_evidence.retrieve_evidence_for_claim(_claim(), conn=_FakeConn())
    # A known-topic claim runs both filtered and unfiltered vector search;
    # both must reuse a single embedding.
    assert calls["text"] == 1
    assert calls["texts"] == 0


def test_batch_retrieval_embeds_the_whole_article_in_one_call(monkeypatch):
    calls = _patch_counters(monkeypatch)
    claims = [_claim(), _claim(text="Matvælaverð myndi lækka", category="trade")]
    retrieve_evidence.retrieve_evidence_for_claims(claims, conn=_FakeConn())
    # One batched embed for the article (both claim texts); no per-search single embeds.
    assert calls["texts"] == 1
    assert calls["batch_sizes"] == [2]
    assert calls["text"] == 0


def test_precomputed_embedding_is_threaded_into_every_search(monkeypatch):
    sentinel = [0.5] * 1024
    seen = []

    def spy_search(
        query, topic_filter=None, domain_filter=None, top_k=10, conn=None, embedding=None
    ):
        seen.append(embedding)
        return []

    monkeypatch.setattr(ops, "embed_text", lambda t: sentinel)
    monkeypatch.setattr(retrieve_evidence, "search_evidence", spy_search)
    retrieve_evidence.retrieve_evidence_for_claim(_claim(), conn=_FakeConn())
    # filtered + unfiltered both receive the one precomputed vector.
    assert seen == [sentinel, sentinel]


# ── lower-level contract: precomputed embedding skips the model ──────


def test_search_evidence_skips_embedding_when_provided(monkeypatch):
    calls = _patch_counters(monkeypatch)
    ops.search_evidence(query="x", embedding=[0.1] * 1024, conn=_FakeConn())
    assert calls["text"] == 0


def test_search_claims_skips_embedding_when_provided(monkeypatch):
    calls = _patch_counters(monkeypatch)
    bank_ops.search_claims(query="x", embedding=[0.1] * 1024, conn=_FakeConn())
    assert calls["text"] == 0


# ── batching must not change the vectors (the safety of cost-07) ─────


@requires_embeddings
def test_batched_embedding_stays_parallel_to_per_text_embedding():
    """cost-07 batches the article via embed_texts. bge-m3 runs in fp16, so batching
    introduces per-component noise on the order of 2**-12 (~2.4e-4) — not bit-identical,
    but the vectors stay parallel (cosine ~ 1), so retrieval ranking (cosine distance) is
    unaffected. Guards against a *real* divergence (a changed model or chunking) while
    tolerating fp16 noise. Runs only in the embeddings env."""
    texts = ["Ísland og sjávarútvegurinn", "Matvælaverð í Evrópusambandinu"]
    batched = ops.embed_texts(texts)
    singles = [ops.embed_text(t) for t in texts]
    assert len(batched) == len(singles) == 2
    for vb, vs in zip(batched, singles):
        dot = sum(a * b for a, b in zip(vb, vs))
        norm_b = sum(a * a for a in vb) ** 0.5
        norm_s = sum(a * a for a in vs) ** 0.5
        cosine = dot / (norm_b * norm_s)
        assert cosine > 0.9999, f"batched vs single embedding cosine only {cosine}"
