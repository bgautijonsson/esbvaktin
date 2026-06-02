"""Tests for prepare_site.py's verdict-overlay safety guard (xrepo-10).

prepare_site.py is a script (not a package module), so it is loaded via importlib.
Its top level is import-safe: the DB connection is lazy inside _load_db_verdicts().
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "prepare_site.py"


def _load_prepare_site():
    spec = importlib.util.spec_from_file_location("_prepare_site_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestVerdictOverlayGuard:
    def test_empty_overlay_with_reports_aborts(self):
        """Reports on disk + empty DB overlay = DB was down → refuse to ship stale verdicts."""
        ps = _load_prepare_site()
        with pytest.raises(SystemExit):
            ps._check_overlay_present({}, report_count=5, allow_empty=False)

    def test_populated_overlay_passes(self):
        ps = _load_prepare_site()
        # No raise expected.
        ps._check_overlay_present(
            {"claim text": {"verdict": "supported"}}, report_count=5, allow_empty=False
        )

    def test_no_reports_does_not_abort(self):
        """A genuinely empty pipeline (no reports) is fine — nothing to overlay."""
        ps = _load_prepare_site()
        ps._check_overlay_present({}, report_count=0, allow_empty=False)

    def test_allow_empty_override_passes(self):
        """The override hatch lets a genuinely empty database through."""
        ps = _load_prepare_site()
        ps._check_overlay_present({}, report_count=5, allow_empty=True)
