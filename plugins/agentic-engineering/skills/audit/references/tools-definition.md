# Tools Definition — Audit Checklist

Tool definitions are part of the model's prompt. Bad tool descriptions degrade tool selection accuracy, parameter quality, and parallel execution behavior.

## Contents

1. Tool name quality
2. Tool description depth
3. Parameter schemas
4. Tool count and cohesion
5. Parallel tool call affordance
6. Error surfaces
7. Input validation and safety
8. Idempotency and side effects
9. Tool triggering guidance
10. Streaming and long-running tools
11. Object references and IDOR-prone schemas
- Findings template

## 1. Tool Name Quality

**Practice:** Names are verb-first, snake_case (or camelCase to match the SDK convention), describe the *action*, and are distinct enough that the model never confuses two tools.

**Look for:**
- Vague names: `do_thing`, `helper`, `process`, `handle_request`
- Near-duplicate names: `get_user` and `fetch_user` and `read_user`
- Names that hide side effects: `get_x` that actually mutates

## 2. Tool Description Depth

**Practice:** Each tool description states what it does, when to use it, when *not* to use it, and what it returns. Two to five sentences is the typical sweet spot.

**Look for:**
- One-line descriptions on non-trivial tools
- Descriptions that restate the name without adding information
- No mention of side effects, costs, or rate limits
- No "use this when" clause to disambiguate from sibling tools

**Example violation:**
```json
{
  "name": "search",
  "description": "Search."
}
```

**Example respected:**
```json
{
  "name": "search_docs",
  "description": "Full-text search across product documentation. Use for questions about features, APIs, or pricing. Do NOT use for code search (use code_search) or for finding open tickets (use ticket_search). Returns up to 10 snippets ranked by relevance, each with a doc URL."
}
```

## 3. Parameter Schemas

**Practice:** Every parameter has a description, a type, and (when relevant) an enum or pattern. Required parameters are marked. Defaults are specified.

**Look for:**
- `additionalProperties: true` accepting arbitrary input
- Parameters with no description ("query: string" alone)
- Enums missing when the field has a fixed value set
- Optional and required not marked
- Free-form strings where a structured type would fit

## 4. Tool Count and Cohesion

**Practice:** A focused tool set (typically 3–15 tools) outperforms a sprawling one. Tools should not overlap in scope.

**Look for:**
- 30+ tools where many are stale or never used
- Two tools doing essentially the same job
- One mega-tool with a `mode` parameter that branches into unrelated behaviors

## 5. Parallel Tool Call Affordance

**Practice:** For models that support it (Claude 4.x, recent GPT-4 series), the system prompt encourages parallel calls when actions are independent. Tool definitions do not have hidden ordering requirements.

**Look for:**
- No mention of parallelism when the workload obviously fans out (reading 5 files, searching 3 indexes)
- Tools that *require* sequential calls without saying so
- Anti-pattern: "After each tool call, summarize before calling the next" — forces serialization

**Example sample prompt (Anthropic best practices):**
```
If you intend to call multiple tools and there are no dependencies between
the tool calls, make all of the independent tool calls in parallel.
```

## 6. Error Surfaces

**Practice:** Tool results return structured errors the model can act on. Errors include enough context to choose a different approach.

**Look for:**
- `throw` paths that surface as opaque "tool failed"
- Errors that say "error" with no reason
- HTTP errors leaking raw stack traces or secrets
- No retry guidance for transient failures

## 7. Input Validation and Safety

**Practice:** Tools validate inputs at the boundary. Destructive tools (deletes, mutations, external posts) gate behind explicit confirmation or scope checks.

**Look for:**
- `execute_shell` with no allowlist, no sandbox, no audit log
- `delete_*` tools called without dry-run support
- File-write tools that accept absolute paths anywhere
- SQL execution accepting raw query strings without parameter binding

## 8. Idempotency and Side Effects

**Practice:** Side-effecting tools document their idempotency. The model is told whether calling twice is safe.

