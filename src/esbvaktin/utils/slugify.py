"""URL-safe slug generation for Icelandic text."""

import re
import unicodedata


def icelandic_slugify(text: str) -> str:
    """Create a URL-safe slug from Icelandic text."""
    replacements = {
        "þ": "th", "Þ": "th",
        "ð": "d", "Ð": "d",
        "æ": "ae", "Æ": "ae",
        "ö": "o", "Ö": "o",
        "á": "a", "Á": "a",
        "é": "e", "É": "e",
        "í": "i", "Í": "i",
        "ó": "o", "Ó": "o",
        "ú": "u", "Ú": "u",
        "ý": "y", "Ý": "y",
    }
    slug = text
    for orig, repl in replacements.items():
        slug = slug.replace(orig, repl)
    slug = unicodedata.normalize("NFKD", slug)
    slug = slug.encode("ascii", "ignore").decode("ascii")
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug
