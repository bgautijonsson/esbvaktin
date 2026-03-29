"""Export merged entity data from per-analysis _entities.json files.

Reads all data/analyses/*/_entities.json files, merges entities by name,
and produces a site-ready entities.json.

Usage:
    uv run python scripts/export_entities.py
    uv run python scripts/export_entities.py --site-dir ~/esbvaktin-site
    uv run python scripts/export_entities.py --status
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYSES_DIR = PROJECT_ROOT / "data" / "analyses"
EXPORT_DIR = PROJECT_ROOT / "data" / "export"
DEFAULT_SITE_DIR = PROJECT_ROOT.parent / "esbvaktin-site"


from esbvaktin.utils.slugify import icelandic_slugify  # noqa: F401 — re-exported


def _get_report_slug(report_path: Path) -> str:
    """Get the report slug from _report_final.json."""
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    title = report.get("article_title", report_path.parent.name)
    return icelandic_slugify(title)


def _load_db_verdict_map() -> dict[str, str]:
    """Load {claim_slug: verdict} from DB for current verdicts."""
    try:
        from esbvaktin.ground_truth.operations import get_connection

        conn = get_connection()
        rows = conn.execute(
            "SELECT claim_slug, verdict FROM claims WHERE published = TRUE"
        ).fetchall()
        conn.close()
        return {slug: verdict for slug, verdict in rows}
    except Exception as exc:
        print(
            f"WARNING: Could not load DB verdicts for entity scoring: {exc}",
            file=sys.stderr,
        )
        return {}


def _get_claim_data(report_path: Path, db_verdicts: dict[str, str] | None = None) -> list[dict]:
    """Get claim slugs and verdicts from a report.

    Returns a list of {slug, verdict, text} dicts, one per claim.
    When db_verdicts is provided, uses current DB verdict instead of the
    stale snapshot value stored in the report file.
    """
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    claims = []
    for item in report.get("claims", []):
        claim = item.get("claim", item)
        text = claim.get("claim_text", "")
        slug = icelandic_slugify(text[:80])
        verdict = (db_verdicts or {}).get(slug, item.get("verdict", "unknown"))
        claims.append(
            {
                "slug": slug,
                "verdict": verdict,
                "text": text,
            }
        )
    return claims


def _load_non_substantive_texts() -> set[str]:
    """Load canonical texts of non-substantive claims from the DB.

    Returns a set of canonical_text_is and canonical_text_en values
    for claims marked as non-substantive. Used to exclude these from
    credibility calculations.
    """
    try:
        from esbvaktin.ground_truth.operations import get_connection

        conn = get_connection()
        rows = conn.execute(
            "SELECT canonical_text_is, canonical_text_en FROM claims WHERE substantive = FALSE"
        ).fetchall()
        conn.close()
    except Exception as exc:
        print(f"ERROR: Could not load non-substantive texts: {exc}", file=sys.stderr)
        return set()

    texts: set[str] = set()
    for text_is, text_en in rows:
        if text_is:
            texts.add(text_is)
        if text_en:
            texts.add(text_en)
    return texts


def _process_entity_dir(
    entities: dict[str, dict],
    entity_dir: Path,
    report_slug: str,
    claim_data: list[dict],
    non_substantive_texts: set[str] | None = None,
) -> None:
    """Process a single directory containing _entities.json."""
    entities_path = entity_dir / "_entities.json"
    if not entities_path.exists():
        return

    with open(entities_path, encoding="utf-8") as f:
        raw = json.load(f)

    author = raw.get("article_author")
    if author and author.get("name"):
        _merge_entity(entities, author, report_slug, claim_data, non_substantive_texts)

    for speaker in raw.get("speakers", []):
        if speaker.get("name"):
            _merge_entity(entities, speaker, report_slug, claim_data, non_substantive_texts)


def load_all_entities(extra_dirs: list[Path] | None = None) -> dict[str, dict]:
    """Load and merge entity data from all analyses and optional extra dirs.

    Args:
        extra_dirs: Additional directories to scan for _entities.json files
                    (e.g. inbox entity dirs from /process-inbox).

    Returns a dict keyed by entity slug with merged data.
    """
    entities: dict[str, dict] = {}
    non_sub = _load_non_substantive_texts()
    if non_sub:
        print(f"  Excluding {len(non_sub)} non-substantive claim texts from credibility")

    db_verdicts = _load_db_verdict_map()
    if db_verdicts:
        print(f"  Loaded {len(db_verdicts)} current verdicts from DB for entity scoring")

    # Standard analyses
    for analysis_dir in sorted(ANALYSES_DIR.iterdir()):
        if not analysis_dir.is_dir():
            continue

        report_path = analysis_dir / "_report_final.json"
        if not report_path.exists():
            continue

        report_slug = _get_report_slug(report_path)
        claim_data = _get_claim_data(report_path, db_verdicts)
        _process_entity_dir(entities, analysis_dir, report_slug, claim_data, non_sub)

    # Extra dirs (inbox entities) — these have _entities.json but no _report_final.json
    # Use the directory name as slug and extract claims from extracted_claims if available
    for extra_dir in extra_dirs or []:
        if not extra_dir.is_dir():
            continue
        for sub_dir in sorted(extra_dir.iterdir()):
            if not sub_dir.is_dir():
                continue
            slug = icelandic_slugify(sub_dir.name)
            _process_entity_dir(entities, sub_dir, slug, [], non_sub)

    return entities


# Known name aliases — map variant names to canonical slugs
# Icelandic morphology creates definite-suffix and case variants
_NAME_ALIASES: dict[str, str] = {
    # Organisations — definite suffixes and common short forms
    "bændasamtökin": "baendasamtok-islands",
    "bændasamtök íslands": "baendasamtok-islands",
    "samtök iðnaðarins": "samtok-idnadarins",
    "samtökin": "samtok-idnadarins",
    "ríkisstjórnin": "rikissjornin",
    "ríkisstjórn íslands": "rikissjornin",
    "alþingi": "althingi",
    "rúv": "ruv",
    "ríkisútvarpið": "ruv",
    # Parties — with/without definite suffix
    "miðflokkurinn": "midflokkurinn",
    "miðflokkur": "midflokkurinn",
    "sjálfstæðisflokkurinn": "sjalfstaedisflokkurinn",
    "sjálfstæðisflokkur": "sjalfstaedisflokkurinn",
    "framsóknarflokkurinn": "framsoknarflokkurinn",
    "framsóknarflokkur": "framsoknarflokkurinn",
    "viðreisn": "vidreisn",
    "samfylkingin": "samfylkingin",
    "samfylking": "samfylkingin",
    "flokkur fólksins": "flokkur-folksins",
    "píratar": "piratar",
    "piratar": "piratar",
    "vinstrihreyfingin – grænt framboð": "vinstri-graen",
    "vinstrihreyfingin - grænt framboð": "vinstri-graen",
    "vinstrihreyfingin grænt framtíð": "vinstri-graen",
    "vinstrihreyfingin grænt framboð": "vinstri-graen",
    "vinstri-græn": "vinstri-graen",
    # Individual name variants
    "bjorn levi gunnarsson": "bjorn-levi-gunnarsson",
    "björn leví gunnarson": "bjorn-levi-gunnarsson",
    "björn leví gunnarsson": "bjorn-levi-gunnarsson",
    "lilja alfreðsdóttir": "lilja-dogg-alfredsdottir",
    "kristrún": "kristrun-frostadottir",
    "kristrúna": "kristrun-frostadottir",
    "kristrúnar frostadóttur": "kristrun-frostadottir",
    "birni inga hrafnsson": "bjorn-ingi-hrafnsson",
    "pawel bartoszek": "pawel-bartoszek",
    "pavel bartoszek": "pawel-bartoszek",
    "þorgerður katrín": "thorgerdur-katrin-gunnarsdottir",
    "þorgerður katrín gunnarsdóttur": "thorgerdur-katrin-gunnarsdottir",
    "dagur b": "dagur-b-eggertsson",
    # Media — short vs full name and duplicate slugs
    "heimildin fréttastofa": "heimildin",
    "mbl.is": "morgunbladid",
    "morgunblaðið": "morgunbladid",
    "fréttastofa rúv": "ruv",
}

# Override display names for aliases where heuristic may pick wrong variant
_CANONICAL_NAMES: dict[str, str] = {
    "bjorn-levi-gunnarsson": "Björn Leví Gunnarsson",
    "heimildin": "Heimildin",
    "bjorn-ingi-hrafnsson": "Björn Ingi Hrafnsson",
    "pawel-bartoszek": "Pawel Bartoszek",
    "thorgerdur-katrin-gunnarsdottir": "Þorgerður Katrín Gunnarsdóttir",
    "dagur-b-eggertsson": "Dagur B. Eggertsson",
    "kristrun-frostadottir": "Kristrún Frostadóttir",
    "lilja-dogg-alfredsdottir": "Lilja Dögg Alfreðsdóttir",
}

# Entries that are titles/roles, not actual entities — skip these
_SKIP_NAMES = {
    "formaður miðflokksins",
    "formaður sjálfstæðisflokksins",
    "utanríkisráðherra",
    "formenn ríkisstjórnarflokkanna",
    "talsmenn esb-aðildar",
    "mbl.is fréttaritari",
    "ritstjórn mbl.is",
}

# Former MPs / politicians who now appear as experts — exclude from
# subtype='politician' so they aren't shown with a current party link.
# Their althingi_stats are preserved as historical record.
_NOT_POLITICIANS: set[str] = {
    "dora-sif-tynes",
}

# Override roles for entities whose extractor-assigned role is outdated
_ROLE_OVERRIDES: dict[str, str] = {
    "dora-sif-tynes": "lögmaður og sérfræðingur í EES-rétti",
}


# ── Alþingi speech enrichment ────────────────────────────────────────

_ALTHINGI_DB_DEFAULT = Path.home() / "althingi" / "althingi-mcp" / "data" / "althingi.db"

_EU_ISSUE_PATTERNS = [
    "%Evróp%",
    "%ESB%",
    "%aðild%Evrópu%",
    "%aðildarviðræð%",
    "%aðildarumsókn%",
    "%þjóðaratkvæðagreiðsl%",
    "%Evrópumál%",
]


def _load_althingi_speakers() -> dict[str, dict]:
    """Load EU speaker summaries from althingi.db (sync, read-only).

    Returns a dict keyed by lowercased speaker name → stats dict.
    Returns empty dict if the DB is unavailable.
    """
    db_path = Path(os.environ.get("ALTHINGI_DB_PATH", str(_ALTHINGI_DB_DEFAULT)))
    if not db_path.exists():
        return {}

    issue_filter = " OR ".join("s.issue_title LIKE ?" for _ in _EU_ISSUE_PATTERNS)
    sql = f"""
        SELECT s.name AS speaker,
               COUNT(*) AS speech_count,
               SUM(COALESCE(t.word_count, 0)) AS total_words,
               COUNT(DISTINCT s.issue_nr) AS issues,
               MIN(s.date) AS first_speech,
               MAX(s.date) AS last_speech
        FROM speeches s
        LEFT JOIN speech_texts t ON s.speech_id = t.speech_id
        WHERE ({issue_filter})
        GROUP BY s.name
        ORDER BY total_words DESC
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, _EU_ISSUE_PATTERNS).fetchall()
        conn.close()
    except Exception as exc:
        print(f"WARNING: Could not load EU speech data from althingi.db: {exc}", file=sys.stderr)
        return {}

    return {
        row["speaker"].lower(): {
            "speech_count": row["speech_count"],
            "total_words": row["total_words"],
            "issues": row["issues"],
            "first_speech": row["first_speech"][:10] if row["first_speech"] else None,
            "last_speech": row["last_speech"][:10] if row["last_speech"] else None,
        }
        for row in rows
    }


