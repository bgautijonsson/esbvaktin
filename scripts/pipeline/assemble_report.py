"""Assemble the final analysis report from subagent outputs.

Parses _assessments.json + _omissions.json, reads _metadata.json, generates
the Icelandic summary, assembles the AnalysisReport, and writes
_report_is.md + _report.json + _report_final.json.

Merges what SKILL.md previously called "Step 6" and "Step 7" into one script.

Usage:
    uv run python scripts/pipeline/assemble_report.py WORK_DIR

Exit codes: 0 = success, 1 = failure
"""

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Assemble final analysis report")
    parser.add_argument("work_dir", type=Path, help="Pipeline working directory")
    parser.add_argument(
        "--language",
        default="is",
        choices=["is", "en"],
        help="Report language (default: is)",
    )
    args = parser.parse_args()

    work_dir: Path = args.work_dir
    assessments_path = work_dir / "_assessments.json"
    omissions_path = work_dir / "_omissions.json"
    meta_path = work_dir / "_metadata.json"

    if not assessments_path.exists():
        print(f"ERROR: {assessments_path} not found", file=sys.stderr)
        sys.exit(1)
    if not omissions_path.exists():
        print(f"ERROR: {omissions_path} not found", file=sys.stderr)
        sys.exit(1)

    # ── Parse subagent outputs ──────────────────────────────────────────
    from esbvaktin.pipeline.parse_outputs import parse_assessments, parse_omissions_safe

    assessments = parse_assessments(assessments_path)
    omissions = parse_omissions_safe(omissions_path)

    # ── Read metadata ───────────────────────────────────────────────────
    raw_meta = {}
    if meta_path.exists():
        raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    article_date = None
    if raw_meta.get("date"):
        try:
            article_date = date.fromisoformat(raw_meta["date"])
        except (ValueError, TypeError):
            pass

    # ── Generate Icelandic summary ──────────────────────────────────────
    verdicts = [a.verdict.value for a in assessments]
    vc = Counter(verdicts)

    verdict_names = {
        "supported": "stutt af heimildum",
        "partially_supported": "stutt að hluta",
        "unsupported": "ekki stutt",
        "misleading": "þarfnast samhengis",
        "unverifiable": "ekki hægt að sannreyna",
    }
    parts = [f"{count} {verdict_names.get(v, v)}" for v, count in vc.most_common()]
    summary = f"Greindar {len(assessments)} fullyrðingar. "
    summary += "Niðurstöður: " + ", ".join(parts) + ". "

    framing_names = {
        "balanced": "jafnvæg",
        "leans_pro_eu": "hallar á ESB-jákvæða hlið",
        "leans_anti_eu": "hallar á ESB-neikvæða hlið",
        "strongly_pro_eu": "mjög ESB-jákvæð",
        "strongly_anti_eu": "mjög ESB-neikvæð",
        "neutral_but_incomplete": "hlutlaus en ófullnægjandi",
    }
    framing = framing_names.get(
        omissions.framing_assessment.value, omissions.framing_assessment.value
    )
    summary += f"Sjónarhorn: {framing}. "
    summary += f"Heildstæðni: {omissions.overall_completeness:.0%}."

    # ── Assemble report ─────────────────────────────────────────────────
    from esbvaktin.pipeline.assemble_report import assemble_report

    report = assemble_report(
        claims=assessments,
        omissions=omissions,
        summary=summary,
        article_title=raw_meta.get("title"),
        article_url=raw_meta.get("url"),
        article_source=raw_meta.get("source"),
        article_date=article_date,
        language=args.language,
    )

    # ── Write all output files ──────────────────────────────────────────
    if report.report_text_is:
        (work_dir / "_report_is.md").write_text(report.report_text_is, encoding="utf-8")
    report_json = report.model_dump_json(indent=2)
    (work_dir / "_report.json").write_text(report_json, encoding="utf-8")

    # _report_final.json — previously a separate "Step 7"
    report_data = json.loads(report_json)
    (work_dir / "_report_final.json").write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # ── Print summary ───────────────────────────────────────────────────
    print("=== GREINING LOKIÐ ===")
    print(f"Vinnusvæði: {work_dir}")
    print(f"Yfirlit: {report.summary}")
    print(f"Fullyrðingar metnar: {len(assessments)}")
    print(f"Heimildir notaðar: {len(report.evidence_used)} færslur")
    print(f"Íslensk skýrsla: {work_dir}/_report_is.md")


if __name__ == "__main__":
    main()
