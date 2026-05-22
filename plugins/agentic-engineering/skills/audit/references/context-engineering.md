# Context Engineering — Audit Checklist

Context engineering is the discipline of getting the right information into the right position in the model's context window, with the right structure, at the right cost.

## Contents

1. Document placement
2. Document structuring
3. Quote grounding
4. Context window budget awareness
5. Retrieval quality (when RAG is used)
6. State and memory across turns
7. Multi-window / long-horizon patterns
8. Input sanitation and injection defense
9. Token-cost hygiene
10. Context awareness signals (Claude 4.6+)
- Findings template

## 1. Document Placement

**Practice:** Long documents and reference material go *near the top* of the prompt, above the query, instructions, and examples. Anthropic measures up to 30% quality improvement from this on multi-document tasks.

**Look for:**
- System prompt + tools, then `{{LARGE_DOCUMENT}}`, then the user question buried at the bottom — common but suboptimal
- Documents and instructions interleaved, breaking parsing
- Query at top, then 100k tokens of documents — worst case

## 2. Document Structuring

**Practice:** Each document is wrapped in `<document>` with `<source>` and `<document_content>` subtags. Metadata (date, author, section) helps citation.

**Look for:**
- Documents concatenated with `\n\n---\n\n` separators
- No source/metadata tags, making citation impossible
- Inconsistent tagging across documents in the same prompt

**Example respected:**
```xml
<documents>
  <document index="1">
    <source>2024-q3-earnings.pdf</source>
    <date>2024-10-22</date>
    <document_content>{{Q3_DOC}}</document_content>
  </document>
  <document index="2">
    <source>2024-q4-earnings.pdf</source>
    <date>2025-01-30</date>
    <document_content>{{Q4_DOC}}</document_content>
  </document>
</documents>
```

## 3. Quote Grounding

**Practice:** Before answering a question over long documents, the model is asked to extract relevant quotes into a `<quotes>` block. This cuts hallucinations and forces the model to find evidence.

**Look for:**
- Long-context tasks where the model is just asked "answer the question" with no extraction step
- Quote extraction asked for *after* the answer (too late to ground reasoning)

## 4. Context Window Budget Awareness

**Practice:** The system manages the context budget — it does not stuff everything in and hope. Choices:
- Retrieval/RAG when documents exceed budget
- Chunking with overlap when ordered context is needed
- Summarization when older turns must persist
- Memory tool when state must outlive the window

**Look for:**
- Hard-coded full-document inserts that grow unbounded
- No mechanism to evict or summarize old turns
- Loading 200k tokens on every call when 5k would do
- For Claude Sonnet 4.6 / Haiku 4.5: not telling the model about external memory or compaction

## 5. Retrieval Quality (when RAG is used)

**Practice:** Retrieval is tuned and measured. The system embeds queries, retrieves top-K with a re-ranking step when K > 10, and includes source metadata.

**Look for:**
- Embedding model mismatched to use case (general-purpose on code search)
- No re-ranker on K > 20
- Retrieved chunks with no source attribution
- Stale index with no refresh schedule
- Chunk size > 1k tokens with no overlap, splitting key passages

## 6. State and Memory Across Turns

**Practice:** Multi-turn conversations carry forward only what is needed. Long histories are compacted or persisted to an external store, not replayed in full.

**Look for:**
- Naive `[...previous_messages, new_message]` that grows linearly forever
- No summarization checkpoint at turn boundaries
- Tool results from 20 turns ago still in the message list
- Sensitive data persisted in conversation state when it shouldn't be

## 7. Multi-Window / Long-Horizon Patterns

**Practice:** For tasks spanning multiple context windows, the system uses external state (files, git, structured JSON) to resume. The model is told how to read and update state.

**Look for:**
- Multi-window agentic work with no `progress.txt`, `tests.json`, or equivalent
- No instruction to call `pwd` / read state at the start of a fresh window
- Stopping work early "because context is full" instead of compacting

**Example respected prompt snippet:**
```
Your context window will be automatically compacted as it approaches its
limit. When you resume from a fresh context, review progress.txt, tests.json,
and the git log before continuing. Do not stop tasks early due to token
budget concerns.
```

## 8. Input Sanitation and Injection Defense

**Practice:** User-supplied content that enters the prompt is wrapped in tags (`<user_input>`), and the model is told to treat content inside those tags as data, not instructions.

**Look for:**
- Untrusted text concatenated directly into the system prompt
- No fencing around `{{USER_QUERY}}` interpolations
- Tool outputs (which may contain attacker-controlled strings) injected into the model without fencing or summarization

## 9. Token-Cost Hygiene

**Practice:** Boilerplate is minimized. Few-shot examples are reused via cache. Verbose framing ("Please carefully read the following...") is trimmed.

**Look for:**
- Repeated full schema dumps inside few-shot examples when one suffices
- Examples 10x longer than needed
- Restating the role 3 times in different sections
- Markdown bullets when prose would be shorter

## 10. Context Awareness Signals (Claude 4.6+)

**Practice:** When using Claude Sonnet 4.6 / Haiku 4.5 in long-horizon agentic loops, the prompt acknowledges the model's awareness of remaining budget and tells it whether external compaction exists.

**Look for:**
- Long-running agent without an instruction about budget behavior
- Telling the model "the context is small, wrap up" when it can in fact be compacted
- Memory tool available but not described in the prompt

## Findings Template

```
- Practice: <which numbered item>
- Status: Violated | Partially respected
- Location: <file:line or prompt section>
- Evidence: <quote or measurement>
- Why it matters: <one line>
- Fix: <concrete change>
```
