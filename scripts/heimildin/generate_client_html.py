"""Generate client-facing HTML deliverables for Heimildin handoff.

Produces self-contained HTML pages from the canonicalised claim data,
suitable for sharing with Heimildin editorial team.

Output: ~/metill-ehf/Deliverables/Heimildin/handoff/

Pages:
    index.html          Overview + navigation
    tidni.html          D1: Meta-claim frequency table (sortable)
    samanburdur.html    D4: Cross-era comparison (perennial/new/disappeared)
    flokkar.html        D5: Party/speaker analysis
    M*.html             D2: Per-meta-claim detail with instances + speech links

Usage:
    uv run python scripts/heimildin/generate_client_html.py
"""

from __future__ import annotations

import html as html_mod
import json
import sys
from pathlib import Path

from config import DELIVERABLES_DIR, TOPIC_LABELS_IS, TOPIC_PREFIX_MAP, WORK_DIR

HANDOFF_DIR = DELIVERABLES_DIR / "handoff"

STANCE_LABELS = {"pro_eu": "Fylgjandi", "anti_eu": "Andvíg", "neutral": "Hlutlaus"}
STANCE_CSS = {"pro_eu": "pro", "anti_eu": "anti", "neutral": "neutral"}

# (foreground, background) — standard Icelandic party colours
PARTY_COLORS: dict[str, tuple[str, str]] = {
    "Sjálfstæðisflokkur": ("#00205B", "#dce4f0"),
    "Viðreisn": ("#E87000", "#fef0e0"),
    "Miðflokkurinn": ("#005E3A", "#dceee5"),
    "Framsóknarflokkur": ("#00843D", "#dcf0e5"),
    "Samfylkingin": ("#E4002B", "#fce0e5"),
    "Flokkur fólksins": ("#B8860B", "#f8f0d8"),
    "Píratar": ("#660099", "#ece0f5"),
    "Vinstri-grænir": ("#00B140", "#dcf5e5"),
    "Sósíalistaflokkur": ("#8B0000", "#f0dcdc"),
    # Historical (EES era)
    "Alþýðuflokkur": ("#CC0033", "#f5dce2"),
    "Alþýðubandalag": ("#CC3333", "#f5dce2"),
    "Kvennalistinn": ("#9B59B6", "#f0e5f5"),
    "Borgaraflokkur": ("#4A6FA5", "#e0e8f2"),
}

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = """\
:root {
  --bg: #fafafa; --fg: #1a1a1a; --muted: #666; --border: #e0e0e0;
  --accent: #2563eb; --accent-light: #eff6ff;
  --amber: #d97706; --amber-light: #fef3c7;
  --green: #059669; --green-light: #dcfce7;
  --red: #dc2626; --red-light: #fee2e2;
  --grey-light: #f3f4f6;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--fg); line-height: 1.6; font-size: 14px;
}
.container { max-width: 1400px; margin: 0 auto; padding: 20px 24px 60px; }

/* Header */
header { margin-bottom: 28px; }
header h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: var(--muted); font-size: 14px; }
.back-link { margin-bottom: 8px; }
.back-link a { font-size: 13px; color: var(--accent); text-decoration: none; }
.back-link a:hover { text-decoration: underline; }

/* Stat cards (index) */
.stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 28px; }
.stat-card { padding: 20px; border-radius: 8px; border: 1px solid var(--border); }
.stat-esb { background: var(--accent-light); border-color: #bfdbfe; }
.stat-ees { background: var(--amber-light); border-color: #fde68a; }
.stat-label { font-weight: 700; font-size: 14px; margin-bottom: 12px; }
.stat-row { display: flex; gap: 24px; flex-wrap: wrap; }
.stat-val { font-size: 24px; font-weight: 700; display: block; }
.stat-unit { font-size: 12px; color: var(--muted); display: block; }

/* Nav cards (index) */
.card-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 28px; }
.nav-card {
  padding: 20px; border-radius: 8px; border: 1px solid var(--border);
  background: white; text-decoration: none; color: var(--fg); transition: all 0.15s;
}
.nav-card:hover { border-color: var(--accent); box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.nav-card h2 { font-size: 16px; margin-bottom: 6px; }
.nav-card p { font-size: 13px; color: var(--muted); }

.method-note {
  padding: 16px 20px; background: var(--grey-light); border-radius: 8px; font-size: 13px; color: var(--muted);
}
.method-note h3 { font-size: 13px; font-weight: 700; margin-bottom: 4px; color: var(--fg); }

/* Tables */
table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
th {
  text-align: left; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.5px; color: var(--muted); padding: 10px 12px;
  border-bottom: 2px solid var(--border); white-space: nowrap;
}
th[data-sort] { cursor: pointer; user-select: none; }
th[data-sort]:hover { color: var(--fg); }
th[data-sort]::after { content: " \\2195"; font-size: 10px; opacity: 0.4; }
th[data-dir="asc"]::after { content: " \\2191"; opacity: 1; }
th[data-dir="desc"]::after { content: " \\2193"; opacity: 1; }
td { padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:hover td { background: #f5f5f5; }
td a { color: var(--accent); text-decoration: none; }
td a:hover { text-decoration: underline; }
.table-footer { font-size: 13px; color: var(--muted); margin-bottom: 8px; }
.speakers { font-size: 12px; color: var(--muted); max-width: 300px; }
td.note { font-size: 12px; color: var(--muted); max-width: 320px; }

/* Badges */
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; white-space: nowrap;
}
.badge-esb { background: var(--accent-light); color: #1e40af; }
.badge-ees { background: var(--amber-light); color: #92400e; }
.badge-pro { background: var(--green-light); color: var(--green); }
.badge-anti { background: var(--red-light); color: var(--red); }
.badge-neutral { background: var(--grey-light); color: var(--muted); }
.badge-topic { background: var(--grey-light); color: var(--muted); }

/* Summary bar */
.summary-bar {
  display: flex; gap: 24px; flex-wrap: wrap;
  padding: 14px 20px; background: var(--grey-light); border-radius: 8px; margin-bottom: 28px; font-size: 14px;
}

/* Sections */
section { margin-bottom: 36px; }
section h2 { font-size: 18px; font-weight: 700; margin-bottom: 6px; }
section h3 { font-size: 15px; font-weight: 700; margin: 20px 0 10px; }
.section-desc { font-size: 13px; color: var(--muted); margin-bottom: 16px; }

/* Detail page stats */
.detail-stats { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.muted { color: var(--muted); font-size: 13px; }

/* Era grid (detail pages) */
.era-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.era-col { min-width: 0; }
.era-header {
  font-size: 14px; font-weight: 700; padding: 10px 14px; margin-bottom: 12px;
  border-radius: 6px; text-align: center;
}
.era-header-esb { background: #dbeafe; color: #1e40af; }
.era-header-ees { background: #fef3c7; color: #92400e; }
.era-count { font-weight: 400; font-size: 12px; }
.no-instances { padding: 20px; color: var(--muted); font-style: italic; text-align: center; }

/* Canonical claim groups */
.canonical-group { margin-bottom: 20px; }
.canonical-header {
  font-size: 13px; font-weight: 600; padding: 8px 12px;
  background: var(--grey-light); border-radius: 6px; margin-bottom: 8px;
}
.canonical-id {
  font-family: monospace; font-size: 11px; font-weight: 700;
  padding: 1px 6px; background: white; border-radius: 3px;
  border: 1px solid var(--border); margin-right: 6px;
}

/* Instance cards */
.instance-card {
  padding: 12px 14px; margin-bottom: 6px;
  border: 1px solid var(--border); border-radius: 6px; background: white;
}
.instance-header {
  display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 6px;
}
.instance-date { font-size: 12px; color: var(--muted); margin-left: auto; }
blockquote {
  font-size: 13px; color: #444; font-style: italic;
  padding: 8px 14px; margin: 6px 0;
  border-left: 3px solid var(--border); background: #fafafa;
  border-radius: 0 4px 4px 0;
}
.speech-link {
  font-size: 12px; color: var(--accent); text-decoration: none; display: inline-block; margin-top: 4px;
}
.speech-link:hover { text-decoration: underline; }

/* Speaker detail */
.speaker-detail { margin-bottom: 16px; }
.speaker-detail h4 { font-size: 14px; margin-bottom: 4px; }
.speaker-detail ul { list-style: none; padding-left: 0; }
.speaker-detail li { font-size: 13px; padding: 2px 0; }
.claim-count {
  font-weight: 700; font-size: 12px; color: var(--accent);
  display: inline-block; min-width: 28px;
}

/* Clickable rows */
tr[data-target] { cursor: pointer; transition: background 0.15s; }
tr[data-target]:hover td { background: var(--accent-light); }
tr.active-row td { background: var(--accent-light); font-weight: 600; }

/* Detail sections (single-page) */
.detail-section {
  margin: 32px 0; padding: 24px; border: 1px solid var(--border);
  border-radius: 8px; background: white;
}
.detail-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 16px; margin-bottom: 12px;
}
.detail-header h2 { font-size: 17px; font-weight: 700; flex: 1; }
.close-detail {
  padding: 4px 12px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--grey-light); color: var(--muted); font-size: 12px;
  cursor: pointer; white-space: nowrap; flex-shrink: 0;
}
.close-detail:hover { background: var(--border); color: var(--fg); }

@media (max-width: 900px) {
  .stat-grid, .era-grid { grid-template-columns: 1fr; }
  .card-grid { grid-template-columns: 1fr; }
}
"""

