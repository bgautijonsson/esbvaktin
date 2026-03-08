"""Pydantic models for the Ground Truth Database."""

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Domain(str, Enum):
    LEGAL = "legal"
    ECONOMIC = "economic"
    POLITICAL = "political"
    PRECEDENT = "precedent"


class SourceType(str, Enum):
    OFFICIAL_STATISTICS = "official_statistics"
    LEGAL_TEXT = "legal_text"
    ACADEMIC_PAPER = "academic_paper"
    EXPERT_ANALYSIS = "expert_analysis"
    INTERNATIONAL_ORG = "international_org"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceEntry(BaseModel):
    """A single evidence entry in the Ground Truth Database."""

    evidence_id: str = Field(..., pattern=r"^[A-Z]+-[A-Z]+-\d{3}$")
    domain: Domain
    topic: str
    subtopic: Optional[str] = None
    statement: str
    source_name: str
    source_url: Optional[str] = None
    source_date: Optional[date] = None
    source_type: SourceType
    confidence: Confidence = Confidence.HIGH
    caveats: Optional[str] = None
    related_entries: list[str] = Field(default_factory=list)
    last_verified: date = Field(default_factory=date.today)


class SearchResult(BaseModel):
    """A search result with similarity score."""

    evidence_id: str
    domain: str
    topic: str
    subtopic: Optional[str]
    statement: str
    source_name: str
    source_url: Optional[str]
    source_date: Optional[date]
    source_type: str
    confidence: str
    caveats: Optional[str]
    similarity: float
