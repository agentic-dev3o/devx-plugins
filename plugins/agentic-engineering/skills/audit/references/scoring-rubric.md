# Scoring Rubric

## Contents

- Severity definitions (CRITICAL, HIGH, MEDIUM, LOW)
- Per-dimension scoring
- Overall maturity tier
- Top fixes ordering
- Reporting honesty rules

## Severity Definitions

### CRITICAL
A finding is CRITICAL when at least one is true:

- The system can leak secrets, PII, or cross-tenant data.
- A tool can be invoked with unbounded or unsafe arguments (shell, SQL, deletes, payments) without validation or confirmation.
- A tool loop has no termination bound (max iterations, max time, max cost).
- There is no evaluation harness for a production system.
- A prompt-injection vector reaches a privileged tool.
- The system silently produces wrong outputs in a class of queries that downstream code trusts.
- Cost or token spend can spiral with no cap on a per-request basis.

CRITICAL findings block production. They are reported first.

### HIGH
A finding is HIGH when impact is material but bounded:

- Prompt caching is absent on a stable, large prefix called frequently (significant cost/latency win missed).
- Documents are placed below the query in long-context prompts (up to 30% quality loss).
- Tool descriptions are vague enough to cause measurable tool-selection errors.
- No max-iteration cap exists but tool loops are short by construction.
- Evals exist but ignore a major axis (safety, latency, or cost).
- Refusal behavior is undefined for a customer-facing product.
- Input validation gaps on non-destructive tools.
- Cache breakpoints exist but are placed below volatile content, invalidating the prefix.

### MEDIUM
A finding is MEDIUM when impact is measurable but minor or non-recurring:

- No role assigned in system prompt for a domain task.
- Format requirements stated without examples.
- One unused or near-duplicate tool clutters the tool list.
- TTL not tuned (5-min default on a daily batch).
- Eval set is too small (under ~50 items) for the production volume.
- Verbosity not calibrated (model defaults to long answers in an SMS context).
- Communication style not tuned (warm phrasing on a B2B engineering tool).

### LOW
A finding is LOW when it is cosmetic or marginal:

- Inconsistent XML tag names.
- Streaming not enabled where it would improve perceived latency.
- Few-shot examples slightly longer than necessary.
- Tool name uses snake_case in a camelCase codebase.
- Missing inline documentation on a self-evident tool.

## Per-Dimension Scoring

Score each dimension out of 10 using this rough mapping:

| Score | Meaning |
|-------|---------|
| 10 | All applicable practices respected. No findings. |
| 9  | Minor LOW findings only. |
| 7-8 | Some MEDIUM findings; no HIGH. |
| 5-6 | At least one HIGH finding, multiple MEDIUM. |
| 3-4 | Multiple HIGH findings, or one CRITICAL. |
| 1-2 | Multiple CRITICAL findings. |
| 0  | Dimension is essentially absent (e.g. no eval harness exists). |

Mark N/A when a dimension genuinely does not apply (e.g. prompt-caching score on an OpenAI target where the SDK manages it automatically). N/A does not contribute to the overall average.

## Overall Maturity Tier

Average the dimension scores (excluding N/A), then map:

| Average | Tier | Description |
|---------|------|-------------|
| 9.0–10.0 | Production-ready | Ship with confidence. Routine monitoring only. |
| 7.0–8.9  | Solid with focused gaps | Ship after addressing HIGH findings. |
| 5.0–6.9  | Functional but fragile | Material risk; remediate HIGH and CRITICAL before scaling. |
| 3.0–4.9  | High-risk | Not for production without major rework. |
| 0.0–2.9  | Not production-worthy | Fundamental gaps; rebuild on a sound base. |

Override the tier downward if any CRITICAL finding exists. A system with one CRITICAL is at most "Functional but fragile" regardless of average.

## Top Fixes Ordering

Order top fixes by *impact per unit effort*:

1. All CRITICAL findings, easiest first.
2. HIGH findings with S (small) effort.
3. HIGH findings with M (medium) effort.
4. The single MEDIUM finding most likely to unblock further improvement.

Tag each fix with effort:

- **S** — under an hour. Single-file edit, prompt tweak, add cache_control marker.
- **M** — half a day to a day. New eval set, tool description rewrite, add validation layer.
- **L** — multi-day. Build an eval harness from scratch, refactor a tool loop, introduce structured outputs across the pipeline.

## Reporting Honesty Rules

- Never inflate severity to make the report look important.
- Never invent findings to fill a dimension. N/A is fine.
- Quote evidence directly when possible; paraphrase only when the quote is large.
- If you cannot verify something (runtime behavior you didn't see), say so and mark it as a question, not a finding.
- The audit's job is to produce action, not to score points.
