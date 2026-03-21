"""Extract rhetorical claims from Alþingi speeches for Heimildin analysis.

Usage:
    uv run python scripts/heimildin/extract_claims.py list-speeches [--era esb|ees] [--issue ISSUE] [--include-replies]
    uv run python scripts/heimildin/extract_claims.py prepare [--era esb] [--issue 516] [--limit 10] [--include-replies]
    uv run python scripts/heimildin/extract_claims.py parse [--era esb]
    uv run python scripts/heimildin/extract_claims.py status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import (
    DEBATES,
    DELIVERABLES_DIR,
    EU_TITLE_PATTERNS,
    KNOWN_TOPICS,
    MIN_WORDS_REPLY,
    MIN_WORDS_SPEECH,
    REPLY_TYPES,
    SUBSTANTIVE_TYPES,
    WORK_DIR,
    connect,
    is_eu_relevant,
    speech_url,
)


def _speech_types(include_replies: bool) -> set[str]:
    """Get the set of speech types to include."""
    types = set(SUBSTANTIVE_TYPES)
    if include_replies:
        types |= REPLY_TYPES
    return types


def _min_words(speech_type: str) -> int:
    """Get minimum word count for a speech type."""
    if speech_type in REPLY_TYPES:
        return MIN_WORDS_REPLY
    return MIN_WORDS_SPEECH


# ---------------------------------------------------------------------------
# list-speeches: show available speeches for a debate
# ---------------------------------------------------------------------------


def list_speeches(era: str, issue_nr: str | None = None,
                  include_replies: bool = False) -> None:
    """List substantive speeches from target debates."""
    debates = DEBATES.get(era, [])
    if not debates:
        print(f"Unknown era: {era}")
        sys.exit(1)

    types = _speech_types(include_replies)
    conn = connect()
    try:
        for debate in debates:
            if issue_nr and debate["issue_nr"] != issue_nr:
                continue

            rows = conn.execute(
                """
                SELECT s.speech_id, s.name, s.date, s.speech_type,
                       s.issue_title, t.word_count, t.party, s.session
                FROM speeches s
                LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
                WHERE s.issue_nr = ?
                  AND s.session = ?
                  AND s.speech_type IN ({})
                ORDER BY s.date, s.started
                """.format(",".join("?" for _ in types)),
                [debate["issue_nr"], debate["session"], *types],
            ).fetchall()

            # Filter by word count and EU relevance
            filtered = []
            skipped_offtopic = 0
            skipped_short = 0
            for row in rows:
                wc = row["word_count"] or 0
                min_wc = _min_words(row["speech_type"])
                if wc < min_wc:
                    skipped_short += 1
                    continue
                if not is_eu_relevant(row["issue_title"] or ""):
                    skipped_offtopic += 1
                    continue
                filtered.append(row)

            print(f"\n## {debate['title']} (issue {debate['issue_nr']}, "
                  f"session {debate['session']})")
            print(f"{'ID':<28} {'Speaker':<35} {'Party':<25} {'Words':>6} "
                  f"{'Date':<12} {'Type'}")
            print("-" * 130)

            total_words = 0
            for row in filtered:
                wc = row["word_count"] or 0
                total_words += wc
                date = row["date"][:10] if row["date"] else "?"
                party = row["party"] or "?"
                print(f"{row['speech_id']:<28} {row['name']:<35} "
                      f"{party:<25} {wc:>6} {date:<12} {row['speech_type']}")

            print(f"\nTotal: {len(filtered)} speeches, {total_words:,} words")
            if skipped_short:
                print(f"  Skipped {skipped_short} below word minimum")
            if skipped_offtopic:
                print(f"  Skipped {skipped_offtopic} off-topic")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# prepare: fetch speeches and write extraction context files
# ---------------------------------------------------------------------------

EXTRACTION_INSTRUCTIONS = """\
# Rhetorical Claim Extraction — Heimildin Project

## Context

