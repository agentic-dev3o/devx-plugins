# Technique 8: Parallel Tool Calling

## Contents

- Principle
- Applies when
- Diagnostic questions
- The standard affordance
- Rewrite patterns (add affordance, remove anti-parallel instructions, reduce enthusiasm, disable parallelism)
- Examples from practice (multi-file read, fan-out research)
- Anti-patterns
- Tool-definition side
- Application note

## Principle

Claude 4.x and recent GPT models can issue multiple tool calls in a single turn when the calls are independent. Without explicit prompting, parallelism rate hovers around 60-80%; with prompting, it approaches 100%. Parallel tool use cuts wall-clock latency on multi-tool workloads by 2-5x.

## Applies When

- The system has tools defined.
- The model is on a parallel-capable runtime (Claude 4.x, recent OpenAI models, Vercel AI SDK with a supporting provider).
- Workloads frequently fan out (reading multiple files, querying multiple APIs, searching multiple indexes).

If the system has no tools, mark this technique N/A.

## Diagnostic Questions

- Does the system prompt mention parallelism at all?
- Are there instructions that *force* sequential behavior ("after each tool call, summarize")?
- Do tool definitions have hidden ordering requirements?
- Are independent tools actually used in parallel in observed traces?

## The Standard Affordance

The Anthropic-recommended snippet:

```
<use_parallel_tool_calls>
If you intend to call multiple tools and there are no dependencies between
the tool calls, make all of the independent tool calls in parallel.
Prioritize calling tools simultaneously whenever the actions can be done
in parallel rather than sequentially. For example, when reading 3 files,
run 3 tool calls in parallel to read all 3 files into context at the same
time. Maximize use of parallel tool calls where possible to increase
speed and efficiency. However, if some tool calls depend on previous
calls to inform dependent values like the parameters, do NOT call these
tools in parallel and instead call them sequentially. Never use
placeholders or guess missing parameters in tool calls.
</use_parallel_tool_calls>
```

Drop this verbatim into a system prompt for a tool-using agent unless the workload is intrinsically sequential.

## Rewrite Patterns

### Pattern A: Add parallel affordance

If the prompt has tools and no parallel guidance, add the standard snippet above (or a trimmed version).

### Pattern B: Remove anti-parallel instructions

Look for and remove or revise:

```
After each tool call, summarize the result before calling the next tool.
```

This forces serialization. Replace with:

```
You may summarize partway through if it helps your reasoning. You do not
need to summarize between every tool call.
```

### Pattern C: Reduce parallel call enthusiasm (when over-firing)

For latency- or cost-sensitive workloads where the model fires too many speculative calls:

```
Execute tool calls deliberately. Prefer one well-chosen call over three
speculative ones. Do not call a tool to confirm something you can already
verify from context.
```

### Pattern D: Disable parallelism (rare)

For workloads where every step depends on the previous (e.g. agentic shell sessions where each command's exit code shapes the next):

```
Execute tool calls sequentially, one at a time. Wait for each tool's
result before deciding the next action.
```

## Examples from Practice

### Multi-file read
Without affordance:
```
[tool_call: read_file("a.md")]
[tool_result: ...]
[tool_call: read_file("b.md")]
[tool_result: ...]
[tool_call: read_file("c.md")]
```

With affordance:
```
[tool_call: read_file("a.md")]
[tool_call: read_file("b.md")]
[tool_call: read_file("c.md")]
[tool_result: ..., tool_result: ..., tool_result: ...]
```

Same work; one round-trip instead of three.

### Fan-out research
Without affordance, the agent does a serial chain: search topic 1 → read result → search topic 2 → read result. With affordance, it kicks off all the searches at once, then reads results as they arrive.

## Anti-Patterns

### Telling the model to "use parallelism" without explaining when

```
Use parallel tool calls whenever possible.
```

Triggers parallel calls even for genuinely dependent operations. The standard snippet's "no dependencies between the tool calls" clause matters — keep it.

### Granting parallelism on dependent tools

```
The model should run write_file and then run tests in parallel.
```

Tests on an unwritten file fail. Parallel only applies when calls are truly independent.

### Mixing parallel-encouraging and parallel-discouraging instructions

Decide whether the workload benefits from parallelism and prompt consistently.

## Tool-Definition Side

Sometimes the bottleneck isn't the prompt — it's the tool definitions. Tools that *imply* sequencing in their descriptions ("Call this after fetching X") will be serialized even with parallel prompting. Audit tool descriptions to ensure they describe each tool's behavior in isolation, not its position in a sequence.

Tool description rewrites are a separate concern from prompt optimization — flag the issue and rewrite the description in its own pass.

## Application Note

For any tool-using agent on Claude 4.x or recent GPT, this is one of the highest-impact, lowest-risk additions you can make. The standard snippet is ~10 lines and typically wins 30-50% on latency for fan-out workloads. The most common rewrite gap: tools defined, parallelism unmentioned.
