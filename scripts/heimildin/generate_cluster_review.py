"""Generate an interactive HTML tool for reviewing HDBSCAN clusters.

Embeds cluster_discovery.json into a single-file HTML for visual inspection.
Clusters can be expanded, filtered, and sorted.

Usage:
    uv run python scripts/heimildin/generate_cluster_review.py
"""

from __future__ import annotations

import json

from config import DELIVERABLES_DIR, TOPIC_LABELS_IS, WORK_DIR


def main() -> None:
    clusters_file = WORK_DIR / "cluster_discovery.json"
    if not clusters_file.exists():
        print("Run cluster_claims.py discover first.")
        return

    clusters = json.loads(clusters_file.read_text(encoding="utf-8"))

    # Load enriched claims for full quotes
    instances = {}
    for era in ["esb", "ees"]:
        path = WORK_DIR / f"{era}_claims_enriched.json"
        if path.exists():
            for c in json.loads(path.read_text(encoding="utf-8")):
                instances[c["instance_id"]] = {
                    "quote": c.get("exact_quote", ""),
                    "url": c.get("speech_url", ""),
                    "party": c.get("party", "?"),
                    "date": c.get("date", "?"),
                }

    # Merge quote data into cluster claims
    for cl in clusters:
        for claim in cl["claims"]:
            inst = instances.get(claim["instance_id"], {})
            claim["quote"] = inst.get("quote", "")
            claim["url"] = inst.get("url", "")
            claim["party"] = inst.get("party", "?")
            claim["date"] = inst.get("date", "?")

    # Stats
    total_clustered = sum(c["size"] for c in clusters)
    total_claims = len(instances)
    noise = total_claims - total_clustered

    stats = {
        "total_claims": total_claims,
        "total_clustered": total_clustered,
        "noise": noise,
        "n_clusters": len(clusters),
    }

    # Use ensure_ascii=False so Icelandic chars stay readable in the HTML.
    # Escape </ sequences to prevent premature </script> closure.
    data_json = json.dumps(clusters, ensure_ascii=False).replace("</", r"<\/")
    stats_json = json.dumps(stats)
    topic_json = json.dumps(TOPIC_LABELS_IS, ensure_ascii=False).replace("</", r"<\/")

    html = HTML.replace("__CLUSTERS__", data_json)
    html = html.replace("__STATS__", stats_json)
    html = html.replace("__TOPICS__", topic_json)

    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    out = DELIVERABLES_DIR / "cluster_review.html"
    out.write_text(html, encoding="utf-8")
    print(f"Cluster review: {out} ({out.stat().st_size // 1024}KB)")


