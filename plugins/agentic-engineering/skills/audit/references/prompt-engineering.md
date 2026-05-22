# Prompt Engineering — Audit Checklist

Walk every prompt (system and user templates) through this checklist. For each item, decide: Respected, Violated, Partially respected, or N/A.

## Contents

1. Clarity and directness
2. Context and motivation
3. Structure with XML tags
4. Role assignment
5. Examples (few-shot)
6. Response length and verbosity calibration
7. Format control
8. Long-context patterns
9. Communication style for the target audience
10. Identity statements (when required)
- Findings template

## 1. Clarity and Directness

**Practice:** Instructions are specific, unambiguous, and use imperative voice. A colleague with minimal context could follow them.

**Look for:**
- Vague verbs like "handle", "process", "deal with" without object or outcome
- Ambiguous referents ("it", "this", "the data") without antecedent
- Multiple sentences where one would do
- Missing success criteria for the task

**Example violation:**
```
You are an assistant. Help the user with their question.
```

**Example respected:**
```
You are a SQL reviewer. For each query in <queries>, identify any N+1 risk,
missing indexes, or unsafe interpolation. Return findings as JSON matching
the schema in <output_schema>.
```

## 2. Context and Motivation

**Practice:** When a rule could be misinterpreted, the prompt explains *why*. The model generalizes from explanations to edge cases.

**Look for:**
- Negative-only constraints ("never X") without rationale
- Numeric thresholds without justification ("respond in under 100 words")
- Format requirements without context ("output JSON") when reason would help

**Example violation:**
```
NEVER use markdown.
```

**Example respected:**
```
Your response is rendered into a plain-text SMS, so do not use markdown,
HTML, or any formatting that would appear as literal characters to the user.
```

## 3. Structure with XML Tags

**Practice:** Mixed content (instructions, context, input, examples) is delimited with XML tags so the model can parse roles unambiguously.

**Look for:**
- Long prose prompts mixing instructions and dynamic input with no separators
- Inconsistent tag names across the prompt
- Nested content without nested tags (e.g. multiple documents jammed together)
- Tags used as decoration (single `<info>` wrapping everything)

**Example respected:**
```
<documents>
  <document index="1">
    <source>policy.md</source>
    <document_content>{{POLICY}}</document_content>
  </document>
</documents>

<task>Answer the user's question, citing the policy by section number.</task>

<user_question>{{QUESTION}}</user_question>
```

## 4. Role Assignment

**Practice:** A clear role in the system prompt focuses tone, vocabulary, and decision priorities. One sentence is often enough.

**Look for:**
- No system prompt at all
- Generic role ("You are a helpful assistant") on a domain-specific task
- Role buried mid-prompt instead of leading
- Multiple conflicting roles ("You are a creative writer and also a strict reviewer")

## 5. Examples (Few-Shot)

**Practice:** For format-sensitive or judgment-heavy tasks, 3–5 examples wrapped in `<example>` tags steer output more reliably than instructions alone.

**Look for:**
- Format requirements with no exemplar
- A single example doing the work of many (no edge-case coverage)
- Examples that don't mirror the real input distribution
- Examples shown as prose rather than wrapped in tags

**When N/A:** Trivial tasks (one-line classifications with clear labels), or tasks where the structured outputs feature already constrains the schema.

## 6. Response Length and Verbosity Calibration

**Practice:** The prompt explicitly states the expected length and depth, especially for Claude 4.6+ models which calibrate to perceived task complexity.

**Look for:**
- No length guidance on tasks where length matters
- Length given in word count (LLMs count tokens; ask for sentence/paragraph counts)
- Asking for both "comprehensive" and "concise" without resolution
- No mention of when to skip preamble

**Example respected:**
```
Respond with one or two short paragraphs. Skip preamble like "Here is..."
or "Based on the documents...".
```

## 7. Format Control

**Practice:** Output format is described positively (what to do), with concrete tags or a JSON schema when structure matters.

**Look for:**
- "Do not use markdown" without saying what to use instead
- Schema described in prose instead of JSON or XML
- Multiple format demands competing (markdown headings *and* JSON)

**Example respected:**
```
Wrap your final answer in <answer> tags. Inside, write smoothly flowing
prose paragraphs without bullet points or headings.
```

## 8. Long-Context Patterns

**Practice:** When the prompt contains 20k+ tokens of reference material, documents go *above* the query/instructions, wrapped in `<document>` tags. The model is asked to extract relevant quotes before answering.

**Look for:**
- Query at the top, then 50k tokens of context, then "now answer the question"
- Documents concatenated without separators
- No quote-grounding step on tasks where citation matters

## 9. Communication Style for the Target Audience

**Practice:** Tone, jargon level, and warmth are calibrated to the end user. Claude Opus 4.7 is more direct and less validation-forward by default; warmth requires explicit prompting.

**Look for:**
- Customer-facing assistant with no tone guidance — will default to terse
- B2B engineering tool with verbose, warm phrasing — wastes tokens
- Mismatched tone (formal role with casual examples, or vice versa)

## 10. Identity Statements (when required)

**Practice:** If the product reveals model identity, the prompt states it explicitly. Claude does not self-identify with a specific version unless told.

**Look for:**
- Apps that say "I am ChatGPT" or wrong-model branding because identity was not pinned
- Identity pinning hard-coded to a deprecated model name

## Findings Template

For each violation found:

```
- Practice: <which numbered item>
- Status: Violated | Partially respected
- Location: <file:line or prompt section>
- Evidence: "<exact quote from prompt, ≤2 lines>"
- Why it matters: <one line tied to the practice>
- Fix: <concrete change, ≤3 lines>
```
