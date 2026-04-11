---
description: "Full command reference for pipeline scripts, inbox management, export, evidence, and development"
globs:
  - "scripts/**"
  - "R/**"
  - ".claude/skills/**"
---

# Commands Reference

## Skills (Slash Commands)

```
/find-articles             # Discover new articles (no auto-analysis)
/find-articles 3           # Scan last 3 days
/find-articles backlog     # Check inbox backlog only
/process-articles          # Batch-analyse top 3 pending articles
/process-articles 5        # Batch-analyse top 5
/process-articles triage   # Show sorted triage table
/analyse-article <url>     # Full pipeline for single article
/process-inbox             # Lightweight claim harvesting (no full assessment)
/health                    # Unified project health dashboard
/health db                 # Database section only
/db                        # Quick DB summary (verdicts, counts)
/db stale evidence         # Query stale evidence
/db "SELECT ..."           # Run raw SQL (read-only)
/evidence-hunt             # Find and draft evidence for gaps
/evidence-hunt fisheries   # Research specific topic
/evidence-hunt monthly     # Refresh high-decay topics (polling, party_positions, org_positions, currency)
/reassess                  # Full reassessment cycle (unverifiable + partial)
/reassess overconfident    # Reassess audit-flagged claims only
/reassess denominator      # Reassess scope-word claims (denominator confusion audit)
/reassess evidence ID1 ID2 ...  # Reassess all claims citing these evidence entries
/reassess claims 123 456 ...    # Reassess specific claims by ID
/entity-review             # Interactive browser-based entity review
/entity-review status      # Entity registry queue status
/tidy                      # Full codebase quality audit
/tidy lint                 # Ruff lint only
/weekly-review              # Generate weekly overview + editorial (checks inbox first)
/weekly-review 2026-W12    # Specific week
/weekly-review last        # Previous week
/link-check                # Check evidence source URLs for link rot + content drift
/link-check populate       # Auto-populate source excerpts (content fingerprints)
/link-check report         # Show link health report
/ci                        # Latest CI run status
/ci list                   # Recent runs (last 10)
/ci failures               # Show only failed runs
/ci logs <run-id>          # Download and show failure logs
```

## Key Commands

