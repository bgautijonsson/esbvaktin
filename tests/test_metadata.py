"""Tests for the article metadata resolution utility."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest

from esbvaktin.utils.metadata import (
    extract_date_from_text,
    extract_date_from_url,
    lookup_inbox,
    resolve_metadata,
)

# --- URL date extraction ---


def test_extract_date_mbl_url():
    url = "https://www.mbl.is/frettir/innlent/2026/03/10/esb-umraeda-haldin/"
    assert extract_date_from_url(url) == date(2026, 3, 10)


def test_extract_date_dv_url():
    url = "https://www.dv.is/eyjan/2026/03/11/pistill-um-esb/"
    assert extract_date_from_url(url) == date(2026, 3, 11)


def test_extract_date_ruv_url():
    url = "https://www.ruv.is/frettir/innlent/2026-03-10-esb-umraeda-a-althingi"
    assert extract_date_from_url(url) == date(2026, 3, 10)


def test_extract_date_xd_url():
    url = "https://xd.is/2026/03/17/esb-umraeda/"
    assert extract_date_from_url(url) == date(2026, 3, 17)


def test_extract_date_kratinn_url():
    url = "https://kratinn.is/2026/03/15/fullveldi-islands/"
    assert extract_date_from_url(url) == date(2026, 3, 15)


def test_extract_date_stjornmalin_url():
    url = "https://stjornmalin.is/2026/03/12/esb-pistill/"
    assert extract_date_from_url(url) == date(2026, 3, 12)


def test_extract_date_visir_returns_none():
    """Vísir uses opaque IDs — no date in URL."""
    url = "https://www.visir.is/g/20262856813d/esb-umraeda"
    assert extract_date_from_url(url) is None


def test_extract_date_no_date_in_path():
    url = "https://example.com/article/some-slug"
    assert extract_date_from_url(url) is None


def test_extract_date_invalid_date_in_url():
    """Invalid date components (month 13) should return None."""
    url = "https://www.mbl.is/frettir/innlent/2026/13/45/bad-date/"
    assert extract_date_from_url(url) is None


# --- Inbox lookup ---


MOCK_INBOX = [
    {
        "id": "mbl-abc123",
        "url": "https://www.mbl.is/frettir/innlent/2026/03/10/esb-umraeda/",
        "title": "ESB-umræða haldin",
        "source": "mbl.is",
        "date": "2026-03-10",
        "status": "pending",
    },
    {
        "id": "ruv-def456",
        "url": "https://ruv.is/frettir/2026-03-11-test-article",
        "title": "Test Article",
        "source": "RÚV",
        "date": "2026-03-11",
        "status": "processed",
    },
]


@pytest.fixture(autouse=True)
def _reset_inbox_cache():
    """Reset the module-level inbox cache between tests."""
    import esbvaktin.utils.metadata as mod

    mod._inbox_cache = None
    yield
    mod._inbox_cache = None


def _mock_inbox_path(tmp_path, inbox_data=None):
    """Create a mock inbox file and patch INBOX_PATH."""
    inbox_file = tmp_path / "inbox.json"
    inbox_file.write_text(json.dumps(inbox_data or MOCK_INBOX, ensure_ascii=False))
    return patch("esbvaktin.utils.metadata.INBOX_PATH", inbox_file)


def test_lookup_inbox_found(tmp_path):
    with _mock_inbox_path(tmp_path):
        result = lookup_inbox("https://www.mbl.is/frettir/innlent/2026/03/10/esb-umraeda/")
    assert result is not None
    assert result["id"] == "mbl-abc123"
    assert result["title"] == "ESB-umræða haldin"


def test_lookup_inbox_normalises_url(tmp_path):
    """Trailing slash and www prefix should not matter."""
    with _mock_inbox_path(tmp_path):
        # URL without trailing slash should still match
        result = lookup_inbox("https://www.mbl.is/frettir/innlent/2026/03/10/esb-umraeda")
    assert result is not None
    assert result["id"] == "mbl-abc123"


def test_lookup_inbox_www_prefix(tmp_path):
    """www. prefix stripped during normalisation."""
    with _mock_inbox_path(tmp_path):
        # Original has www., query without www. should match
        result = lookup_inbox("https://mbl.is/frettir/innlent/2026/03/10/esb-umraeda/")
    assert result is not None
    assert result["id"] == "mbl-abc123"


def test_lookup_inbox_missing(tmp_path):
    with _mock_inbox_path(tmp_path):
        result = lookup_inbox("https://example.com/not-in-inbox")
    assert result is None


def test_lookup_inbox_empty_file(tmp_path):
    with _mock_inbox_path(tmp_path, inbox_data=[]):
        result = lookup_inbox("https://www.mbl.is/any-url")
    assert result is None


def test_lookup_inbox_no_file(tmp_path):
    """Missing inbox file should return None, not raise."""
    missing = tmp_path / "nonexistent" / "inbox.json"
    with patch("esbvaktin.utils.metadata.INBOX_PATH", missing):
        result = lookup_inbox("https://example.com")
    assert result is None


# --- resolve_metadata ---


def test_resolve_metadata_prefers_inbox(tmp_path):
    """Inbox date should win over URL extraction."""
    with _mock_inbox_path(tmp_path):
        meta = resolve_metadata("https://www.mbl.is/frettir/innlent/2026/03/10/esb-umraeda/")
    assert meta.date == date(2026, 3, 10)
    assert meta.title == "ESB-umræða haldin"
    assert meta.source == "mbl.is"


def test_resolve_metadata_falls_back_to_url(tmp_path):
    """When URL not in inbox, extract date from URL pattern."""
    with _mock_inbox_path(tmp_path):
        meta = resolve_metadata("https://www.mbl.is/frettir/innlent/2026/03/15/other-article/")
    assert meta.date == date(2026, 3, 15)
    assert meta.title is None  # Not in inbox
    assert meta.source is None


def test_resolve_metadata_all_none(tmp_path):
    """No inbox match, no URL pattern → all None fields (except url)."""
    with _mock_inbox_path(tmp_path):
        meta = resolve_metadata("https://www.visir.is/g/20262856813d/opaque")
    assert meta.date is None
    assert meta.title is None
    assert meta.source is None
    assert meta.url == "https://www.visir.is/g/20262856813d/opaque"


def test_resolve_metadata_inbox_date_overrides_url(tmp_path):
    """If inbox has a different date than URL, inbox wins."""
    inbox = [
        {
            "id": "test-1",
            "url": "https://www.mbl.is/frettir/innlent/2026/03/10/slug/",
            "title": "Title",
            "source": "mbl.is",
            "date": "2026-03-09",  # Inbox says 9th, URL says 10th
            "status": "pending",
        }
    ]
    with _mock_inbox_path(tmp_path, inbox_data=inbox):
        meta = resolve_metadata("https://www.mbl.is/frettir/innlent/2026/03/10/slug/")
    assert meta.date == date(2026, 3, 9)  # Inbox wins


# --- extract_date_from_text ---


def test_extract_date_icelandic():
    text = "Höfundur: Jón\n9. mars 2026\nGreinin fjallar um..."
    assert extract_date_from_text(text) == date(2026, 3, 9)


def test_extract_date_icelandic_december():
    text = "21. desember 2025 — Gylfi Magnússon skrifar..."
    assert extract_date_from_text(text) == date(2025, 12, 21)


def test_extract_date_iso():
    text = "Published: 2026-03-10\nContent starts here..."
    assert extract_date_from_text(text) == date(2026, 3, 10)


def test_extract_date_frettasafn_metadata():
    text = '**Source:** Vísir | **Date:** 2026-03-11T11:37:34+00:00 | **URL:** https://...\n\nContent'
    assert extract_date_from_text(text) == date(2026, 3, 11)


def test_extract_date_frettasafn_preferred_over_icelandic():
    """Fréttasafn metadata line should win over Icelandic date deeper in text."""
    text = '**Source:** Vísir | **Date:** 2026-03-11T11:37:34+00:00\n\n9. mars 2026\nContent'
    assert extract_date_from_text(text) == date(2026, 3, 11)


def test_extract_date_no_date():
    text = "This article has no date anywhere in its header."
    assert extract_date_from_text(text) is None


def test_extract_date_respects_limit():
    """Date beyond the limit should not be found."""
    text = "x" * 2000 + "\n9. mars 2026"
    assert extract_date_from_text(text, limit=1500) is None


# --- resolve_metadata with article_text ---


def test_resolve_metadata_falls_back_to_text(tmp_path):
    """Opaque URL + no inbox → falls back to article text."""
    text = "9. mars 2026\nGreinin fjallar um ESB-aðild."
    with _mock_inbox_path(tmp_path):
        meta = resolve_metadata(
            "https://www.visir.is/g/20262856813d/opaque",
            article_text=text,
        )
    assert meta.date == date(2026, 3, 9)


def test_resolve_metadata_inbox_beats_text(tmp_path):
    """Inbox date should still win over article text date."""
    text = "15. mars 2026\nContent..."
    with _mock_inbox_path(tmp_path):
        meta = resolve_metadata(
            "https://www.mbl.is/frettir/innlent/2026/03/10/esb-umraeda/",
            article_text=text,
        )
    assert meta.date == date(2026, 3, 10)  # Inbox date, not text date
