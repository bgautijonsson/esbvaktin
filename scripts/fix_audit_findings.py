"""Apply fixes from the 2026-03-14 evidence audit.

Handles:
  1. High-severity statement corrections (7)
  2. Metadata corrections (subtopic/source_type errors)
  3. Clear-cut medium fixes (stale numbers, outdated info)
  4. Duplicate retirement (update claim references, then delete)

Usage:
    uv run python scripts/fix_audit_findings.py --dry-run   # Preview changes
    uv run python scripts/fix_audit_findings.py              # Apply changes
"""

import argparse
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("DATABASE_URL", "postgresql://esb:localdev@localhost/esbvaktin")


# ── Helpers ──────────────────────────────────────────────────────────

def get_conn() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)


def patch_statement(conn, eid: str, old_fragment: str, new_fragment: str, label: str):
    """Replace a fragment in an evidence entry's statement."""
    cur = conn.execute(
        "SELECT statement FROM evidence WHERE evidence_id = %s", (eid,)
    )
    row = cur.fetchone()
    if not row:
        print(f"  [SKIP] {eid} not found in DB")
        return False
    statement = row[0]
    if old_fragment not in statement:
        print(f"  [SKIP] {eid}: old fragment not found — may already be fixed")
        return False
    new_statement = statement.replace(old_fragment, new_fragment, 1)
    print(f"  [FIX]  {eid}: {label}")
    if not DRY_RUN:
        conn.execute(
            "UPDATE evidence SET statement = %s, statement_is = NULL, "
            "is_proofread_hash = NULL, updated_at = now() WHERE evidence_id = %s",
            (new_statement, eid),
        )
    return True


def patch_caveats(conn, eid: str, old_fragment: str, new_fragment: str, label: str):
    """Replace a fragment in an evidence entry's caveats."""
    cur = conn.execute(
        "SELECT caveats FROM evidence WHERE evidence_id = %s", (eid,)
    )
    row = cur.fetchone()
    if not row or not row[0]:
        print(f"  [SKIP] {eid} caveats not found")
        return False
    caveats = row[0]
    if old_fragment not in caveats:
        print(f"  [SKIP] {eid}: old caveats fragment not found — may already be fixed")
        return False
    new_caveats = caveats.replace(old_fragment, new_fragment, 1)
    print(f"  [FIX]  {eid}: {label}")
    if not DRY_RUN:
        conn.execute(
            "UPDATE evidence SET caveats = %s, caveats_is = NULL, "
            "is_proofread_hash = NULL, updated_at = now() WHERE evidence_id = %s",
            (new_caveats, eid),
        )
    return True


_ALLOWED_METADATA_FIELDS = {"subtopic", "source_type", "confidence", "topic"}


def fix_metadata(conn, eid: str, field: str, old_val: str, new_val: str, label: str):
    """Fix a metadata field (subtopic, source_type)."""
    if field not in _ALLOWED_METADATA_FIELDS:
        raise ValueError(f"Field {field!r} not in allowed metadata fields: {_ALLOWED_METADATA_FIELDS}")
    cur = conn.execute(
        f"SELECT {field} FROM evidence WHERE evidence_id = %s", (eid,)
    )
    row = cur.fetchone()
    if not row:
        print(f"  [SKIP] {eid} not found")
        return False
    if row[0] != old_val:
        print(f"  [SKIP] {eid}.{field} is '{row[0]}', expected '{old_val}'")
        return False
    print(f"  [META] {eid}.{field}: '{old_val}' → '{new_val}' ({label})")
    if not DRY_RUN:
        conn.execute(
            f"UPDATE evidence SET {field} = %s, updated_at = now() WHERE evidence_id = %s",
            (new_val, eid),
        )
    return True


