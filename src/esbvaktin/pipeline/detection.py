"""Source type detection utilities."""

from __future__ import annotations

import re

# Panel show source slugs (fréttasafn source names)
PANEL_SHOW_SOURCES = {"silfrid", "kastljos", "sprasar", "kiljan"}

# Text markers for panel show detection
PANEL_SHOW_MARKERS = ["**Source:** Silfrið", "**Source:** Kastljós", "(umsjónarmaður)"]

# Regex for speaker-with-role pattern (3+ matches = panel show)
SPEAKER_ROLE_PATTERN = re.compile(r"^([A-ZÁÐÉÍÓÚÝÞÆÖ][^\n:]{2,})\s*\([^)]+\)\s*:", re.MULTILINE)


def is_panel_show(metadata: dict, text: str) -> bool:
    """Detect if an article is a panel show transcript.

    Returns True if any of:
    - metadata ``source`` matches a known panel show slug
    - text contains a known panel show marker string
    - text contains 3+ speaker-with-role patterns (e.g. ``Name (role):``)
    """
    source = (metadata.get("source") or "").lower()
    if source in PANEL_SHOW_SOURCES:
        return True
    for marker in PANEL_SHOW_MARKERS:
        if marker in text:
            return True
    return len(SPEAKER_ROLE_PATTERN.findall(text)) >= 3
