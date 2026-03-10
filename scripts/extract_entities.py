"""Prepare entity extraction contexts for all existing analyses.

This script reads each analysis directory's _article.md and _report_final.json,
then writes _context_entities.md for a Claude Code subagent to process.

Usage:
    uv run python scripts/extract_entities.py prepare          # Write context files
    uv run python scripts/extract_entities.py status            # Show extraction status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"

sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _load_claims_from_report(report_path: Path) -> list[dict]:
    """Extract claim data from _report_final.json."""
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    claims = []
    for item in report.get("claims", []):
        claim = item.get("claim", item)
        claims.append({
            "claim_text": claim.get("claim_text", ""),
            "original_quote": claim.get("original_quote", ""),
            "category": claim.get("category", "other"),
            "claim_type": claim.get("claim_type", "opinion"),
            "confidence": claim.get("confidence", 0.5),
        })
    return claims


def _extract_metadata(article_path: Path) -> dict:
    """Extract metadata from the article markdown file."""
    text = article_path.read_text(encoding="utf-8")
    metadata: dict[str, str | None] = {
        "title": None,
        "author": None,
        "source": None,
        "date": None,
    }

    # Try structured format: **Heimild:** ... | **Dagsetning:** ...
    for line in text.split("\n")[:10]:
        if "**Höfundur:**" in line:
            parts = line.split("**Höfundur:**")
            if len(parts) > 1:
                metadata["author"] = parts[1].strip().rstrip("|").strip()
        if "**Heimild:**" in line:
            parts = line.split("**Heimild:**")
            if len(parts) > 1:
                metadata["source"] = parts[1].split("|")[0].strip()
        if "**Dagsetning:**" in line:
            parts = line.split("**Dagsetning:**")
            if len(parts) > 1:
                metadata["date"] = parts[1].split("|")[0].strip()
        if line.startswith("# "):
            metadata["title"] = line[2:].strip()

    return metadata


def prepare_all() -> None:
    """Write _context_entities.md for all analyses that don't have _entities.json yet."""
    from esbvaktin.pipeline.models import Claim
    from esbvaktin.pipeline.prepare_context import prepare_entity_context

    analysis_dirs = sorted(ANALYSES_DIR.iterdir())
    prepared = 0
    skipped = 0

    for analysis_dir in analysis_dirs:
        if not analysis_dir.is_dir():
            continue

        report_path = analysis_dir / "_report_final.json"
        article_path = analysis_dir / "_article.md"
        entities_path = analysis_dir / "_entities.json"
        context_path = analysis_dir / "_context_entities.md"

        if not report_path.exists() or not article_path.exists():
            continue

        if entities_path.exists():
            print(f"  {analysis_dir.name}: already has _entities.json — skipping")
            skipped += 1
            continue

        # Load article and claims
        article_text = article_path.read_text(encoding="utf-8")
        raw_claims = _load_claims_from_report(report_path)
        claims = [Claim.model_validate(c) for c in raw_claims]
        metadata = _extract_metadata(article_path)

        # Prepare context
        prepare_entity_context(
            article_text=article_text,
            claims=claims,
            output_dir=analysis_dir,
            metadata=metadata,
        )
        print(f"  {analysis_dir.name}: context prepared ({len(claims)} claims)")
        prepared += 1

    print(f"\nPrepared {prepared} context files, skipped {skipped}")
    if prepared > 0:
        print("\nNext: launch subagents to process each _context_entities.md")
        print("Each subagent reads _context_entities.md and writes _entities.json")


def show_status() -> None:
    """Show entity extraction status for all analyses."""
    analysis_dirs = sorted(ANALYSES_DIR.iterdir())
    total = 0
    with_entities = 0
    with_context = 0

    for analysis_dir in analysis_dirs:
        if not analysis_dir.is_dir():
            continue
        report_path = analysis_dir / "_report_final.json"
        if not report_path.exists():
            continue

        total += 1
        entities_path = analysis_dir / "_entities.json"
        context_path = analysis_dir / "_context_entities.md"

        # Get article title
        with open(report_path, encoding="utf-8") as f:
            title = json.load(f).get("article_title", "?")

        status = "  "
        if entities_path.exists():
            with_entities += 1
            status = "✓ "
        elif context_path.exists():
            with_context += 1
            status = "⏳"
        else:
            status = "✗ "

        print(f"  {status} {analysis_dir.name} — {title}")

    print(f"\n{with_entities}/{total} extracted, {with_context} pending, "
          f"{total - with_entities - with_context} need preparation")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("prepare", "status"):
        print("Usage: uv run python scripts/extract_entities.py <prepare|status>")
        sys.exit(1)

    if sys.argv[1] == "prepare":
        prepare_all()
    elif sys.argv[1] == "status":
        show_status()


if __name__ == "__main__":
    main()
