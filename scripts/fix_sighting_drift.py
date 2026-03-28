#!/usr/bin/env python3
"""Fix sighting drift — canonical verdicts that disagree with sighting majority.

When >50% of per-article sighting verdicts (with 3+ sightings) disagree with
the canonical verdict, the canonical is likely wrong. This script prepares
context for a claim-assessor subagent to re-evaluate using both evidence AND
sighting verdict patterns, then applies the corrections.

Usage:
    # Step 1: Identify drifted claims and prepare context
    uv run python scripts/fix_sighting_drift.py prepare

    # Step 2: Run subagent assessment (Claude Code reads each batch context
    #         and writes _drift_assessments_batch_N.json)
    # → see printed instructions after prepare

    # Step 3: Apply corrections to DB (shows before/after diff)
    uv run python scripts/fix_sighting_drift.py apply

    # Check current drift status
    uv run python scripts/fix_sighting_drift.py status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORK_DIR = Path("data/drift_fix")
_BLOCKS_PATH = Path(".claude/skills/icelandic-shared/assessment-blocks.md")
SIMILARITY_THRESHOLD = 0.45
BATCH_SIZE = 10
MIN_SIGHTINGS = 3
DRIFT_THRESHOLD = 0.50  # >50% of sightings must disagree


def _get_drifted_claims(conn) -> list[dict]:
    """Find claims where >50% of sightings (min 3) disagree with canonical verdict."""
    rows = conn.execute(
        """
        SELECT c.id, c.claim_slug, c.canonical_text_is, c.canonical_text_en,
               c.category, c.verdict, c.confidence, c.explanation_is,
               c.missing_context_is, c.published,
               COUNT(*) as total_sightings,
               COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END) as mismatches
        FROM claims c
        JOIN claim_sightings cs ON c.id = cs.claim_id
        WHERE cs.speech_verdict IS NOT NULL
        GROUP BY c.id, c.claim_slug, c.canonical_text_is, c.canonical_text_en,
                 c.category, c.verdict, c.confidence, c.explanation_is,
                 c.missing_context_is, c.published
        HAVING COUNT(*) >= %(min_sightings)s
           AND COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END)::float
               / COUNT(*) > %(drift_threshold)s
        ORDER BY COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END)::float
                 / COUNT(*) DESC,
                 COUNT(*) DESC
        """,
        {"min_sightings": MIN_SIGHTINGS, "drift_threshold": DRIFT_THRESHOLD},
    ).fetchall()

    claims = []
    for r in rows:
        claims.append(
            {
                "claim_id": r[0],
                "slug": r[1],
                "text_is": r[2],
                "text_en": r[3],
                "category": r[4],
                "verdict": r[5],
                "confidence": r[6],
                "explanation_is": r[7],
                "missing_context_is": r[8],
                "published": r[9],
                "total_sightings": r[10],
                "mismatches": r[11],
            }
        )

    return claims


def _get_sightings(claim_id: int, conn) -> list[dict]:
    """Fetch all sightings with speech_verdict for a claim."""
    rows = conn.execute(
        """
        SELECT original_text, speech_verdict, source_title, source_url,
               source_date, speaker_name
        FROM claim_sightings
        WHERE claim_id = %(claim_id)s AND speech_verdict IS NOT NULL
        ORDER BY source_date NULLS LAST
        """,
        {"claim_id": claim_id},
    ).fetchall()

    return [
        {
            "original_text": r[0],
            "speech_verdict": r[1],
            "source_title": r[2],
            "source_url": r[3],
            "source_date": str(r[4]) if r[4] else None,
            "speaker_name": r[5],
        }
        for r in rows
    ]


def _search_evidence(text_is: str | None, text_en: str | None, conn, top_k: int = 8):
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

    return sorted(
        [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
        key=lambda r: r.similarity,
        reverse=True,
    )[:top_k]


def _write_batch_context(batch: list[dict], batch_num: int) -> Path:
    """Write an Icelandic context file for a batch of drifted claims."""
    path = WORK_DIR / f"_context_drift_batch_{batch_num}.md"

    lines = [
        f"# Leiðrétting á misræmi heimildamats — Lota {batch_num}\n",
        "Þú ert staðreyndaprófari fyrir ESBvaktin.is, óháðan vettvang um",
        "þjóðaratkvæðagreiðslu Íslands um ESB-aðild (29. ágúst 2026).",
        "Þú metur fullyrðingar jafnt hvort sem þær eru ESB-jákvæðar eða ESB-neikvæðar.",
        "",
        "## Vandamálið",
        "",
        f"Þessi lota inniheldur **{len(batch)} fullyrðingar** þar sem meirihluti",
        "heimildamata úr einstökum greiningum (**speech_verdict**) er frábrugðinn",
        "yfirúrskurðinum (**canonical verdict**). Þetta bendir til þess að",
        "yfirúrskurðurinn sé rangur eða úreltur.",
        "",
        "## Verkefnið þitt",
        "",
        "Fyrir hverja fullyrðingu:",
        "",
        "1. **Texti:** Veldu besta textann — annaðhvort núverandi yfirtexta eða einn",
        "   af heimildatextunum (original_text), eða endurbætta útgáfu. Ef tölur eða",
        "   ártöl eru röng í yfirtextanum, leiðréttu þau.",
        "2. **Úrskurður:** Endurmettu í ljósi BÆÐI heimildagrunnsins (evidence)",
        "   OG mynsturs heimildamata (speech_verdict). Ef stór meirihluti sér",
        "   fullyrðinguna öðruvísi en yfirúrskurðurinn, er líklegt að þeir hafi rétt",
        "   fyrir sér — en ekki alltaf. Heimildir (evidence) eru úrslitaþátturinn.",
        "3. **Útskýring:** Nýja útskýringuna á íslensku (2-3 setningar) með",
        "   tilvísun í evidence ID. Byrjaðu á matinu, ekki á endurtekningu",
        "   fullyrðingarinnar.",
        "",
    ]

    for i, claim in enumerate(batch, 1):
        drift_pct = claim["mismatches"] / claim["total_sightings"] * 100
        lines.append(
            f"## Fullyrðing {i} (claim_id: {claim['claim_id']}) — "
            f"misræmi {claim['mismatches']}/{claim['total_sightings']} ({drift_pct:.0f}%)"
        )
        lines.append("")
        lines.append(f"**Núverandi yfirtexti:** {claim['text_is']}")
        if claim["text_en"]:
            lines.append(f"**Enskur texti:** {claim['text_en']}")
        lines.append(f"**Flokkur:** {claim['category']}")
        lines.append(
            f"**Núverandi úrskurður:** {claim['verdict']} (traust: {claim['confidence']:.2f})"
        )
        if claim["explanation_is"]:
            lines.append(f"**Núverandi útskýring:** {claim['explanation_is']}")
        lines.append("")

        # Sighting data
        lines.append("**Heimildamat úr greiningum:**")
        lines.append("")

        # Group sighting verdicts for summary
        verdict_counts: dict[str, int] = {}
        for s in claim["sightings"]:
            v = s["speech_verdict"]
            verdict_counts[v] = verdict_counts.get(v, 0) + 1

        verdict_summary = ", ".join(
            f"{v}: {c}" for v, c in sorted(verdict_counts.items(), key=lambda x: -x[1])
        )
        lines.append(f"*Dreifing úrskurða: {verdict_summary}*")
        lines.append("")

        for j, s in enumerate(claim["sightings"], 1):
            speaker = f" [{s['speaker_name']}]" if s.get("speaker_name") else ""
            date_str = f" ({s['source_date']})" if s.get("source_date") else ""
            lines.append(f"{j}. **{s['speech_verdict']}**{speaker}{date_str}")
            lines.append(f"   *{s['source_title'][:80]}*")
            lines.append(f"   Texti: {s['original_text']}")
            lines.append("")

        # Evidence
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
    lines.extend(
        [
            "## Úttakssnið",
            "",
            f"Skrifaðu JSON-fylki í `_drift_assessments_batch_{batch_num}.json` "
            "(hrátt JSON, engin markdown-umbúðir).",
            "Skrifaðu `explanation_is` og `missing_context_is` á **íslensku**.",
            "Hvert atriði:",
            "",
            "```json",
            "{",
            '  "claim_id": 123,',
            '  "canonical_text_is": "Leiðréttur eða óbreyttur yfirtexti",',
            '  "text_changed": true,',
            '  "change_reason": "Leiðrétti ártal úr 2010 í 2009 samkvæmt meirihluta heimilda",',
            '  "verdict": "supported | partially_supported | unsupported | misleading | unverifiable",',
            '  "explanation_is": "2-3 setningar á íslensku sem útskýra matið",',
            '  "supporting_evidence": ["EVIDENCE-ID-001"],',
            '  "contradicting_evidence": [],',
            '  "missing_context_is": "mikilvægt samhengi á íslensku, eða null",',
            '  "confidence": 0.85',
            "}",
            "```",
            "",
            "**Um `text_changed`:** Settu `true` ef þú breyttir yfirtextanum "
            "(leiðrétting á tölum, ártölum, orðalagi). Settu `false` ef textinn er óbreyttur.",
            "",
            "**Um `change_reason`:** Aðeins ef `text_changed` er `true` — stuttur rökstuðningur.",
            "",
            "## Meginreglur",
            "",
            "- **Óhlutdrægni**: metið ESB-jákvæðar og ESB-neikvæðar fullyrðingar jafnt",
            "- **Heimildum háð**: sérhvert mat VERÐUR að vitna í tilteknar evidence_id",
            "- **Heimildamat skiptir máli**: ef stór meirihluti greiningarmata bendir í aðra átt"
            " en yfirúrskurðurinn, þá ber að rökstyðja vel ef þú heldur yfirúrskurðinum",
            "- **Textaleiðréttingar**: ef tölur eða ártöl í yfirtextanum eru röng"
            " samkvæmt meirihluta heimildatexta, leiðréttu þau",
            "- **Fyrirvarar skipta máli**: komið á framfæri fyrirvörum úr heimildum",
            "- **Auðmýkt**: ef heimildir duga ekki til, notið `unverifiable`",
            "- **Pólitískar fullyrðingar**: einungis `supported` ef heimild staðfestir beint",
            "- **Tölulegar fullyrðingar**: ef heimildir sýna nálægar en ekki nákvæmlega"
            " sömu tölur, notið `partially_supported`",
            '- **JSON-gæsalappir**: ALDREI nota íslensku gæsalappirnar „…" í JSON. '
            "Notaðu «…» (guillemets) í staðinn. Ef þú VERÐUR að nota tvöfaldar "
            'gæsalappir, slepptu þeim: \\\\"…\\\\"',
        ]
    )

    # Append Icelandic quality blocks
    if _BLOCKS_PATH.exists():
        lines.append("")
        lines.append(_BLOCKS_PATH.read_text(encoding="utf-8"))

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def prepare():
    """Identify drifted claims and prepare context files for subagent assessment."""
    from esbvaktin.ground_truth.operations import get_connection

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # Clean stale output files
    stale = list(WORK_DIR.glob("_drift_assessments_batch_*.json"))
    if stale:
        for f in stale:
            f.unlink()
        print(f"Cleaned {len(stale)} stale assessment file(s) from previous run.")

    conn = get_connection()
    print("Finding claims with sighting drift (>50% disagreement, 3+ sightings)...")
    claims = _get_drifted_claims(conn)
    print(f"Found {len(claims)} drifted claims.")

    if not claims:
        conn.close()
        print("No drifted claims found.")
        return

    # Enrich each claim with sightings and evidence
    print("Fetching sightings and evidence...")
    for claim in claims:
        claim["sightings"] = _get_sightings(claim["claim_id"], conn)
        evidence = _search_evidence(claim["text_is"], claim["text_en"], conn)
        claim["evidence"] = [
            {
                "evidence_id": r.evidence_id,
                "statement": r.statement,
                "similarity": round(r.similarity, 3),
                "source_name": r.source_name,
                "source_url": r.source_url,
                "caveats": r.caveats,
            }
            for r in evidence
        ]

    conn.close()

    # Split into batches
    batches = [claims[i : i + BATCH_SIZE] for i in range(0, len(claims), BATCH_SIZE)]

    # Write batch context files and manifest
    manifest = []
    for batch_num, batch in enumerate(batches, 1):
        path = _write_batch_context(batch, batch_num)
        manifest.append(
            {
                "batch": batch_num,
                "context_file": str(path),
                "claims": [c["claim_id"] for c in batch],
                "slugs": [c["slug"] for c in batch],
            }
        )
        print(f"  Batch {batch_num}: {len(batch)} claims → {path}")

    # Write manifest
    manifest_path = WORK_DIR / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write full claims data for apply step (before-state snapshot)
    claims_path = WORK_DIR / "_claims_before.json"
    # Strip sighting objects (too large) but keep summaries
    claims_snapshot = []
    for c in claims:
        snap = {k: v for k, v in c.items() if k != "sightings"}
        snap["sighting_count"] = len(c["sightings"])
        # Keep verdict distribution
        verdict_counts: dict[str, int] = {}
        for s in c["sightings"]:
            v = s["speech_verdict"]
            verdict_counts[v] = verdict_counts.get(v, 0) + 1
        snap["sighting_verdicts"] = verdict_counts
        claims_snapshot.append(snap)
    claims_path.write_text(
        json.dumps(claims_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nManifest: {manifest_path}")
    print(f"Before-state snapshot: {claims_path}")
    print(f"\n{'=' * 70}")
    print("NEXT STEP: Run subagent assessment for each batch.")
    print(f"{'=' * 70}")
    for batch_num, batch in enumerate(batches, 1):
        ctx = WORK_DIR / f"_context_drift_batch_{batch_num}.md"
        out = WORK_DIR / f"_drift_assessments_batch_{batch_num}.json"
        print(f"\n  Batch {batch_num} ({len(batch)} claims):")
        print(f"    Read:  {ctx}")
        print(f"    Write: {out}")
    print("\nAfter all batches are assessed:")
    print("  uv run python scripts/fix_sighting_drift.py apply")


def apply():
    """Parse subagent output and apply corrections to the DB."""
    from esbvaktin.claim_bank.operations import (
        generate_slug,
        update_claim_canonical,
        update_claim_verdict,
    )
    from esbvaktin.ground_truth.operations import get_connection
    from esbvaktin.pipeline.parse_outputs import _extract_json

    manifest_path = WORK_DIR / "_manifest.json"
    if not manifest_path.exists():
        print("No manifest found. Run 'prepare' first.")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Load before-state for diff display
    before_path = WORK_DIR / "_claims_before.json"
    before_data = {}
    if before_path.exists():
        for c in json.loads(before_path.read_text(encoding="utf-8")):
            before_data[c["claim_id"]] = c

    conn = get_connection()
    updated = 0
    text_changed = 0
    skipped = 0
    errors = []

    for batch_info in manifest:
        batch_num = batch_info["batch"]
        output_path = WORK_DIR / f"_drift_assessments_batch_{batch_num}.json"

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

            valid_verdicts = {
                "supported",
                "partially_supported",
                "unsupported",
                "misleading",
                "unverifiable",
            }
            if verdict not in valid_verdicts:
                print(f"    Invalid verdict '{verdict}' for claim {claim_id}")
                skipped += 1
                continue

            # Post-process Icelandic text
            explanation_is = item.get("explanation_is", "")
            missing_context_is = item.get("missing_context_is")
            try:
                from esbvaktin.corrections.greynir import (
                    apply_fixes_to_text,
                    check_with_library,
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
                                print(
                                    f"    GreynirCorrect: {count} fix(es) for "
                                    f"{field_name} (claim {claim_id})"
                                )
                                if field_name == "explanation_is":
                                    explanation_is = fixed
                                else:
                                    missing_context_is = fixed
            except ImportError:
                pass

            # Determine if canonical text changed
            new_text = item.get("canonical_text_is")
            is_text_changed = item.get("text_changed", False)
            before = before_data.get(claim_id, {})

            try:
                if is_text_changed and new_text and new_text != before.get("text_is"):
                    new_slug = generate_slug(new_text[:80])
                    update_claim_canonical(
                        claim_id=claim_id,
                        canonical_text_is=new_text,
                        claim_slug=new_slug,
                        verdict=verdict,
                        explanation_is=explanation_is,
                        supporting_evidence=item.get("supporting_evidence", []),
                        contradicting_evidence=item.get("contradicting_evidence", []),
                        missing_context_is=missing_context_is,
                        confidence=item.get("confidence", 0.5),
                        conn=conn,
                    )
                    text_changed += 1
                else:
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
                continue

            # Show before/after diff
            old_verdict = before.get("verdict", "?")
            old_text_trunc = (before.get("text_is") or "")[:80]
            new_text_trunc = (new_text or before.get("text_is") or "")[:80]
            verdict_arrow = f"{old_verdict} → {verdict}"
            if old_verdict == verdict:
                verdict_arrow = f"{verdict} (unchanged)"

            print(f"  [{claim_id}] {verdict_arrow}")
            if is_text_changed and new_text:
                print(f"    OLD: {old_text_trunc}...")
                print(f"    NEW: {new_text_trunc}...")
                reason = item.get("change_reason", "")
                if reason:
                    print(f"    WHY: {reason}")

    conn.close()

    print(f"\n{'=' * 70}")
    print("SIGHTING DRIFT FIX COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Updated:      {updated}")
    print(f"  Text changed: {text_changed}")
    print(f"  Skipped:      {skipped}")
    if errors:
        print(f"  Errors:       {len(errors)}")
        for ref, err in errors:
            print(f"    - {ref}: {err}")

    print("\nNext steps:")
    print("  1. Review changes: uv run python scripts/fix_sighting_drift.py status")
    print("  2. Re-export: ./scripts/run_export.sh --site-dir ~/esbvaktin-site")


def status():
    """Show current sighting drift status."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()

    # Overall drift stats
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT c.id) as total_sighted,
            COUNT(DISTINCT c.id) FILTER (
                WHERE cs_agg.mismatches > 0
            ) as any_drift,
            COUNT(DISTINCT c.id) FILTER (
                WHERE cs_agg.total >= 3
                  AND cs_agg.mismatches::float / cs_agg.total > 0.5
            ) as majority_drift,
            COUNT(DISTINCT c.id) FILTER (
                WHERE cs_agg.total >= 3
                  AND cs_agg.mismatches::float / cs_agg.total > 0.75
            ) as strong_drift
        FROM claims c
        JOIN (
            SELECT claim_id,
                   COUNT(*) as total,
                   COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END) as mismatches
            FROM claim_sightings cs
            JOIN claims c ON c.id = cs.claim_id
            WHERE cs.speech_verdict IS NOT NULL
            GROUP BY cs.claim_id, c.verdict
        ) cs_agg ON cs_agg.claim_id = c.id
        """,
    ).fetchone()

    total_sighted, any_drift, majority_drift, strong_drift = row

    print(f"\n{'=' * 60}")
    print("SIGHTING DRIFT STATUS")
    print(f"{'=' * 60}")
    print(f"  Total sighted claims:                    {total_sighted}")
    print(
        f"  Any disagreement:                        {any_drift} ({100 * any_drift / max(total_sighted, 1):.1f}%)"
    )
    print(f"  Majority drift (>50%, 3+ sightings):     {majority_drift}")
    print(f"  Strong drift (>75%, 3+ sightings):       {strong_drift}")

    # Show the majority-drift claims if any remain
    if majority_drift > 0:
        rows = conn.execute(
            """
            SELECT c.id, c.claim_slug, c.verdict, c.canonical_text_is,
                   COUNT(*) as total,
                   COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END) as mismatches,
                   array_agg(DISTINCT cs.speech_verdict)
                     FILTER (WHERE cs.speech_verdict != c.verdict) as divergent
            FROM claims c
            JOIN claim_sightings cs ON c.id = cs.claim_id
            WHERE cs.speech_verdict IS NOT NULL
            GROUP BY c.id, c.claim_slug, c.verdict, c.canonical_text_is
            HAVING COUNT(*) >= %(min)s
               AND COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END)::float
                   / COUNT(*) > %(threshold)s
            ORDER BY COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END)::float
                     / COUNT(*) DESC
            """,
            {"min": MIN_SIGHTINGS, "threshold": DRIFT_THRESHOLD},
        ).fetchall()

        print(f"\n{'─' * 60}")
        print("MAJORITY-DRIFT CLAIMS")
        print(f"{'─' * 60}")
        for r in rows:
            cid, slug, verdict, text, total, mis, divergent = r
            pct = 100 * mis / total
            print(f"\n  [{cid}] {text[:90]}...")
            print(f"    Canonical: {verdict} | Drift: {mis}/{total} ({pct:.0f}%) → {divergent}")

    # Check for pending work
    if WORK_DIR.exists():
        manifest_path = WORK_DIR / "_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            done = sum(
                1
                for b in manifest
                if (WORK_DIR / f"_drift_assessments_batch_{b['batch']}.json").exists()
            )
            pending = len(manifest) - done
            if pending:
                print(f"\n  Pending assessment batches: {pending}")
                print(f"  Completed batches: {done}")

    conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/fix_sighting_drift.py [prepare|apply|status]")
        print("  prepare    Find drifted claims and prepare context for subagent")
        print("  apply      Parse subagent output and update DB")
        print("  status     Show current sighting drift stats")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare()
    elif cmd == "apply":
        apply()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
