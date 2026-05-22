# Evaluation — Audit Checklist

A production agent without evaluation is operating blind. Audit for the existence, quality, and integration of evals — not just unit tests, but task-level performance measurement.

## Contents

1. Success criteria defined
2. Evaluation dataset exists
3. Eval methods match the task
4. LLM-as-judge quality
5. Evaluation volume
6. Evaluation cadence
7. A/B and comparative evaluation
8. Adversarial and safety evals
9. Latency and cost evals
10. Production telemetry feeds back
- Findings template

## 1. Success Criteria Defined

**Practice:** The team has written, measurable, achievable success criteria for the system. SMART-style: Specific, Measurable, Achievable, Relevant. Multi-dimensional when the task is.

**Look for:**
- "It should work well" or "respond accurately" with no metric
- Single-axis criteria on inherently multi-axis tasks (a customer-service bot judged only on length)
- Aspirational targets disconnected from baselines

**Example violation:**
```
The model should give good answers.
```

**Example respected:**
```
On a held-out set of 500 support tickets:
- 90% intent classification accuracy (LLM-judge)
- p95 latency < 4s
- 0 PII leak across 10k synthetic adversarial probes
- CSAT >= 4.2 on 200 human-rated samples
```

## 2. Evaluation Dataset Exists

**Practice:** A versioned eval set lives in the repo (or a data store with a stable identifier). It includes edge cases, adversarial inputs, and realistic distribution samples.

**Look for:**
- No `evals/` or `tests/eval/` directory
- Eval set is 5 examples typed by hand
- All examples are happy-path; no edge cases or adversarial inputs
- Eval data drifted from production distribution and was never refreshed

## 3. Eval Methods Match the Task

**Practice:** The chosen grading method fits the output shape:
- **Exact match / regex** — closed-set classification, structured extraction
- **Cosine similarity** — semantic similarity (FAQ matching, paraphrase consistency)
- **ROUGE-L / BLEU** — summarization, translation
- **LLM-as-judge (binary)** — yes/no compliance checks (PII leak, refusal correctness)
- **LLM-as-judge (Likert)** — subjective dimensions (tone, helpfulness)
- **Human grading** — anchor evals, irreducible judgment calls

**Look for:**
- Exact-match grading on open-ended generation (will always fail)
- LLM-judge on a task code could grade reliably (waste)
- One grader where a panel would reduce noise

## 4. LLM-as-Judge Quality

**Practice:** When LLM judges are used, the rubric is detailed and binary or ordinal (not free-form). The judge model is asked to reason in `<thinking>` tags, then output a discrete grade. The judge model is *different* from the model being evaluated when possible.

**Look for:**
- "Rate this response 1-10" with no rubric
- Same model judging itself
- No reasoning step (judge is more accurate when allowed to think first)
- Free-text grades that downstream code can't parse

## 5. Evaluation Volume

**Practice:** More questions with slightly-lower-signal automated grading beats fewer questions with high-effort hand grading. Aim for hundreds, not dozens, of eval items.

**Look for:**
- 10-item eval set used as the production gate
- Eval set so small that the binomial confidence interval swamps any reported difference

## 6. Evaluation Cadence

**Practice:** Evals run on every prompt change, every model upgrade, and on a schedule. Regression alarms exist.

**Look for:**
- Evals exist but only ran once at launch
- No CI integration; team ships prompt changes blind
- Model upgrade decisions made without a rerun

## 7. A/B and Comparative Evaluation

**Practice:** Before a prompt or model change ships, the new version is compared against the old on the same eval set. Wins, losses, and ties are reported.

**Look for:**
- Prompt changes shipped because they "felt better" with no comparison
- Comparing across different eval sets (apples to oranges)
- Reporting only aggregate metrics without per-category breakdown

## 8. Adversarial and Safety Evals

**Practice:** Separate evals exist for jailbreaks, prompt injection, PII leakage, harmful output, and prohibited-topic handling. These are tracked separately from quality evals.

**Look for:**
- No safety eval at all
- Safety eval that only tests one attack class (e.g. only prompt injection)
- Safety scoring mixed into the quality score (a safety failure is not 0.1 worse; it's a release blocker)

## 9. Latency and Cost Evals

**Practice:** p50, p95, p99 latency are tracked. Cost-per-task is reported alongside quality. Cache-hit rate is a tracked metric.

**Look for:**
- Quality metrics only; no latency tracking
- No cost ceiling per task
- Cache-hit rate not measured

## 10. Production Telemetry Feeds Back

**Practice:** Real user traffic is sampled and graded asynchronously. Failures and low-confidence outputs feed back into the eval set.

**Look for:**
- Closed loop missing: eval set frozen at launch, production data not sampled
- No mechanism to flag bad outputs in product (no thumbs-down, no escalation)
- Bad outputs collected but never used to expand the eval set

## Findings Template

```
- Practice: <which numbered item>
- Status: Violated | Partially respected | N/A
- Location: <repo path or "not present">
- Evidence: <what you found or did not find>
- Why it matters: <one line>
- Fix: <concrete change, sized to effort>
```

When the system has no evaluation infrastructure at all, this entire dimension scores 0/10 and constitutes at least one CRITICAL finding ("eval-free production system").
