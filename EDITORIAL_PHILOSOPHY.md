# Editorial Philosophy

ESBvaktin exists to help Icelandic citizens make an informed decision about EU membership. It does not exist to tell them what to decide.

This document defines the epistemic principles that govern every part of the platform — from how claims are extracted to how verdicts are displayed, from what the pipeline measures to what it deliberately leaves unmeasured. These principles are not aspirational. They are design constraints. Code that violates them is a bug.

## The Three Pillars

### 1. Curiosity over judgement — Tim Harford

> "Be curious."
> — Tim Harford, _How to Make the World Add Up_ (2020)

Harford's golden rule is not "be sceptical" — scepticism is cold and defensive. Curiosity is warm and productive. A curious person _enjoys_ being surprised. They hunger for the unexpected.

> "A curious person enjoys being surprised and hungers for the unexpected."

ESBvaktin approaches every claim with curiosity, not suspicion. When the central bank governor says euro adoption would require painful adjustment, we don't ask "is he lying?" — we ask "what does the evidence say, and what context is missing?" When a pro-EU columnist says Iceland is falling behind small EU states, we don't dismiss the comparison — we check the numbers, surface the methodology, and note what's left out.

Harford warns about motivated reasoning: the brain responds to facts that threaten our beliefs much as it responds to threats to survival. Both sides of the EU debate have emotional priors. ESBvaktin's job is to make it harder to fool yourself — not to fool you in the other direction.

> "When a measure becomes a target, it ceases to be a good measure."
> — Goodhart's Law, as cited by Harford

This applies to ESBvaktin itself. Our verdict counts, completeness scores, and confidence numbers are tools for understanding, not targets to optimise. If we find ourselves adjusting verdicts to make the numbers look balanced, we have failed.

> "Not asking what a statistic actually means is a failure of empathy."

Every number on the site should be accompanied by enough context that a reader can understand what it means — not just what it is.

**Source:** Tim Harford, _How to Make the World Add Up: Ten Rules for Thinking Differently About Numbers_ (London: The Bridge Street Press, 2020).

### 2. Inform, not persuade — David Spiegelhalter

> "To inform, not persuade."
> — Motto of the Winton Centre for Risk and Evidence Communication, University of Cambridge

The Winton Centre, led by Spiegelhalter until its closure in 2022, established principles for trustworthy evidence communication that ESBvaktin adopts directly:

1. **Serve the audience's interests**, not the communicator's
2. **Present evidence in a balanced and clear way**
3. **Include uncertainties and limitations**
4. **Be appropriate for the audience** in content, length, depth, and format
5. **Be clear about purpose** — who is this helping, and what decision are they making?

Spiegelhalter demonstrates how framing distorts: the Brexit campaign's "£350 million per week to the EU" and the equivalent "80 pence per person per day" are both arithmetically correct. Neither is honest alone. ESBvaktin must present claims in their most informative framing, not their most dramatic one.

> "Numbers are used to persuade people, not to inform them."

This is the default behaviour of public discourse. ESBvaktin exists to be the exception. When we assess a claim, we don't assign a verdict to score a point — we show what the evidence says and what it doesn't, so the reader can think for themselves.

> "There's no point in being trustworthy if you're boring."

The platform must be engaging. Dry accuracy that nobody reads serves nobody. The capsule-writer agent, the editorial tone, the design system — these exist because trustworthy information that fails to reach people is wasted trustworthiness.

**Sources:**

- David Spiegelhalter, _The Art of Statistics: How to Learn from Data_ (London: Pelican, 2019).
- Winton Centre for Risk and Evidence Communication, mission statement and guidelines (University of Cambridge, 2016–2022). https://wintoncentre.maths.cam.ac.uk/

### 3. Trustworthiness over trust — Onora O'Neill

> "Nobody sensible simply wants more trust."
> — Onora O'Neill, _A Question of Trust: The BBC Reith Lectures 2002_

O'Neill draws a distinction that governs how ESBvaktin thinks about its own credibility. Trust is a _response_ — it's what readers give us. Trustworthiness is a _quality_ — it's what we build. We cannot demand trust. We can only earn it by being genuinely trustworthy, and then demonstrating that trustworthiness in ways others can verify.

O'Neill identifies three qualities that make trust well-placed:

1. **Competence** — you know what you're doing
2. **Honesty** — you tell the truth, including uncomfortable truths
3. **Reliability** — you do it consistently, not just when it's convenient

And she defines three requirements for information that supports intelligent trust:

1. **Accessible** — people can get at it
2. **Intelligible** — they can understand it
3. **Assessable** — they can check it and challenge it

> "What originators seek to communicate must be accessible to recipients, must be intelligible to them, and must be assessable by them in ways that support understanding and interpretation, and enable forms of check and challenge."

The crucial distinction is between _transparency_ and _intelligent openness_. Dumping raw data is transparent. Making it understandable and checkable is intelligently open. O'Neill notes: "The press are skilled at making material accessible, but erratic about making it assessable." ESBvaktin must do both.

O'Neill also warns of the **accountability paradox**: systems designed to enforce compliance through metrics and audits can damage trust by incentivising box-ticking over genuine honesty. This applies directly to our pipeline — we must resist the temptation to optimise metrics (verdict counts, completeness scores, confidence numbers) at the expense of honest assessment.

**Sources:**

