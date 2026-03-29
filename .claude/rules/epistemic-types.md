---
globs:
  - "src/esbvaktin/pipeline/**"
  - "scripts/reassess*"
  - "scripts/audit_claims.py"
  - ".claude/agents/claim-*"
  - "scripts/prepare_overview_context.py"
  - "scripts/validate_editorial.py"
description: "Epistemic type classification rules — hearsay short-circuit, confidence ceilings, attribution requirements"
---

# Epistemic Types

Two orthogonal dimensions on every claim: `ClaimType` (what kind of claim) and `EpistemicType` (epistemic status).

## The four types

| Type | Definition |
|---|---|
| `factual` | Verifiable assertion about past or present state. Standard evidence-based assessment. |
| `hearsay` | Claim attributed to unnamed sources, second-hand reports, or unverifiable attribution chains. |
| `counterfactual` | Claim about an unrealised past scenario ("ef X hefði..."). |
| `prediction` | Claim about a future state ("ef aðild næðist myndi..."). |

## Naming collision — FORECAST vs PREDICTION

`ClaimType.PREDICTION` was **renamed to `ClaimType.FORECAST`** to avoid collision with `EpistemicType.PREDICTION`. Always use:
- `ClaimType.FORECAST` for forecast-type claims
- `EpistemicType.PREDICTION` for epistemic status

## Hearsay: short-circuit path

Hearsay claims **never reach evidence retrieval or the assessor agent**. In `retrieve_evidence.py`, they are intercepted before the retrieval loop and returned as pre-built `UNVERIFIABLE` assessments.

Consequences at registration:
- `verdict = unverifiable`
- `published = True` (visible on site with amber warning badge)
- `substantive = False` (excluded from credibility scoring)

Do not pass hearsay claims to `retrieve_evidence_for_claim()` or the claim-assessor agent.

## Prediction and counterfactual: reasoning-based assessment

These types proceed through normal evidence retrieval, but the assessor evaluates **reasoning quality** rather than direct evidence match:

1. Source consensus — do multiple credible sources agree?
2. Source credibility — official bodies, experts, or unnamed?
3. Precedent — experience from comparable countries (Norway, Sweden, Croatia)?
4. Causal chain — is the cause-effect logic sound?

**Confidence ceiling: 0.8** for both prediction and counterfactual. Never assign confidence > 0.8 regardless of evidence strength.

## Editorial / context output: attribution language for hearsay

When hearsay claims appear in editorial or overview context, **always use attribution language**. Never present hearsay as a named individual's stated position.

| Wrong | Right |
|---|---|
| „Þorgerður taldi að kommissarinn myndi koma í hlut Íslands" | „Ónafngreindir fundargestir sögðu Þorgerði hafa látið falla orð um..." |

Required attribution phrases: `sagt er að`, `ónafngreindir aðilar sögðu`, `fullyrt var`, `samkvæmt frásögnum`.

If the named subject denied the claim, include the denial in the same sentence or the one immediately following.
