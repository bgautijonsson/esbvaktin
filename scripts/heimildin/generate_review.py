"""Generate an interactive HTML review tool for Heimildin deliverables.

Embeds all canonical claims and instances into a single self-contained HTML file
for browsing, filtering, and quality review.

Usage:
    uv run python scripts/heimildin/generate_review.py
"""

from __future__ import annotations

import json

from config import DELIVERABLES_DIR, TOPIC_LABELS_IS, TOPIC_PREFIX_MAP, WORK_DIR

STANCE_LABELS = {
    "pro_eu": "Fylgjandi",
    "anti_eu": "Andvíg",
    "neutral": "Hlutlaus",
}


def get_topic(canonical_id: str) -> str:
    prefix = canonical_id.split("-")[0] if "-" in canonical_id else "OTH"
    return TOPIC_PREFIX_MAP.get(prefix, "other")


def build_data() -> dict:
    """Load and prepare all data for embedding."""
    data = {"canonicals": [], "instances": {}, "stats": {}, "cross_era": []}

    for era in ["esb", "ees"]:
        canon = json.loads((WORK_DIR / f"{era}_canonical.json").read_text(encoding="utf-8"))
        enriched = json.loads(
            (WORK_DIR / f"{era}_claims_enriched.json").read_text(encoding="utf-8")
        )
        stats_file = WORK_DIR / f"{era}_stats.json"
        if stats_file.exists():
            data["stats"][era] = json.loads(stats_file.read_text(encoding="utf-8"))

        for c in canon:
            c["era"] = era
            c["topic"] = get_topic(c["canonical_id"])
            data["canonicals"].append(c)

        for inst in enriched:
            data["instances"][inst["instance_id"]] = {
                "speaker": inst.get("speaker", "?"),
                "party": inst.get("party", "?"),
                "date": inst.get("date", "?"),
                "quote": inst.get("exact_quote", ""),
                "url": inst.get("speech_url", ""),
                "summary": inst.get("claim_summary", ""),
            }

    # Cross-era themes
    themes_file = WORK_DIR / "canonicalise" / "cross_era_themes.json"
    if themes_file.exists():
        data["cross_era"] = json.loads(themes_file.read_text(encoding="utf-8"))

    # Meta-claims (if curated)
    meta_file = WORK_DIR / "meta_claims.json"
    if meta_file.exists():
        data["meta_claims"] = json.loads(meta_file.read_text(encoding="utf-8"))
        data["meta_assigned"] = {}
        for era in ["esb", "ees"]:
            assigned_file = WORK_DIR / f"{era}_meta_assigned.json"
            if assigned_file.exists():
                assigned = json.loads(assigned_file.read_text(encoding="utf-8"))
                for inst in assigned:
                    iid = inst.get("instance_id", "")
                    if iid in data["instances"]:
                        data["instances"][iid]["meta_claim_id"] = inst.get(
                            "meta_claim_id", "UNASSIGNED"
                        )
                        data["instances"][iid]["meta_claim_sim"] = inst.get("meta_claim_sim", 0)

    return data


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="is">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Heimildin — Yfirferð meginfullyrðinga</title>
<style>
  :root {
    --bg: #fafafa; --fg: #1a1a1a; --muted: #666; --border: #ddd;
    --accent: #2563eb; --accent-light: #eff6ff;
    --pro: #059669; --anti: #dc2626; --neutral: #6b7280;
    --row-hover: #f5f5f5; --expand-bg: #f9fafb;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg);
    line-height: 1.5; font-size: 14px;
  }
  .container { max-width: 1400px; margin: 0 auto; padding: 16px; }

  /* Header */
  header { padding: 20px 0 12px; border-bottom: 2px solid var(--fg); margin-bottom: 16px; }
  header h1 { font-size: 22px; font-weight: 700; }
  header p { color: var(--muted); font-size: 13px; margin-top: 4px; }

  /* Stats bar */
  .stats-bar {
    display: flex; gap: 24px; flex-wrap: wrap;
    padding: 12px 0; border-bottom: 1px solid var(--border); margin-bottom: 16px;
  }
  .stat { text-align: center; }
  .stat .val { font-size: 24px; font-weight: 700; }
  .stat .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }

  /* Tabs */
  .tabs {
    display: flex; gap: 0; border-bottom: 2px solid var(--border); margin-bottom: 16px;
  }
  .tab {
    padding: 8px 20px; cursor: pointer; font-size: 13px; font-weight: 600;
    color: var(--muted); border-bottom: 2px solid transparent;
    margin-bottom: -2px; transition: all 0.15s;
  }
  .tab:hover { color: var(--fg); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }

  /* Filters */
  .filters {
    display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
    margin-bottom: 12px;
  }
  .filters select, .filters input {
    padding: 6px 10px; border: 1px solid var(--border); border-radius: 4px;
    font-size: 13px; background: white;
  }
  .filters input { width: 260px; }
  .filters .count { font-size: 12px; color: var(--muted); margin-left: auto; }

  /* Sort controls */
  .sort-row {
    display: flex; gap: 8px; align-items: center; margin-bottom: 8px;
    font-size: 12px; color: var(--muted);
  }
  .sort-btn {
    padding: 3px 8px; border: 1px solid var(--border); border-radius: 3px;
    background: white; cursor: pointer; font-size: 11px;
  }
  .sort-btn.active { background: var(--accent); color: white; border-color: var(--accent); }

  /* Table */
  table { width: 100%; border-collapse: collapse; }
  th {
    text-align: left; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; color: var(--muted); padding: 8px 10px;
    border-bottom: 2px solid var(--border); cursor: pointer;
    user-select: none; white-space: nowrap;
  }
  th:hover { color: var(--fg); }
  th .arrow { font-size: 10px; margin-left: 3px; }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:hover td { background: var(--row-hover); }
  tr.expandable { cursor: pointer; }

  .canonical-text { max-width: 500px; }
  .freq { font-weight: 700; font-size: 16px; text-align: center; }
  .era-tag {
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 11px; font-weight: 600; text-transform: uppercase;
  }
  .era-esb { background: #dbeafe; color: #1e40af; }
  .era-ees { background: #fef3c7; color: #92400e; }

  .stance-tag {
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 11px; font-weight: 600;
  }
  .stance-pro_eu { background: #d1fae5; color: var(--pro); }
  .stance-anti_eu { background: #fee2e2; color: var(--anti); }
  .stance-neutral { background: #f3f4f6; color: var(--neutral); }

  .topic-tag {
    font-size: 11px; color: var(--muted); white-space: nowrap;
  }
  .cid { font-family: monospace; font-size: 12px; color: var(--muted); }
  .speakers { font-size: 12px; color: var(--muted); max-width: 200px; }

  /* Expanded row */
  .instance-row td { background: var(--expand-bg); border-bottom: 1px solid #eee; padding: 6px 10px 6px 30px; }
  .instance-row .inst-speaker { font-weight: 600; }
  .instance-row .inst-party { color: var(--muted); font-size: 12px; }
  .instance-row .inst-date { color: var(--muted); font-size: 12px; }
  .instance-row .inst-quote {
    font-style: italic; color: #444; font-size: 13px;
    max-width: 700px; display: block; margin-top: 3px;
  }
  .instance-row a { color: var(--accent); text-decoration: none; font-size: 12px; }
  .instance-row a:hover { text-decoration: underline; }

  /* Cross-era view */
  .theme-type-header {
    font-size: 16px; font-weight: 700; margin: 20px 0 8px; padding-bottom: 4px;
    border-bottom: 1px solid var(--border);
  }
  .theme-row td { padding: 6px 10px; }
  .theme-note { font-size: 12px; color: var(--muted); max-width: 400px; }

  /* Responsive */
  @media (max-width: 900px) {
    .canonical-text { max-width: 300px; }
    .speakers { display: none; }
  }

  .hidden { display: none; }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Heimildin — Yfirferð meginfullyrðinga</h1>
    <p>Samanburður á ESB-umræðu (2024–2026) og EES-umræðu (1991–1993) á Alþingi</p>
  </header>

  <div class="stats-bar" id="stats-bar"></div>

  <div class="tabs">
    <div class="tab active" data-tab="claims">Meginfullyrðingar</div>
    <div class="tab" data-tab="cross-era">Samanburður milli tímabila</div>
    <div class="tab" data-tab="meta" id="meta-tab" style="display:none">Meta-fullyrðingar</div>
  </div>

  <div id="claims-view">
    <div class="filters">
      <select id="filter-era">
        <option value="">Bæði tímabil</option>
        <option value="esb">ESB (2024–2026)</option>
        <option value="ees">EES (1991–1993)</option>
      </select>
      <select id="filter-topic"><option value="">Allir flokkar</option></select>
      <select id="filter-stance">
        <option value="">Öll afstaða</option>
        <option value="anti_eu">Andvíg</option>
        <option value="pro_eu">Fylgjandi</option>
        <option value="neutral">Hlutlaus</option>
      </select>
      <select id="filter-min">
        <option value="1">Allar (≥1)</option>
        <option value="2">≥2 tilvik</option>
        <option value="3">≥3 tilvik</option>
        <option value="5">≥5 tilvik</option>
        <option value="10">≥10 tilvik</option>
      </select>
      <input type="text" id="filter-text" placeholder="Leita í texta...">
      <span class="count" id="filter-count"></span>
    </div>

    <div class="sort-row">
      Raða:
      <button class="sort-btn active" data-sort="freq">Tíðni</button>
      <button class="sort-btn" data-sort="topic">Flokkur</button>
      <button class="sort-btn" data-sort="id">Auðkenni</button>
      <button class="sort-btn" data-sort="text">Texti</button>
    </div>

    <table id="claims-table">
      <thead>
        <tr>
          <th style="width:40px">#</th>
          <th style="width:70px">Tíðni</th>
          <th style="width:60px">Tímabil</th>
          <th style="width:70px">Auðkenni</th>
          <th>Meginfullyrðing</th>
          <th style="width:100px">Flokkur</th>
          <th style="width:80px">Afstaða</th>
          <th style="width:200px">Þingmenn</th>
        </tr>
      </thead>
      <tbody id="claims-body"></tbody>
    </table>
  </div>

  <div id="cross-era-view" class="hidden">
    <div class="filters">
      <select id="ce-filter-type">
        <option value="">Allar gerðir</option>
        <option value="perennial">Lifðu af (perennial)</option>
        <option value="new_2026">Nýjar 2026</option>
        <option value="disappeared">Hurfu</option>
      </select>
      <span class="count" id="ce-count"></span>
    </div>
    <table id="cross-era-table">
      <thead>
        <tr>
          <th style="width:40px">#</th>
          <th>Röksemdafærsla</th>
          <th style="width:60px">Gerð</th>
          <th style="width:80px">ESB (2026)</th>
          <th style="width:80px">EES (1993)</th>
          <th style="width:100px">ESB-auðkenni</th>
          <th style="width:100px">EES-auðkenni</th>
          <th style="width:300px">Athugasemd</th>
        </tr>
      </thead>
      <tbody id="cross-era-body"></tbody>
    </table>
  </div>

  <div id="meta-view" class="hidden">
    <div class="filters">
      <select id="meta-filter-topic"><option value="">Allir flokkar</option></select>
      <input type="text" id="meta-filter-text" placeholder="Leita...">
      <span class="count" id="meta-count"></span>
    </div>
    <table>
      <thead>
        <tr>
          <th style="width:40px">#</th>
          <th style="width:50px">ID</th>
          <th>Meta-fullyrðing</th>
          <th style="width:100px">Efnisflokkur</th>
          <th style="width:80px">ESB</th>
          <th style="width:80px">EES</th>
          <th style="width:80px">Samtals</th>
        </tr>
      </thead>
      <tbody id="meta-body"></tbody>
    </table>
  </div>
</div>

<script id="review-data" type="application/json">__DATA_PLACEHOLDER__</script>
<script id="topic-labels" type="application/json">__TOPIC_LABELS_IS__</script>
<script id="stance-labels" type="application/json">__STANCE_LABELS__</script>

<script>
const DATA = JSON.parse(document.getElementById("review-data").textContent);

const TOPIC_IS = JSON.parse(document.getElementById("topic-labels").textContent);
const STANCE_IS = JSON.parse(document.getElementById("stance-labels").textContent);
const TYPE_IS = {perennial: "Lifði af", new_2026: "Ný 2026", disappeared: "Hvarf"};

// Build lookups
const canonById = {};
DATA.canonicals.forEach(c => { canonById[c.canonical_id] = c; });

// Speakers per canonical
function speakersFor(c) {
  const s = new Set();
  (c.instance_ids || []).forEach(id => {
    const inst = DATA.instances[id];
    if (inst) s.add(inst.speaker);
  });
  return [...s].sort();
}

// Parties per canonical
function partiesFor(c) {
  const s = new Set();
  (c.instance_ids || []).forEach(id => {
    const inst = DATA.instances[id];
    if (inst) s.add(inst.party);
  });
  return [...s].sort();
}

// Stats bar
function renderStats() {
  const bar = document.getElementById("stats-bar");
  const esb = DATA.stats.esb || {};
  const ees = DATA.stats.ees || {};
  const esbCanon = DATA.canonicals.filter(c => c.era === "esb").length;
  const eesCanon = DATA.canonicals.filter(c => c.era === "ees").length;
  bar.innerHTML = `
    <div class="stat"><div class="val">${esb.speeches || 0}</div><div class="label">ESB ræður</div></div>
    <div class="stat"><div class="val">${ees.speeches || 0}</div><div class="label">EES ræður</div></div>
    <div class="stat"><div class="val">${esb.total_claims || 0}</div><div class="label">ESB tilvik</div></div>
    <div class="stat"><div class="val">${ees.total_claims || 0}</div><div class="label">EES tilvik</div></div>
    <div class="stat"><div class="val">${esbCanon}</div><div class="label">ESB meginfull.</div></div>
    <div class="stat"><div class="val">${eesCanon}</div><div class="label">EES meginfull.</div></div>
    <div class="stat"><div class="val">${DATA.cross_era.length}</div><div class="label">Þemu</div></div>
  `;
}

// Populate topic filter
function populateTopicFilter() {
  const topics = new Set();
  DATA.canonicals.forEach(c => topics.add(c.topic));
  const sel = document.getElementById("filter-topic");
  [...topics].sort().forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = TOPIC_IS[t] || t;
    sel.appendChild(opt);
  });
}

// State
let currentSort = "freq";
let sortAsc = false;
let expandedRows = new Set();

function getFiltered() {
  const era = document.getElementById("filter-era").value;
  const topic = document.getElementById("filter-topic").value;
  const stance = document.getElementById("filter-stance").value;
  const minCount = parseInt(document.getElementById("filter-min").value) || 1;
  const text = document.getElementById("filter-text").value.toLowerCase();

  return DATA.canonicals.filter(c => {
    if (era && c.era !== era) return false;
    if (topic && c.topic !== topic) return false;
    if (stance && c.stance !== stance) return false;
    if (c.instance_count < minCount) return false;
    if (text && !c.canonical_text.toLowerCase().includes(text)
        && !c.canonical_id.toLowerCase().includes(text)) return false;
    return true;
  });
}

function sortData(list) {
  const dir = sortAsc ? 1 : -1;
  return list.sort((a, b) => {
    switch (currentSort) {
      case "freq": return dir * (b.instance_count - a.instance_count);
      case "topic": return dir * a.topic.localeCompare(b.topic);
      case "id": return dir * a.canonical_id.localeCompare(b.canonical_id);
      case "text": return dir * a.canonical_text.localeCompare(b.canonical_text, "is");
      default: return 0;
    }
  });
}

function renderClaims() {
  const filtered = sortData(getFiltered());
  const tbody = document.getElementById("claims-body");
  const rows = [];

  filtered.forEach((c, i) => {
    const speakers = speakersFor(c);
    const speakerText = speakers.map(s => s.split(" ").pop()).join(", ");
    const isExpanded = expandedRows.has(c.canonical_id + c.era);

    rows.push(`<tr class="expandable" data-cid="${c.canonical_id}" data-era="${c.era}">
      <td>${i + 1}</td>
      <td class="freq">${c.instance_count}×</td>
      <td><span class="era-tag era-${c.era}">${c.era.toUpperCase()}</span></td>
      <td class="cid">${c.canonical_id}</td>
      <td class="canonical-text">${esc(c.canonical_text)}</td>
      <td class="topic-tag">${TOPIC_IS[c.topic] || c.topic}</td>
      <td><span class="stance-tag stance-${c.stance}">${STANCE_IS[c.stance] || c.stance}</span></td>
      <td class="speakers" title="${esc(speakers.join(', '))}">${esc(speakerText)}</td>
    </tr>`);

    if (isExpanded) {
      const instances = (c.instance_ids || [])
        .map(id => DATA.instances[id])
        .filter(Boolean)
        .sort((a, b) => (a.date || "").localeCompare(b.date || ""));

      instances.forEach(inst => {
        rows.push(`<tr class="instance-row">
          <td></td>
          <td colspan="7">
            <span class="inst-speaker">${esc(inst.speaker)}</span>
            <span class="inst-party">(${esc(inst.party)})</span>
            <span class="inst-date">— ${inst.date}</span>
            ${inst.url ? `<a href="${inst.url}" target="_blank">althingi.is</a>` : ""}
            <span class="inst-quote">${esc(inst.quote)}</span>
          </td>
        </tr>`);
      });
    }
  });

  tbody.innerHTML = rows.join("");
  document.getElementById("filter-count").textContent =
    `${filtered.length} af ${DATA.canonicals.length} meginfullyrðingum`;
}

// Cross-era view
function renderCrossEra() {
  const typeFilter = document.getElementById("ce-filter-type").value;
  let themes = DATA.cross_era;
  if (typeFilter) themes = themes.filter(t => t.type === typeFilter);

  // Sort by total instances desc
  themes = themes.sort((a, b) => {
    const aTotal = countInstances(a, "esb") + countInstances(a, "ees");
    const bTotal = countInstances(b, "esb") + countInstances(b, "ees");
    return bTotal - aTotal;
  });

  const tbody = document.getElementById("cross-era-body");
  const rows = [];

  themes.forEach((t, i) => {
    const esbN = countInstances(t, "esb");
    const eesN = countInstances(t, "ees");
    rows.push(`<tr class="theme-row">
      <td>${i + 1}</td>
      <td>${esc(t.theme)}</td>
      <td><span class="era-tag ${t.type === 'new_2026' ? 'era-esb' : t.type === 'disappeared' ? 'era-ees' : ''}">${TYPE_IS[t.type] || t.type}</span></td>
      <td class="freq">${esbN ? esbN + "×" : "—"}</td>
      <td class="freq">${eesN ? eesN + "×" : "—"}</td>
      <td class="cid">${(t.esb_ids || []).join(", ")}</td>
      <td class="cid">${(t.ees_ids || []).join(", ")}</td>
      <td class="theme-note">${esc(t.note || "")}</td>
    </tr>`);
  });

  tbody.innerHTML = rows.join("");
  document.getElementById("ce-count").textContent = `${themes.length} þemu`;
}

function countInstances(theme, era) {
  const ids = theme[era + "_ids"] || [];
  return ids.reduce((sum, id) => {
    const c = canonById[id];
    return sum + (c ? c.instance_count : 0);
  }, 0);
}

function esc(s) {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Event handlers
document.getElementById("claims-body").addEventListener("click", e => {
  const row = e.target.closest("tr.expandable");
  if (!row) return;
  const key = row.dataset.cid + row.dataset.era;
  if (expandedRows.has(key)) expandedRows.delete(key);
  else expandedRows.add(key);
  renderClaims();
});

document.querySelectorAll(".filters select, .filters input").forEach(el => {
  el.addEventListener("change", () => {
    expandedRows.clear();
    if (document.getElementById("claims-view").style.display !== "none") renderClaims();
    else renderCrossEra();
  });
  if (el.tagName === "INPUT") {
    el.addEventListener("input", () => { expandedRows.clear(); renderClaims(); });
  }
});

document.querySelectorAll(".sort-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const newSort = btn.dataset.sort;
    if (currentSort === newSort) sortAsc = !sortAsc;
    else { currentSort = newSort; sortAsc = false; }
    document.querySelectorAll(".sort-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    expandedRows.clear();
    renderClaims();
  });
});

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    const view = tab.dataset.tab;
    document.getElementById("claims-view").classList.toggle("hidden", view !== "claims");
    document.getElementById("cross-era-view").classList.toggle("hidden", view !== "cross-era");
    document.getElementById("meta-view").classList.toggle("hidden", view !== "meta");
    if (view === "cross-era") renderCrossEra();
    else if (view === "meta") renderMeta();
    else renderClaims();
  });
});