def _name_matches(entity_name: str, althingi_name: str) -> bool:
    """Check if an entity name matches an Alþingi speaker name.

    Handles exact match and partial match (all words of the shorter name
    appear in the longer name, with at least 2 words to prevent false positives).
    """
    en = entity_name.lower().strip()
    an = althingi_name.lower().strip()
    if en == an:
        return True
    short, long_ = (en, an) if len(en) <= len(an) else (an, en)
    short_words = set(short.split())
    long_words = set(long_.split())
    return len(short_words) >= 2 and short_words.issubset(long_words)


def _enrich_althingi_stats(entities: dict[str, dict]) -> int:
    """Add althingi_stats to entities that match Alþingi EU speakers.

    Returns the number of entities enriched.
    """
    speakers = _load_althingi_speakers()
    if not speakers:
        return 0

    enriched = 0
    for entity in entities.values():
        if entity["type"] != "individual":
            continue

        name = entity["name"]
        # Exact match first
        stats = speakers.get(name.lower())
        if not stats:
            # Fuzzy: all words of one name appear in the other
            for speaker_name, s in speakers.items():
                if _name_matches(name, speaker_name):
                    stats = s
                    break

        if stats:
            entity["althingi_stats"] = stats
            enriched += 1

    return enriched


# ── Authoritative party affiliations from Alþingi DB ─────────────────

