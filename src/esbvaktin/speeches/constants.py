"""Shared EU keyword and pattern constants for speech search."""

# FTS5 query string for EU-related speech content
EU_KEYWORDS_FTS = (
    '"ESB" OR "Evrópusamband" OR "Evrópusambandið" OR "Evrópusambands"'
    ' OR "aðildarviðræður" OR "aðildarumsókn" OR "aðild"'
    ' OR "þjóðaratkvæðagreiðsla" OR "þjóðaratkvæðagreiðslu"'
    ' OR "Evrópumál" OR "EES"'
)

# LIKE patterns for filtering by issue title
EU_ISSUE_PATTERNS = [
    "%Evróp%",
    "%ESB%",
    "%aðild%Evrópu%",
    "%aðildarviðræð%",
    "%aðildarumsókn%",
    "%þjóðaratkvæðagreiðsl%",
    "%Evrópumál%",
]

# Icelandic ballot letters (listabókstafir) for the parties currently in Alþingi,
# mapped to the exact full names stored in althingi.db's `party` column. Callers
# (and the MCP docstrings) supply the letter; the DB never stored it, so an
# unmapped party filter previously matched nothing. Verified against the live
# DB (schema v8): every value below is present in `speech_texts.party`.
PARTY_ABBREVIATIONS = {
    "B": "Framsóknarflokkur",
    "C": "Viðreisn",
    "D": "Sjálfstæðisflokkur",
    "F": "Flokkur fólksins",
    "M": "Miðflokkurinn",
    "P": "Píratar",
    "S": "Samfylkingin",
    "V": "Vinstrihreyfingin - grænt framboð",
}


def normalise_party(party: str) -> str:
    """Resolve a party filter value to the form stored in althingi.db.

    A known ballot letter (case-insensitive, e.g. ``"D"``) maps to its full
    Icelandic party name. Anything else — a full name already, or an unknown
    token — is returned unchanged, so full-name filters keep working and an
    unrecognised value degrades to a literal no-match rather than a crash.
    """
    if not party:
        return party
    return PARTY_ABBREVIATIONS.get(party.strip().upper(), party)
