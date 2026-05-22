---
name: auditing-agentic-systems
description: >-
  Audits an agent, tool loop, or inference request across six dimensions
  (prompt engineering, tools definition, context engineering, cache usage,
  evaluation, guardrails) and produces a scored gap analysis with severity
  ratings and concrete remediations. Framework-agnostic; recognizes patterns
  from Anthropic SDK, OpenAI SDK, Vercel AI SDK, and OpenAI Agents SDK.
  Triggers on: audit my agent, review tool loop, audit inference request,
  agentic engineering review, audit prompt, review agent code, check prompt
  caching, evaluate guardrails.
---

# Agentic System Audit

Target: `$ARGUMENTS` (path to file, directory, prompt text, or description of the system to audit)

## Workflow

Progress checklist:

```
Agentic System Audit:
- [ ] Step 1: Resolve audit target
- [ ] Step 2: Detect framework and identify components
- [ ] Step 3: Evaluate across six dimensions
- [ ] Step 4: Classify findings and assign severity
- [ ] Step 5: Produce scored gap analysis
```

### Step 1: Resolve Audit Target

The target is one of:

- **Agent definition file** — markdown with frontmatter, JSON/YAML config, or code (TS/Py)
- **Inference call site** — code that builds messages and calls an LLM API
- **Tool loop** — code that iterates on tool calls until done
- **Prompt text** — a system prompt, user prompt template, or both
- **Description** — the user describes the system in natural language

If `$ARGUMENTS` is a path, read the file(s). If a directory, list it and ask the user to scope to specific files when more than ~5 are present. If it is prompt text, treat the text as the target directly. If it is a description, ask one clarifying question only when the framework or component shape is genuinely ambiguous.

### Step 2: Detect Framework and Identify Components

Identify the runtime context to ground recommendations:

- **Anthropic SDK** (`anthropic`, `@anthropic-ai/sdk`) — supports prompt caching, adaptive thinking, effort parameter, parallel tool use
- **OpenAI SDK** (`openai`) — tool calling, structured outputs, parallel calls, no native prompt caching as of writing
- **Vercel AI SDK** (`ai`, `@ai-sdk/*`) — provider-agnostic tool calling, streaming, structured generation
- **OpenAI Agents SDK** (`@openai/agents`) — handoffs, guardrails, tracing
- **Custom / framework-less** — raw HTTP calls, hand-rolled loops

Identify the components present in the target: system prompt, user prompt, tool definitions, tool loop, memory/state, evals, guardrails, retries, streaming.

### Step 3: Evaluate Across Six Dimensions

For each dimension, load the matching reference and walk the checklist against the target. Do not declare a finding without concrete evidence (a quote from the prompt, a line in the code, or a missing pattern that should be present).

1. **Prompt engineering** — [references/prompt-engineering.md](references/prompt-engineering.md)
2. **Tools definition** — [references/tools-definition.md](references/tools-definition.md)
3. **Context engineering** — [references/context-engineering.md](references/context-engineering.md)
4. **Cache usage** — [references/cache-usage.md](references/cache-usage.md)
5. **Evaluation** — [references/evaluation.md](references/evaluation.md)
6. **Guardrails** — [references/guardrails.md](references/guardrails.md)

When a dimension is not applicable (e.g. no tools defined), mark it `N/A` and explain why. Do not invent issues to fill a dimension.

### Step 4: Classify Findings and Assign Severity

Severity rubric (see [references/scoring-rubric.md](references/scoring-rubric.md) for full criteria):

- **CRITICAL** — Will produce wrong outputs, leak secrets, run unbounded loops, or burn 10x the necessary tokens. Examples: no stop conditions, secrets in prompts, no input validation on tool args, eval-free production system.
- **HIGH** — Significantly degrades quality, cost, or reliability. Examples: documents below the query in long context, no prompt caching on a stable 5k-token system prompt, vague tool descriptions, no max-iteration cap on a tool loop.
- **MEDIUM** — Measurable but bounded impact. Examples: missing role assignment, no examples for a structured output task, single-shot evals instead of multi-criteria.
- **LOW** — Style or minor optimization. Examples: inconsistent XML tag names, missing `argument-hint`-style metadata, no streaming where it would help UX.

Each finding must include: the practice it violates, where (file:line or prompt section), evidence, the recommended fix, and a one-line "why it matters" rooted in the reference.

### Step 5: Produce Scored Gap Analysis

Output a markdown table with these columns:

| Practice | Status | Severity | Location | Evidence | Fix |
|----------|--------|----------|----------|----------|-----|

Status values: **Respected**, **Violated**, **Partially respected**, **N/A**.

Group rows by dimension in this order: Prompt engineering, Tools definition, Context engineering, Cache usage, Evaluation, Guardrails.

End with:

1. **Score summary** — per-dimension score (X/10) and an overall maturity tier:
   - 9–10: Production-ready
   - 7–8: Solid, with focused gaps
   - 5–6: Functional but fragile
   - 3–4: High-risk
   - 0–2: Not production-worthy
2. **Top fixes** — ordered list of the 3–5 highest-impact changes, each with effort estimate (S/M/L).
3. **What looks good** — specific strengths worth keeping. Do not invent these; only list real strengths.

If the audit cannot be completed (target unreadable, framework unrecognized after Step 2), say so plainly and stop. Do not fabricate findings.

## Constraints

- Framework-agnostic in spirit, framework-aware in recommendations. Do not suggest Anthropic-only features (prompt caching, adaptive thinking) for a target on OpenAI, and vice versa.
- Cite the source. Every recommendation should map back to a specific best practice in the reference files.
- No speculation. If a behavior depends on runtime configuration you cannot see, mark it as a question, not a finding.
- Do not rewrite the prompt or code during the audit. The audit produces findings; the [prompt-optimizer](../prompt-optimizer/SKILL.md) skill rewrites.
- Do not flag a missing feature as a violation when the use case does not need it (e.g. no caching on a 200-token prompt called once).
