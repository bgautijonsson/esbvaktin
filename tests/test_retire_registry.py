"""Tests for the xrepo-01 registry-retirement gate (read-only coverage check).

scripts/retire_registry.py is a standalone script, loaded via importlib.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "retire_registry.py"


def _load():
    spec = importlib.util.spec_from_file_location("retire_registry", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_uncovered_urls_excludes_locally_scanned_and_consumer_state_known():
    """A source URL loses dedup on retirement ONLY if it is neither covered by the
    post-retirement data/analyses/ scan (locally_covered) NOR known to consumer_state.
    data/analyses/ URLs absent from consumer_state are still scan-covered — not at risk."""
    mod = _load()
    state = {"a": "processed", "b": "rejected", "c": None, "d": None}
    locally_covered = {"d"}  # d has a local data/analyses/ dir -> scan covers it

    # a/b in consumer_state => covered; d locally scanned => covered; only c is at risk.
    assert mod.uncovered_urls({"a", "b", "c", "d"}, locally_covered, state) == {"c"}
    # All locally covered => nothing at risk even if absent from consumer_state.
    assert mod.uncovered_urls({"c", "d"}, {"c", "d"}, state) == set()
    assert mod.uncovered_urls(set(), locally_covered, state) == set()