- Onora O'Neill, _A Question of Trust: The BBC Reith Lectures 2002_ (Cambridge: Cambridge University Press, 2002).
- Onora O'Neill, "Trust, Trustworthiness, and Accountability," in _Capital Failure: Rebuilding Trust in Financial Services_ (Oxford: Oxford University Press, 2014).
- Onora O'Neill, _A Philosopher Looks at Digital Communication_ (Cambridge: Cambridge University Press, 2022).

## Operational Principles

These translate the three pillars into concrete pipeline behaviour.

### What we show

| Principle                                   | This means we...                                                                                                                                       |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Show the evidence, not just the verdict** | Every assessed claim links to its supporting and contradicting evidence entries. Readers can trace our reasoning.                                      |
| **Surface uncertainty honestly**            | Confidence scores reflect genuine uncertainty. A claim with mixed evidence gets a moderate score, not a confident one. We never round up to certainty. |
| **Include what's missing**                  | The `missing_context` field on every assessment tells readers what the article left out. Omissions analysis is as important as verdict assignment.     |
| **Present both sides with equal rigour**    | Pro-EU and anti-EU claims are assessed against the same evidence base with the same standards. Balance is about fairness, not false equivalence.       |
| **Make framing visible**                    | Articles receive framing labels (`leans_pro_eu`, `leans_anti_eu`, `neutral_but_incomplete`). Readers know the lens before reading the analysis.        |

### What we don't do

| Anti-pattern                   | Why we avoid it                                                                                                                                                         |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Credibility scorekeeping**   | We don't rank entities as trustworthy or untrustworthy. We show what people said and what the evidence says. Patterns are for readers to notice.                        |
| **Gotcha framing**             | We don't lead with who was wrong. We lead with what's interesting and verifiable. Assessments explain what the evidence says, not who made a mistake.                   |
| **False precision**            | We don't present confidence scores to three decimal places or completeness scores as if they're thermometer readings. These are tools for comparison, not measurements. |
| **Premature certainty**        | We don't assign definitive stances, verdicts, or labels when we don't have enough data. `NULL` means "we don't know yet" — it's more honest than a guess.               |
| **Optimising our own metrics** | We don't adjust verdicts to make the balance look better, inflate claim counts for coverage, or lower completeness thresholds to produce nicer numbers.                 |

### How we handle the hard cases

**When a claim is factually correct but misleading in context:**
Use `partially_supported` or `misleading` and explain the gap between what was said and what it means. The reader learns something either way.

**When we lack evidence to assess a claim:**
Use `unverifiable` honestly. An honest "we don't know" is more trustworthy than a hedged guess. Note what evidence would be needed to verify it.

**When both sides make the same error:**
Say so. The platform's editorial philosophy doesn't require artificial symmetry. If both pro-EU and anti-EU commentators cherry-pick the same dataset, that's a finding worth sharing.

**When our own assessment might be wrong:**
The reassessment pipeline exists for this reason. Claims are living documents. New evidence triggers re-evaluation. The audit system flags patterns that suggest systematic bias in our own verdicts.

## Applying the Pillars to Design Decisions

### Entity stance assignment

**O'Neill:** Don't assert what you can't demonstrate. If an entity has only 1–2 observations, we lack the evidence to assign a stance. `NULL` (unknown) is distinct from `neutral` (deliberately takes no side).
**Harford:** Search your feelings — are we assigning a stance because the data supports it, or because the first article we read created an impression?

### Completeness scores

**Spiegelhalter:** Be clear about what you're measuring. A 35% completeness score on an opinion piece doesn't mean the author failed — it means the piece serves a different purpose than comprehensive analysis. The scale should reflect genre expectations.
**Harford:** When a measure becomes a target, it ceases to be a good measure. If we start writing to maximise completeness scores, we've lost the plot.

### Capsule writing

**Spiegelhalter:** Serve the audience's interests. The capsule exists to help readers understand what an article gets right and what context it misses — not to summarise our assessment.
**Harford:** Be curious. The capsule should make readers more curious about the topic, not more certain about the verdict.
**O'Neill:** Make it assessable. The capsule should give readers enough information to form their own view, not just defer to ours.

### Evidence confidence

**O'Neill:** Competence includes knowing the limits of your knowledge. Evidence entries with `high` confidence should genuinely be high-confidence — not just "from an official source". Official sources can be outdated, misinterpreted, or inapplicable to the Icelandic context.

### Publication decisions

**O'Neill:** Reliability means consistency. If we publish claims immediately and retract them later, we're not reliable. A cooling-off period or minimum-evidence gate would be more trustworthy than instant publication.
**Spiegelhalter:** Include uncertainties. If a claim is published with low confidence, the uncertainty should be visible to readers, not hidden behind a binary published/unpublished gate.

## For Agents and Contributors

If you are an agent (claim-assessor, omissions-analyst, editorial-writer, capsule-writer) or a human contributor, these principles apply to your output:

1. **Write to inform, not to persuade.** Your job is to help the reader understand, not to convince them of anything.
2. **Show your uncertainty.** If the evidence is mixed, say so. If you're not sure, say so. Never hedge with "virðist benda til" when you mean "staðfestir" — but equally, never write "staðfestir" when you mean "bendir til".
3. **Be curious, not judgemental.** Lead with what's interesting, not with who's wrong.
4. **Make it checkable.** Cite evidence entries. Link to sources. Give the reader what they need to verify your work.
5. **Remember who you serve.** The Icelandic voter deciding how to cast their ballot on 29 August 2026. Not the pro-EU campaign. Not the anti-EU campaign. Not the government. Not us.
