CREATE EXTENSION IF NOT EXISTS vector;

-- Core evidence table
CREATE TABLE IF NOT EXISTS evidence (
    id SERIAL PRIMARY KEY,
    evidence_id TEXT UNIQUE NOT NULL,       -- e.g. "FISH-DATA-001"
    domain TEXT NOT NULL,                    -- legal | economic | political | precedent
    topic TEXT NOT NULL,                     -- e.g. "fisheries", "trade", "sovereignty"
    subtopic TEXT,                           -- e.g. "quota_allocation", "cfp_rules"
    statement TEXT NOT NULL,                 -- the factual statement
    source_name TEXT NOT NULL,               -- e.g. "Fiskistofa — Aflaheimildir 2025"
    source_url TEXT,
    source_date DATE,
    source_type TEXT NOT NULL,               -- official_statistics | legal_text | academic_paper | expert_analysis | international_org | parliamentary_record
    confidence TEXT NOT NULL DEFAULT 'high', -- high | medium | low
    caveats TEXT,                            -- important qualifications
    related_entries TEXT[],                  -- array of evidence_ids
    last_verified DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- pgvector embedding for semantic search
    embedding vector(1024)                   -- 1024 for BAAI/bge-m3 (local, multilingual)
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_evidence_domain ON evidence(domain);
CREATE INDEX IF NOT EXISTS idx_evidence_topic ON evidence(topic);
CREATE INDEX IF NOT EXISTS idx_evidence_evidence_id ON evidence(evidence_id);

-- Vector similarity index (ivfflat).
-- Rebuild after large batch inserts: DROP INDEX idx_evidence_embedding; then re-CREATE.
-- lists = sqrt(n): 20 for ~400 rows, increase to 30 at ~900 rows.
CREATE INDEX IF NOT EXISTS idx_evidence_embedding ON evidence
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);

-- Full-text search (Icelandic isn't in pg's built-in configs, so use 'simple')
CREATE INDEX IF NOT EXISTS idx_evidence_fts ON evidence
    USING gin(to_tsvector('simple', statement || ' ' || COALESCE(caveats, '')));

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS evidence_updated_at ON evidence;
CREATE TRIGGER evidence_updated_at
    BEFORE UPDATE ON evidence
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- ═══════════════════════════════════════════════════════════════════════
-- Migration: Icelandic summary fields for /heimildir/ pages
-- ═══════════════════════════════════════════════════════════════════════

ALTER TABLE evidence ADD COLUMN IF NOT EXISTS statement_is TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS source_description_is TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS caveats_is TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS is_proofread_hash TEXT;


-- ═══════════════════════════════════════════════════════════════════════
-- Migration: source link health tracking
-- ═══════════════════════════════════════════════════════════════════════

ALTER TABLE evidence ADD COLUMN IF NOT EXISTS source_excerpt TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS source_url_status TEXT;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS source_url_checked DATE;


-- ═══════════════════════════════════════════════════════════════════════
-- Claim Bank: canonical claims with pre-processed assessments
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS claims (
    id SERIAL PRIMARY KEY,
    claim_slug TEXT UNIQUE NOT NULL,            -- URL-safe slug for permalink
    canonical_text_is TEXT NOT NULL,            -- Icelandic canonical text (primary)
    canonical_text_en TEXT,                     -- English equivalent (optional)
    category TEXT NOT NULL,                     -- topic (fisheries, trade, etc.)
    claim_type TEXT NOT NULL,                   -- statistic | legal_assertion | comparison | prediction | opinion
    verdict TEXT NOT NULL,                      -- supported | partially_supported | unsupported | misleading | unverifiable
    explanation_is TEXT NOT NULL,               -- Icelandic explanation
    explanation_en TEXT,                        -- English explanation (optional)
    missing_context_is TEXT,                    -- Icelandic context/caveats
    supporting_evidence TEXT[] DEFAULT '{}',    -- evidence IDs that support
    contradicting_evidence TEXT[] DEFAULT '{}', -- evidence IDs that contradict
    confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    embedding vector(1024),                    -- BAAI/bge-m3 for semantic matching
    version INT DEFAULT 1,                     -- incremented on verdict updates
    last_verified DATE NOT NULL DEFAULT CURRENT_DATE,
    published BOOLEAN DEFAULT FALSE,           -- visible on esbvaktin.is
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_claims_slug ON claims(claim_slug);
CREATE INDEX IF NOT EXISTS idx_claims_category ON claims(category);
CREATE INDEX IF NOT EXISTS idx_claims_verdict ON claims(verdict);
CREATE INDEX IF NOT EXISTS idx_claims_published ON claims(published);

-- Vector similarity index for claim bank matching.
-- lists = sqrt(n): 31 for ~961 rows. Rebuild after large batch inserts.
CREATE INDEX IF NOT EXISTS idx_claims_embedding ON claims
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 31);