```bash
# Article inbox
uv run python scripts/manage_inbox.py status              # Backlog summary
uv run python scripts/manage_inbox.py triage               # Sorted triage table for processing decisions
uv run python scripts/manage_inbox.py list                 # Pending articles
uv run python scripts/manage_inbox.py list --priority high # High priority only
uv run python scripts/manage_inbox.py next --high-only     # Next articles ready for analysis
uv run python scripts/manage_inbox.py next --limit 10      # Next N articles (HIGH + MEDIUM)
uv run python scripts/manage_inbox.py add-batch FILE.json  # Batch import from scan
uv run python scripts/manage_inbox.py queue ID [ID ...]    # Queue for analysis
uv run python scripts/manage_inbox.py reject ID [ID ...]   # Reject + add to rejected_urls.txt
uv run python scripts/manage_inbox.py skip ID [ID ...]     # Skip (not worth it)
uv run python scripts/manage_inbox.py prune --days 30      # Clean old entries

# Development
uv run --extra dev python -m pytest              # Run all tests
uv run --extra dev python -m pytest tests/test_models.py  # Single test file
uv run --extra dev python -m pytest -k "test_name"        # Single test by name
uv run --extra dev ruff check src/ scripts/      # Lint
uv run --extra dev ruff check --fix src/ scripts/  # Lint with auto-fix

# Export pipeline (all 7 steps with validation)
./scripts/run_export.sh --site-dir ~/esbvaktin-site   # Run full pipeline
# Or run individual steps:
uv run python scripts/export_entities.py --site-dir ~/esbvaktin-site  # 1. Export entities
uv run python scripts/export_evidence.py --site-dir ~/esbvaktin-site  # 2. Export evidence for /heimildir/
uv run python scripts/export_topics.py --site-dir ~/esbvaktin-site    # 3. Export topics (per-topic aggregations)
uv run python scripts/export_claims.py --site-dir ~/esbvaktin-site    # 4. Export claims (tracker + homepage)
uv run python scripts/prepare_site.py --site-dir ~/esbvaktin-site     # 5. Prepare site data (overlays DB verdicts)
uv run python scripts/prepare_speeches.py --site-dir ~/esbvaktin-site # 6. Export Alþingi debate data
uv run python scripts/export_overviews.py --site-dir ~/esbvaktin-site # 7. Export weekly overviews

# Entity registry
uv run python scripts/migrate_entities.py --status     # Registry status (counts, verification breakdown)
uv run python scripts/migrate_entities.py              # Run big-bang migration
uv run python scripts/migrate_entities.py --report     # Show migration report (duplicates, conflicts)
uv run python scripts/migrate_entities.py --force      # Re-run migration (clears existing data)

# Database backup (daily via launchd, syncs to iCloud)
./scripts/backup_db.sh            # Manual backup
./scripts/backup_db.sh --status   # Show existing backups
uv run python scripts/export_topics.py --status        # Show topic distribution
uv run python scripts/generate_overview.py --week 2026-W11  # Generate weekly overview data (checks inbox first)
uv run python scripts/generate_overview.py --week 2026-W11 --force  # Skip inbox gap warning
uv run python scripts/generate_overview.py --status         # Show overview coverage
uv run python scripts/prepare_overview_context.py 2026-W11  # Prepare editorial context (Icelandic)
uv run python scripts/correct_icelandic.py check-editorial data/overviews/2026-W11/editorial.md --fix  # Post-process editorial
uv run python scripts/validate_editorial.py data/overviews/2026-W11/editorial.md  # Validate against claim DB
uv run python scripts/export_overviews.py --status         # Show overview export coverage
uv run python scripts/export_evidence.py --status        # Show evidence DB summary
uv run python scripts/generate_evidence_is.py prepare     # Prepare IS summary batches (12 batches x 30)
uv run python scripts/generate_evidence_is.py write       # Parse subagent output -> update DB
uv run python scripts/generate_evidence_is.py status      # Show IS coverage
uv run python scripts/improve_evidence_is.py status              # Show IS quality (caveats, proofreading)
uv run python scripts/improve_evidence_is.py translate-caveats   # Translate EN caveats -> IS via Malstadur
uv run python scripts/improve_evidence_is.py correct             # Grammar-correct IS fields via Malstadur
uv run python scripts/improve_evidence_is.py correct --dry-run   # Preview without API calls
# Note: `correct` may need 2-3 runs to converge (corrections change text hash -> re-eligible)
uv run python scripts/seed_evidence.py status          # Show DB summary
uv run python scripts/seed_evidence.py insert data/seeds/  # Seed all JSON files

# Monthly evidence refresh (first Monday of month -- polling, party_positions, org_positions, currency)
# These topics decay fastest; schedule via /evidence-hunt monthly
uv run python scripts/curate_speech_evidence.py list        # Find high-value Althingi speeches for evidence curation
uv run python scripts/fact_check_speeches.py select --limit 5  # Rank speeches for fact-checking
uv run python scripts/fact_check_speeches.py run <speech_id>   # Fact-check a single speech (run outside Claude Code session)
uv run python scripts/fact_check_speeches.py status            # Show fact-check progress
uv run python scripts/reassess_claims.py prepare           # Prepare reassessment batches (auto-cleans stale output)
uv run python scripts/reassess_claims.py prepare --only overconfident --limit 30  # Verdict audit candidates
uv run python scripts/reassess_claims.py prepare --only denominator   # Scope-word claims (denominator confusion)
uv run python scripts/reassess_claims.py prepare --evidence ID1 ID2  # Claims citing these evidence entries
uv run python scripts/reassess_claims.py prepare --claims 123 456    # Specific claims by ID
uv run python scripts/reassess_claims.py update            # Apply subagent reassessments to DB
uv run python scripts/reassess_claims.py status            # Show verdict distribution
uv run python scripts/audit_claims.py report               # Full claim verdict audit (4 patterns)
uv run python scripts/audit_claims.py candidates           # Priority reassessment list
uv run python scripts/audit_claims.py status               # Quick audit summary
uv run python scripts/publish_claims.py status             # Claim publishing summary (should show 0 eligible)
uv run python scripts/publish_claims.py eligible           # Show unpublished claims eligible for publishing
uv run python scripts/publish_claims.py backfill           # One-time: publish all eligible unpublished claims
uv run python scripts/publish_claims.py unpublish <id>     # Manually suppress a published claim
uv run python scripts/backfill_epistemic_type.py status    # Epistemic type distribution
uv run python scripts/backfill_epistemic_type.py classify  # Classify claims (heuristic, dry run)
uv run python scripts/backfill_epistemic_type.py classify --apply  # Apply classification
uv run python scripts/backfill_epistemic_type.py correct --apply   # Fix hearsay verdicts
uv run python scripts/register_article_sightings.py        # Batch-register all unregistered reports into DB sightings
uv run python scripts/build_article_registry.py --status  # Show processed article registry
uv run python scripts/check_duplicate.py --url URL        # Check if article already processed
uv run python scripts/check_evidence_urls.py status        # Link health summary
uv run python scripts/check_evidence_urls.py check         # Check all evidence URLs (3-tier)
uv run python scripts/check_evidence_urls.py populate      # Auto-populate source excerpts
uv run python scripts/check_evidence_urls.py report        # Detailed link health report
docker compose up -d       # Start PostgreSQL
Rscript R/02_eurostat.R    # Fetch Eurostat data (example; scripts 01-07)
```
