#!/usr/bin/env python3
"""Re-assess unverifiable claims that now have matching evidence.

Retrieves evidence for each unverifiable claim, writes context files for
subagent assessment, then parses subagent output and updates the DB.

Usage:
    # Step 1: Prepare context files (batches of ~10 claims each)
    uv run python scripts/reassess_claims.py prepare

    # Step 2: Run subagent assessment (Claude Code reads each batch context
    #         and writes _assessments_batch_N.json)
    # → see printed instructions after prepare

    # Step 3: Parse subagent output and update DB
    uv run python scripts/reassess_claims.py update

    # Check status
    uv run python scripts/reassess_claims.py status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORK_DIR = Path("data/reassessment")
_BLOCKS_PATH = Path(".claude/skills/icelandic-shared/assessment-blocks.md")
SIMILARITY_THRESHOLD = 0.45
BATCH_SIZE = 10


def _get_unverifiable_claims_with_evidence(conn):
    """Fetch unverifiable claims and retrieve matching evidence for each."""
    from esbvaktin.ground_truth.operations import search_evidence

    rows = conn.execute(
        "SELECT id, canonical_text_is, canonical_text_en, category, claim_slug "
        "FROM claims WHERE verdict = 'unverifiable' "
        "ORDER BY category, claim_slug"
    ).fetchall()

    assessable = []
    for row in rows:
        claim_id, text_is, text_en, category, slug = row
        query = text_is or text_en
        if not query:
            continue

        # Dual search: Icelandic + English
        results = search_evidence(query, top_k=8, conn=conn)
        if text_en and text_en != text_is:
            results_en = search_evidence(text_en, top_k=8, conn=conn)
            seen_ids = {r.evidence_id for r in results}
            for r in results_en:
                if r.evidence_id not in seen_ids:
                    results.append(r)
                    seen_ids.add(r.evidence_id)

        # Filter by threshold, take top 8
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:8]

        if strong:
            assessable.append({
                "claim_id": claim_id,
                "text_is": text_is,
                "text_en": text_en,
                "category": category,
                "slug": slug,
                "evidence": [
                    {
                        "evidence_id": r.evidence_id,
                        "statement": r.statement,
                        "similarity": round(r.similarity, 3),
                        "source_name": r.source_name,
                        "source_url": r.source_url,
                        "caveats": r.caveats,
                    }
                    for r in strong
                ],
            })

    return assessable


def _write_batch_context(batch: list[dict], batch_num: int) -> Path:
    """Write a context file for a batch of claims to be assessed by a subagent."""
    path = WORK_DIR / f"_context_batch_{batch_num}.md"
    lines = [
        "# Endurmat fullyrðinga — Lota {}\n".format(batch_num),
        "Þú ert staðreyndaprófari fyrir ESBvaktin.is, óháðan vettvang um",
        "þjóðaratkvæðagreiðslu Íslands um ESB-aðild (29. ágúst 2026).",
        "Þú metur fullyrðingar jafnt hvort sem þær eru ESB-jákvæðar eða ESB-neikvæðar.",
        "",
        "Þessar fullyrðingar voru áður flokkaðar sem **óstaðfestanlegar** (unverifiable)",
        "vegna þess að heimildir skorti. Nú eru nýjar heimildir komnar í gagnagrunninn.",
        "Endurmettu hverja fullyrðingu í ljósi heimildanna hér að neðan.",
        "",
    ]

    for i, claim in enumerate(batch, 1):
        lines.append(f"## Fullyrðing {i} (claim_id: {claim['claim_id']})")
        lines.append("")
        lines.append(f"**Íslenskur texti:** {claim['text_is']}")
        if claim["text_en"]:
            lines.append(f"**Enskur texti:** {claim['text_en']}")
        lines.append(f"**Flokkur:** {claim['category']}")
        lines.append("")
        lines.append("**Heimildir úr staðreyndagrunni:**")
        lines.append("")
        for ev in claim["evidence"]:
            lines.append(f"- **{ev['evidence_id']}** (líkindi: {ev['similarity']})")
            lines.append(f"  {ev['statement']}")
            lines.append(f"  *Heimild: {ev['source_name']}*")
            if ev.get("caveats"):
                lines.append(f"  Fyrirvarar: {ev['caveats']}")
            lines.append("")

    # Output format
    lines.extend([
        "## Úttakssnið",
        "",
        f"Skrifaðu JSON-fylki í `_assessments_batch_{batch_num}.json` (hrátt JSON, engin markdown-umbúðir).",
        "Skrifaðu `explanation_is` og `missing_context_is` á **íslensku**.",
        "Hvert atriði:",
        "",
        "```json",
        "{",
        '  "claim_id": 123,',
        '  "verdict": "supported | partially_supported | unsupported | misleading | unverifiable",',
        '  "explanation_is": "2-3 setningar á íslensku sem útskýra matið með tilvísun í heimildir",',
        '  "supporting_evidence": ["EVIDENCE-ID-001"],',
        '  "contradicting_evidence": [],',
        '  "missing_context_is": "mikilvægt samhengi á íslensku, eða null",',
        '  "confidence": 0.85',
        "}",
        "```",
        "",
        "## Meginreglur",
        "",
        "- **Óhlutdrægni**: metið ESB-jákvæðar og ESB-neikvæðar fullyrðingar jafnt",
        "- **Heimildum háð**: sérhvert mat VERÐUR að vitna í tilteknar evidence_id úr heimildum hér að ofan",
        "- **Fyrirvarar skipta máli**: komið á framfæri fyrirvörum úr heimildum — þeir geta haft mikla þýðingu",
        "- **Auðmýkt**: ef heimildir duga ekki til, notið áfram `unverifiable` — ekki giska",
        "- **Pólitískar fullyrðingar**: fullyrðingar um afstöðu flokka eða ákveðnar yfirlýsingar stjórnmálamanna "
        "verða einungis merktar `supported` ef heimild staðfestir beint — almennar upplýsingar um flokk duga ekki",
        "- **Tölulegar fullyrðingar**: ef heimildir sýna nálægar en ekki nákvæmlega sömu tölur, notið `partially_supported`",
        '- JSON-\u00f6ryggi: noti\u00f0 \\\\" fyrir g\u00e6salappir \u00ed JSON-strengjum, ekki \u201e\u2026\u201c',
    ])

    # Append Icelandic quality blocks
    if _BLOCKS_PATH.exists():
        lines.append("")
        lines.append(_BLOCKS_PATH.read_text(encoding="utf-8"))

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def prepare():
    """Prepare context files for subagent re-assessment."""
    from esbvaktin.ground_truth.operations import get_connection

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    print("Retrieving evidence for unverifiable claims...")
    assessable = _get_unverifiable_claims_with_evidence(conn)
    conn.close()

    print(f"Found {len(assessable)} assessable claims")

    # Split into batches
    batches = [
        assessable[i : i + BATCH_SIZE]
        for i in range(0, len(assessable), BATCH_SIZE)
    ]

    # Write batch context files and a manifest
    manifest = []
    for batch_num, batch in enumerate(batches, 1):
        path = _write_batch_context(batch, batch_num)
        manifest.append({
            "batch": batch_num,
            "context_file": str(path),
            "claims": [c["claim_id"] for c in batch],
            "slugs": [c["slug"] for c in batch],
        })
        print(f"  Batch {batch_num}: {len(batch)} claims → {path}")

    # Write manifest
    manifest_path = WORK_DIR / "_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write flat claims data for update step
    claims_path = WORK_DIR / "_claims_data.json"
    claims_path.write_text(
        json.dumps(assessable, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nManifest: {manifest_path}")
    print(f"Claims data: {claims_path}")
    print(f"\n{'='*70}")
    print("NEXT STEP: Run subagent assessment for each batch.")
    print(f"{'='*70}")
    print()
    print("For each batch, launch a Claude Code subagent:")
    for batch_num, batch in enumerate(batches, 1):
        ctx = WORK_DIR / f"_context_batch_{batch_num}.md"
        out = WORK_DIR / f"_assessments_batch_{batch_num}.json"
        print(f"\n  Batch {batch_num} ({len(batch)} claims):")
        print(f"    Read:  {ctx}")
        print(f"    Write: {out}")

    print(f"\nAfter all batches are assessed:")
    print(f"  uv run python scripts/reassess_claims.py update")


def update():
    """Parse subagent output and update claim verdicts in the DB."""
    from esbvaktin.claim_bank.operations import update_claim_verdict
    from esbvaktin.ground_truth.operations import get_connection
    from esbvaktin.pipeline.parse_outputs import _extract_json

    manifest = json.loads(
        (WORK_DIR / "_manifest.json").read_text(encoding="utf-8")
    )

    conn = get_connection()
    updated = 0
    skipped = 0
    errors = []

    for batch_info in manifest:
        batch_num = batch_info["batch"]
        output_path = WORK_DIR / f"_assessments_batch_{batch_num}.json"

        if not output_path.exists():
            print(f"  Batch {batch_num}: MISSING — {output_path}")
            skipped += len(batch_info["claims"])
            continue

        try:
            raw_text = output_path.read_text(encoding="utf-8")
            raw = json.loads(_extract_json(raw_text))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Batch {batch_num}: JSON PARSE ERROR — {e}")
            errors.append((batch_num, str(e)))
            continue

        for item in raw:
            claim_id = item.get("claim_id")
            verdict = item.get("verdict")
            if not claim_id or not verdict:
                print(f"    Skipping malformed item: {item}")
                skipped += 1
                continue

            # Validate verdict
            valid_verdicts = {
                "supported", "partially_supported", "unsupported",
                "misleading", "unverifiable",
            }
            if verdict not in valid_verdicts:
                print(f"    Invalid verdict '{verdict}' for claim {claim_id}")
                skipped += 1
                continue

            try:
                update_claim_verdict(
                    claim_id=claim_id,
                    verdict=verdict,
                    explanation_is=item.get("explanation_is", ""),
                    supporting_evidence=item.get("supporting_evidence", []),
                    contradicting_evidence=item.get("contradicting_evidence", []),
                    missing_context_is=item.get("missing_context_is"),
                    confidence=item.get("confidence", 0.5),
                    conn=conn,
                )
                updated += 1
            except Exception as e:
                print(f"    Error updating claim {claim_id}: {e}")
                errors.append((claim_id, str(e)))

    conn.close()

    print(f"\n{'='*70}")
    print(f"RE-ASSESSMENT COMPLETE")
    print(f"{'='*70}")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    if errors:
        print(f"  Errors:  {len(errors)}")
        for ref, err in errors:
            print(f"    - {ref}: {err}")

    print(f"\nNext: check results with")
    print(f"  uv run python scripts/reassess_claims.py status")
    print(f"  uv run python scripts/seed_claim_bank.py status")


def status():
    """Show current verdict distribution."""
    from esbvaktin.claim_bank.operations import get_claim_counts, get_total_claims
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()
    counts = get_claim_counts(conn)
    total = get_total_claims(conn)

    # Check for pending assessment files
    pending_batches = 0
    done_batches = 0
    if WORK_DIR.exists():
        manifest_path = WORK_DIR / "_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for batch_info in manifest:
                output = WORK_DIR / f"_assessments_batch_{batch_info['batch']}.json"
                if output.exists():
                    done_batches += 1
                else:
                    pending_batches += 1

    print(f"{'='*50}")
    print(f"CLAIM BANK STATUS")
    print(f"{'='*50}")
    print(f"  Total claims: {total}")
    print()
    for verdict, count in sorted(counts.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        bar = "#" * int(pct / 2)
        print(f"  {verdict:25s} {count:3d} ({pct:4.1f}%) {bar}")

    unverifiable = counts.get("unverifiable", 0)
    print(f"\n  Unverifiable rate: {unverifiable}/{total} = {unverifiable/total*100:.1f}%")

    if pending_batches or done_batches:
        print(f"\n  Assessment batches: {done_batches} done, {pending_batches} pending")

    conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/reassess_claims.py [prepare|update|status]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare()
    elif cmd == "update":
        update()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
