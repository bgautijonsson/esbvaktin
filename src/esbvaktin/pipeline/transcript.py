"""Parse panel show transcripts from fréttasafn into structured data.

Transcripts from fréttasafn (e.g. Silfrið) use a consistent format:
- Markdown header with title, source, date, URL, word count
- Speaker turns labelled as ``Speaker Name (role): text``
- Moderator turns labelled as ``Mælandi N: text``

This module parses that format into structured dataclasses suitable
for the claim extraction pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ArticleEntities, ClaimAssessment

# Speaker label at the start of a line: "Name (role):" or "Mælandi N:"
# Must start with an uppercase letter (including Icelandic characters).
# The label ends at the first colon followed by a space or end of line.
_SPEAKER_RE = re.compile(
    r"^([A-ZÁÐÉÍÓÚÝÞÆÖ][^\n:]{2,}?):\s",
    re.MULTILINE,
)

# Moderator labels: "Mælandi 1", "Mælandi 2", etc.
_MODERATOR_RE = re.compile(r"^Mælandi\s+\d+$")

# Name (role) pattern
_NAME_ROLE_RE = re.compile(r"^(.+?)\s*\(([^)]+)\)$")

# Header metadata patterns
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_SOURCE_RE = re.compile(r"\*\*Source:\*\*\s*([^|]+)")
_DATE_RE = re.compile(r"\*\*Date:\*\*\s*(\S+)")
_URL_RE = re.compile(r"\*\*URL:\*\*\s*(\S+)")
_WORDS_RE = re.compile(r"\*\*Words:\*\*\s*(\d+)")


@dataclass
class TranscriptTurn:
    """A single speaker turn in a panel show transcript."""

    speaker_label: str  # Full label, e.g. "Sigmundur Davíð Gunnlaugsson (formaður Miðflokksins)"
    speaker_name: str  # Just the name, e.g. "Sigmundur Davíð Gunnlaugsson"
    speaker_role: str | None  # Role from parentheses, e.g. "formaður Miðflokksins"
    text: str  # The speech text for this turn
    is_moderator: bool  # True for "Mælandi N" labels


@dataclass
class ParsedTranscript:
    """A fully parsed panel show transcript."""

    title: str
    show_name: str  # e.g. "Silfrið"
    episode: str | None  # e.g. "25. þáttur" (extracted from title if possible)
    date: date | None
    url: str | None
    broadcaster: str | None  # e.g. "RÚV"
    word_count: int
    turns: list[TranscriptTurn] = field(default_factory=list)

    @property
    def participants(self) -> list[dict[str, str | None]]:
        """Unique non-moderator speakers with their roles."""
        seen: dict[str, str | None] = {}
        for turn in self.turns:
            if not turn.is_moderator and turn.speaker_name not in seen:
                seen[turn.speaker_name] = turn.speaker_role
        return [
            {"name": name, "role": role} for name, role in seen.items()
        ]

    @property
    def participant_names(self) -> list[str]:
        """Unique non-moderator speaker names, in order of first appearance."""
        return [p["name"] for p in self.participants]

    @property
    def speaker_turn_counts(self) -> dict[str, int]:
        """Number of turns per speaker (including moderator)."""
        counts: dict[str, int] = {}
        for turn in self.turns:
            label = "Moderator" if turn.is_moderator else turn.speaker_name
            counts[label] = counts.get(label, 0) + 1
        return counts

    @property
    def speaker_word_counts(self) -> dict[str, int]:
        """Word count per speaker (excluding moderator)."""
        counts: dict[str, int] = {}
        for turn in self.turns:
            if not turn.is_moderator:
                counts[turn.speaker_name] = (
                    counts.get(turn.speaker_name, 0) + len(turn.text.split())
                )
        return counts

    def speaker_text(self, speaker_name: str) -> str:
        """Concatenate all turns by a specific speaker."""
        return "\n\n".join(
            turn.text for turn in self.turns
            if turn.speaker_name == speaker_name
        )

    def debate_text(self, include_moderator: bool = False) -> str:
        """Full transcript as labelled text, optionally including moderator."""
        parts = []
        for turn in self.turns:
            if turn.is_moderator and not include_moderator:
                continue
            parts.append(f"**{turn.speaker_name}:** {turn.text}")
        return "\n\n".join(parts)


def _parse_header(text: str) -> dict:
    """Extract metadata from the fréttasafn markdown header."""
    meta: dict = {}

    title_m = _TITLE_RE.search(text)
    if title_m:
        meta["title"] = title_m.group(1).strip()

    source_m = _SOURCE_RE.search(text)
    if source_m:
        raw_source = source_m.group(1).strip()
        # "Silfrið (RÚV)" → show_name="Silfrið", broadcaster="RÚV"
        m = _NAME_ROLE_RE.match(raw_source)
        if m:
            meta["show_name"] = m.group(1).strip()
            meta["broadcaster"] = m.group(2).strip()
        else:
            meta["show_name"] = raw_source
            meta["broadcaster"] = None

    date_m = _DATE_RE.search(text)
    if date_m:
        raw_date = date_m.group(1).strip()
        try:
            meta["date"] = datetime.fromisoformat(raw_date).date()
        except ValueError:
            meta["date"] = None

    url_m = _URL_RE.search(text)
    if url_m:
        meta["url"] = url_m.group(1).strip()

    words_m = _WORDS_RE.search(text)
    if words_m:
        meta["word_count"] = int(words_m.group(1))

    # Try to extract episode from title: "25. þáttur: ..." or "25.þáttur: ..."
    if "title" in meta:
        ep_m = re.match(r"(\d+\.?\s*þáttur)", meta["title"])
        if ep_m:
            meta["episode"] = ep_m.group(1)

    return meta


def _parse_name_role(label: str) -> tuple[str, str | None]:
    """Split 'Name (role)' into (name, role). Returns (label, None) if no parens."""
    m = _NAME_ROLE_RE.match(label.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return label.strip(), None


def _detect_moderator(
    turns: list[TranscriptTurn],
) -> str | None:
    """Auto-detect the moderator as the most-frequent speaker without a role.

    Heuristic: in panel shows, the moderator speaks most often and is listed
    without a parenthetical role (e.g. ``Bergsteinn Sigurðsson`` vs
    ``Sigmundur Davíð Gunnlaugsson (formaður Miðflokksins)``).
    Returns the speaker_name if found, or None.
    """
    no_role: dict[str, int] = {}
    with_role: set[str] = set()
    for turn in turns:
        if turn.speaker_role:
            with_role.add(turn.speaker_name)
        else:
            no_role[turn.speaker_name] = no_role.get(turn.speaker_name, 0) + 1

    # Exclude anyone who also appears with a role (edge case)
    candidates = {n: c for n, c in no_role.items() if n not in with_role}
    if not candidates:
        return None

    # The no-role speaker with the most turns is likely the moderator
    top_name = max(candidates, key=candidates.get)  # type: ignore[arg-type]
    top_count = candidates[top_name]

    # Sanity: should have significantly more turns than any panellist
    # (at least 5 turns to avoid false positives on short transcripts)
    if top_count >= 5:
        return top_name
    return None


def parse_transcript(
    text: str,
    moderator_names: set[str] | None = None,
) -> ParsedTranscript:
    """Parse a fréttasafn panel show transcript into structured data.

    Args:
        text: Full article text from fréttasafn (markdown with header + transcript).
        moderator_names: Explicit set of moderator names. If None, moderators
            are detected by the ``Mælandi N`` pattern plus auto-detection
            (most-frequent speaker without a parenthetical role).

    Returns:
        ParsedTranscript with metadata and speaker turns.
    """
    meta = _parse_header(text)

    # Find all speaker turns by splitting on speaker labels
    splits = list(_SPEAKER_RE.finditer(text))
    turns: list[TranscriptTurn] = []

    for i, match in enumerate(splits):
        label = match.group(1).strip()
        start = match.end()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
        turn_text = text[start:end].strip()

        is_moderator = bool(_MODERATOR_RE.match(label))
        name, role = _parse_name_role(label)

        # Check explicit moderator names
        if moderator_names and name in moderator_names:
            is_moderator = True

        turns.append(TranscriptTurn(
            speaker_label=label,
            speaker_name=name,
            speaker_role=role,
            text=turn_text,
            is_moderator=is_moderator,
        ))

    # Auto-detect moderator if no explicit names given and no Mælandi pattern found
    if not moderator_names and not any(t.is_moderator for t in turns):
        detected = _detect_moderator(turns)
        if detected:
            for turn in turns:
                if turn.speaker_name == detected:
                    turn.is_moderator = True

    return ParsedTranscript(
        title=meta.get("title", ""),
        show_name=meta.get("show_name", ""),
        episode=meta.get("episode"),
        date=meta.get("date"),
        url=meta.get("url"),
        broadcaster=meta.get("broadcaster"),
        word_count=meta.get("word_count", sum(len(t.text.split()) for t in turns)),
        turns=turns,
    )


# ── Simplified entity extraction for panel shows ────────────────────


# Map common Icelandic role patterns to party names
_ROLE_TO_PARTY: dict[str, str] = {
    "miðflokksins": "Miðflokkurinn",
    "miðflokks": "Miðflokkurinn",
    "sjálfstæðisflokksins": "Sjálfstæðisflokkurinn",
    "sjálfstæðisflokks": "Sjálfstæðisflokkurinn",
    "framsóknarflokksins": "Framsóknarflokkurinn",
    "framsóknar": "Framsóknarflokkurinn",
    "samfylkingarinnar": "Samfylkingin",
    "samfylkingar": "Samfylkingin",
    "flokks fólksins": "Flokkur fólksins",
    "viðreisnar": "Viðreisn",
    "vg": "Vinstrihreyfingin – grænt framboð",
    "vinstrihreyfingarinnar": "Vinstrihreyfingin – grænt framboð",
    "pírata": "Píratar",
    "sósíalistaflokksins": "Sósíalistaflokkur Íslands",
}


def _infer_party(role: str | None) -> str | None:
    """Infer party name from a speaker's role label."""
    if not role:
        return None
    lower = role.lower()
    for pattern, party in _ROLE_TO_PARTY.items():
        if pattern in lower:
            return party
    return None