# ---------------------------------------------------------------------------
# Sort JS (vanilla, no deps)
# ---------------------------------------------------------------------------

SORT_JS = """\
document.querySelectorAll('th[data-sort]').forEach(th => {
  th.addEventListener('click', () => {
    const table = th.closest('table');
    const tbody = table.querySelector('tbody');
    const rows = [...tbody.rows];
    const col = th.cellIndex;
    const type = th.dataset.sort;
    const asc = th.dataset.dir !== 'asc';
    table.querySelectorAll('th').forEach(h => delete h.dataset.dir);
    th.dataset.dir = asc ? 'asc' : 'desc';
    rows.sort((a, b) => {
      let va = a.cells[col].dataset.val || a.cells[col].textContent.trim();
      let vb = b.cells[col].dataset.val || b.cells[col].textContent.trim();
      if (type === 'num') { va = parseFloat(va) || 0; vb = parseFloat(vb) || 0; }
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
    rows.forEach(r => tbody.appendChild(r));
  });
});
"""


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def esc(text: str) -> str:
    return html_mod.escape(str(text))


def wrap_page(title: str, body: str, extra_js: str = "") -> str:
    js_block = f"<script>{extra_js}</script>" if extra_js else ""
    return f"""<!DOCTYPE html>
<html lang="is">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
{body}
</div>
{js_block}
</body>
</html>"""


def topic_badge(topic_or_category: str) -> str:
    label = TOPIC_LABELS_IS.get(topic_or_category, topic_or_category)
    return f'<span class="badge badge-topic">{esc(label)}</span>'


def stance_badge(stance: str) -> str:
    label = STANCE_LABELS.get(stance, stance)
    cls = STANCE_CSS.get(stance, "neutral")
    return f'<span class="badge badge-{cls}">{esc(label)}</span>'


def party_badge(party: str) -> str:
    fg, bg = PARTY_COLORS.get(party, ("#666", "#f3f4f6"))
    return f'<span class="badge" style="background:{bg};color:{fg}">{esc(party)}</span>'


def _topic_from_id(canonical_id: str) -> str:
    prefix = canonical_id.split("-")[0] if "-" in canonical_id else "OTH"
    return TOPIC_PREFIX_MAP.get(prefix, "other")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> list | dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_all() -> dict:
    """Load all data needed for HTML generation."""
    data: dict = {}

    # Stats
    for era in ["esb", "ees"]:
        sf = WORK_DIR / f"{era}_stats.json"
        data[f"{era}_stats"] = _load_json(sf) if sf.exists() else {}

    # Canonical claims
    for era in ["esb", "ees"]:
        cf = WORK_DIR / f"{era}_canonical.json"
        data[f"{era}_canonical"] = _load_json(cf) if cf.exists() else []

    # Enriched instances
    for era in ["esb", "ees"]:
        ef = WORK_DIR / f"{era}_claims_enriched.json"
        data[f"{era}_instances"] = _load_json(ef) if ef.exists() else []

    # Canonical text lookup
    ct: dict[str, str] = {}
    for cc in data["esb_canonical"] + data["ees_canonical"]:
        ct[cc["canonical_id"]] = cc.get("canonical_text", "")
    data["canonical_text"] = ct

    # Canonical claim lookup (for cross-era counts)
    data["esb_cc"] = {cc["canonical_id"]: cc for cc in data["esb_canonical"]}
    data["ees_cc"] = {cc["canonical_id"]: cc for cc in data["ees_canonical"]}

    # Meta-claims from registry
    registry_file = WORK_DIR / "meta_claims" / "registry.json"
    if registry_file.exists():
        registry = _load_json(registry_file)
        accepted = [e for e in registry if e.get("status") == "accepted"]
        data["meta_claims"] = accepted

        # instance_id → meta_claim_id
        id_to_meta: dict[str, str] = {}
        for entry in accepted:
            review_file = WORK_DIR / "meta_claims" / entry["id"] / "user_review.json"
            if review_file.exists():
                review = _load_json(review_file)
                for inst in review.get("accepted", []):
                    id_to_meta[inst["instance_id"]] = entry["id"]
        data["id_to_meta"] = id_to_meta

        # Instances grouped by meta-claim
        meta_instances: dict[str, list[dict]] = {}
        for era in ["esb", "ees"]:
            for inst in data[f"{era}_instances"]:
                iid = inst.get("instance_id", "")
                mid = id_to_meta.get(iid)
                if mid:
                    inst_copy = dict(inst)
                    inst_copy["era"] = era
                    meta_instances.setdefault(mid, []).append(inst_copy)
        data["meta_instances"] = meta_instances
    else:
        data["meta_claims"] = []
        data["id_to_meta"] = {}
        data["meta_instances"] = {}

    # Cross-era themes
    themes_file = WORK_DIR / "canonicalise" / "cross_era_themes.json"
    data["cross_era_themes"] = _load_json(themes_file) if themes_file.exists() else []

    return data


# ---------------------------------------------------------------------------
# Page: Index
# ---------------------------------------------------------------------------


def generate_index(data: dict) -> str:
    esb_s = data["esb_stats"]
    ees_s = data["ees_stats"]
    n_meta = len(data["meta_claims"])
    n_themes = len(data["cross_era_themes"])

    total_instances = sum(len(v) for v in data["meta_instances"].values())

    body = f"""\
<header>
  <h1>Greining á þingumræðum um ESB og EES</h1>
  <p class="subtitle">Samanburður á röksemdafærslum í Alþingisumræðum 1991–1993 og 2024–2026</p>
</header>

<div class="stat-grid">
  <div class="stat-card stat-esb">
    <div class="stat-label">ESB-umræða (2024–2026)</div>
    <div class="stat-row">
      <div><span class="stat-val">{esb_s.get("speeches", "?")}</span><span class="stat-unit">ræður</span></div>
      <div><span class="stat-val">{esb_s.get("total_words", 0):,}</span><span class="stat-unit">orð</span></div>
      <div><span class="stat-val">{esb_s.get("unique_speakers", "?")}</span><span class="stat-unit">þingmenn</span></div>
      <div><span class="stat-val">{esb_s.get("total_claims", "?")}</span><span class="stat-unit">tilvik</span></div>
    </div>
  </div>
  <div class="stat-card stat-ees">
    <div class="stat-label">EES-umræða (1991–1993)</div>
    <div class="stat-row">
      <div><span class="stat-val">{ees_s.get("speeches", "?")}</span><span class="stat-unit">ræður</span></div>
      <div><span class="stat-val">{ees_s.get("total_words", 0):,}</span><span class="stat-unit">orð</span></div>
      <div><span class="stat-val">{ees_s.get("unique_speakers", "?")}</span><span class="stat-unit">þingmenn</span></div>
      <div><span class="stat-val">{ees_s.get("total_claims", "?")}</span><span class="stat-unit">tilvik</span></div>
    </div>
  </div>
</div>

<div class="card-grid">
  <a href="tidni.html" class="nav-card">
    <h2>Tíðni meginfullyrðinga</h2>
    <p>{n_meta} meginfullyrðingar greindar — {total_instances} tilvik samtals</p>
  </a>
  <a href="samanburdur.html" class="nav-card">
    <h2>Samanburður milli tímabila</h2>
    <p>{n_themes} röksemdafærslur bornar saman yfir 30 ár</p>
  </a>
  <a href="flokkar.html" class="nav-card">
    <h2>Flokka- og þingmannagreining</h2>
    <p>Hvernig skiptast röksemdafærslur eftir flokkum og þingmönnum</p>
  </a>
</div>

<div class="method-note">
  <h3>Aðferð</h3>
  <p>Ræður voru sóttar úr gagnagrunnsskrám Alþingis. Fullyrðingar voru dregnar
  úr texta ræðnanna, flokkaðar eftir efni og afstöðu, og bornar saman milli
  tímabila. Allar tilvísanir vísa á upprunalegan ræðutexta á althingi.is.</p>
</div>"""

    return wrap_page("Greining á þingumræðum um ESB og EES", body)


# ---------------------------------------------------------------------------
# Page: Frequency (D1)
# ---------------------------------------------------------------------------


def generate_frequency(data: dict) -> str:
    meta_claims = data["meta_claims"]
    meta_instances = data["meta_instances"]
    esb_stats = data["esb_stats"]
    ees_stats = data["ees_stats"]

    rows = []
    for mc in meta_claims:
        mid = mc["id"]
        instances = meta_instances.get(mid, [])
        esb_count = sum(1 for i in instances if i.get("era") == "esb")
        ees_count = sum(1 for i in instances if i.get("era") == "ees")
        total = esb_count + ees_count
        speakers = sorted({i.get("speaker", "?") for i in instances})
        rows.append(
            {
                "id": mid,
                "text": mc["text"],
                "category": mc.get("category", "other"),
                "esb": esb_count,
                "ees": ees_count,
                "total": total,
                "speakers": speakers,
            }
        )

    rows.sort(key=lambda r: -r["total"])
    total_assigned = sum(r["total"] for r in rows)

    table_rows = []
    for i, r in enumerate(rows, 1):
        esb_str = f"{r['esb']}×" if r["esb"] else "—"
        ees_str = f"{r['ees']}×" if r["ees"] else "—"
        table_rows.append(
            f"<tr>"
            f'<td data-val="{i}">{i}</td>'
            f'<td><a href="{r["id"]}.html">{esc(r["text"])}</a></td>'
            f"<td>{topic_badge(r['category'])}</td>"
            f'<td data-val="{r["esb"]}">{esb_str}</td>'
            f'<td data-val="{r["ees"]}">{ees_str}</td>'
            f'<td data-val="{r["total"]}"><strong>{r["total"]}×</strong></td>'
            f"</tr>"
        )

    body = f"""\
<header>
  <h1>Tíðni meginfullyrðinga</h1>
  <p class="subtitle">Hver lína er ein meginfullyrðing — röksemd sem einn eða fleiri
  þingmenn settu fram í umræðum. Smelltu á línu til að sjá öll tilvik.</p>
</header>

<table>
<thead>
<tr>
  <th data-sort="num">#</th>
  <th data-sort="text">Meginfullyrðing</th>
  <th>Efnisflokkur</th>
  <th data-sort="num">ESB (2026)</th>
  <th data-sort="num">EES (1991–93)</th>
  <th data-sort="num">Samtals</th>
</tr>
</thead>
<tbody>
{"".join(table_rows)}
</tbody>
</table>

<p class="table-footer">{total_assigned} fullyrðingatilvik í {len(rows)} meginfullyrðingum.</p>
<p class="table-footer">
ESB: {esb_stats.get("speeches", "?")} ræður, {esb_stats.get("total_words", 0):,} orð,
{esb_stats.get("unique_speakers", "?")} þingmenn.
EES: {ees_stats.get("speeches", "?")} ræður, {ees_stats.get("total_words", 0):,} orð,
{ees_stats.get("unique_speakers", "?")} þingmenn.
</p>"""

    return wrap_page("Tíðni meginfullyrðinga", body, SORT_JS)