This is a comparative analysis of Alþingi debate rhetoric for the Icelandic
newspaper Heimildin. We are extracting rhetorical and political claims from
parliamentary speeches to compare argumentation patterns between eras.

**This is NOT fact-checking.** We want ALL substantive arguments, opinions,
predictions, and assertions — not just verifiable factual claims.

## What to extract

Extract every distinct argument, assertion, or claim the speaker makes.
This includes:

- **Factual claims**: "Ísland flytur út 40% af sjávarafurðum til ESB"
- **Predictions**: "Aðild mun leiða til atvinnuaukningar"
- **Sovereignty arguments**: "Við munum missa fullveldi okkar"
- **Comparisons**: "Noregur sýnir að þetta virkar ekki"
- **Value claims**: "Sjálfstæði þjóðarinnar er mikilvægara en efnahagslegur ávinningur"
- **Process claims**: "Ríkisstjórnin hefur ekki veitt nægar upplýsingar"

## What to SKIP

- Parliamentary procedure ("Virðulegi forseti", "ég þakka hv. þingmanni")
- Pure rhetorical questions with no implicit claim
- Repetitions of the same claim within the same speech (extract only once)
- References to what other speakers said (unless the speaker endorses/adopts the claim)

## Output format

Write a JSON array where each element has:

```json
{{
    "exact_quote": "The relevant passage from the speech (1-3 sentences, Icelandic)",
    "claim_summary": "Simplified claim in third person, present tense (Icelandic)",
    "topic": "One of: {topics}",
    "stance": "pro_eu | anti_eu | neutral"
}}
```

### Rules for `claim_summary`

The summary should be written so that identical arguments from different
speakers produce the same (or very similar) summary text. This is critical
for frequency counting.

- Use third person, present tense: "Aðild að ESB mun..." not "Við munum..."
- Strip parliamentary rhetoric — focus on the core argument
- Keep it concise: one sentence, ~10-25 words
- Use Icelandic with correct Unicode characters (þ, ð, á, é, í, ó, ú, ý, æ, ö)

### Rules for `exact_quote`

- Copy the relevant 1-3 sentences verbatim from the speech
- Must be directly attributable to this speaker
- Prefer the most concise passage that captures the claim

### JSON safety

- NEVER use Icelandic „…" quotes inside JSON strings — they break parsing
- Use «…» (guillemets) or escaped \\"...\\" if you need quotes within strings
- Ensure valid JSON that can be parsed by `json.loads()`

## Speech to analyse

