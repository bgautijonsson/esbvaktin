"""Write the capsule text back into _report_final.json.

Reads _capsule.txt (written by the capsule-writer subagent), inserts it
into _report_final.json as the "capsule" field.

Usage:
    uv run python scripts/pipeline/write_capsule.py WORK_DIR

Exit codes: 0 = success, 1 = capsule missing (warning, not failure)
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Write capsule text into _report_final.json")
    parser.add_argument("work_dir", type=Path, help="Pipeline working directory")
    args = parser.parse_args()

    work_dir: Path = args.work_dir
    capsule_path = work_dir / "_capsule.txt"
    report_path = work_dir / "_report_final.json"

    if not capsule_path.exists():
        print("WARNING: _capsule.txt not found — skipping.")
        sys.exit(1)

    if not report_path.exists():
        print(f"ERROR: {report_path} not found", file=sys.stderr)
        sys.exit(1)

    capsule = capsule_path.read_text(encoding="utf-8").strip()
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    report_data["capsule"] = capsule
    report_path.write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"Capsule written: {capsule[:100]}...")


if __name__ == "__main__":
    main()
