"""Generate an index HTML page linking all meta-claim review pages.

Reads registry.json and generates a dashboard with links to each
meta_review_{ID}.html file.

Usage:
    uv run python scripts/heimildin/generate_meta_index.py
"""

from __future__ import annotations

import json

from config import DELIVERABLES_DIR, TOPIC_LABELS_IS, WORK_DIR

CURATE_DIR = WORK_DIR / "meta_claims"
REGISTRY_FILE = CURATE_DIR / "registry.json"

STATUS_LABELS = {
    "draft": "Drög",
    "candidates": "Umsækjendur",
    "filtered": "Síað",
    "accepted": "Samþykkt",
}


def main() -> None:
    if not REGISTRY_FILE.exists():
        print("No registry.json found.")
        return

    registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))

    # Enrich with per-claim stats
    for entry in registry:
        claim_dir = CURATE_DIR / entry["id"]
        candidates_file = claim_dir / "candidates.json"
        verdicts_file = claim_dir / "agent_verdicts.json"
        review_file = claim_dir / "user_review.json"

        if candidates_file.exists():
            candidates = json.loads(candidates_file.read_text(encoding="utf-8"))
            entry["n_candidates"] = len(candidates)
            entry["n_esb"] = sum(1 for c in candidates if c["era"] == "esb")
            entry["n_ees"] = sum(1 for c in candidates if c["era"] == "ees")

        if verdicts_file.exists():
            verdicts = json.loads(verdicts_file.read_text(encoding="utf-8"))
            entry["n_accept"] = sum(1 for v in verdicts if v["verdict"] == "accept")
            entry["n_reject"] = sum(1 for v in verdicts if v["verdict"] == "reject")

        if review_file.exists():
            review = json.loads(review_file.read_text(encoding="utf-8"))
            entry["n_final"] = review.get("accepted_count", len(review.get("accepted", [])))
            entry["n_excluded"] = len(review.get("excluded_by_user", []))

        # Check if review HTML exists
        html_file = DELIVERABLES_DIR / f"meta_review_{entry['id']}.html"
        entry["has_html"] = html_file.exists()

    data_json = json.dumps(registry, ensure_ascii=False).replace("</", r"<\/")
    topic_json = json.dumps(TOPIC_LABELS_IS, ensure_ascii=False).replace("</", r"<\/")
    status_json = json.dumps(STATUS_LABELS, ensure_ascii=False).replace("</", r"<\/")

    html = HTML.replace("__REGISTRY__", data_json)
    html = html.replace("__TOPICS__", topic_json)
    html = html.replace("__STATUSES__", status_json)

    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    out = DELIVERABLES_DIR / "meta_claims_index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Index: {out} ({len(registry)} claims)")


