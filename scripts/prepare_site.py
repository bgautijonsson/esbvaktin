"""Prepare analysis reports for the 11ty site.

Reads each data/analyses/*/_report_final.json, extracts key fields,
enriches with Icelandic text from report_text_is, and attaches evidence
source metadata (names + URLs) for rendering as hyperlinks.

Also parses _article.md to extract article metadata (source, URL, author,
date) and generates a lightweight listing JSON for client-side filtering.

Usage:
    uv run python scripts/prepare_site.py
    uv run python scripts/prepare_site.py --site-dir ~/esbvaktin-site
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"
EVIDENCE_META_PATH = PROJECT_ROOT / "data" / "export" / "evidence_meta.json"
DEFAULT_SITE_DIR = PROJECT_ROOT.parent / "esbvaktin-site"

# Evidence ID pattern: e.g. FISH-DATA-001, SOV-LEGAL-006
_EVIDENCE_ID_RE = re.compile(r"\b([A-Z]+-[A-Z]+-\d{3})\b")


# ── DB verdict overlay ──────────────────────────────────────────────


def _load_db_verdicts() -> dict[str, dict]:
    """Load current verdicts from the DB, keyed by claim text (IS and EN).

    Returns a dict mapping claim text → {verdict, explanation_is,
    confidence, supporting_evidence, contradicting_evidence, missing_context_is}.
    Used to overlay reassessed verdicts on top of _report_final.json snapshots.
    """
    try:
        from esbvaktin.ground_truth.operations import get_connection

        conn = get_connection()
        rows = conn.execute(
            "SELECT canonical_text_is, canonical_text_en, verdict, "
            "explanation_is, confidence, supporting_evidence, "
            "contradicting_evidence, missing_context_is "
            "FROM claims"
        ).fetchall()
        conn.close()
    except Exception:
        return {}

    lookup: dict[str, dict] = {}
    for text_is, text_en, verdict, expl_is, conf, sup, contra, missing in rows:
        entry = {
            "verdict": verdict,
            "explanation_is": expl_is,
            "confidence": conf,
            "supporting_evidence": sup or [],
            "contradicting_evidence": contra or [],
            "missing_context_is": missing,
        }
        if text_is:
            lookup[text_is] = entry
        if text_en:
            lookup[text_en] = entry
    return lookup

# ── Article metadata extraction ──────────────────────────────────────

_SOURCE_FROM_DOMAIN: dict[str, str] = {
    "visir.is": "Vísir",
    "mbl.is": "Morgunblaðið",
    "ruv.is": "RÚV",
    "heimildin.is": "Heimildin",
    "kjarninn.is": "Kjarninn",
    "stundin.is": "Stundin",
    "frettabladid.is": "Fréttablaðið",
}

_IS_MONTHS: dict[str, int] = {
    "janúar": 1, "febrúar": 2, "mars": 3, "apríl": 4,
    "maí": 5, "júní": 6, "júlí": 7, "ágúst": 8,
    "september": 9, "október": 10, "nóvember": 11, "desember": 12,
}


def _source_from_url(url: str) -> str | None:
    """Derive media outlet name from article URL domain."""
    try:
        host = urlparse(url).hostname or ""
        for domain, name in _SOURCE_FROM_DOMAIN.items():
            if host.endswith(domain):
                return name
    except Exception:
        pass
    return None


def _parse_is_date(text: str) -> str | None:
    """Parse Icelandic date like '9. mars 2026' to ISO 'YYYY-MM-DD'."""
    m = re.search(r"(\d{1,2})\.\s*(\w+)\s+(\d{4})", text)
    if m:
        day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = _IS_MONTHS.get(month_name)
        if month:
            return f"{year:04d}-{month:02d}-{day:02d}"
    # Already ISO?
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    return None


def _parse_article_meta(analysis_dir: Path) -> dict:
    """Extract article metadata from _article.md.

    Returns dict with keys: article_source, article_url, article_author, article_date.
    All values may be None if not found.
    """
    meta: dict[str, str | None] = {
        "article_source": None,
        "article_url": None,
        "article_author": None,
        "article_date": None,
    }

    article_path = analysis_dir / "_article.md"
    if not article_path.exists():
        return meta

    text = article_path.read_text(encoding="utf-8")

    # ── Format 1: YAML frontmatter ───────────────────────────────
    yaml_match = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
    if yaml_match:
        block = yaml_match.group(1)
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip().strip('"').strip("'")
            if key == "url" and val:
                meta["article_url"] = val
            elif key == "date" and val:
                meta["article_date"] = _parse_is_date(val)
            elif key == "title" and val:
                pass  # title comes from report JSON
            elif key == "author" and val:
                meta["article_author"] = val
        # Derive source from URL domain
        if meta["article_url"]:
            meta["article_source"] = _source_from_url(meta["article_url"])
        return meta

    # ── Format 2: Pipe-separated metadata line ───────────────────
    # **Heimild:** X | **Dagsetning:** Y | **Höfundur:** Z
    pipe_match = re.search(
        r"\*\*Heimild:\*\*\s*(.+?)\s*\|\s*\*\*Dagsetning:\*\*\s*(.+?)\s*\|\s*\*\*Höfundur:\*\*\s*(.+)",
        text,
    )
    if pipe_match:
        meta["article_source"] = pipe_match.group(1).strip()
        meta["article_date"] = _parse_is_date(pipe_match.group(2).strip())
        meta["article_author"] = pipe_match.group(3).strip()
        # URL on a separate line
        url_match = re.search(r"\*\*URL:\*\*\s*(https?://\S+)", text)
        if url_match:
            meta["article_url"] = url_match.group(1).strip()
        return meta

    # ── Format 2b: English pipe-separated (fréttasafn transcripts) ─
    # **Source:** X | **Date:** Y | **URL:** Z
    pipe_en = re.search(
        r"\*\*Source:\*\*\s*(.+?)\s*\|\s*\*\*Date:\*\*\s*(\S+)",
        text,
    )
    if pipe_en:
        meta["article_source"] = pipe_en.group(1).strip()
        date_str = pipe_en.group(2).strip()
        # Handle ISO datetime (2026-03-10T12:38:51) → date only
        meta["article_date"] = date_str[:10] if len(date_str) >= 10 else date_str
        url_match = re.search(r"\*\*URL:\*\*\s*(https?://\S+)", text)
        if url_match:
            meta["article_url"] = url_match.group(1).strip()
        return meta

    # ── Format 3: Key-value lines (bold or plain) ────────────────
    # **Heimild:** X  or  Heimild: X  (colon required to avoid matching body text)
    heimild = re.search(r"\*?\*?Heimild:\*?\*?\s*(.+)", text)
    if heimild:
        meta["article_source"] = heimild.group(1).strip()
    hofundur = re.search(r"\*?\*?Höfundur:\*?\*?\s*(.+)", text)
    if hofundur:
        meta["article_author"] = hofundur.group(1).strip()
    dagsetning = re.search(r"\*?\*?Dagsetning:\*?\*?\s*(.+)", text)
    if dagsetning:
        meta["article_date"] = _parse_is_date(dagsetning.group(1).strip())
    url_match = re.search(r"\*?\*?URL:\*?\*?\s*(https?://\S+)", text)
    if url_match:
        meta["article_url"] = url_match.group(1).strip()

    # If we found structured keys, return
    if meta["article_source"] or meta["article_url"]:
        # Try to derive source from URL if not found
        if not meta["article_source"] and meta["article_url"]:
            meta["article_source"] = _source_from_url(meta["article_url"])
        return meta

    # ── Format 4: Inline byline "Author skrifar — date — Source" ─
    byline = re.search(
        r"(.+?)\s+skrifar\s*[—–-]\s*(.+?)\s*[—–-]\s*(\S+)", text
    )
    if byline:
        meta["article_author"] = byline.group(1).strip().lstrip("*")
        meta["article_date"] = _parse_is_date(byline.group(2).strip())
        meta["article_source"] = byline.group(3).strip().rstrip("*")
        return meta

    # ── Format 5: Detect source from content clues ───────────────
    if "Viltu birta grein á Vísi" in text or "visir.is" in text or "Vísir/" in text:
        meta["article_source"] = "Vísir"
    elif "mbl.is" in text or "Morgunblaðið" in text[:500]:
        meta["article_source"] = "Morgunblaðið"
    elif "ruv.is" in text or "RÚV" in text[:500]:
        meta["article_source"] = "RÚV"

    # Try to extract author from "Author skrifar" in first 300 chars only
    header = text[:300]
    author_match = re.search(r"^(.+?)\s+skrifar\b", header, re.MULTILINE)
    if author_match and not meta["article_author"]:
        candidate = author_match.group(1).strip().lstrip("#").strip()
        # Reject if it looks like a title+author combo — extract capitalised name
        if len(candidate.split()) > 4:
            # "Title words Author Name skrifar" — take trailing capitalised words
            words = candidate.split()
            name_words = []
            for w in reversed(words):
                if w[0].isupper():
                    name_words.insert(0, w)
                else:
                    break
            candidate = " ".join(name_words) if name_words else " ".join(words[-2:])
        meta["article_author"] = candidate

    # Try to extract date from Icelandic date pattern anywhere
    if not meta["article_date"]:
        meta["article_date"] = _parse_is_date(text[:500])

    return meta


def icelandic_slugify(text: str) -> str:
    """Create a URL-safe slug from Icelandic text."""
    replacements = {
        "þ": "th", "Þ": "th",
        "ð": "d", "Ð": "d",
        "æ": "ae", "Æ": "ae",
        "ö": "o", "Ö": "o",
        "á": "a", "Á": "a",
        "é": "e", "É": "e",
        "í": "i", "Í": "i",
        "ó": "o", "Ó": "o",
        "ú": "u", "Ú": "u",
        "ý": "y", "Ý": "y",
    }
    slug = text
    for orig, repl in replacements.items():
        slug = slug.replace(orig, repl)

    slug = unicodedata.normalize("NFKD", slug)
    slug = slug.encode("ascii", "ignore").decode("ascii")
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


# ── Icelandic text extraction from report_text_is ────────────────────


def _parse_icelandic_report(report_text_is: str) -> dict:
    """Parse the Icelandic markdown report to extract per-claim text.

    Returns a dict with:
      - summary_is: Icelandic summary text
      - claims_is: list of dicts with claim_text_is, explanation_is, missing_context_is
    """
    result: dict = {"summary_is": None, "claims_is": []}

    if not report_text_is:
        return result

    # Extract summary (may be under "## Yfirlit" or "## Samantekt")
    summary_match = re.search(
        r"## (?:Yfirlit|Samantekt)\n\n(.+?)(?=\n\n##)", report_text_is, re.DOTALL
    )
    if summary_match:
        result["summary_is"] = summary_match.group(1).strip()

    # Split into per-claim sections at "### Fullyrðing N:"
    claim_sections = re.split(r"### Fullyrðing \d+:", report_text_is)
    # First element is everything before claim 1 — skip it
    claim_sections = claim_sections[1:]

    for section in claim_sections:
        claim_data: dict = {
            "claim_text_is": None,
            "explanation_is": None,
            "missing_context_is": None,
        }

        # Extract claim text: **Fullyrðing:** <text>
        claim_match = re.search(
            r"\*\*Fullyrðing:\*\*\s*(.+?)(?=\n\n|\n\*\*)", section, re.DOTALL
        )
        if claim_match:
            claim_data["claim_text_is"] = claim_match.group(1).strip()

        # Extract explanation: **Mat:** <text>
        mat_match = re.search(
            r"\*\*Mat:\*\*\s*(.+?)(?=\n\*\*|\n\n---|\Z)", section, re.DOTALL
        )
        if mat_match:
            claim_data["explanation_is"] = mat_match.group(1).strip()

        # Extract missing context: **Vantar samhengi:** or **Samhengi sem vantar:**
        context_match = re.search(
            r"\*\*(?:Vantar samhengi|Samhengi sem vantar):\*\*\s*(.+?)(?=\n\*\*|\n\n---|\Z)",
            section,
            re.DOTALL,
        )
        if context_match:
            claim_data["missing_context_is"] = context_match.group(1).strip()

        result["claims_is"].append(claim_data)

    return result


# ── Evidence link enrichment ─────────────────────────────────────────


def _load_evidence_meta() -> dict[str, dict]:
    """Load evidence metadata lookup from exported JSON."""
    if not EVIDENCE_META_PATH.exists():
        print(f"  Warning: {EVIDENCE_META_PATH} not found — run export_evidence_meta.py first")
        return {}
    with open(EVIDENCE_META_PATH, encoding="utf-8") as f:
        return json.load(f)


def _linkify_evidence_ids(text: str, evidence_meta: dict[str, dict]) -> str:
    """Replace evidence IDs in text with HTML links where URLs are available.

    E.g. "POL-DATA-001 staðfestir..." becomes
    '<a href="https://..." title="Source Name">POL-DATA-001</a> staðfestir...'
    """
    if not text or not evidence_meta:
        return text

    def _replace_id(match: re.Match) -> str:
        eid = match.group(1)
        meta = evidence_meta.get(eid)
        if meta and meta.get("source_url"):
            name = meta["source_name"]
            url = meta["source_url"]
            return f'<a href="{url}" title="{name}" target="_blank" rel="noopener">{eid}</a>'
        return eid

    return _EVIDENCE_ID_RE.sub(_replace_id, text)


def _build_evidence_sources(
    evidence_ids: list[str], evidence_meta: dict[str, dict]
) -> list[dict]:
    """Build a list of evidence source dicts for template rendering.

    Each dict has: id, source_name, source_url (or null).
    """
    sources = []
    for eid in evidence_ids:
        meta = evidence_meta.get(eid, {})
        sources.append({
            "id": eid,
            "source_name": meta.get("source_name", eid),
            "source_url": meta.get("source_url"),
        })
    return sources


# ── Panel show detection + participants ───────────────────────────────


def _is_panel_show(analysis_dir: Path) -> bool:
    """Detect panel show analyses by directory name prefix."""
    return analysis_dir.name.startswith("panel_")


def _load_site_entities(site_dir: Path) -> dict[str, dict]:
    """Load site-wide entities.json as a name → entity lookup."""
    entities_path = site_dir / "_data" / "entities.json"
    if not entities_path.exists():
        return {}
    with open(entities_path, encoding="utf-8") as f:
        entities = json.load(f)
    return {e["name"]: e for e in entities}


def _build_participants(
    entities_data: dict | None,
    claims: list[dict],
    site_entities: dict[str, dict] | None = None,
) -> list[dict]:
    """Build participant list with per-speaker verdict breakdown.

    Enriches with site-wide entity data (slug, credibility, mention_count,
    althingi speech count) when available.
    """
    if not entities_data:
        return []

    site_entities = site_entities or {}
    participants = []
    for speaker in entities_data.get("speakers", []):
        attrs = speaker.get("attributions", [])
        if not attrs:
            # Legacy format
            attrs = [
                {"claim_index": idx} for idx in speaker.get("claim_indices", [])
            ]

        verdicts: dict[str, int] = {}
        for attr in attrs:
            idx = attr["claim_index"]
            if idx < len(claims):
                v = claims[idx].get("verdict", "unknown")
                verdicts[v] = verdicts.get(v, 0) + 1

        p: dict = {
            "name": speaker["name"],
            "role": speaker.get("role"),
            "party": speaker.get("party"),
            "claim_count": len(attrs),
            "verdicts": verdicts,
        }

        # Enrich from site-wide entity data
        entity = site_entities.get(speaker["name"])
        if entity:
            p["slug"] = entity.get("slug")
            p["mention_count"] = entity.get("mention_count")
            p["credibility"] = entity.get("credibility")
            stats = entity.get("althingi_stats")
            if stats:
                p["speech_count"] = stats.get("speech_count")

        participants.append(p)

    # Sort by claim count descending
    participants.sort(key=lambda p: p["claim_count"], reverse=True)
    return participants


# ── Report preparation ───────────────────────────────────────────────


def _load_entities(analysis_dir: Path) -> dict | None:
    """Load entity data from _entities.json if it exists."""
    entities_path = analysis_dir / "_entities.json"
    if not entities_path.exists():
        return None
    with open(entities_path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_speaker_attributions(speaker: dict) -> list[dict]:
    """Resolve attributions from raw speaker dict (new or legacy format).

    Returns list of {claim_index, attribution} dicts.
    """
    attributions = speaker.get("attributions", [])
    if attributions:
        return [
            {
                "claim_index": a["claim_index"],
                "attribution": a.get("attribution", "asserted"),
            }
            for a in attributions
        ]
    return [
        {"claim_index": idx, "attribution": "asserted"}
        for idx in speaker.get("claim_indices", [])
    ]


def _speakers_for_claim(entities_data: dict | None, claim_index: int) -> list[dict]:
    """Get speakers attributed to a claim by index.

    Returns a list of {name, type, role, party, stance, attribution} dicts.
    """
    if not entities_data:
        return []

    speakers = []

    def _check_speaker(speaker: dict) -> None:
        for attr in _resolve_speaker_attributions(speaker):
            if attr["claim_index"] == claim_index:
                speakers.append({
                    "name": speaker["name"],
                    "type": speaker.get("type", "individual"),
                    "role": speaker.get("role"),
                    "party": speaker.get("party"),
                    "stance": speaker.get("stance", "neutral"),
                    "attribution": attr["attribution"],
                    "stance_score": speaker.get("stance_score"),
                    "credibility": speaker.get("credibility"),
                })
                break  # One entry per speaker per claim

    # Check article author
    author = entities_data.get("article_author")
    if author:
        _check_speaker(author)

    # Check all other speakers
    for speaker in entities_data.get("speakers", []):
        _check_speaker(speaker)

    return speakers


def prepare_report(
    report_path: Path,
    evidence_meta: dict[str, dict],
    site_entities: dict[str, dict] | None = None,
    db_verdicts: dict[str, dict] | None = None,
) -> dict:
    """Extract site-ready fields from a _report_final.json file.

    Enriches with:
    - Article metadata parsed from _article.md (source, URL, author, date)
    - Icelandic text parsed from report_text_is
    - Evidence source metadata (names + URLs) for linking
    - Speaker attributions from entity extraction
    - DB verdict overlay (if db_verdicts provided, reassessed verdicts
      replace the pipeline snapshot verdicts)
    """
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    analysis_id = report_path.parent.name
    slug = icelandic_slugify(report["article_title"])

    # Extract article metadata from _article.md
    article_meta = _parse_article_meta(report_path.parent)

    # Use article_meta, falling back to report JSON fields
    article_source = article_meta["article_source"] or report.get("article_source")
    article_url = article_meta["article_url"] or report.get("article_url")
    article_author = article_meta["article_author"] or report.get("article_author")
    article_date = article_meta["article_date"] or report.get("article_date")

    # Load entity data if available
    entities_data = _load_entities(report_path.parent)

    # Parse Icelandic report text
    is_data = _parse_icelandic_report(report.get("report_text_is", ""))

    # Compute dominant category from claims
    category_counts = Counter(
        item.get("claim", {}).get("category", "")
        for item in report.get("claims", [])
        if item.get("claim", {}).get("category")
    )
    dominant_category = category_counts.most_common(1)[0][0] if category_counts else None
    categories = sorted(set(category_counts.keys()))

    # Enrich claims with Icelandic text and evidence links
    claims = report.get("claims", [])
    claims_is = is_data.get("claims_is", [])

    enriched_claims = []
    for i, item in enumerate(claims):
        # Merge Icelandic text from parsed report
        is_claim = claims_is[i] if i < len(claims_is) else {}

        explanation_is = is_claim.get("explanation_is") or item.get("explanation", "")
        missing_context_is = is_claim.get("missing_context_is") or item.get("missing_context")
        claim_text_is = is_claim.get("claim_text_is") or item.get("claim", {}).get("claim_text", "")

        # Overlay DB verdict if available (catches reassessments)
        claim_text_raw = item.get("claim", {}).get("claim_text", "")
        verdict = item.get("verdict", "unknown")
        confidence = item.get("confidence", 0)
        sup_evidence = item.get("supporting_evidence", [])
        contra_evidence = item.get("contradicting_evidence", [])

        if db_verdicts:
            db_entry = db_verdicts.get(claim_text_raw) or db_verdicts.get(claim_text_is)
            if db_entry:
                verdict = db_entry["verdict"]
                confidence = db_entry["confidence"] or confidence
                sup_evidence = db_entry["supporting_evidence"]
                contra_evidence = db_entry["contradicting_evidence"]
                if db_entry["explanation_is"]:
                    explanation_is = db_entry["explanation_is"]
                if db_entry["missing_context_is"]:
                    missing_context_is = db_entry["missing_context_is"]

        # Linkify evidence IDs in text fields
        explanation_is = _linkify_evidence_ids(explanation_is, evidence_meta)
        if missing_context_is:
            missing_context_is = _linkify_evidence_ids(missing_context_is, evidence_meta)

        # Build evidence source lists with metadata
        supporting = _build_evidence_sources(sup_evidence, evidence_meta)
        contradicting = _build_evidence_sources(contra_evidence, evidence_meta)

        enriched_claims.append({
            "claim": {
                "original_quote": item.get("claim", {}).get("original_quote", ""),
                "claim_text": claim_text_is,
                "category": item.get("claim", {}).get("category", ""),
                "claim_type": item.get("claim", {}).get("claim_type", ""),
                "confidence": item.get("claim", {}).get("confidence", 0),
            },
            "verdict": verdict,
            "explanation": explanation_is,
            "supporting_evidence": supporting,
            "contradicting_evidence": contradicting,
            "missing_context": missing_context_is,
            "confidence": confidence,
            "speakers": _speakers_for_claim(entities_data, i),
        })

    # Count verdicts from enriched claims (reflects DB reassessments)
    verdict_counts: dict[str, int] = {}
    for ec in enriched_claims:
        v = ec.get("verdict", "unknown")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    # Use Icelandic summary or generate one
    summary_is = is_data.get("summary_is") or report.get("summary", "")

    # Detect panel show and build participant data
    panel_show = _is_panel_show(report_path.parent)
    participants = (
        _build_participants(entities_data, claims, site_entities)
        if panel_show else []
    )

    result = {
        "analysis_id": analysis_id,
        "slug": slug,
        "article_title": report["article_title"],
        "article_source": article_source,
        "article_url": article_url,
        "article_author": article_author,
        "article_date": article_date,
        "analysis_date": report.get("analysis_date"),
        "summary": summary_is,
        "verdict_counts": verdict_counts,
        "claim_count": len(claims),
        "dominant_category": dominant_category,
        "categories": categories,
        "claims": enriched_claims,
    }

    if panel_show:
        result["source_type"] = "panel_show"
        result["participants"] = participants

    return result


def _listing_entry(report_data: dict) -> dict:
    """Create a lightweight listing entry (no full claims array)."""
    # Collect unique speakers across all claims
    seen_speakers: set[str] = set()
    speakers = []
    for item in report_data.get("claims", []):
        for s in item.get("speakers", []):
            if s["name"] not in seen_speakers:
                seen_speakers.add(s["name"])
                speakers.append({
                    "name": s["name"],
                    "party": s.get("party"),
                    "stance": s.get("stance"),
                })

    entry = {
        "slug": report_data["slug"],
        "article_title": report_data["article_title"],
        "article_source": report_data.get("article_source"),
        "article_url": report_data.get("article_url"),
        "article_author": report_data.get("article_author"),
        "article_date": report_data.get("article_date"),
        "analysis_date": report_data.get("analysis_date"),
        "summary": report_data.get("summary", ""),
        "claim_count": report_data.get("claim_count", 0),
        "verdict_counts": report_data.get("verdict_counts", {}),
        "dominant_category": report_data.get("dominant_category"),
        "categories": report_data.get("categories", []),
        "speakers": speakers,
    }

    if report_data.get("source_type") == "panel_show":
        entry["source_type"] = "panel_show"
        entry["participants"] = report_data.get("participants", [])

    return entry


def main() -> None:
    site_dir = Path(sys.argv[sys.argv.index("--site-dir") + 1]) if "--site-dir" in sys.argv else DEFAULT_SITE_DIR

    if not site_dir.exists():
        print(f"Site directory not found: {site_dir}")
        sys.exit(1)

    reports_dir = site_dir / "_data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Load evidence metadata for linking
    evidence_meta = _load_evidence_meta()
    if evidence_meta:
        with_url = sum(1 for v in evidence_meta.values() if v.get("source_url"))
        print(f"Evidence metadata: {len(evidence_meta)} entries ({with_url} with URLs)")

    # Load site-wide entities for panel show participant enrichment
    site_entities = _load_site_entities(site_dir)
    if site_entities:
        print(f"Site entities: {len(site_entities)} loaded for participant enrichment")

    # Load DB verdicts for overlay (catches reassessments)
    db_verdicts = _load_db_verdicts()
    if db_verdicts:
        print(f"DB verdict overlay: {len(db_verdicts)} claim texts loaded")

    # Find all completed analysis reports
    report_files = sorted(ANALYSES_DIR.glob("*/_report_final.json"))

    if not report_files:
        print("No analysis reports found.")
        return

    all_reports = []
    written = 0
    for report_path in report_files:
        report_data = prepare_report(report_path, evidence_meta, site_entities, db_verdicts)
        out_path = reports_dir / f"{report_data['slug']}.json"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        all_reports.append(report_data)
        print(f"  {report_data['analysis_id']} → {out_path.name} ({report_data['claim_count']} claims)")
        written += 1

    print(f"\nWrote {written} reports to {reports_dir}")

    # Generate lightweight listing JSON for client-side filtering
    listing_dir = site_dir / "assets" / "data"
    listing_dir.mkdir(parents=True, exist_ok=True)
    listing_path = listing_dir / "reports.json"

    listing = [_listing_entry(r) for r in all_reports]
    with open(listing_path, "w", encoding="utf-8") as f:
        json.dump(listing, f, ensure_ascii=False, indent=2)

    sources = set(r.get("article_source") for r in all_reports if r.get("article_source"))
    print(f"Wrote listing JSON: {len(listing)} reports ({len(sources)} sources: {', '.join(sorted(sources))})")

    # Prepare entity detail pages
    prepare_entity_details(site_dir)

    # Prepare evidence detail pages
    prepare_evidence_details(site_dir)


# ── Entity detail page preparation ───────────────────────────────────

_ACTIVE_ATTRIBUTIONS = {"asserted", "quoted", "paraphrased"}

_ATTRIBUTION_LABELS = {
    "asserted": "Fullyrt",
    "quoted": "Vitnað í",
    "paraphrased": "Umorðað",
    "mentioned": "Nefnt",
}


def prepare_entity_details(site_dir: Path) -> None:
    """Build per-entity detail JSONs by resolving claims through reports.

    For each entity, loads linked report JSONs and finds claims where the
    entity appears in the speakers[] array (by name match). This bypasses the
    truncated claim slug problem in entities.json.
    """
    entities_path = site_dir / "_data" / "entities.json"
    reports_dir = site_dir / "_data" / "reports"
    details_dir = site_dir / "_data" / "entity-details"
    details_dir.mkdir(parents=True, exist_ok=True)

    if not entities_path.exists():
        print("No entities.json found — skipping entity details.")
        return

    with open(entities_path, encoding="utf-8") as f:
        entities = json.load(f)

    # Load all reports into a slug → data map
    reports_map: dict[str, dict] = {}
    for rp in sorted(reports_dir.glob("*.json")):
        with open(rp, encoding="utf-8") as f:
            rd = json.load(f)
        reports_map[rd["slug"]] = rd

    written = 0
    for entity in entities:
        detail = _build_entity_detail(entity, reports_map)
        out_path = details_dir / f"{entity['slug']}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)
        written += 1

    print(f"\nWrote {written} entity detail pages to {details_dir}")


def _build_entity_detail(entity: dict, reports_map: dict[str, dict]) -> dict:
    """Build a detail JSON for a single entity.

    Resolves claims by scanning the entity's linked articles for speaker matches.
    """
    entity_name = entity["name"]
    article_slugs = entity.get("articles", [])

    resolved_claims = []
    resolved_articles = []
    scorecard: dict[str, int] = {}

    for article_slug in article_slugs:
        report = reports_map.get(article_slug)
        if not report:
            continue

        article_claims = []
        article_attr_types: set[str] = set()

        for claim_item in report.get("claims", []):
            speakers = claim_item.get("speakers", [])
            # Find this entity in the claim's speakers
            match = None
            for s in speakers:
                if s["name"] == entity_name:
                    match = s
                    break
            if not match:
                continue

            attribution = match.get("attribution", "asserted")
            article_attr_types.add(attribution)

            # Prefer Icelandic claim text
            claim_text = claim_item.get("claim", {}).get("claim_text", "")
            verdict = claim_item.get("verdict", "unknown")
            category = claim_item.get("claim", {}).get("category", "")

            resolved_claims.append({
                "claim_text": claim_text,
                "verdict": verdict,
                "category": category,
                "attribution": attribution,
                "article_slug": article_slug,
                "article_title": report.get("article_title", ""),
                "article_source": report.get("article_source"),
                "article_date": report.get("article_date"),
            })

            # Only active attributions count toward scorecard
            if attribution in _ACTIVE_ATTRIBUTIONS:
                scorecard[verdict] = scorecard.get(verdict, 0) + 1

            article_claims.append(attribution)

        claim_count_in_article = len(article_claims)
        if claim_count_in_article > 0:
            resolved_articles.append({
                "slug": article_slug,
                "title": report.get("article_title", ""),
                "source": report.get("article_source"),
                "date": report.get("article_date"),
                "claim_count": claim_count_in_article,
                "attribution_types": sorted(article_attr_types),
            })

    return {
        "slug": entity["slug"],
        "name": entity_name,
        "type": entity.get("type", "individual"),
        "description": entity.get("description"),
        "role": entity.get("role"),
        "party": entity.get("party"),
        "stance": entity.get("stance"),
        "stance_score": entity.get("stance_score"),
        "credibility": entity.get("credibility"),
        "attribution_counts": entity.get("attribution_counts"),
        "althingi_stats": entity.get("althingi_stats"),
        "scorecard": scorecard,
        "claims": resolved_claims,
        "articles": resolved_articles,
    }


# ── Evidence detail page preparation ─────────────────────────────────

EVIDENCE_FULL_PATH = PROJECT_ROOT / "data" / "export" / "evidence_full.json"


def prepare_evidence_details(site_dir: Path) -> None:
    """Build per-evidence detail JSONs with cited-by reverse index.

    For each evidence entry, scans all report JSONs to find claims where
    this evidence_id appears in supporting_evidence or contradicting_evidence.
    Also resolves related_entries IDs to {slug, evidence_id, statement_is}.
    """
    details_dir = site_dir / "_data" / "evidence-details"
    details_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = site_dir / "_data" / "reports"

    if not EVIDENCE_FULL_PATH.exists():
        print("No evidence_full.json found — run export_evidence.py first. Skipping evidence details.")
        return

    with open(EVIDENCE_FULL_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    # Build evidence lookup for resolving related_entries
    evidence_lookup: dict[str, dict] = {}
    for e in entries:
        evidence_lookup[e["evidence_id"]] = e

    # Build cited-by reverse index from all reports
    cited_by = _build_cited_by_index(reports_dir)

    written = 0
    for entry in entries:
        detail = _build_evidence_detail(entry, evidence_lookup, cited_by)
        out_path = details_dir / f"{entry['slug']}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)
        written += 1

    cited_count = sum(1 for e in entries if e["evidence_id"] in cited_by)
    print(f"\nWrote {written} evidence detail pages to {details_dir}")
    print(f"  {cited_count}/{len(entries)} entries cited by at least one report")


def _build_cited_by_index(reports_dir: Path) -> dict[str, list[dict]]:
    """Scan all report JSONs and build evidence_id → [citation] reverse index.

    Each citation includes the report slug, claim text, verdict, and whether
    the evidence was supporting or contradicting.
    """
    cited_by: dict[str, list[dict]] = {}

    if not reports_dir.exists():
        return cited_by

    for rp in sorted(reports_dir.glob("*.json")):
        with open(rp, encoding="utf-8") as f:
            report = json.load(f)

        report_slug = report.get("slug", "")
        report_title = report.get("article_title", "")
        report_source = report.get("article_source")
        report_date = report.get("article_date")

        for claim_item in report.get("claims", []):
            claim_text = claim_item.get("claim", {}).get("claim_text", "")
            verdict = claim_item.get("verdict", "unknown")

            # Check supporting_evidence
            for ev in claim_item.get("supporting_evidence", []):
                ev_id = ev.get("id") if isinstance(ev, dict) else ev
                if ev_id:
                    cited_by.setdefault(ev_id, []).append({
                        "report_slug": report_slug,
                        "report_title": report_title,
                        "report_source": report_source,
                        "report_date": report_date,
                        "claim_text": claim_text,
                        "verdict": verdict,
                        "role": "supporting",
                    })

            # Check contradicting_evidence
            for ev in claim_item.get("contradicting_evidence", []):
                ev_id = ev.get("id") if isinstance(ev, dict) else ev
                if ev_id:
                    cited_by.setdefault(ev_id, []).append({
                        "report_slug": report_slug,
                        "report_title": report_title,
                        "report_source": report_source,
                        "report_date": report_date,
                        "claim_text": claim_text,
                        "verdict": verdict,
                        "role": "contradicting",
                    })

    return cited_by


def _build_evidence_detail(
    entry: dict,
    evidence_lookup: dict[str, dict],
    cited_by: dict[str, list[dict]],
) -> dict:
    """Build a detail JSON for a single evidence entry."""
    eid = entry["evidence_id"]

    # Resolve related_entries to mini objects
    related = []
    for rel_id in entry.get("related_entries", []):
        rel = evidence_lookup.get(rel_id)
        if rel:
            related.append({
                "slug": rel["slug"],
                "evidence_id": rel_id,
                "statement": rel.get("statement_is") or rel["statement"],
                "topic": rel.get("topic"),
            })

    # Get citations for this entry
    citations = cited_by.get(eid, [])
    citation_count = len(citations)

    # Group citations by report for display
    reports_citing: dict[str, dict] = {}
    for cit in citations:
        rs = cit["report_slug"]
        if rs not in reports_citing:
            reports_citing[rs] = {
                "report_slug": rs,
                "report_title": cit["report_title"],
                "report_source": cit.get("report_source"),
                "report_date": cit.get("report_date"),
                "claims": [],
            }
        reports_citing[rs]["claims"].append({
            "claim_text": cit["claim_text"],
            "verdict": cit["verdict"],
            "role": cit["role"],
        })

    return {
        "slug": entry["slug"],
        "evidence_id": eid,
        "domain": entry["domain"],
        "topic": entry["topic"],
        "subtopic": entry.get("subtopic"),
        "statement": entry["statement"],
        "statement_is": entry.get("statement_is"),
        "source_name": entry["source_name"],
        "source_url": entry.get("source_url"),
        "source_date": entry.get("source_date"),
        "source_type": entry["source_type"],
        "source_description_is": entry.get("source_description_is"),
        "confidence": entry["confidence"],
        "caveats": entry.get("caveats"),
        "last_verified": entry.get("last_verified"),
        "related_entries": related,
        "citations": list(reports_citing.values()),
        "citation_count": citation_count,
    }


if __name__ == "__main__":
    main()
