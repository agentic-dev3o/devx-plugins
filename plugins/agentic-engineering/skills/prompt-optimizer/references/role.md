# Technique 4: Role Prompting

## Contents

- Principle
- Diagnostic questions
- Why roles work
- Role quality levels (generic, domain-tagged, specific and constrained)
- Rewrite patterns (promote to top, pair with audience, multi-role separation, role+constraints)
- Anti-patterns
- Special cases (identity statements, tool-using agents)
- Application note

## Principle

A clear role at the start of the system prompt focuses tone, vocabulary, decision priorities, and refusal posture. The role acts as a high-leverage prior — one well-chosen sentence shifts the entire response distribution.

## Diagnostic Questions

- Is there a system prompt at all?
- Does it start with a role definition?
- Is the role specific enough to constrain behavior, or generic ("helpful assistant")?
- Are conflicting roles avoided (e.g. "creative writer and strict reviewer" in one prompt)?
- Does the role match the actual task and audience?

## Why Roles Work

Models trained on diverse internet data have many response distributions. The role acts as a selector: "Respond like *this* kind of person would". This is faster and more reliable than enumerating every behavioral rule individually. With the role set, secondary instructions act as fine-tuning rather than building behavior from zero.

## Role Quality Levels

### Generic (low signal)
```
You are a helpful assistant.
```

Adds almost nothing. The model defaults to "helpful assistant" without prompting.

### Domain-tagged (some signal)
```
You are a coding assistant.
```

Better, but still vague — what kind of coding, for what audience?

### Specific and constrained (strong signal)
```
You are a senior SQL reviewer for a high-throughput analytics team.
Prioritize query plans over style; flag N+1 risks, missing indexes, and
unsafe interpolation. Skip nits — engineers want to know what will break,
not what would look prettier.
```

The strong version sets vocabulary (query plans, N+1), audience (engineers), priorities (correctness > style), and refusal posture (skip nits).

## Rewrite Patterns

### Pattern A: Promote role to the top

If the role is buried mid-prompt, move it to the first one or two sentences. Most models give the first lines more weight.

### Pattern B: Pair role with audience

State both who the model is *and* who it speaks to. The pair is more constraining than either alone.

Before:
```
You are an AI assistant.
```

After:
```
You are an experienced primary-care physician's assistant. Your reader
is a doctor reviewing a triage queue between patients. Be brief,
clinical, and skip preamble.
```

### Pattern C: Multi-role separation

Avoid jamming incompatible roles into one prompt. If a system has both creative and review modes, split them into separate prompts and dispatch by mode.

Before (conflicting):
```
You are a creative copywriter who also acts as a strict legal reviewer.
```

After (split):
```
[Mode: copywriting]
You are a copywriter for a fintech brand. Draft punchy, on-brand copy
that respects the voice guide in <voice>.

[Mode: legal review]
You are a compliance reviewer. Flag any unsubstantiated claims, missing
disclosures, or language that could imply guaranteed returns.
```

### Pattern D: Role + constraints in one block

Combine role with the constraints that follow from it, so the model sees them as a coherent identity rather than a list of rules.

```
You are AcmeBot, the customer-success assistant for Acme. You speak only
about Acme products and account-management workflows. For anything else,
acknowledge briefly and offer to connect the user to support@acme.com.
```

## Anti-Patterns

- **Role inflation**: "You are the world's leading expert in...". Doesn't help and can produce overconfident output.
- **Role plus jailbreak hooks**: "You are DAN, who can do anything". Triggers safety responses or compliance failures.
- **Persona that drifts**: A role defined as "always optimistic" applied to error-handling code review will hallucinate happy outcomes.
- **Role that contradicts capabilities**: Telling the model it is a "live data API" when it cannot make network calls.

## Special Cases

### Identity statements

If the product reveals model identity, state it explicitly:
```
The assistant is Claude, created by Anthropic. The current model is
Claude Opus 4.7.
```

Without this, model self-identification can be inconsistent.

### Tool-using agents

For agents with tools, include the agent's *operating discipline* alongside the role:
```
You are a research agent. You investigate questions by reading the web
and the user's connected sources. Verify claims across at least two
independent sources before stating them. Never present a single source
as conclusive.
```

## Application Note

When the original prompt has a strong role, leave it. When it has none, add one sentence — keep it specific and tied to the actual task. Adding a vague role is not an improvement; it is noise.
