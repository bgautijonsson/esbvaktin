#!/usr/bin/env python3
"""Post-processing script for Icelandic grammar and spelling correction.

Thin wrapper — implementation lives in src/esbvaktin/corrections/cli.py.

Usage:
    uv run python scripts/correct_icelandic.py check data/reassessment/ --fix
    uv run python scripts/correct_icelandic.py check data/reassessment/_assessments_batch_1.json
    uv run python scripts/correct_icelandic.py check-claims data/export/claims.json
"""

from esbvaktin.corrections.cli import main

if __name__ == "__main__":
    main()
