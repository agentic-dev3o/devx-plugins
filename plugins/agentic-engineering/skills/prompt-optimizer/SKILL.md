---
name: optimizing-prompts
description: >-
  Rewrites a given prompt or agent definition by applying Anthropic
  prompt-engineering best practices — clarity and directness, context and
  motivation, XML structure, role assignment, long-context layout, output
  format control, communication-style calibration, and parallel-tool-call
  affordance. Produces a before/after with per-change rationale.
  Triggers on: optimize this prompt, improve my prompt, rewrite prompt,
  prompt optimization, refine system prompt, tune agent prompt, polish
  prompt for production.
---

# Prompt Optimizer

Target: `$ARGUMENTS` (path to a prompt file, agent definition, or pasted prompt text)

## Workflow

Progress checklist:

```
Prompt Optimization:
- [ ] Step 1: Capture the target prompt
- [ ] Step 2: Identify intent, model, and runtime
- [ ] Step 3: Diagnose against eight techniques
- [ ] Step 4: Rewrite the prompt
- [ ] Step 5: Produce before/after report with rationale
```

### Step 1: Capture the Target Prompt

Determine whether `$ARGUMENTS` is:

- A file path → read the file
- An agent definition (markdown with frontmatter, JSON/YAML) → extract the system prompt and any few-shot examples
- Inline prompt text → use as-is
- A directory → list it and ask the user to pick one prompt to optimize

If the prompt is part of a larger agent (tools, examples, memory layout), capture the surrounding shape but keep the rewrite scoped to the prompt itself. Do not rewrite tool definitions in this skill — the [audit](../audit/SKILL.md) skill flags those, and tool rewrites belong in their own pass.

### Step 2: Identify Intent, Model, and Runtime

Before optimizing, answer:

- **What does the prompt do?** Classification, extraction, generation, agent loop, chat?
- **Who is the end user?** Internal engineer, customer, batch pipeline?
- **What model runs it?** Claude Opus 4.7 / Sonnet 4.6 / Haiku 4.5 / GPT-x / etc. — affects defaults (verbosity, thinking, effort) and which features apply (caching, adaptive thinking, structured outputs).
- **Is this interactive or autonomous?** Single-turn API, multi-turn chat, long-horizon agent? Verbosity and update-frequency guidance differs.

If any of these are ambiguous and would materially change the rewrite, ask one focused question. Do not ask if the answer is inferable from the prompt itself.

### Step 3: Diagnose Against Eight Techniques

For each technique below, read the matching reference and decide whether the current prompt applies it well, partially, or not at all. Note the gap concretely (quote the offending text or note its absence).

1. **Clarity and directness** — [references/clarity.md](references/clarity.md)
2. **Context and motivation** — [references/context.md](references/context.md)
3. **Structure with XML tags** — [references/structure.md](references/structure.md)
4. **Role prompting** — [references/role.md](references/role.md)
5. **Long-context layout** — [references/long-context.md](references/long-context.md)
6. **Communication style and verbosity** — [references/communication-style.md](references/communication-style.md)
7. **Format control** — [references/format-control.md](references/format-control.md)
8. **Parallel tool calling** — [references/parallel-tools.md](references/parallel-tools.md)

Skip techniques that do not apply (e.g. parallel tool calling on a prompt with no tools). Do not invent gaps to justify rewrites.

### Step 4: Rewrite the Prompt

Apply changes in this order, smallest-impact-first to preserve voice:

1. Add missing role assignment (one sentence at the top).
2. Add motivation to rules that need it.
3. Restructure with XML tags where mixed content benefits.
4. Tighten verbose passages; remove restated rules.
5. Add explicit format control if absent.
6. Add long-context layout adjustments if applicable.
7. Add communication-style and verbosity calibration.
8. Add parallel-tool-call affordance if tools are present.

Constraints on the rewrite:

- Preserve the original intent exactly. Do not bolt on features the prompt did not ask for.
- Do not invent new instructions to "improve" behavior the user did not request.
- Keep the rewrite as short as the original allows. Prompt bloat is a real failure mode.
- Match the voice already established when one exists.
- When the original is already good on a technique, leave it alone — note "Already respected" in the report.

### Step 5: Produce Before/After Report with Rationale

Output structure:

```markdown
## Target

<file path or "inline prompt">

## Diagnosis

| Technique | Current state | Action |
|-----------|---------------|--------|
| Clarity and directness | Respected / Partial / Missing | Applied / Skipped / N/A |
| Context and motivation | ... | ... |
| Structure (XML) | ... | ... |
| Role | ... | ... |
| Long context | ... | ... |
| Communication style | ... | ... |
| Format control | ... | ... |
| Parallel tools | ... | ... |

## Before

<original prompt, verbatim>

## After

<rewritten prompt>

## Changes Applied

1. <Technique>: <what changed and why, ≤2 sentences, citing the reference>
2. <Technique>: ...
...

## What I Did Not Change

- <Things you considered and left alone, with reason>
```

If the prompt is already strong on every technique that applies, say so plainly and do not rewrite. A non-change is a valid output.

## Constraints

- One rewrite per invocation. Do not produce three variants unless explicitly asked.
- Do not change identity, refusal policy, or safety guardrails without a flagged note. If the original lacks them and the use case needs them, recommend adding them in a follow-up rather than silently inserting.
- When the rewrite would significantly change model behavior, recommend running the existing eval set against both versions before deploying.
- Do not optimize prompts that contain secrets, credentials, or PII. Stop and surface the issue.
- For diagnosis without rewriting (audit-style review), use the [audit](../audit/SKILL.md) skill instead.
