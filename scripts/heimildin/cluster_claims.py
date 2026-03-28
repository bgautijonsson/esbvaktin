"""Embedding-based meta-claim clustering for Heimildin.

Clustering:
    discover    Embed all claims, run HDBSCAN, show natural clusters
    seed        Generate starter meta-claims from top clusters
    assign      Assign instances to curated meta-claims by cosine similarity

Per-claim curation (data/heimildin/meta_claims/<ID>/):
    curate init     Create claim, embed + rank candidates
    curate compare  Test alternative wordings
    curate filter   Run LLM agent to accept/reject candidates
    curate review   Generate interactive HTML review
    curate accept   Import user review from HTML export
    curate status   Show all claims and their progress

Usage:
    uv run python scripts/heimildin/cluster_claims.py discover [--min-cluster 5]
    uv run python scripts/heimildin/cluster_claims.py seed [--top 40]
    uv run python scripts/heimildin/cluster_claims.py curate init M01 --text "..." --category fisheries
    uv run python scripts/heimildin/cluster_claims.py curate filter M01
    uv run python scripts/heimildin/cluster_claims.py curate review M01
    uv run python scripts/heimildin/cluster_claims.py curate accept M01 --file exported.json
    uv run python scripts/heimildin/cluster_claims.py curate status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from config import WORK_DIR

CACHE_FILE = WORK_DIR / "embeddings_cache.npz"


def _load_all_claims() -> list[dict]:
    """Load enriched claims from both eras."""
    claims = []
    for era in ["esb", "ees"]:
        path = WORK_DIR / f"{era}_claims_enriched.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for c in data:
                c["era"] = era
            claims.extend(data)
    return claims


def _embed_claims(claims: list[dict]) -> np.ndarray:
    """Embed all claim summaries, with caching."""
    if CACHE_FILE.exists():
        cached = np.load(CACHE_FILE)
        cached_ids = list(cached["instance_ids"])
        current_ids = [c.get("instance_id", "") for c in claims]
        if cached_ids == current_ids:
            print(f"Using cached embeddings ({len(cached_ids)} claims)")
            return cached["embeddings"]

    print(f"Embedding {len(claims)} claim summaries...")
    from esbvaktin.ground_truth.operations import embed_texts

    texts = [c.get("claim_summary", "") for c in claims]
    embeddings = embed_texts(texts, batch_size=64)
    embeddings = np.array(embeddings, dtype=np.float32)

    # Cache
    instance_ids = np.array([c.get("instance_id", "") for c in claims])
    np.savez_compressed(CACHE_FILE, embeddings=embeddings, instance_ids=instance_ids)
    print(f"Cached embeddings to {CACHE_FILE}")

    return embeddings


def discover(min_cluster_size: int = 5, min_samples: int = 3) -> None:
    """Phase 1: Unsupervised clustering to discover natural meta-claim groups."""
    import umap
    from sklearn.cluster import HDBSCAN
    from sklearn.metrics.pairwise import cosine_distances

    claims = _load_all_claims()
    embeddings = _embed_claims(claims)

    # UMAP dimensionality reduction (1024 → 50) — critical for HDBSCAN performance
    print("\nReducing dimensions with UMAP (1024 → 50)...")
    reducer = umap.UMAP(
        n_components=50, metric="cosine", n_neighbors=30, min_dist=0.0, random_state=42
    )
    reduced = reducer.fit_transform(embeddings)

    print(f"Running HDBSCAN (min_cluster_size={min_cluster_size}, min_samples={min_samples})...")
    clusterer = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
    )
    labels = clusterer.fit_predict(reduced)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = (labels == -1).sum()
    print(
        f"Found {n_clusters} clusters, {n_noise} noise points ({n_noise * 100 / len(claims):.0f}%)"
    )

    # Build cluster info
    clusters = []
    for cluster_id in sorted(set(labels)):
        if cluster_id == -1:
            continue

        mask = labels == cluster_id
        indices = np.where(mask)[0]
        cluster_embeddings = embeddings[indices]

        # Find most central claim (closest to centroid)
        centroid = cluster_embeddings.mean(axis=0, keepdims=True)
        dists = cosine_distances(centroid, cluster_embeddings)[0]
        central_idx = indices[np.argmin(dists)]

        cluster_claims = [claims[i] for i in indices]
        esb_count = sum(1 for c in cluster_claims if c["era"] == "esb")
        ees_count = sum(1 for c in cluster_claims if c["era"] == "ees")

        # Topic distribution
        topics = {}
        for c in cluster_claims:
            t = c.get("topic", "other")
            topics[t] = topics.get(t, 0) + 1
        top_topic = max(topics, key=topics.get) if topics else "?"

        # Unique speakers
        speakers = sorted({c.get("speaker", "?") for c in cluster_claims})

        clusters.append(
            {
                "cluster_id": int(cluster_id),
                "size": len(indices),
                "esb_count": esb_count,
                "ees_count": ees_count,
                "representative": claims[central_idx].get("claim_summary", ""),
                "top_topic": top_topic,
                "topics": topics,
                "speakers": speakers,
                "claims": [
                    {
                        "instance_id": c.get("instance_id", ""),
                        "era": c["era"],
                        "summary": c.get("claim_summary", ""),
                        "speaker": c.get("speaker", "?"),
                        "topic": c.get("topic", "?"),
                    }
                    for c in cluster_claims
                ],
            }
        )

    # Sort by size descending
    clusters.sort(key=lambda c: c["size"], reverse=True)

    # Write full results
    out_file = WORK_DIR / "cluster_discovery.json"
    out_file.write_text(json.dumps(clusters, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print summary
    print(f"\n{'#':>3} {'Size':>5} {'ESB':>4} {'EES':>4} {'Topic':>15}  Representative claim")
    print("-" * 100)
    for i, cl in enumerate(clusters):
        print(
            f"{i + 1:3} {cl['size']:5} {cl['esb_count']:4} {cl['ees_count']:4} "
            f"{cl['top_topic']:>15}  {cl['representative'][:60]}"
        )

    print(f"\nFull results: {out_file}")
    print(f"Clusters: {len(clusters)}, Noise: {n_noise}/{len(claims)}")


def assign(threshold: float = 0.55) -> None:
    """Phase 2: Assign claims to user-curated meta-claims by cosine similarity."""
    from sklearn.metrics.pairwise import cosine_similarity

    meta_file = WORK_DIR / "meta_claims.json"
    if not meta_file.exists():
        print(f"No meta-claims defined yet. Create {meta_file} first.")
        print('Format: [{"id": "M01", "text": "...", "category": "..."}, ...]')
        sys.exit(1)

    meta_claims = json.loads(meta_file.read_text(encoding="utf-8"))
    print(f"Loaded {len(meta_claims)} meta-claims from {meta_file}")

    claims = _load_all_claims()
    claim_embeddings = _embed_claims(claims)

    # Embed meta-claims
    print(f"Embedding {len(meta_claims)} meta-claim texts...")
    from esbvaktin.ground_truth.operations import embed_texts

    meta_texts = [m["text"] for m in meta_claims]
    meta_embeddings = np.array(embed_texts(meta_texts, batch_size=32), dtype=np.float32)

    # Compute similarity matrix: (n_claims, n_meta)
    sims = cosine_similarity(claim_embeddings, meta_embeddings)

    # Assign each claim to nearest meta-claim
    best_meta_idx = sims.argmax(axis=1)
    best_sim = sims.max(axis=1)

    assigned = 0
    unassigned = 0
    for i, claim in enumerate(claims):
        if best_sim[i] >= threshold:
            claim["meta_claim_id"] = meta_claims[best_meta_idx[i]]["id"]
            claim["meta_claim_sim"] = round(float(best_sim[i]), 3)
            assigned += 1
        else:
            claim["meta_claim_id"] = "UNASSIGNED"
            claim["meta_claim_sim"] = round(float(best_sim[i]), 3)
            unassigned += 1

    # Write enriched claims per era
    for era in ["esb", "ees"]:
        era_claims = [c for c in claims if c["era"] == era]
        out = WORK_DIR / f"{era}_meta_assigned.json"
        out.write_text(json.dumps(era_claims, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {era.upper()}: {out}")

    # Print frequency table
    freq: dict[str, dict] = {}
    for claim in claims:
        mid = claim["meta_claim_id"]
        era = claim["era"]
        freq.setdefault(mid, {"esb": 0, "ees": 0, "text": ""})
        freq[mid][era] += 1

    for m in meta_claims:
        if m["id"] in freq:
            freq[m["id"]]["text"] = m["text"]
            freq[m["id"]]["category"] = m.get("category", "")

    print(f"\n{'ID':>5} {'ESB':>4} {'EES':>4} {'Cat':>12}  Meta-claim")
    print("-" * 90)
    for mid, f in sorted(freq.items(), key=lambda x: -(x[1]["esb"] + x[1]["ees"])):
        if mid == "UNASSIGNED":
            continue
        print(f"{mid:>5} {f['esb']:4} {f['ees']:4} {f.get('category', ''):>12}  {f['text'][:55]}")

    if "UNASSIGNED" in freq:
        u = freq["UNASSIGNED"]
        print(f"\nUnassigned: {u['esb']} ESB + {u['ees']} EES = {u['esb'] + u['ees']} total")

    print(f"\nAssigned: {assigned}, Unassigned: {unassigned} (threshold={threshold})")


def seed(top_n: int = 40) -> None:
    """Generate a starter meta_claims.json from the top N clusters."""
    discovery = WORK_DIR / "cluster_discovery.json"
    if not discovery.exists():
        print("Run 'discover' first.")
        sys.exit(1)

    clusters = json.loads(discovery.read_text(encoding="utf-8"))
    # Already sorted by size descending from discover()
    selected = clusters[:top_n]

    meta_claims = []
    for i, cl in enumerate(selected, start=1):
        meta_claims.append(
            {
                "id": f"M{i:02d}",
                "text": cl["representative"],
                "category": cl["top_topic"],
                "source_cluster": cl["cluster_id"],
                "cluster_size": cl["size"],
                "esb_count": cl["esb_count"],
                "ees_count": cl["ees_count"],
            }
        )

    out = WORK_DIR / "meta_claims_seed.json"
    out.write_text(json.dumps(meta_claims, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Generated {len(meta_claims)} seed meta-claims → {out}")
    print("\nTo use: review in cluster_review.html, edit as needed, then:")
    print(f"  cp {out} {WORK_DIR / 'meta_claims.json'}")
    print(f"\n{'ID':>4} {'Size':>5} {'ESB':>4} {'EES':>4} {'Category':>15}  Text")
    print("-" * 100)
    for m in meta_claims:
        print(
            f"{m['id']:>4} {m['cluster_size']:5} {m['esb_count']:4} {m['ees_count']:4} "
            f"{m['category']:>15}  {m['text'][:55]}"
        )


def status() -> None:
    """Show current state of clustering."""
    if CACHE_FILE.exists():
        cached = np.load(CACHE_FILE)
        print(f"Embeddings cached: {len(cached['instance_ids'])} claims")
    else:
        print("No embeddings cached yet.")

    discovery = WORK_DIR / "cluster_discovery.json"
    if discovery.exists():
        clusters = json.loads(discovery.read_text())
        total = sum(c["size"] for c in clusters)
        print(f"Discovery: {len(clusters)} clusters, {total} claims assigned")

    meta_file = WORK_DIR / "meta_claims.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        print(f"Meta-claims defined: {len(meta)}")

    for era in ["esb", "ees"]:
        assigned = WORK_DIR / f"{era}_meta_assigned.json"
        if assigned.exists():
            data = json.loads(assigned.read_text())
            n_assigned = sum(1 for c in data if c.get("meta_claim_id") != "UNASSIGNED")
            print(f"  {era.upper()}: {n_assigned}/{len(data)} assigned to meta-claims")


CURATE_DIR = WORK_DIR / "meta_claims"
REGISTRY_FILE = CURATE_DIR / "registry.json"


def _load_registry() -> list[dict]:
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    return []


def _save_registry(registry: list[dict]) -> None:
    CURATE_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_registry(claim_id: str, updates: dict) -> None:
    registry = _load_registry()
    for entry in registry:
        if entry["id"] == claim_id:
            entry.update(updates)
            _save_registry(registry)
            return
    # New entry
    registry.append({"id": claim_id, **updates})
    _save_registry(registry)


def _claim_dir(claim_id: str) -> Path:
    d = CURATE_DIR / claim_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def curate_init(
    claim_id: str,
    text: str,
    category: str,
    threshold: float,
    keywords: list[str] | None = None,
) -> None:
    """Create a claim folder and compute embedding-ranked candidates.

    When keywords are provided, uses hybrid selection: keyword filter for recall,
    embedding for ranking. Without keywords, uses pure embedding similarity.
    """
    from sklearn.metrics.pairwise import cosine_similarity

    claim_dir = _claim_dir(claim_id)

    claims = _load_all_claims()
    embeddings = _embed_claims(claims)

    print("Embedding meta-claim text...")
    from esbvaktin.ground_truth.operations import embed_texts

    meta_emb = np.array(embed_texts([text], batch_size=1), dtype=np.float32)
    sims = cosine_similarity(meta_emb, embeddings)[0]

    # Save claim definition
    claim_data = {
        "id": claim_id,
        "text": text,
        "category": category,
        "threshold": threshold,
        "keywords": keywords or [],
        "method": "keyword_embedding" if keywords else "embedding",
        "exemplars": [],
        "wording_history": [],
    }

    # Record initial wording stats
    for t in [0.60, 0.55, 0.50]:
        n = int((sims >= t).sum())
        esb = int(sum(1 for j, s in enumerate(sims) if s >= t and claims[j]["era"] == "esb"))
        ees = n - esb
        if t == 0.55:
            claim_data["wording_history"].append(
                {
                    "text": text,
                    "at_055": n,
                    "esb": esb,
                    "ees": ees,
                }
            )

    (claim_dir / "claim.json").write_text(
        json.dumps(claim_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Build candidates — keyword pre-filter if specified
    if keywords:
        kw_lower = [k.lower() for k in keywords]

    candidates = []
    for i, (sim, claim) in enumerate(zip(sims, claims)):
        if keywords:
            # Hybrid: keyword match in summary or quote, then rank by embedding
            text_to_search = (
                claim.get("claim_summary", "") + " " + claim.get("exact_quote", "")
            ).lower()
            if not any(kw in text_to_search for kw in kw_lower):
                continue
            # Accept all keyword matches (embedding provides ranking only)
            candidates.append(
                {
                    "instance_id": claim.get("instance_id", ""),
                    "similarity": round(float(sim), 4),
                    "era": claim["era"],
                    "speaker": claim.get("speaker", "?"),
                    "party": claim.get("party", "?"),
                    "date": claim.get("date", "?"),
                    "topic": claim.get("topic", "?"),
                    "stance": claim.get("stance", "?"),
                    "claim_summary": claim.get("claim_summary", ""),
                    "exact_quote": claim.get("exact_quote", ""),
                    "speech_url": claim.get("speech_url", ""),
                }
            )
        elif sim >= threshold:
            candidates.append(
                {
                    "instance_id": claim.get("instance_id", ""),
                    "similarity": round(float(sim), 4),
                    "era": claim["era"],
                    "speaker": claim.get("speaker", "?"),
                    "party": claim.get("party", "?"),
                    "date": claim.get("date", "?"),
                    "topic": claim.get("topic", "?"),
                    "stance": claim.get("stance", "?"),
                    "claim_summary": claim.get("claim_summary", ""),
                    "exact_quote": claim.get("exact_quote", ""),
                    "speech_url": claim.get("speech_url", ""),
                }
            )

    candidates.sort(key=lambda c: -c["similarity"])
    (claim_dir / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    esb = sum(1 for c in candidates if c["era"] == "esb")
    ees = sum(1 for c in candidates if c["era"] == "ees")
    print(f"\n{claim_id}: {len(candidates)} candidates at ≥{threshold} ({esb} ESB, {ees} EES)")
    print(f"  → {claim_dir}/")

    # Distribution
    print(f"\n{'Threshold':>10} {'Total':>6} {'ESB':>5} {'EES':>5}")
    print("-" * 30)
    for t in [0.65, 0.60, 0.55, 0.50, 0.45]:
        n = sum(1 for c in candidates if c["similarity"] >= t)
        e = sum(1 for c in candidates if c["similarity"] >= t and c["era"] == "esb")
        print(f"    ≥{t:.2f} {n:6} {e:5} {n - e:5}")

    _update_registry(
        claim_id,
        {
            "text": text,
            "category": category,
            "status": "candidates",
            "count": len(candidates),
        },
    )


def curate_compare(claim_id: str, texts: list[str]) -> None:
    """Test alternative wordings against the candidate set."""
    from sklearn.metrics.pairwise import cosine_similarity

    from esbvaktin.ground_truth.operations import embed_texts

    claim_dir = _claim_dir(claim_id)
    claim_data = json.loads((claim_dir / "claim.json").read_text(encoding="utf-8"))

    claims = _load_all_claims()
    embeddings = _embed_claims(claims)

    # Include current text for comparison
    all_texts = [claim_data["text"]] + texts
    all_embs = np.array(embed_texts(all_texts, batch_size=8), dtype=np.float32)

    print(f"{'#':>2} {'≥0.60':>6} {'≥0.55':>6} {'≥0.50':>6} {'ESB≥.55':>8} {'EES≥.55':>8}  Text")
    print("-" * 110)

    for i, (text, emb) in enumerate(zip(all_texts, all_embs)):
        sims = cosine_similarity(emb.reshape(1, -1), embeddings)[0]
        n60 = int((sims >= 0.60).sum())
        n55 = int((sims >= 0.55).sum())
        n50 = int((sims >= 0.50).sum())
        esb55 = int(sum(1 for j, s in enumerate(sims) if s >= 0.55 and claims[j]["era"] == "esb"))
        ees55 = n55 - esb55
        tag = " ◄ current" if i == 0 else ""
        print(f"{i:2} {n60:6} {n55:6} {n50:6} {esb55:8} {ees55:8}  {text[:60]}{tag}")

        # Record in wording history (skip current)
        if i > 0:
            claim_data["wording_history"].append(
                {
                    "text": text,
                    "at_055": n55,
                    "esb": esb55,
                    "ees": ees55,
                }
            )

    (claim_dir / "claim.json").write_text(
        json.dumps(claim_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def curate_exemplars(claim_id: str, quotes: list[str]) -> None:
    """Add exemplar quotes to a claim definition."""
    claim_dir = _claim_dir(claim_id)
    claim_data = json.loads((claim_dir / "claim.json").read_text(encoding="utf-8"))
    claim_data["exemplars"] = quotes
    (claim_dir / "claim.json").write_text(
        json.dumps(claim_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved {len(quotes)} exemplars to {claim_id}/claim.json")


def curate_filter(claim_id: str) -> None:
    """Generate agent context and write it for LLM filtering."""
    claim_dir = _claim_dir(claim_id)
    claim_data = json.loads((claim_dir / "claim.json").read_text(encoding="utf-8"))
    candidates = json.loads((claim_dir / "candidates.json").read_text(encoding="utf-8"))

    meta_text = claim_data["text"]
    exemplars = claim_data.get("exemplars", [])

    lines = [
        "# Meta-claim filtering task",
        "",
        f'## Meta-claim: "{meta_text}"',
        "",
        "## What this meta-claim captures",
        "",
        "Any argument that EU/EEA membership threatens Iceland in the way described by the meta-claim.",
        "Accept claims that express the same core argument, even if worded differently.",
        "",
    ]

    if exemplars:
        lines.append("## Exemplar quotes (ACCEPT — these define what belongs)")
        lines.append("")
        for q in exemplars:
            lines.append(f"> {q}")
            lines.append("")

    lines.extend(
        [
            "## What to REJECT",
            "",
            "ONLY reject claims that are clearly NOT about this topic:",
            "- Claims arguing the OPPOSITE of the meta-claim",
            "- Claims about a fundamentally different topic",
            "- Pure procedural/debate process claims",
            "",
            "When in doubt, ACCEPT. Better to include a borderline claim than miss a real one.",
            "",
            f"## Candidates to classify ({len(candidates)} total)",
            "",
            "Output a JSON array:",
            "```json",
            '[{"instance_id": "...", "verdict": "accept"|"reject", "reason": "brief reason"}]',
            "```",
            "",
        ]
    )

    for c in candidates:
        lines.append(
            f"### {c['instance_id']} (sim={c['similarity']:.3f}, "
            f"{c['era'].upper()}, {c['speaker']})"
        )
        lines.append(f"**Summary:** {c['claim_summary']}")
        quote = c.get("exact_quote", "")
        if quote:
            lines.append(f"**Quote:** {quote[:200]}")
        lines.append("")

    context = "\n".join(lines)
    context_file = claim_dir / "_context_filter.md"
    context_file.write_text(context, encoding="utf-8")
    print(f"Context file: {context_file} ({len(context) // 1024}KB, {len(candidates)} candidates)")
    print(f"\nRun the agent, then place verdicts at: {claim_dir / 'agent_verdicts.json'}")
    print(f"Or run: curate review {claim_id} (verdicts are optional)")

    # Don't downgrade if already user-accepted
    registry = _load_registry()
    current_status = next((e.get("status") for e in registry if e["id"] == claim_id), None)
    if current_status != "accepted":
        _update_registry(claim_id, {"status": "filtered"})


def curate_review(claim_id: str) -> None:
    """Generate the interactive HTML review for a claim."""
    from generate_meta_review import generate_review_html

    claim_dir = _claim_dir(claim_id)
    generate_review_html(claim_dir, claim_id)


def curate_accept(claim_id: str, file_path: str) -> None:
    """Import user review from HTML export."""

    claim_dir = _claim_dir(claim_id)
    src = Path(file_path).expanduser()
    if not src.exists():
        print(f"File not found: {src}")
        sys.exit(1)

    data = json.loads(src.read_text(encoding="utf-8"))
    dest = claim_dir / "user_review.json"
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    count = data.get("accepted_count", len(data.get("accepted", [])))
    excluded = len(data.get("excluded_by_user", []))
    print(f"Imported: {count} accepted, {excluded} user-excluded → {dest}")

    _update_registry(claim_id, {"status": "accepted", "count": count})


def curate_status() -> None:
    """Show all curated claims and their progress."""
    registry = _load_registry()
    if not registry:
        print("No curated claims yet. Run: curate init M01 --text '...'")
        return

    print(f"\n{'ID':>4} {'Status':>12} {'Count':>6} {'Category':>15}  Text")
    print("-" * 90)
    for entry in registry:
        print(
            f"{entry['id']:>4} {entry.get('status', '?'):>12} "
            f"{entry.get('count', '?'):>6} "
            f"{entry.get('category', '?'):>15}  {entry.get('text', '?')[:45]}"
        )

    # Summary
    by_status = {}
    for e in registry:
        s = e.get("status", "?")
        by_status[s] = by_status.get(s, 0) + 1
    parts = [f"{v} {k}" for k, v in sorted(by_status.items())]
    print(f"\n{len(registry)} claims: {', '.join(parts)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Embedding-based meta-claim clustering")
    sub = parser.add_subparsers(dest="command")

    d = sub.add_parser("discover", help="Unsupervised cluster discovery")
    d.add_argument("--min-cluster", type=int, default=5, help="HDBSCAN min_cluster_size")
    d.add_argument("--min-samples", type=int, default=3, help="HDBSCAN min_samples")

    a = sub.add_parser("assign", help="Assign claims to curated meta-claims")
    a.add_argument("--threshold", type=float, default=0.55, help="Minimum cosine similarity")

    s = sub.add_parser("seed", help="Generate starter meta_claims from top clusters")
    s.add_argument("--top", type=int, default=40, help="Number of top clusters to seed")

    sub.add_parser("status", help="Show clustering status")

    # Curate subcommands
    c = sub.add_parser("curate", help="Per-claim curation workflow")
    csub = c.add_subparsers(dest="curate_command")

    ci = csub.add_parser("init", help="Create claim and rank candidates")
    ci.add_argument("claim_id", help="Claim ID (e.g. M01)")
    ci.add_argument("--text", required=True, help="Meta-claim text")
    ci.add_argument("--category", default="other", help="Topic category")
    ci.add_argument("--threshold", type=float, default=0.50, help="Min similarity")
    ci.add_argument(
        "--keywords",
        nargs="+",
        default=None,
        help="Keyword stems for hybrid selection (keyword filter + embedding rank)",
    )

    cc = csub.add_parser("compare", help="Test alternative wordings")
    cc.add_argument("claim_id", help="Claim ID")
    cc.add_argument("--text", action="append", required=True, help="Candidate wording(s)")

    ce = csub.add_parser("exemplars", help="Add exemplar quotes")
    ce.add_argument("claim_id", help="Claim ID")
    ce.add_argument("--quotes-file", required=True, help="File with one quote per paragraph")

    cf = csub.add_parser("filter", help="Generate agent filtering context")
    cf.add_argument("claim_id", help="Claim ID")

    cr = csub.add_parser("review", help="Generate review HTML")
    cr.add_argument("claim_id", help="Claim ID")

    ca = csub.add_parser("accept", help="Import user review from HTML export")
    ca.add_argument("claim_id", help="Claim ID")
    ca.add_argument("--file", required=True, help="Path to exported JSON")

    csub.add_parser("status", help="Show all curated claims")

    args = parser.parse_args()

    if args.command == "discover":
        discover(min_cluster_size=args.min_cluster, min_samples=args.min_samples)
    elif args.command == "assign":
        assign(threshold=args.threshold)
    elif args.command == "seed":
        seed(top_n=args.top)
    elif args.command == "status":
        status()
    elif args.command == "curate":
        if args.curate_command == "init":
            curate_init(
                args.claim_id, args.text, args.category, args.threshold, keywords=args.keywords
            )
        elif args.curate_command == "compare":
            curate_compare(args.claim_id, args.text)
        elif args.curate_command == "exemplars":
            quotes = Path(args.quotes_file).read_text(encoding="utf-8").strip().split("\n\n")
            curate_exemplars(args.claim_id, [q.strip() for q in quotes if q.strip()])
        elif args.curate_command == "filter":
            curate_filter(args.claim_id)
        elif args.curate_command == "review":
            curate_review(args.claim_id)
        elif args.curate_command == "accept":
            curate_accept(args.claim_id, args.file)
        elif args.curate_command == "status":
            curate_status()
        else:
            c.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
