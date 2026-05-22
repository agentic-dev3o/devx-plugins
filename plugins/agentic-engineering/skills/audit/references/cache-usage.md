# Cache Usage — Audit Checklist

Prompt caching (Anthropic SDK) and equivalent mechanisms cut latency by 50–80% and cost by up to 90% on cached tokens. The cache has a 5-minute TTL (1 hour with `ttl: "1h"` on the cache_control block). Misalignment with the cache invalidates everything downstream.

> **Framework note:** This dimension applies primarily to Anthropic SDK and the Vercel AI SDK Anthropic provider, where the developer marks cacheable spans explicitly. When the runtime caches automatically without developer-controlled markers (e.g. OpenAI's automatic prefix caching), mark items N/A and audit instead for stable-prefix discipline.

## Contents

1. Cache eligibility
2. Cache block ordering
3. Number and placement of cache breakpoints
4. TTL selection
5. Cache invalidation hygiene
6. Cache hit measurement
7. Cost-aware design
8. Multi-tenant considerations
9. Streaming and cache interaction
10. Other frameworks
- Findings template

## 1. Cache Eligibility

**Practice:** Static prefixes (system prompt, tool definitions, large reference docs, few-shot examples) are marked with `cache_control: {type: "ephemeral"}` when they exceed the minimum (1024 tokens for most models, 2048 for Haiku).

**Look for:**
- System prompts >2k tokens with no cache_control
- Tool definitions blocks (often 1k+ tokens) not cached
- Few-shot examples repeated on every call without caching
- Reference documents inlined per request

## 2. Cache Block Ordering

**Practice:** Content is ordered from *most stable* to *most volatile* — system prompt and tools first, then static context (docs, examples), then dynamic user input last. The cache breakpoint sits at the boundary between stable and volatile.

**Look for:**
- Volatile content (timestamps, user turns) above stable content — defeats the cache
- Dynamic IDs in the system prompt invalidating every call
- Tool list reordered between calls (non-deterministic serialization)

## 3. Number and Placement of Cache Breakpoints

**Practice:** Up to 4 cache breakpoints per request. Place them at natural section boundaries: end of system prompt, end of tool list, end of stable context.

**Look for:**
- One breakpoint near the top covering nothing useful
- Five+ breakpoints (over the limit; the API will reject or ignore)
- Breakpoint mid-string in a paragraph (matches a literal prefix; brittle)

**Example respected (Anthropic SDK):**
```python
system=[
    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
],
tools=[
    *tool_defs,  # last tool gets cache_control
],
messages=[
    {"role": "user", "content": [
        {"type": "text", "text": LARGE_DOC, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": user_question},
    ]},
],
```

## 4. TTL Selection

**Practice:** Default 5-minute TTL is right for interactive chat. The 1-hour TTL (`cache_control: {type: "ephemeral", ttl: "1h"}`) suits batch jobs, scheduled workflows, or long-running agents.

**Look for:**
- 1-hour TTL on highly volatile content (wasted; refreshes drop hits)
- 5-minute TTL on a daily batch — every call misses
- TTL not considered at all (default everywhere)

## 5. Cache Invalidation Hygiene

**Practice:** Anything that can change between calls is *below* the cache breakpoint. Common offenders: dates, request IDs, A/B variant text, randomized example order.

**Look for:**
- `datetime.now()` interpolated into the system prompt
- Random seeds or session IDs above the cache point
- "Hello {user_name}" leading the system prompt
- Reordering examples per call (kills the prefix match)

## 6. Cache Hit Measurement

**Practice:** Cache hit rate is measured. Anthropic returns `cache_read_input_tokens` and `cache_creation_input_tokens` on every response. Hit rate <50% on a workload that should cache is an investigation trigger.

**Look for:**
- No logging of cache metrics
- No alarms on cache-hit regression
- Treating cache as "set and forget" instead of an SLI

## 7. Cost-Aware Design

**Practice:** The team has run the math: at current pricing, cache writes cost 1.25x the base rate and reads cost 0.1x. The breakeven is ~2 hits per write. Don't cache prefixes touched less than twice within the TTL.

**Look for:**
- Caching one-shot prompts (write cost with no read benefit)
- Caching a 100-token system prompt (below minimum; no effect or wasted breakpoint)
- Heavy caching with low traffic — write cost dominates

## 8. Multi-Tenant Considerations

**Practice:** When the prompt prefix varies per tenant, each tenant gets a stable cache namespace; cross-tenant content is below the breakpoint.

**Look for:**
- Tenant ID in the system prompt with no per-tenant cache strategy
- One shared prefix across tenants leaking namespace-specific context

## 9. Streaming and Cache Interaction

**Practice:** Cache reads work with streaming. The first chunk arrives faster on a cache hit. No code is needed to enable this beyond marking the cache_control.

**Look for:**
- Comments suggesting cache "doesn't work with streaming" (outdated)
- Disabling streaming to "get cache" (unnecessary)

## 10. Other Frameworks

**OpenAI SDK:** Automatic prompt caching kicks in for prompts >1024 tokens, with no developer-controlled markers. Audit instead for stable-prefix discipline (same considerations as #5 above) since OpenAI's automatic caching also benefits from stability.

**Vercel AI SDK:** Pass `providerOptions.anthropic.cacheControl` per message part. Same rules as Anthropic SDK apply.

**OpenAI Agents SDK:** Inherits the OpenAI caching model. Audit for stable instruction strings on agents called repeatedly.

## Findings Template

```
- Practice: <which numbered item>
- Status: Violated | Partially respected | N/A (framework)
- Location: <file:line>
- Evidence: <code snippet or measurement>
- Why it matters: <one line, ideally with quantified impact>
- Fix: <concrete change>
```
