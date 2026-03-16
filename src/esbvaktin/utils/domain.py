"""URL domain extraction with podcast CDN alias resolution."""

from urllib.parse import urlparse

# Podcast CDN domains → parent broadcaster
_DOMAIN_ALIASES: dict[str, str] = {
    "shows.acast.com": "ruv.is",
    "ruv-radio.akamaized.net": "ruv.is",
    "podcasters.spotify.com": "mbl.is",
    "anchor.fm": "mbl.is",
}


def extract_domain(url: str | None) -> str | None:
    """Extract domain from a URL, stripping www. and resolving CDN aliases.

    >>> extract_domain("https://www.visir.is/g/123")
    'visir.is'
    >>> extract_domain("https://shows.acast.com/silfrid/episodes/123")
    'ruv.is'
    >>> extract_domain(None)
    """
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return _DOMAIN_ALIASES.get(host, host) or None
    except Exception:
        return None
