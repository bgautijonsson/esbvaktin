"""xrepo-08: EU_ISSUE_PATTERNS must have a single source of truth.

The EU issue-title LIKE patterns were copy-pasted into three scripts. This guard
loads each script and asserts its pattern list IS the canonical object in
esbvaktin.speeches.constants — ``is``, not ``==``, so a fresh hand-copy that happens
to match today still fails the guard, preventing silent drift.

The scripts are import-safe: their top level is imports + module constants only.
"""

import importlib.util
from pathlib import Path

import pytest

from esbvaktin.speeches.constants import EU_ISSUE_PATTERNS

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

_SCRIPTS = [
    ("prepare_speeches.py", "EU_ISSUE_PATTERNS"),
    ("curate_speech_evidence.py", "EU_ISSUE_PATTERNS"),
    ("export_entities.py", "_EU_ISSUE_PATTERNS"),
]


def _load(script_name):
    path = _SCRIPTS_DIR / script_name
    spec = importlib.util.spec_from_file_location(f"_under_test_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(("script_name", "attr"), _SCRIPTS)
def test_script_uses_canonical_eu_issue_patterns(script_name, attr):
    mod = _load(script_name)
    assert getattr(mod, attr) is EU_ISSUE_PATTERNS
