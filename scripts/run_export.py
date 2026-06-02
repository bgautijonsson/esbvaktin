#!/usr/bin/env python3
"""Run the ESBvaktin export pipeline along its real dependency DAG (latency-01).

The seven export steps are NOT a serial chain. Reading each script's inputs shows:

  - steps 1, 2, 3, 4, 6 read only the databases (Postgres / read-only althingi.db)
    and write disjoint files → mutually independent roots
  - step 5 (prepare_site) reads entities.json (step 1) + evidence_meta/full (step 2)
  - step 7 (export_overviews) reads data/export/entities.json (step 1)

So independent steps run concurrently; step 5 starts once 1 and 2 finish, step 7 once
1 finishes. A failed step — or a failed size-floor gate on its output — skips every
step that depends on it (transitively) and the run exits non-zero.

Usage:
    uv run python scripts/run_export.py --site-dir ~/esbvaktin-site
    uv run python scripts/run_export.py                 # export to data/export/ only
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Step:
    id: str
    desc: str
    script: str
    deps: tuple[str, ...] = ()
    gate: tuple[str, int] | None = None  # (path relative to repo root, min bytes)


def build_steps() -> list[Step]:
    """The export DAG. Dependencies were verified by reading each script's inputs."""
    return [
        Step("1", "Export entities", "export_entities.py"),
        Step(
            "2",
            "Export evidence",
            "export_evidence.py",
            gate=("data/export/evidence_meta.json", 100),
        ),
        Step("3", "Export topics", "export_topics.py"),
        Step("4", "Export claims", "export_claims.py", gate=("data/export/claims.json", 100)),
        Step("5", "Prepare site data", "prepare_site.py", deps=("1", "2")),
        Step("6", "Prepare speeches", "prepare_speeches.py"),
        Step("7", "Export overviews", "export_overviews.py", deps=("1",)),
    ]


def _ready_steps(steps: list[Step], done: set[str], started: set[str] | None = None) -> list[Step]:
    """Steps whose dependencies are all satisfied and which have not started yet."""
    started = started or set()
    return [s for s in steps if s.id not in started and all(d in done for d in s.deps)]


@dataclass
class DagResult:
    succeeded: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    order: list[str] = field(default_factory=list)  # ids in completion order

    @property
    def ok(self) -> bool:
        return not self.failed and not self.skipped


def run_dag(steps, runner, gate_checker=None, max_workers: int = 8) -> DagResult:
    """Execute ``steps`` respecting ``deps``, running independent steps concurrently.

    ``runner(step) -> bool`` returns True on success; ``gate_checker(path, min_bytes)
    -> bool`` validates a step's output. A step whose runner returns False or whose
    gate fails is marked failed; any step with a failed/skipped dependency is skipped.
    """
    result = DagResult()
    started: set[str] = set()

    def cascade_skips() -> None:
        changed = True
        while changed:
            changed = False
            blocked = result.failed | result.skipped
            for s in steps:
                if s.id not in started and any(d in blocked for d in s.deps):
                    result.skipped.add(s.id)
                    started.add(s.id)
                    changed = True

    def step_ok(step: Step) -> bool:
        if not runner(step):
            return False
        if step.gate and gate_checker is not None:
            path, min_bytes = step.gate
            if not gate_checker(path, min_bytes):
                return False
        return True

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        running: dict = {}
        while True:
            cascade_skips()
            for s in _ready_steps(steps, result.succeeded, started):
                started.add(s.id)
                running[pool.submit(step_ok, s)] = s
            if not running:
                break
            done, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for fut in done:
                step = running.pop(fut)
                result.order.append(step.id)
                if fut.result():
                    result.succeeded.add(step.id)
                else:
                    result.failed.add(step.id)
    cascade_skips()
    return result


def _build_command(step: Step, site_args: list[str]) -> list[str]:
    return ["uv", "run", "python", f"scripts/{step.script}", *site_args]


def _subprocess_runner(site_args: list[str]):
    def run(step: Step) -> bool:
        cmd = _build_command(step, site_args)
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
        ok = proc.returncode == 0
        # Print each step's output as one grouped block (steps run concurrently).
        header = f"\n=== Step {step.id}: {step.desc} ===  ({' '.join(cmd)})"
        print(header)
        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        print(f"  [{'OK' if ok else 'FAIL'}] Step {step.id} (exit {proc.returncode})")
        return ok

    return run


def _gate_checker(path: str, min_bytes: int) -> bool:
    p = PROJECT_ROOT / path
    if not p.exists():
        print(f"  [GATE FAIL] expected file missing: {path}", file=sys.stderr)
        return False
    size = p.stat().st_size
    if size < min_bytes:
        print(f"  [GATE FAIL] file suspiciously small ({size} bytes): {path}", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    site_args: list[str] = []
    if "--site-dir" in argv:
        i = argv.index("--site-dir")
        if i + 1 < len(argv):
            site_args = ["--site-dir", argv[i + 1]]
            print(f"Site directory: {argv[i + 1]}")

    print("ESBvaktin Export Pipeline (DAG-parallel)")
    print("========================================")

    steps = build_steps()
    result = run_dag(steps, _subprocess_runner(site_args), _gate_checker)

    print("\n========================================")
    by_id = {s.id: s for s in steps}
    for sid in sorted(by_id):
        if sid in result.succeeded:
            status = "OK"
        elif sid in result.failed:
            status = "FAIL"
        else:
            status = "SKIPPED"
        print(f"  Step {sid} ({by_id[sid].desc}): {status}")

    if result.ok:
        print("\nAll 7 steps completed successfully.")
        return 0
    print(
        f"\nWARNING: failed={sorted(result.failed)} skipped={sorted(result.skipped)}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
