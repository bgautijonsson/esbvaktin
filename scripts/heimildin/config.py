"""Heimildin project configuration.

Comparative analysis of Alþingi rhetoric: ESB (2024-2026) vs EES (1991-1993).
Client: Heimildin (Aðalsteinn Kjartansson). Metill ehf.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DEFAULT_DB = Path.home() / "althingi" / "althingi-mcp" / "data" / "althingi.db"

WORK_DIR = Path("data/heimildin")
DELIVERABLES_DIR = Path.home() / "metill-ehf" / "Deliverables" / "Heimildin"

# ---------------------------------------------------------------------------
# Debate definitions — each era's key issue numbers and sessions
# ---------------------------------------------------------------------------

DEBATES: dict[str, list[dict]] = {
    "esb": [
        {
            "issue_nr": "516",
            "session": 157,
            "title": "þjóðaratkvæðagreiðsla um framhald viðræðna um aðild Íslands að ESB",
            "dates": ["2026-03-09", "2026-03-10", "2026-03-16"],
        },
        # EEA review debate — add if needed
        # {"issue_nr": "85", "session": 156, ...},
    ],
    "ees": [
        {
            "issue_nr": "21",
            "session": 115,
            "title": "skýrsla utanrrh. um niðurstöður samninga um EES",
            "dates": None,  # fetch all dates
        },
        {
            "issue_nr": "440",
            "session": 116,
            "title": "Evrópskt efnahagssvæði",
            "dates": None,
        },
        {
            "issue_nr": "303",
            "session": 116,
            "title": "tvíhliða samskipti við Evrópubandalagið",
            "dates": None,
        },
    ],
}

# Speech types to include (skip andsvör and procedural)
SUBSTANTIVE_TYPES = {"ræða", "flutningsræða", "ráðherraræða"}

# ---------------------------------------------------------------------------
# Topic taxonomy (shared with esbvaktin where applicable)
# ---------------------------------------------------------------------------

KNOWN_TOPICS = [
    "fisheries",
    "trade",
    "sovereignty",
    "eea_eu_law",
    "agriculture",
    "precedents",
    "currency",
    "labour",
    "energy",
    "housing",
    "defence",
    "democracy",
    "environment",
    "other",
]

# ---------------------------------------------------------------------------
# Party abbreviation → full name (covers both eras)
# ---------------------------------------------------------------------------

PARTY_NAMES = {
    # Current parties
    "D": "Sjálfstæðisflokkur",
    "B": "Framsóknarflokkur",
    "S": "Samfylkingin",
    "V": "Vinstri-Grænir",
    "C": "Viðreisn",
    "M": "Miðflokkurinn",
    "F": "Flokkur fólksins",
    "P": "Píratar",
    "J": "Sóknarflokkur",
    # Historical parties (1990s)
    "A": "Alþýðuflokkur",
    "AB": "Alþýðubandalag",
    "K": "Kvennalistinn",
    "T": "Borgaraflokkurinn",
}


# ---------------------------------------------------------------------------
# Database access (sync sqlite3, read-only — same pattern as fact_check.py)
# ---------------------------------------------------------------------------


def db_path() -> Path:
    return Path(os.environ.get("ALTHINGI_DB_PATH", str(_DEFAULT_DB)))


def connect() -> sqlite3.Connection:
    path = db_path()
    if not path.exists():
        raise FileNotFoundError(f"althingi.db not found at {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def speech_url(session: int, speech_id: str) -> str:
    return f"https://www.althingi.is/altext/raeda/{session}/{speech_id}.html"


def party_name(abbrev: str) -> str:
    return PARTY_NAMES.get(abbrev, abbrev)
