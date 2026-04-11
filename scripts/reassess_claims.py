#!/usr/bin/env python3
"""Re-assess claims that may benefit from new evidence or verdict correction.

Four categories of claims are targeted:
  1. **Unverifiable** — previously lacked evidence, may now have matches
  2. **Partially supported** — had some evidence, may now have additional
     evidence that upgrades (or changes) the verdict
  3. **Overconfident** — 'supported' claims flagged by the verdict audit
     (sighting drift, contradicting evidence, or substantial caveats)
  4. **Denominator confusion** — 'supported' claims using scope-broadening
     language ("megnið", "flest", "öll") that may apply subset evidence to
     a whole-population claim (Pattern 2 from audit_claims.py)

Retrieves evidence for each claim, writes context files for subagent
assessment, then parses subagent output and updates the DB.

Usage:
    # Step 1: Prepare context files (batches of ~10 claims each)
    uv run python scripts/reassess_claims.py prepare           # unverifiable + partial
    uv run python scripts/reassess_claims.py prepare --only unverifiable
    uv run python scripts/reassess_claims.py prepare --only partial
    uv run python scripts/reassess_claims.py prepare --only overconfident  # verdict audit
    uv run python scripts/reassess_claims.py prepare --only overconfident --limit 30
    uv run python scripts/reassess_claims.py prepare --only denominator    # scope-word audit
    uv run python scripts/reassess_claims.py prepare --evidence CURR-DATA-007 CURRENCY-DATA-017
    uv run python scripts/reassess_claims.py prepare --claims 123 456 789

    # Step 2: Run subagent assessment (Claude Code reads each batch context
    #         and writes _assessments_batch_N.json)
    # → see printed instructions after prepare

    # Step 3: Parse subagent output and update DB
    uv run python scripts/reassess_claims.py update

    # Check status
    uv run python scripts/reassess_claims.py status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORK_DIR = Path("data/reassessment")
_BLOCKS_PATH = Path(".claude/skills/icelandic-shared/assessment-blocks.md")
SIMILARITY_THRESHOLD = 0.45
BATCH_SIZE = 10
SCOPE_WORDS_PATTERN = r"(megnið|flest|langflest|meirihlut|allra|öll |alls )"


def _search_evidence_hybrid(
    text_is: str | None,
    text_en: str | None,
    category: str | None,
    conn,
    top_k: int = 8,
):
    """Hybrid BM25 + vector search using the full retrieval pipeline.

    Constructs a minimal Claim object to leverage retrieve_evidence_for_claim()
    which runs topic-filtered vector + unfiltered vector + BM25 keyword search
    with RRF fusion. Falls back to dual vector-only search if the pipeline
    import fails.
    """
    from esbvaktin.pipeline.models import Claim, ClaimType, EpistemicType
    from esbvaktin.pipeline.retrieve_evidence import retrieve_evidence_for_claim

    query = text_is or text_en
    if not query:
        return []

    claim = Claim(
        claim_text=query,
        original_quote=query,
        category=category or "sovereignty",
        claim_type=ClaimType.OPINION,
        epistemic_type=EpistemicType.FACTUAL,
        confidence=0.5,
    )
    cwe = retrieve_evidence_for_claim(claim, top_k=top_k, conn=conn)
    return list(cwe.evidence)


def _get_reassessable_claims(
    conn,
    *,
    include_unverifiable: bool = True,
    include_partial: bool = True,
    include_overconfident: bool = False,
    include_denominator: bool = False,
    include_flagged: bool = False,
    overconfident_limit: int = 30,
    evidence_ids: list[str] | None = None,
    claim_ids: list[int] | None = None,
):
    """Fetch claims that may benefit from (re-)assessment with current evidence.

    For unverifiable claims: any strong evidence match qualifies.
    For partially_supported claims: must have NEW evidence not already linked.
    For overconfident claims: flagged by verdict audit (sighting drift, contradicting evidence, caveats).
    For denominator claims: 'supported' with scope-broadening language (Pattern 2).
    For evidence_ids: all claims citing any of the given evidence entries.
    For claim_ids: specific claims by ID.
    """
    # Targeted modes bypass category logic
    if evidence_ids:
        return _get_claims_by_evidence(conn, evidence_ids)
    if claim_ids:
        return _get_claims_by_ids(conn, claim_ids)

    assessable = []

    if include_unverifiable:
        assessable.extend(_get_unverifiable_with_evidence(conn))

    if include_partial:
        assessable.extend(_get_partial_with_new_evidence(conn))

    if include_overconfident:
        assessable.extend(_get_overconfident_supported(conn, limit=overconfident_limit))

    if include_denominator:
        assessable.extend(_get_denominator_claims(conn))

    if include_flagged:
        assessable.extend(_get_flagged_claims(conn, limit=overconfident_limit))

    return assessable


def _get_claims_by_evidence(conn, evidence_ids: list[str]) -> list[dict]:
    """All claims citing any of the given evidence IDs — for reassessment after evidence updates."""
    placeholders = ", ".join(["%s"] * len(evidence_ids))
    rows = conn.execute(
        f"SELECT id, canonical_text_is, canonical_text_en, category, claim_slug, "
        f"       verdict, confidence, epistemic_type "
        f"FROM claims "
        f"WHERE (supporting_evidence && ARRAY[{placeholders}]::text[] "
        f"    OR contradicting_evidence && ARRAY[{placeholders}]::text[]) "
        f"  AND epistemic_type != 'hearsay' "
        f"ORDER BY verdict, id",
        evidence_ids + evidence_ids,  # params needed twice for both clauses
    ).fetchall()

    assessable = []
    for claim_id, text_is, text_en, category, slug, verdict, confidence, epistemic_type in rows:
        results = _search_evidence_hybrid(text_is, text_en, category, conn)
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:8]
        if not strong:
            continue

        # Mark updated evidence entries as "new" so assessor pays attention
        updated_set = set(evidence_ids)
        assessable.append(
            _make_claim_entry(
                claim_id,
                text_is,
                text_en,
                category,
                slug,
                strong,
                reason="evidence_update",
                new_evidence_ids=updated_set,
                current_confidence=confidence,
                epistemic_type=epistemic_type or "factual",
            )
        )

    return assessable


def _get_claims_by_ids(conn, claim_ids: list[int]) -> list[dict]:
    """Specific claims by ID — for targeted reassessment."""
    placeholders = ", ".join(["%s"] * len(claim_ids))
    rows = conn.execute(
        f"SELECT id, canonical_text_is, canonical_text_en, category, claim_slug, "
        f"       verdict, confidence, epistemic_type "
        f"FROM claims "
        f"WHERE id IN ({placeholders}) "
        f"  AND epistemic_type != 'hearsay' "
        f"ORDER BY id",
        claim_ids,
    ).fetchall()

    assessable = []
    for claim_id, text_is, text_en, category, slug, verdict, confidence, epistemic_type in rows:
        results = _search_evidence_hybrid(text_is, text_en, category, conn)
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:8]
        if not strong:
            continue

        assessable.append(
            _make_claim_entry(
                claim_id,
                text_is,
                text_en,
                category,
                slug,
                strong,
                reason="targeted",
                current_confidence=confidence,
                epistemic_type=epistemic_type or "factual",
            )
        )

    return assessable


def _get_unverifiable_with_evidence(conn) -> list[dict]:
    """Unverifiable claims that now have matching evidence."""
    rows = conn.execute(
        "SELECT id, canonical_text_is, canonical_text_en, category, claim_slug, epistemic_type "
        "FROM claims WHERE verdict = 'unverifiable' "
        "AND epistemic_type != 'hearsay' "
        "ORDER BY category, claim_slug"
    ).fetchall()

    assessable = []
    for claim_id, text_is, text_en, category, slug, epistemic_type in rows:
        results = _search_evidence_hybrid(text_is, text_en, category, conn)
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:8]

        if strong:
            assessable.append(
                _make_claim_entry(
                    claim_id,
                    text_is,
                    text_en,
                    category,
                    slug,
                    strong,
                    reason="unverifiable",
                    epistemic_type=epistemic_type,
                )
            )

    return assessable


def _get_partial_with_new_evidence(conn) -> list[dict]:
    """Partially supported claims that have NEW evidence not already linked."""
    rows = conn.execute(
        "SELECT id, canonical_text_is, canonical_text_en, category, claim_slug, "
        "       supporting_evidence, contradicting_evidence, confidence, epistemic_type "
        "FROM claims WHERE verdict = 'partially_supported' "
        "AND epistemic_type != 'hearsay' "
        "ORDER BY confidence ASC, category, claim_slug"
    ).fetchall()

    assessable = []
    for row in rows:
        (
            claim_id,
            text_is,
            text_en,
            category,
            slug,
            supporting,
            contradicting,
            confidence,
            epistemic_type,
        ) = row
        existing_ids = set(supporting or []) | set(contradicting or [])

        results = _search_evidence_hybrid(text_is, text_en, category, conn)
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:12]  # wider net — we need to find NEW matches

        # Separate into new and existing evidence
        new_evidence = [r for r in strong if r.evidence_id not in existing_ids]
        old_evidence = [r for r in strong if r.evidence_id in existing_ids]

        if not new_evidence:
            continue  # no new evidence — skip, subagent would just re-confirm

        # Include ALL strong evidence (old + new) so subagent has full picture,
        # but flag which ones are new
        all_evidence = (old_evidence + new_evidence)[:8]
        new_ids = {r.evidence_id for r in new_evidence}

        assessable.append(
            _make_claim_entry(
                claim_id,
                text_is,
                text_en,
                category,
                slug,
                all_evidence,
                reason="partial",
                new_evidence_ids=new_ids,
                current_confidence=confidence,
                epistemic_type=epistemic_type,
            )
        )

    return assessable


def _get_overconfident_supported(conn, *, limit: int = 30) -> list[dict]:
    """Supported claims flagged by the verdict audit — multi-pattern and high-score.

    Prioritises claims that are:
    1. Supported + sighting drift (speech verdicts disagree)
    2. Supported + contradicting evidence listed
    3. Supported + substantial missing_context + high confidence

    Returns the top N by a composite score.
    """
    # Get claims with sighting drift (Pattern 3)
    drift_claims = {}
    rows = conn.execute(
        """
        SELECT c.id, c.claim_slug, c.canonical_text_is, c.canonical_text_en,
               c.category, c.confidence, c.published, c.epistemic_type,
               COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END) as mismatches,
               COUNT(*) as total_sightings
        FROM claims c
        JOIN claim_sightings cs ON c.id = cs.claim_id
        WHERE c.verdict = 'supported' AND cs.speech_verdict IS NOT NULL
          AND c.epistemic_type != 'hearsay'
        GROUP BY c.id, c.claim_slug, c.canonical_text_is, c.canonical_text_en,
                 c.category, c.confidence, c.published, c.epistemic_type
        HAVING COUNT(CASE WHEN cs.speech_verdict != c.verdict THEN 1 END) > 0
        """,
    ).fetchall()
    for r in rows:
        drift_claims[r[0]] = {
            "claim_id": r[0],
            "slug": r[1],
            "text_is": r[2],
            "text_en": r[3],
            "category": r[4],
            "confidence": r[5],
            "published": r[6],
            "epistemic_type": r[7],
            "mismatches": r[8],
            "total_sightings": r[9],
            "score": 2.0 * (r[8] / max(r[9], 1)) * (1 + r[8]),  # drift weight
        }

    # Get claims with contradicting evidence (Pattern 4)
    contra_claims = {}
    rows = conn.execute(
        """
        SELECT id, claim_slug, canonical_text_is, canonical_text_en,
               category, confidence, published, epistemic_type,
               array_length(contradicting_evidence, 1) as contra_count
        FROM claims
        WHERE verdict = 'supported'
          AND contradicting_evidence IS NOT NULL
          AND array_length(contradicting_evidence, 1) > 0
          AND epistemic_type != 'hearsay'
        """,
    ).fetchall()
    for r in rows:
        contra_claims[r[0]] = {
            "claim_id": r[0],
            "slug": r[1],
            "text_is": r[2],
            "text_en": r[3],
            "category": r[4],
            "confidence": r[5],
            "published": r[6],
            "epistemic_type": r[7],
            "contra_count": r[8],
            "score": 1.5 * r[8],
        }

    # Get overconfident claims (Pattern 1) — top by missing_context length
    overconf_claims = {}
    rows = conn.execute(
        """
        SELECT id, claim_slug, canonical_text_is, canonical_text_en,
               category, confidence, published, epistemic_type,
               length(missing_context_is) as ctx_len
        FROM claims
        WHERE verdict = 'supported' AND confidence >= 0.85
          AND missing_context_is IS NOT NULL AND length(missing_context_is) >= 80
          AND epistemic_type != 'hearsay'
        ORDER BY confidence DESC, length(missing_context_is) DESC
        """,
    ).fetchall()
    for r in rows:
        overconf_claims[r[0]] = {
            "claim_id": r[0],
            "slug": r[1],
            "text_is": r[2],
            "text_en": r[3],
            "category": r[4],
            "confidence": r[5],
            "published": r[6],
            "epistemic_type": r[7],
            "ctx_len": r[8],
            "score": 1.0 * (r[8] / 200) * r[5],
        }

    # Merge and score — claims in multiple patterns get combined scores
    all_ids = set(drift_claims) | set(contra_claims) | set(overconf_claims)
    scored = []
    for cid in all_ids:
        # Take base info from whichever pattern found it
        info = drift_claims.get(cid) or contra_claims.get(cid) or overconf_claims[cid]
        total_score = sum(
            d.get("score", 0)
            for d in [
                drift_claims.get(cid, {}),
                contra_claims.get(cid, {}),
                overconf_claims.get(cid, {}),
            ]
        )
        # Published claims get priority (published already fetched in initial queries)
        is_published = info.get("published", False)
        if is_published:
            total_score *= 1.5

        patterns = []
        if cid in drift_claims:
            patterns.append("sighting_drift")
        if cid in contra_claims:
            patterns.append("contradicting_ignored")
        if cid in overconf_claims:
            patterns.append("overconfident")

        scored.append(
            {
                **info,
                "total_score": total_score,
                "patterns": patterns,
                "published": is_published,
            }
        )

    scored.sort(key=lambda x: -x["total_score"])
    top = scored[:limit]

    # Retrieve evidence for each claim
    assessable = []
    for claim in top:
        results = _search_evidence_hybrid(
            claim["text_is"],
            claim["text_en"],
            claim.get("category"),
            conn,
        )
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:8]

        if not strong:
            continue

        assessable.append(
            _make_claim_entry(
                claim["claim_id"],
                claim["text_is"],
                claim["text_en"],
                claim["category"],
                claim["slug"],
                strong,
                reason="overconfident",
                current_confidence=claim["confidence"],
                epistemic_type=claim.get("epistemic_type", "factual"),
            )
        )

    return assessable


def _get_denominator_claims(conn) -> list[dict]:
    """Supported claims with scope-broadening language — denominator confusion risk (Pattern 2).

    Targets claims using words like "megnið", "flest", "öll" that may apply evidence
    about a subset of cases to a claim about the whole population.
    """
    rows = conn.execute(
        f"""
        SELECT id, canonical_text_is, canonical_text_en, category, claim_slug,
               confidence, epistemic_type
        FROM claims
        WHERE verdict = 'supported'
          AND canonical_text_is ~* '{SCOPE_WORDS_PATTERN}'
          AND epistemic_type != 'hearsay'
        ORDER BY confidence DESC
        """,
    ).fetchall()

    assessable = []
    for claim_id, text_is, text_en, category, slug, confidence, epistemic_type in rows:
        results = _search_evidence_hybrid(text_is, text_en, category, conn)
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:8]

        if not strong:
            continue

        assessable.append(
            _make_claim_entry(
                claim_id,
                text_is,
                text_en,
                category,
                slug,
                strong,
                reason="denominator_audit",
                current_confidence=confidence,
                epistemic_type=epistemic_type or "factual",
            )
        )

    return assessable


def _get_flagged_claims(conn, limit: int = 30) -> list[dict]:
    """Claims flagged for reassessment by the confidence decay trigger.

    These are claims where sighting drift caused confidence to cross below
    REASSESSMENT_THRESHOLD (0.50), indicating the verdict may need revision.
    """
    rows = conn.execute(
        """
        SELECT id, canonical_text_is, canonical_text_en, category, claim_slug,
               confidence, epistemic_type, reassessment_reason
        FROM claims
        WHERE needs_reassessment = TRUE
          AND epistemic_type != 'hearsay'
        ORDER BY confidence ASC
        LIMIT %(limit)s
        """,
        {"limit": limit},
    ).fetchall()

    assessable = []
    for (
        claim_id,
        text_is,
        text_en,
        category,
        slug,
        confidence,
        epistemic_type,
        reason_detail,
    ) in rows:
        results = _search_evidence_hybrid(text_is, text_en, category, conn)
        strong = sorted(
            [r for r in results if r.similarity >= SIMILARITY_THRESHOLD],
            key=lambda r: r.similarity,
            reverse=True,
        )[:8]

        if not strong:
            continue

        assessable.append(
            _make_claim_entry(
                claim_id,
                text_is,
                text_en,
                category,
                slug,
                strong,
                reason=f"flagged:{reason_detail or 'sighting_drift'}",
                current_confidence=confidence,
                epistemic_type=epistemic_type or "factual",
            )
        )

    return assessable


def _make_claim_entry(
    claim_id,
    text_is,
    text_en,
    category,
    slug,
    results,
    *,
    reason: str,
    new_evidence_ids: set[str] | None = None,
    current_confidence: float | None = None,
    epistemic_type: str = "factual",
) -> dict:
    """Build a claim entry dict for context generation."""
    entry = {
        "claim_id": claim_id,
        "text_is": text_is,
        "text_en": text_en,
        "epistemic_type": epistemic_type,
        "category": category,
        "slug": slug,
        "reason": reason,
        "evidence": [
            {
                "evidence_id": r.evidence_id,
                "statement": r.statement,
                "similarity": round(r.similarity, 3),
                "source_name": r.source_name,
                "source_url": r.source_url,
                "caveats": r.caveats,
                "is_new": r.evidence_id in new_evidence_ids if new_evidence_ids else True,
            }
            for r in results
        ],
    }
    if current_confidence is not None:
        entry["current_confidence"] = current_confidence
    return entry


def _write_batch_context(batch: list[dict], batch_num: int) -> Path:
    """Write a context file for a batch of claims to be assessed by a subagent."""
    path = WORK_DIR / f"_context_batch_{batch_num}.md"

    # Classify the batch
    n_unverifiable = sum(1 for c in batch if c["reason"] == "unverifiable")
    n_partial = sum(1 for c in batch if c["reason"] == "partial")
    n_overconfident = sum(1 for c in batch if c["reason"] == "overconfident")
    n_evidence_update = sum(1 for c in batch if c["reason"] == "evidence_update")
    n_targeted = sum(1 for c in batch if c["reason"] == "targeted")
    n_denominator = sum(1 for c in batch if c["reason"] == "denominator_audit")

    lines = [
        f"# Endurmat fullyrðinga — Lota {batch_num}\n",
        "Þú ert staðreyndaprófari fyrir ESBvaktin.is, óháðan vettvang um",
        "þjóðaratkvæðagreiðslu Íslands um ESB-aðild (29. ágúst 2026).",
        "Þú metur fullyrðingar jafnt hvort sem þær eru ESB-jákvæðar eða ESB-neikvæðar.",
        "",
    ]

    if n_evidence_update or n_targeted:
        total = n_evidence_update + n_targeted
        lines.extend(
            [
                "## Endurmat eftir uppfærslu heimilda",
                "",
                f"Þessi lota inniheldur **{total} fullyrðingar** sem þarf að endurmeta vegna þess að",
                "heimildir í staðreyndagrunni hafa verið uppfærðar. Heimildir merktar 🆕 hafa breyst",
                "frá síðasta mati — lestu þær vandlega og mettu fullyrðinguna í ljósi nýjustu upplýsinga.",
                "",
                "**Mikilvægt:** Fyrri mat gætu verið rangt vegna úreltra heimilda. Mettu hverja fullyrðingu",
                "eingöngu á grundvelli heimildanna hér að neðan, ekki fyrra mats.",
                "",
            ]
        )
    elif n_overconfident:
        lines.extend(
            [
                "## Gæðaendurskoðun — of örugg «supported» mat",
                "",
                f"Þessi lota inniheldur **{n_overconfident} fullyrðingar** sem voru áður metnar `supported`",
                "en eru nú flaggaðar af gæðaendurskoðun vegna eins eða fleiri vandamála:",
                "",
                "- **Fyrirvarar í útskýringu** sem takmarka gildi fullyrðingarinnar en komu ekki fram í úrskurði",
                "- **Misræmi við heimildamat** — sama fullyrðing fékk annað mat í öðru samhengi",
                "- **Andstæðar heimildir** voru skráðar en úrskurður var samt `supported`",
                "",
                "**Reglur fyrir þessa lotu:**",
                "",
                "1. Lestu hverja fullyrðingu og heimildir vandlega",
                "2. Ef fyrirvarar/takmarkanir í heimildum takmarka gildi fullyrðingarinnar → `partially_supported`",
                "3. Ef fullyrðingin notar of vítt gildissvið (t.d. «megnið af regluverki ESB» þegar",
                "   heimildir ná aðeins til innri markaðar) → `partially_supported`",
                "4. Ef andstæðar heimildir eru til staðar og þú getur ekki útskýrt af hverju",
                "   stuðningsheimildir vega þyngra → `partially_supported`",
                "5. Aðeins halda `supported` ef fullyrðingin er nákvæm og heimildir staðfesta hana",
                "   án verulegra fyrirvara",
                "",
            ]
        )
    elif n_denominator:
        lines.extend(
            [
                "## Gæðaendurskoðun — gildissvið fullyrðinga (denominator confusion)",
                "",
                f"Þessi lota inniheldur **{n_denominator} fullyrðingar** sem eru flokkaðar `supported`",
                "en nota umfangsmiðað orðalag eins og «megnið», «flest», «öll» eða «meirihluti».",
                "Hætta er á að heimildir staðfesti hluta tilfella en fullyrðingin sé orðuð sem allsherjar regla.",
                "",
                "**Reglur fyrir þessa lotu:**",
                "",
                "1. Lestu fullyrðinguna og heimildir vandlega",
                "2. Ef heimildir ná aðeins til hluta þess gildissviðs sem fullyrðingin lýsir → `partially_supported`",
                "3. Ef fullyrðingin notar «öll» eða «megnið» en heimildir sýna 60-80% tilfella → `partially_supported`",
                "4. Aðeins halda `supported` ef heimildir staðfesta bæði umsögn og gildissvið fullyrðingarinnar",
                "",
            ]
        )
    elif n_unverifiable and n_partial:
        lines.extend(
            [
                "Þessi lota inniheldur tvenns konar fullyrðingar:",
                f"- **{n_unverifiable} óstaðfestanlegar** — áður skorti heimildir, nú eru nýjar komnar",
                f"- **{n_partial} að hluta staðfestar** — nýjar heimildir (merktar 🆕) gætu breytt matinu",
                "",
            ]
        )
    elif n_unverifiable:
        lines.extend(
            [
                "Þessar fullyrðingar voru áður flokkaðar sem **óstaðfestanlegar** (unverifiable)",
                "vegna þess að heimildir skorti. Nú eru nýjar heimildir komnar í gagnagrunninn.",
                "Endurmettu hverja fullyrðingu í ljósi heimildanna hér að neðan.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "Þessar fullyrðingar voru áður flokkaðar sem **að hluta staðfestar** (partially_supported).",
                "Nýjar heimildir (merktar 🆕) hafa bæst við gagnagrunninn síðan síðasta mat.",
                "Endurmettu hverja fullyrðingu í ljósi ALLRA heimilda — bæði eldri og nýrra.",
                "",
                "**Mikilvægt:** Breyttu aðeins niðurstöðunni ef nýju heimildarnar réttlæta það.",
                "Ef nýju heimildarnar bæta litlu við, haltu `partially_supported` en uppfærðu útskýringuna.",
                "",
            ]
        )

    for i, claim in enumerate(batch, 1):
        reason_tags = {
            "unverifiable": "óstaðfestanleg",
            "partial": "að hluta staðfest",
            "overconfident": "gæðaendurskoðun — of örugg",
            "evidence_update": "uppfærðar heimildir",
            "targeted": "markvisst endurmat",
            "denominator_audit": "gæðaendurskoðun — gildissvið",
        }
        reason_tag = reason_tags.get(claim["reason"], claim["reason"])
        conf_tag = ""
        if claim.get("current_confidence") is not None:
            conf_tag = f" · traust: {claim['current_confidence']:.2f}"
        lines.append(f"## Fullyrðing {i} (claim_id: {claim['claim_id']}) — {reason_tag}{conf_tag}")
        lines.append("")
        lines.append(f"**Íslenskur texti:** {claim['text_is']}")
        if claim["text_en"]:
            lines.append(f"**Enskur texti:** {claim['text_en']}")
        lines.append(f"**Flokkur:** {claim['category']}")
        lines.append("")
        lines.append("**Heimildir úr staðreyndagrunni:**")
        lines.append("")
        for ev in claim["evidence"]:
            new_marker = " 🆕" if ev.get("is_new") else ""
            lines.append(f"- **{ev['evidence_id']}**{new_marker} (líkindi: {ev['similarity']})")
            lines.append(f"  {ev['statement']}")
            lines.append(f"  *Heimild: {ev['source_name']}*")
            if ev.get("caveats"):
                lines.append(f"  Fyrirvarar: {ev['caveats']}")
            lines.append("")

    # Output format
    lines.extend(
        [
            "## Úttakssnið",
            "",
            f"Skrifaðu JSON-fylki í `_assessments_batch_{batch_num}.json` (hrátt JSON, engin markdown-umbúðir).",
            "Skrifaðu `explanation_is` og `missing_context_is` á **íslensku**.",
            "Hvert atriði:",
            "",
            "```json",
            "{",
            '  "claim_id": 123,',
            '  "verdict": "supported | partially_supported | unsupported | misleading | unverifiable",',
            '  "explanation_is": "2-3 setningar á íslensku sem útskýra matið með tilvísun í heimildir",',
            '  "supporting_evidence": ["EVIDENCE-ID-001"],',
            '  "contradicting_evidence": [],',
            '  "missing_context_is": "mikilvægt samhengi á íslensku, eða null",',
            '  "confidence": 0.85',
            "}",
            "```",
            "",
            "## Meginreglur",
            "",
            "- **Óhlutdrægni**: metið ESB-jákvæðar og ESB-neikvæðar fullyrðingar jafnt",
            "- **Heimildum háð**: sérhvert mat VERÐUR að vitna í tilteknar evidence_id úr heimildum hér að ofan",
            "- **Fyrirvarar skipta máli**: komið á framfæri fyrirvörum úr heimildum — þeir geta haft mikla þýðingu",
            "- **Auðmýkt**: ef heimildir duga ekki til, notið áfram `unverifiable` — ekki giska",
            "- **Uppfærsla, ekki endurskrif**: fyrir fullyrðingar sem eru «að hluta staðfestar» — breytið aðeins ef nýju heimildarnar 🆕 breyta myndinni verulega",
            "- **Pólitískar fullyrðingar**: fullyrðingar um afstöðu flokka eða ákveðnar yfirlýsingar stjórnmálamanna "
            "verða einungis merktar `supported` ef heimild staðfestir beint — almennar upplýsingar um flokk duga ekki",
            "- **Tölulegar fullyrðingar**: ef heimildir sýna nálægar en ekki nákvæmlega sömu tölur, notið `partially_supported`",
            '- **JSON-gæsalappir**: ALDREI nota íslensku gæsalappirnar „…" í JSON-strengjagildum — þær brjóta JSON-þáttun. Notaðu «…» (guillemets) í staðinn. Ef þú VERÐUR að nota tvöfaldar gæsalappir, slepptu þeim: \\\\"…\\\\"',
        ]
    )

    # Append Icelandic quality blocks
    if _BLOCKS_PATH.exists():
        lines.append("")
        lines.append(_BLOCKS_PATH.read_text(encoding="utf-8"))

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def prepare(
    *,
    only: str | None = None,
    limit: int = 30,
    evidence_ids: list[str] | None = None,
    claim_ids: list[int] | None = None,
):
    """Prepare context files for subagent re-assessment."""
    from esbvaktin.ground_truth.operations import get_connection

    include_unverifiable = only in (None, "unverifiable") and not evidence_ids and not claim_ids
    include_partial = only in (None, "partial") and not evidence_ids and not claim_ids
    include_overconfident = only == "overconfident" and not evidence_ids and not claim_ids
    include_denominator = only == "denominator" and not evidence_ids and not claim_ids
    include_flagged = only == "flagged" and not evidence_ids and not claim_ids

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # Clean stale output files from previous runs
    stale = list(WORK_DIR.glob("_assessments_batch_*.json"))
    if stale:
        for f in stale:
            f.unlink()
        print(f"Cleaned {len(stale)} stale assessment file(s) from previous run.")

    conn = get_connection()

    if evidence_ids:
        print(f"Retrieving claims citing evidence: {', '.join(evidence_ids)}...")
    elif claim_ids:
        print(f"Retrieving claims by ID: {', '.join(str(c) for c in claim_ids)}...")
    else:
        types = []
        if include_unverifiable:
            types.append("unverifiable")
        if include_partial:
            types.append("partially_supported")
        if include_overconfident:
            types.append(f"overconfident (top {limit})")
        if include_denominator:
            types.append("denominator_audit")
        if include_flagged:
            types.append(f"flagged (top {limit})")
        print(f"Retrieving evidence for {' + '.join(types)} claims...")

    assessable = _get_reassessable_claims(
        conn,
        include_unverifiable=include_unverifiable,
        include_partial=include_partial,
        include_overconfident=include_overconfident,
        include_denominator=include_denominator,
        include_flagged=include_flagged,
        overconfident_limit=limit,
        evidence_ids=evidence_ids,
        claim_ids=claim_ids,
    )
    conn.close()

    n_unv = sum(1 for c in assessable if c["reason"] == "unverifiable")
    n_par = sum(1 for c in assessable if c["reason"] == "partial")
    n_over = sum(1 for c in assessable if c["reason"] == "overconfident")
    n_den = sum(1 for c in assessable if c["reason"] == "denominator_audit")
    n_flagged = sum(1 for c in assessable if c["reason"].startswith("flagged:"))
    parts = []
    if n_unv:
        parts.append(f"{n_unv} unverifiable")
    if n_par:
        parts.append(f"{n_par} partial")
    if n_over:
        parts.append(f"{n_over} overconfident")
    if n_den:
        parts.append(f"{n_den} denominator_audit")
    if n_flagged:
        parts.append(f"{n_flagged} flagged")
    print(f"Found {len(assessable)} assessable claims ({', '.join(parts)})")

    # Split into batches
    batches = [assessable[i : i + BATCH_SIZE] for i in range(0, len(assessable), BATCH_SIZE)]

    # Write batch context files and a manifest
    manifest = []
    for batch_num, batch in enumerate(batches, 1):
        path = _write_batch_context(batch, batch_num)
        manifest.append(
            {
                "batch": batch_num,
                "context_file": str(path),
                "claims": [c["claim_id"] for c in batch],
                "slugs": [c["slug"] for c in batch],
            }
        )
        print(f"  Batch {batch_num}: {len(batch)} claims → {path}")

    # Write manifest
    manifest_path = WORK_DIR / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write flat claims data for update step
    claims_path = WORK_DIR / "_claims_data.json"
    claims_path.write_text(json.dumps(assessable, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nManifest: {manifest_path}")
    print(f"Claims data: {claims_path}")
    print(f"\n{'=' * 70}")
    print("NEXT STEP: Run subagent assessment for each batch.")
    print(f"{'=' * 70}")
    print()
    print("For each batch, launch a Claude Code subagent:")
    for batch_num, batch in enumerate(batches, 1):
        ctx = WORK_DIR / f"_context_batch_{batch_num}.md"
        out = WORK_DIR / f"_assessments_batch_{batch_num}.json"
        print(f"\n  Batch {batch_num} ({len(batch)} claims):")
        print(f"    Read:  {ctx}")
        print(f"    Write: {out}")

    print("\nAfter all batches are assessed:")
    print("  uv run python scripts/reassess_claims.py update")


_EPISTEMIC_CONFIDENCE_CEILING = 0.8
_CLAMPED_EPISTEMIC_TYPES = {"prediction", "counterfactual"}


def update():
    """Parse subagent output and update claim verdicts in the DB."""
    from esbvaktin.claim_bank.operations import update_claim_verdict
    from esbvaktin.ground_truth.operations import get_connection
    from esbvaktin.pipeline.parse_outputs import _extract_json

    manifest = json.loads((WORK_DIR / "_manifest.json").read_text(encoding="utf-8"))

    # Build epistemic_type lookup from saved claims data (for confidence clamping)
    epistemic_by_id: dict[int, str] = {}
    claims_data_path = WORK_DIR / "_claims_data.json"
    if claims_data_path.exists():
        claims_data = json.loads(claims_data_path.read_text(encoding="utf-8"))
        for c in claims_data:
            if c.get("claim_id") and c.get("epistemic_type"):
                epistemic_by_id[c["claim_id"]] = c["epistemic_type"]

    conn = get_connection()
    updated = 0
    skipped = 0
    errors = []

    for batch_info in manifest:
        batch_num = batch_info["batch"]
        output_path = WORK_DIR / f"_assessments_batch_{batch_num}.json"

        if not output_path.exists():
            print(f"  Batch {batch_num}: MISSING — {output_path}")
            skipped += len(batch_info["claims"])
            continue

        try:
            raw_text = output_path.read_text(encoding="utf-8")
            raw = json.loads(_extract_json(raw_text))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Batch {batch_num}: JSON PARSE ERROR — {e}")
            errors.append((batch_num, str(e)))
            continue

        for item in raw:
            # Handle both flat (claim_id: N) and nested (claim: {id: N}) formats
            claim_id = item.get("claim_id")
            if not claim_id and isinstance(item.get("claim"), dict):
                claim_id = item["claim"].get("id")
            verdict = item.get("verdict") or item.get("new_verdict")
            if not claim_id or not verdict:
                print(f"    Skipping malformed item: {item}")
                skipped += 1
                continue

            # Validate verdict
            valid_verdicts = {
                "supported",
                "partially_supported",
                "unsupported",
                "misleading",
                "unverifiable",
            }
            if verdict not in valid_verdicts:
                print(f"    Invalid verdict '{verdict}' for claim {claim_id}")
                skipped += 1
                continue

            # Post-process Icelandic text if corrections package is available
            explanation_is = item.get("explanation_is", "")
            missing_context_is = item.get("missing_context_is")
            try:
                from esbvaktin.corrections.greynir import (
                    apply_fixes_to_text,
                    check_with_library,
                )

                for field_name, field_val in [
                    ("explanation_is", explanation_is),
                    ("missing_context_is", missing_context_is),
                ]:
                    if field_val and len(field_val) > 10:
                        sents = [(field_val, 1)]
                        results = check_with_library(sents)
                        if results:
                            fixed, count = apply_fixes_to_text(field_val, results)
                            if count > 0:
                                print(
                                    f"    GreynirCorrect: {count} fix(es) for {field_name} (claim {claim_id})"
                                )
                                if field_name == "explanation_is":
                                    explanation_is = fixed
                                else:
                                    missing_context_is = fixed
            except ImportError:
                pass  # corrections package not installed — skip

            # Apply confidence ceiling for prediction/counterfactual claims
            confidence = item.get("confidence", 0.5)
            epistemic_type = epistemic_by_id.get(claim_id, "factual")
            if epistemic_type in _CLAMPED_EPISTEMIC_TYPES:
                clamped = min(confidence, _EPISTEMIC_CONFIDENCE_CEILING)
                if clamped < confidence:
                    print(
                        f"    Confidence clamped {confidence:.2f}→{clamped:.2f} "
                        f"for {epistemic_type} claim {claim_id}"
                    )
                confidence = clamped

            try:
                update_claim_verdict(
                    claim_id=claim_id,
                    verdict=verdict,
                    explanation_is=explanation_is,
                    supporting_evidence=item.get("supporting_evidence", []),
                    contradicting_evidence=item.get("contradicting_evidence", []),
                    missing_context_is=missing_context_is,
                    confidence=confidence,
                    conn=conn,
                )
                # Clear reassessment flag if it was set
                conn.execute(
                    """UPDATE claims
                    SET needs_reassessment = FALSE, reassessment_reason = NULL
                    WHERE id = %(claim_id)s AND needs_reassessment = TRUE""",
                    {"claim_id": claim_id},
                )
                conn.commit()
                updated += 1
            except Exception as e:
                print(f"    Error updating claim {claim_id}: {e}")
                errors.append((claim_id, str(e)))

    conn.close()

    print(f"\n{'=' * 70}")
    print("RE-ASSESSMENT COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    if errors:
        print(f"  Errors:  {len(errors)}")
        for ref, err in errors:
            print(f"    - {ref}: {err}")

    print("\nNext: check results with")
    print("  uv run python scripts/reassess_claims.py status")
    print("  uv run python scripts/seed_claim_bank.py status")


def status():
    """Show current verdict distribution."""
    from esbvaktin.claim_bank.operations import get_claim_counts, get_total_claims
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()
    counts = get_claim_counts(conn)
    total = get_total_claims(conn)

    # Check for pending assessment files
    pending_batches = 0
    done_batches = 0
    if WORK_DIR.exists():
        manifest_path = WORK_DIR / "_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for batch_info in manifest:
                output = WORK_DIR / f"_assessments_batch_{batch_info['batch']}.json"
                if output.exists():
                    done_batches += 1
                else:
                    pending_batches += 1

    print(f"{'=' * 50}")
    print("CLAIM BANK STATUS")
    print(f"{'=' * 50}")
    print(f"  Total claims: {total}")
    print()
    for verdict, count in sorted(counts.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        bar = "#" * int(pct / 2)
        print(f"  {verdict:25s} {count:3d} ({pct:4.1f}%) {bar}")

    unverifiable = counts.get("unverifiable", 0)
    partial = counts.get("partially_supported", 0)
    print(f"\n  Unverifiable rate: {unverifiable}/{total} = {unverifiable / total * 100:.1f}%")
    print(f"  Partial rate:      {partial}/{total} = {partial / total * 100:.1f}%")

    # Flagged for reassessment (confidence decay trigger)
    flagged = conn.execute(
        "SELECT COUNT(*) FROM claims WHERE needs_reassessment = TRUE"
    ).fetchone()[0]
    if flagged > 0:
        print(f"\n  Flagged for reassessment: {flagged}")
        reasons = conn.execute(
            "SELECT reassessment_reason, COUNT(*) FROM claims "
            "WHERE needs_reassessment = TRUE GROUP BY reassessment_reason"
        ).fetchall()
        for reason, count in reasons:
            print(f"    {reason or '(no reason)'}: {count}")

    if pending_batches or done_batches:
        print(f"\n  Assessment batches: {done_batches} done, {pending_batches} pending")

    conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/reassess_claims.py [prepare|update|status]")
        print(
            "  prepare [--only unverifiable|partial|overconfident|denominator|flagged] [--limit N]"
        )
        print("  prepare --evidence ID1 ID2 ...          Claims citing these evidence entries")
        print("  prepare --claims 123 456 ...             Specific claims by ID")
        print("          Prepare context files (auto-cleans stale output files)")
        print("  update                                   Parse subagent output → DB")
        print("  status                                   Show verdict distribution")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "prepare":
        only = None
        limit = 30
        evidence_ids = None
        claim_ids = None

        if "--evidence" in sys.argv:
            idx = sys.argv.index("--evidence")
            evidence_ids = [a for a in sys.argv[idx + 1 :] if not a.startswith("--")]
            if not evidence_ids:
                print("--evidence requires at least one evidence ID")
                sys.exit(1)
        elif "--claims" in sys.argv:
            idx = sys.argv.index("--claims")
            claim_ids = [int(a) for a in sys.argv[idx + 1 :] if not a.startswith("--")]
            if not claim_ids:
                print("--claims requires at least one claim ID")
                sys.exit(1)
        else:
            if "--only" in sys.argv:
                idx = sys.argv.index("--only")
                if idx + 1 < len(sys.argv):
                    only = sys.argv[idx + 1]
                    if only not in (
                        "unverifiable",
                        "partial",
                        "overconfident",
                        "denominator",
                        "flagged",
                    ):
                        print(
                            f"Unknown --only value: {only} "
                            f"(use 'unverifiable', 'partial', 'overconfident', 'denominator', or 'flagged')"
                        )
                        sys.exit(1)
            if "--limit" in sys.argv:
                idx = sys.argv.index("--limit")
                if idx + 1 < len(sys.argv):
                    limit = int(sys.argv[idx + 1])

        prepare(only=only, limit=limit, evidence_ids=evidence_ids, claim_ids=claim_ids)
    elif cmd == "update":
        update()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
