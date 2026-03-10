"""Prepare analysis reports for the 11ty site.

Reads each data/analyses/*/_report_final.json, extracts key fields,
and writes cleaned JSON files to the site repo's _data/reports/ directory.

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
DEFAULT_SITE_DIR = PROJECT_ROOT.parent / "esbvaktin-site"


def icelandic_slugify(text: str) -> str:
    """Create a URL-safe slug from Icelandic text.

    Transliterates Icelandic characters before slugifying:
    þ→th, ð→d, æ→ae, ö→o, á→a, é→e, í→i, ó→o, ú→u, ý→y.
    """
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

    # Normalise unicode, lowercase, replace non-alnum with hyphens
    slug = unicodedata.normalize("NFKD", slug)
    slug = slug.encode("ascii", "ignore").decode("ascii")
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def prepare_report(report_path: Path) -> dict:
    """Extract site-ready fields from a _report_final.json file."""
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    analysis_id = report_path.parent.name
    slug = icelandic_slugify(report["article_title"])

    # Count verdicts for summary stats
    verdict_counts: dict[str, int] = {}
    for item in report.get("claims", []):
        v = item.get("verdict", "unknown")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    return {
        "analysis_id": analysis_id,
        "slug": slug,
        "article_title": report["article_title"],
        "article_source": report.get("article_source"),
        "article_date": report.get("article_date"),
        "analysis_date": report.get("analysis_date"),
        "summary": report.get("summary", ""),
        "verdict_counts": verdict_counts,
        "claim_count": len(report.get("claims", [])),
        "claims": report.get("claims", []),
    }


def main() -> None:
    site_dir = Path(sys.argv[sys.argv.index("--site-dir") + 1]) if "--site-dir" in sys.argv else DEFAULT_SITE_DIR

    if not site_dir.exists():
        print(f"Site directory not found: {site_dir}")
        sys.exit(1)

    reports_dir = site_dir / "_data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Find all completed analysis reports
    report_files = sorted(ANALYSES_DIR.glob("*/_report_final.json"))

    if not report_files:
        print("No analysis reports found.")
        return

    written = 0
    for report_path in report_files:
        report_data = prepare_report(report_path)
        out_path = reports_dir / f"{report_data['slug']}.json"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        print(f"  {report_data['analysis_id']} → {out_path.name} ({report_data['claim_count']} claims)")
        written += 1

    print(f"\nWrote {written} reports to {reports_dir}")


if __name__ == "__main__":
    main()