DROP TRIGGER IF EXISTS claims_updated_at ON claims;
CREATE TRIGGER claims_updated_at
    BEFORE UPDATE ON claims
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Track which articles reference which canonical claims
CREATE TABLE IF NOT EXISTS article_claims (
    id SERIAL PRIMARY KEY,
    analysis_id TEXT NOT NULL,                  -- e.g. "20260309_123421"
    claim_id INT NOT NULL REFERENCES claims(id),
    similarity FLOAT,                          -- how close was the match
    original_claim_text TEXT,                   -- original extraction for comparison
    cache_hit BOOLEAN DEFAULT FALSE,           -- was the bank entry reused?
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(analysis_id, claim_id)
);


-- ═══════════════════════════════════════════════════════════════════════
-- Claim Sightings: track where claims appear in public discourse
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS claim_sightings (
    id SERIAL PRIMARY KEY,
    claim_id INT NOT NULL REFERENCES claims(id),
    source_url TEXT NOT NULL,                   -- article URL
    source_title TEXT,                          -- article title (extracted)
    source_date DATE,                           -- publication date if available
    source_type TEXT,                           -- news | opinion | althingi | interview | panel_show | other
    original_text TEXT,                         -- the claim as it appeared in this article
    similarity FLOAT,                           -- cosine similarity to canonical claim
    speech_verdict TEXT,                        -- verdict specific to this speech/panel occurrence
    speech_id TEXT,                             -- althingi.db speech_id (for source_type='althingi')
    speaker_name TEXT,                          -- who said it (panel_show, althingi)
    extracted_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(claim_id, source_url)                -- one sighting per claim per article
);

CREATE INDEX IF NOT EXISTS idx_sightings_claim ON claim_sightings(claim_id);
CREATE INDEX IF NOT EXISTS idx_sightings_date ON claim_sightings(source_date);
CREATE INDEX IF NOT EXISTS idx_sightings_url ON claim_sightings(source_url);
CREATE INDEX IF NOT EXISTS idx_sightings_speech_id ON claim_sightings(speech_id);

-- ═══════════════════════════════════════════════════════════════════════
-- Migration: substantive flag for credibility weighting
-- ═══════════════════════════════════════════════════════════════════════

ALTER TABLE claims ADD COLUMN IF NOT EXISTS substantive BOOLEAN DEFAULT TRUE;


-- ═══════════════════════════════════════════════════════════════════════
-- Migration: source_domain + speaker_stance for analytics
-- ═══════════════════════════════════════════════════════════════════════

ALTER TABLE claim_sightings ADD COLUMN IF NOT EXISTS source_domain TEXT;
ALTER TABLE claim_sightings ADD COLUMN IF NOT EXISTS speaker_stance TEXT;

CREATE INDEX IF NOT EXISTS idx_sightings_domain ON claim_sightings(source_domain);
CREATE INDEX IF NOT EXISTS idx_sightings_stance ON claim_sightings(speaker_stance);