"""


def prepare(era: str, issue_nr: str | None = None, limit: int | None = None,
            include_replies: bool = False) -> None:
    """Fetch speeches and write context files for extraction."""
    debates = DEBATES.get(era, [])
    if not debates:
        print(f"Unknown era: {era}")
        sys.exit(1)

    types = _speech_types(include_replies)
    conn = connect()
    prepared = 0

    try:
        for debate in debates:
            if issue_nr and debate["issue_nr"] != issue_nr:
                continue

            rows = conn.execute(
                """
                SELECT s.speech_id, s.name, s.date, s.speech_type,
                       s.issue_title, s.session,
                       t.word_count, t.party, t.full_text
                FROM speeches s
                LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
                WHERE s.issue_nr = ?
                  AND s.session = ?
                  AND s.speech_type IN ({})
                ORDER BY t.word_count DESC
                """.format(",".join("?" for _ in types)),
                [debate["issue_nr"], debate["session"], *types],
            ).fetchall()

            for row in rows:
                if limit and prepared >= limit:
                    break

                sid = row["speech_id"]
                wc = row["word_count"] or 0
                min_wc = _min_words(row["speech_type"])

                # Skip short speeches
                if wc < min_wc:
                    continue

                # P1.4: Skip off-topic speeches
                if not is_eu_relevant(row["issue_title"] or ""):
                    print(f"  skip {sid} (off-topic: {row['issue_title'][:50]})")
                    continue

                work = WORK_DIR / era / f"issue_{debate['issue_nr']}" / sid
                claims_file = work / "_claims.json"

                # Skip if already extracted
                if claims_file.exists():
                    continue

                work.mkdir(parents=True, exist_ok=True)

                # Build context file
                date = row["date"][:10] if row["date"] else "?"
                session = row["session"] or debate["session"]
                url = speech_url(session, sid)
                party = row["party"] or "?"

                topics_str = ", ".join(KNOWN_TOPICS)
                instructions = EXTRACTION_INSTRUCTIONS.format(topics=topics_str)

                metadata = (
                    f"- **Ræðumaður**: {row['name']}, {party}\n"
                    f"- **Dagsetning**: {date}\n"
                    f"- **Umræðuefni**: {row['issue_title']}\n"
                    f"- **Tegund**: {row['speech_type']}\n"
                    f"- **Orðafjöldi**: {wc}\n"
                    f"- **Heimild**: {url}\n"
                    f"- **Tímabil**: {'ESB-umræða (2024–2026)' if era == 'esb' else 'EES-umræða (1991–1993)'}\n"
                )

                context = (
                    instructions
                    + metadata
                    + "\n---\n\n"
                    + (row["full_text"] or "(enginn texti)")
                )

                (work / "_context_extraction.md").write_text(
                    context, encoding="utf-8"
                )

                # Write metadata JSON for later assembly
                meta = {
                    "speech_id": sid,
                    "speaker": row["name"],
                    "party": party,
                    "date": date,
                    "session": session,
                    "issue_nr": debate["issue_nr"],
                    "issue_title": row["issue_title"],
                    "speech_type": row["speech_type"],
                    "word_count": wc,
                    "url": url,
                    "era": era,
                }
                (work / "_meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                prepared += 1
                print(f"  prepared {sid} — {row['name']} ({wc} words, {row['speech_type']})")

            if limit and prepared >= limit:
                break

    finally:
        conn.close()

    print(f"\nPrepared {prepared} speeches in {WORK_DIR / era}/")
    print(f"Run claim-extractor agent on each _context_extraction.md → _claims.json")


# ---------------------------------------------------------------------------
# parse: read extraction outputs and merge into unified format
# Uses stable instance_id = "{speech_id}:{n}" instead of global array index
# ---------------------------------------------------------------------------


def parse(era: str) -> None:
    """Parse _claims.json files and merge into a unified claim instances list."""
    era_dir = WORK_DIR / era
    if not era_dir.exists():
        print(f"No work directory for era '{era}'")
        sys.exit(1)

    all_claims = []
    speech_count = 0
    total_words = 0
    errors = []

    for claims_file in sorted(era_dir.rglob("_claims.json")):
        meta_file = claims_file.parent / "_meta.json"
        if not meta_file.exists():
            errors.append(f"Missing _meta.json for {claims_file.parent.name}")
            continue

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        sid = meta["speech_id"]

        raw = claims_file.read_text(encoding="utf-8")
        # Sanitise Icelandic quotes (same as esbvaktin pipeline)
        raw = raw.replace("\u201e", '"').replace("\u201c", '"')
        # Strip markdown fences if present
        if raw.strip().startswith("```"):
            lines = raw.strip().split("\n")
            raw = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            )

        try:
            claims = json.loads(raw)
        except json.JSONDecodeError as e:
            errors.append(f"JSON error in {claims_file}: {e}")
            continue

        if not isinstance(claims, list):
            errors.append(f"Expected list in {claims_file}, got {type(claims).__name__}")
            continue

        speech_count += 1
        total_words += meta.get("word_count", 0)

        for n, claim in enumerate(claims):
            instance_id = f"{sid}:{n}"
            all_claims.append({
                "instance_id": instance_id,
                "speech_id": meta["speech_id"],
                "speaker": meta["speaker"],
                "party": meta["party"],
                "date": meta["date"],
                "session": meta["session"],
                "speech_url": meta["url"],
                "era": meta["era"],
                "exact_quote": claim.get("exact_quote", ""),
                "claim_summary": claim.get("claim_summary", ""),
                "topic": claim.get("topic", "other"),
                "stance": claim.get("stance", "neutral"),
            })

    # Write merged output
    output_file = WORK_DIR / f"{era}_claims_raw.json"
    output_file.write_text(
        json.dumps(all_claims, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Write era stats for normalisation (P1.3)
    stats = {
        "era": era,
        "speeches": speech_count,
        "total_words": total_words,
        "total_claims": len(all_claims),
        "unique_speakers": len({c["speaker"] for c in all_claims}),
    }
    stats_file = WORK_DIR / f"{era}_stats.json"
    stats_file.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(f"Parsed {speech_count} speeches → {len(all_claims)} claim instances")
    print(f"  Words: {total_words:,}, Speakers: {stats['unique_speakers']}")
    print(f"Output: {output_file}")

    if errors:
        print(f"\n{len(errors)} errors:")
        for err in errors:
            print(f"  - {err}")


# ---------------------------------------------------------------------------
# status: show extraction progress
# ---------------------------------------------------------------------------


def status() -> None:
    """Show what's been prepared and extracted."""
    for era in ["esb", "ees"]:
        era_dir = WORK_DIR / era
        if not era_dir.exists():
            continue

        context_files = list(era_dir.rglob("_context_extraction.md"))
        claims_files = list(era_dir.rglob("_claims.json"))

        print(f"\n## {era.upper()} era")
        print(f"  Prepared: {len(context_files)} speeches")
        print(f"  Extracted: {len(claims_files)} speeches")
        print(f"  Remaining: {len(context_files) - len(claims_files)}")

        # Show per-issue breakdown
        issues = {}
        for cf in context_files:
            issue = cf.parent.parent.name
            issues.setdefault(issue, {"prepared": 0, "extracted": 0})
            issues[issue]["prepared"] += 1
        for cf in claims_files:
            issue = cf.parent.parent.name
            issues.setdefault(issue, {"prepared": 0, "extracted": 0})
            issues[issue]["extracted"] += 1

        for issue, counts in sorted(issues.items()):
            print(f"    {issue}: {counts['extracted']}/{counts['prepared']}")

    # Check for merged output
    for era in ["esb", "ees"]:
        merged = WORK_DIR / f"{era}_claims_raw.json"
        if merged.exists():
            data = json.loads(merged.read_text(encoding="utf-8"))
            print(f"\n  Merged {era.upper()}: {len(data)} claim instances")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract rhetorical claims from Alþingi speeches"
    )
    sub = parser.add_subparsers(dest="command")

    # list-speeches
    ls = sub.add_parser("list-speeches", help="List available speeches")
    ls.add_argument("--era", default="esb", choices=["esb", "ees"])
    ls.add_argument("--issue", default=None, help="Filter to specific issue number")
    ls.add_argument("--include-replies", action="store_true",
                    help="Include andsvör/svar (≥150 words)")

    # prepare
    prep = sub.add_parser("prepare", help="Prepare context files for extraction")
    prep.add_argument("--era", default="esb", choices=["esb", "ees"])
    prep.add_argument("--issue", default=None, help="Filter to specific issue number")
    prep.add_argument("--limit", type=int, default=None,
                      help="Max speeches to prepare")
    prep.add_argument("--include-replies", action="store_true",
                      help="Include andsvör/svar (≥150 words)")

    # parse
    p = sub.add_parser("parse", help="Parse extraction outputs into unified format")
    p.add_argument("--era", default="esb", choices=["esb", "ees"])

    # status
    sub.add_parser("status", help="Show extraction progress")

    args = parser.parse_args()

    if args.command == "list-speeches":
        list_speeches(args.era, args.issue, args.include_replies)
    elif args.command == "prepare":
        prepare(args.era, args.issue, args.limit, args.include_replies)
    elif args.command == "parse":
        parse(args.era)
    elif args.command == "status":
        status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
