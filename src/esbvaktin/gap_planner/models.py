"""Pydantic models for the Verification Gap Planner."""

from datetime import date
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


class GapCategory(StrEnum):
    """Why a claim is unverifiable."""

    MISSING_DATA = "missing_data"          # Data source exists but not in DB
    SPECULATIVE = "speculative"            # Inherently unverifiable (predictions)
    RECENT_EVENT = "recent_event"          # References recent events not yet documented
    SOURCE_NEEDED = "source_needed"        # Claim likely true, just needs sourcing
    CONTRADICTORY = "contradictory"        # Conflicting evidence, needs resolution


class ResearchType(StrEnum):
    """Type of research needed to resolve a gap."""

    DATA_SEARCH = "data_search"            # Find and import statistical data
    DOCUMENT_REVIEW = "document_review"    # Read and extract from legal/policy docs
    EXPERT_CONTACT = "expert_contact"      # Requires reaching out to domain experts
    LEGISLATIVE_CHECK = "legislative_check" # Check Althingi or EU parliamentary records


class EvidenceGap(BaseModel):
    """An unverifiable claim that needs research."""

    claim_index: int = Field(..., description="Index in the original claims list")
    claim_text: str
    original_quote: str = ""
    category: str = Field(..., description="Topic category (fisheries, trade, etc.)")
    explanation: str = Field(..., description="Why this claim is unverifiable")
    missing_context: Optional[str] = None
    gap_category: GapCategory = Field(
        ..., description="Classification of why it's unverifiable"
    )
    evidence_ids_consulted: list[str] = Field(
        default_factory=list,
        description="Evidence IDs that were checked but insufficient",
    )


class ResearchTask(BaseModel):
    """A targeted task to research and fill an evidence gap."""

    title: str
    description: str
    gap: EvidenceGap
    research_type: ResearchType
    priority: str = Field(
        ..., description="high | medium | low"
    )
    suggested_sources: list[str] = Field(default_factory=list)
    estimated_effort_hours: float = 0
    notes: Optional[str] = None


class GapAnalysisReport(BaseModel):
    """Summary of gaps and research plan from one analysis."""

    analysis_id: str
    analysis_date: date = Field(default_factory=date.today)
    total_claims: int
    total_unverifiable: int
    gaps_by_category: dict[str, int] = Field(default_factory=dict)
    research_tasks: list[ResearchTask] = Field(default_factory=list)