// ─── Meta-claim view ────────────────────────────────────────────────
const HAS_META = !!(DATA.meta_claims && DATA.meta_claims.length);

function buildMetaStats() {
  if (!HAS_META) return {};
  const stats = {};
  DATA.meta_claims.forEach(m => { stats[m.id] = { esb: 0, ees: 0 }; });
  // Count from instances that have meta_claim_id
  Object.values(DATA.instances).forEach(inst => {
    const mid = inst.meta_claim_id;
    if (mid && mid !== "UNASSIGNED" && stats[mid]) {
      // Determine era from date
      const year = parseInt((inst.date || "").substring(0, 4));
      if (year >= 2020) stats[mid].esb++;
      else stats[mid].ees++;
    }
  });
  return stats;
}

const metaStats = buildMetaStats();

function renderMeta() {
  if (!HAS_META) return;
  const textFilter = document.getElementById("meta-filter-text").value.toLowerCase();
  const topicFilter = document.getElementById("meta-filter-topic").value;

  let metas = DATA.meta_claims.filter(m => {
    if (topicFilter && m.category !== topicFilter) return false;
    if (textFilter && !m.text.toLowerCase().includes(textFilter)) return false;
    return true;
  });

  // Sort by total
  metas.sort((a, b) => {
    const aT = (metaStats[a.id]?.esb || 0) + (metaStats[a.id]?.ees || 0);
    const bT = (metaStats[b.id]?.esb || 0) + (metaStats[b.id]?.ees || 0);
    return bT - aT;
  });

  const tbody = document.getElementById("meta-body");
  tbody.innerHTML = metas.map((m, i) => {
    const s = metaStats[m.id] || { esb: 0, ees: 0 };
    const total = s.esb + s.ees;
    return `<tr>
      <td>${i + 1}</td>
      <td class="cid">${m.id}</td>
      <td>${esc(m.text)}</td>
      <td class="topic-tag">${TOPIC_IS[m.category] || m.category}</td>
      <td class="freq">${s.esb ? s.esb + "×" : "—"}</td>
      <td class="freq">${s.ees ? s.ees + "×" : "—"}</td>
      <td class="freq">${total}×</td>
    </tr>`;
  }).join("");

  document.getElementById("meta-count").textContent =
    `${metas.length} af ${DATA.meta_claims.length} meta-fullyrðingum`;
}