HTML = """\
<!DOCTYPE html>
<html lang="is">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Heimildin — Cluster Review</title>
<style>
  :root {
    --bg: #fafafa; --fg: #1a1a1a; --muted: #666; --border: #ddd;
    --accent: #2563eb; --accent-light: #eff6ff;
    --pro: #059669; --anti: #dc2626; --neutral: #6b7280;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg); line-height: 1.5; font-size: 14px;
  }
  .app { display: flex; height: 100vh; }

  /* Sidebar — cluster list */
  .sidebar {
    width: 420px; min-width: 320px; border-right: 1px solid var(--border);
    display: flex; flex-direction: column; background: white;
  }
  .sidebar-header {
    padding: 16px; border-bottom: 1px solid var(--border);
  }
  .sidebar-header h1 { font-size: 16px; font-weight: 700; }
  .sidebar-header p { font-size: 12px; color: var(--muted); margin-top: 2px; }

  .sidebar-filters {
    padding: 8px 16px; border-bottom: 1px solid var(--border);
    display: flex; gap: 8px; flex-wrap: wrap;
  }
  .sidebar-filters select, .sidebar-filters input {
    padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px;
    font-size: 12px; background: white;
  }
  .sidebar-filters input { flex: 1; min-width: 120px; }

  .cluster-list {
    flex: 1; overflow-y: auto; padding: 0;
  }
  .cluster-item {
    padding: 10px 16px; border-bottom: 1px solid #eee; cursor: pointer;
    transition: background 0.1s;
  }
  .cluster-item:hover { background: #f5f5f5; }
  .cluster-item.selected { background: var(--accent-light); border-left: 3px solid var(--accent); }
  .cluster-item .ci-top {
    display: flex; align-items: center; gap: 8px; margin-bottom: 4px;
  }
  .cluster-item .ci-rank {
    font-size: 11px; color: var(--muted); min-width: 20px;
  }
  .cluster-item .ci-size {
    font-weight: 700; font-size: 18px; min-width: 35px;
  }
  .cluster-item .ci-bars {
    flex: 1; display: flex; height: 14px; border-radius: 3px; overflow: hidden;
    background: #eee;
  }
  .ci-bar-esb { background: #3b82f6; }
  .ci-bar-ees { background: #f59e0b; }
  .cluster-item .ci-text {
    font-size: 13px; color: #333; line-height: 1.4;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .cluster-item .ci-meta {
    font-size: 11px; color: var(--muted); margin-top: 3px;
  }
  .topic-pill {
    display: inline-block; padding: 0 5px; border-radius: 3px;
    font-size: 10px; font-weight: 600; background: #f3f4f6; color: var(--muted);
    margin-right: 4px;
  }
  .era-pill {
    display: inline-block; padding: 0 5px; border-radius: 3px;
    font-size: 10px; font-weight: 600; margin-right: 2px;
  }
  .era-esb { background: #dbeafe; color: #1e40af; }
  .era-ees { background: #fef3c7; color: #92400e; }

  /* Main panel — cluster detail */
  .main {
    flex: 1; overflow-y: auto; padding: 24px 32px;
  }
  .main-empty {
    display: flex; align-items: center; justify-content: center;
    height: 100%; color: var(--muted); font-size: 15px;
  }

  .detail-header { margin-bottom: 20px; }
  .detail-header h2 { font-size: 18px; font-weight: 700; margin-bottom: 4px; }
  .detail-header .dh-meta {
    font-size: 13px; color: var(--muted); margin-bottom: 8px;
  }
  .detail-header .dh-stats {
    display: flex; gap: 16px; flex-wrap: wrap;
  }
  .dh-stat {
    text-align: center; padding: 8px 16px;
    background: white; border: 1px solid var(--border); border-radius: 6px;
  }
  .dh-stat .val { font-size: 22px; font-weight: 700; }
  .dh-stat .lbl { font-size: 10px; color: var(--muted); text-transform: uppercase; }

  .detail-bar {
    display: flex; height: 24px; border-radius: 6px; overflow: hidden;
    margin: 12px 0; background: #eee;
  }
  .db-esb { background: #3b82f6; display: flex; align-items: center; justify-content: center;
    color: white; font-size: 11px; font-weight: 600; }
  .db-ees { background: #f59e0b; display: flex; align-items: center; justify-content: center;
    color: white; font-size: 11px; font-weight: 600; }

  .detail-topics {
    display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;
  }
  .detail-topics .tp {
    padding: 2px 8px; border-radius: 4px; font-size: 12px;
    background: #f3f4f6; color: var(--fg);
  }
  .detail-topics .tp .tp-n { font-weight: 700; }

  /* Claims table */
  .claims-section h3 {
    font-size: 13px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.5px; color: var(--muted); margin-bottom: 8px;
    padding-bottom: 4px; border-bottom: 1px solid var(--border);
  }
  .claim-card {
    padding: 10px 12px; margin-bottom: 8px;
    background: white; border: 1px solid var(--border); border-radius: 6px;
  }
  .claim-card:hover { border-color: #bbb; }
  .cc-summary { font-size: 13px; font-weight: 500; margin-bottom: 4px; }
  .cc-meta {
    font-size: 12px; color: var(--muted);
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  }
  .cc-speaker { font-weight: 600; color: var(--fg); }
  .cc-quote {
    margin-top: 6px; padding: 6px 10px; background: #f9fafb;
    border-left: 3px solid var(--border); font-style: italic;
    font-size: 12px; color: #555; line-height: 1.5;
    max-height: 80px; overflow: hidden; cursor: pointer;
    transition: max-height 0.3s;
  }
  .cc-quote.expanded { max-height: none; }
  .cc-link { font-size: 11px; }
  .cc-link a { color: var(--accent); text-decoration: none; }
  .cc-link a:hover { text-decoration: underline; }

  /* Sort tabs for claims */
  .sort-tabs {
    display: flex; gap: 4px; margin-bottom: 12px;
  }
  .sort-tab {
    padding: 3px 10px; border: 1px solid var(--border); border-radius: 4px;
    font-size: 11px; cursor: pointer; background: white;
  }
  .sort-tab.active { background: var(--accent); color: white; border-color: var(--accent); }

  .hidden { display: none; }
</style>
</head>
<body>
<div class="app">
  <div class="sidebar">
    <div class="sidebar-header">
      <h1>Cluster Review</h1>
      <p id="summary-text"></p>
    </div>
    <div class="sidebar-filters">
      <select id="f-topic"><option value="">Allir flokkar</option></select>
      <select id="f-era">
        <option value="">Bæði</option>
        <option value="esb">ESB-ríkjandi</option>
        <option value="ees">EES-ríkjandi</option>
        <option value="both">Í báðum</option>
      </select>
      <select id="f-sort">
        <option value="size">Stærð</option>
        <option value="esb">ESB-hlutfall</option>
        <option value="ees">EES-hlutfall</option>
      </select>
      <input type="text" id="f-search" placeholder="Leita...">
    </div>
    <div class="cluster-list" id="cluster-list"></div>
  </div>
  <div class="main" id="main">
    <div class="main-empty">Veldu cluster til að skoða</div>
  </div>
</div>

<script id="cluster-data" type="application/json">__CLUSTERS__</script>
<script id="stats-data" type="application/json">__STATS__</script>
<script id="topics-data" type="application/json">__TOPICS__</script>

<script>
const CLUSTERS = JSON.parse(document.getElementById("cluster-data").textContent);
const STATS = JSON.parse(document.getElementById("stats-data").textContent);
const TOPICS = JSON.parse(document.getElementById("topics-data").textContent);

document.getElementById("summary-text").textContent =
  STATS.n_clusters + " clusters, " + STATS.total_clustered + "/" + STATS.total_claims +
  " claims (" + STATS.noise + " noise)";

// Populate topic filter
const topicSet = new Set();
CLUSTERS.forEach(c => Object.keys(c.topics).forEach(t => topicSet.add(t)));
const fTopic = document.getElementById("f-topic");
[...topicSet].sort().forEach(t => {
  const o = document.createElement("option");
  o.value = t; o.textContent = TOPICS[t] || t;
  fTopic.appendChild(o);
});

let selectedCluster = null;

function getFiltered() {
  const topic = document.getElementById("f-topic").value;
  const era = document.getElementById("f-era").value;
  const search = document.getElementById("f-search").value.toLowerCase();
  const sort = document.getElementById("f-sort").value;

  let list = CLUSTERS.filter(c => {
    if (topic && c.top_topic !== topic) return false;
    if (era === "esb" && c.esb_count <= c.ees_count) return false;
    if (era === "ees" && c.ees_count <= c.esb_count) return false;
    if (era === "both" && (c.esb_count === 0 || c.ees_count === 0)) return false;
    if (search && !c.representative.toLowerCase().includes(search)
        && !c.claims.some(cl => cl.summary.toLowerCase().includes(search))) return false;
    return true;
  });

  if (sort === "size") list.sort((a, b) => b.size - a.size);
  else if (sort === "esb") list.sort((a, b) => (b.esb_count / b.size) - (a.esb_count / a.size));
  else if (sort === "ees") list.sort((a, b) => (b.ees_count / b.size) - (a.ees_count / a.size));

  return list;
}

function renderList() {
  const filtered = getFiltered();
  const container = document.getElementById("cluster-list");
  container.innerHTML = filtered.map((c, i) => {
    const esbPct = (c.esb_count / c.size * 100).toFixed(0);
    const eesPct = (c.ees_count / c.size * 100).toFixed(0);
    const sel = selectedCluster === c.cluster_id ? " selected" : "";
    const topTopics = Object.entries(c.topics)
      .sort((a, b) => b[1] - a[1]).slice(0, 2)
      .map(([t, n]) => '<span class="topic-pill">' + (TOPICS[t] || t) + '</span>').join("");

    return '<div class="cluster-item' + sel + '" data-cid="' + c.cluster_id + '">' +
      '<div class="ci-top">' +
        '<span class="ci-rank">' + (i + 1) + '</span>' +
        '<span class="ci-size">' + c.size + '</span>' +
        '<div class="ci-bars">' +
          (c.esb_count ? '<div class="ci-bar-esb" style="width:' + esbPct + '%" title="ESB: ' + c.esb_count + '"></div>' : '') +
          (c.ees_count ? '<div class="ci-bar-ees" style="width:' + eesPct + '%" title="EES: ' + c.ees_count + '"></div>' : '') +
        '</div>' +
        '<span class="era-pill era-esb">' + c.esb_count + '</span>' +
        '<span class="era-pill era-ees">' + c.ees_count + '</span>' +
      '</div>' +
      '<div class="ci-text">' + esc(c.representative) + '</div>' +
      '<div class="ci-meta">' + topTopics + '</div>' +
    '</div>';
  }).join("");

  // Click handlers
  container.querySelectorAll(".cluster-item").forEach(el => {
    el.addEventListener("click", () => {
      selectedCluster = parseInt(el.dataset.cid);
      renderList();
      renderDetail(CLUSTERS.find(c => c.cluster_id === selectedCluster));
    });
  });
}

function renderDetail(c) {
  if (!c) return;
  const main = document.getElementById("main");
  const esbPct = (c.esb_count / c.size * 100).toFixed(0);
  const eesPct = (c.ees_count / c.size * 100).toFixed(0);

  const topicHtml = Object.entries(c.topics)
    .sort((a, b) => b[1] - a[1])
    .map(([t, n]) => '<span class="tp">' + (TOPICS[t] || t) + ' <span class="tp-n">' + n + '</span></span>')
    .join("");

  // Group claims by era, sort by date
  const esbClaims = c.claims.filter(cl => cl.era === "esb").sort((a, b) => (a.date || "").localeCompare(b.date || ""));
  const eesClaims = c.claims.filter(cl => cl.era === "ees").sort((a, b) => (a.date || "").localeCompare(b.date || ""));

  const claimHtml = (claims, eraLabel) => {
    if (!claims.length) return "";
    return '<div class="claims-section"><h3>' + eraLabel + ' (' + claims.length + ')</h3>' +
      claims.map(cl => {
        const quote = cl.quote ? '<div class="cc-quote" onclick="this.classList.toggle(\\'expanded\\')">' + esc(cl.quote) + '</div>' : '';
        const link = cl.url ? '<span class="cc-link"><a href="' + cl.url + '" target="_blank">althingi.is</a></span>' : '';
        return '<div class="claim-card">' +
          '<div class="cc-summary">' + esc(cl.summary) + '</div>' +
          '<div class="cc-meta">' +
            '<span class="cc-speaker">' + esc(cl.speaker) + '</span>' +
            '<span>' + esc(cl.party) + '</span>' +
            '<span>' + cl.date + '</span>' +
            '<span class="topic-pill">' + (TOPICS[cl.topic] || cl.topic) + '</span>' +
            link +
          '</div>' +
          quote +
        '</div>';
      }).join("") +
    '</div>';
  };

  main.innerHTML =
    '<div class="detail-header">' +
      '<h2>Cluster ' + c.cluster_id + '</h2>' +
      '<div class="dh-meta">' + esc(c.representative) + '</div>' +
      '<div class="dh-stats">' +
        '<div class="dh-stat"><div class="val">' + c.size + '</div><div class="lbl">Tilvik</div></div>' +
        '<div class="dh-stat"><div class="val">' + c.esb_count + '</div><div class="lbl">ESB</div></div>' +
        '<div class="dh-stat"><div class="val">' + c.ees_count + '</div><div class="lbl">EES</div></div>' +
        '<div class="dh-stat"><div class="val">' + c.speakers.length + '</div><div class="lbl">Þingmenn</div></div>' +
      '</div>' +
      '<div class="detail-bar">' +
        (c.esb_count ? '<div class="db-esb" style="width:' + esbPct + '%">ESB ' + c.esb_count + '</div>' : '') +
        (c.ees_count ? '<div class="db-ees" style="width:' + eesPct + '%">EES ' + c.ees_count + '</div>' : '') +
      '</div>' +
      '<div class="detail-topics">' + topicHtml + '</div>' +
    '</div>' +
    claimHtml(esbClaims, "ESB (2024–2026)") +
    claimHtml(eesClaims, "EES (1991–1993)");
}

function esc(s) {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Events
["f-topic", "f-era", "f-sort"].forEach(id => {
  document.getElementById(id).addEventListener("change", renderList);
});
document.getElementById("f-search").addEventListener("input", renderList);

renderList();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