HTML = """\
<!DOCTYPE html>
<html lang="is">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Heimildin — Meginfullyrðingar</title>
<style>
  :root {
    --bg: #fafafa; --fg: #1a1a1a; --muted: #666; --border: #ddd;
    --accent: #2563eb; --accent-light: #eff6ff;
    --green: #059669; --amber: #d97706;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg); line-height: 1.5; font-size: 14px;
  }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }

  header { padding: 20px 0 16px; border-bottom: 2px solid var(--fg); margin-bottom: 24px; }
  header h1 { font-size: 22px; font-weight: 700; }
  header p { color: var(--muted); font-size: 13px; margin-top: 4px; }

  .summary {
    display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 24px;
  }
  .summary .stat { text-align: center; }
  .summary .val { font-size: 28px; font-weight: 700; }
  .summary .lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; }

  table { width: 100%; border-collapse: collapse; }
  th {
    text-align: left; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; color: var(--muted); padding: 10px 12px;
    border-bottom: 2px solid var(--border);
  }
  td { padding: 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:hover td { background: #f5f5f5; }

  .claim-id { font-family: monospace; font-weight: 700; font-size: 15px; }
  .claim-text { font-size: 14px; max-width: 400px; }
  .topic-tag {
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 11px; background: #f3f4f6; color: var(--muted);
  }
  .status-tag {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 600;
  }
  .status-accepted { background: #dcfce7; color: var(--green); }
  .status-filtered { background: #fef3c7; color: var(--amber); }
  .status-candidates { background: #e0e7ff; color: #4338ca; }
  .status-draft { background: #f3f4f6; color: var(--muted); }

  .counts { font-size: 13px; white-space: nowrap; }
  .counts .n { font-weight: 700; }

  .era-bar {
    display: flex; height: 16px; border-radius: 4px; overflow: hidden;
    background: #eee; min-width: 100px;
  }
  .era-bar-esb { background: #3b82f6; }
  .era-bar-ees { background: #f59e0b; }

  a.review-link {
    display: inline-block; padding: 4px 12px; border-radius: 4px;
    background: var(--accent); color: white; text-decoration: none;
    font-size: 12px; font-weight: 600;
  }
  a.review-link:hover { background: #1d4ed8; }
  .no-link { font-size: 12px; color: var(--muted); }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Heimildin — Meginfullyrðingar</h1>
    <p>Samanburður á ESB-umræðu (2024–2026) og EES-umræðu (1991–1993) á Alþingi</p>
  </header>

  <div class="summary" id="summary"></div>

  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Meginfullyrðing</th>
        <th>Flokkur</th>
        <th>Staða</th>
        <th>Umsækjendur</th>
        <th>ESB / EES</th>
        <th>LLM-síað</th>
        <th>Yfirferð</th>
      </tr>
    </thead>
    <tbody id="claims-body"></tbody>
  </table>
</div>

<script id="registry-data" type="application/json">__REGISTRY__</script>
<script id="topics-data" type="application/json">__TOPICS__</script>
<script id="statuses-data" type="application/json">__STATUSES__</script>

<script>
const REGISTRY = JSON.parse(document.getElementById("registry-data").textContent);
const TOPICS = JSON.parse(document.getElementById("topics-data").textContent);
const STATUSES = JSON.parse(document.getElementById("statuses-data").textContent);

// Summary
const total = REGISTRY.length;
const totalAccept = REGISTRY.reduce((s, e) => s + (e.n_accept || 0), 0);
const totalFinal = REGISTRY.reduce((s, e) => s + (e.n_final || 0), 0);
document.getElementById("summary").innerHTML =
  '<div class="stat"><div class="val">' + total + '</div><div class="lbl">Meginfullyrðingar</div></div>' +
  '<div class="stat"><div class="val">' + totalAccept + '</div><div class="lbl">LLM-samþykkt</div></div>' +
  '<div class="stat"><div class="val">' + totalFinal + '</div><div class="lbl">Lokasafn</div></div>';

// Table
const tbody = document.getElementById("claims-body");
tbody.innerHTML = REGISTRY.map(e => {
  const topic = TOPICS[e.category] || e.category || "?";
  const status = e.status || "?";
  const statusLabel = STATUSES[status] || status;
  const n = e.n_candidates || e.count || 0;
  const esb = e.n_esb || 0;
  const ees = e.n_ees || 0;
  const esbPct = n ? (esb / n * 100).toFixed(0) : 0;
  const eesPct = n ? (ees / n * 100).toFixed(0) : 0;

  const acceptStr = e.n_accept != null
    ? '<span class="n">' + e.n_accept + '</span> / ' + n
    : '—';

  const link = e.has_html
    ? '<a class="review-link" href="meta_review_' + e.id + '.html">Opna yfirferð</a>'
    : '<span class="no-link">Engin yfirferð</span>';

  return '<tr>' +
    '<td class="claim-id">' + e.id + '</td>' +
    '<td class="claim-text">' + (e.text || "?") + '</td>' +
    '<td><span class="topic-tag">' + topic + '</span></td>' +
    '<td><span class="status-tag status-' + status + '">' + statusLabel + '</span></td>' +
    '<td class="counts">' + n + '</td>' +
    '<td><div class="era-bar">' +
      (esb ? '<div class="era-bar-esb" style="width:' + esbPct + '%" title="ESB: ' + esb + '"></div>' : '') +
      (ees ? '<div class="era-bar-ees" style="width:' + eesPct + '%" title="EES: ' + ees + '"></div>' : '') +
    '</div></td>' +
    '<td class="counts">' + acceptStr + '</td>' +
    '<td>' + link + '</td>' +
  '</tr>';
}).join("");
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