def generate_panel_entities(
    transcript: ParsedTranscript,
    assessments: list[ClaimAssessment],
) -> ArticleEntities:
    """Generate entities from a parsed panel show transcript + assessments.

    In panel shows, speakers are already labelled with names and roles.
    Every claim is attributed as ``asserted`` since speakers directly
    state their positions in a debate. This replaces the entity extraction
    subagent for panel shows.

    Args:
        transcript: Parsed panel show transcript.
        assessments: Assessed claims (with ``speaker_name`` on each claim).

    Returns:
        ArticleEntities with no article_author and all panellists as speakers.
    """
    from .models import (
        ArticleEntities,
        Attribution,
        ClaimAttribution,
        EntityType,
        Speaker,
        Stance,
    )

    # Build a map of speaker_name → list of (claim_index, assessment)
    speaker_claims: dict[str, list[int]] = {}
    for i, assessment in enumerate(assessments):
        name = assessment.claim.speaker_name
        if name:
            speaker_claims.setdefault(name, []).append(i)

    speakers: list[Speaker] = []
    for participant in transcript.participants:
        name = participant["name"]
        role = participant["role"]
        party = _infer_party(role)
        claim_indices = speaker_claims.get(name, [])

        attributions = [
            ClaimAttribution(claim_index=idx, attribution=Attribution.ASSERTED)
            for idx in claim_indices
        ]

        speakers.append(Speaker(
            name=name,
            type=EntityType.INDIVIDUAL,
            role=role,
            party=party,
            stance=Stance.NEUTRAL,  # determined by export pipeline from claim content
            attributions=attributions,
        ))

    return ArticleEntities(
        article_author=None,
        speakers=speakers,
    )