function initMeta() {
  if (!HAS_META) return;
  // Show tab
  document.getElementById("meta-tab").style.display = "";
  // Populate topic filter
  const topics = new Set(DATA.meta_claims.map(m => m.category));
  const sel = document.getElementById("meta-filter-topic");
  [...topics].sort().forEach(t => {
    const o = document.createElement("option");
    o.value = t; o.textContent = TOPIC_IS[t] || t;
    sel.appendChild(o);
  });
  sel.addEventListener("change", renderMeta);
  document.getElementById("meta-filter-text").addEventListener("input", renderMeta);
}

// Init
renderStats();
populateTopicFilter();
renderClaims();
initMeta();
</script>
</body>
</html>
"""


def main() -> None:
    data = build_data()

    data_json = json.dumps(data, ensure_ascii=False).replace("</", r"<\/")
    topic_json = json.dumps(TOPIC_LABELS_IS, ensure_ascii=False).replace("</", r"<\/")
    stance_json = json.dumps(STANCE_LABELS, ensure_ascii=False).replace("</", r"<\/")

    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)
    html = html.replace("__TOPIC_LABELS_IS__", topic_json)
    html = html.replace("__STANCE_LABELS__", stance_json)

    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    out = DELIVERABLES_DIR / "review.html"
    out.write_text(html, encoding="utf-8")
    print(f"Review tool written: {out} ({out.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