# ---------------------------------------------------------------------------
# Page: Cross-era (D4)
# ---------------------------------------------------------------------------


def generate_crossera(data: dict) -> str:
    themes = data["cross_era_themes"]
    esb_cc = data["esb_cc"]
    ees_cc = data["ees_cc"]
    esb_words = data["esb_stats"].get("total_words", 0)
    ees_words = data["ees_stats"].get("total_words", 0)

    type_defs = [
        (
            "perennial",
            "Röksemdafærslur sem lifðu af 30 ár",
            "Þessar röksemdafærslur birtast í báðum umræðum — frá EES-samningnum "
            "1991–1993 og ESB-þjóðaratkvæðagreiðslunni 2026.",
        ),
        (
            "new_2026",
            "Nýjar röksemdafærslur 2026",
            "Þessar röksemdafærslur birtast aðeins í ESB-umræðunni 2026 — "
            "þær áttu sér enga hliðstæðu í EES-umræðunni.",
        ),
        (
            "disappeared",
            "Röksemdafærslur sem hurfu",
            "Þessar röksemdafærslur voru áberandi í EES-umræðunni 1991–1993 "
            "en birtast ekki í ESB-umræðunni 2026.",
        ),
    ]

    sections_html = []
    counts: dict[str, int] = {}

    for type_key, type_label, type_desc in type_defs:
        type_themes = [t for t in themes if t.get("type") == type_key]
        counts[type_key] = len(type_themes)
        if not type_themes:
            continue

        def _total(t: dict) -> int:
            esb_n = sum(esb_cc[i]["instance_count"] for i in t.get("esb_ids", []) if i in esb_cc)
            ees_n = sum(ees_cc[i]["instance_count"] for i in t.get("ees_ids", []) if i in ees_cc)
            return esb_n + ees_n

        type_themes.sort(key=_total, reverse=True)

        table_rows = []
        for t in type_themes:
            theme = t.get("theme", "?")
            note = t.get("note", "")
            esb_n = sum(esb_cc[i]["instance_count"] for i in t.get("esb_ids", []) if i in esb_cc)
            ees_n = sum(ees_cc[i]["instance_count"] for i in t.get("ees_ids", []) if i in ees_cc)
            esb_str = f"{esb_n}×" if esb_n else "—"
            ees_str = f"{ees_n}×" if ees_n else "—"
            esb_rate = f"{esb_n * 10000 / esb_words:.1f}" if esb_n and esb_words else "—"
            ees_rate = f"{ees_n * 10000 / ees_words:.1f}" if ees_n and ees_words else "—"
            esb_rate_val = f"{esb_n * 10000 / esb_words:.1f}" if esb_n and esb_words else "0"
            ees_rate_val = f"{ees_n * 10000 / ees_words:.1f}" if ees_n and ees_words else "0"

            table_rows.append(
                f"<tr>"
                f"<td>{esc(theme)}</td>"
                f'<td data-val="{esb_n}">{esb_str}</td>'
                f'<td data-val="{esb_rate_val}">{esb_rate}</td>'
                f'<td data-val="{ees_n}">{ees_str}</td>'
                f'<td data-val="{ees_rate_val}">{ees_rate}</td>'
                f'<td class="note">{esc(note)}</td>'
                f"</tr>"
            )

        sections_html.append(
            f"<section>"
            f"<h2>{esc(type_label)}</h2>"
            f'<p class="section-desc">{esc(type_desc)}</p>'
            f"<table>"
            f"<thead><tr>"
            f'<th data-sort="text">Meginfullyrðing</th>'
            f'<th data-sort="num">ESB (2026)</th>'
            f'<th data-sort="num">ESB/10k</th>'
            f'<th data-sort="num">EES (1991–93)</th>'
            f'<th data-sort="num">EES/10k</th>'
            f"<th>Athugasemd</th>"
            f"</tr></thead>"
            f"<tbody>{''.join(table_rows)}</tbody>"
            f"</table>"
            f"</section>"
        )

    body = f"""\
<header>
  <h1>Samanburður á ESB- og EES-umræðu á Alþingi</h1>
  <p class="subtitle">Hvaða röksemdafærslur lifðu af 30 ár? Hverjar hurfu? Hverjar eru nýjar?</p>
</header>

<div class="summary-bar">
  <span><strong>{counts.get("perennial", 0)}</strong> röksemdafærslur birtast í báðum umræðum</span>
  <span><strong>{counts.get("new_2026", 0)}</strong> röksemdafærslur eru nýjar 2026</span>
  <span><strong>{counts.get("disappeared", 0)}</strong> röksemdafærslur hurfu frá 1993</span>
</div>

{"".join(sections_html)}"""

    return wrap_page("Samanburður milli tímabila", body, SORT_JS)


