# Technique 2: Context and Motivation

## Contents

- Principle
- Diagnostic questions
- Why rationale helps
- Examples (format, length, tone, audience)
- Rewrite patterns (because-clause, downstream consumer, audience, define terms)
- What context is NOT
- Application note

## Principle

Explaining *why* lets the model generalize. A rule with a reason behind it survives edge cases; a rule without one breaks the first time the situation isn't quite what you imagined.

## Diagnostic Questions

- For each numeric threshold or hard constraint, is the reason given?
- For each negative instruction ("never X"), is the rationale clear enough to handle a near-miss case?
- Does the prompt describe *who* will read the output and *where*?
- When a format is requested, is the downstream consumer named?
- Are domain-specific terms defined when the model might not share the team's meaning?

## Why Rationale Helps

The model is general; your context is specific. Without motivation, the model fills in the gap with its prior — which is often wrong for your use case. A single sentence of context can replace dozens of brittle edge-case rules.

## Examples

### Format motivation

Before:
```
NEVER use ellipses.
```

After:
```
Your response will be read aloud by a text-to-speech engine, so never use
ellipses since the engine will not know how to pronounce them.
```

The version with context generalizes: the model will also avoid em-dashes that produce weird TTS, and emoji, and other things you didn't explicitly forbid.

### Length motivation

Before:
```
Keep responses under 100 words.
```

After:
```
Responses appear in an SMS UI that truncates after 160 characters per
message and breaks long replies into many messages. Keep responses to
2-3 short sentences; aim for under 160 characters total when possible.
```

### Tone motivation

Before:
```
Be friendly.
```

After:
```
You speak with first-time users opening their account; warmth helps them
feel welcome on what may be a stressful day. Use plain language, avoid
banking jargon, and acknowledge that questions are normal.
```

### Audience motivation

Before:
```
Explain like I'm five.
```

After:
```
Your reader is a non-technical product manager who needs to make a build-vs-buy
decision today. Skip implementation details; focus on what the choice means
for their roadmap, cost, and risk.
```

## Rewrite Patterns

### Pattern A: Add a "Because" clause

For any rule that could be misinterpreted, append "because <reason>". If you cannot articulate a reason, the rule may not be load-bearing — consider deleting it.

### Pattern B: Frame the downstream consumer

For format rules, name the consumer:
- "Output JSON because the next step parses it programmatically."
- "Use markdown because the response renders in a docs viewer."
- "Avoid markdown because the response goes to a plain-text logs viewer."

### Pattern C: Surface the audience

Once near the top of the prompt:
- "Your reader is <who> in <situation>."
- "This response is consumed by <system> which expects <shape>."

### Pattern D: Define terms that matter

When your team uses a domain term with non-standard meaning, define it:
```
A "boundary" in this system is a tenant-level access scope. A user can
belong to multiple boundaries with different roles in each. When the
boundary parameter is present, every query must filter by it.
```

## What Context is NOT

- Not a place to dump irrelevant company history. Keep it task-relevant.
- Not an excuse to ramble. One sentence of why beats three sentences of background.
- Not a substitute for clarity. Clear + motivated outperforms motivated + vague.

## Application Note

If the prompt already explains its constraints, leave it. If a critical rule has no rationale and the rule is non-obvious, add one. If the prompt is full of "why" but missing "what", apply the [clarity](clarity.md) technique first.
