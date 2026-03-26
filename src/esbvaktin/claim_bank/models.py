"""Pydantic models for the Claim Bank."""

from datetime import date

from pydantic import BaseModel, Field, field_validator


class CanonicalClaim(BaseModel):
    """A canonical claim stored in the claim bank.

    Each canonical claim represents a single verifiable assertion that
    may appear (in various phrasings) across multiple articles.
    """

    claim_slug: str = Field(
        ...,
        pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$",
        description="URL-safe slug for permalink (e.g. 'sjavarutvegur-kvotakerfi')",
    )
    canonical_text_is: str = Field(..., description="Icelandic canonical claim text (primary)")
    canonical_text_en: str | None = Field(default=None, description="English equivalent (optional)")
    category: str = Field(..., description="Topic (fisheries, trade, etc.)")
    claim_type: str = Field(
        ..., description="statistic | legal_assertion | comparison | forecast | opinion"
    )
    epistemic_type: str = Field(
        default="factual",
        description="factual | hearsay | counterfactual | prediction",
    )

    # Pre-computed verdict
    verdict: str = Field(
        ...,
        description="supported | partially_supported | unsupported | misleading | unverifiable",
    )
    explanation_is: str = Field(..., description="2-3 sentence Icelandic explanation")
    explanation_en: str | None = Field(default=None, description="English explanation (optional)")
    missing_context_is: str | None = Field(default=None, description="Icelandic context/caveats")

    # Evidence references
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)

    # Metadata
    confidence: float = Field(..., ge=0, le=1)
    last_verified: date = Field(default_factory=date.today)
    published: bool = True
    substantive: bool = True


class ClaimBankMatch(BaseModel):
    """Result of semantic matching against the claim bank."""

    claim_id: int
    claim_slug: str
    canonical_text_is: str
    similarity: float = Field(..., ge=0, le=1)
    verdict: str
    explanation_is: str
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    missing_context_is: str | None = None
    confidence: float = Field(..., ge=0, le=1)
    last_verified: date
    is_fresh: bool = Field(..., description="True if last_verified < 30 days ago")

    @field_validator("supporting_evidence", "contradicting_evidence", mode="before")
    @classmethod
    def _coerce_none_to_list(cls, v: list[str] | None) -> list[str]:
        return v if v is not None else []
