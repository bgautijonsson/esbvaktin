#!/usr/bin/env python3
"""Audit Ground Truth evidence for internal contradictions.

Groups evidence entries by topic, then uses a subagent to identify
factual contradictions within each topic group. Also flags potential
duplicates (similarity >= 0.95).

Usage:
    # Step 1: Group by topic and write context files
    uv run python scripts/audit_evidence.py prepare

    # Step 2: Subagent reads each context file and writes findings
    # → see printed instructions after prepare

    # Step 3: Parse findings and show report
    uv run python scripts/audit_evidence.py report

    # Show topic stats and audit progress
    uv run python scripts/audit_evidence.py status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORK_DIR = Path("data/audit")
DUPLICATE_THRESHOLD = 0.95  # Flag as potential duplicates
HIGH_SIM_THRESHOLD = 0.85  # Highlight high-similarity pairs within topic groups
MAX_ENTRIES_PER_BATCH = 40  # Max evidence entries per agent batch


def _get_topic_groups(conn) -> dict[str, list[dict]]:
    """Fetch all evidence entries grouped by topic."""
    rows = conn.execute(
        """
        SELECT evidence_id, domain, topic, subtopic, statement,
               source_name, source_url, source_date, source_type,
               confidence, caveats
        FROM evidence
        WHERE embedding IS NOT NULL
        ORDER BY topic, evidence_id
        """
    ).fetchall()

    groups: dict[str, list[dict]] = {}
    for r in rows:
        entry = {
            "evidence_id": r[0],
            "domain": r[1],
            "topic": r[2],
            "subtopic": r[3],
            "statement": r[4],
            "source_name": r[5],
            "source_url": r[6],
            "source_date": str(r[7]) if r[7] else None,
            "source_type": r[8],
            "confidence": r[9],
            "caveats": r[10],
        }
        groups.setdefault(r[2], []).append(entry)

    return groups


def _get_high_similarity_pairs(conn, topic: str) -> list[tuple[str, str, float]]:
    """Find high-similarity pairs within a topic."""
    rows = conn.execute(
        """
        SELECT
            a.evidence_id, b.evidence_id,
            1 - (a.embedding <=> b.embedding) AS similarity
        FROM evidence a
        JOIN evidence b ON a.evidence_id < b.evidence_id
        WHERE a.embedding IS NOT NULL AND b.embedding IS NOT NULL
          AND a.topic = %(topic)s AND b.topic = %(topic)s
          AND 1 - (a.embedding <=> b.embedding) >= %(threshold)s
        ORDER BY similarity DESC
        """,
        {"topic": topic, "threshold": HIGH_SIM_THRESHOLD},
    ).fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]


def _get_cross_topic_high_pairs(conn) -> list[tuple[str, str, float]]:
    """Find high-similarity pairs across different topics — these are
    most likely to contain contradictions (same fact, different source entries)."""
    rows = conn.execute(
        """
        SELECT
            a.evidence_id, b.evidence_id,
            1 - (a.embedding <=> b.embedding) AS similarity
        FROM evidence a
        JOIN evidence b ON a.evidence_id < b.evidence_id
        WHERE a.embedding IS NOT NULL AND b.embedding IS NOT NULL
          AND a.topic != b.topic
          AND 1 - (a.embedding <=> b.embedding) >= %(threshold)s
        ORDER BY similarity DESC
        """,
        {"threshold": HIGH_SIM_THRESHOLD},
    ).fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]


def _fetch_entries_by_ids(conn, ids: list[str]) -> list[dict]:
    """Fetch evidence entries by IDs."""
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    rows = conn.execute(
        f"""
        SELECT evidence_id, domain, topic, subtopic, statement,
               source_name, source_url, source_date, source_type,
               confidence, caveats
        FROM evidence
        WHERE evidence_id IN ({placeholders})
        ORDER BY evidence_id
        """,
        ids,
    ).fetchall()
    return [
        {
            "evidence_id": r[0], "domain": r[1], "topic": r[2],
            "subtopic": r[3], "statement": r[4], "source_name": r[5],
            "source_url": r[6], "source_date": str(r[7]) if r[7] else None,
            "source_type": r[8], "confidence": r[9], "caveats": r[10],
        }
        for r in rows
    ]


def _write_topic_batch(
    topic_groups: list[dict], batch_num: int, total_batches: int
) -> Path:
    """Write a context file for a batch of topic groups."""
    path = WORK_DIR / f"_context_audit_{batch_num}.md"

    lines = [
        f"# Evidence Contradiction Audit — Batch {batch_num}/{total_batches}\n",
        "You are auditing the ESBvaktin Ground Truth evidence database for internal",
        "contradictions. Each section below contains evidence entries grouped by topic.",
        "",
        "## Your task",
        "",
        "For each topic group, identify pairs of entries that make **mutually exclusive",
        "factual claims** — statements that cannot both be true.",
        "",
        "**Flag these:**",
        "- Two entries stating opposite facts (e.g. 'X participates through the EEA'",
        "  vs 'X participates through a bilateral agreement, not the EEA')",
        "- Incompatible numbers or dates for the same metric",
        "- One entry asserting something while another denies it",
        "",
        "**Do NOT flag:**",
        "- Entries covering different aspects of the same topic without conflict",
        "- Different levels of detail (general vs specific) unless the general one is wrong",
        "- Entries with caveats that acknowledge uncertainty",
        "- Policy opinions or framing differences",
        "",
        "High-similarity pairs (>= 0.85 cosine) are highlighted — these share similar",
        "semantic content and are the most likely locations for contradictions.",
        "",
    ]

    for tg in topic_groups:
        topic_name = tg["topic"]
        entries = tg["entries"]
        high_pairs = tg["high_sim_pairs"]

        lines.append(f"## Topic: {topic_name} ({len(entries)} entries)")
        lines.append("")

        if high_pairs:
            lines.append("**High-similarity pairs to check closely:**")
            for a, b, sim in high_pairs:
                marker = " ⚠️ POTENTIAL DUPLICATE" if sim >= DUPLICATE_THRESHOLD else ""
                lines.append(f"- {a} ↔ {b}: {sim:.3f}{marker}")
            lines.append("")

        for entry in entries:
            lines.append(f"### {entry['evidence_id']}")
            lines.append(f"- **Subtopic:** {entry['subtopic']}")
            lines.append(f"- **Domain:** {entry['domain']}")
            lines.append(f"- **Source:** {entry['source_name']} ({entry['source_type']})")
            lines.append(f"- **Confidence:** {entry['confidence']}")
            lines.append("")
            lines.append(f"**Statement:** {entry['statement']}")
            lines.append("")
            if entry.get("caveats"):
                lines.append(f"**Caveats:** {entry['caveats']}")
                lines.append("")

    # Cross-topic section if present
    [tg for tg in topic_groups if tg.get("is_cross_topic")]
    # (handled inline above)

    # Output format
    lines.extend([
        "## Output",
        "",
        f"Write your findings as a raw JSON array to `data/audit/_findings_{batch_num}.json`.",
        "",
        "Each contradiction found:",
        "```json",
        "{",
        '  "entry_a": "EVIDENCE-ID",',
        '  "entry_b": "EVIDENCE-ID",',
        '  "contradiction": "description of the factual conflict",',
        '  "likely_correct": "EVIDENCE-ID",',
        '  "reasoning": "why this entry is more authoritative (cite legal instruments, source type)",',
        '  "severity": "high | medium | low",',
        '  "suggested_fix": "what to change in the incorrect entry"',
        "}",
        "```",
        "",
        "For potential duplicates (similarity >= 0.95):",
        "```json",
        "{",
        '  "entry_a": "EVIDENCE-ID",',
        '  "entry_b": "EVIDENCE-ID",',
        '  "type": "duplicate",',
        '  "note": "which should be kept or merged"',
        "}",
        "```",
        "",
        "For topics with no issues:",
        "```json",
        "{",
        '  "topic": "topic_name",',
        '  "status": "no_contradictions",',
        '  "note": "brief summary"',
        "}",
        "```",
        "",
        "**Severity guide:**",
        "- **high** — direct factual contradiction that would cause wrong claim verdicts",
        "- **medium** — inconsistent claims that could confuse assessment",
        "- **low** — minor discrepancies in numbers, dates, or framing",
    ])

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def prepare():
    """Group evidence by topic and write context files for subagent audit."""
    from esbvaktin.ground_truth.operations import get_connection

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()

    print("Grouping evidence by topic...")
    topic_groups = _get_topic_groups(conn)
    print(f"  Found {len(topic_groups)} topics, "
          f"{sum(len(v) for v in topic_groups.values())} total entries")

    for topic, entries in sorted(topic_groups.items(), key=lambda x: -len(x[1])):
        print(f"    {topic}: {len(entries)} entries")

    # Get high-similarity pairs per topic
    print("\nFinding high-similarity pairs per topic...")
    topic_data = []
    for topic, entries in sorted(topic_groups.items()):
        high_pairs = _get_high_similarity_pairs(conn, topic)
        topic_data.append({
            "topic": topic,
            "entries": entries,
            "high_sim_pairs": high_pairs,
        })
        if high_pairs:
            dupes = sum(1 for _, _, s in high_pairs if s >= DUPLICATE_THRESHOLD)
            print(f"    {topic}: {len(high_pairs)} high-sim pairs"
                  f"{f' ({dupes} potential duplicates)' if dupes else ''}")

    # Get cross-topic high-similarity pairs
    print("\nFinding cross-topic high-similarity pairs...")
    cross_pairs = _get_cross_topic_high_pairs(conn)
    if cross_pairs:
        print(f"  Found {len(cross_pairs)} cross-topic pairs (>= {HIGH_SIM_THRESHOLD})")
        # Collect unique entry IDs from cross-topic pairs
        cross_ids = set()
        for a, b, _ in cross_pairs:
            cross_ids.add(a)
            cross_ids.add(b)
        cross_entries = _fetch_entries_by_ids(conn, list(cross_ids))
        topic_data.append({
            "topic": "CROSS-TOPIC (entries from different topics with high similarity)",
            "entries": cross_entries,
            "high_sim_pairs": cross_pairs,
            "is_cross_topic": True,
        })

    conn.close()

    # Batch topic groups, respecting max entries per batch
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_count = 0

    for td in topic_data:
        entry_count = len(td["entries"])
        if current_count + entry_count > MAX_ENTRIES_PER_BATCH and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_count = 0
        current_batch.append(td)
        current_count += entry_count

    if current_batch:
        batches.append(current_batch)

    # Write batch context files and manifest
    manifest = []
    for batch_num, batch in enumerate(batches, 1):
        path = _write_topic_batch(batch, batch_num, len(batches))
        topics = [td["topic"] for td in batch]
        entry_count = sum(len(td["entries"]) for td in batch)
        manifest.append({
            "batch": batch_num,
            "context_file": str(path),
            "topics": topics,
            "entry_count": entry_count,
        })
        print(f"\n  Batch {batch_num}: {len(batch)} topic(s), "
              f"{entry_count} entries → {path}")

    manifest_path = WORK_DIR / "_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nManifest: {manifest_path}")
    print(f"\n{'='*70}")
    print("NEXT STEP: Run evidence-auditor subagent for each batch.")
    print(f"{'='*70}")
    for batch_num, batch in enumerate(batches, 1):
        entry_count = sum(len(td["entries"]) for td in batch)
        ctx = WORK_DIR / f"_context_audit_{batch_num}.md"
        out = WORK_DIR / f"_findings_{batch_num}.json"
        print(f"\n  Batch {batch_num} ({entry_count} entries):")
        print(f"    Read:  {ctx}")
        print(f"    Write: {out}")

    print("\nAfter all batches are audited:")
    print("  uv run python scripts/audit_evidence.py report")


def report():
    """Parse subagent findings and display contradiction report."""
    from esbvaktin.pipeline.parse_outputs import _extract_json

    manifest_path = WORK_DIR / "_manifest.json"
    if not manifest_path.exists():
        print("No manifest found. Run 'prepare' first.")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    all_findings = []
    missing = 0

    for batch_info in manifest:
        batch_num = batch_info["batch"]
        output_path = WORK_DIR / f"_findings_{batch_num}.json"

        if not output_path.exists():
            print(f"  Batch {batch_num}: MISSING — {output_path}")
            missing += 1
            continue

        try:
            raw_text = output_path.read_text(encoding="utf-8")
            findings = json.loads(_extract_json(raw_text))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Batch {batch_num}: JSON PARSE ERROR — {e}")
            continue

        for f in findings:
            f["batch"] = batch_num
        all_findings.extend(findings)

    # Categorise findings
    contradictions = [f for f in all_findings if f.get("entry_a") and f.get("severity")]
    duplicates = [f for f in all_findings if f.get("type") == "duplicate"]
    clean = [f for f in all_findings if f.get("status") == "no_contradictions"]

    # Sort contradictions by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    contradictions.sort(key=lambda f: severity_order.get(f.get("severity", "low"), 3))

    print(f"\n{'='*70}")
    print("EVIDENCE AUDIT REPORT")
    print(f"{'='*70}")
    print(f"  Batches processed: {len(manifest) - missing}/{len(manifest)}")
    print(f"  Contradictions found: {len(contradictions)}")
    print(f"  Potential duplicates: {len(duplicates)}")
    print(f"  Clean topics: {len(clean)}")

    high = [f for f in contradictions if f.get("severity") == "high"]
    medium = [f for f in contradictions if f.get("severity") == "medium"]
    low = [f for f in contradictions if f.get("severity") == "low"]

    print(f"\n  By severity: {len(high)} high, {len(medium)} medium, {len(low)} low")

    if duplicates:
        print(f"\n{'─'*70}")
        print("POTENTIAL DUPLICATES")
        print(f"{'─'*70}")
        for f in duplicates:
            print(f"\n  {f['entry_a']} ↔ {f['entry_b']}")
            print(f"  {f.get('note', '')}")

    if high:
        print(f"\n{'─'*70}")
        print("HIGH SEVERITY CONTRADICTIONS")
        print(f"{'─'*70}")
        for f in high:
            print(f"\n  {f['entry_a']} ↔ {f['entry_b']}")
            print(f"  Contradiction: {f['contradiction']}")
            print(f"  Likely correct: {f['likely_correct']}")
            print(f"  Reasoning: {f['reasoning']}")
            print(f"  Fix: {f['suggested_fix']}")

    if medium:
        print(f"\n{'─'*70}")
        print("MEDIUM SEVERITY")
        print(f"{'─'*70}")
        for f in medium:
            print(f"\n  {f['entry_a']} ↔ {f['entry_b']}")
            print(f"  {f['contradiction']}")
            print(f"  Likely correct: {f['likely_correct']}")

    if low:
        print(f"\n{'─'*70}")
        print(f"LOW SEVERITY: {len(low)} findings (use --verbose to show)")
        if "--verbose" in sys.argv:
            for f in low:
                print(f"  {f['entry_a']} ↔ {f['entry_b']}: {f['contradiction']}")

    # Write consolidated report
    report_path = WORK_DIR / "audit_report.json"
    report_path.write_text(
        json.dumps({
            "contradictions": contradictions,
            "duplicates": duplicates,
            "clean_topics": len(clean),
            "total_findings": len(all_findings),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nFull report: {report_path}")


def status():
    """Show topic stats and audit progress."""
    from esbvaktin.ground_truth.operations import get_connection

    conn = get_connection()

    total = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE embedding IS NOT NULL"
    ).fetchone()[0]

    rows = conn.execute(
        """
        SELECT topic, COUNT(*) as cnt
        FROM evidence WHERE embedding IS NOT NULL
        GROUP BY topic ORDER BY cnt DESC
        """
    ).fetchall()

    print(f"Evidence entries with embeddings: {total}")
    print(f"Topics: {len(rows)}")
    for topic, cnt in rows:
        print(f"  {topic}: {cnt}")

    # Check cross-topic high-sim pairs
    cross = conn.execute(
        """
        SELECT COUNT(*)
        FROM evidence a JOIN evidence b ON a.evidence_id < b.evidence_id
        WHERE a.embedding IS NOT NULL AND b.embedding IS NOT NULL
          AND a.topic != b.topic
          AND 1 - (a.embedding <=> b.embedding) >= %(t)s
        """,
        {"t": HIGH_SIM_THRESHOLD},
    ).fetchone()[0]
    print(f"\nCross-topic pairs (>= {HIGH_SIM_THRESHOLD}): {cross}")

    # Duplicate candidates
    dupes = conn.execute(
        """
        SELECT a.evidence_id, b.evidence_id,
               1 - (a.embedding <=> b.embedding) AS sim
        FROM evidence a JOIN evidence b ON a.evidence_id < b.evidence_id
        WHERE a.embedding IS NOT NULL AND b.embedding IS NOT NULL
          AND 1 - (a.embedding <=> b.embedding) >= %(t)s
        ORDER BY sim DESC
        """,
        {"t": DUPLICATE_THRESHOLD},
    ).fetchall()
    if dupes:
        print(f"Potential duplicates (>= {DUPLICATE_THRESHOLD}):")
        for a, b, s in dupes:
            print(f"  {a} ↔ {b}: {s:.4f}")

    conn.close()

    # Check for existing audit results
    if WORK_DIR.exists():
        manifest_path = WORK_DIR / "_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            done = sum(
                1 for b in manifest
                if (WORK_DIR / f"_findings_{b['batch']}.json").exists()
            )
            print(f"\nAudit batches: {done}/{len(manifest)} complete")


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/audit_evidence.py [prepare|report|status]")
        print("  prepare   Group by topic, write context files for subagent")
        print("  report    Parse subagent findings, show contradiction report")
        print("  status    Show topic stats and audit progress")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare()
    elif cmd == "report":
        report()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