# ---------------------------------------------------------------------------
# Page: Party/Speaker (D5)
# ---------------------------------------------------------------------------


def generate_party_speaker(data: dict) -> str:
    eras_html = []

    for era, era_label in [("esb", "ESB (2024–2026)"), ("ees", "EES (1991–1993)")]:
        instances = data[f"{era}_instances"]
        canonical = data[f"{era}_canonical"]
        canon_text = {cc["canonical_id"]: cc.get("canonical_text", "") for cc in canonical}

        # Party stats
        party_stats: dict[str, dict] = {}
        for inst in instances:
            party = inst.get("party", "?")
            stance = inst.get("stance", "neutral")
            ps = party_stats.setdefault(
                party,
                {"pro_eu": 0, "anti_eu": 0, "neutral": 0, "total": 0, "speakers": set()},
            )
            ps[stance] = ps.get(stance, 0) + 1
            ps["total"] += 1
            ps["speakers"].add(inst.get("speaker", "?"))

        party_rows = []
        for party, ps in sorted(party_stats.items(), key=lambda x: -x[1]["total"]):
            n_spk = len(ps["speakers"])
            pct = f"{ps['pro_eu'] / ps['total'] * 100:.0f}%" if ps["total"] else "—"
            party_rows.append(
                f"<tr>"
                f"<td><strong>{esc(party)}</strong></td>"
                f'<td data-val="{n_spk}">{n_spk}</td>'
                f'<td data-val="{ps["total"]}">{ps["total"]}</td>'
                f'<td data-val="{ps["pro_eu"]}">{ps["pro_eu"]}</td>'
                f'<td data-val="{ps["anti_eu"]}">{ps["anti_eu"]}</td>'
                f'<td data-val="{ps["neutral"]}">{ps["neutral"]}</td>'
                f'<td data-val="{ps["pro_eu"] / ps["total"] * 100 if ps["total"] else 0:.0f}">{pct}</td>'
                f"</tr>"
            )

        # Speaker stats
        speaker_stats: dict[str, dict] = {}
        for inst in instances:
            speaker = inst.get("speaker", "?")
            party = inst.get("party", "?")
            stance = inst.get("stance", "neutral")
            ss = speaker_stats.setdefault(
                speaker,
                {
                    "party": party,
                    "pro_eu": 0,
                    "anti_eu": 0,
                    "neutral": 0,
                    "total": 0,
                    "top_claims": {},
                },
            )
            ss[stance] = ss.get(stance, 0) + 1
            ss["total"] += 1
            cid = inst.get("canonical_id", "?")
            ss["top_claims"][cid] = ss["top_claims"].get(cid, 0) + 1

        speaker_rows = []
        for speaker, ss in sorted(speaker_stats.items(), key=lambda x: -x[1]["total"]):
            speaker_rows.append(
                f"<tr>"
                f"<td><strong>{esc(speaker)}</strong></td>"
                f"<td>{esc(ss['party'])}</td>"
                f'<td data-val="{ss["total"]}">{ss["total"]}</td>'
                f'<td data-val="{ss["pro_eu"]}">{ss["pro_eu"]}</td>'
                f'<td data-val="{ss["anti_eu"]}">{ss["anti_eu"]}</td>'
                f'<td data-val="{ss["neutral"]}">{ss["neutral"]}</td>'
                f"</tr>"
            )

        # Top claims per speaker
        speaker_details = []
        for speaker, ss in sorted(speaker_stats.items(), key=lambda x: -x[1]["total"]):
            if ss["total"] < 3:
                continue
            top = sorted(ss["top_claims"].items(), key=lambda x: -x[1])[:5]
            claims_li = "\n".join(
                f'<li><span class="claim-count">{count}×</span> '
                f"{esc(canon_text.get(cid, cid)[:80])}</li>"
                for cid, count in top
            )
            speaker_details.append(
                f'<div class="speaker-detail">'
                f"<h4>{esc(speaker)} "
                f"{party_badge(ss['party'])} "
                f'<span class="muted">({ss["total"]} fullyrðingar)</span></h4>'
                f"<ul>{claims_li}</ul>"
                f"</div>"
            )

        eras_html.append(
            f"<section>"
            f"<h2>{esc(era_label)}</h2>"
            f"<h3>Flokkar — afstaða</h3>"
            f"<table><thead><tr>"
            f'<th data-sort="text">Flokkur</th>'
            f'<th data-sort="num">Þingmenn</th>'
            f'<th data-sort="num">Fullyrðingar</th>'
            f'<th data-sort="num">Fylgjandi</th>'
            f'<th data-sort="num">Andvíg</th>'
            f'<th data-sort="num">Hlutlaus</th>'
            f'<th data-sort="num">% fylgjandi</th>'
            f"</tr></thead><tbody>{''.join(party_rows)}</tbody></table>"
            f"<h3>Þingmenn — yfirlit</h3>"
            f"<table><thead><tr>"
            f'<th data-sort="text">Þingmaður</th>'
            f'<th data-sort="text">Flokkur</th>'
            f'<th data-sort="num">Fullyrðingar</th>'
            f'<th data-sort="num">Fylgjandi</th>'
            f'<th data-sort="num">Andvíg</th>'
            f'<th data-sort="num">Hlutlaus</th>'
            f"</tr></thead><tbody>{''.join(speaker_rows)}</tbody></table>"
            f"<h3>Þingmenn — helstu röksemdafærslur</h3>"
            f"{''.join(speaker_details)}"
            f"</section>"
        )

    body = f"""\
<header>
  <h1>Flokka- og þingmannagreining</h1>
  <p class="subtitle">Hvernig skiptast röksemdafærslur eftir flokkum og þingmönnum?</p>
</header>

{"".join(eras_html)}"""

    return wrap_page("Flokka- og þingmannagreining", body, SORT_JS)


