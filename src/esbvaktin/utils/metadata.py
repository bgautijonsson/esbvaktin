"""Article metadata resolution from inbox, URL patterns, and article text.

Provides a single resolution point for article metadata (title, source, date)
that cascades through available sources: inbox lookup → URL date extraction →
article text date parsing. Follows the same pattern as domain.py — small
utility, module-level cache.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

INBOX_PATH = Path("data/inbox/inbox.json")

# Module-level cache: normalised URL → inbox entry dict
_inbox_cache: dict[str, dict] | None = None


@dataclass
class ArticleMetadata:
    title: str | None = None
    source: str | None = None
    date: date | None = None
    url: str | None = None


def _normalise_url(url: str) -> str:
    """Normalise URL for comparison: strip trailing slash, lowercase host."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        # Rebuild with normalised host but preserve path case
        path = parsed.path.rstrip("/")
        return f"{host}{path}"
    except Exception:
        return url.rstrip("/").lower()


def _load_inbox_cache() -> dict[str, dict]:
    """Load inbox.json and index by normalised URL. Cached after first call."""
    global _inbox_cache
    if _inbox_cache is not None:
        return _inbox_cache

    _inbox_cache = {}
    if INBOX_PATH.exists():
        try:
            entries = json.loads(INBOX_PATH.read_text())
            for entry in entries:
                url = entry.get("url", "")
                if url:
                    _inbox_cache[_normalise_url(url)] = entry
        except (json.JSONDecodeError, OSError):
            pass
    return _inbox_cache


def lookup_inbox(url: str) -> dict | None:
    """Look up an article in the inbox by URL.

    Returns the inbox entry dict if found, None otherwise.
    Normalises URLs for matching (strips trailing slash, lowercases host).
    """
    cache = _load_inbox_cache()
    return cache.get(_normalise_url(url))


# Domain-specific URL date patterns
# Group 1: YYYY, Group 2: MM, Group 3: DD
_URL_DATE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # mbl.is, dv.is, xd.is, kratinn.is, stjornmalin.is: /YYYY/MM/DD/ in path
    ("slash", re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")),
    # ruv.is: /YYYY-MM-DD- in path
    ("dash", re.compile(r"/(\d{4})-(\d{2})-(\d{2})-")),
]


def extract_date_from_url(url: str) -> date | None:
    """Extract publication date from URL path patterns.

    Supports:
    - mbl.is, dv.is, xd.is, kratinn.is, stjornmalin.is: /YYYY/MM/DD/
    - ruv.is: /YYYY-MM-DD-
    - Returns None for opaque URLs (visir.is /g/..., etc.)
    """
    try:
        path = urlparse(url).path
    except Exception:
        return None

    for _name, pattern in _URL_DATE_PATTERNS:
        match = pattern.search(path)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
    return None


_MONTHS_IS = {
    "janúar": 1, "febrúar": 2, "mars": 3, "apríl": 4, "maí": 5, "júní": 6,
    "júlí": 7, "ágúst": 8, "september": 9, "október": 10, "nóvember": 11, "desember": 12,
}

# Icelandic date: "9. mars 2026"
_IS_DATE_RE = re.compile(
    r"\b(\d{1,2})\.\s*("
    + "|".join(_MONTHS_IS)
    + r")\s+(\d{4})\b",
    re.IGNORECASE,
)
# ISO date: "2026-03-10" or "2026/03/10"
_ISO_DATE_RE = re.compile(r"\b(20\d{2})[-/](\d{2})[-/](\d{2})\b")
# Fréttasafn metadata line: **Date:** 2026-03-11T11:37:34+00:00
_META_DATE_RE = re.compile(r"\*\*Date:\*\*\s*(20\d{2})-(\d{2})-(\d{2})")


def extract_date_from_text(text: str, limit: int = 1500) -> date | None:
    """Extract publication date from article text header.

    Checks the first `limit` characters for:
    1. Fréttasafn metadata lines (**Date:** ...)
    2. Icelandic dates (9. mars 2026)
    3. ISO dates (2026-03-10)

    Returns the first valid date found, or None.
    """
    head = text[:limit]

    # 1. Fréttasafn metadata (most precise — includes time)
    m = _META_DATE_RE.search(head)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # 2. Icelandic date
    m = _IS_DATE_RE.search(head[:500])
    if m:
        try:
            return date(int(m.group(3)), _MONTHS_IS[m.group(2).lower()], int(m.group(1)))
        except (ValueError, KeyError):
            pass

    # 3. ISO date
    m = _ISO_DATE_RE.search(head[:500])
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None


def resolve_metadata(
    url: str,
    article_text: str | None = None,
) -> ArticleMetadata:
    """Resolve article metadata from all available sources.

    Resolution order (first non-None wins per field):
    1. Inbox lookup (by URL) — has title, source, date
    2. URL date extraction (regex per domain) — date only
    3. Article text date parsing (if text provided) — date only

    Never raises — returns ArticleMetadata with None fields for unresolvable items.
    """
    meta = ArticleMetadata(url=url)

    # 1. Inbox lookup
    inbox_entry = lookup_inbox(url)
    if inbox_entry:
        meta.title = inbox_entry.get("title") or None
        meta.source = inbox_entry.get("source") or None
        date_str = inbox_entry.get("date", "")
        if date_str:
            try:
                meta.date = date.fromisoformat(date_str)
            except (ValueError, TypeError):
                pass

    # 2. URL date extraction (only if inbox didn't provide a date)
    if meta.date is None:
        meta.date = extract_date_from_url(url)

    # 3. Article text date parsing (last resort)
    if meta.date is None and article_text:
        meta.date = extract_date_from_text(article_text)

    return meta
