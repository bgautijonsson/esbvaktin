"""Prepare Alþingi EU debate data for the esbvaktin-site.

Queries althingi.db directly (sync sqlite3, read-only) and exports:
  - _data/debates/{session}-{issue_nr}.json  (individual debate detail)
  - assets/data/debates.json                  (lightweight listing for client-side JS)

Usage:
    uv run python scripts/prepare_speeches.py --site-dir ~/esbvaktin-site
    uv run python scripts/prepare_speeches.py --status
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE_DIR = PROJECT_ROOT.parent / "esbvaktin-site"
_ALTHINGI_DB_DEFAULT = Path.home() / "althingi" / "althingi-mcp" / "data" / "althingi.db"

EU_ISSUE_PATTERNS = [
    "%Evróp%", "%ESB%", "%aðild%Evrópu%", "%aðildarviðræð%",
    "%aðildarumsókn%", "%þjóðaratkvæðagreiðsl%", "%Evrópumál%",
]


# ── Helpers ──────────────────────────────────────────────────────────


def _db_path() -> Path:
    return Path(os.environ.get("ALTHINGI_DB_PATH", str(_ALTHINGI_DB_DEFAULT)))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if not path.exists():
        print(f"Error: althingi.db not found at {path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _issue_filter_sql(alias: str = "s") -> tuple[str, list[str]]:
    """Build WHERE clause for EU issue title patterns."""
    clause = " OR ".join(f"{alias}.issue_title LIKE ?" for _ in EU_ISSUE_PATTERNS)
    return f"({clause})", list(EU_ISSUE_PATTERNS)


def _capitalise_first(text: str) -> str:
    """Capitalise the first character of a string (preserving the rest)."""
    if not text:
        return text
    return text[0].upper() + text[1:]


def icelandic_slugify(text: str) -> str:
    """Create a URL-safe slug from Icelandic text."""
    replacements = {
        "þ": "th", "Þ": "th", "ð": "d", "Ð": "d",
        "æ": "ae", "Æ": "ae", "ö": "o", "Ö": "o",
        "á": "a", "Á": "a", "é": "e", "É": "e",
        "í": "i", "Í": "i", "ó": "o", "Ó": "o",
        "ú": "u", "Ú": "u", "ý": "y", "Ý": "y",
    }
    slug = text
    for orig, repl in replacements.items():
        slug = slug.replace(orig, repl)
    slug = unicodedata.normalize("NFKD", slug)
    slug = slug.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


# ── Party display names ──────────────────────────────────────────────

PARTY_SHORT = {
    "Sjálfstæðisflokkur": "xD",
    "Samfylkingin": "S",
    "Framsóknarflokkur": "B",
    "Miðflokkurinn": "M",
    "Viðreisn": "C",
    "Vinstrihreyfingin - grænt framboð": "V",
    "Píratar": "P",
    "Flokkur fólksins": "F",
    "Hreyfingin": "HR",
}

PARTY_COLOURS = {
    "Sjálfstæðisflokkur": "#003897",
    "Samfylkingin": "#e30613",
    "Framsóknarflokkur": "#007a33",
    "Miðflokkurinn": "#003459",
    "Viðreisn": "#ff8c00",
    "Vinstrihreyfingin - grænt framboð": "#00843d",
    "Píratar": "#660099",
    "Flokkur fólksins": "#ffdd00",
    "Hreyfingin": "#009fe3",
}


# ── Data loading ─────────────────────────────────────────────────────


def load_debates(conn: sqlite3.Connection) -> list[dict]:
    """Load all EU-related debates with aggregate stats."""
    where, params = _issue_filter_sql()
    sql = f"""
        SELECT s.session, s.issue_nr, s.issue_title,
               COUNT(*) AS speech_count,
               COUNT(DISTINCT s.mp_id) AS speaker_count,
               SUM(COALESCE(t.word_count, 0)) AS total_words,
               MIN(s.date) AS first_date,
               MAX(s.date) AS last_date
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE {where}
        GROUP BY s.session, s.issue_nr, s.issue_title
        ORDER BY last_date DESC, speech_count DESC
    """
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def load_debate_speakers(
    conn: sqlite3.Connection, session: int, issue_nr: str, issue_title: str
) -> list[dict]:
    """Load speaker stats for a specific debate."""
    sql = """
        SELECT s.name AS speaker, t.party,
               COUNT(*) AS speech_count,
               SUM(COALESCE(t.word_count, 0)) AS total_words
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE s.session = ? AND s.issue_nr = ? AND s.issue_title = ?
        GROUP BY s.name, t.party
        ORDER BY total_words DESC
    """
    rows = conn.execute(sql, (session, issue_nr, issue_title)).fetchall()
    return [dict(r) for r in rows]


def load_debate_speeches(
    conn: sqlite3.Connection, session: int, issue_nr: str, issue_title: str
) -> list[dict]:
    """Load individual speeches for a debate timeline."""
    sql = """
        SELECT s.speech_id, s.name AS speaker, s.mp_id, s.date,
               s.started, s.ended, s.speech_type,
               t.party, t.word_count,
               substr(t.full_text, 1, 500) AS excerpt
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE s.session = ? AND s.issue_nr = ? AND s.issue_title = ?
        ORDER BY s.started ASC
    """
    rows = conn.execute(sql, (session, issue_nr, issue_title)).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        # Clean excerpt
        if d.get("excerpt"):
            d["excerpt"] = d["excerpt"].replace("\n", " ").strip()
            if len(d["excerpt"]) >= 490:
                d["excerpt"] = d["excerpt"].rsplit(" ", 1)[0] + "…"
        results.append(d)
    return results


# ── Export ───────────────────────────────────────────────────────────


def make_slug(session: int, issue_nr: str) -> str:
    """Debate slug: {session}-{issue_nr}."""
    return f"{session}-{issue_nr}"


def build_debate_detail(
    debate: dict, speakers: list[dict], speeches: list[dict]
) -> dict:
    """Build the full detail JSON for one debate (for 11ty pagination)."""
    slug = make_slug(debate["session"], debate["issue_nr"])
    title_slug = icelandic_slugify(debate["issue_title"][:80])
    parties = sorted({s["party"] for s in speakers if s.get("party")})

    title = _capitalise_first(debate["issue_title"])

    return {
        "slug": slug,
        "title_slug": title_slug,
        "session": debate["session"],
        "issue_nr": str(debate["issue_nr"]),
        "issue_title": title,
        "speech_count": debate["speech_count"],
        "speaker_count": debate["speaker_count"],
        "total_words": debate["total_words"],
        "first_date": debate["first_date"],
        "last_date": debate["last_date"],
        "althingi_url": (
            f"https://www.althingi.is/thingstorf/thingmalalistar-eftir-thingum/"
            f"ferill/?ltg={debate['session']}&mnr={debate['issue_nr']}"
        ),
        "parties": parties,
        "speakers": [
            {
                "name": s["speaker"],
                "party": s.get("party", ""),
                "speech_count": s["speech_count"],
                "total_words": s["total_words"],
            }
            for s in speakers
        ],
        "speeches": [
            {
                "speech_id": s["speech_id"],
                "speaker": s["speaker"],
                "party": s.get("party", ""),
                "date": s.get("date", ""),
                "started": s.get("started", ""),
                "speech_type": s.get("speech_type", ""),
                "word_count": s.get("word_count", 0),
                "excerpt": s.get("excerpt", ""),
            }
            for s in speeches
        ],
    }


def build_listing_entry(detail: dict) -> dict:
    """Lightweight version for the client-side listing (no speech texts)."""
    return {
        "slug": detail["slug"],
        "session": detail["session"],
        "issue_nr": detail["issue_nr"],
        "issue_title": detail["issue_title"],
        "speech_count": detail["speech_count"],
        "speaker_count": detail["speaker_count"],
        "total_words": detail["total_words"],
        "first_date": detail["first_date"],
        "last_date": detail["last_date"],
        "althingi_url": detail["althingi_url"],
        "parties": detail["parties"],
        "top_speakers": [
            {"name": s["name"], "party": s["party"], "words": s["total_words"]}
            for s in detail["speakers"][:5]
        ],
        "speaker_names": [s["name"] for s in detail["speakers"]],
    }


# ── Main ─────────────────────────────────────────────────────────────


def status(conn: sqlite3.Connection) -> None:
    """Print summary statistics."""
    debates = load_debates(conn)
    total_speeches = sum(d["speech_count"] for d in debates)
    total_words = sum(d["total_words"] for d in debates)
    sessions = sorted({d["session"] for d in debates})

    print(f"EU debates:    {len(debates)}")
    print(f"Total speeches: {total_speeches:,}")
    print(f"Total words:    {total_words:,}")
    print(f"Sessions:       {min(sessions)}–{max(sessions)} ({len(sessions)} sessions)")
    if debates:
        print(f"Date range:     {debates[-1]['first_date']} – {debates[0]['last_date']}")

    # Top 10 by speech count
    top = sorted(debates, key=lambda d: d["speech_count"], reverse=True)[:10]
    print("\nTop 10 debates by speech count:")
    for d in top:
        print(f"  {d['session']}-{d['issue_nr']:>4}  {d['speech_count']:>3} speeches  {d['issue_title'][:70]}")


def export(conn: sqlite3.Connection, site_dir: Path) -> None:
    """Export debate data to the site repo."""
    debates_data_dir = site_dir / "_data" / "debates"
    debates_data_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = site_dir / "assets" / "data"
    assets_dir.mkdir(parents=True, exist_ok=True)

    debates = load_debates(conn)
    print(f"Found {len(debates)} EU debates")

    details = []
    seen_slugs: dict[str, str] = {}

    for i, debate in enumerate(debates):
        slug = make_slug(debate["session"], debate["issue_nr"])

        # Handle slug collisions (same session+issue_nr, different titles)
        if slug in seen_slugs:
            # Append title hash to disambiguate
            title_hash = icelandic_slugify(debate["issue_title"][:30])[:12]
            slug = f"{slug}-{title_hash}"

        seen_slugs[slug] = debate["issue_title"]

        speakers = load_debate_speakers(
            conn, debate["session"], debate["issue_nr"], debate["issue_title"]
        )
        speeches = load_debate_speeches(
            conn, debate["session"], debate["issue_nr"], debate["issue_title"]
        )

        detail = build_debate_detail(debate, speakers, speeches)
        detail["slug"] = slug  # Use disambiguated slug
        details.append(detail)

        # Write individual debate JSON
        out_path = debates_data_dir / f"{slug}.json"
        out_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2) + "\n")

        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(debates)} debates…")

    # Write listing JSON
    listing = [build_listing_entry(d) for d in details]
    listing_path = assets_dir / "debates.json"
    listing_path.write_text(json.dumps(listing, ensure_ascii=False, indent=2) + "\n")

    print(f"Wrote {len(details)} debate detail files to {debates_data_dir}")
    print(f"Wrote listing ({len(listing)} entries) to {listing_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Alþingi EU debate data for site")
    parser.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)
    parser.add_argument("--status", action="store_true", help="Show stats only")
    args = parser.parse_args()

    conn = _connect()
    try:
        if args.status:
            status(conn)
        else:
            export(conn, args.site_dir)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