# ---------------------------------------------------------------------------
# Page: Meta-claim detail (one per accepted meta-claim)
# ---------------------------------------------------------------------------


def _render_era_column(
    era_instances: list[dict],
    era_label: str,
    era_css: str,
) -> str:
    if not era_instances:
        return (
            f'<div class="era-col">'
            f'<div class="era-header era-header-{era_css}">'
            f'{era_label} <span class="era-count">0 tilvik</span></div>'
            f'<p class="no-instances">Engin tilvik í þessu tímabili.</p>'
            f"</div>"
        )

    sorted_instances = sorted(era_instances, key=lambda i: i.get("date", ""))

    cards = []
    for inst in sorted_instances:
        speaker = inst.get("speaker", "?")
        party = inst.get("party", "?")
        date = inst.get("date", "?")
        quote = inst.get("exact_quote", "").replace("\n", " ")
        url = inst.get("speech_url", "")

        link_html = (
            f'<a href="{esc(url)}" target="_blank" class="speech-link">Ræða á althingi.is →</a>'
            if url
            else ""
        )
        quote_html = f"<blockquote>{esc(quote)}</blockquote>" if quote else ""

        cards.append(
            f'<div class="instance-card">'
            f'<div class="instance-header">'
            f"<strong>{esc(speaker)}</strong> "
            f"{party_badge(party)} "
            f'<span class="instance-date">{esc(date)}</span>'
            f"</div>"
            f"{quote_html}"
            f"{link_html}"
            f"</div>"
        )

    return (
        f'<div class="era-col">'
        f'<div class="era-header era-header-{era_css}">'
        f'{era_label} <span class="era-count">{len(era_instances)} tilvik</span></div>'
        f"{''.join(cards)}"
        f"</div>"
    )


def generate_detail_page(meta_claim: dict, data: dict) -> str:
    mid = meta_claim["id"]
    text = meta_claim["text"]
    category = meta_claim.get("category", "other")
    instances = data["meta_instances"].get(mid, [])

    esb_inst = [i for i in instances if i.get("era") == "esb"]
    ees_inst = [i for i in instances if i.get("era") == "ees"]
    speakers = sorted({i.get("speaker", "?") for i in instances})

    esb_col = _render_era_column(esb_inst, "ESB (2024–2026)", "esb")
    ees_col = _render_era_column(ees_inst, "EES (1991–1993)", "ees")

    body = f"""\
<header>
  <div class="back-link"><a href="index.html">← Tíðnitafla</a></div>
  <h1>{esc(text)}</h1>
  <div class="detail-stats">
    {topic_badge(category)}
    <span class="badge badge-esb">ESB: {len(esb_inst)}</span>
    <span class="badge badge-ees">EES: {len(ees_inst)}</span>
    <span class="muted">Samtals: {len(instances)} tilvik · {len(speakers)} þingmenn</span>
  </div>
</header>

<div class="era-grid">
{esb_col}
{ees_col}
</div>"""

    return wrap_page(f"{mid}: {text[:60]}", body)


# ---------------------------------------------------------------------------
# Single-page combined view
# ---------------------------------------------------------------------------

TOGGLE_JS = """\
document.querySelectorAll('tr[data-target]').forEach(tr => {
  tr.style.cursor = 'pointer';
  tr.addEventListener('click', () => {
    const id = tr.dataset.target;
    const section = document.getElementById(id);
    const wasOpen = !section.hidden;
    document.querySelectorAll('.detail-section').forEach(s => s.hidden = true);
    document.querySelectorAll('tr[data-target]').forEach(r => r.classList.remove('active-row'));
    if (!wasOpen) {
      section.hidden = false;
      tr.classList.add('active-row');
      section.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
  });
  // close button
});
document.querySelectorAll('.close-detail').forEach(btn => {
  btn.addEventListener('click', () => {
    const section = btn.closest('.detail-section');
    section.hidden = true;
    const mid = section.id;
    const tr = document.querySelector('tr[data-target="' + mid + '"]');
    if (tr) { tr.classList.remove('active-row'); tr.scrollIntoView({behavior: 'smooth', block: 'center'}); }
  });
});
"""


