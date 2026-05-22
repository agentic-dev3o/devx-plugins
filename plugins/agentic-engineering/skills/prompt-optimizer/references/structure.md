# Technique 3: Structure with XML Tags

## Contents

- Principle
- Diagnostic questions
- Common failure modes (mixing, inconsistent tags, flat structure, decorative tags)
- Useful tag conventions
- Rewrite patterns (fence variables, wrap examples, nest items, long-context layout)
- Limits
- Application note

## Principle

XML tags give the model unambiguous boundaries between instruction, context, examples, and dynamic input. The model was trained on XML-tagged prompts and recognizes them as section markers — this is more reliable than markdown headings, ALL CAPS, or whitespace alone.

## Diagnostic Questions

- Does the prompt mix instructions and dynamic input ({{VARIABLES}}) inline?
- Are documents, examples, or constraints distinguishable from prose?
- Are tag names consistent across the prompt?
- Are nested concepts in nested tags (e.g. multiple documents inside `<documents>`)?
- Is dynamic user input fenced so injection cannot escape into instructions?

## Common Failure Modes

### Mixing instruction and input

```
Summarize this email: {{EMAIL}} into 2 sentences focused on action items.
```

After:
```
<task>Summarize the email below into 2 sentences focused on action items.</task>

<email>
{{EMAIL}}
</email>
```

### Inconsistent tag names

```
<input>...</input>
<INPUT_DATA>...</INPUT_DATA>
<userInput>...</userInput>
```

Pick one convention (`<user_input>` is common) and use it throughout.

### Flat structure when hierarchy exists

```
<doc>A.pdf content</doc>
<doc>B.pdf content</doc>
<doc>C.pdf content</doc>
```

After:
```xml
<documents>
  <document index="1">
    <source>A.pdf</source>
    <document_content>...</document_content>
  </document>
  <document index="2">
    <source>B.pdf</source>
    <document_content>...</document_content>
  </document>
</documents>
```

### Decorative tags

```
<info>
You are a helpful assistant. Answer the user's questions clearly and
accurately. If you don't know, say so.
</info>
```

A single tag wrapping everything adds no signal. Drop it or break the content into meaningfully separated sections.

## Useful Tag Conventions

| Tag | Use |
|-----|-----|
| `<task>` | The primary instruction |
| `<context>` | Background or motivation |
| `<role>` | Role definition (or use the system field) |
| `<documents>` / `<document>` | Long reference material |
| `<example>` / `<examples>` | Few-shot examples |
| `<user_input>` / `<untrusted_input>` | Dynamic user content (fenced) |
| `<output_format>` / `<output_schema>` | Format specification |
| `<thinking>` | Where the model should reason before answering |
| `<answer>` / `<output>` | The final answer container |
| `<constraints>` | Hard rules |

You do not need to use every tag — only the ones that separate genuinely different roles in the prompt.

## Rewrite Patterns

### Pattern A: Fence the variable

Any `{{VAR}}` interpolation should sit inside a tag named after its role.

Before:
```
Translate {{TEXT}} into French.
```

After:
```
<task>Translate the text in <source> into French.</task>

<source>
{{TEXT}}
</source>
```

### Pattern B: Wrap the example block

Before:
```
Here is an example: Question: What time is it? Answer: It is 3pm.

Now do the same for: {{QUESTION}}
```

After:
```
<example>
<question>What time is it?</question>
<answer>It is 3pm.</answer>
</example>

<question>{{QUESTION}}</question>
<answer>
```

(The trailing open tag is a soft prefill — it nudges the model into the answer shape without a hard prefill.)

### Pattern C: Nest related items

Before:
```
Rules:
1. No markdown.
2. No emoji.
3. Max 100 tokens.

Examples:
...
```

After:
```xml
<constraints>
  - No markdown.
  - No emoji.
  - Max 100 tokens.
</constraints>

<examples>
  <example>...</example>
  <example>...</example>
</examples>
```

### Pattern D: Long-context layout

When the prompt includes large reference material, put it inside `<documents>` near the top, then state the task below. Long-context details live in [long-context.md](long-context.md).

## Limits

- XML tags help most when the prompt has multiple content kinds. A 50-token classification prompt does not need them.
- Do not nest deeper than 3 levels — readability drops faster than the model benefits.
- Closing tags matter. Unclosed tags confuse downstream parsers and sometimes the model.

## Application Note

If the prompt is already well-structured, leave it. The most common rewrite is to fence `{{USER_INPUT}}` variables that are sitting inline — this is both a structure win and a prompt-injection defense (untrusted content stays in its own tagged region rather than executing as instructions).
