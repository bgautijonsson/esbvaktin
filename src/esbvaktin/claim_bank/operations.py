"""Core database operations for the Claim Bank.

Provides semantic search, insertion, and update operations for
canonical claims stored in PostgreSQL with pgvector embeddings.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import TYPE_CHECKING

from .models import CanonicalClaim, ClaimBankMatch

if TYPE_CHECKING:
    import psycopg

# ── Schema ────────────────────────────────────────────────────────────

CLAIMS_SCHEMA = """
-- Canonical claims with pre-processed assessments
CREATE TABLE IF NOT EXISTS claims (
    id SERIAL PRIMARY KEY,
    claim_slug TEXT UNIQUE NOT NULL,
    canonical_text_is TEXT NOT NULL,
    canonical_text_en TEXT,
    category TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    epistemic_type TEXT NOT NULL DEFAULT 'factual',
    verdict TEXT NOT NULL,
    explanation_is TEXT NOT NULL,
    explanation_en TEXT,
    missing_context_is TEXT,
    supporting_evidence TEXT[] DEFAULT '{}',
    contradicting_evidence TEXT[] DEFAULT '{}',
    confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    embedding vector(1024),
    version INT DEFAULT 1,
    last_verified DATE NOT NULL DEFAULT CURRENT_DATE,
    published BOOLEAN DEFAULT TRUE,
    substantive BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_claims_slug ON claims(claim_slug);
CREATE INDEX IF NOT EXISTS idx_claims_category ON claims(category);
CREATE INDEX IF NOT EXISTS idx_claims_verdict ON claims(verdict);
CREATE INDEX IF NOT EXISTS idx_claims_published ON claims(published);

-- Track which articles reference which claims
CREATE TABLE IF NOT EXISTS article_claims (
    id SERIAL PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    claim_id INT NOT NULL REFERENCES claims(id),
    similarity FLOAT,
    original_claim_text TEXT,
    cache_hit BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(analysis_id, claim_id)
);
"""


def init_claims_schema(conn: psycopg.Connection | None = None) -> None:
    """Create the claims and article_claims tables."""
    from ..ground_truth.operations import get_connection

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    conn.execute(CLAIMS_SCHEMA)
    conn.commit()

    if close:
        conn.close()


# ── Slug generation ───────────────────────────────────────────────────

# Icelandic character mapping for URL-safe slugs
_ICELANDIC_MAP = str.maketrans(
    {
        "á": "a",
        "ð": "d",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ý": "y",
        "þ": "th",
        "æ": "ae",
        "ö": "o",
        "Á": "a",
        "Ð": "d",
        "É": "e",
        "Í": "i",
        "Ó": "o",
        "Ú": "u",
        "Ý": "y",
        "Þ": "th",
        "Æ": "ae",
        "Ö": "o",
    }
)


def generate_slug(text_is: str) -> str:
    """Convert Icelandic text to URL-friendly slug.

    Examples:
        >>> generate_slug("Sjávarútvegur — kvótakerfi ESB")
        'sjavarutvegur-kvotakerfi-esb'
        >>> generate_slug("30% samdráttur í afla")
        '30-percent-samdrattur-i-afla'
    """
    text = text_is.lower()
    # Replace % with 'percent' before character mapping
    text = text.replace("%", " percent ")
    # Map Icelandic characters
    text = text.translate(_ICELANDIC_MAP)
    # Normalise any remaining unicode
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    # Replace non-alphanumeric with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Collapse multiple hyphens, strip edges
    text = re.sub(r"-+", "-", text).strip("-")
    return text


# ── Search ────────────────────────────────────────────────────────────

_FRESHNESS_DAYS = 30


def search_claims(
    query: str,
    threshold: float = 0.70,
    top_k: int = 5,
    conn: psycopg.Connection | None = None,
) -> list[ClaimBankMatch]:
    """Semantic search against the claim bank.

    Returns claims above the similarity threshold, sorted by similarity
    descending. Each result includes an `is_fresh` flag indicating whether
    the claim's verdict has been verified within the last 30 days.
    """
    from ..ground_truth.operations import embed_text, get_connection

    query_embedding = embed_text(query)

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    rows = conn.execute(
        """
        SELECT id, claim_slug, canonical_text_is, verdict, epistemic_type,
               explanation_is, supporting_evidence, contradicting_evidence,
               missing_context_is, confidence, last_verified,
               1 - (embedding <=> %(embedding)s::vector) AS similarity
        FROM claims
        WHERE 1 - (embedding <=> %(embedding)s::vector) >= %(threshold)s
        ORDER BY embedding <=> %(embedding)s::vector
        LIMIT %(top_k)s
        """,
        {
            "embedding": query_embedding,
            "threshold": threshold,
            "top_k": top_k,
        },
    ).fetchall()

    columns = [
        "claim_id",
        "claim_slug",
        "canonical_text_is",
        "verdict",
        "epistemic_type",
        "explanation_is",
        "supporting_evidence",
        "contradicting_evidence",
        "missing_context_is",
        "confidence",
        "last_verified",
        "similarity",
    ]

    cutoff = date.today() - timedelta(days=_FRESHNESS_DAYS)
    results = []
    for row in rows:
        data = dict(zip(columns, row))
        data["is_fresh"] = data["last_verified"] >= cutoff
        results.append(ClaimBankMatch(**data))

    if close:
        conn.close()
    return results


# ── Insert ────────────────────────────────────────────────────────────


def add_claim(
    claim: CanonicalClaim,
    conn: psycopg.Connection | None = None,
) -> int:
    """Insert a canonical claim into the bank.

    Generates embedding from canonical_text_is. Returns the claim id.
    Uses upsert: if a claim with the same slug exists, update it and
    increment the version.
    """
    from ..ground_truth.operations import embed_text, get_connection

    embedding = embed_text(claim.canonical_text_is)

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    row = conn.execute(
        """
        INSERT INTO claims (
            claim_slug, canonical_text_is, canonical_text_en,
            category, claim_type, epistemic_type, verdict,
            explanation_is, explanation_en, missing_context_is,
            supporting_evidence, contradicting_evidence,
            confidence, embedding, last_verified, published
        ) VALUES (
            %(slug)s, %(text_is)s, %(text_en)s,
            %(category)s, %(claim_type)s, %(epistemic_type)s, %(verdict)s,
            %(explanation_is)s, %(explanation_en)s, %(missing_context_is)s,
            %(supporting)s, %(contradicting)s,
            %(confidence)s, %(embedding)s, %(last_verified)s, %(published)s
        ) ON CONFLICT (claim_slug) DO UPDATE SET
            canonical_text_is = EXCLUDED.canonical_text_is,
            canonical_text_en = EXCLUDED.canonical_text_en,
            epistemic_type = EXCLUDED.epistemic_type,
            verdict = EXCLUDED.verdict,
            explanation_is = EXCLUDED.explanation_is,
            explanation_en = EXCLUDED.explanation_en,
            missing_context_is = EXCLUDED.missing_context_is,
            supporting_evidence = EXCLUDED.supporting_evidence,
            contradicting_evidence = EXCLUDED.contradicting_evidence,
            confidence = EXCLUDED.confidence,
            embedding = EXCLUDED.embedding,
            last_verified = EXCLUDED.last_verified,
            version = claims.version + 1,
            updated_at = NOW()
        RETURNING id
        """,
        {
            "slug": claim.claim_slug,
            "text_is": claim.canonical_text_is,
            "text_en": claim.canonical_text_en,
            "category": claim.category,
            "claim_type": claim.claim_type,
            "epistemic_type": claim.epistemic_type,
            "verdict": claim.verdict,
            "explanation_is": claim.explanation_is,
            "explanation_en": claim.explanation_en,
            "missing_context_is": claim.missing_context_is,
            "supporting": claim.supporting_evidence,
            "contradicting": claim.contradicting_evidence,
            "confidence": claim.confidence,
            "embedding": embedding,
            "last_verified": claim.last_verified,
            "published": claim.published,
        },
    ).fetchone()
    conn.commit()

    claim_id = row[0]
    if close:
        conn.close()
    return claim_id


# ── Update ────────────────────────────────────────────────────────────


def update_claim_verdict(
    claim_id: int,
    *,
    verdict: str,
    explanation_is: str,
    supporting_evidence: list[str],
    contradicting_evidence: list[str],
    missing_context_is: str | None = None,
    confidence: float,
    conn: psycopg.Connection | None = None,
) -> None:
    """Update a claim's verdict and evidence after re-assessment.

    Increments version, updates last_verified to today.
    """
    from ..ground_truth.operations import get_connection

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    conn.execute(
        """
        UPDATE claims SET
            verdict = %(verdict)s,
            explanation_is = %(explanation_is)s,
            supporting_evidence = %(supporting)s,
            contradicting_evidence = %(contradicting)s,
            missing_context_is = %(missing_context_is)s,
            confidence = %(confidence)s,
            last_verified = CURRENT_DATE,
            version = version + 1,
            updated_at = NOW()
        WHERE id = %(claim_id)s
        """,
        {
            "claim_id": claim_id,
            "verdict": verdict,
            "explanation_is": explanation_is,
            "supporting": supporting_evidence,
            "contradicting": contradicting_evidence,
            "missing_context_is": missing_context_is,
            "confidence": confidence,
        },
    )
    conn.commit()

    if close:
        conn.close()


def update_claim_canonical(
    claim_id: int,
    *,
    canonical_text_is: str,
    claim_slug: str,
    verdict: str,
    explanation_is: str,
    supporting_evidence: list[str],
    contradicting_evidence: list[str],
    missing_context_is: str | None = None,
    confidence: float,
    conn: psycopg.Connection | None = None,
) -> None:
    """Update a claim's canonical text, slug, embedding, and verdict.

    Use when sighting drift correction changes the canonical text.
    Re-embeds the text so future semantic matches use the corrected vector.
    Increments version, updates last_verified to today.
    """
    from ..ground_truth.operations import embed_text, get_connection

    embedding = embed_text(canonical_text_is)

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    conn.execute(
        """
        UPDATE claims SET
            canonical_text_is = %(text_is)s,
            claim_slug = %(slug)s,
            embedding = %(embedding)s,
            verdict = %(verdict)s,
            explanation_is = %(explanation_is)s,
            supporting_evidence = %(supporting)s,
            contradicting_evidence = %(contradicting)s,
            missing_context_is = %(missing_context_is)s,
            confidence = %(confidence)s,
            last_verified = CURRENT_DATE,
            version = version + 1,
            updated_at = NOW()
        WHERE id = %(claim_id)s
        """,
        {
            "claim_id": claim_id,
            "text_is": canonical_text_is,
            "slug": claim_slug,
            "embedding": embedding,
            "verdict": verdict,
            "explanation_is": explanation_is,
            "supporting": supporting_evidence,
            "contradicting": contradicting_evidence,
            "missing_context_is": missing_context_is,
            "confidence": confidence,
        },
    )
    conn.commit()

    if close:
        conn.close()


# ── Article–claim reference tracking ─────────────────────────────────


def record_article_match(
    analysis_id: str,
    claim_id: int,
    similarity: float,
    original_claim_text: str,
    cache_hit: bool = False,
    conn: psycopg.Connection | None = None,
) -> None:
    """Record that an article analysis matched a claim bank entry."""
    from ..ground_truth.operations import get_connection

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    conn.execute(
        """
        INSERT INTO article_claims (analysis_id, claim_id, similarity, original_claim_text, cache_hit)
        VALUES (%(analysis_id)s, %(claim_id)s, %(similarity)s, %(text)s, %(cache_hit)s)
        ON CONFLICT (analysis_id, claim_id) DO NOTHING
        """,
        {
            "analysis_id": analysis_id,
            "claim_id": claim_id,
            "similarity": similarity,
            "text": original_claim_text,
            "cache_hit": cache_hit,
        },
    )
    conn.commit()

    if close:
        conn.close()


# ── Stats ─────────────────────────────────────────────────────────────


def get_claim_counts(
    conn: psycopg.Connection | None = None,
) -> dict[str, int]:
    """Get claim counts by verdict."""
    from ..ground_truth.operations import get_connection

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    rows = conn.execute(
        "SELECT verdict, COUNT(*) FROM claims GROUP BY verdict ORDER BY COUNT(*) DESC"
    ).fetchall()

    if close:
        conn.close()
    return dict(rows)


def get_total_claims(conn: psycopg.Connection | None = None) -> int:
    """Get total number of canonical claims."""
    from ..ground_truth.operations import get_connection

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    count = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]

    if close:
        conn.close()
    return count
