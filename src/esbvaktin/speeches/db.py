"""Read-only SQLite connection to althingi.db for EU speech queries."""

from __future__ import annotations

import os
from pathlib import Path

import aiosqlite

_db: aiosqlite.Connection | None = None

# Default: sibling project's DB
_DEFAULT_DB = Path.home() / "althingi" / "althingi-mcp" / "data" / "althingi.db"


def _db_path() -> Path:
    """Resolve database path from ALTHINGI_DB_PATH env var or default."""
    return Path(os.environ.get("ALTHINGI_DB_PATH", str(_DEFAULT_DB)))


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
    return _db


async def close_db() -> None:
    """Close the cached connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