# Map DB canonical party names → existing entity slugs
_DB_PARTY_TO_SLUG: dict[str, str] = {
    "Samfylkingin": "samfylkingin",
    "Sjálfstæðisflokkur": "sjalfstaedisflokkurinn",
    "Framsóknarflokkur": "framsoknarflokkurinn",
    "Miðflokkurinn": "midflokkurinn",
    "Viðreisn": "vidreisn",
    "Flokkur fólksins": "flokkur-folksins",
    "Píratar": "piratar",
    "Vinstrihreyfingin - grænt framboð": "vinstri-graen",
}

# Reverse: free-text party variants → DB canonical name (for non-roster matches)
_FREETEXT_TO_DB_PARTY: dict[str, str] = {
    "miðflokkurinn": "Miðflokkurinn",
    "miðflokkur": "Miðflokkurinn",
    "sjálfstæðisflokkurinn": "Sjálfstæðisflokkur",
    "sjálfstæðisflokkur": "Sjálfstæðisflokkur",
    "framsóknarflokkurinn": "Framsóknarflokkur",
    "framsóknarflokkur": "Framsóknarflokkur",
    "viðreisn": "Viðreisn",
    "samfylkingin": "Samfylkingin",
    "samfylking": "Samfylkingin",
    "flokkur fólksins": "Flokkur fólksins",
    "píratar": "Píratar",
    "piratar": "Píratar",
    "vinstrihreyfingin – grænt framboð": "Vinstrihreyfingin - grænt framboð",
    "vinstrihreyfingin - grænt framboð": "Vinstrihreyfingin - grænt framboð",
    "vinstrihreyfingin grænt framtíð": "Vinstrihreyfingin - grænt framboð",
    "vinstrihreyfingin grænt framboð": "Vinstrihreyfingin - grænt framboð",
    "vinstri-græn": "Vinstrihreyfingin - grænt framboð",
}


