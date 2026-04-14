---
name: code-review
description: Reviews pull requests and code changes for correctness, conventions, maintainability, performance, test coverage, and security. Use when the user asks for a code review, PR review, feedback on a diff, or to check code quality.
---

# Code Review

Target: `$ARGUMENTS` (optional PR number, branch, path, or diff scope)

## Workflow

Progress checklist:

```
Code Review:
- [ ] Step 1: Identify review target
- [ ] Step 2: Gather change context
- [ ] Step 3: Evaluate the change
- [ ] Step 4: Separate findings from noise
- [ ] Step 5: Deliver findings-first review
```

### Step 1: Identify Review Target

- If `$ARGUMENTS` is empty and the request is about a PR, run `gh pr list` to show open PRs, then ask the user which PR to review.
- If `$ARGUMENTS` looks like a PR number, run `gh pr view <number>` to capture the title, status, base branch, head branch, and summary.
- Otherwise treat the target as local changes, a branch, a commit range, or a file path.

### Step 2: Gather Change Context

- For PR review, run `gh pr diff <number>`.
- For local review, inspect `git diff`, `git diff --staged`, or the diff for the requested range.
- Read the changed files with surrounding context. Do not review the raw diff in isolation.
- Identify the scope: feature, bug fix, refactor, test, docs, or mixed.
- If `gh` is unavailable or unauthenticated, say so clearly and fall back to the available local diff.

### Step 3: Evaluate the Change

Review for:

- **Correctness** — edge cases, null or empty inputs, error handling, stale state, off-by-one logic, async races, retries, cancellation, and timeouts.
- **Maintainability** — naming, duplication, single responsibility, magic values, avoidable complexity, and consistency with nearby code.
- **Performance** — N+1 queries, repeated expensive work, render-loop costs, unnecessary allocations, and over- or under-used memoization.
- **Type safety** — missing narrowing, unchecked unions, overly broad types, and unclear public API return types.
- **Testing** — coverage for happy paths, failure paths, and the most likely regression cases.
- **Security** — auth gaps, injection risks, secret handling, unsafe parsing, XSS, SSRF, or CSRF when relevant.

### Step 4: Separate Findings from Noise

- Flag only issues with real impact on correctness, risk, maintainability, performance, or test confidence.
- Do not bikeshed on formatting or linter-owned style.
- Prefer concrete evidence from the diff and surrounding code over speculation.
- If intent is ambiguous, frame it as a question or risk instead of overstating certainty.

### Step 5: Deliver Findings-First Review

Present findings first, ordered by severity:

- **Must fix** — bugs, security issues, data loss, broken behavior, merge blockers.
- **Should fix** — maintainability issues, meaningful performance problems, missing tests, or convention drift with real cost.
- **Nit** — optional minor suggestions.

For each finding include:

- `file`
- `line` or nearest symbol
- the issue
- why it matters
- a suggested fix

Then include:

1. A short overview of what the change does.
2. Good decisions worth keeping.
3. Residual risks or test gaps.

If no actionable findings remain, say so explicitly and mention any remaining uncertainty.

Use this response shape:

```markdown
## Must fix
- `path/to/file:line` Issue. Why it matters. Suggested fix.

## Should fix
- None.

## Nit
- None.

## Overview
- Brief summary of the change.

## What looks good
- Specific strengths.

## Residual risks
- Missing test coverage, assumptions, or things not verified.
```

## Constraints

- Findings first. Keep the summary brief.
- Be constructive and specific.
- Follow project conventions by reading adjacent code, tests, and config before flagging style issues.
- Do not invent missing context; say what you verified and what you could not verify.
