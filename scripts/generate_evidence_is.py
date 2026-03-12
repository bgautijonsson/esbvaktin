#!/usr/bin/env python3
"""Generate Icelandic summaries for evidence entries.

Batch subagent workflow: prepare context → subagent writes IS text → write to DB.

Usage:
    # Step 1: Prepare context batches
    uv run python scripts/generate_evidence_is.py prepare

    # Step 2: Run subagent for each batch (Claude Code reads batch context,
    #         writes _output_batch_N.json)

    # Step 3: Parse output and update DB
    uv run python scripts/generate_evidence_is.py write

    # Check progress
    uv run python scripts/generate_evidence_is.py status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORK_DIR = PROJECT_ROOT / "data" / "evidence_is"
_BLOCKS_PATH = PROJECT_ROOT / ".claude" / "skills" / "icelandic-shared" / "assessment-blocks.md"
BATCH_SIZE = 30


def _get_connection():
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")

    import psycopg

    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="esbvaktin",
        user="esb",
        password="localdev",
    )


# ── Prepare ────────────────────────────────────────────────────────────

_EVIDENCE_QUERY = """\
SELECT evidence_id, domain, topic, subtopic,
       statement, source_name, source_url, source_type,
       confidence, caveats
FROM evidence
WHERE statement_is IS NULL
ORDER BY topic, evidence_id
"""


def _write_batch_context(batch: list[dict], batch_num: int) -> Path:
    """Write a context file for a batch of evidence entries."""
    path = WORK_DIR / f"_context_batch_{batch_num}.md"
    lines = [
        f"# Íslenskar samantektir heimilda — Lota {batch_num}\n",
        "Þú ert sérfræðingur í íslensku fræðimáli sem vinnur fyrir ESBvaktin.is,",
        "óháðan vettvang um þjóðaratkvæðagreiðslu Íslands um ESB-aðild (29. ágúst 2026).",
        "",
        "Verkefnið: Skrifa íslenskar samantektir (`statement_is`) og heimildarlýsingar",
        "(`source_description_is`) fyrir gagnagrunnsfærslur sem eru á ensku.",
        "",
        "## Meginreglur",
        "",
        "- **Samsetning, ekki þýðing.** Skrifaðu frá gögnum — EKKI þýða enska textann orð fyrir orð.",
        "  Hugsaðu á íslensku frá upphafi. Ef setningin hljómar eins og þýdd enska, eyddu og byrjaðu aftur.",
        "- **statement_is**: 1–2 setningar. Nákvæm, greiningarleg samantekt á efni heimildarinnar.",
        "  Ef tölur eru í frumtextanum, haltu þeim nákvæmum. Ef aðeins er um staðreynd að ræða,",
        "  nægir ein setning.",
        "- **source_description_is**: 15\u201330 orð. Stutt lýsing á upprunastofnun/útgefanda.",
        '  Dæmi: «Hagstofa Íslands er opinber tölfræðistofnun sem gefur reglulega út hagtölur'
        ' um efnahag, fólksfjölda og samfélag.»',
        "- **Unicode skylda**: Sérhver íslensk setning VERÐUR að innihalda stafi úr",
        "  {þ, ð, á, é, í, ó, ú, ý, æ, ö}. Ef setning vantar þessa stafi er hún gölluð.",
        "- **ESB-hugtök**: Notaðu samræmd íslensk hugtök (sjá Block F hér að neðan).",
        "- **Ekki ofþýða**: Stofnanaheiti sem eru þekkt á íslensku (Hagstofa Íslands,",
        "  Seðlabanki Íslands, Eurostat, OECD) nota íslenskt heiti. Ensk heiti sem",
        "  hafa ekki viðtekna íslensku (t.d. sérstök skýrsluheiti) má halda á ensku.",
        '- **JSON-gæsalappir**: ALDREI nota íslensku gæsalappirnar „…" í JSON-strengjagildum — þær brjóta JSON-þáttun. Notaðu «…» (guillemets) í staðinn. Ef þú VERÐUR að nota tvöfaldar gæsalappir, slepptu þeim: \\\\"…\\\\"',
        "",
    ]

    # Evidence entries
    for i, ev in enumerate(batch, 1):
        lines.append(f"---\n")
        lines.append(f"## Heimild {i}: {ev['evidence_id']}")
        lines.append("")
        lines.append(f"- **Svið (domain):** {ev['domain']}")
        lines.append(f"- **Efnisflokkur (topic):** {ev['topic']}")
        if ev.get("subtopic"):
            lines.append(f"- **Undirflokkur:** {ev['subtopic']}")
        lines.append(f"- **Heimildagerð:** {ev['source_type']}")
        lines.append(f"- **Áreiðanleiki:** {ev['confidence']}")
        lines.append(f"- **Heimild:** {ev['source_name']}")
        if ev.get("source_url"):
            lines.append(f"- **Slóð:** {ev['source_url']}")
        lines.append("")
        lines.append(f"**Statement (enska):**")
        lines.append(f"> {ev['statement']}")
        lines.append("")
        if ev.get("caveats"):
            lines.append(f"**Caveats:** {ev['caveats']}")
            lines.append("")

    # Output format
    lines.extend([
        "---\n",
        "## Úttakssnið",
        "",
        f"Skrifaðu JSON-fylki í `_output_batch_{batch_num}.json` (hrátt JSON, engin markdown-umbúðir).",
        "Hvert atriði:",
        "",
        "```json",
        "{",
        '  "evidence_id": "FISH-DATA-001",',
        '  "statement_is": "Íslensk samantekt, 1-2 setningar.",',
        '  "source_description_is": "Stutt lýsing á upprunastofnun, 15-30 orð."',
        "}",
        "```",
        "",
        "**Reglur um source_description_is:**",
        "- Sama stofnun getur birst mörgum sinnum í lotunni.",
        "  Skrifaðu SÖMU lýsinguna fyrir sömu stofnun í hvert skipti (samræmi).",
        "- Ef stofnunin er þekkt (Hagstofa Íslands, Eurostat, OECD, Alþingi)",
        "  — stutt og þekkt lýsing. Ef minna þekkt — lýstu hlutverki hennar.",
        "",
    ])

    # Append Icelandic quality blocks
    if _BLOCKS_PATH.exists():
        lines.append("")
        lines.append(_BLOCKS_PATH.read_text(encoding="utf-8"))

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def prepare() -> None:
    """Prepare context batches for subagent IS summary generation."""
    conn = _get_connection()
    rows = conn.execute(_EVIDENCE_QUERY).fetchall()
    conn.close()

    cols = [
        "evidence_id", "domain", "topic", "subtopic",
        "statement", "source_name", "source_url", "source_type",
        "confidence", "caveats",
    ]
    entries = [dict(zip(cols, row)) for row in rows]

    if not entries:
        print("All evidence entries already have statement_is. Nothing to do.")
        return

    print(f"Found {len(entries)} entries without Icelandic summaries.")

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # Split into batches
    batches = [
        entries[i : i + BATCH_SIZE]
        for i in range(0, len(entries), BATCH_SIZE)
    ]

    manifest = []
    for batch_num, batch in enumerate(batches, 1):
        path = _write_batch_context(batch, batch_num)
        manifest.append({
            "batch": batch_num,
            "context_file": str(path),
            "evidence_ids": [e["evidence_id"] for e in batch],
            "count": len(batch),
        })
        print(f"  Batch {batch_num}: {len(batch)} entries → {path}")

    # Write manifest
    manifest_path = WORK_DIR / "_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write flat entries data for reference
    data_path = WORK_DIR / "_entries_data.json"
    data_path.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nManifest: {manifest_path}")
    print(f"Entries data: {data_path}")
    print(f"\n{'='*70}")
    print("NEXT STEP: Run subagent for each batch.")
    print(f"{'='*70}")
    print()
    print("For each batch, launch a Claude Code subagent:")
    for batch_num, batch in enumerate(batches, 1):
        ctx = WORK_DIR / f"_context_batch_{batch_num}.md"
        out = WORK_DIR / f"_output_batch_{batch_num}.json"
        print(f"\n  Batch {batch_num} ({len(batch)} entries):")
        print(f"    Read:  {ctx}")
        print(f"    Write: {out}")

    print(f"\nAfter all batches are done:")
    print(f"  uv run python scripts/generate_evidence_is.py write")


# ── Write ──────────────────────────────────────────────────────────────

_IS_CHARS = set("þðáéíóúýæöÞÐÁÉÍÓÚÝÆÖ")


def _has_icelandic_chars(text: str) -> bool:
    """Check if text contains at least one Icelandic-specific character."""
    return bool(_IS_CHARS.intersection(text))


def _extract_json_text(raw: str) -> str:
    """Extract JSON from text, handling Icelandic quotes and markdown wrapping.

    Delegates to the canonical ``_extract_json`` from parse_outputs which
    properly escapes Icelandic „…" quotes inside JSON string values.
    """
    from esbvaktin.pipeline.parse_outputs import _extract_json

    return _extract_json(raw)


def write() -> None:
    """Parse subagent output and update the DB with IS summaries."""
    manifest_path = WORK_DIR / "_manifest.json"
    if not manifest_path.exists():
        print("No manifest found. Run 'prepare' first.")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    conn = _get_connection()
    updated = 0
    skipped = 0
    errors: list[tuple[str, str]] = []
    ascii_warnings: list[str] = []

    for batch_info in manifest:
        batch_num = batch_info["batch"]
        output_path = WORK_DIR / f"_output_batch_{batch_num}.json"

        if not output_path.exists():
            print(f"  Batch {batch_num}: MISSING — {output_path}")
            skipped += batch_info["count"]
            continue

        try:
            raw_text = output_path.read_text(encoding="utf-8")
            cleaned = _extract_json_text(raw_text)
            items = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Batch {batch_num}: JSON PARSE ERROR — {e}")
            errors.append((f"batch_{batch_num}", str(e)))
            continue

        if not isinstance(items, list):
            print(f"  Batch {batch_num}: Expected JSON array, got {type(items).__name__}")
            errors.append((f"batch_{batch_num}", "not a JSON array"))
            continue

        batch_updated = 0
        for item in items:
            eid = item.get("evidence_id")
            statement_is = item.get("statement_is")
            source_desc_is = item.get("source_description_is")

            if not eid or not statement_is:
                print(f"    Skipping malformed item: {item.get('evidence_id', '???')}")
                skipped += 1
                continue

            # Validate Icelandic characters
            if not _has_icelandic_chars(statement_is):
                ascii_warnings.append(eid)
                print(f"    WARNING: {eid} statement_is lacks Icelandic chars — writing anyway")

            if source_desc_is and not _has_icelandic_chars(source_desc_is):
                ascii_warnings.append(f"{eid}:desc")
                print(f"    WARNING: {eid} source_description_is lacks Icelandic chars")

            # Optional GreynirCorrect post-processing
            try:
                from esbvaktin.corrections.greynir import (
                    check_with_library,
                    apply_fixes_to_text,
                )

                for label, text in [("statement_is", statement_is), ("source_description_is", source_desc_is)]:
                    if text and len(text) > 10:
                        sents = [(text, 1)]
                        results = check_with_library(sents)
                        if results:
                            fixed, count = apply_fixes_to_text(text, results)
                            if count > 0:
                                print(f"    GreynirCorrect: {count} fix(es) for {label} ({eid})")
                                if label == "statement_is":
                                    statement_is = fixed
                                else:
                                    source_desc_is = fixed
            except ImportError:
                pass  # corrections package not installed

            # Update DB
            try:
                update_fields = ["statement_is = %s"]
                update_values: list = [statement_is]

                if source_desc_is:
                    update_fields.append("source_description_is = %s")
                    update_values.append(source_desc_is)

                update_values.append(eid)
                conn.execute(
                    f"UPDATE evidence SET {', '.join(update_fields)} WHERE evidence_id = %s",
                    update_values,
                )
                conn.commit()
                batch_updated += 1
                updated += 1
            except Exception as e:
                print(f"    Error updating {eid}: {e}")
                errors.append((eid, str(e)))

        print(f"  Batch {batch_num}: {batch_updated} updated")

    conn.close()

    print(f"\n{'='*70}")
    print("ICELANDIC SUMMARY GENERATION COMPLETE")
    print(f"{'='*70}")
    print(f"  Updated:  {updated}")
    print(f"  Skipped:  {skipped}")
    if ascii_warnings:
        print(f"  ASCII warnings: {len(ascii_warnings)} (missing Icelandic chars)")
    if errors:
        print(f"  Errors:   {len(errors)}")
        for ref, err in errors:
            print(f"    - {ref}: {err}")

    print(f"\nNext steps:")
    print(f"  uv run python scripts/generate_evidence_is.py status")
    print(f"  uv run python scripts/export_evidence.py --site-dir ~/esbvaktin-site")


# ── Status ─────────────────────────────────────────────────────────────

def status() -> None:
    """Show IS coverage and batch progress."""
    conn = _get_connection()

    total = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    with_is = conn.execute("SELECT COUNT(*) FROM evidence WHERE statement_is IS NOT NULL").fetchone()[0]
    with_desc = conn.execute("SELECT COUNT(*) FROM evidence WHERE source_description_is IS NOT NULL").fetchone()[0]

    # Per-topic breakdown
    topic_rows = conn.execute(
        "SELECT topic, COUNT(*), COUNT(statement_is) "
        "FROM evidence GROUP BY topic ORDER BY topic"
    ).fetchall()

    conn.close()

    pct = with_is / total * 100 if total else 0
    desc_pct = with_desc / total * 100 if total else 0

    print(f"\n{'='*50}")
    print("ICELANDIC EVIDENCE SUMMARY STATUS")
    print(f"{'='*50}")
    print(f"  Total entries:       {total}")
    print(f"  With statement_is:   {with_is}/{total} ({pct:.0f}%)")
    print(f"  With description_is: {with_desc}/{total} ({desc_pct:.0f}%)")
    print(f"  Remaining:           {total - with_is}")

    print(f"\nBy topic:")
    for topic, count, has_is in topic_rows:
        done_pct = has_is / count * 100 if count else 0
        bar = "#" * int(done_pct / 5)
        print(f"  {topic:25s} {has_is:3d}/{count:3d} ({done_pct:4.0f}%) {bar}")

    # Check batch progress
    if WORK_DIR.exists():
        manifest_path = WORK_DIR / "_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            done = sum(
                1 for b in manifest
                if (WORK_DIR / f"_output_batch_{b['batch']}.json").exists()
            )
            pending = len(manifest) - done
            print(f"\n  Batches: {done} done, {pending} pending (of {len(manifest)})")


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/generate_evidence_is.py [prepare|write|status]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare()
    elif cmd == "write":
        write()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
