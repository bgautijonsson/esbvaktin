"""Canonicalise extracted claims into grouped canonical claims.

Groups similar claim instances into canonical claims using LLM-based
clustering. Works per-topic to keep context manageable.

Uses stable instance_id ("{speech_id}:{n}") instead of positional indices,
so adding/removing speeches doesn't invalidate canonical assignments.

Usage:
    uv run python scripts/heimildin/canonicalise.py prepare [--era esb]
    uv run python scripts/heimildin/canonicalise.py parse [--era esb]
    uv run python scripts/heimildin/canonicalise.py status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import WORK_DIR

CANONICALISE_DIR = WORK_DIR / "canonicalise"

# ---------------------------------------------------------------------------
# Context template for LLM clustering
# ---------------------------------------------------------------------------

CLUSTERING_INSTRUCTIONS = """\
# Claim Canonicalisation — Heimildin Project

## Task

You are given a list of claim summaries extracted from Alþingi speeches about
Iceland's EU membership debate. Each claim has a stable ID (format: speech_id:n).

Your job: group claims that express **the same core argument** into canonical
clusters. Two claims belong in the same cluster if a reader would recognise
them as "the same point being made."

## Grouping principles

- **Same argument, different words** → same cluster
  - "ESB-aðild felur í sér fullveldistap" and "Framsal valds til Brussel" = same
- **Same topic, different argument** → different clusters
  - "ESB-samningur er landssérstakur" vs "Ísland er 80% inni í ESB vegna EES" = different
- **Opposite stances on same issue** → different clusters
  - "EES virkar vel" (anti-EU) vs "EES er ófullnægjandi" (pro-EU) = different
- When in doubt, **keep clusters separate** — it's better to have too many
  canonical claims than to merge genuinely different arguments
- **A claim can only belong to ONE cluster** — never assign a claim to multiple clusters

## Output format

Write a JSON array where each element is one canonical claim:

```json
[
    {{
        "canonical_id": "SOV-01",
        "canonical_text": "Aðild að ESB felur í sér fullveldistap og framsal ákvörðunarvalds til Brussel.",
        "stance": "anti_eu",
        "instance_ids": ["rad20260309T171000:3", "rad20260309T175023:7"]
    }}
]
```

### Rules

- `canonical_id`: `TOPIC_PREFIX-NN` (e.g. `DEM-01`, `SOV-01`, `EEA-01`)
- `canonical_text`: A clean, neutral summary of the core argument (Icelandic, 1 sentence)
- `stance`: The dominant stance of claims in this cluster (pro_eu / anti_eu / neutral)
- `instance_ids`: List of claim IDs that belong to this cluster
- **Every claim ID must appear in EXACTLY ONE cluster — no duplicates**
- Use correct Icelandic Unicode (þ, ð, á, é, í, ó, ú, ý, æ, ö)
- NEVER use „…" quotes in JSON — use «…» or escaped \\"…\\"

## Topic prefix mapping

fisheries→FIS, trade→TRA, sovereignty→SOV, eea_eu_law→EEA,
agriculture→AGR, precedents→PRE, currency→CUR, labour→LAB,
energy→ENE, housing→HOU, defence→DEF, democracy→DEM,
environment→ENV, other→OTH

## Claims to cluster

**Topic: {topic}** ({count} claims)

