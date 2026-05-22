# Technique 6: Communication Style and Verbosity

## Contents

- Principle
- Diagnostic questions
- Verbosity calibration (too verbose, too terse, mismatched)
- Tone calibration (warmer, crisper, customer service)
- Markdown control
- Preamble suppression
- User-facing updates in long-horizon agents
- Anti-patterns
- Application note

## Principle

Recent Claude models (4.6 family and beyond) calibrate response length to perceived task complexity rather than defaulting to a fixed verbosity. Without explicit guidance, you get long replies on open-ended tasks and short ones on lookups — which is often right but sometimes catastrophically wrong (e.g. a customer-service product that suddenly writes essays).

## Diagnostic Questions

- Does the prompt state expected response length?
- Is the tone matched to the audience?
- Is markdown usage controlled, or left to default?
- Is preamble ("Here is..." / "Based on...") explicitly suppressed or allowed?
- For interactive products, is the verbosity calibrated to the UI?
- For long-horizon agents, is the user-update frequency specified?

## Verbosity Calibration

### Symptom: Too verbose

If responses are consistently longer than the use case needs, add:

```
Provide concise, focused responses. Skip non-essential context, and
keep examples minimal.
```

For SMS or chat UIs:
```
Responses render in a chat bubble. Keep replies to 1-3 short sentences.
```

For voice (TTS):
```
Your response will be read aloud. Use short sentences, no markdown,
no bullet points, no ellipses, no parentheticals.
```

### Symptom: Too terse

When responses skip important reasoning steps:

```
Show your reasoning before answering. For complex multi-step problems,
walk through the steps before giving the final answer.
```

### Symptom: Verbose on simple, terse on complex

This is usually a model-default mismatch. Adjust effort level (Claude 4.7) rather than prompting around it. If you must stay at low effort:

```
This task requires multi-step reasoning. Think carefully before answering.
```

## Tone Calibration

Recent Claude defaults: direct, less validation-forward, fewer emoji. If your product needs a different voice, state it.

### Warmer, more conversational
```
Use a warm, collaborative tone. Acknowledge the user's framing before
answering. It is OK to use first-person plural ("we") when describing
a process you can walk them through.
```

### Crisper, more technical
```
You speak with senior engineers. Skip validation phrases like "great
question". Lead with the answer, then provide context if needed.
Assume the reader knows the field.
```

### Customer service
```
Use a warm but efficient tone. Acknowledge frustration when present,
then move directly to resolution. Avoid corporate-speak ("we appreciate
your business") and avoid over-apology ("I'm so sorry"). One genuine
acknowledgment is better than three formulaic ones.
```

## Markdown Control

Claude 4.6+ models default to LaTeX for math and markdown for structure. Both can be wrong for your context.

### Disable markdown
```
Format your response in plain text only. Do not use markdown. Do not use
LaTeX. Do not use bullet points unless presenting genuinely discrete
items. Write in flowing prose.
```

### Disable LaTeX only
```
Format math using plain text characters: "/" for division, "*" for
multiplication, "^" for exponents. Do not use LaTeX or MathJax notation.
```

### Reduce bullet-list overuse
```
<avoid_excessive_markdown_and_bullet_points>
Write in clear prose using paragraphs and sentences. Reserve markdown
primarily for `inline code`, code blocks, and simple headings (### or ##).
Avoid **bold** and *italics*. Do not use bullet lists unless presenting
truly discrete items.
</avoid_excessive_markdown_and_bullet_points>
```

## Preamble Suppression

The model often opens with "Here is...", "Based on the documents...", "Sure! Let me...". For many products this is wasted tokens.

```
Respond directly without preamble. Do not begin with phrases like
"Here is", "Based on", "Sure", or "Let me". Lead with the answer.
```

## User-Facing Updates in Long-Horizon Agents

For agents doing extended work, calibrate how often and how the agent updates the user.

### Default (too quiet)
The agent works silently for minutes, then dumps a result.

### Default (too noisy)
The agent narrates every tool call. User attention burns out.

### Tuned
```
Provide short status updates at key moments: when you start a new phase,
when you find something noteworthy, when you change direction, when you
hit a blocker, when you complete the task. Do not narrate routine tool
calls. One sentence per update.
```

## Anti-Patterns

- Length specified in word count. The model counts tokens, not words. Ask for sentences or paragraphs.
- "Be concise but thorough" — contradictory; pick one and explain when to switch.
- Mixing markdown demands with prose demands ("use bullet points but write naturally") — pick one.

## Application Note

Communication-style fixes are usually small but high-impact for end-user-facing products. The most common gap: no length guidance on a chat product that defaults to long replies. Adding two sentences fixes it.