def retire_duplicate(conn, retire_id: str, keep_id: str, label: str):
    """Retire a duplicate entry: update claim references, then delete."""
    # Check it exists
    cur = conn.execute(
        "SELECT evidence_id FROM evidence WHERE evidence_id = %s", (retire_id,)
    )
    if not cur.fetchone():
        print(f"  [SKIP] {retire_id} already deleted")
        return False

    print(f"  [DUP]  Retire {retire_id} (keep {keep_id}): {label}")

    if not DRY_RUN:
        # Update claims.supporting_evidence: replace retired ID with kept ID
        conn.execute(
            """
            UPDATE claims SET
                supporting_evidence = array_replace(supporting_evidence, %s, %s),
                updated_at = now()
            WHERE %s = ANY(supporting_evidence)
            """,
            (retire_id, keep_id, retire_id),
        )
        # Update claims.contradicting_evidence similarly
        conn.execute(
            """
            UPDATE claims SET
                contradicting_evidence = array_replace(contradicting_evidence, %s, %s),
                updated_at = now()
            WHERE %s = ANY(contradicting_evidence)
            """,
            (retire_id, keep_id, retire_id),
        )
        # Remove duplicates from arrays (in case keep_id was already there)
        conn.execute(
            """
            UPDATE claims SET
                supporting_evidence = (
                    SELECT array_agg(DISTINCT elem)
                    FROM unnest(supporting_evidence) elem
                ),
                contradicting_evidence = (
                    SELECT array_agg(DISTINCT elem)
                    FROM unnest(contradicting_evidence) elem
                )
            WHERE %s = ANY(supporting_evidence) OR %s = ANY(contradicting_evidence)
            """,
            (keep_id, keep_id),
        )
        # Delete the retired entry
        conn.execute(
            "DELETE FROM evidence WHERE evidence_id = %s", (retire_id,)
        )
    return True


# ── Fix definitions ──────────────────────────────────────────────────

def apply_high_severity(conn):
    """Fix 7 high-severity contradictions."""
    print("\n=== HIGH SEVERITY (7) ===")
    count = 0

    # 1. EEA-LEGAL-012: Denmark did NOT adopt the euro
    count += patch_statement(
        conn, "EEA-LEGAL-012",
        "euro opt-out was removed when Denmark adopted it in 2025",
        "euro opt-out remains in force as of 2026; Denmark has not adopted the euro",
        "Denmark did NOT adopt the euro",
    )

    # 2. POLITICAL-DATA-010: Iceland did not "formally withdraw"
    count += patch_statement(
        conn, "POLITICAL-DATA-010",
        "Iceland formally withdrew its application on 12 March 2015",
        "Foreign Minister Gunnar Bragi Sveinsson sent a letter on 12 March 2015 "
        "stating Iceland should no longer be regarded as a candidate country; however, "
        "the EU did not formally recognise this as a withdrawal, and the European "
        "Commission stated the application remains valid",
        "EU application withdrawal was not formally recognised",
    )

    # 3. TRADE-DATA-002: fishery products DO have EEA tariff-free access
    count += patch_statement(
        conn, "TRADE-DATA-002",
        "excluding agricultural and fishery products",
        "excluding most agricultural products; fisheries products have preferential/"
        "tariff-free access under EEA Protocol 9 (fish and marine products) and "
        "Protocol 3 (processed fisheries)",
        "Fisheries products have EEA tariff-free access",
    )

    # 4. HOUS-DATA-005: CBI rate is 7.25%, not 8.5%
    count += patch_statement(
        conn, "HOUS-DATA-005",
        "8–9%",
        "7.5–8.5%",
        "Non-indexed mortgage rate floor aligned with HOUSING-DATA-008",
    )
    # Also fix the stale CBI base rate reference if present
    cur = conn.execute(
        "SELECT statement FROM evidence WHERE evidence_id = 'HOUS-DATA-005'"
    )
    row = cur.fetchone()
    if row and "8.5%" in row[0] and "Seðlabanki" in row[0]:
        patch_statement(
            conn, "HOUS-DATA-005",
            "8.5%",
            "7.25%",
            "CBI base rate updated to current 7.25%",
        )

    # 5. PREC-DATA-019: Croatian housing loan rate was 3.64%, not ~3.0%
    count += patch_statement(
        conn, "PREC-DATA-019",
        "approximately 3.0%",
        "approximately 3.64% (January 2024, per CNB Governor Vujčić/BIS Review)",
        "Croatian loan rate corrected to 3.64%",
    )

    # 6. AGRI-DATA-018: 33 chapters (not 35), 6 never opened (not 8)
    count += patch_statement(
        conn, "AGRI-DATA-018",
        "Of the 35 negotiating chapters",
        "Of the 33 standard negotiating chapters",
        "Chapter count corrected to 33 (consistent with EEA-DATA-009, PREC-HIST-004)",
    )
    patch_statement(
        conn, "AGRI-DATA-018",
        "8 chapters were never opened",
        "6 chapters were never opened",
        "Unopened chapter count corrected to 6",
    )

    # 7. AGRI-LEGAL-003: also correct to 6 chapters (was listed as 6 but
    #    the chapter list was wrong — this one is already at 6, just needs
    #    the list fixed)
    # The cross-topic audit (batch 13) flagged the 33 vs 35 issue primarily
    # in AGRI-DATA-018. AGRI-LEGAL-003 already says 6 but has wrong list items.
    # We'll leave the list as-is since it requires domain verification.

    print(f"  Applied: {count} high-severity fixes")
    return count