**Look for:**
- Mutation tools without idempotency keys when retries are possible
- "Send email" tools called inside loops without dedupe
- Charge/payment tools without explicit single-call constraints

## 9. Tool Triggering Guidance

**Practice:** The system prompt tells the model *when* to use each tool, not just that the tools exist. Claude 4.7 uses tools less aggressively than 4.6 by default and may need explicit prompting.

**Look for:**
- Tool list exists but the prompt never references when to call them
- "You have access to web search" with no triggering rule (will undertrigger)
- Over-aggressive triggering ("MUST use X tool for every question") causing over-search

## 10. Streaming and Long-Running Tools

**Practice:** Tools that take >5s or produce large outputs are designed for the runtime: chunked results, progress events, or async with a polling tool.

**Look for:**
- Tool that runs a 10-minute job and blocks the loop
- Large file reads returning megabytes inline
- No timeout on outbound HTTP

## 11. Object References and IDOR-Prone Schemas

**Practice:** Tool schemas that accept an identifier or reference to select a specific object (id, uuid, slug, path, key, ref) require an authorization check inside the implementation. Where possible, design the schema so the object is implicit from the call's authenticated context rather than supplied as a free-form parameter.

**Why this matters at schema-design time:** Tool schemas shape the IDOR risk surface of the entire system. A schema that takes a free-form `object_id` is implicitly opting into "I will authz at runtime" — easy to forget, hard to audit later. A schema where the object is context-bound makes the IDOR class impossible by construction. In an agentic system, the IDs that reach a tool may originate from the user, a previous tool's output, a retrieved document, or the model's own reasoning — none of these should be treated as trusted.

**Look for:**
- Tools whose only or primary argument is a raw ID (`get_invoice(invoice_id)`, `delete_user(user_id)`)
- Tools that accept both `tenant_id` and `object_id` from the model — both are spoofable; the tenant scoping adds no security when both come from the model
- Path/URL parameters with no schema-level allowlist (`fetch_file(path)`, `open_url(url)`)
- ID parameter types with no documented "where does this come from?" — a sign the design hasn't reckoned with trust boundaries
- Destructive tools (`send_*`, `transfer_*`, `delete_*`) with multiple attacker-controllable parameters

**Example violation:**

```json
{
  "name": "send_invoice",
  "parameters": {
    "invoice_id": "string",
    "destination_email": "string"
  }
}
```

Both arguments are attacker-controllable through prompt injection. The schema neither constrains `destination_email` nor binds `invoice_id` to the caller. Even with downstream authz, the schema design signals that this tool is IDOR-prone.

**Schema-design alternatives (in order of preference):**

1. **Context binding — no ID parameter.** Tool operates on objects already pinned in the call's authenticated session. Use when the object is unambiguous ("my latest invoice", "the active document", "the current tenant's settings").
2. **Capability handles.** Schema accepts an opaque signed token instead of a raw ID. A read tool mints the handle after checking rights; the action tool verifies the signature and acts. The model passes handles, never raw IDs.
3. **Scoped ID + documented authz contract.** Schema takes an ID and the tool's documentation states explicitly that the implementation calls `assert_can_access(caller, id, action)` on every invocation. The runtime check is then audited under the guardrails dimension.
4. **Constrained parameter types.** For path/URL/email-shaped arguments, use stricter schema types (pattern, enum, prefix-match) so the boundary rejects out-of-scope values before the tool runs.

**The cross-tool agentic case:** When one tool's output feeds another tool's input (Tool A returns objects, Tool B acts on one of them), the schema alone cannot prevent IDOR — runtime authz must re-check the caller against the object at Tool B. This is a guardrail concern (see the guardrails dimension, section 11), not a schema fix. The schema-level recommendation here is to make raw-ID parameters the exception rather than the default, so the surface where re-authz is required is minimized.

## Findings Template

```
- Practice: <which numbered item>
- Status: Violated | Partially respected
- Location: <tool name or file:line>
- Evidence: "<schema snippet or description quote>"
- Why it matters: <one line>
- Fix: <concrete change>
```
