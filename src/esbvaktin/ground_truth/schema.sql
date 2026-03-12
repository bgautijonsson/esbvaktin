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

-- Vector similarity index (ivfflat with ~20 lists for <1000 entries)
-- NOTE: ivfflat requires rows to exist before building; create after seeding
-- For small datasets, exact search (no index) is fine — add this later:
-- CREATE INDEX idx_evidence_embedding ON evidence
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);

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


-- View: claim frequency for prioritisation
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
