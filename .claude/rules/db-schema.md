---
paths:
  - "src/esbvaktin/ground_truth/**"
  - "src/esbvaktin/claim_bank/**"
  - "src/esbvaktin/speeches/**"
  - "scripts/export_*"
  - "scripts/seed_*"
  - "scripts/reassess_*"
  - "scripts/audit_*"
  - "scripts/register_*"
  - "scripts/migrate_*"
  - "src/esbvaktin/entity_registry/**"
  - "scripts/check_evidence_*"
  - "scripts/generate_overview*"
  - "scripts/pipeline/retrieve_evidence.py"
  - "scripts/pipeline/assemble_report.py"
---

# DB Schema Quick Reference

| Table | Key Columns | Notes |
|---|---|---|
| `evidence` | `evidence_id` (PK text), `domain`, `topic`, `statement`, `statement_is`, `source_name`, `source_url`, `source_type`, `confidence` (high/medium/low text), `caveats`, `caveats_is`, `related_entries TEXT[]`, `last_verified`, `source_excerpt`, `source_url_status`, `source_url_checked`, `embedding vector(1024)` | `related_entries` has no FK integrity. `source_excerpt` = content fingerprint for link health checks. |
| `claims` | `claim_slug` (unique), `canonical_text_is`, `category`, `verdict`, `published`, `substantive`, `confidence FLOAT`, `supporting_evidence TEXT[]`, `contradicting_evidence TEXT[]`, `embedding vector(1024)`, `version`, `last_verified` | Use `evidence_id = ANY(supporting_evidence)` for cross-join |
| `claim_sightings` | `claim_id` FK, `source_url`, `source_domain`, `source_date`, `source_type`, `speaker_name`, `speaker_stance`, `speech_id`, `speech_verdict` | `speaker_name` may be NULL for older althingi sightings |
| `article_claims` | `analysis_id`, `claim_id`, `similarity`, `cache_hit` | Populated but rarely queried — use `claim_sightings` for linkage |
| `entities` | `slug` (unique), `canonical_name`, `entity_type`, `subtype`, `stance`, `stance_score REAL`, `stance_confidence REAL`, `party_slug`, `althingi_id INT`, `aliases TEXT[]`, `roles JSONB`, `verification_status` (auto_generated/needs_review/confirmed) | Canonical entity registry. `aliases` has GIN index for containment queries. |
| `entity_observations` | `entity_id` FK, `article_slug`, `article_url`, `observed_name`, `observed_stance`, `observed_role`, `observed_party`, `observed_type`, `attribution_types TEXT[]`, `claim_indices INT[]`, `match_confidence REAL`, `match_method`, `disagreements JSONB` | Per-article entity extractions linked to registry. `entity_id = NULL` means unmatched. |

**Analytical views** (all read from published claims):
- `verdict_weekly_trend` — cumulative verdict distribution over time
- `evidence_utilisation` — citation counts + days since verification
- `stale_evidence` — entries not verified in 90+ days
- `claim_velocity` — new claims per week per topic
- `balance_audit` — verdict distribution by `speaker_stance`
- `outlet_verdicts` — verdict distribution by `source_domain`
- `claim_frequency` — sighting count per claim

**Domain extraction:** `source_domain` is populated on INSERT via `esbvaktin.utils.domain.extract_domain()`. Resolves podcast CDN aliases (acast→RÚV, spotify→mbl). The canonical alias dict is in `src/esbvaktin/utils/domain.py`.
