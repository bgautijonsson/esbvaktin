"""Fact-check Alþingi EU speeches against the evidence DB.

CLI with 4 subcommands:
    select   — rank candidate speeches for batch processing
    run      — run full pipeline on a single speech
    batch    — run pipeline on top N speeches
    status   — show fact-checking progress stats

Usage:
    uv run python scripts/fact_check_speeches.py select --limit 5
    uv run python scripts/fact_check_speeches.py run rad20260309T171000
    uv run python scripts/fact_check_speeches.py batch --limit 3
    uv run python scripts/fact_check_speeches.py status
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from textwrap import shorten

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from esbvaktin.speeches.fact_check import (
    _session_for_date,
    get_speech_for_fact_check,
    prepare_speech_work_dir,
    select_speeches_for_batch,
)


def cmd_select(args: argparse.Namespace) -> None:
    """List top candidate speeches for fact-checking."""
    candidates = select_speeches_for_batch(
        limit=args.limit,
        min_words=args.min_words,
        exclude_checked=not args.include_checked,
    )

    if not candidates:
        print("No candidate speeches found.")
        return

    print(f"{'Score':>5}  {'Date':10}  {'Words':>5}  {'Type':15}  {'Speaker':35}  {'Issue'}")
    print("-" * 120)
    for c in candidates:
        print(
            f"{c['score']:5.1f}  {c['date']:10}  {c['word_count']:5}  "
            f"{c['speech_type']:15}  {c['name']:35}  "
            f"{shorten(c['issue_title'], width=50, placeholder='…')}"
        )
    print(f"\n{len(candidates)} candidates shown.")


def cmd_run(args: argparse.Namespace) -> None:
    """Run the full fact-check pipeline on a single speech."""
    speech_id = args.speech_id

    # 1. Load speech
    print(f"Loading speech {speech_id}...")
    speech = get_speech_for_fact_check(speech_id)
    if not speech:
        print(f"Error: Speech '{speech_id}' not found in althingi.db", file=sys.stderr)
        sys.exit(1)

    print(f"  Speaker: {speech['name']} ({speech['party']})")
    print(f"  Type: {speech['speech_type']}, {speech['word_count']} words")
    print(f"  Issue: {speech['issue_title']}")
    print(f"  Date: {speech['date']}")

    # 2. Prepare work dir
    work_dir = prepare_speech_work_dir(speech_id)
    if not work_dir:
        print("Error: Could not prepare work directory", file=sys.stderr)
        sys.exit(1)
    print(f"  Work dir: {work_dir}")

    # 3. Prepare extraction context
    print("Preparing extraction context...")
    from esbvaktin.pipeline.prepare_context import prepare_speech_extraction_context

    session = speech["session"]
    if session == "?":
        session = _session_for_date(speech["date"])

    speaker_metadata = {
        "name": speech["name"],
        "party": speech["party"],
        "speech_type": speech["speech_type"],
        "issue_title": speech["issue_title"],
        "date": speech["date"],
        "session": session,
    }
    ctx_path = prepare_speech_extraction_context(
        speech_text=speech["full_text"],
        speaker_metadata=speaker_metadata,
        output_dir=work_dir,
        language="is",
    )
    print(f"  Extraction context: {ctx_path}")

    # 4. Run extraction subagent
    print("Running extraction subagent...")
    extraction_output = work_dir / "_claims.json"
    _run_subagent(
        task=(
            f"Read {ctx_path} and follow its instructions. "
            f"Extract all factual claims from the speech. "
            f"Write the output (a JSON array of claims) to {extraction_output}. "
            f"Write raw JSON, no markdown wrapping."
        ),
        output_path=extraction_output,
    )

    if not extraction_output.exists():
        print("Error: Extraction subagent did not produce output", file=sys.stderr)
        sys.exit(1)

    # 5. Parse extracted claims
    from esbvaktin.pipeline.parse_outputs import parse_claims

    claims = parse_claims(extraction_output)
    print(f"  Extracted {len(claims)} claims")

    if not claims:
        print("No claims extracted — nothing to assess.")
        return

    # 6. Retrieve evidence
    print("Retrieving evidence...")
    from esbvaktin.pipeline.retrieve_evidence import retrieve_evidence_for_claims

    claims_with_evidence, bank_matches, hearsay_assessments = retrieve_evidence_for_claims(
        claims,
        top_k=5,
        use_claim_bank=True,
    )
    if hearsay_assessments:
        print(f"  {len(hearsay_assessments)} hearsay claim(s) short-circuited as unverifiable")
    for cwe in claims_with_evidence:
        print(f"  {cwe.claim.claim_text[:60]}... — {len(cwe.evidence)} evidence matches")

    # 7. Prepare fact-check context
    print("Preparing assessment context...")
    from esbvaktin.pipeline.prepare_fact_check import prepare_fact_check_context

    fc_path = prepare_fact_check_context(
        claims_with_evidence,
        work_dir,
        language="is",
    )
    print(f"  Assessment context: {fc_path}")

    # 8. Run assessment subagent
    print("Running assessment subagent...")
    assessment_output = work_dir / "_assessments.json"
    _run_subagent(
        task=(
            f"Read {fc_path} and follow its instructions. "
            f"Assess each claim against the evidence provided. "
            f"Write the output (a JSON array of assessments) to {assessment_output}. "
            f"Write explanation and missing_context in Icelandic. "
            f"Write raw JSON, no markdown wrapping. "
            "Escape Icelandic quotation marks as backslash-quote in all JSON string values."
        ),
        output_path=assessment_output,
    )

    if not assessment_output.exists():
        print("Error: Assessment subagent did not produce output", file=sys.stderr)
        sys.exit(1)

    # 9. Parse assessments
    from esbvaktin.pipeline.parse_outputs import parse_assessments

    assessments = parse_assessments(assessment_output)
    print(f"  Assessed {len(assessments)} claims")

    # Print verdict summary
    verdict_counts: dict[str, int] = {}
    for a in assessments:
        v = a.verdict.value
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
    print(f"  Verdicts: {verdict_counts}")

    # 10. Register sightings
    if not args.dry_run:
        print("Registering sightings...")
        from esbvaktin.speeches.register_sightings import register_speech_sightings

        source_url = f"https://www.althingi.is/altext/raeda/{session}/{speech_id}.html"
        counts = register_speech_sightings(
            assessments=assessments,
            speech_id=speech_id,
            source_url=source_url,
            source_title=f"{speech['name']} — {speech['issue_title']}",
            source_date=_parse_date(speech["date"]),
        )
        print(f"  Sightings: {counts}")
    else:
        print("  (dry run — sightings not registered)")

    # Save summary
    summary = {
        "speech_id": speech_id,
        "speaker": speech["name"],
        "party": speech["party"],
        "speech_type": speech["speech_type"],
        "issue_title": speech["issue_title"],
        "date": speech["date"],
        "word_count": speech["word_count"],
        "claims_extracted": len(claims),
        "claims_assessed": len(assessments),
        "verdicts": verdict_counts,
        "processed_at": datetime.now().isoformat(),
    }
    (work_dir / "_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nDone. Summary saved to {work_dir / '_summary.json'}")


def cmd_batch(args: argparse.Namespace) -> None:
    """Run fact-check pipeline on top N speeches."""
    candidates = select_speeches_for_batch(
        limit=args.limit,
        min_words=args.min_words,
        exclude_checked=True,
    )

    if not candidates:
        print("No unchecked candidate speeches found.")
        return

    print(f"Processing {len(candidates)} speeches...\n")
    for i, c in enumerate(candidates, 1):
        print(f"═══ [{i}/{len(candidates)}] {c['name']} — {c['speech_type']} ═══")
        # Create a namespace with the same args
        run_args = argparse.Namespace(
            speech_id=c["speech_id"],
            dry_run=args.dry_run,
        )
        try:
            cmd_run(run_args)
        except SystemExit:
            print(f"  Skipping {c['speech_id']} (error)")
        except Exception as e:
            print(f"  Error processing {c['speech_id']}: {e}")
        print()


def cmd_status(args: argparse.Namespace) -> None:
    """Show fact-checking progress stats."""
    # Count processed speeches from work dirs
    speech_checks_dir = Path("data/speech_checks")
    processed = []
    if speech_checks_dir.exists():
        for d in sorted(speech_checks_dir.iterdir()):
            summary_path = d / "_summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                processed.append(summary)

    print("Speech fact-check status")
    print(f"  Processed speeches: {len(processed)}")

    if processed:
        total_claims = sum(s.get("claims_assessed", 0) for s in processed)
        print(f"  Total claims assessed: {total_claims}")

        # Aggregate verdicts
        all_verdicts: dict[str, int] = {}
        for s in processed:
            for v, count in s.get("verdicts", {}).items():
                all_verdicts[v] = all_verdicts.get(v, 0) + count
        if all_verdicts:
            print("  Verdict breakdown:")
            for v, count in sorted(all_verdicts.items()):
                print(f"    {v}: {count}")

    # Check DB sightings
    try:
        from esbvaktin.ground_truth.operations import get_connection

        conn = get_connection()
        row = conn.execute(
            "SELECT COUNT(*) FROM claim_sightings WHERE source_type = 'althingi'"
        ).fetchone()
        print(f"  DB sightings (althingi): {row[0]}")

        row = conn.execute(
            "SELECT COUNT(DISTINCT speech_id) FROM claim_sightings "
            "WHERE source_type = 'althingi' AND speech_id IS NOT NULL"
        ).fetchone()
        print(f"  Unique speeches checked: {row[0]}")
        conn.close()
    except Exception:
        print("  (DB not available for sighting counts)")


def _run_subagent(task: str, output_path: Path) -> None:
    """Run a Claude Code subagent via subprocess."""
    result = subprocess.run(
        [
            "claude",
            "-p",
            task,
            "--output-format",
            "text",
            "--max-turns",
            "3",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        print(f"  Subagent stderr: {result.stderr[:500]}", file=sys.stderr)
    # If the output file wasn't written by the subagent, try to capture stdout
    if not output_path.exists() and result.stdout.strip():
        output_path.write_text(result.stdout, encoding="utf-8")


def _parse_date(date_str: str) -> date | None:
    """Parse a date string (YYYY-MM-DD) or return None."""
    if not date_str or date_str == "?":
        return None
    try:
        return date.fromisoformat(date_str[:10])
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fact-check Alþingi EU speeches against the evidence DB"
    )
    sub = parser.add_subparsers(dest="command")

    # select
    sel = sub.add_parser("select", help="List candidate speeches for fact-checking")
    sel.add_argument("--limit", type=int, default=10)
    sel.add_argument("--min-words", type=int, default=300)
    sel.add_argument(
        "--include-checked", action="store_true", help="Include already-checked speeches"
    )

    # run
    run = sub.add_parser("run", help="Fact-check a single speech")
    run.add_argument("speech_id", help="althingi.db speech_id")
    run.add_argument("--dry-run", action="store_true", help="Skip sighting registration")

    # batch
    bat = sub.add_parser("batch", help="Fact-check top N speeches")
    bat.add_argument("--limit", type=int, default=5)
    bat.add_argument("--min-words", type=int, default=300)
    bat.add_argument("--dry-run", action="store_true", help="Skip sighting registration")

    # status
    sub.add_parser("status", help="Show fact-checking progress")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "select": cmd_select,
        "run": cmd_run,
        "batch": cmd_batch,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
