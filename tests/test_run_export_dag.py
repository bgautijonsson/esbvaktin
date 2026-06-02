"""latency-01: run_export runs the 7 export steps along their real dependency DAG,
executing independent steps concurrently.

Verified dependencies (by reading each script's inputs):
  - steps 1, 2, 3, 4, 6 read only the databases → independent roots
  - step 5 (prepare_site) reads entities.json (1) + evidence_meta/full (2) → {1, 2}
  - step 7 (export_overviews) reads data/export/entities.json (1) → {1}

A failed step, or a failed size-floor gate, skips its dependents. These tests inject
the step runner + gate checker, so no subprocess or database is touched. run_export.py
is a script, loaded via importlib.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_export.py"


def _load():
    spec = importlib.util.spec_from_file_location("_run_export_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve string annotations
    # (from __future__ import annotations) via sys.modules.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_independent_steps_are_all_ready_at_the_start():
    m = _load()
    steps = m.build_steps()
    ready = {s.id for s in m._ready_steps(steps, done=set())}
    # 1,2,3,4,6 read only the DBs — none waits on another.
    assert ready == {"1", "2", "3", "4", "6"}
    # step 7 unlocks once 1 is done; step 5 needs both 1 and 2.
    assert "7" in {s.id for s in m._ready_steps(steps, done={"1"})}
    assert "5" not in {s.id for s in m._ready_steps(steps, done={"1"})}
    assert "5" in {s.id for s in m._ready_steps(steps, done={"1", "2"})}


def test_run_dag_respects_dependencies_on_full_success():
    m = _load()
    steps = m.build_steps()
    result = m.run_dag(steps, runner=lambda step: True)
    assert result.ok
    assert set(result.order) == {s.id for s in steps}
    idx = {sid: i for i, sid in enumerate(result.order)}
    for s in steps:
        for d in s.deps:
            assert idx[d] < idx[s.id], f"{d} must finish before {s.id}"


def test_failed_step_skips_only_its_dependents():
    m = _load()
    steps = m.build_steps()
    result = m.run_dag(steps, runner=lambda step: step.id != "1")
    assert not result.ok
    assert "1" in result.failed
    # 5 (needs 1+2) and 7 (needs 1) are skipped; the independents still run.
    assert result.skipped == {"5", "7"}
    assert {"2", "3", "4", "6"} <= result.succeeded


def test_failed_gate_blocks_dependents_but_not_independents():
    m = _load()
    steps = m.build_steps()

    def gate(path, min_bytes):
        return "evidence_meta" not in path  # fail step 2's gate

    result = m.run_dag(steps, runner=lambda step: True, gate_checker=gate)
    assert not result.ok
    assert "2" in result.failed
    assert "5" in result.skipped  # depends on 2
    assert "7" in result.succeeded  # only depends on 1


def test_command_construction_threads_site_args():
    m = _load()
    steps = {s.id: s for s in m.build_steps()}
    cmd = m._build_command(steps["1"], ["--site-dir", "/tmp/site"])
    assert cmd == ["uv", "run", "python", "scripts/export_entities.py", "--site-dir", "/tmp/site"]
    assert m._build_command(steps["3"], []) == ["uv", "run", "python", "scripts/export_topics.py"]


def test_main_returns_zero_when_all_steps_succeed(monkeypatch):
    """End-to-end glue smoke test: fake subprocess + gate so no DB/site is touched."""
    m = _load()

    class _Fake:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: _Fake())
    monkeypatch.setattr(m, "_gate_checker", lambda path, min_bytes: True)
    assert m.main([]) == 0


def test_main_returns_nonzero_when_a_step_fails(monkeypatch):
    m = _load()

    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: _Fail())
    monkeypatch.setattr(m, "_gate_checker", lambda path, min_bytes: True)
    assert m.main([]) == 1
