#!/usr/bin/env python3
"""Re-assess claims that may benefit from new evidence.

Two categories of claims are targeted:
  1. **Unverifiable** — previously lacked evidence, may now have matches
  2. **Partially supported** — had some evidence, may now have additional
     evidence that upgrades (or changes) the verdict

Retrieves evidence for each claim, writes context files for subagent
assessment, then parses subagent output and updates the DB.

Usage:
    # Step 1: Prepare context files (batches of ~10 claims each)
    uv run python scripts/reassess_claims.py prepare           # both types
    uv run python scripts/reassess_claims.py prepare --only unverifiable
    uv run python scripts/reassess_claims.py prepare --only partial

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


def _search_evidence_dual(text_is: str | None, text_en: str | None, conn, top_k: int = 8):
    """Semantic search using both IS and EN text, deduplicated."""
    from esbvaktin.ground_truth.operations import search_evidence

    query = text_is or text_en
    if not query:
        return []

    results = search_evidence(query, top_k=top_k, conn=conn)
    if text_en and text_en != text_is:
        results_en = search_evidence(text_en, top_k=top_k, conn=conn)
        seen_ids = {r.evidence_id for r in results}
        for r in results_en:
            if r.evidence_id not in seen_ids:
                results.append(r)
                seen_ids.add(r.evidence_id)
    return results


def _get_reassessable_claims(conn, *, include_unverifiable: bool = True, include_partial: bool = True):
    """Fetch claims that may benefit from (re-)assessment with current evidence.

    For unverifiable claims: any strong evidence match qualifies.
    For partially_supported claims: must have NEW evidence not already linked.
    """
    assessable = []

    if include_unverifiable:
        assessable.extend(_get_unverifiable_with_evidence(conn))

    if include_partial:
        assessable.extend(_get_partial_with_new_evidence(conn))

    return assessable


def _get_unverifiable_with_evidence(conn) -> list[dict]:
    """Unverifiable claims that now have matching evidence."""
    rows = conn.execute(
        "SELECT id, canonical_text_is, canonical_text_en, category, claim_slug "
        "FROM claims WHERE verdict = 'unverifiable' "
        "ORDER BY category, claim_slug"
    ).fetchall()

    assessable = []
    for claim_id, text_is, text_en, category, slug in rows:
        results = _search_evidence_dual(text_is, text_en, conn)
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity, reverse=True,
        )[:8]

        if strong:
            assessable.append(_make_claim_entry(
                claim_id, text_is, text_en, category, slug,
                strong, reason="unverifiable",
            ))

    return assessable


def _get_partial_with_new_evidence(conn) -> list[dict]:
    """Partially supported claims that have NEW evidence not already linked."""
    rows = conn.execute(
        "SELECT id, canonical_text_is, canonical_text_en, category, claim_slug, "
        "       supporting_evidence, contradicting_evidence, confidence "
        "FROM claims WHERE verdict = 'partially_supported' "
        "ORDER BY confidence ASC, category, claim_slug"
    ).fetchall()

    assessable = []
    for row in rows:
        claim_id, text_is, text_en, category, slug, supporting, contradicting, confidence = row
        existing_ids = set(supporting or []) | set(contradicting or [])

        results = _search_evidence_dual(text_is, text_en, conn)
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity, reverse=True,
        )[:12]  # wider net — we need to find NEW matches

        # Separate into new and existing evidence
        new_evidence = [r for r in strong if r.evidence_id not in existing_ids]
        old_evidence = [r for r in strong if r.evidence_id in existing_ids]

        if not new_evidence:
            continue  # no new evidence — skip, subagent would just re-confirm

        # Include ALL strong evidence (old + new) so subagent has full picture,
        # but flag which ones are new
        all_evidence = (old_evidence + new_evidence)[:8]
        new_ids = {r.evidence_id for r in new_evidence}

        assessable.append(_make_claim_entry(
            claim_id, text_is, text_en, category, slug,
            all_evidence, reason="partial",
            new_evidence_ids=new_ids,
            current_confidence=confidence,
        ))

    return assessable


def _make_claim_entry(
    claim_id, text_is, text_en, category, slug, results, *,
    reason: str, new_evidence_ids: set[str] | None = None,
    current_confidence: float | None = None,
) -> dict:
    """Build a claim entry dict for context generation."""
    entry = {
        "claim_id": claim_id,
        "text_is": text_is,
        "text_en": text_en,
        "category": category,
        "slug": slug,
        "reason": reason,
        "evidence": [
            {
                "evidence_id": r.evidence_id,
                "statement": r.statement,
                "similarity": round(r.similarity, 3),
                "source_name": r.source_name,
                "source_url": r.source_url,
                "caveats": r.caveats,
                "is_new": r.evidence_id in new_evidence_ids if new_evidence_ids else True,
            }
            for r in results
        ],
    }
    if current_confidence is not None:
        entry["current_confidence"] = current_confidence
    return entry


def _write_batch_context(batch: list[dict], batch_num: int) -> Path:
    """Write a context file for a batch of claims to be assessed by a subagent."""
    path = WORK_DIR / f"_context_batch_{batch_num}.md"

    # Classify the batch
    n_unverifiable = sum(1 for c in batch if c["reason"] == "unverifiable")
    n_partial = sum(1 for c in batch if c["reason"] == "partial")

    lines = [
        "# Endurmat fullyrðinga — Lota {}\n".format(batch_num),
        "Þú ert staðreyndaprófari fyrir ESBvaktin.is, óháðan vettvang um",
        "þjóðaratkvæðagreiðslu Íslands um ESB-aðild (29. ágúst 2026).",
        "Þú metur fullyrðingar jafnt hvort sem þær eru ESB-jákvæðar eða ESB-neikvæðar.",
        "",
    ]

    if n_unverifiable and n_partial:
        lines.extend([
            "Þessi lota inniheldur tvenns konar fullyrðingar:",
            f"- **{n_unverifiable} óstaðfestanlegar** — áður skorti heimildir, nú eru nýjar komnar",
            f"- **{n_partial} að hluta staðfestar** — nýjar heimildir (merktar 🆕) gætu breytt matinu",
            "",
        ])
    elif n_unverifiable:
        lines.extend([
            "Þessar fullyrðingar voru áður flokkaðar sem **óstaðfestanlegar** (unverifiable)",
            "vegna þess að heimildir skorti. Nú eru nýjar heimildir komnar í gagnagrunninn.",
            "Endurmettu hverja fullyrðingu í ljósi heimildanna hér að neðan.",
            "",
        ])
    else:
        lines.extend([
            "Þessar fullyrðingar voru áður flokkaðar sem **að hluta staðfestar** (partially_supported).",
            "Nýjar heimildir (merktar 🆕) hafa bæst við gagnagrunninn síðan síðasta mat.",
            "Endurmettu hverja fullyrðingu í ljósi ALLRA heimilda — bæði eldri og nýrra.",
            "",
            "**Mikilvægt:** Breyttu aðeins niðurstöðunni ef nýju heimildarnar réttlæta það.",
            "Ef nýju heimildarnar bæta litlu við, haltu `partially_supported` en uppfærðu útskýringuna.",
            "",
        ])

    for i, claim in enumerate(batch, 1):
        reason_tag = "óstaðfestanleg" if claim["reason"] == "unverifiable" else "að hluta staðfest"
        conf_tag = ""
        if claim.get("current_confidence") is not None:
            conf_tag = f" · traust: {claim['current_confidence']:.2f}"
        lines.append(f"## Fullyrðing {i} (claim_id: {claim['claim_id']}) — {reason_tag}{conf_tag}")
        lines.append("")
        lines.append(f"**Íslenskur texti:** {claim['text_is']}")
        if claim["text_en"]:
            lines.append(f"**Enskur texti:** {claim['text_en']}")
        lines.append(f"**Flokkur:** {claim['category']}")
        lines.append("")
        lines.append("**Heimildir úr staðreyndagrunni:**")
        lines.append("")
        for ev in claim["evidence"]:
            new_marker = " 🆕" if ev.get("is_new") else ""
            lines.append(f"- **{ev['evidence_id']}**{new_marker} (líkindi: {ev['similarity']})")
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
        '- **Uppfærsla, ekki endurskrif**: fyrir fullyrðingar sem eru «að hluta staðfestar» — breytið aðeins ef nýju heimildarnar 🆕 breyta myndinni verulega',
        "- **Pólitískar fullyrðingar**: fullyrðingar um afstöðu flokka eða ákveðnar yfirlýsingar stjórnmálamanna "
        "verða einungis merktar `supported` ef heimild staðfestir beint — almennar upplýsingar um flokk duga ekki",
        "- **Tölulegar fullyrðingar**: ef heimildir sýna nálægar en ekki nákvæmlega sömu tölur, notið `partially_supported`",
        '- **JSON-gæsalappir**: ALDREI nota íslensku gæsalappirnar „…" í JSON-strengjagildum — þær brjóta JSON-þáttun. Notaðu «…» (guillemets) í staðinn. Ef þú VERÐUR að nota tvöfaldar gæsalappir, slepptu þeim: \\\\"…\\\\"',
    ])

    # Append Icelandic quality blocks
    if _BLOCKS_PATH.exists():
        lines.append("")
        lines.append(_BLOCKS_PATH.read_text(encoding="utf-8"))

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def prepare(*, only: str | None = None):
    """Prepare context files for subagent re-assessment."""
    from esbvaktin.ground_truth.operations import get_connection

    include_unverifiable = only in (None, "unverifiable")
    include_partial = only in (None, "partial")

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    types = []
    if include_unverifiable:
        types.append("unverifiable")
    if include_partial:
        types.append("partially_supported")
    print(f"Retrieving evidence for {' + '.join(types)} claims...")
    assessable = _get_reassessable_claims(
        conn, include_unverifiable=include_unverifiable, include_partial=include_partial,
    )
    conn.close()

    n_unv = sum(1 for c in assessable if c["reason"] == "unverifiable")
    n_par = sum(1 for c in assessable if c["reason"] == "partial")
    print(f"Found {len(assessable)} assessable claims ({n_unv} unverifiable, {n_par} partial)")

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
            verdict = item.get("verdict") or item.get("new_verdict")
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

            # Post-process Icelandic text if corrections package is available
            explanation_is = item.get("explanation_is", "")
            missing_context_is = item.get("missing_context_is")
            try:
                from esbvaktin.corrections.greynir import (
                    check_with_library,
                    apply_fixes_to_text,
                )

                for field_name, field_val in [
                    ("explanation_is", explanation_is),
                    ("missing_context_is", missing_context_is),
                ]:
                    if field_val and len(field_val) > 10:
                        sents = [(field_val, 1)]
                        results = check_with_library(sents)
                        if results:
                            fixed, count = apply_fixes_to_text(field_val, results)
                            if count > 0:
                                print(f"    GreynirCorrect: {count} fix(es) for {field_name} (claim {claim_id})")
                                if field_name == "explanation_is":
                                    explanation_is = fixed
                                else:
                                    missing_context_is = fixed
            except ImportError:
                pass  # corrections package not installed — skip

            try:
                update_claim_verdict(
                    claim_id=claim_id,
                    verdict=verdict,
                    explanation_is=explanation_is,
                    supporting_evidence=item.get("supporting_evidence", []),
                    contradicting_evidence=item.get("contradicting_evidence", []),
                    missing_context_is=missing_context_is,
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
    partial = counts.get("partially_supported", 0)
    print(f"\n  Unverifiable rate: {unverifiable}/{total} = {unverifiable/total*100:.1f}%")
    print(f"  Partial rate:      {partial}/{total} = {partial/total*100:.1f}%")

    if pending_batches or done_batches:
        print(f"\n  Assessment batches: {done_batches} done, {pending_batches} pending")

    conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/reassess_claims.py [prepare|update|status]")
        print("  prepare [--only unverifiable|partial]  Prepare context files")
        print("  update                                 Parse subagent output → DB")
        print("  status                                 Show verdict distribution")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "prepare":
        only = None
        if "--only" in sys.argv:
            idx = sys.argv.index("--only")
            if idx + 1 < len(sys.argv):
                only = sys.argv[idx + 1]
                if only not in ("unverifiable", "partial"):
                    print(f"Unknown --only value: {only} (use 'unverifiable' or 'partial')")
                    sys.exit(1)
        prepare(only=only)
    elif cmd == "update":
        update()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
