"""Tests for the althingi.db health guard (xrepo-06).

esbvaktin reads the sibling althingi.db read-only, pinned to its schema. The guard turns
two silent failure modes loud: a 0-byte/empty stub (path.exists() passes but there's no
speeches table) serving empty results, and an althingi schema migration (v9) that could
break column-name joins without warning.
"""

import logging

import pytest

from esbvaktin.speeches.db import EXPECTED_ALTHINGI_SCHEMA, _check_db_health


def test_raises_when_speeches_table_missing_or_empty():
    """A 0-byte stub has no speeches table — fail loudly instead of serving empty results."""
    with pytest.raises(RuntimeError):
        _check_db_health(schema_version=EXPECTED_ALTHINGI_SCHEMA, speeches_exist=False)


def test_passes_on_healthy_db():
    _check_db_health(schema_version=EXPECTED_ALTHINGI_SCHEMA, speeches_exist=True)


def test_warns_on_schema_mismatch(caplog):
    with caplog.at_level(logging.WARNING):
        _check_db_health(schema_version=EXPECTED_ALTHINGI_SCHEMA + 1, speeches_exist=True)
    assert any("schema" in r.message.lower() for r in caplog.records)


def test_no_warning_when_schema_version_unknown(caplog):
    """schema_version table may be absent on older DBs — skip the check, don't warn."""
    with caplog.at_level(logging.WARNING):
        _check_db_health(schema_version=None, speeches_exist=True)
    assert not caplog.records
