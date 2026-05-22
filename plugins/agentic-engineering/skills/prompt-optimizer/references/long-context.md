# Technique 5: Long-Context Layout

## Contents

- Principle
- Diagnostic questions
- The core rule (documents above, query below)
- Common failure modes
- Rewrite patterns (reorder, wrap each document, quote-grounding, add metadata)
- When the prompt is NOT long-context
- Multi-window / long-horizon tasks
- Application note

## Principle

When the prompt contains 20k+ tokens of reference material, *where* you put things matters as much as *what* you put. Anthropic measures up to 30% quality improvement on multi-document tasks just from reordering the same content.

## Diagnostic Questions

- Is the total prompt above ~20k tokens?
- Where are documents relative to the user query?
- Are documents tagged with source and metadata?
- Is the model asked to ground in quotes before answering?
- For tasks requiring citation, can the model name its sources?

## The Core Rule

**Documents go above. Query goes below.**

Standard layout:

```xml
<system>
  role and operating rules
</system>

<user>
  <documents>
    <document index="1">...</document>
    <document index="2">...</document>
    ...
  </documents>

  <task>What I want you to do</task>

  <user_question>{{QUESTION}}</user_question>
</user>
```

This matters because attention skews toward recency for the actual generation step, while the documents benefit from being placed where the model can "look back" to them. The query last lets the model parse the docs first, then read what it should do with them.

## Common Failure Modes

### Query at top, docs at bottom

```
Answer this question: {{QUESTION}}

Here are the documents:
[200k tokens of docs]
```

Performance dips 10–30% versus the corrected layout.

### Documents mashed together

```
[doc 1 content]
---
[doc 2 content]
---
[doc 3 content]
```

The model cannot reliably tell where one doc ends and the next begins, and cannot cite cleanly. Wrap each in `<document>` tags.

### No source metadata

```
<document>...content...</document>
```

Adding `<source>filename.pdf</source>` and `<date>...</date>` enables citation and helps the model resolve contradictions (e.g. older vs newer policy versions).

### No grounding step

A long-context Q&A prompt with no instruction to extract relevant quotes first will produce more hallucinations.

## Rewrite Patterns

### Pattern A: Reorder

Move documents above the query. This is often the single highest-impact change in a long-context prompt.

### Pattern B: Wrap each document

```xml
<documents>
  <document index="1">
    <source>2024-q3-earnings.pdf</source>
    <date>2024-10-22</date>
    <document_content>
      ...
    </document_content>
  </document>
  <document index="2">
    <source>2024-q4-earnings.pdf</source>
    <date>2025-01-30</date>
    <document_content>
      ...
    </document_content>
  </document>
</documents>
```

### Pattern C: Quote-grounding step

Before:
```
Answer the user's question using the documents.
```

After:
```
Before answering, extract the quotes from the documents that are most
relevant to the question. Place them inside <quotes> tags with their
source. Then write your answer inside <answer> tags, citing source
files inline.
```

### Pattern D: Add metadata that disambiguates

For document sets where context matters (versions, dates, authorship), include the metadata. The model uses it to resolve conflicts.

## When the Prompt is NOT Long-Context

For prompts under ~5k tokens, none of these patterns apply. Trying to add `<documents>` machinery to a short prompt is over-engineering — mark this technique N/A.

## Multi-Window / Long-Horizon Tasks

For tasks that exceed a single context window (Claude Sonnet 4.6 / Haiku 4.5 with context awareness, or any model in an agent loop):

```
Your context window will be automatically compacted as it approaches
its limit, allowing you to continue working indefinitely. Do not stop
tasks early due to token-budget concerns. As you approach the limit,
save your progress and state to disk before compaction. After compaction,
read progress.txt and the git log before continuing.
```

This unlocks long-horizon agentic behavior without premature termination.

## Application Note

The most common rewrite here: move `{{LARGE_DOCUMENT}}` from below the question to above it, and wrap it with source metadata. The change is small but the quality lift is consistent.
