"""Tests for the xrepo-01 registry-retirement gate (read-only coverage check).

scripts/retire_registry.py is a standalone script, loaded via importlib.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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


# ── xrepo-01 backfill: orphan exclusion + --backfill orchestration ──────


def test_gate_candidates_excludes_orphan_backfill_urls():
    """The gate audits site/DB-only URLs minus locally-scanned minus the known
    slug-drift orphans (handled out-of-band by marking their article_ids), so a
    post-backfill run can reach 0 even though their URLs can't resolve."""
    mod = _load()
    orphan = next(iter(mod.ORPHAN_BACKFILL))  # an esbvaktin-stored orphan URL
    site_db = {"https://x.is/a", "https://y.is/b", mod._norm(orphan)}
    local: set[str] = set()

    cands = mod.gate_candidates(local, site_db)

    assert mod._norm(orphan) not in cands
    assert {"https://x.is/a", "https://y.is/b"} <= cands


def test_backfill_marks_resolvable_urls_and_orphan_ids():
    """--backfill marks the resolvable gaps by URL and the 2 known orphans by their
    verified frettasafn article_id. Deps are injected so no real DB write happens."""
    mod = _load()
    orphan_keys = {mod._norm(u) for u in mod.ORPHAN_BACKFILL}
    gaps = {"https://x.is/a", "https://y.is/b"} | orphan_keys
    calls: dict[str, tuple] = {}

    def fake_mark_urls(urls, state, metadata_per_url=None):
        calls["mark_urls"] = (list(urls), state, metadata_per_url)
        unmatched = [u for u in urls if u in orphan_keys]  # orphans don't resolve by URL
        return (len(urls) - len(unmatched), unmatched)

    def fake_mark_articles(article_ids, state, metadata=None):
        calls["mark_articles"] = (list(article_ids), state, metadata)
        return len(article_ids)

    url_rows, orphan_ids = mod.backfill(
        gaps, mark_urls_fn=fake_mark_urls, mark_articles_fn=fake_mark_articles
    )

    assert calls["mark_urls"][1] == "processed"
    assert set(calls["mark_urls"][0]) == gaps
    assert calls["mark_articles"][0] == list(mod.ORPHAN_BACKFILL.values())
    assert calls["mark_articles"][1] == "processed"
    assert orphan_ids == list(mod.ORPHAN_BACKFILL.values())


def test_backfill_guard_raises_when_unmatched_drifts_from_known_orphans():
    """If the unmatched set no longer equals the known orphan URLs (gap set drifted —
    a new orphan, or the known ones already resolved), fail loud rather than mis-backfill;
    and do NOT mark any article_ids."""
    mod = _load()
    gaps = {"https://x.is/a"}  # no known orphans present
    marked_articles = []

    def fake_mark_urls(urls, state, metadata_per_url=None):
        return (len(urls), [])  # everything resolved, nothing unmatched

    def fake_mark_articles(article_ids, state, metadata=None):
        marked_articles.extend(article_ids)
        return len(article_ids)

    with pytest.raises(RuntimeError, match="drift"):
        mod.backfill(gaps, mark_urls_fn=fake_mark_urls, mark_articles_fn=fake_mark_articles)

    assert marked_articles == []  # guard fired before any article_id write


def test_main_backfill_branch_operates_on_raw_gaps(monkeypatch):
    """`--backfill` must pass the RAW gap set (orphans included) to backfill(), not the
    orphan-excluded gate candidates — else the orphans never surface for the id-backfill."""
    mod = _load()
    orphan_keys = {mod._norm(u) for u in mod.ORPHAN_BACKFILL}
    local = {"https://local.is/x"}
    site_db = {"https://gap.is/a"} | orphan_keys

    monkeypatch.setattr(mod, "analyses_urls", lambda: local)
    monkeypatch.setattr(mod, "site_report_urls", lambda: site_db)
    monkeypatch.setattr(mod, "db_sighting_urls", lambda conn: set())
    monkeypatch.setattr(mod, "consumer_state_by_url", lambda urls: dict.fromkeys(urls, None))

    class _Conn:
        def close(self):  # noqa: D401
            pass

    import esbvaktin.ground_truth.operations as ops

    monkeypatch.setattr(ops, "get_connection", lambda: _Conn())

    seen: dict[str, set] = {}

    def fake_backfill(gaps, **kw):
        seen["gaps"] = set(gaps)
        return (1, list(mod.ORPHAN_BACKFILL.values()))

    monkeypatch.setattr(mod, "backfill", fake_backfill)

    rc = mod.main(["--backfill"])

    assert rc == 0
    assert seen["gaps"] == {"https://gap.is/a"} | orphan_keys
