"""Identify high-value Alþingi speeches for evidence DB curation.

Queries althingi.db for ministerial statements, sponsor speeches
(flutningsræður), and significant opposition speeches on EU topics.
Outputs candidate speeches as draft evidence seed JSON for review.

Usage:
    # List candidate speeches (default: top 20 by relevance):
    uv run python scripts/curate_speech_evidence.py list

    # List with more results:
    uv run python scripts/curate_speech_evidence.py list --limit 50

    # Export draft seed JSON for specific speech IDs:
    uv run python scripts/curate_speech_evidence.py export rad20260309T171000 rad20260309T182328

    # Export all candidates above a word count threshold:
    uv run python scripts/curate_speech_evidence.py export --min-words 800
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path
from textwrap import shorten

_DEFAULT_DB = Path.home() / "althingi" / "althingi-mcp" / "data" / "althingi.db"

EU_ISSUE_PATTERNS = [
    "%Evróp%", "%ESB%", "%aðild%Evrópu%", "%aðildarviðræð%",
    "%aðildarumsókn%", "%þjóðaratkvæðagreiðsl%", "%Evrópumál%",
]

# Speech types ranked by evidence value
HIGH_VALUE_TYPES = ["flutningsræða", "ráðherraræða"]
MEDIUM_VALUE_TYPES = ["ræða", "svar"]

# Known key figures for prioritisation
KEY_FIGURES = {
    "Þorgerður Katrín Gunnarsdóttir",  # Foreign Minister
    "Kristrún Frostadóttir",  # Prime Minister
    "Sigmundur Davíð Gunnlaugsson",  # Centre Party leader
    "Guðrún Hafsteinsdóttir",  # Independence Party
    "Bjarni Benediktsson",  # Former PM/FM
    "Guðlaugur Þór Þórðarson",  # Former FM
    "Logi Einarsson",  # Samfylkingin (earlier referendum proposals)
    "Diljá Mist Einarsdóttir",  # Viðreisn
}

# Topic classification by issue title keywords
TOPIC_KEYWORDS = {
    "fisheries": ["sjávarút", "fiskveiði", "kvóta", "auðlind"],
    "sovereignty": ["þjóðaratkvæðagreiðsl", "aðild", "fullveld"],
    "eea_eu_law": ["Evrópska efnahagssvæðið", "EES", "bókun"],
    "trade": ["viðskipta", "losunarheim", "ETS", "tollar"],
    "party_positions": ["forræði", "afstaða"],
}


def _connect() -> sqlite3.Connection:
    db_path = Path(os.environ.get("ALTHINGI_DB_PATH", str(_DEFAULT_DB)))
    if not db_path.exists():
        print(f"Error: althingi.db not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _issue_filter_sql() -> tuple[str, list[str]]:
    clause = " OR ".join(f"s.issue_title LIKE ?" for _ in EU_ISSUE_PATTERNS)
    return clause, list(EU_ISSUE_PATTERNS)


def _classify_topic(issue_title: str) -> str:
    title_lower = issue_title.lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw.lower() in title_lower for kw in keywords):
            return topic
    return "sovereignty"  # default for EU-related


def _score_speech(row: sqlite3.Row) -> float:
    """Score a speech by evidence value (higher = more valuable)."""
    score = 0.0

    # Speech type priority
    if row["speech_type"] in HIGH_VALUE_TYPES:
        score += 3.0
    elif row["speech_type"] in MEDIUM_VALUE_TYPES:
        score += 1.0

    # Key figure bonus
    if row["name"] in KEY_FIGURES:
        score += 2.0

    # Word count bonus (substantive speeches)
    wc = row["word_count"] or 0
    if wc > 1500:
        score += 2.0
    elif wc > 800:
        score += 1.0
    elif wc < 300:
        score -= 1.0

    # Recency bonus
    speech_date = row["date"][:10] if row["date"] else "2000-01-01"
    year = int(speech_date[:4])
    if year >= 2026:
        score += 2.0
    elif year >= 2024:
        score += 1.0

    return score


def list_candidates(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Find and rank candidate speeches for evidence curation."""
    issue_clause, params = _issue_filter_sql()

    sql = f"""
        SELECT s.speech_id, s.name, s.date, s.issue_title,
               s.speech_type, t.word_count, t.party
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE ({issue_clause})
          AND t.word_count > 250
        ORDER BY s.date DESC
    """
    rows = conn.execute(sql, params).fetchall()

    candidates = []
    for row in rows:
        score = _score_speech(row)
        candidates.append({
            "speech_id": row["speech_id"],
            "name": row["name"],
            "date": row["date"][:10] if row["date"] else "?",
            "issue_title": row["issue_title"],
            "speech_type": row["speech_type"],
            "word_count": row["word_count"] or 0,
            "party": row["party"] or "?",
            "score": score,
            "topic": _classify_topic(row["issue_title"]),
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:limit]


def export_drafts(
    conn: sqlite3.Connection,
    speech_ids: list[str] | None = None,
    min_words: int = 0,
) -> list[dict]:
    """Export draft evidence seed entries for specified speeches."""
    issue_clause, base_params = _issue_filter_sql()

    if speech_ids:
        placeholders = ", ".join("?" for _ in speech_ids)
        sql = f"""
            SELECT s.speech_id, s.name, s.date, s.issue_title,
                   s.speech_type, t.word_count, t.party,
                   substr(t.full_text, 1, 3000) AS excerpt
            FROM speeches s
            LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
            WHERE s.speech_id IN ({placeholders})
        """
        rows = conn.execute(sql, speech_ids).fetchall()
    else:
        sql = f"""
            SELECT s.speech_id, s.name, s.date, s.issue_title,
                   s.speech_type, t.word_count, t.party,
                   substr(t.full_text, 1, 3000) AS excerpt
            FROM speeches s
            LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
            WHERE ({issue_clause})
              AND t.word_count >= ?
              AND s.speech_type IN ('flutningsræða', 'ráðherraræða', 'ræða')
            ORDER BY s.date DESC
            LIMIT 30
        """
        rows = conn.execute(sql, base_params + [min_words]).fetchall()

    drafts = []
    for i, row in enumerate(rows, 1):
        topic = _classify_topic(row["issue_title"])
        topic_prefix = {
            "fisheries": "FISH",
            "sovereignty": "SOV",
            "eea_eu_law": "EEA",
            "trade": "TRADE",
            "party_positions": "PARTY",
        }.get(topic, "SOV")

        excerpt = (row["excerpt"] or "").replace("\n", " ").strip()
        excerpt = shorten(excerpt, width=500, placeholder="…")

        speech_type_is = row["speech_type"] or "ræða"
        session = "157" if row["date"] and row["date"] >= "2025-09" else "156"

        drafts.append({
            "evidence_id": f"{topic_prefix}-PARL-{900 + i:03d}",
            "domain": "political" if topic in ("sovereignty", "party_positions") else ("legal" if topic == "eea_eu_law" else "economic"),
            "topic": topic,
            "subtopic": "REVIEW_AND_SET",
            "statement": f"[DRAFT — summarise from excerpt] {excerpt}",
            "source_name": f"Alþingi — {row['name']}, {row['party']} ({speech_type_is}, {session}. löggjafarþing)",
            "source_url": f"https://www.althingi.is/altext/raeda/{session}/{row['speech_id']}.html",
            "source_date": row["date"][:10] if row["date"] else None,
            "source_type": "parliamentary_record",
            "confidence": "high",
            "caveats": "REVIEW — add speech-specific caveats",
            "related_entries": [],
            "_meta": {
                "speech_id": row["speech_id"],
                "word_count": row["word_count"] or 0,
                "speech_type": speech_type_is,
            },
        })

    return drafts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Identify high-value Alþingi speeches for evidence curation"
    )
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser("list", help="List candidate speeches")
    list_parser.add_argument("--limit", type=int, default=20)

    export_parser = sub.add_parser("export", help="Export draft seed JSON")
    export_parser.add_argument("speech_ids", nargs="*", help="Specific speech IDs")
    export_parser.add_argument("--min-words", type=int, default=800)
    export_parser.add_argument("-o", "--output", type=str, help="Output file path")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    conn = _connect()

    if args.command == "list":
        candidates = list_candidates(conn, limit=args.limit)
        print(f"{'Score':>5}  {'Date':10}  {'Words':>5}  {'Type':15}  {'Speaker':35}  {'Issue'}")
        print("-" * 120)
        for c in candidates:
            print(
                f"{c['score']:5.1f}  {c['date']:10}  {c['word_count']:5}  "
                f"{c['speech_type']:15}  {c['name']:35}  "
                f"{shorten(c['issue_title'], width=50, placeholder='…')}"
            )

    elif args.command == "export":
        drafts = export_drafts(
            conn,
            speech_ids=args.speech_ids or None,
            min_words=args.min_words,
        )

        # Strip _meta for clean output
        clean_drafts = []
        for d in drafts:
            meta = d.pop("_meta", {})
            clean_drafts.append(d)
            print(
                f"  {d['evidence_id']}: {meta.get('speech_id', '?')} "
                f"({meta.get('word_count', 0)} words)",
                file=sys.stderr,
            )

        output = json.dumps(clean_drafts, indent=2, ensure_ascii=False, default=str)
        if args.output:
            Path(args.output).write_text(output + "\n")
            print(f"\nWrote {len(clean_drafts)} drafts to {args.output}", file=sys.stderr)
        else:
            print(output)

    conn.close()


if __name__ == "__main__":
    main()
