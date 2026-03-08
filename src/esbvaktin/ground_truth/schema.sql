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
    source_type TEXT NOT NULL,               -- official_statistics | legal_text | academic_paper | expert_analysis | international_org
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
