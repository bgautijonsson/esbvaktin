"""Tests for the synchronous frettasafn consumer_state bridge."""

import sqlite3

from esbvaktin.utils import frettasafn_state


def test_connect_sets_explicit_busy_timeout(tmp_path, monkeypatch):
    """_connect sets an EXPLICIT busy_timeout so a write-back survives a concurrent 30-min
    scrape instead of erroring with 'database is locked' (rel-05).

    Python's sqlite3.connect() defaults timeout=5.0 (=5000ms), but relying on that implicit
    default is fragile — a future refactor could pass timeout=0 or use a different helper.
    Asserting 10000 (distinct from the 5000 default) proves the PRAGMA is set deliberately.
    """
    db = tmp_path / "frettasafn.db"
    sqlite3.connect(str(db)).close()  # create an empty file so _connect() doesn't raise
    monkeypatch.setenv("FRETTASAFN_DB", str(db))

    conn = frettasafn_state._connect()
    try:
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy_timeout == 10000
    finally:
        conn.close()
