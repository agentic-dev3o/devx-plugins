# Technique 7: Format Control

## Contents

- Principle
- Diagnostic questions
- Hierarchy of format control (from structured outputs to negative instructions)
- Rewrite patterns (positive description, show schema, wrap output in tags, mirror prompt style, few-shot, forced format)
- Common failures (mixed-format, schema-by-prose, buried format requirement)
- When format control is light
- Application note

## Principle

Output format is steered most reliably by showing the model what to *do*, not what to *avoid*. Positive examples beat negative instructions; structured outputs beat both when the schema is critical.

## Diagnostic Questions

- Does the prompt specify the output format positively, or only forbid alternatives?
- For structured output, is a schema shown (XML, JSON, or pseudocode)?
- For format-sensitive tasks, are there 1-3 examples?
- Does the prompt style mirror the desired output style?
- When the format is critical to downstream code, is a constrained-output mechanism used (structured outputs / forced tool call)?

## Hierarchy of Format Control

From most to least reliable:

1. **Structured outputs / forced tool call** — the API constrains the model to a schema. Use this when the shape must be guaranteed.
2. **Schema in prompt + few-shot examples** — robust for most cases. Pair a written schema with 2-3 worked examples.
3. **Schema in prompt only** — works for simple shapes (single-level JSON, basic XML).
4. **Prose description of format** — fragile; only adequate for free-text outputs with light constraints.
5. **Negative instructions ("don't use X")** — least reliable; the model often complies with the letter but not the spirit.

## Rewrite Patterns

### Pattern A: Convert negative to positive

Before:
```
Do not use markdown in your response.
```

After:
```
Write your response as flowing prose paragraphs. No headings, no bullet
lists, no bold or italic emphasis. Use punctuation for emphasis instead.
```

### Pattern B: Show the schema

Before:
```
Return a JSON object with the user info.
```

After:
````
Return JSON matching this schema:
```json
{
  "name": "string",
  "email": "string (RFC 5322 format)",
  "signup_date": "string (ISO 8601 date)",
  "tier": "free | basic | pro | enterprise"
}
```
````

### Pattern C: Wrap output in tags

Before:
```
Provide the summary and then list action items.
```

After:
```
<summary>
A 2-3 sentence summary.
</summary>

<action_items>
- One action item per line, starting with a verb.
</action_items>
```

Tag-wrapping makes parsing trivial and helps the model separate concerns.

### Pattern D: Mirror your prompt style to your desired output style

If you want prose output, write the prompt in prose. If you want bullet output, use bullets in the prompt. Format leaks both directions — match the prompt to the goal.

### Pattern E: Use few-shot for judgment-laden format

When the format requires judgment (which fields to include, how much detail per field), show 2-3 examples spanning the variation:

```xml
<example>
  <input>...</input>
  <output>
    <classification>positive</classification>
    <confidence>0.9</confidence>
    <evidence>"loved it"</evidence>
  </output>
</example>

<example>
  <input>...</input>
  <output>
    <classification>mixed</classification>
    <confidence>0.6</confidence>
    <evidence>"the plot dragged but the acting saved it"</evidence>
  </output>
</example>
```

### Pattern F: Force the format via constrained outputs

When the downstream code parses the response, do not rely on prompt instructions alone. Use:

- **Anthropic structured outputs** — declare a JSON schema; the API constrains generation.
- **Forced tool call** — define a tool whose parameters match your schema and force the model to call it.
- **OpenAI response_format json_schema** — declare a strict schema with `strict: true`.

These methods guarantee structure in a way prompting alone cannot.

## Common Failures

### Mixed-format demands

```
Output as JSON, with a markdown summary at the top.
```

Pick one. If you genuinely need both, output JSON only and have downstream code format the markdown.

### Schema-by-prose

```
Return an object with the user's name, then their email, then a list
of their orders sorted by date, with each order having an ID and total.
```

Hard to follow. Show the schema instead.

### Format buried below other content

```
[5000 tokens of context]
...
Return your answer as JSON.
```

Repeat the format requirement *next to* the call to action, or restate at the end.

### Punctuation-sensitive formats described in prose

```
Output should be RFC 5322 email format with semicolons separating
addresses and angle brackets around each address.
```

Show one example. Saves words and ambiguity.

## When Format Control is Light

For chat assistants and creative writing where the response is meant to be free-form, do not over-constrain format. The technique is "control format *when needed*", not "always specify format".

## Application Note

The most common rewrite: replace "don't use markdown" with a positive description of the desired prose style. Second most common: add a schema block to a prompt that just said "return JSON". For critical pipelines, recommend migrating to structured outputs rather than relying on prompt-only schema.