-- ═══════════════════════════════════════════════════════════════════════
-- Views: analytical queries for editorial workflow
-- ═══════════════════════════════════════════════════════════════════════

-- Claim frequency for prioritisation
CREATE OR REPLACE VIEW claim_frequency AS
SELECT
    c.id AS claim_id,
    c.claim_slug,
    c.canonical_text_is,
    c.category,
    c.verdict,
    c.published,
    COUNT(s.id) AS sighting_count,
    MAX(s.source_date) AS last_seen,
    MIN(s.source_date) AS first_seen
FROM claims c
LEFT JOIN claim_sightings s ON c.id = s.claim_id
GROUP BY c.id, c.claim_slug, c.canonical_text_is, c.category, c.verdict, c.published
ORDER BY sighting_count DESC;

-- Verdict trend: cumulative weekly verdict distribution
CREATE OR REPLACE VIEW verdict_weekly_trend AS
SELECT
    week, verdict, new_claims,
    SUM(new_claims) OVER (PARTITION BY verdict ORDER BY week) AS cumulative
FROM (
    SELECT
        DATE_TRUNC('week', created_at)::date AS week,
        verdict,
        COUNT(*) AS new_claims
    FROM claims
    WHERE published = TRUE
    GROUP BY DATE_TRUNC('week', created_at)::date, verdict
) sub
ORDER BY week, verdict;

-- Evidence utilisation: citation counts + staleness
CREATE OR REPLACE VIEW evidence_utilisation AS
SELECT *, supporting_count + contradicting_count AS total_citations
FROM (
    SELECT
        e.evidence_id,
        e.topic,
        e.source_name,
        e.confidence,
        e.last_verified,
        (CURRENT_DATE - e.last_verified) AS days_since_verified,
        (SELECT COUNT(*) FROM claims c
         WHERE e.evidence_id = ANY(c.supporting_evidence) AND c.published = TRUE
        ) AS supporting_count,
        (SELECT COUNT(*) FROM claims c
         WHERE e.evidence_id = ANY(c.contradicting_evidence) AND c.published = TRUE
        ) AS contradicting_count
    FROM evidence e
) sub
ORDER BY total_citations DESC;

-- Stale evidence: entries not verified in 90+ days
CREATE OR REPLACE VIEW stale_evidence AS
SELECT evidence_id, topic, source_name, last_verified,
       (CURRENT_DATE - last_verified) AS days_stale
FROM evidence
WHERE last_verified < CURRENT_DATE - INTERVAL '90 days'
ORDER BY days_stale DESC;

-- Claim velocity: weekly new published claims per topic
CREATE OR REPLACE VIEW claim_velocity AS
SELECT
    DATE_TRUNC('week', created_at)::date AS week,
    category,
    COUNT(*) AS new_claims
FROM claims
WHERE published = TRUE
GROUP BY DATE_TRUNC('week', created_at)::date, category
ORDER BY week, category;

-- Balance audit: verdict distribution by speaker stance
CREATE OR REPLACE VIEW balance_audit AS
SELECT
    speaker_stance,
    c.verdict,
    COUNT(*) AS n,
    ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY speaker_stance), 0), 1) AS pct
FROM claim_sightings s
JOIN claims c ON c.id = s.claim_id
WHERE c.published = TRUE AND s.speaker_stance IS NOT NULL
GROUP BY s.speaker_stance, c.verdict
ORDER BY s.speaker_stance, c.verdict;

-- Per-outlet verdict breakdown
CREATE OR REPLACE VIEW outlet_verdicts AS
SELECT
    s.source_domain,
    c.verdict,
    COUNT(*) AS n,
    ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY s.source_domain), 0), 1) AS pct
FROM claim_sightings s
JOIN claims c ON c.id = s.claim_id
WHERE c.published = TRUE AND s.source_domain IS NOT NULL
GROUP BY s.source_domain, c.verdict
ORDER BY s.source_domain, c.verdict;