def generate_single_page(data: dict) -> str:
    """Single HTML file: frequency table + expandable detail sections."""
    meta_claims = data["meta_claims"]
    meta_instances = data["meta_instances"]

    # Build frequency rows
    rows = []
    for mc in meta_claims:
        mid = mc["id"]
        instances = meta_instances.get(mid, [])
        esb_count = sum(1 for i in instances if i.get("era") == "esb")
        ees_count = sum(1 for i in instances if i.get("era") == "ees")
        total = esb_count + ees_count
        rows.append(
            {
                "id": mid,
                "text": mc["text"],
                "category": mc.get("category", "other"),
                "esb": esb_count,
                "ees": ees_count,
                "total": total,
            }
        )
    rows.sort(key=lambda r: -r["total"])
    total_assigned = sum(r["total"] for r in rows)

    table_rows = []
    for i, r in enumerate(rows, 1):
        esb_str = f"{r['esb']}×" if r["esb"] else "—"
        ees_str = f"{r['ees']}×" if r["ees"] else "—"
        table_rows.append(
            f'<tr data-target="{r["id"]}">'
            f'<td data-val="{i}">{i}</td>'
            f"<td>{esc(r['text'])}</td>"
            f'<td data-val="{r["esb"]}">{esb_str}</td>'
            f'<td data-val="{r["ees"]}">{ees_str}</td>'
            f'<td data-val="{r["total"]}"><strong>{r["total"]}×</strong></td>'
            f"</tr>"
        )

    # Build detail sections
    detail_sections = []
    mc_lookup = {mc["id"]: mc for mc in meta_claims}
    for r in rows:
        mid = r["id"]
        mc = mc_lookup[mid]
        instances = meta_instances.get(mid, [])
        esb_inst = [i for i in instances if i.get("era") == "esb"]
        ees_inst = [i for i in instances if i.get("era") == "ees"]
        speakers = sorted({i.get("speaker", "?") for i in instances})

        esb_col = _render_era_column(esb_inst, "ESB (2024–2026)", "esb")
        ees_col = _render_era_column(ees_inst, "EES (1991–1993)", "ees")

        detail_sections.append(
            f'<div id="{mid}" class="detail-section" hidden>'
            f'<div class="detail-header">'
            f"<h2>{esc(r['text'])}</h2>"
            f'<button class="close-detail">✕ Loka</button>'
            f"</div>"
            f'<div class="detail-stats">'
            f"{topic_badge(mc.get('category', 'other'))} "
            f'<span class="badge badge-esb">ESB: {len(esb_inst)}</span> '
            f'<span class="badge badge-ees">EES: {len(ees_inst)}</span> '
            f'<span class="muted">Samtals: {len(instances)} tilvik · '
            f"{len(speakers)} þingmenn</span>"
            f"</div>"
            f'<div class="era-grid">{esb_col}{ees_col}</div>'
            f"</div>"
        )

    body = f"""\
<header>
  <h1>Greining á þingumræðum um ESB og EES</h1>
  <p class="subtitle">Samanburður á röksemdafærslum í Alþingisumræðum 1991–1993 og 2024–2026.
  Smelltu á línu til að sjá öll tilvik.</p>
</header>

<table>
<thead>
<tr>
  <th data-sort="num">#</th>
  <th data-sort="text">Meginfullyrðing</th>
  <th data-sort="num">ESB (2026)</th>
  <th data-sort="num">EES (1991–93)</th>
  <th data-sort="num">Samtals</th>
</tr>
</thead>
<tbody>
{"".join(table_rows)}
</tbody>
</table>

<p class="table-footer">{total_assigned} fullyrðingatilvik í {len(rows)} meginfullyrðingum.</p>

{"".join(detail_sections)}"""

    return wrap_page(
        "Greining á þingumræðum um ESB og EES",
        body,
        SORT_JS + TOGGLE_JS,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Loading data...")
    data = load_all()

    if not data["meta_claims"]:
        print("No accepted meta-claims found. Run the meta-claim pipeline first.")
        sys.exit(1)

    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)

    # Clean previous run
    for old in HANDOFF_DIR.glob("*.html"):
        old.unlink()

    # Single-page handoff
    content = generate_single_page(data)
    out = HANDOFF_DIR / "heimildin.html"
    out.write_text(content, encoding="utf-8")
    size_kb = out.stat().st_size / 1024
    print(f"  {out.name} ({size_kb:.0f} KB)")

    n_meta = len(data["meta_claims"])
    n_inst = sum(len(v) for v in data["meta_instances"].values())
    print(f"\n  {n_meta} meginfullyrðingar, {n_inst} tilvik")
    print(f"  {HANDOFF_DIR / out.name}")


if __name__ == "__main__":
    main()