"""


def prepare(era: str) -> None:
    """Group claims by topic and write clustering context files."""
    raw_file = WORK_DIR / f"{era}_claims_raw.json"
    if not raw_file.exists():
        print(f"No raw claims found. Run 'parse --era {era}' first.")
        sys.exit(1)

    claims = json.loads(raw_file.read_text(encoding="utf-8"))
    print(f"Loaded {len(claims)} claims from {raw_file}")

    # Group by topic
    by_topic: dict[str, list[dict]] = {}
    for claim in claims:
        topic = claim.get("topic", "other")
        by_topic.setdefault(topic, []).append(claim)

    out_dir = CANONICALISE_DIR / era
    out_dir.mkdir(parents=True, exist_ok=True)

    prepared = 0
    for topic, topic_claims in sorted(by_topic.items(), key=lambda x: -len(x[1])):
        if len(topic_claims) < 2:
            print(f"  skip {topic} ({len(topic_claims)} claim — no clustering needed)")
            continue

        output_file = out_dir / f"{topic}_canonical.json"
        if output_file.exists():
            print(f"  skip {topic} (already canonicalised)")
            continue

        # Build context using stable instance_ids
        context = CLUSTERING_INSTRUCTIONS.format(
            topic=topic, count=len(topic_claims)
        )

        for claim in topic_claims:
            iid = claim.get("instance_id", "?")
            stance_tag = claim.get("stance", "?")
            speaker = claim.get("speaker", "?")
            context += (
                f"[{iid}] ({stance_tag}, {speaker}): "
                f"{claim['claim_summary']}\n"
            )

        context_file = out_dir / f"_context_{topic}.md"
        context_file.write_text(context, encoding="utf-8")

        prepared += 1
        print(f"  prepared {topic}: {len(topic_claims)} claims → {context_file.name}")

    print(f"\nPrepared {prepared} topics for canonicalisation in {out_dir}/")
    print("Run LLM agent on each _context_{topic}.md → {topic}_canonical.json")


def parse(era: str) -> None:
    """Parse canonical clustering outputs and build the full canonical mapping."""
    canon_dir = CANONICALISE_DIR / era
    if not canon_dir.exists():
        print(f"No canonicalisation directory for era '{era}'")
        sys.exit(1)

    raw_file = WORK_DIR / f"{era}_claims_raw.json"
    claims = json.loads(raw_file.read_text(encoding="utf-8"))

    # Build instance_id → claim index lookup
    id_to_idx: dict[str, int] = {}
    for i, claim in enumerate(claims):
        iid = claim.get("instance_id")
        if iid:
            id_to_idx[iid] = i

    canonical_claims = []
    instance_map: dict[str, str] = {}  # instance_id → canonical_id
    errors = []
    duplicates = 0

    for canon_file in sorted(canon_dir.glob("*_canonical.json")):
        raw = canon_file.read_text(encoding="utf-8")
        # Sanitise Icelandic quotes
        raw = raw.replace("\u201e", '"').replace("\u201c", '"')
        if raw.strip().startswith("```"):
            lines = raw.strip().split("\n")
            raw = "\n".join(line for line in lines if not line.strip().startswith("```"))

        try:
            groups = json.loads(raw)
        except json.JSONDecodeError as e:
            errors.append(f"JSON error in {canon_file.name}: {e}")
            continue

        if not isinstance(groups, list):
            errors.append(f"Expected list in {canon_file.name}")
            continue

        for group in groups:
            cid = group.get("canonical_id", "?")
            # Support both "instance_ids" (new) and "instance_indices" (old)
            ids = group.get("instance_ids", group.get("instance_indices", []))

            # Deduplicate: skip IDs already assigned (P3.3)
            clean_ids = []
            for iid in ids:
                iid_str = str(iid)
                if iid_str in instance_map:
                    duplicates += 1
                    continue
                clean_ids.append(iid_str)
                instance_map[iid_str] = cid

            canonical_claims.append({
                "canonical_id": cid,
                "canonical_text": group.get("canonical_text", ""),
                "stance": group.get("stance", "neutral"),
                "instance_count": len(clean_ids),
                "instance_ids": clean_ids,
            })

    # Handle unmapped claims (single-instance topics, or missed by clustering)
    all_ids = {c.get("instance_id") for c in claims if c.get("instance_id")}
    unmapped = all_ids - set(instance_map.keys())
    if unmapped:
        single_topics = set()
        for iid in unmapped:
            idx = id_to_idx.get(iid)
            if idx is not None:
                single_topics.add(claims[idx].get("topic", "other"))
        if single_topics:
            print(f"Note: {len(unmapped)} unmapped claims "
                  f"({', '.join(single_topics)}) — creating singleton canonicals")

        for iid in sorted(unmapped):
            idx = id_to_idx.get(iid)
            if idx is None:
                continue
            claim = claims[idx]
            topic = claim.get("topic", "other")
            prefix = _topic_prefix(topic)
            # Use speech_id fragment for readable singleton IDs
            short_id = iid.split(":")[0][-6:] if ":" in iid else iid[-6:]
            cid = f"{prefix}-S{short_id}"
            canonical_claims.append({
                "canonical_id": cid,
                "canonical_text": claim.get("claim_summary", ""),
                "stance": claim.get("stance", "neutral"),
                "instance_count": 1,
                "instance_ids": [iid],
            })
            instance_map[iid] = cid

    # Enrich raw claims with canonical_id
    for claim in claims:
        iid = claim.get("instance_id")
        claim["canonical_id"] = instance_map.get(iid, "UNMAPPED") if iid else "UNMAPPED"

    # Sort canonical claims by instance count descending
    canonical_claims.sort(key=lambda c: c["instance_count"], reverse=True)

    # Write outputs
    canonical_file = WORK_DIR / f"{era}_canonical.json"
    canonical_file.write_text(
        json.dumps(canonical_claims, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    enriched_file = WORK_DIR / f"{era}_claims_enriched.json"
    enriched_file.write_text(
        json.dumps(claims, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Canonical claims: {len(canonical_claims)}")
    print(f"  Output: {canonical_file}")
    print(f"  Enriched claims: {enriched_file}")
    if duplicates:
        print(f"  Fixed {duplicates} double-assignments (kept first)")

    # Show top canonical claims by frequency
    print(f"\nTop 20 canonical claims:")
    for cc in canonical_claims[:20]:
        print(f"  {cc['canonical_id']:8} ({cc['instance_count']:2}×) "
              f"[{cc['stance']:8}] {cc['canonical_text'][:70]}")

    if errors:
        print(f"\n{len(errors)} errors:")
        for err in errors:
            print(f"  - {err}")


def status() -> None:
    """Show canonicalisation progress."""
    for era in ["esb", "ees"]:
        canon_dir = CANONICALISE_DIR / era
        if not canon_dir.exists():
            continue

        contexts = list(canon_dir.glob("_context_*.md"))
        outputs = list(canon_dir.glob("*_canonical.json"))

        print(f"\n## {era.upper()} era")
        print(f"  Topics prepared: {len(contexts)}")
        print(f"  Topics canonicalised: {len(outputs)}")

        for ctx in sorted(contexts):
            topic = ctx.stem.replace("_context_", "")
            done = (canon_dir / f"{topic}_canonical.json").exists()
            status_str = "done" if done else "pending"
            print(f"    {topic}: {status_str}")


_TOPIC_PREFIXES = {
    "fisheries": "FIS", "trade": "TRA", "sovereignty": "SOV",
    "eea_eu_law": "EEA", "agriculture": "AGR", "precedents": "PRE",
    "currency": "CUR", "labour": "LAB", "energy": "ENE",
    "housing": "HOU", "defence": "DEF", "democracy": "DEM",
    "environment": "ENV", "other": "OTH",
}


def _topic_prefix(topic: str) -> str:
    return _TOPIC_PREFIXES.get(topic, "OTH")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Canonicalise extracted claims"
    )
    sub = parser.add_subparsers(dest="command")

    prep = sub.add_parser("prepare", help="Group claims and write clustering contexts")
    prep.add_argument("--era", default="esb", choices=["esb", "ees"])

    p = sub.add_parser("parse", help="Parse clustering output into canonical mapping")
    p.add_argument("--era", default="esb", choices=["esb", "ees"])

    sub.add_parser("status", help="Show canonicalisation progress")

    args = parser.parse_args()

    if args.command == "prepare":
        prepare(args.era)
    elif args.command == "parse":
        parse(args.era)
    elif args.command == "status":
        status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
