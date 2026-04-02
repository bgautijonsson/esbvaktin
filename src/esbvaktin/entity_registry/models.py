"""Pydantic models for the canonical entity registry."""

from enum import StrEnum

from pydantic import BaseModel, Field


class VerificationStatus(StrEnum):
    AUTO_GENERATED = "auto_generated"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"


class MatchMethod(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    LEMMA = "lemma"
    FUZZY = "fuzzy"
    MANUAL = "manual"


class RoleEntry(BaseModel):
    """A role held by an entity over a time period."""

    role: str
    from_date: str | None = None
    to_date: str | None = None


class Entity(BaseModel):
    """Canonical entity in the registry."""

    id: int | None = None
    slug: str
    canonical_name: str
    entity_type: str = Field(..., pattern=r"^(individual|party|institution|union)$")
    subtype: str | None = Field(None, pattern=r"^(politician|media)$")
    stance: str | None = Field(None, pattern=r"^(pro_eu|anti_eu|mixed|neutral)$")
    stance_score: float | None = Field(None, ge=-1.0, le=1.0)
    stance_confidence: float | None = Field(None, ge=0.0, le=1.0)
    party_slug: str | None = None
    althingi_id: int | None = None
    aliases: list[str] = Field(default_factory=list)
    roles: list[RoleEntry] = Field(default_factory=list)
    notes: str | None = None
    verification_status: VerificationStatus = VerificationStatus.AUTO_GENERATED
    is_icelandic: bool = True
    locked_fields: list[str] = Field(default_factory=list)


class EntityObservation(BaseModel):
    """A per-article entity extraction linked to the registry."""

    id: int | None = None
    entity_id: int | None = None
    article_slug: str
    article_url: str | None = None
    observed_name: str
    observed_stance: str | None = None
    observed_role: str | None = None
    observed_party: str | None = None
    observed_type: str | None = None
    attribution_types: list[str] = Field(default_factory=list)
    claim_indices: list[int] = Field(default_factory=list)
    match_confidence: float | None = None
    match_method: MatchMethod | None = None
    disagreements: dict[str, bool] | None = None
    dismissed: bool = False
