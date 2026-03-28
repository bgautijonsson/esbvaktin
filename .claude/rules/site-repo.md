---
paths:
  - "scripts/export_*"
  - "scripts/prepare_site.py"
  - "scripts/prepare_speeches.py"
  - "scripts/run_export.sh"
---

# Site Repo Reference

Sibling repo `~/esbvaktin-site/` (public, `bgautijonsson/esbvaktin-site`). 11ty v3 static site. Has its own `CLAUDE.md` with full site conventions.
- `_data/` — 11ty build data (entities.json, reports/*.json, entity-details/*.json, evidence-details/*.json, debates/*.json)
- `assets/data/` — client-side JS data (entities.json, reports.json, claims.json, evidence.json, sources.json, debates.json) — **must be kept in sync** (export scripts write to both)
- `eleventy.config.js` — custom Nunjucks filters (isDate, localeString, verdictLabel, sourceTypeLabel, domainLabel, etc.), watches `assets/data`
- Build: `cd ~/esbvaktin-site && npm run build` (or `npm run serve` for dev)
- Data pipeline: `export_entities.py` → `export_evidence.py` → `export_topics.py` → `export_claims.py` → `prepare_site.py` (overlays DB verdicts) → `prepare_speeches.py` → `export_overviews.py` → build site
- `prepare_site.py` overlays DB verdicts onto `_report_final.json` snapshots — report files are immutable pipeline output, DB is source of truth for verdicts
- Homepage: server-rendered from `_data/home.js` which reads `assets/data/*.json` (countdown, signal cards, verdict distribution, recent reports, featured voices)
- Tracker JS architecture: `site-taxonomy.js` → `tracker-utils.js` → `tracker-renderer.js` → `tracker-controller.js` → page-specific tracker. Controller owns boot flow; page scripts keep only domain logic.
- Pages: `/umraedan/` (reports), `/fullyrdingar/` (claims), `/raddirnar/` (entities), `/heimildir/` (evidence, 338 detail pages), `/thingraedur/` (debates). `/greiningar/` redirects to `/umraedan/`.
- Nunjucks `capitalize` filter lowercases the rest of the string — don't use it for titles with proper nouns. Capitalise in Python data export instead.
- Speeches module has two DB access patterns: async aiosqlite (MCP server in `search.py`) and sync sqlite3 (pipeline in `context.py`, export scripts). Same althingi.db.
