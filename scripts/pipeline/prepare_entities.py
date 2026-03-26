"""Prepare entity extraction context — or generate entities directly for panels.

For regular articles: reads _report_final.json + _article.md, writes
_context_entities.md for the entity-extractor subagent.

For panel shows: generates _entities.json directly from the transcript +
assessments (no subagent needed — speaker attribution is structural).

Usage:
    uv run python scripts/pipeline/prepare_entities.py WORK_DIR

Exit codes: 0 = success, 1 = failure
"""

import argparse
import json
import sys
from pathlib import Path

from esbvaktin.pipeline.detection import is_panel_show as _is_panel_show_impl


def _is_panel_show(article_text: str, metadata: dict) -> bool:
    """Detect whether the article is a panel show transcript."""
    return _is_panel_show_impl(metadata, article_text)


def main():
    parser = argparse.ArgumentParser(
        description="Prepare entity context or generate panel entities"
    )
    parser.add_argument("work_dir", type=Path, help="Pipeline working directory")
    args = parser.parse_args()

    work_dir: Path = args.work_dir
    article_path = work_dir / "_article.md"
    report_path = work_dir / "_report_final.json"

    if not report_path.exists():
        print(f"ERROR: {report_path} not found", file=sys.stderr)
        sys.exit(1)
    if not article_path.exists():
        print(f"ERROR: {article_path} not found", file=sys.stderr)
        sys.exit(1)

    article_text = article_path.read_text(encoding="utf-8")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # Read metadata from _metadata.json (not from report — report may lack fields)
    meta_path = work_dir / "_metadata.json"
    metadata = {}
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    if _is_panel_show(article_text, metadata):
        # Panel: generate entities directly
        from esbvaktin.pipeline.parse_outputs import parse_assessments
        from esbvaktin.pipeline.transcript import generate_panel_entities, parse_transcript

        transcript = parse_transcript(article_text)
        assessments = parse_assessments(work_dir / "_assessments.json")

        entities = generate_panel_entities(transcript, assessments)
        data = entities.model_dump(mode="json")
        (work_dir / "_entities.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Panel entities generated: {len(entities.speakers)} speakers")
        for s in entities.speakers:
            print(f"  - {s.name} ({s.party or s.role}) — {len(s.attributions)} claims")
    else:
        # Article: prepare context for entity-extractor subagent
        from esbvaktin.pipeline.models import Claim
        from esbvaktin.pipeline.prepare_context import prepare_entity_context

        claims = []
        for item in report.get("claims", []):
            c = item.get("claim", item)
            claims.append(Claim.model_validate(c))

        entity_meta = {
            "title": report.get("article_title") or metadata.get("title"),
            "source": report.get("article_source") or metadata.get("source"),
            "date": report.get("article_date") or metadata.get("date"),
        }
        prepare_entity_context(article_text, claims, work_dir, entity_meta)
        print(f"Entity context prepared ({len(claims)} claims).")
        print("Next: spawn entity-extractor agent.")


if __name__ == "__main__":
    main()
