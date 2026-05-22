# Technique 1: Clarity and Directness

## Contents

- Principle
- Diagnostic questions
- Common symptoms of low clarity
- Rewrite patterns (verb+object+outcome, numbered steps, above-and-beyond, disambiguate pronouns)
- What "clarity" does NOT mean
- Application note

## Principle

Treat the model as a brilliant new colleague with no context on your norms. The more precisely you state what you want, the better the result. The "golden rule": show the prompt to a teammate with no project context — if they would be confused, the model will be too.

## Diagnostic Questions

- Can a reader determine the *exact* output expected from a single read?
- Are instructions written in imperative voice ("Do X") rather than declarative ("X should be done")?
- Are vague verbs (handle, process, deal with, manage) backed by specific outcomes?
- Are pronouns ("it", "this", "the data") tied to clear antecedents?
- Are sequential steps numbered when order matters?
- Are completeness criteria spelled out for multi-part tasks?

## Common Symptoms of Low Clarity

### Vague verbs without object

```
Help the user with their question.
```

### Conflicting instructions

```
Be thorough but concise. Cover all cases but keep responses short.
```

### Implicit standards

```
Respond appropriately.
```

### Missing success criteria

```
Translate this document.
```
(Into what language? Preserving what formatting? With what tone?)

## Rewrite Patterns

### Pattern A: Verb + Object + Outcome

Before:
```
Help summarize emails.
```

After:
```
For each email in <emails>, write a 1-2 sentence summary that states the
sender's primary ask and any deadline. Return summaries as a JSON array
matching <output_schema>.
```

### Pattern B: Numbered Steps for Sequential Work

Before:
```
Review the PR and provide feedback.
```

After:
```
Review the PR in three passes:
1. Read the diff and surrounding code; do not flag style issues.
2. Check for correctness, security, and test coverage.
3. Group findings by severity (must-fix, should-fix, nit).
Return findings in the format shown in <example_output>.
```

### Pattern C: Above-and-Beyond Modifier

When the desired output is "a lot of effort", say so explicitly. The model interprets neutral phrasing as "do the minimum acceptable thing".

Before:
```
Build a dashboard.
```

After:
```
Build a dashboard. Include as many relevant features and interactions as
possible. Go beyond the basics to create a fully-featured implementation.
```

### Pattern D: Disambiguate Pronouns

Before:
```
Look at the data and tell me about it. If there are problems, fix them.
```

After:
```
Look at <input_records>. For each record, identify validation errors
matching the rules in <validation_rules>. Output the corrected record
with errors listed in a <corrections> array.
```

## What "Clarity" Does NOT Mean

- It does not mean longer. A 200-word vague prompt is worse than a 50-word direct one.
- It does not mean removing nuance. When two outcomes are both acceptable, say so.
- It does not mean over-specifying obvious details. Don't define "JSON" or restate model conventions.

## Application Note

When the original is already clear and direct, leave it. Mark "Already respected" in the report. Most prompts written by experienced engineers are clear at the sentence level but fail one of the other techniques (structure, role, or format control).
