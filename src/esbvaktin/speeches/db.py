"""Read-only SQLite connection to althingi.db for EU speech queries."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import aiosqlite

_db: aiosqlite.Connection | None = None

# Default: sibling project's DB
_DEFAULT_DB = Path.home() / "althingi" / "althingi-mcp" / "data" / "althingi.db"


def _db_path() -> Path:
    """Resolve database path from ALTHINGI_DB_PATH env var or default."""
    return Path(os.environ.get("ALTHINGI_DB_PATH", str(_DEFAULT_DB)))


# althingi owns this schema; bump in lockstep when althingi migrates (see its session-rollover note).
EXPECTED_ALTHINGI_SCHEMA = 8


def _check_db_health(schema_version, speeches_exist: bool) -> None:
    """Validate the althingi.db we opened (xrepo-06).

    Raises if there is no speeches table: a 0-byte stub or empty DB passes path.exists()
    but would silently serve empty results. Warns — does not crash — on a schema-version
    mismatch (e.g. an althingi v9 migration), so a column-name break surfaces loudly
    instead of corrupting joins. schema_version is None on DBs without the table; skip then.
    """
    if not speeches_exist:
        raise RuntimeError(
            "althingi.db has no 'speeches' table (0-byte stub or empty DB?). "
            "Set ALTHINGI_DB_PATH to the real althingi-mcp database."
        )
    if schema_version is not None and int(schema_version) != EXPECTED_ALTHINGI_SCHEMA:
        logging.getLogger(__name__).warning(
            "althingi.db schema_version=%s but esbvaktin expects %s — a migration may have "
            "renamed columns; verify EU speech queries still resolve (xrepo-06).",
            schema_version,
            EXPECTED_ALTHINGI_SCHEMA,
        )


async def get_db() -> aiosqlite.Connection:
    """Return (and cache) a read-only connection to althingi.db."""
    global _db
    if _db is not None:
        return _db

    path = _db_path()
    if not path.exists():
        raise FileNotFoundError(
            f"althingi.db not found at {path}. "
            "Set ALTHINGI_DB_PATH or run update_week.py in the althingi project."
        )

    # Open read-only via URI to prevent accidental writes
    uri = f"file:{path}?mode=ro"
    _db = await aiosqlite.connect(uri, uri=True)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA query_only = ON")

    # xrepo-06: fail loudly on a stub/empty DB; warn on a schema-version drift.
    cur = await _db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='speeches'")
    speeches_exist = await cur.fetchone() is not None
    schema_version = None
    try:
        sv = await _db.execute("SELECT MAX(version) FROM schema_version")
        row = await sv.fetchone()
        schema_version = row[0] if row else None
    except Exception:
        schema_version = None  # schema_version table absent — skip the version check
    _check_db_health(schema_version, speeches_exist)
    return _db


async def close_db() -> None:
    """Close the cached connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
