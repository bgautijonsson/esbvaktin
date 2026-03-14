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

# Icelandic display labels for each topic
TOPIC_LABELS_IS: dict[str, str] = {
    "fisheries": "Sjávarútvegur",
    "trade": "Viðskipti og verslun",
    "sovereignty": "Fullveldi",
    "eea_eu_law": "EES og löggjöf ESB",
    "agriculture": "Landbúnaður",
    "precedents": "Fordæmi annarra ríkja",
    "currency": "Gjaldmiðill og peningamál",
    "labour": "Vinnumarkaður",
    "housing": "Húsnæðismál",
    "polling": "Könnanir og þjóðarvilji",
    "party_positions": "Afstaða stjórnmálaflokka",
    "org_positions": "Afstaða stofnana og samtaka",
}


class Claim(BaseModel):
    """A factual claim extracted from an article."""

    claim_text: str = Field(..., description="The factual claim as stated")
    original_quote: str = Field(..., description="Exact quote from the article")
    category: str = Field(..., description="Topic category (e.g. fisheries, trade)")
    claim_type: ClaimType
    confidence: float = Field(..., ge=0, le=1, description="Extraction confidence")
    speaker_name: str | None = Field(
        None, description="Speaker who made the claim (panel shows / transcripts)"
    )


class EvidenceMatch(BaseModel):
    """A matched evidence entry from the Ground Truth DB."""

    evidence_id: str
    statement: str
    similarity: float
    source_name: str
    source_url: str | None = None
    caveats: str | None = None
    statement_is: str | None = None


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


class EntityType(StrEnum):
    INDIVIDUAL = "individual"
    PARTY = "party"
    INSTITUTION = "institution"
    UNION = "union"


class Stance(StrEnum):
    PRO_EU = "pro_eu"
    ANTI_EU = "anti_eu"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class Attribution(StrEnum):
    """How a speaker is connected to a claim."""

    ASSERTED = "asserted"  # Speaker directly states the claim as their own position
    QUOTED = "quoted"  # Speaker is directly quoted making the claim
    PARAPHRASED = "paraphrased"  # Article paraphrases the speaker's position
    MENTIONED = "mentioned"  # Speaker is referenced in context but didn't make the claim


class ClaimAttribution(BaseModel):
    """Links a speaker to a specific claim with attribution type."""

    claim_index: int = Field(..., description="0-based index into the claims list")
    attribution: Attribution = Field(
        default=Attribution.ASSERTED,
        description="How the speaker is connected to this claim",
    )


class Speaker(BaseModel):
    """A person, party, or organisation quoted or attributed in an article."""

    name: str = Field(..., description="Full name in Icelandic")
    type: EntityType
    role: str | None = Field(None, description="e.g. 'þingmaður', 'framkvæmdastjóri'")
    party: str | None = Field(None, description="Political party (for individuals)")
    stance: Stance = Field(default=Stance.NEUTRAL, description="EU membership stance")
    attributions: list[ClaimAttribution] = Field(
        default_factory=list,
        description="Claims attributed to this speaker, with attribution type",
    )
    # Legacy field — kept for backward compatibility with existing _entities.json
    claim_indices: list[int] = Field(
        default_factory=list,
        description="Deprecated: use attributions instead. Bare indices default to 'asserted'.",
    )

    def resolved_attributions(self) -> list[ClaimAttribution]:
        """Return attributions, falling back to claim_indices for legacy data.

        If `attributions` is populated, return it directly.
        Otherwise, convert bare `claim_indices` to attributions with type 'asserted'.
        """
        if self.attributions:
            return self.attributions
        return [
            ClaimAttribution(claim_index=idx, attribution=Attribution.ASSERTED)
            for idx in self.claim_indices
        ]

    def claim_index_set(self) -> set[int]:
        """Return all claim indices this speaker is linked to."""
        return {a.claim_index for a in self.resolved_attributions()}


class ArticleEntities(BaseModel):
    """Extracted entity/speaker data for an article."""

    article_author: Speaker | None = None
    speakers: list[Speaker] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    """Complete analysis report for an article."""

    article_title: str | None = None
    article_url: str | None = None
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
    capsule: str | None = Field(
        None,
        description="Short Icelandic editorial insight (2-3 sentences) for article cards",
    )
    report_text_is: str = Field(default="", description="Icelandic report (primary)")
    report_text_en: str = Field(default="", description="English report (optional)")
