"""Prepare analysis reports for the 11ty site.

Reads each data/analyses/*/_report_final.json, extracts key fields,
enriches with Icelandic text from report_text_is, and attaches evidence
source metadata (names + URLs) for rendering as hyperlinks.

Usage:
    uv run python scripts/prepare_site.py
    uv run python scripts/prepare_site.py --site-dir ~/esbvaktin-site
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"
EVIDENCE_META_PATH = PROJECT_ROOT / "data" / "export" / "evidence_meta.json"
DEFAULT_SITE_DIR = PROJECT_ROOT.parent / "esbvaktin-site"

# Evidence ID pattern: e.g. FISH-DATA-001, SOV-LEGAL-006
_EVIDENCE_ID_RE = re.compile(r"\b([A-Z]+-[A-Z]+-\d{3})\b")


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


# ── Report preparation ───────────────────────────────────────────────


def prepare_report(report_path: Path, evidence_meta: dict[str, dict]) -> dict:
    """Extract site-ready fields from a _report_final.json file.

    Enriches with:
    - Icelandic text parsed from report_text_is
    - Evidence source metadata (names + URLs) for linking
    """
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    analysis_id = report_path.parent.name
    slug = icelandic_slugify(report["article_title"])

    # Parse Icelandic report text
    is_data = _parse_icelandic_report(report.get("report_text_is", ""))

    # Count verdicts for summary stats
    verdict_counts: dict[str, int] = {}
    for item in report.get("claims", []):
        v = item.get("verdict", "unknown")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

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

        # Linkify evidence IDs in text fields
        explanation_is = _linkify_evidence_ids(explanation_is, evidence_meta)
        if missing_context_is:
            missing_context_is = _linkify_evidence_ids(missing_context_is, evidence_meta)

        # Build evidence source lists with metadata
        supporting = _build_evidence_sources(
            item.get("supporting_evidence", []), evidence_meta
        )
        contradicting = _build_evidence_sources(
            item.get("contradicting_evidence", []), evidence_meta
        )

        enriched_claims.append({
            "claim": {
                "original_quote": item.get("claim", {}).get("original_quote", ""),
                "claim_text": claim_text_is,
                "category": item.get("claim", {}).get("category", ""),
                "claim_type": item.get("claim", {}).get("claim_type", ""),
                "confidence": item.get("claim", {}).get("confidence", 0),
            },
            "verdict": item.get("verdict", "unknown"),
            "explanation": explanation_is,
            "supporting_evidence": supporting,
            "contradicting_evidence": contradicting,
            "missing_context": missing_context_is,
            "confidence": item.get("confidence", 0),
        })

    # Use Icelandic summary or generate one
    summary_is = is_data.get("summary_is") or report.get("summary", "")

    return {
        "analysis_id": analysis_id,
        "slug": slug,
        "article_title": report["article_title"],
        "article_source": report.get("article_source"),
        "article_date": report.get("article_date"),
        "analysis_date": report.get("analysis_date"),
        "summary": summary_is,
        "verdict_counts": verdict_counts,
        "claim_count": len(claims),
        "claims": enriched_claims,
    }


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

    # Find all completed analysis reports
    report_files = sorted(ANALYSES_DIR.glob("*/_report_final.json"))

    if not report_files:
        print("No analysis reports found.")
        return

    written = 0
    for report_path in report_files:
        report_data = prepare_report(report_path, evidence_meta)
        out_path = reports_dir / f"{report_data['slug']}.json"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        print(f"  {report_data['analysis_id']} → {out_path.name} ({report_data['claim_count']} claims)")
        written += 1

    print(f"\nWrote {written} reports to {reports_dir}")


if __name__ == "__main__":
    main()
