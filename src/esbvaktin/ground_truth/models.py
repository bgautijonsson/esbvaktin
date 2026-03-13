"""Pydantic models for the Ground Truth Database."""

import warnings
from datetime import date
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator


class Domain(StrEnum):
    LEGAL = "legal"
    ECONOMIC = "economic"
    POLITICAL = "political"
    PRECEDENT = "precedent"


class SourceType(StrEnum):
    OFFICIAL_STATISTICS = "official_statistics"
    LEGAL_TEXT = "legal_text"
    ACADEMIC_PAPER = "academic_paper"
    EXPERT_ANALYSIS = "expert_analysis"
    INTERNATIONAL_ORG = "international_org"
    PARLIAMENTARY_RECORD = "parliamentary_record"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceEntry(BaseModel):
    """A single evidence entry in the Ground Truth Database."""

    evidence_id: str = Field(..., pattern=r"^[A-Z]+-[A-Z]+-\d{3}$")
    domain: Domain
    topic: str
    subtopic: str | None = None
    statement: str
    source_name: str
    source_url: str | None = None
    source_date: date | None = None
    source_type: SourceType
    confidence: Confidence = Confidence.HIGH
    caveats: str | None = None
    statement_is: str | None = None
    source_description_is: str | None = None
    related_entries: list[str] = Field(default_factory=list)
    last_verified: date = Field(default_factory=date.today)

    @model_validator(mode="after")
    def _warn_generic_url(self) -> "EvidenceEntry":
        """Warn if source_url is missing or just a domain root."""
        if not self.source_url:
            warnings.warn(
                f"{self.evidence_id}: missing source_url", stacklevel=2
            )
        else:
            parsed = urlparse(self.source_url)
            if parsed.path in ("", "/") and not parsed.query:
                warnings.warn(
                    f"{self.evidence_id}: generic root URL '{self.source_url}'",
                    stacklevel=2,
                )
        return self


class SearchResult(BaseModel):
    """A search result with similarity score."""

    evidence_id: str
    domain: str
    topic: str
    subtopic: str | None
    statement: str
    source_name: str
    source_url: str | None
    source_date: date | None
    source_type: str
    confidence: str
    caveats: str | None
    similarity: float
    statement_is: str | None = None
