#!/usr/bin/env python3
"""Fix claims with ASCII-only Icelandic text.

Identifies claims where explanation_is has no Icelandic characters,
retrieves evidence, and writes context files for subagent re-assessment
with improved Icelandic quality blocks.

Usage:
    uv run python scripts/fix_ascii_claims.py prepare     # Write context files
    uv run python scripts/fix_ascii_claims.py update       # Parse output and update DB
    uv run python scripts/fix_ascii_claims.py status       # Check progress
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

WORK_DIR = Path("data/reassessment/ascii_fix")
SIMILARITY_THRESHOLD = 0.40
BATCH_SIZE = 10
_BLOCKS_PATH = Path(".claude/skills/icelandic-shared/assessment-blocks.md")
_ICE_CHARS = re.compile(r"[þðáéíóúýæöÞÐÁÉÍÓÚÝÆÖ]")


def _get_ascii_claims_with_evidence(conn):
    """Fetch claims with ASCII-only explanation_is and retrieve evidence."""
    from esbvaktin.ground_truth.operations import search_evidence

    rows = conn.execute(
        "SELECT id, canonical_text_is, canonical_text_en, category, claim_slug, "
        "verdict, explanation_is, missing_context_is "
        "FROM claims WHERE length(explanation_is) > 50 "
        "ORDER BY category, claim_slug"
    ).fetchall()

    assessable = []
    for row in rows:
        claim_id, text_is, text_en, category, slug, verdict, exp_is, ctx_is = row
        # Skip claims that already have proper Icelandic
        if _ICE_CHARS.search(exp_is or ""):
            continue

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

        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:8]

        assessable.append({
            "claim_id": claim_id,
            "text_is": text_is,
            "text_en": text_en,
            "category": category,
            "slug": slug,
            "current_verdict": verdict,
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
            ] if strong else [],
        })

    return assessable


def _write_batch_context(batch: list[dict], batch_num: int) -> Path:
    """Write context file for a batch of claims with full Icelandic quality blocks."""
    path = WORK_DIR / f"_context_batch_{batch_num}.md"
    lines = [
        f"# Endurskrifa íslensku — Lota {batch_num}\n",
        "Þú ert staðreyndaprófari fyrir ESBvaktin.is. Þessar fullyrðingar hafa verið",
        "metnar áður en **íslenskan í úttökunni er gölluð** — textinn er á ASCII í stað",
        "réttra íslenskra stafa. Þú þarft að **endurskrifa** matið á réttri íslensku,",
        "ekki breyta sjálfu matinu (verdict) nema heimildir gefi skýrt tilefni til þess.",
        "",
        "**MIKILVÆGT:** Úttakið VERÐUR að vera á réttri íslensku með öllum séríslenskum stöfum",
        "(þ, ð, á, é, í, ó, ú, ý, æ, ö). Ef texti inniheldur \"thjodaratkvaedagreidsla\"",
        "í stað \"þjóðaratkvæðagreiðsla\" er hann gallaður. Lestu Block D í viðhengi vandlega.",
        "",
    ]

    for i, claim in enumerate(batch, 1):
        lines.append(f"## Fullyrðing {i} (claim_id: {claim['claim_id']})")
        lines.append("")
        lines.append(f"**Íslenskur texti:** {claim['text_is']}")
        if claim["text_en"]:
            lines.append(f"**Enskur texti:** {claim['text_en']}")
        lines.append(f"**Flokkur:** {claim['category']}")
        lines.append(f"**Núverandi mat:** {claim['current_verdict']}")
        lines.append("")
        if claim["evidence"]:
            lines.append("**Heimildir úr staðreyndagrunni:**")
            lines.append("")
            for ev in claim["evidence"]:
                lines.append(f"- **{ev['evidence_id']}** (líkindi: {ev['similarity']})")
                lines.append(f"  {ev['statement']}")
                lines.append(f"  *Heimild: {ev['source_name']}*")
                if ev.get("caveats"):
                    lines.append(f"  Fyrirvarar: {ev['caveats']}")
                lines.append("")
        else:
            lines.append("**Engar heimildir fundust í staðreyndagrunni.**")
            lines.append("")

    # Output format
    lines.extend([
        "## Úttakssnið",
        "",
        f"Skrifaðu JSON-fylki í `_assessments_batch_{batch_num}.json` (hrátt JSON, engin markdown-umbúðir).",
        "Skrifaðu `explanation_is` og `missing_context_is` á **réttri íslensku** — ALDREI á ASCII.",
        "Hvert atriði:",
        "",
        "```json",
        "{",
        '  "claim_id": 123,',
        '  "verdict": "supported | partially_supported | unsupported | misleading | unverifiable",',
        '  "explanation_is": "2-3 setningar á RÉTTRI ÍSLENSKU með tilvísun í heimildir",',
        '  "supporting_evidence": ["EVIDENCE-ID-001"],',
        '  "contradicting_evidence": [],',
        '  "missing_context_is": "mikilvægt samhengi á RÉTTRI ÍSLENSKU, eða null",',
        '  "confidence": 0.85',
        "}",
        "```",
        "",
        "## Meginreglur",
        "",
        "- **ÍSLENSKU STAFIR:** ALLUR texti VERÐUR að nota þ, ð, á, é, í, ó, ú, ý, æ, ö. ALDREI ASCII.",
        "- **Óhlutdrægni**: metið ESB-jákvæðar og ESB-neikvæðar fullyrðingar jafnt",
        "- **Heimildum háð**: sérhvert mat VERÐUR að vitna í tilteknar evidence_id",
        "- **Fyrirvarar skipta máli**: komið á framfæri fyrirvörum úr heimildum",
        "- **Auðmýkt**: ef heimildir duga ekki, notið `unverifiable`",
        "- **Beinskeytni**: segðu \"staðfestir\" ekki \"virðist benda til\"",
        '- JSON-öryggi: notið \\\\" fyrir gæsalappir í JSON-strengjum',
    ])

    # Append Icelandic quality blocks
    if _BLOCKS_PATH.exists():
        lines.append("")
        lines.append(_BLOCKS_PATH.read_text(encoding="utf-8"))

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def prepare():
    """Prepare context files for subagent re-assessment of ASCII claims."""
    from esbvaktin.ground_truth.operations import get_connection

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    print("Finding claims with ASCII-only Icelandic text...")
    assessable = _get_ascii_claims_with_evidence(conn)
    conn.close()

    print(f"Found {len(assessable)} claims to fix")

    # Split into batches
    batches = [
        assessable[i : i + BATCH_SIZE]
        for i in range(0, len(assessable), BATCH_SIZE)
    ]

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

    manifest_path = WORK_DIR / "_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    claims_path = WORK_DIR / "_claims_data.json"
    claims_path.write_text(
        json.dumps(assessable, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nManifest: {manifest_path}")
    print(f"\n{'='*70}")
    print("NEXT STEP: Run subagent assessment for each batch.")
    print(f"{'='*70}")
    print()
    for batch_num, batch in enumerate(batches, 1):
        ctx = WORK_DIR / f"_context_batch_{batch_num}.md"
        out = WORK_DIR / f"_assessments_batch_{batch_num}.json"
        print(f"  Batch {batch_num} ({len(batch)} claims):")
        print(f"    Read:  {ctx}")
        print(f"    Write: {out}")
    print("\nAfter all batches: uv run python scripts/fix_ascii_claims.py update")


def update():
    """Parse subagent output and update claims in the DB."""
    from esbvaktin.claim_bank.operations import update_claim_verdict
    from esbvaktin.ground_truth.operations import get_connection
    from esbvaktin.pipeline.parse_outputs import _extract_json

    manifest = json.loads(
        (WORK_DIR / "_manifest.json").read_text(encoding="utf-8")
    )

    conn = get_connection()
    updated = 0
    skipped = 0
    still_ascii = 0
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

            # Verify the output has proper Icelandic
            exp_is = item.get("explanation_is", "")
            if len(exp_is) > 50 and not _ICE_CHARS.search(exp_is):
                print(f"    WARNING: Claim {claim_id} STILL has ASCII-only explanation_is!")
                still_ascii += 1
                # Still update — the verdict might have changed, and we can fix text later

            try:
                update_claim_verdict(
                    claim_id=claim_id,
                    verdict=verdict,
                    explanation_is=exp_is,
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
    print("ASCII FIX COMPLETE")
    print(f"{'='*70}")
    print(f"  Updated:    {updated}")
    print(f"  Skipped:    {skipped}")
    print(f"  Still ASCII: {still_ascii}")
    if errors:
        print(f"  Errors:     {len(errors)}")


def status():
    """Show progress of the ASCII fix."""
    if not WORK_DIR.exists():
        print("No ASCII fix in progress. Run: uv run python scripts/fix_ascii_claims.py prepare")
        return

    manifest_path = WORK_DIR / "_manifest.json"
    if not manifest_path.exists():
        print("No manifest found. Run prepare first.")
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    total = sum(len(b["claims"]) for b in manifest)
    done = 0
    pending = 0

    for batch_info in manifest:
        output = WORK_DIR / f"_assessments_batch_{batch_info['batch']}.json"
        if output.exists():
            done += 1
        else:
            pending += 1

    print("ASCII Fix Progress:")
    print(f"  Total claims: {total}")
    print(f"  Batches: {done} done, {pending} pending (of {len(manifest)})")


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/fix_ascii_claims.py [prepare|update|status]")
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
