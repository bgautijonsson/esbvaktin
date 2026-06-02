"""rel-06: post-batch reconciliation validator.

A read-only check that a batch's work is internally consistent across the three state
stores — inbox.json, frettasafn's consumer_state, and claim_sightings — so a silently
dropped article or verdict becomes a loud, named failure (exits non-zero on drift).

reconcile_batch_state.py is a script, loaded via importlib.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "reconcile_batch_state.py"


def _load():
    spec = importlib.util.spec_from_file_location("_reconcile_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_clean_state_has_no_findings():
    m = _load()
    inbox = [
        {"url": "https://x/1", "status": "processed"},
        {"url": "https://x/2", "status": "queued"},
    ]
    cs = {"https://x/1": "processed", "https://x/2": "pending"}
    findings = m.reconcile(inbox, cs, report_urls={"https://x/1"}, sighting_urls={"https://x/1"})
    assert findings == []


def test_processed_inbox_without_consumer_state_is_flagged():
    m = _load()
    inbox = [{"url": "https://x/1", "status": "processed"}]
    findings = m.reconcile(inbox, consumer_state_by_url={}, report_urls=set(), sighting_urls=set())
    assert [f.kind for f in findings] == ["processed_without_consumer_state"]


def test_queued_but_processed_is_flagged():
    m = _load()
    inbox = [{"url": "https://x/1", "status": "queued"}]
    cs = {"https://x/1": "processed"}
    findings = m.reconcile(inbox, cs, report_urls=set(), sighting_urls=set())
    assert [f.kind for f in findings] == ["queued_but_processed"]


def test_report_without_sightings_is_flagged():
    m = _load()
    findings = m.reconcile([], {}, report_urls={"https://x/1"}, sighting_urls=set())
    assert [f.kind for f in findings] == ["report_without_sightings"]


def test_has_drift_drives_the_exit_code():
    m = _load()
    assert m.has_drift([]) is False
    assert m.has_drift([m.Finding("processed_without_consumer_state", "u", "d")]) is True
