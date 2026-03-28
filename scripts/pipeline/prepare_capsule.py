"""Prepare the capsule context for the capsule-writer subagent.

Reads _report_final.json, writes _context_capsule.md.

Usage:
    uv run python scripts/pipeline/prepare_capsule.py WORK_DIR

Exit codes: 0 = success, 1 = failure
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Prepare capsule context for capsule-writer subagent"
    )
    parser.add_argument("work_dir", type=Path, help="Pipeline working directory")
    args = parser.parse_args()

    work_dir: Path = args.work_dir
    report_path = work_dir / "_report_final.json"

    if not report_path.exists():
        print(f"ERROR: {report_path} not found", file=sys.stderr)
        sys.exit(1)

    from esbvaktin.pipeline.prepare_context import prepare_capsule_context

    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    prepare_capsule_context(report_data, work_dir)
    print("Capsule context prepared.")
    print("Next: spawn capsule-writer agent.")


if __name__ == "__main__":
    main()
