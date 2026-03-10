"""Pydantic models for the Article Analysis Pipeline."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class ClaimType(StrEnum):
    STATISTIC = "statistic"
    LEGAL_ASSERTION = "legal_assertion"
    COMPARISON = "comparison"
    PREDICTION = "prediction"
    OPINION = "opinion"


class Verdict(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    MISLEADING = "misleading"
    UNVERIFIABLE = "unverifiable"


class FramingAssessment(StrEnum):
    BALANCED = "balanced"
    LEANS_PRO_EU = "leans_pro_eu"
    LEANS_ANTI_EU = "leans_anti_eu"
    STRONGLY_PRO_EU = "strongly_pro_eu"
    STRONGLY_ANTI_EU = "strongly_anti_eu"
    NEUTRAL_BUT_INCOMPLETE = "neutral_but_incomplete"


# Known topics matching ground truth database
KNOWN_TOPICS = {
    "fisheries",
    "trade",
    "sovereignty",
    "eea_eu_law",
    "agriculture",
    "precedents",
    "currency",
    "labour",
    "housing",
    "polling",
    "party_positions",
    "org_positions",
}


class Claim(BaseModel):
    """A factual claim extracted from an article."""

    claim_text: str = Field(..., description="The factual claim as stated")
    original_quote: str = Field(..., description="Exact quote from the article")
    category: str = Field(..., description="Topic category (e.g. fisheries, trade)")
    claim_type: ClaimType
    confidence: float = Field(..., ge=0, le=1, description="Extraction confidence")


class EvidenceMatch(BaseModel):
    """A matched evidence entry from the Ground Truth DB."""

    evidence_id: str
    statement: str
    similarity: float
    source_name: str
    source_url: str | None = None
    caveats: str | None = None


class ClaimWithEvidence(BaseModel):
    """A claim paired with its top evidence matches."""

    claim: Claim
    evidence: list[EvidenceMatch]


class ClaimAssessment(BaseModel):
    """Assessment of a single claim against evidence."""

    claim: Claim
    verdict: Verdict
    explanation: str = Field(..., description="2-3 sentence explanation")
    supporting_evidence: list[str] = Field(
        default_factory=list, description="Evidence IDs that support"
    )
    contradicting_evidence: list[str] = Field(
        default_factory=list, description="Evidence IDs that contradict"
    )
    missing_context: str | None = None
    confidence: float = Field(..., ge=0, le=1)


class Omission(BaseModel):
    """A significant omission from the article."""

    topic: str
    description: str
    relevant_evidence: list[str] = Field(
        default_factory=list, description="Evidence IDs"
    )


class OmissionAnalysis(BaseModel):
    """Analysis of what the article leaves out."""

    omissions: list[Omission] = Field(default_factory=list)
    framing_assessment: FramingAssessment
    overall_completeness: float = Field(
        ..., ge=0, le=1, description="How complete the article's coverage is"
    )


class AnalysisReport(BaseModel):
    """Complete analysis report for an article."""

    article_title: str | None = None
    article_source: str | None = None
    article_date: date | None = None
    analysis_date: date = Field(default_factory=date.today)
    language: str = Field(default="is", description="Primary pipeline language")
    summary: str
    claims: list[ClaimAssessment]
    omissions: OmissionAnalysis
    evidence_used: list[str] = Field(
        default_factory=list, description="All evidence IDs referenced"
    )
    report_text_is: str = Field(default="", description="Icelandic report (primary)")
    report_text_en: str = Field(default="", description="English report (optional)")