def _load_mp_roster() -> dict[str, dict]:
    """Load MP roster from althingi.db for sessions 155–157.

    Returns a dict keyed by lowercased MP name → {name, mp_id, party}.
    For MPs who served in multiple sessions, takes the latest session's party.
    """
    db_path = Path(os.environ.get("ALTHINGI_DB_PATH", str(_ALTHINGI_DB_DEFAULT)))
    if not db_path.exists():
        return {}

    sql = """
        SELECT m.name, m.id AS mp_id, ms.party, ms.seat_type, ms.session
        FROM member_sessions ms
        JOIN members m ON ms.mp_id = m.id AND ms.session = m.session
        WHERE ms.session IN (155, 156, 157)
          AND ms.party != 'utan þingflokka'
        ORDER BY ms.session ASC
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql).fetchall()
        conn.close()
    except Exception as exc:
        print(f"WARNING: Could not load MP roster from althingi.db: {exc}", file=sys.stderr)
        return {}

    # Later sessions overwrite earlier — gives us the most recent party
    roster: dict[str, dict] = {}
    for row in rows:
        roster[row["name"].lower()] = {
            "name": row["name"],
            "mp_id": row["mp_id"],
            "party": row["party"],
            "seat_type": row["seat_type"],
        }
    return roster


def _enrich_party_affiliations(
    entities: dict[str, dict],
    roster: dict[str, dict],
) -> int:
    """Override free-text party/role with canonical DB data, add party_slug.

    Only processes subtype='politician' entities.
    Returns the number of entities enriched with authoritative party data.
    """
    enriched = 0
    for entity in entities.values():
        if entity.get("subtype") != "politician":
            continue

        name = entity["name"]
        # Try roster match (same fuzzy logic as althingi stats)
        mp = roster.get(name.lower())
        if not mp:
            for roster_name, r in roster.items():
                if _name_matches(name, roster_name):
                    mp = r
                    break

        if mp:
            db_party = mp["party"]
            entity["party"] = db_party
            slug = _DB_PARTY_TO_SLUG.get(db_party)
            if slug:
                entity["party_slug"] = slug
            # Override role with authoritative "þingmaður" for roster MPs
            entity["role"] = "þingmaður"
            enriched += 1
        else:
            # Non-roster politician (foreign, former, etc.) — resolve from free text
            free_party = (entity.get("party") or "").lower().strip()
            if free_party:
                db_party = _FREETEXT_TO_DB_PARTY.get(free_party)
                if db_party:
                    entity["party"] = db_party
                    slug = _DB_PARTY_TO_SLUG.get(db_party)
                    if slug:
                        entity["party_slug"] = slug

    return enriched


def _ensure_party_entities(entities: dict[str, dict]) -> int:
    """Create placeholder party entities for any party_slug that has no entity.

    Returns the number of placeholder entities created.
    """
    # Collect all party_slugs referenced by politicians
    referenced_slugs = {e["party_slug"] for e in entities.values() if e.get("party_slug")}

    # Find which ones are missing
    existing_party_slugs = {slug for slug, e in entities.items() if e["type"] == "party"}
    missing = referenced_slugs - existing_party_slugs

    # Reverse lookup for display names
    slug_to_name = {v: k for k, v in _DB_PARTY_TO_SLUG.items()}

    created = 0
    for slug in missing:
        name = slug_to_name.get(slug, slug)
        entities[slug] = {
            "slug": slug,
            "name": name,
            "type": "party",
            "description": "Stjórnmálaflokkur",
            "role": None,
            "party": None,
            "mention_count": 0,
            "claim_count": 0,
            "articles": [],
            "claims": [],
            "stance_score": 0.0,
            "stance": "neutral",
            "credibility": None,
            "attribution_counts": {},
        }
        created += 1

    return created


def _resolve_attributions(speaker: dict) -> list[dict]:
    """Resolve attributions from a raw speaker dict.

    Supports both new format (attributions list) and legacy (bare claim_indices).
    Returns list of {claim_index, attribution} dicts.
    """
    attributions = speaker.get("attributions", [])
    if attributions:
        return [
            {
                "claim_index": a["claim_index"],
                "attribution": a.get("attribution", "asserted"),
            }
            for a in attributions
        ]
    # Legacy fallback: bare claim_indices default to 'asserted'
    return [
        {"claim_index": idx, "attribution": "asserted"} for idx in speaker.get("claim_indices", [])
    ]


# Attribution types that imply the entity *made* the claim (vs merely being referenced)
_ACTIVE_ATTRIBUTIONS = {"asserted", "quoted", "paraphrased"}


def _merge_entity(
    entities: dict[str, dict],
    speaker: dict,
    report_slug: str,
    claim_data: list[dict],
    non_substantive_texts: set[str] | None = None,
) -> None:
    """Merge a speaker into the entities dict, deduplicating by slug."""
    name = speaker["name"]

    # Skip title-based entries
    if name.lower() in _SKIP_NAMES:
        return

    # Apply name aliases
    slug = _NAME_ALIASES.get(name.lower(), icelandic_slugify(name))

    # Prefer the "best" name variant: most Icelandic chars, then longest
    # This picks "Björn Leví Gunnarsson" over "Bjorn Levi Gunnarsson"
    # and "Lilja Dögg Alfreðsdóttir" over "Lilja Alfreðsdóttir"
    def _name_score(n: str) -> tuple[int, int]:
        icelandic = sum(1 for c in n if c in "áðéíóúýþæöÁÐÉÍÓÚÝÞÆÖ")
        return (icelandic, len(n))

    if slug in entities:
        if _name_score(name) > _name_score(entities[slug]["name"]):
            entities[slug]["name"] = name

    if slug not in entities:
        entities[slug] = {
            "slug": slug,
            "name": name,
            "type": speaker.get("type", "individual"),
            "description": "",
            "role": speaker.get("role"),
            "party": speaker.get("party"),
            "mention_count": 0,
            "claim_count": 0,
            "articles": [],
            "claims": [],
            # Intermediate tracking — finalised by _compute_scores()
            "_stances": [],
            "_verdicts": [],
            # Attribution breakdown — how many of each type across all articles
            "_attribution_counts": {"asserted": 0, "quoted": 0, "paraphrased": 0, "mentioned": 0},
        }

    entity = entities[slug]

    # Update with richer data if available
    if speaker.get("role") and not entity.get("role"):
        entity["role"] = speaker["role"]
    if speaker.get("party") and not entity.get("party"):
        entity["party"] = speaker["party"]

    # Track this per-article stance for averaging
    entity["_stances"].append(speaker.get("stance", "neutral"))

    # Add article reference
    if report_slug not in entity["articles"]:
        entity["articles"].append(report_slug)

    # Map attributions to claim slugs, collect verdicts, and count types
    for attr in _resolve_attributions(speaker):
        idx = attr["claim_index"]
        attr_type = attr["attribution"]

        # Count attribution types
        if attr_type in entity["_attribution_counts"]:
            entity["_attribution_counts"][attr_type] += 1

        if 0 <= idx < len(claim_data):
            cd = claim_data[idx]
            # Only link claims for active attributions (not 'mentioned')
            if attr_type not in _ACTIVE_ATTRIBUTIONS:
                continue
            if cd["slug"] not in entity["claims"]:
                entity["claims"].append(cd["slug"])
            # Only count verdicts for substantive claims
            is_non_sub = non_substantive_texts and cd.get("text") in non_substantive_texts
            if not is_non_sub:
                entity["_verdicts"].append(cd["verdict"])

    # Update mention count (count of articles) and claim count
    entity["mention_count"] = len(entity["articles"])
    entity["claim_count"] = len(entity.get("claims") or [])


_STANCE_SCORES = {
    "pro_eu": 1.0,
    "anti_eu": -1.0,
    "mixed": 0.0,
    "neutral": 0.0,
}

_VERDICT_SCORES = {
    "supported": 1.0,
    "partially_supported": 0.5,
    "unsupported": 0.0,
    "misleading": 0.0,
}


def _stance_label(score: float) -> str:
    """Derive a categorical stance label from a continuous score."""
    if score >= 0.5:
        return "pro_eu"
    elif score <= -0.5:
        return "anti_eu"
    elif abs(score) < 0.1:
        return "neutral"
    else:
        return "mixed"


def _compute_scores(entities: dict[str, dict]) -> None:
    """Compute stance_score, credibility, and attribution_counts from accumulated data.

    stance_score: average of per-article categorical stances mapped to [-1, 1].
    credibility: proportion of verifiable claims that are supported/partially supported.
                 Only counts active attributions (asserted, quoted, paraphrased) — not 'mentioned'.
    attribution_counts: breakdown of how claims are attributed to this entity.
    """
    for entity in entities.values():
        # Stance score — average of all per-article stances
        stances = entity.pop("_stances")
        if stances:
            numeric = [_STANCE_SCORES.get(s, 0.0) for s in stances]
            entity["stance_score"] = round(sum(numeric) / len(numeric), 2)
        else:
            entity["stance_score"] = 0.0
        entity["stance"] = _stance_label(entity["stance_score"])

        # Credibility — from claim verdicts (unverifiable excluded, 'mentioned' excluded)
        verdicts = entity.pop("_verdicts")
        verifiable = [v for v in verdicts if v in _VERDICT_SCORES]
        if verifiable:
            scores = [_VERDICT_SCORES[v] for v in verifiable]
            entity["credibility"] = round(sum(scores) / len(scores), 2)
        else:
            entity["credibility"] = None

        # Promote attribution counts to output (drop zero counts for compactness)
        raw_counts = entity.pop("_attribution_counts")
        entity["attribution_counts"] = {k: v for k, v in raw_counts.items() if v > 0}


# ── Politician subtype classification ────────────────────────────────

# Icelandic role strings that indicate elected officials, ministers, or heads of state
_POLITICIAN_ROLE_PATTERNS = {
    "þingmaður",
    "þingkona",
    "ráðherra",
    "forsætisráðherra",
    "utanríkisráðherra",
    "fjármálaráðherra",
    "sjávarútvegsráðherra",
    "landbúnaðarráðherra",
    "atvinnuvegaáðherra",
    "heilbrigðisráðherra",
    "dómsmálaráðherra",
    "menntamálaráðherra",
    "umhverfisráðherra",
    "samgönguráðherra",
    "innviðaráðherra",
    "forseti íslands",
    "forseti",
    "formaður flokks",
    "varaformaður flokks",
    "borgarstjóri",
    # Foreign heads of state / government
    "kanzlari",
    "forsætisráðherra",
    "forseti",
    "kanslari",
}


def _is_politician(entity: dict) -> bool:
    """Determine if an individual entity is a politician.

    Signals (any one is sufficient):
    1. Has Alþingi speech stats → elected official or minister
    2. Has a party affiliation → party-connected political figure
    3. Has a role matching known political role patterns
    """
    if entity["type"] != "individual":
        return False

    # Signal 1: Alþingi record
    if entity.get("althingi_stats"):
        return True

    # Signal 2: Party affiliation
    if entity.get("party"):
        return True

    # Signal 3: Role matches political patterns
    role = (entity.get("role") or "").lower().strip()
    if role:
        # Check if role starts with or contains any politician pattern
        for pattern in _POLITICIAN_ROLE_PATTERNS:
            if pattern in role:
                return True
        # Also catch compound ráðherra roles (e.g. "utanríkis- og þróunarráðherra")
        if "ráðherra" in role:
            return True

    return False


def _classify_subtypes(entities: dict[str, dict]) -> int:
    """Add subtype='politician' to individual entities that are politicians.

    Returns the number of entities classified as politicians.
    """
    count = 0
    for slug, entity in entities.items():
        if slug in _NOT_POLITICIANS:
            # Former politician — strip party affiliation, apply role override
            entity.pop("party", None)
            entity.pop("party_slug", None)
            if slug in _ROLE_OVERRIDES:
                entity["role"] = _ROLE_OVERRIDES[slug]
            continue
        if _is_politician(entity):
            entity["subtype"] = "politician"
            count += 1
    return count


# ── Icelandic entity classification ──────────────────────────────────

# Icelandic party slugs (8 current Alþingi parties)
_ICELANDIC_PARTIES: set[str] = {
    "midflokkurinn",
    "sjalfstaedisflokkurinn",
    "vidreisn",
    "flokkur-folksins",
    "framsoknarflokkurinn",
    "samfylkingin",
    "piratar",
    "vinstri-graen",
}

# Icelandic media outlet slugs
_ICELANDIC_OUTLETS: set[str] = {
    "visir",
    "morgunbladid",
    "ruv",
    "dv",
    "heimildin",
    "kjarninn",
    "stundin",
    "frettabladid",
    "nutiminn",
}

# ── Media outlet subtype classification ───────────────────────────────

# Known media outlet slugs — derived from _SOURCE_FROM_DOMAIN in prepare_site.py
_KNOWN_OUTLETS: set[str] = {
    "visir",
    "morgunbladid",
    "ruv",
    "heimildin",
    "kjarninn",
    "stundin",
    "frettabladid",
    "dv",
    "altinget-no",
    "nutiminn",
}

# Map outlet entity slugs → all article_source values that belong to them.
# Panel shows and podcasts fold into their parent outlet.
_OUTLET_SOURCE_ALIASES: dict[str, list[str]] = {
    "morgunbladid": ["Morgunblaðið", "Morgunbladid", "mbl", "Spursmál (mbl.is)"],
    "ruv": ["RÚV", "Silfrið (RÚV)", "Vikulokin (RÚV)", "Ríkisútvarpið"],
    "visir": ["Vísir", "Visir", "Vísir/Bylgjan"],
    "dv": ["DV"],
    "heimildin": ["Heimildin"],
    "kjarninn": ["Kjarninn"],
    "stundin": ["Stundin"],
    "frettabladid": ["Fréttablaðið"],
    "altinget-no": ["Altinget.no"],
    "nutiminn": ["Nútíminn"],
}

# Roles that indicate a media/news operation
_MEDIA_ROLE_PATTERNS = {"fréttaflutningur", "fréttamiðill", "fjölmiðill"}


def _classify_media_outlets(entities: dict[str, dict]) -> int:
    """Add subtype='media' to institution entities that are news outlets.

    Returns the number of entities classified as media outlets.
    """
    count = 0
    for slug, entity in entities.items():
        if entity["type"] != "institution":
            continue

        # Known outlet slug
        if slug in _KNOWN_OUTLETS:
            entity["subtype"] = "media"
            count += 1
            continue

        # Role matches media patterns
        role = (entity.get("role") or "").lower().strip()
        if role and role in _MEDIA_ROLE_PATTERNS:
            entity["subtype"] = "media"
            count += 1

    return count


def _generate_descriptions(entities: dict[str, dict]) -> None:
    """Generate basic Icelandic descriptions for entities that lack one."""
    type_labels = {
        "individual": "Einstaklingur",
        "party": "Stjórnmálaflokkur",
        "institution": "Stofnun",
        "union": "Samtök",
    }
    stance_labels = {
        "pro_eu": "hlynnt ESB-aðild",
        "anti_eu": "andvíg/ur ESB-aðild",
        "mixed": "blandað viðhorf til ESB-aðildar",
        "neutral": "hlutlaus um ESB-aðild",
    }

    for entity in entities.values():
        if entity.get("description"):
            continue

        parts = []
        type_label = type_labels.get(entity["type"], "")

        if entity["type"] == "individual":
            if entity.get("role"):
                role = entity["role"]
                # Capitalise first letter only — .capitalize() lowercases
                # the rest, which breaks acronyms like EES, ESB
                parts.append(role[0].upper() + role[1:] if role else role)
            if entity.get("party"):
                parts.append(f"({entity['party']})")
        else:
            if type_label:
                parts.append(type_label)

        stance_desc = stance_labels.get(entity["stance"], "")
        if stance_desc:
            if parts:
                parts.append(f"— {stance_desc}.")
            else:
                parts.append(stance_desc.capitalize() + ".")

        entity["description"] = " ".join(parts) if parts else ""


def export_entities(
    site_dir: Path | None = None,
    extra_dirs: list[Path] | None = None,
) -> list[dict]:
    """Export merged entities to JSON files."""
    entities = load_all_entities(extra_dirs=extra_dirs)
    _compute_scores(entities)
    althingi_count = _enrich_althingi_stats(entities)
    politician_count = _classify_subtypes(entities)
    media_count = _classify_media_outlets(entities)
    roster = _load_mp_roster()
    party_enriched = _enrich_party_affiliations(entities, roster)
    party_created = _ensure_party_entities(entities)
    _generate_descriptions(entities)

    # Flag Icelandic parties and outlets
    for slug, entity in entities.items():
        if entity["type"] == "party":
            entity["icelandic"] = slug in _ICELANDIC_PARTIES
        elif entity.get("subtype") == "media":
            entity["icelandic"] = slug in _ICELANDIC_OUTLETS

    # Apply canonical name overrides
    for slug, canonical in _CANONICAL_NAMES.items():
        if slug in entities:
            entities[slug]["name"] = canonical

    # Sort by mention count (descending), then name
    sorted_entities = sorted(
        entities.values(),
        key=lambda e: (-e["claim_count"], -e["mention_count"], e["name"]),
    )

    # Export to data/export/
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = EXPORT_DIR / "entities.json"
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(sorted_entities, f, ensure_ascii=False, indent=2)
    print(f"Exported {len(sorted_entities)} entities to {export_path}")

    # Export to site _data/ if available
    if site_dir and site_dir.exists():
        site_path = site_dir / "_data" / "entities.json"
        with open(site_path, "w", encoding="utf-8") as f:
            json.dump(sorted_entities, f, ensure_ascii=False, indent=2)
        print(f"Copied to {site_path}")

        # Also write to assets/data/ for client-side JS (Raddirnar page)
        assets_path = site_dir / "assets" / "data" / "entities.json"
        assets_path.parent.mkdir(parents=True, exist_ok=True)
        with open(assets_path, "w", encoding="utf-8") as f:
            json.dump(sorted_entities, f, ensure_ascii=False, indent=2)
        print(f"Copied to {assets_path}")

    # Print summary
    by_type: dict[str, int] = {}
    by_stance: dict[str, int] = {}
    cred_values = []
    for e in sorted_entities:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        by_stance[e["stance"]] = by_stance.get(e["stance"], 0) + 1
        if e.get("credibility") is not None:
            cred_values.append(e["credibility"])

    print(f"\nBy type: {by_type}")
    print(f"By stance: {by_stance}")
    print(f"Total articles covered: {len({a for e in sorted_entities for a in e['articles']})}")
    if cred_values:
        avg_cred = sum(cred_values) / len(cred_values)
        print(f"Credibility: {len(cred_values)} entities scored, avg={avg_cred:.2f}")
    if althingi_count:
        print(f"Alþingi stats: {althingi_count} entities enriched with parliamentary data")
    if politician_count:
        print(f"Politicians: {politician_count} individuals classified as subtype=politician")
    if party_enriched:
        print(
            f"Party affiliations: {party_enriched} politicians linked to authoritative party data"
        )
    if party_created:
        print(f"Party placeholders: {party_created} new party entities created as link targets")
    if media_count:
        print(f"Media outlets: {media_count} institutions classified as subtype=media")

    return sorted_entities


def main() -> None:
    if "--status" in sys.argv:
        entities = load_all_entities()
        _compute_scores(entities)
        print(f"Found {len(entities)} unique entities across analyses")
        for slug, e in sorted(entities.items(), key=lambda x: -x[1]["mention_count"]):
            cred = f", cred={e['credibility']:.2f}" if e.get("credibility") is not None else ""
            print(
                f"  {e['name']} ({e['type']}, stance={e['stance_score']:+.2f}{cred}) — {e['mention_count']} articles"
            )
        return

    site_dir = (
        Path(sys.argv[sys.argv.index("--site-dir") + 1])
        if "--site-dir" in sys.argv
        else DEFAULT_SITE_DIR
    )

    extra_dirs = []
    if "--inbox-dir" in sys.argv:
        idx = sys.argv.index("--inbox-dir")
        extra_dirs.append(Path(sys.argv[idx + 1]))

    export_entities(site_dir, extra_dirs=extra_dirs or None)


if __name__ == "__main__":
    main()
