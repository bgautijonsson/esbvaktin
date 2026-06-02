"""rel-03 / rel-08: validate that a pipeline work dir's agent outputs were written.

Subagents report success without writing their output ~25% of the time. For each
`_context_<step>.md` present in a work dir, the matching `_<step>.json` must exist and be
non-empty. This is the reliable detection core that the advisory SubagentStop hook calls
(and that orchestration/CI can call to hard-fail).

validate_workdir.py is a script, loaded via importlib.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "validate_workdir.py"


def _load():
    spec = importlib.util.spec_from_file_location("_validate_workdir_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_no_context_files_means_nothing_missing(tmp_path):
    m = _load()
    assert m.missing_outputs(tmp_path) == []


def test_context_with_written_output_is_ok(tmp_path):
    m = _load()
    (tmp_path / "_context_extraction.md").write_text("ctx")
    (tmp_path / "_claims.json").write_text("[]")
    assert m.missing_outputs(tmp_path) == []


def test_context_without_output_is_flagged(tmp_path):
    m = _load()
    (tmp_path / "_context_extraction.md").write_text("ctx")
    assert m.missing_outputs(tmp_path) == [("_context_extraction.md", "_claims.json")]


def test_empty_output_counts_as_missing(tmp_path):
    m = _load()
    (tmp_path / "_context_assessment.md").write_text("ctx")
    (tmp_path / "_assessments.json").write_text("")  # written but empty
    assert m.missing_outputs(tmp_path) == [("_context_assessment.md", "_assessments.json")]


def test_only_present_contexts_are_checked(tmp_path):
    m = _load()
    (tmp_path / "_context_extraction.md").write_text("ctx")
    (tmp_path / "_claims.json").write_text("[{}]")
    (tmp_path / "_context_omissions.md").write_text("ctx")  # output not yet written
    assert m.missing_outputs(tmp_path) == [("_context_omissions.md", "_omissions.json")]


def test_most_recent_workdir_picks_newest(tmp_path):
    m = _load()
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    assert m.most_recent_workdir(tmp_path) == b


def test_most_recent_workdir_none_when_empty(tmp_path):
    m = _load()
    assert m.most_recent_workdir(tmp_path) is None
