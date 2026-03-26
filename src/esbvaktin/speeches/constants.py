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