def apply_metadata_fixes(conn):
    """Fix metadata errors (wrong subtopic/source_type)."""
    print("\n=== METADATA CORRECTIONS ===")
    count = 0

    # PREC-DATA-012: Croatia content mislabelled as Norway
    count += fix_metadata(
        conn, "PREC-DATA-012", "subtopic",
        "norway_storting_eu_debate_2026",
        "croatia_euro_housing_loan_impact",
        "Croatia content, not Norway",
    )
    count += fix_metadata(
        conn, "PREC-DATA-012", "source_type",
        "parliamentary_record",
        "expert_analysis",
        "BIS Review, not parliamentary record",
    )

    # PREC-DATA-013: Finland content mislabelled as Denmark
    count += fix_metadata(
        conn, "PREC-DATA-013", "subtopic",
        "denmark_ccpi_climate_ranking_2024",
        "finland_euro_economic_performance",
        "Finland content, not Denmark",
    )

    # FISH-LEGAL-004: Norway subtopic but EU CFP content
    count += fix_metadata(
        conn, "FISH-LEGAL-004", "subtopic",
        "norway_fisheries_model",
        "eu_cfp_landing_obligation",
        "Content is about EU CFP, not Norway",
    )

    # POLL-DATA-007: wrong subtopic and source_type (duplicate of POLL-DATA-017)
    # Will be retired as duplicate instead

    print(f"  Applied: {count} metadata fixes")
    return count


