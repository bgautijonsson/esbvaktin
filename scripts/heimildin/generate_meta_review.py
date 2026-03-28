"""Generate a focused review HTML for a single meta-claim's candidate instances.

Reads meta_review_candidates.json (produced by similarity computation) and
generates an interactive HTML for reviewing which instances belong to the claim.

Usage:
    uv run python scripts/heimildin/generate_meta_review.py "Við munum missa fiskinn..."
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from config import DELIVERABLES_DIR, TOPIC_LABELS_IS, WORK_DIR


def generate_review_html(
    claim_dir: Path,
    claim_id: str | None = None,
) -> None:
    """Generate review HTML from a claim folder's artefacts.

    Reads claim.json + candidates.json + optionally agent_verdicts.json
    from claim_dir. Writes HTML to DELIVERABLES_DIR.
    """
    claim_data = json.loads((claim_dir / "claim.json").read_text(encoding="utf-8"))
    meta_text = claim_data["text"]
    cid = claim_id or claim_data.get("id", "")

    candidates = json.loads((claim_dir / "candidates.json").read_text(encoding="utf-8"))

    # Merge agent verdicts if available
    verdicts_file = claim_dir / "agent_verdicts.json"
    if verdicts_file.exists():
        verdicts = {
            v["instance_id"]: v for v in json.loads(verdicts_file.read_text(encoding="utf-8"))
        }
        for c in candidates:
            v = verdicts.get(c["instance_id"], {})
            c["agent_verdict"] = v.get("verdict", "")
            c["agent_reason"] = v.get("reason", "")
        n_accept = sum(1 for c in candidates if c.get("agent_verdict") == "accept")
        print(f"Merged agent verdicts: {n_accept} accept, {len(candidates) - n_accept} reject")

    data_json = json.dumps(candidates, ensure_ascii=False).replace("</", r"<\/")
    meta_json = json.dumps(meta_text, ensure_ascii=False).replace("</", r"<\/")
    topic_json = json.dumps(TOPIC_LABELS_IS, ensure_ascii=False).replace("</", r"<\/")

    cid_json = json.dumps(cid, ensure_ascii=False)

    html = HTML.replace("__CANDIDATES__", data_json)
    html = html.replace("__META_TEXT__", meta_json)
    html = html.replace("__TOPICS__", topic_json)
    html = html.replace("__CLAIM_ID__", cid_json)

    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"meta_review_{cid}.html" if cid else "meta_review.html"
    out = DELIVERABLES_DIR / filename
    out.write_text(html, encoding="utf-8")
    print(f"Review: {out} ({len(candidates)} candidates, {out.stat().st_size // 1024}KB)")


def main() -> None:
    """CLI entry point — supports both legacy (text arg) and folder-based usage."""
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
        # Folder mode: generate_meta_review.py <claim_dir> [claim_id]
        claim_dir = Path(sys.argv[1])
        claim_id = sys.argv[2] if len(sys.argv) > 2 else None
        generate_review_html(claim_dir, claim_id)
        return

    # Legacy mode: generate_meta_review.py "meta claim text..."
    meta_text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""

    candidates_file = WORK_DIR / "meta_review_candidates.json"
    if not candidates_file.exists():
        print("No candidates file. Run similarity computation first.")
        sys.exit(1)

    candidates = json.loads(candidates_file.read_text(encoding="utf-8"))

    verdicts_file = WORK_DIR / "_meta_filter_verdicts.json"
    if verdicts_file.exists():
        verdicts = {
            v["instance_id"]: v for v in json.loads(verdicts_file.read_text(encoding="utf-8"))
        }
        for c in candidates:
            v = verdicts.get(c["instance_id"], {})
            c["agent_verdict"] = v.get("verdict", "")
            c["agent_reason"] = v.get("reason", "")
        n_accept = sum(1 for c in candidates if c.get("agent_verdict") == "accept")
        print(f"Merged agent verdicts: {n_accept} accept, {len(candidates) - n_accept} reject")

    data_json = json.dumps(candidates, ensure_ascii=False).replace("</", r"<\/")
    meta_json = json.dumps(meta_text, ensure_ascii=False).replace("</", r"<\/")
    topic_json = json.dumps(TOPIC_LABELS_IS, ensure_ascii=False).replace("</", r"<\/")

    html = HTML.replace("__CANDIDATES__", data_json)
    html = html.replace("__META_TEXT__", meta_json)
    html = html.replace("__TOPICS__", topic_json)
    html = html.replace("__CLAIM_ID__", json.dumps("legacy"))

    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    out = DELIVERABLES_DIR / "meta_review.html"
    out.write_text(html, encoding="utf-8")
    print(f"Meta review: {out} ({len(candidates)} candidates, {out.stat().st_size // 1024}KB)")


HTML = """\
<!DOCTYPE html>
<html lang="is">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meta-claim Review</title>
<style>
  :root {
    --bg: #fafafa; --fg: #1a1a1a; --muted: #666; --border: #ddd;
    --accent: #2563eb; --accent-light: #eff6ff;
    --green: #059669; --red: #dc2626; --amber: #d97706;
    --high: #dcfce7; --mid: #fef9c3; --low: #fee2e2;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg); line-height: 1.5; font-size: 14px;
  }
  .container { max-width: 1600px; margin: 0 auto; padding: 16px 24px; }

  header { padding: 20px 0 16px; border-bottom: 2px solid var(--fg); margin-bottom: 16px; }
  header h1 { font-size: 18px; font-weight: 700; }
  .meta-text {
    font-size: 16px; font-style: italic; color: #333;
    margin: 8px 0; padding: 10px 16px;
    background: var(--accent-light); border-left: 4px solid var(--accent);
    border-radius: 4px;
  }
  .stats {
    display: flex; gap: 20px; flex-wrap: wrap; margin: 12px 0;
    font-size: 13px; color: var(--muted);
  }
  .stats .val { font-weight: 700; font-size: 18px; color: var(--fg); }

  .controls {
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
    margin: 12px 0; padding: 10px 0; border-bottom: 1px solid var(--border);
  }
  .controls label { font-size: 12px; color: var(--muted); }
  .controls input[type="range"] { width: 200px; }
  .controls select, .controls input[type="text"] {
    padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px;
    font-size: 12px; background: white;
  }
  .controls input[type="text"] { width: 200px; }
  .threshold-val { font-weight: 700; font-size: 14px; min-width: 40px; }
  #showing { font-size: 12px; color: var(--muted); margin-left: auto; }

  .claim-columns {
    display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 8px;
  }
  .claim-col-header {
    font-size: 14px; font-weight: 700; padding: 8px 12px; margin-bottom: 8px;
    border-radius: 6px; text-align: center;
  }
  .claim-col-header-ees { background: #fef3c7; color: #92400e; }
  .claim-col-header-esb { background: #dbeafe; color: #1e40af; }
  .claim-col-count { font-weight: 400; font-size: 12px; }
  .claim-list { margin-top: 0; }

  .claim-card {
    padding: 12px 16px; margin-bottom: 6px;
    border: 1px solid var(--border); border-radius: 6px;
    background: white; transition: border-color 0.15s;
  }
  .claim-card:hover { border-color: #aaa; }
  .claim-card.agent-reject { opacity: 0.45; }
  .claim-card.agent-reject:hover { opacity: 0.85; }
  .claim-card.zone-high { border-left: 4px solid var(--green); }
  .claim-card.zone-mid { border-left: 4px solid var(--amber); }
  .claim-card.zone-low { border-left: 4px solid var(--red); }

  .agent-badge {
    font-size: 10px; font-weight: 700; padding: 1px 6px;
    border-radius: 3px; text-transform: uppercase;
  }
  .agent-accept { background: var(--high); color: var(--green); }
  .agent-reject-badge { background: var(--low); color: var(--red); }
  .agent-reason { font-size: 11px; color: var(--muted); font-style: italic; }

  .claim-card.user-excluded { opacity: 0.3; border-left-color: #999 !important; }
  .claim-card.user-excluded:hover { opacity: 0.7; }
  .claim-card.user-excluded .cc-summary { text-decoration: line-through; }

  .exclude-btn {
    width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--border);
    background: white; cursor: pointer; font-size: 12px; line-height: 18px;
    text-align: center; flex-shrink: 0; transition: all 0.15s;
    color: transparent;
  }
  .exclude-btn:hover { border-color: var(--red); color: var(--red); }
  .claim-card.user-excluded .exclude-btn {
    background: var(--red); border-color: var(--red); color: white;
  }

  .export-bar {
    position: sticky; bottom: 0; background: white; border-top: 2px solid var(--border);
    padding: 10px 24px; display: flex; align-items: center; gap: 16px;
    box-shadow: 0 -2px 8px rgba(0,0,0,0.08); z-index: 10;
  }
  .export-bar .val { font-weight: 700; font-size: 16px; }
  .export-btn {
    padding: 6px 16px; background: var(--accent); color: white; border: none;
    border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 600;
  }
  .export-btn:hover { background: #1d4ed8; }
  .reset-btn {
    padding: 6px 12px; background: white; color: var(--muted); border: 1px solid var(--border);
    border-radius: 4px; cursor: pointer; font-size: 12px;
  }

  .cc-top {
    display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
  }
  .cc-sim {
    font-weight: 700; font-size: 15px; min-width: 50px;
    padding: 2px 6px; border-radius: 4px; text-align: center;
  }
  .cc-sim.high { background: var(--high); color: var(--green); }
  .cc-sim.mid { background: var(--mid); color: var(--amber); }
  .cc-sim.low { background: var(--low); color: var(--red); }

  .cc-era {
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 11px; font-weight: 600; text-transform: uppercase;
  }
  .cc-era-esb { background: #dbeafe; color: #1e40af; }
  .cc-era-ees { background: #fef3c7; color: #92400e; }

  .cc-speaker { font-weight: 600; }
  .cc-party { color: var(--muted); font-size: 12px; }
  .cc-date { color: var(--muted); font-size: 12px; }
  .cc-topic {
    font-size: 11px; color: var(--muted); padding: 0 5px;
    background: #f3f4f6; border-radius: 3px;
  }

  .cc-summary { font-size: 14px; margin: 6px 0; line-height: 1.5; }
  .cc-quote {
    margin-top: 6px; padding: 8px 12px; background: #f9fafb;
    border-left: 3px solid var(--border); font-style: italic;
    font-size: 13px; color: #555; line-height: 1.5;
    max-height: 60px; overflow: hidden; cursor: pointer;
    transition: max-height 0.3s;
  }
  .cc-quote.expanded { max-height: none; }
  .cc-link { font-size: 11px; margin-top: 4px; }
  .cc-link a { color: var(--accent); text-decoration: none; }
  .cc-link a:hover { text-decoration: underline; }

  .sim-bar {
    height: 12px; border-radius: 6px; overflow: hidden;
    background: #eee; margin: 12px 0;
  }
  .sim-bar-inner { height: 100%; transition: width 0.3s; }
  .sim-bar-high { background: var(--green); }
  .sim-bar-mid { background: var(--amber); }
  .sim-bar-low { background: var(--red); }

  .distribution {
    display: flex; height: 40px; gap: 1px; align-items: flex-end;
    margin: 8px 0; padding: 4px 0;
  }
  .dist-bar {
    flex: 1; background: #cbd5e1; border-radius: 2px 2px 0 0;
    min-width: 2px; position: relative;
  }
  .dist-bar.above { background: var(--accent); }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Meta-claim Review</h1>
    <div class="meta-text" id="meta-text"></div>
  </header>

  <div class="stats" id="stats"></div>

  <div class="controls">
    <label>Þröskuldur:</label>
    <input type="range" id="threshold" min="0.40" max="0.70" step="0.01" value="0.55">
    <span class="threshold-val" id="threshold-val">0.55</span>
    <select id="filter-agent">
      <option value="">Öll (LLM)</option>
      <option value="accept" selected>Samþykkt</option>
      <option value="reject">Hafnað</option>
    </select>
    <input type="text" id="filter-text" placeholder="Leita...">
    <span id="showing"></span>
  </div>

  <div class="distribution" id="distribution"></div>

  <div class="export-bar">
    <span><span class="val" id="final-count">0</span> samþykkt</span>
    <span><span id="excluded-count">0</span> útilokuð af notanda</span>
    <button class="export-btn" id="export-btn">Vista JSON</button>
    <button class="reset-btn" id="reset-btn">Hreinsa merkingar</button>
  </div>

  <div class="claim-columns">
    <div>
      <div class="claim-col-header claim-col-header-ees">EES (1991–1993) <span class="claim-col-count" id="ees-count"></span></div>
      <div class="claim-list" id="claim-list-ees"></div>
    </div>
    <div>
      <div class="claim-col-header claim-col-header-esb">ESB (2024–2026) <span class="claim-col-count" id="esb-count"></span></div>
      <div class="claim-list" id="claim-list-esb"></div>
    </div>
  </div>
</div>

<script id="candidates-data" type="application/json">__CANDIDATES__</script>
<script id="meta-text-data" type="application/json">__META_TEXT__</script>
<script id="topics-data" type="application/json">__TOPICS__</script>
<script id="claim-id-data" type="application/json">__CLAIM_ID__</script>

<script>
const CANDIDATES = JSON.parse(document.getElementById("candidates-data").textContent);
const META_TEXT = JSON.parse(document.getElementById("meta-text-data").textContent);
const TOPICS = JSON.parse(document.getElementById("topics-data").textContent);
const CLAIM_ID = JSON.parse(document.getElementById("claim-id-data").textContent) || "";

document.getElementById("meta-text").textContent = META_TEXT;

// User exclusions — persisted in localStorage
const STORAGE_KEY = "meta_review_excluded_" + (CLAIM_ID || META_TEXT.substring(0, 30));
let userExcluded = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"));

function saveExclusions() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...userExcluded]));
}

function toggleExclude(instanceId) {
  if (userExcluded.has(instanceId)) userExcluded.delete(instanceId);
  else userExcluded.add(instanceId);
  saveExclusions();
  render();
}

function simZone(sim, threshold) {
  if (sim >= threshold + 0.05) return "high";
  if (sim >= threshold) return "mid";
  return "low";
}

function esc(s) {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function renderDistribution() {
  const threshold = parseFloat(document.getElementById("threshold").value);
  // Bucket similarities into 30 bins from 0.40 to 0.70
  const bins = new Array(30).fill(0);
  CANDIDATES.forEach(c => {
    const idx = Math.min(29, Math.max(0, Math.floor((c.similarity - 0.40) / 0.01)));
    bins[idx]++;
  });
  const maxBin = Math.max(...bins, 1);

  const container = document.getElementById("distribution");
  container.innerHTML = bins.map((count, i) => {
    const sim = 0.40 + i * 0.01;
    const height = (count / maxBin * 100).toFixed(0);
    const above = sim >= threshold;
    return '<div class="dist-bar' + (above ? ' above' : '') +
      '" style="height:' + Math.max(2, height) + '%" title="' +
      sim.toFixed(2) + ': ' + count + '"></div>';
  }).join("");
}

function renderCard(c, threshold) {
  const zone = simZone(c.similarity, threshold);
  const isReject = c.agent_verdict === "reject";
  const rejectClass = isReject ? " agent-reject" : "";
  const excludedClass = userExcluded.has(c.instance_id) ? " user-excluded" : "";
  const badge = c.agent_verdict
    ? '<span class="agent-badge ' + (isReject ? 'agent-reject-badge' : 'agent-accept') + '">' +
      (isReject ? '\\u2717' : '\\u2713') + '</span>' +
      (c.agent_reason ? '<span class="agent-reason">' + esc(c.agent_reason) + '</span>' : '')
    : '';
  const quote = c.exact_quote
    ? '<div class="cc-quote" onclick="event.stopPropagation();this.classList.toggle(\\'expanded\\')">' + esc(c.exact_quote) + '</div>'
    : '';
  const link = c.speech_url
    ? '<div class="cc-link"><a href="' + c.speech_url + '" target="_blank" onclick="event.stopPropagation()">althingi.is</a></div>'
    : '';

  return '<div class="claim-card zone-' + zone + rejectClass + excludedClass +
    '" data-iid="' + c.instance_id + '" onclick="toggleExclude(\\'' + c.instance_id + '\\')">' +
    '<div class="cc-top">' +
      '<button class="exclude-btn" title="Útiloka/endurheimta">\\u2717</button>' +
      '<span class="cc-sim ' + zone + '">' + c.similarity.toFixed(3) + '</span>' +
      badge +
      '<span class="cc-speaker">' + esc(c.speaker) + '</span>' +
      '<span class="cc-party">(' + esc(c.party) + ')</span>' +
      '<span class="cc-date">' + c.date + '</span>' +
      '<span class="cc-topic">' + (TOPICS[c.topic] || c.topic) + '</span>' +
    '</div>' +
    '<div class="cc-summary">' + esc(c.claim_summary) + '</div>' +
    quote + link +
  '</div>';
}

function render() {
  const threshold = parseFloat(document.getElementById("threshold").value);
  const textFilter = document.getElementById("filter-text").value.toLowerCase();

  document.getElementById("threshold-val").textContent = threshold.toFixed(2);

  const agentFilter = document.getElementById("filter-agent").value;

  let filtered = CANDIDATES.filter(c => {
    if (agentFilter && c.agent_verdict !== agentFilter) return false;
    if (textFilter && !c.claim_summary.toLowerCase().includes(textFilter)
        && !c.speaker.toLowerCase().includes(textFilter)
        && !c.exact_quote.toLowerCase().includes(textFilter)) return false;
    return true;
  });

  // Split by era, then above/below threshold within each
  const eesAll = filtered.filter(c => c.era === "ees");
  const esbAll = filtered.filter(c => c.era === "esb");
  const eesAbove = eesAll.filter(c => c.similarity >= threshold);
  const esbAbove = esbAll.filter(c => c.similarity >= threshold);
  const eesBelow = eesAll.filter(c => c.similarity < threshold);
  const esbBelow = esbAll.filter(c => c.similarity < threshold);

  document.getElementById("stats").innerHTML =
    '<div><span class="val">' + (eesAbove.length + esbAbove.length) + '</span> yfir þröskuldi</div>' +
    '<div><span class="val">' + esbAbove.length + '</span> ESB</div>' +
    '<div><span class="val">' + eesAbove.length + '</span> EES</div>' +
    '<div><span class="val">' + (eesBelow.length + esbBelow.length) + '</span> undir þröskuldi</div>';

  document.getElementById("showing").textContent =
    (eesAbove.length + esbAbove.length) + " yfir / " + filtered.length + " af " + CANDIDATES.length;

  // Render columns — above threshold first, then below
  document.getElementById("ees-count").textContent = "— " + eesAbove.length + " yfir þröskuldi";
  document.getElementById("esb-count").textContent = "— " + esbAbove.length + " yfir þröskuldi";

  document.getElementById("claim-list-ees").innerHTML =
    [...eesAbove, ...eesBelow].map(c => renderCard(c, threshold)).join("");
  document.getElementById("claim-list-esb").innerHTML =
    [...esbAbove, ...esbBelow].map(c => renderCard(c, threshold)).join("");

  renderDistribution();
  updateExportBar();
}

function updateExportBar() {
  const threshold = parseFloat(document.getElementById("threshold").value);
  const agentFilter = document.getElementById("filter-agent").value;

  // Count final accepted: agent-accepted, above threshold, not user-excluded
  const final = CANDIDATES.filter(c => {
    if (agentFilter && c.agent_verdict !== agentFilter) return false;
    if (c.similarity < threshold) return false;
    if (userExcluded.has(c.instance_id)) return false;
    return true;
  });

  document.getElementById("final-count").textContent = final.length;
  document.getElementById("excluded-count").textContent = userExcluded.size;
}

// Export: download JSON with final accepted instance IDs
document.getElementById("export-btn").addEventListener("click", () => {
  const threshold = parseFloat(document.getElementById("threshold").value);
  const agentFilter = document.getElementById("filter-agent").value;

  const accepted = CANDIDATES.filter(c => {
    if (agentFilter && c.agent_verdict !== agentFilter) return false;
    if (c.similarity < threshold) return false;
    if (userExcluded.has(c.instance_id)) return false;
    return true;
  });

  const output = {
    meta_claim: META_TEXT,
    threshold: threshold,
    excluded_by_user: [...userExcluded],
    accepted_count: accepted.length,
    accepted: accepted.map(c => ({
      instance_id: c.instance_id,
      similarity: c.similarity,
      era: c.era,
      speaker: c.speaker,
      claim_summary: c.claim_summary,
    })),
  };

  const blob = new Blob([JSON.stringify(output, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "meta_claim_" + (CLAIM_ID || "unknown") + "_accepted.json";
  a.click();
  URL.revokeObjectURL(url);
});

document.getElementById("reset-btn").addEventListener("click", () => {
  userExcluded.clear();
  saveExclusions();
  render();
});

// Events
document.getElementById("threshold").addEventListener("input", render);
document.getElementById("filter-agent").addEventListener("change", render);
document.getElementById("filter-text").addEventListener("input", render);

render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
