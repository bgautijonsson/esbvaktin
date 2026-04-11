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
    ],
    "ees": [
        {
            "issue_nr": "1",
            "session": 116,
            "title": "Evrópskt efnahagssvæði (aðalumræða)",
            "dates": None,
        },
        {
            "issue_nr": "21",
            "session": 115,
            "title": "skýrsla utanrrh. um niðurstöður samninga um EES",
            "dates": None,
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

# Speech types to include
SUBSTANTIVE_TYPES = {"ræða", "flutningsræða", "ráðherraræða"}
REPLY_TYPES = {"andsvar", "svar"}

# Minimum word count for inclusion
MIN_WORDS_SPEECH = 200
MIN_WORDS_REPLY = 150

# Issue title patterns for filtering off-topic speeches (P1.4)
EU_TITLE_PATTERNS = [
    "evróp",
    "ees",
    "esb",
    "evrópubandalag",
    "evrópusamband",
    "efnahagssvæð",
    "fríverslunarsamtök",
    "aðild",
    "tvíhliða",
    "þjóðaratkvæðagreiðsl",
]

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

TOPIC_LABELS_IS: dict[str, str] = {
    "fisheries": "Sjávarútvegur",
    "trade": "Viðskipti",
    "sovereignty": "Fullveldi",
    "eea_eu_law": "EES/ESB-löggjöf",
    "agriculture": "Landbúnaður",
    "precedents": "Fordæmi",
    "currency": "Gjaldmiðill",
    "labour": "Vinnumarkaður",
    "energy": "Orkumál",
    "housing": "Húsnæðismál",
    "defence": "Varnarmál",
    "democracy": "Lýðræði/ferli",
    "environment": "Umhverfismál",
    "other": "Annað",
}

TOPIC_LABELS_IS_LOWER: dict[str, str] = {k: v.lower() for k, v in TOPIC_LABELS_IS.items()}

TOPIC_PREFIX_MAP: dict[str, str] = {
    "FIS": "fisheries",
    "TRA": "trade",
    "SOV": "sovereignty",
    "EEA": "eea_eu_law",
    "AGR": "agriculture",
    "PRE": "precedents",
    "CUR": "currency",
    "LAB": "labour",
    "ENE": "energy",
    "HOU": "housing",
    "DEF": "defence",
    "DEM": "democracy",
    "ENV": "environment",
    "OTH": "other",
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


def is_eu_relevant(issue_title: str) -> bool:
    """Check if an issue title is EU/EES-relevant (filters off-topic speeches)."""
    title_lower = issue_title.lower()
    return any(pat in title_lower for pat in EU_TITLE_PATTERNS)