def apply_medium_fixes(conn):
    """Fix clear-cut medium-severity issues (stale numbers, wrong citations)."""
    print("\n=== MEDIUM SEVERITY (clear-cut) ===")
    count = 0

    # EEA-LEGAL-010: veto WAS invoked by Norway
    count += patch_caveats(
        conn, "EEA-LEGAL-010",
        "the veto has never been formally invoked",
        "Norway has invoked Article 102 reservations on several occasions "
        "(including the Third Postal Directive and the AIFM Directive), though "
        "most were eventually resolved. Iceland has never invoked it",
        "Article 102 veto correction (Norway HAS invoked it)",
    )

    # EEA-LEGAL-024: internal contradiction in caveats
    count += patch_caveats(
        conn, "EEA-LEGAL-024",
        "The Article 102 reservation right has never been formally invoked "
        "in over 30 years of the EEA Agreement's operation and is considered "
        "a nuclear option",
        "Norway has invoked Article 102 reservations multiple times (including "
        "the Third Postal Directive and AIFM Directive), though most were "
        "eventually resolved. Iceland has never invoked it. The political cost "
        "of invoking it is considered high",
        "Article 102 caveats: remove false 'never invoked' claim",
    )

    # SOV-DATA-003: EP seats 705 → 720, Malta population
    count += patch_statement(
        conn, "SOV-DATA-003",
        "705",
        "720",
        "EP seat count updated to post-2024 figure",
    )
    patch_statement(
        conn, "SOV-DATA-003",
        "~520,000",
        "~540,000",
        "Malta population updated",
    )

    # AGRI-DATA-017: farm count 3,500 → 2,300
    count += patch_statement(
        conn, "AGRI-DATA-017",
        "approximately 3,500 farms",
        "approximately 2,300 farms",
        "Farm count aligned with Hagstofa (AGRI-DATA-003)",
    )

    # AGRI-DATA-013: GDP share 1.5% → 1.0–1.2%, employment 4,000 → 3,500
    count += patch_statement(
        conn, "AGRI-DATA-013",
        "roughly 1.5% of GDP",
        "roughly 1.0–1.2% of GDP",
        "GDP share aligned with Hagstofa (AGRI-DATA-003)",
    )
    patch_statement(
        conn, "AGRI-DATA-013",
        "employs about 4,000 people (2.3% of the workforce)",
        "employs about 3,500 people (~1.7% of the workforce)",
        "Employment aligned with Hagstofa (AGRI-DATA-003)",
    )

    # HOUS-DATA-006: wrong Glaeser citation (2008 → 2012)
    count += patch_statement(
        conn, "HOUS-DATA-006",
        "Glaeser et al. 2008",
        "Glaeser, Gottlieb & Gyourko (2012)",
        "Correct Glaeser citation for capitalisation estimate",
    )
    # Also fix if the full citation appears
    patch_statement(
        conn, "HOUS-DATA-006",
        "Glaeser, Gyourko & Saiz 2008",
        "Glaeser, Gottlieb & Gyourko 2012",
        "Correct full Glaeser citation",
    )

    # POLITICAL-DATA-003: Ragnar Þór Ingólfsson is MP, not minister
    # This is complex (removing from cabinet list) — flag for manual review
    print("  [NOTE] POLITICAL-DATA-003: Ragnar Þór Ingólfsson listed as minister "
          "but is MP only — needs manual statement rewrite")

    # POL-DATA-003, POL-DATA-008, POL-DATA-009: VG/Píratar no longer in parliament
    for eid in ("POL-DATA-003", "POL-DATA-008", "POL-DATA-009"):
        cur = conn.execute(
            "SELECT caveats FROM evidence WHERE evidence_id = %s", (eid,)
        )
        row = cur.fetchone()
        caveat_note = (
            " Note: following the 2024 elections, neither VG nor Píratar hold "
            "seats in the 157th Althingi session."
        )
        if row and row[0] and "157th Althingi" not in row[0]:
            print(f"  [FIX]  {eid}: Add caveat noting VG/Píratar lost seats in 2024")
            if not DRY_RUN:
                conn.execute(
                    "UPDATE evidence SET caveats = caveats || %s, caveats_is = NULL, "
                    "is_proofread_hash = NULL, updated_at = now() "
                    "WHERE evidence_id = %s",
                    (caveat_note, eid),
                )
            count += 1

    # PREC-DATA-002: OBR estimate is GDP, not productivity
    count += patch_statement(
        conn, "PREC-DATA-002",
        "productivity",
        "GDP",
        "OBR estimate metric: GDP not productivity",
    )

    print(f"  Applied: {count} medium fixes")
    return count


