/**
 * ESBvaktin Claim Tracker — Client-side UI powered by DuckDB-WASM
 *
 * Loads a Parquet file of referendum claims and provides interactive
 * filtering, searching, and sorting entirely in the browser.
 *
 * Falls back to plain JSON + array filtering if WASM is unavailable.
 */

(function () {
  "use strict";

  // ── Configuration ────────────────────────────────────────────────
  const DATA_BASE = document.currentScript?.dataset.base || "/assets/data";
  const PARQUET_URL = `${DATA_BASE}/claims.parquet`;
  const JSON_URL = `${DATA_BASE}/claims.json`;

  // Icelandic labels
  const VERDICT_LABELS = {
    supported: "Staðfest",
    partially_supported: "Að hluta staðfest",
    unsupported: "Óstutt",
    misleading: "Villandi",
    unverifiable: "Ósannanlegt",
  };

  const CATEGORY_LABELS = {
    fisheries: "Sjávarútvegur",
    trade: "Viðskipti",
    sovereignty: "Fullveldi",
    agriculture: "Landbúnaður",
    labour: "Vinnumarkaður",
    currency: "Gjaldmiðill",
    precedents: "Fordæmi",
    eea_eu_law: "EES/ESB-löggjöf",
    housing: "Húsnæðismál",
    polling: "Kannanir",
    party_positions: "Flokkastefnur",
    org_positions: "Samtakastefnur",
    energy: "Orkumál",
  };

  const VERDICT_CLASSES = {
    supported: "verdict-supported",
    partially_supported: "verdict-partial",
    unsupported: "verdict-unsupported",
    misleading: "verdict-misleading",
    unverifiable: "verdict-unverifiable",
  };

  // ── State ────────────────────────────────────────────────────────
  let db = null;
  let conn = null;
  let usingDuckDB = false;
  let jsonData = null;

  // Current filter state
  let filters = {
    search: "",
    category: "",
    verdict: "",
    sort: "sighting_count",
    sortDir: "DESC",
  };

  // ── DOM references ───────────────────────────────────────────────
  const root = document.getElementById("claim-tracker");
  if (!root) return;

  // ── Initialisation ───────────────────────────────────────────────

  async function init() {
    renderSkeleton();

    try {
      await initDuckDB();
      usingDuckDB = true;
    } catch (err) {
      console.warn("DuckDB-WASM unavailable, falling back to JSON:", err);
      await initJSONFallback();
    }

    renderStats();
    renderResults();
    bindEvents();
  }

  async function initDuckDB() {
    const duckdb = await import(
      "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm"
    );

    const JSDELIVR_BUNDLES = duckdb.getJsDelivrBundles();

    const bundle = await duckdb.selectBundle(JSDELIVR_BUNDLES);
    const worker = new Worker(bundle.mainWorker);
    const logger = new duckdb.ConsoleLogger();

    db = new duckdb.AsyncDuckDB(logger, worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);

    conn = await db.connect();

    // Load ICU for Icelandic collation
    await conn.query("INSTALL icu; LOAD icu;");

    // Register the Parquet file
    await db.registerFileURL("claims.parquet", PARQUET_URL, 4, false);
    await conn.query(
      "CREATE TABLE claims AS SELECT * FROM read_parquet('claims.parquet')"
    );

    // Verify data loaded
    const result = await conn.query("SELECT COUNT(*) AS n FROM claims");
    const count = result.toArray()[0].n;
    if (count === 0) throw new Error("No claims in Parquet file");

    console.log(`DuckDB-WASM loaded: ${count} claims`);
  }

  async function initJSONFallback() {
    const resp = await fetch(JSON_URL);
    if (!resp.ok) throw new Error(`Failed to fetch ${JSON_URL}: ${resp.status}`);
    jsonData = await resp.json();
    console.log(`JSON fallback loaded: ${jsonData.length} claims`);
  }

  // ── Query layer ──────────────────────────────────────────────────

  async function queryClaims() {
    if (usingDuckDB) return queryDuckDB();
    return queryJSON();
  }

  async function queryDuckDB() {
    const conditions = [];
    const params = [];

    if (filters.search) {
      // Use ILIKE for Icelandic case-insensitive search
      conditions.push(
        "(canonical_text_is ILIKE ? OR explanation_is ILIKE ? OR COALESCE(missing_context_is, '') ILIKE ?)"
      );
      const pattern = `%${filters.search}%`;
      params.push(pattern, pattern, pattern);
    }
    if (filters.category) {
      conditions.push("category = ?");
      params.push(filters.category);
    }
    if (filters.verdict) {
      conditions.push("verdict = ?");
      params.push(filters.verdict);
    }

    const where = conditions.length
      ? `WHERE ${conditions.join(" AND ")}`
      : "";

    const validSorts = [
      "sighting_count",
      "category",
      "confidence",
      "last_verified",
      "claim_slug",
    ];
    const sort = validSorts.includes(filters.sort)
      ? filters.sort
      : "sighting_count";
    const dir = filters.sortDir === "ASC" ? "ASC" : "DESC";

    const sql = `SELECT * FROM claims ${where} ORDER BY ${sort} ${dir}`;

    const stmt = await conn.prepare(sql);
    params.forEach((p, i) => stmt.bind(i + 1, p));
    const result = await stmt.query();
    stmt.close();

    return result.toArray().map((row) => ({
      claim_slug: row.claim_slug,
      canonical_text_is: row.canonical_text_is,
      canonical_text_en: row.canonical_text_en,
      category: row.category,
      claim_type: row.claim_type,
      verdict: row.verdict,
      explanation_is: row.explanation_is,
      explanation_en: row.explanation_en,
      missing_context_is: row.missing_context_is,
      confidence: row.confidence,
      last_verified: row.last_verified,
      sighting_count: Number(row.sighting_count),
      last_seen: row.last_seen,
      first_seen: row.first_seen,
    }));
  }

  function queryJSON() {
    let results = [...jsonData];

    if (filters.search) {
      const q = filters.search.toLowerCase();
      results = results.filter(
        (c) =>
          c.canonical_text_is?.toLowerCase().includes(q) ||
          c.explanation_is?.toLowerCase().includes(q) ||
          c.missing_context_is?.toLowerCase().includes(q)
      );
    }
    if (filters.category) {
      results = results.filter((c) => c.category === filters.category);
    }
    if (filters.verdict) {
      results = results.filter((c) => c.verdict === filters.verdict);
    }

    const sort = filters.sort || "sighting_count";
    const dir = filters.sortDir === "ASC" ? 1 : -1;
    results.sort((a, b) => {
      const va = a[sort] ?? "";
      const vb = b[sort] ?? "";
      if (typeof va === "number") return (va - vb) * dir;
      return String(va).localeCompare(String(vb), "is") * dir;
    });

    return results;
  }

  async function queryStats() {
    if (usingDuckDB) {
      const result = await conn.query(`
        SELECT
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE verdict = 'supported') AS supported,
          COUNT(*) FILTER (WHERE verdict = 'partially_supported') AS partial,
          COUNT(*) FILTER (WHERE verdict = 'misleading') AS misleading,
          COUNT(*) FILTER (WHERE verdict = 'unverifiable') AS unverifiable,
          COUNT(*) FILTER (WHERE verdict = 'unsupported') AS unsupported,
          COALESCE(SUM(sighting_count), 0) AS total_sightings
        FROM claims
      `);
      const row = result.toArray()[0];
      return {
        total: Number(row.total),
        supported: Number(row.supported),
        partial: Number(row.partial),
        misleading: Number(row.misleading),
        unverifiable: Number(row.unverifiable),
        unsupported: Number(row.unsupported),
        totalSightings: Number(row.total_sightings),
      };
    }

    // JSON fallback
    const data = jsonData || [];
    return {
      total: data.length,
      supported: data.filter((c) => c.verdict === "supported").length,
      partial: data.filter((c) => c.verdict === "partially_supported").length,
      misleading: data.filter((c) => c.verdict === "misleading").length,
      unverifiable: data.filter((c) => c.verdict === "unverifiable").length,
      unsupported: data.filter((c) => c.verdict === "unsupported").length,
      totalSightings: data.reduce((s, c) => s + (c.sighting_count || 0), 0),
    };
  }

  // ── Rendering ────────────────────────────────────────────────────

  function renderSkeleton() {
    root.innerHTML = `
      <div class="ct-header">
        <h2>Fullyrðingavaktin</h2>
        <p class="ct-subtitle">Allar helstu fullyrðingar í ESB-umræðunni — metnar á móti gögnum og heimildum.</p>
      </div>

      <div class="ct-stats" id="ct-stats">
        <div class="ct-stat-loading">Hleð gögnum…</div>
      </div>

      <div class="ct-controls">
        <div class="ct-search-wrap">
          <input type="search" id="ct-search" class="ct-search"
                 placeholder="Leita í fullyrðingum…" autocomplete="off" />
        </div>
        <div class="ct-filter-row">
          <select id="ct-category" class="ct-select">
            <option value="">Allir flokkar</option>
            ${Object.entries(CATEGORY_LABELS)
              .sort((a, b) => a[1].localeCompare(b[1], "is"))
              .map(([k, v]) => `<option value="${k}">${v}</option>`)
              .join("")}
          </select>
          <select id="ct-verdict" class="ct-select">
            <option value="">Öll úrskurðir</option>
            ${Object.entries(VERDICT_LABELS)
              .map(([k, v]) => `<option value="${k}">${v}</option>`)
              .join("")}
          </select>
          <select id="ct-sort" class="ct-select">
            <option value="sighting_count">Tíðni</option>
            <option value="category">Flokkur</option>
            <option value="confidence">Vissustig</option>
            <option value="last_verified">Síðast staðfest</option>
          </select>
        </div>
      </div>

      <div class="ct-results" id="ct-results">
        <div class="ct-loading">Hleð fullyrðingum…</div>
      </div>
    `;
  }

  async function renderStats() {
    const stats = await queryStats();
    const el = document.getElementById("ct-stats");
    el.innerHTML = `
      <div class="ct-stat">
        <span class="ct-stat-num">${stats.total}</span>
        <span class="ct-stat-label">fullyrðingar</span>
      </div>
      <div class="ct-stat">
        <span class="ct-stat-num">${stats.totalSightings}</span>
        <span class="ct-stat-label">tilvitnun</span>
      </div>
      <div class="ct-stat ct-stat-supported">
        <span class="ct-stat-num">${stats.supported}</span>
        <span class="ct-stat-label">staðfestar</span>
      </div>
      <div class="ct-stat ct-stat-partial">
        <span class="ct-stat-num">${stats.partial}</span>
        <span class="ct-stat-label">að hluta</span>
      </div>
      <div class="ct-stat ct-stat-misleading">
        <span class="ct-stat-num">${stats.misleading}</span>
        <span class="ct-stat-label">villandi</span>
      </div>
      <div class="ct-stat ct-stat-unverifiable">
        <span class="ct-stat-num">${stats.unverifiable}</span>
        <span class="ct-stat-label">ósannanlegar</span>
      </div>
    `;
  }

  async function renderResults() {
    const claims = await queryClaims();
    const el = document.getElementById("ct-results");

    if (claims.length === 0) {
      el.innerHTML = `<div class="ct-empty">Engar fullyrðingar fundust.</div>`;
      return;
    }

    el.innerHTML = claims.map(renderClaimCard).join("");

    // Bind expand/collapse
    el.querySelectorAll(".ct-card-header").forEach((header) => {
      header.addEventListener("click", () => {
        header.parentElement.classList.toggle("ct-expanded");
      });
    });
  }

  function renderClaimCard(claim) {
    const verdictClass = VERDICT_CLASSES[claim.verdict] || "";
    const verdictLabel = VERDICT_LABELS[claim.verdict] || claim.verdict;
    const categoryLabel = CATEGORY_LABELS[claim.category] || claim.category;
    const confidencePct = Math.round((claim.confidence || 0) * 100);

    let detailsHtml = "";
    if (claim.explanation_is) {
      detailsHtml += `<div class="ct-detail"><strong>Útskýring:</strong> ${escapeHtml(claim.explanation_is)}</div>`;
    }
    if (claim.missing_context_is) {
      detailsHtml += `<div class="ct-detail"><strong>Samhengi sem vantar:</strong> ${escapeHtml(claim.missing_context_is)}</div>`;
    }
    if (claim.canonical_text_en) {
      detailsHtml += `<div class="ct-detail ct-english"><strong>English:</strong> ${escapeHtml(claim.canonical_text_en)}</div>`;
    }

    const sightingBadge =
      claim.sighting_count > 0
        ? `<span class="ct-sighting-count" title="Fjöldi tilvitana">${claim.sighting_count}×</span>`
        : "";

    return `
      <div class="ct-card" data-slug="${escapeHtml(claim.claim_slug)}">
        <div class="ct-card-header" role="button" tabindex="0" aria-expanded="false">
          <div class="ct-card-main">
            <span class="ct-verdict-pill ${verdictClass}">${verdictLabel}</span>
            <span class="ct-category-tag">${categoryLabel}</span>
            ${sightingBadge}
          </div>
          <p class="ct-claim-text">${escapeHtml(claim.canonical_text_is)}</p>
          <div class="ct-card-meta">
            <span class="ct-confidence" title="Vissustig">
              <span class="ct-confidence-bar" style="width: ${confidencePct}%"></span>
              ${confidencePct}%
            </span>
            <span class="ct-expand-icon">▸</span>
          </div>
        </div>
        <div class="ct-card-details">
          ${detailsHtml}
        </div>
      </div>
    `;
  }

  // ── Events ───────────────────────────────────────────────────────

  let searchTimeout = null;

  function bindEvents() {
    const searchInput = document.getElementById("ct-search");
    const categorySelect = document.getElementById("ct-category");
    const verdictSelect = document.getElementById("ct-verdict");
    const sortSelect = document.getElementById("ct-sort");

    searchInput.addEventListener("input", (e) => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        filters.search = e.target.value.trim();
        renderResults();
      }, 200);
    });

    categorySelect.addEventListener("change", (e) => {
      filters.category = e.target.value;
      renderResults();
    });

    verdictSelect.addEventListener("change", (e) => {
      filters.verdict = e.target.value;
      renderResults();
    });

    sortSelect.addEventListener("change", (e) => {
      filters.sort = e.target.value;
      renderResults();
    });
  }

  // ── Utilities ────────────────────────────────────────────────────

  function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Boot ─────────────────────────────────────────────────────────
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
