"""Report assembly — combines parsed pipeline outputs into a final AnalysisReport."""

from datetime import date

from .models import (
    AnalysisReport,
    ClaimAssessment,
    OmissionAnalysis,
    Verdict,
)


def _collect_evidence_ids(
    claims: list[ClaimAssessment],
    omissions: OmissionAnalysis,
) -> list[str]:
    """Collect all unique evidence IDs referenced across claims and omissions."""
    ids: set[str] = set()
    for ca in claims:
        ids.update(ca.supporting_evidence)
        ids.update(ca.contradicting_evidence)
    for om in omissions.omissions:
        ids.update(om.relevant_evidence)
    return sorted(ids)


def _verdict_label(verdict: Verdict) -> str:
    labels = {
        Verdict.SUPPORTED: "✅ Supported",
        Verdict.PARTIALLY_SUPPORTED: "⚠️ Partially Supported",
        Verdict.UNSUPPORTED: "❌ Unsupported",
        Verdict.MISLEADING: "🔍 Misleading",
        Verdict.UNVERIFIABLE: "❓ Unverifiable",
    }
    return labels.get(verdict, verdict.value)


def render_report_en(
    claims: list[ClaimAssessment],
    omissions: OmissionAnalysis,
    summary: str,
    article_title: str | None = None,
    article_source: str | None = None,
    article_date: date | None = None,
) -> str:
    """Render the English markdown report from structured data."""
    lines: list[str] = []

    # Header
    title = article_title or "Article Analysis"
    lines.append(f"# {title}")
    lines.append("")
    meta_parts = []
    if article_source:
        meta_parts.append(f"**Source:** {article_source}")
    if article_date:
        meta_parts.append(f"**Date:** {article_date.isoformat()}")
    meta_parts.append(f"**Analysis date:** {date.today().isoformat()}")
    lines.append(" | ".join(meta_parts))
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(summary)
    lines.append("")

    # Verdicts overview
    verdict_counts: dict[str, int] = {}
    for ca in claims:
        label = ca.verdict.value
        verdict_counts[label] = verdict_counts.get(label, 0) + 1
    lines.append("## Verdicts Overview")
    lines.append("")
    for v, count in sorted(verdict_counts.items()):
        lines.append(f"- **{v}**: {count}")
    lines.append("")

    # Claim assessments
    lines.append("## Claim Assessments")
    lines.append("")
    for i, ca in enumerate(claims, 1):
        lines.append(f"### Claim {i}: {_verdict_label(ca.verdict)}")
        lines.append("")
        lines.append(f"> {ca.claim.original_quote}")
        lines.append("")
        lines.append(f"**Claim:** {ca.claim.claim_text}")
        lines.append("")
        lines.append(f"**Assessment:** {ca.explanation}")
        lines.append("")
        if ca.supporting_evidence:
            lines.append(f"**Supporting evidence:** {', '.join(ca.supporting_evidence)}")
        if ca.contradicting_evidence:
            lines.append(f"**Contradicting evidence:** {', '.join(ca.contradicting_evidence)}")
        if ca.missing_context:
            lines.append(f"**Missing context:** {ca.missing_context}")
        lines.append(f"**Confidence:** {ca.confidence:.0%}")
        lines.append("")

    # Omissions
    lines.append("## Omissions and Framing")
    lines.append("")
    framing_labels = {
        "balanced": "Balanced",
        "leans_pro_eu": "Leans pro-EU",
        "leans_anti_eu": "Leans anti-EU",
        "neutral_but_incomplete": "Neutral but incomplete",
    }
    framing = omissions.framing_assessment.value
    framing_label = framing_labels.get(framing, framing)
    lines.append(f"**Framing:** {framing_label}")
    lines.append(f"**Completeness:** {omissions.overall_completeness:.0%}")
    lines.append("")
    if omissions.omissions:
        for om in omissions.omissions:
            lines.append(f"- **{om.topic}**: {om.description}")
            if om.relevant_evidence:
                lines.append(f"  Evidence: {', '.join(om.relevant_evidence)}")
    else:
        lines.append("_No significant omissions identified._")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append("*Analysis by ESBvaktin.is — independent, evidence-based, both sides equally.*")

    return "\n".join(lines)


def assemble_report(
    claims: list[ClaimAssessment],
    omissions: OmissionAnalysis,
    summary: str,
    article_title: str | None = None,
    article_source: str | None = None,
    article_date: date | None = None,
    report_text_is: str = "",
) -> AnalysisReport:
    """Assemble the final AnalysisReport from all pipeline outputs."""
    evidence_ids = _collect_evidence_ids(claims, omissions)

    report_text_en = render_report_en(
        claims=claims,
        omissions=omissions,
        summary=summary,
        article_title=article_title,
        article_source=article_source,
        article_date=article_date,
    )

    return AnalysisReport(
        article_title=article_title,
        article_source=article_source,
        article_date=article_date,
        summary=summary,
        claims=claims,
        omissions=omissions,
        evidence_used=evidence_ids,
        report_text_en=report_text_en,
        report_text_is=report_text_is,
    )