def apply_duplicate_retirement(conn):
    """Retire 20 duplicate entries, updating claim references."""
    print("\n=== DUPLICATE RETIREMENT ===")

    duplicates = [
        # (retire, keep, label)
        # Polling: exact duplicates
        ("POLL-DATA-007", "POLL-DATA-017", "Identical Gallup methodology text"),
        ("POLL-DATA-008", "POLL-DATA-018", "Identical Gallup demographics text"),
        # Agriculture
        ("AGRI-LEGAL-001", "AGRI-DATA-015", "CAP budget — DATA-015 more detailed"),
        ("AGRI-DATA-021", "AGRI-LEGAL-002", "Article 142 aid — LEGAL-002 more precise"),
        # Currency
        ("CURRENCY-DATA-008", "CURRENCY-DATA-013", "Inflation volatility — DATA-013 more comprehensive"),
        ("CURR-DATA-004", "CURRENCY-DATA-015", "CBI-ECB rate differential — identical data"),
        # Org positions
        ("ORG-DATA-002", "POL-DATA-019", "BÍ position — POL-DATA-019 more detailed"),
        ("POL-DATA-004", "POL-DATA-012", "SA position — subsumed by POL-DATA-012 + 013"),
        ("POL-DATA-005", "POL-DATA-014", "LÍÚ position — subsumed by POL-DATA-014"),
        # Precedents
        ("PREC-HIST-008", "PREC-HIST-017", "Greenland withdrawal — HIST-017 more detailed"),
        ("PREC-HIST-009", "PREC-HIST-018", "Finland accession — HIST-018 more comprehensive"),
        ("PREC-HIST-007", "PREC-HIST-015", "Swiss bilateral — HIST-015 more detailed"),
        ("PREC-HIST-003", "PREC-DATA-008", "Brexit GDP impact — DATA-008 more detailed"),
        ("PREC-HIST-006", "PREC-HIST-011", "Croatia accession — HIST-011 more detailed"),
        ("PREC-DATA-009", "PREC-DATA-018", "Norway fisheries — DATA-018 more recent"),
        # Sovereignty
        ("SOV-DATA-003", "SOV-DATA-017", "EU voting weight — DATA-017 more accurate (720 seats)"),
        # Cross-topic duplicates
        ("PREC-HIST-010", "SOV-LEGAL-010", "Denmark opt-outs — cross-referenced"),
        ("SOV-LEGAL-009", "EEA-DATA-011", "EEA democratic deficit — DATA-011 more detailed"),
        # Agriculture (chapter negotiations) — keep both after fixing, they have
        # different angles. Skip this pair.
        # AGRI-DATA-016/020 — keep both, they cover different CAP phasing aspects
    ]

    count = 0
    for retire_id, keep_id, label in duplicates:
        if retire_duplicate(conn, retire_id, keep_id, label):
            count += 1

    print(f"  Retired: {count} duplicate entries")
    return count


# ── Main ─────────────────────────────────────────────────────────────

DRY_RUN = False


def main():
    global DRY_RUN
    parser = argparse.ArgumentParser(description="Apply evidence audit fixes")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    args = parser.parse_args()
    DRY_RUN = args.dry_run

    if DRY_RUN:
        print("DRY RUN — no changes will be applied\n")

    conn = get_conn()

    # Count before
    before = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]

    h = apply_high_severity(conn)
    m = apply_metadata_fixes(conn)
    med = apply_medium_fixes(conn)
    d = apply_duplicate_retirement(conn)

    # Count after
    after = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]

    print(f"\n{'=' * 60}")
    print(f"SUMMARY {'(DRY RUN)' if DRY_RUN else ''}")
    print(f"{'=' * 60}")
    print(f"  High-severity fixes:    {h}")
    print(f"  Metadata fixes:         {m}")
    print(f"  Medium fixes:           {med}")
    print(f"  Duplicates retired:     {d}")
    print(f"  Evidence entries:       {before} → {after} ({after - before:+d})")

    if not DRY_RUN:
        # Flag entries needing IS regeneration
        cur = conn.execute(
            "SELECT COUNT(*) FROM evidence WHERE statement_is IS NULL"
        )
        needs_is = cur.fetchone()[0]
        if needs_is:
            print(f"\n  ⚠ {needs_is} entries need IS translation regeneration")
            print("    Run: uv run python scripts/generate_evidence_is.py prepare")

        # Flag for manual review
        print("\n  Manual review still needed:")
        print("    - POLITICAL-DATA-003: Ragnar Þór Ingólfsson cabinet error")
        print("    - AGRI-DATA-004/022: agricultural support scope clarification")
        print("    - AGRI-LEGAL-003: chapter list verification against MFA source")
        print("    - ORG-DATA-001/POL-DATA-016: SI position (leadership vs members)")

    conn.close()


if __name__ == "__main__":
    main()
