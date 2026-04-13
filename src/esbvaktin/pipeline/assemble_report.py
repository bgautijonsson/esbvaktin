"""Report assembly — combines parsed pipeline outputs into a final AnalysisReport."""

from datetime import date

from ..utils.slugify import icelandic_slugify
from .models import (
    AnalysisReport,
    ClaimAssessment,
    EpistemicType,
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


# ── Verdict labels ────────────────────────────────────────────────────

_VERDICT_LABELS_EN = {
    Verdict.SUPPORTED: "✅ Supported",
    Verdict.PARTIALLY_SUPPORTED: "⚠️ Partially Supported",
    Verdict.UNSUPPORTED: "❌ Unsupported",
    Verdict.MISLEADING: "🔍 Misleading",
    Verdict.UNVERIFIABLE: "❓ Unverifiable",
}

_VERDICT_LABELS_IS = {
    Verdict.SUPPORTED: "✅ Stutt af heimildum",
    Verdict.PARTIALLY_SUPPORTED: "⚠️ Stutt að hluta",
    Verdict.UNSUPPORTED: "❌ Ekki stutt af heimildum",
    Verdict.MISLEADING: "🔍 Þarfnast samhengis",
    Verdict.UNVERIFIABLE: "❓ Ekki hægt að sannreyna",
}

_VERDICT_LABELS_IS_PREDICTION = {
    Verdict.SUPPORTED: "✅ Víðtæk samstaða",
    Verdict.PARTIALLY_SUPPORTED: "🔶 Nokkur stoð",
    Verdict.UNSUPPORTED: "❌ Órökstudd",
    Verdict.MISLEADING: "🔍 Ofeinföldun",
    Verdict.UNVERIFIABLE: "⚪ Heimildir vantar",
}

_VERDICT_LABELS_EN_PREDICTION = {
    Verdict.SUPPORTED: "✅ Broad consensus",
    Verdict.PARTIALLY_SUPPORTED: "🔶 Some basis",
    Verdict.UNSUPPORTED: "❌ Unsubstantiated",
    Verdict.MISLEADING: "🔍 Oversimplification",
    Verdict.UNVERIFIABLE: "⚪ Evidence lacking",
}

_PREDICTION_TYPES = {EpistemicType.PREDICTION, EpistemicType.COUNTERFACTUAL}

_FRAMING_LABELS_IS = {
    "balanced": "Jafnvæg umfjöllun",
    "leans_pro_eu": "Hallar á ESB-jákvæða hlið",
    "leans_anti_eu": "Hallar á ESB-neikvæða hlið",
    "strongly_pro_eu": "Mjög ESB-jákvæð",
    "strongly_anti_eu": "Mjög ESB-neikvæð",
    "neutral_but_incomplete": "Hlutlaus en ófullnægjandi",
}

_FRAMING_LABELS_EN = {
    "balanced": "Balanced",
    "leans_pro_eu": "Leans pro-EU",
    "leans_anti_eu": "Leans anti-EU",
    "strongly_pro_eu": "Strongly pro-EU",
    "strongly_anti_eu": "Strongly anti-EU",
    "neutral_but_incomplete": "Neutral but incomplete",
}


def _verdict_label(
    verdict: Verdict,
    language: str = "en",
    epistemic_type: EpistemicType | None = None,
) -> str:
    """Return a display label for a verdict, adapted for epistemic type.

    Predictions and counterfactuals use a different label set that reflects
    the inherent uncertainty of forward-looking or hypothetical claims.
    """
    if epistemic_type in _PREDICTION_TYPES:
        labels = (
            _VERDICT_LABELS_IS_PREDICTION if language == "is" else _VERDICT_LABELS_EN_PREDICTION
        )
    else:
        labels = _VERDICT_LABELS_IS if language == "is" else _VERDICT_LABELS_EN
    return labels.get(verdict, verdict.value)


# ── Icelandic report renderer (primary) ──────────────────────────────


def render_report_is(
    claims: list[ClaimAssessment],
    omissions: OmissionAnalysis,
    summary: str,
    article_title: str | None = None,
    article_source: str | None = None,
    article_date: date | None = None,
) -> str:
    """Render the Icelandic markdown report from structured data.

    This is the primary report — generated natively, not translated.
    """
    lines: list[str] = []

    # Header
    title = article_title or "Greining greinar"
    lines.append(f"# {title}")
    lines.append("")
    meta_parts = []
    if article_source:
        meta_parts.append(f"**Heimild:** {article_source}")
    if article_date:
        meta_parts.append(f"**Dagsetning:** {article_date.isoformat()}")
    meta_parts.append(f"**Greiningardagur:** {date.today().isoformat()}")
    lines.append(" | ".join(meta_parts))
    lines.append("")

    # Summary
    lines.append("## Yfirlit")
    lines.append("")
    lines.append(summary)
    lines.append("")

    # Verdicts overview
    verdict_counts: dict[str, int] = {}
    for ca in claims:
        label = ca.verdict.value
        verdict_counts[label] = verdict_counts.get(label, 0) + 1

    lines.append("## Niðurstöður mats")
    lines.append("")
    verdict_names_is = {
        "supported": "Stutt af heimildum",
        "partially_supported": "Stutt að hluta",
        "unsupported": "Ekki stutt",
        "misleading": "Þarfnast samhengis",
        "unverifiable": "Ekki hægt að sannreyna",
    }
    for v, count in sorted(verdict_counts.items()):
        is_name = verdict_names_is.get(v, v)
        lines.append(f"- **{is_name}**: {count}")
    lines.append("")

    # Claim assessments
    lines.append("## Fullyrðingamat")
    lines.append("")
    for i, ca in enumerate(claims, 1):
        lines.append(
            f"### Fullyrðing {i}: {_verdict_label(ca.verdict, 'is', ca.claim.epistemic_type)}"
        )
        lines.append("")
        lines.append(f"> {ca.claim.original_quote}")
        lines.append("")
        lines.append(f"**Fullyrðing:** {ca.claim.claim_text}")
        lines.append("")
        lines.append(f"**Mat:** {ca.explanation}")
        lines.append("")
        if ca.supporting_evidence:
            lines.append(f"**Stuðningsheimildir:** {', '.join(ca.supporting_evidence)}")
        if ca.contradicting_evidence:
            lines.append(f"**Andstæðar heimildir:** {', '.join(ca.contradicting_evidence)}")
        if ca.missing_context:
            lines.append(f"**Samhengi sem vantar:** {ca.missing_context}")
        lines.append(f"**Traust:** {ca.confidence:.0%}")
        lines.append("")

    # Omissions
    lines.append("## Eyður og sjónarhorn")
    lines.append("")
    framing = omissions.framing_assessment.value
    framing_label = _FRAMING_LABELS_IS.get(framing, framing)
    lines.append(f"**Sjónarhorn:** {framing_label}")
    lines.append(f"**Heildstæðni:** {omissions.overall_completeness:.0%}")
    lines.append("")
    if omissions.omissions:
        for om in omissions.omissions:
            lines.append(f"- **{om.topic}**: {om.description}")
            if om.relevant_evidence:
                lines.append(f"  Heimildir: {', '.join(om.relevant_evidence)}")
    else:
        lines.append("_Engar mikilvægar eyður greindar._")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append("*Greining ESBvaktin.is — óháð, heimildum háð, báðir sjónarvinklar metnir jafnt.*")

    return "\n".join(lines)


# ── English report renderer (secondary/optional) ─────────────────────


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
        lines.append(f"### Claim {i}: {_verdict_label(ca.verdict, 'en', ca.claim.epistemic_type)}")
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
    framing = omissions.framing_assessment.value
    framing_label = _FRAMING_LABELS_EN.get(framing, framing)
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


# ── Report assembly ───────────────────────────────────────────────────


def assemble_report(
    claims: list[ClaimAssessment],
    omissions: OmissionAnalysis,
    summary: str,
    article_title: str | None = None,
    article_url: str | None = None,
    article_source: str | None = None,
    article_date: date | None = None,
    language: str = "is",
) -> AnalysisReport:
    """Assemble the final AnalysisReport from all pipeline outputs.

    Default language is Icelandic ("is"). The primary report is always
    generated in the pipeline language; the secondary report is left
    empty unless explicitly requested.
    """
    evidence_ids = _collect_evidence_ids(claims, omissions)

    report_kwargs = dict(
        claims=claims,
        omissions=omissions,
        summary=summary,
        article_title=article_title,
        article_source=article_source,
        article_date=article_date,
    )

    report_text_is = ""
    report_text_en = ""

    if language == "is":
        report_text_is = render_report_is(**report_kwargs)
    else:
        report_text_en = render_report_en(**report_kwargs)

    slug = icelandic_slugify(article_title) if article_title else None

    return AnalysisReport(
        article_title=article_title,
        article_url=article_url,
        article_source=article_source,
        article_date=article_date,
        language=language,
        summary=summary,
        slug=slug,
        capsule=None,
        claims=claims,
        omissions=omissions,
        evidence_used=evidence_ids,
        report_text_is=report_text_is,
        report_text_en=report_text_en,
    )
