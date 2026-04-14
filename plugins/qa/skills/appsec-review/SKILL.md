---
name: appsec-review
description: This skill should be used when the user asks to "security review this PR", "review this diff for vulnerabilities", "appsec review these changes", "audit this branch for auth, injection, or data exposure bugs", "check this code for exploitable security issues", or requests a focused application security review of pending changes.
---

# Application Security Review

Target: `$ARGUMENTS` (optional PR number, branch, commit range, or path; default to the current branch against the remote default branch)

## Objective

Review only newly introduced application-layer vulnerabilities in the requested change set. Optimize for high-confidence, exploitable findings with real attacker value. Think in terms of trust boundaries, attacker-controlled inputs, privilege changes, unsafe parsing, outbound request control, data exposure, and framework-specific behavior across TypeScript, Node.js, Python, Rust, and modern web stacks.

Favor signal over coverage. Missing a speculative issue is better than shipping a noisy report.

## Workflow

Progress checklist:

```text
Application Security Review:
- [ ] Step 1: Resolve the review scope
- [ ] Step 2: Build repository security context
- [ ] Step 3: Generate candidate vulnerabilities
- [ ] Step 4: Filter false positives in parallel
- [ ] Step 5: Publish the final markdown report
```

### Step 1: Resolve the Review Scope

- If `$ARGUMENTS` looks like a PR number and GitHub context is available, gather the PR metadata first and review that diff.
- Otherwise resolve the local review base from `origin/HEAD`. If the default branch is unclear, inspect `git remote show origin`.
- Capture the complete review context:
  - `git status`
  - `git diff --name-only <base>...HEAD`
  - `git log --no-decorate <base>...HEAD`
  - `git diff <base>...HEAD`
- Use `git show <commit>` when a suspicious commit needs narrower intent or before/after context.
- If remote comparison is unavailable, fall back to staged plus unstaged local diff and say so explicitly in the review setup.

### Step 2: Build Repository Security Context

- Read adjacent code instead of reviewing the raw diff in isolation.
- Identify the stack, auth model, tenant model, validation patterns, templating paths, serializers, and secret-handling conventions used near the changed files.
- Compare the new code against nearby secure patterns before declaring a finding.
- Load `references/review-playbook.md` for threat-model questions, attack-surface coverage, and stack-specific heuristics.

### Step 3: Generate Candidate Vulnerabilities

- Launch one readonly sub-task dedicated to finding candidate vulnerabilities across the entire change set.
- Use the investigator prompt in `references/subtask-templates.md`.
- Require the sub-task to return candidates only when there is:
  - a changed code location
  - a concrete exploit path
  - meaningful impact
  - preliminary confidence from 7 to 10
- Prefer categories such as `authz_bypass`, `sql_injection`, `nosql_injection`, `command_injection`, `path_traversal`, `unsafe_deserialization`, `xss`, `ssrf`, `jwt`, `data_exposure`, or `crypto_misuse`.

### Step 4: Filter False Positives in Parallel

- Create one readonly validation sub-task per candidate and launch them in parallel.
- Use the validator prompt in `references/subtask-templates.md`.
- Load `references/false-positive-filter.md` inside each validator task.
- Instruct each validator to challenge the candidate aggressively and reject it unless the exploit path is concrete, introduced by the change set, and still valid after considering framework protections and surrounding code.
- If sub-tasks are unavailable, run the same investigator and validator flow inline and validate candidates sequentially with the same filtering bar.

### Step 5: Publish the Final Markdown Report

- Keep only findings with confidence `>= 8/10` after validation.
- Report HIGH and MEDIUM only.
- If no findings survive, say so plainly.
- Output markdown only. Do not include tool transcripts, chain-of-thought, or process notes.
- Use the final report shape in `references/subtask-templates.md`.

## Review Standard

- Focus only on security issues introduced by the reviewed change set.
- Trace attacker input to sensitive sinks such as database queries, shell execution, file access, template rendering, redirects, outbound HTTP, authz gates, token issuance, cache keys, webhook validation, and cross-tenant data filters.
- Prioritize authorization regressions, trust-boundary mistakes, unsafe execution, unsafe deserialization, file and path handling, token and session flaws, sensitive data leakage, and exploitable client rendering bugs.
- Treat local-network reachability as potentially high impact when the attacker can still reach the vulnerable surface.
- Treat Rust as memory-safe by default. Review it for authz, injection, unsafe parsing, crypto misuse, path handling, and logic flaws instead of buffer corruption.
- Treat React and Angular as safe by default unless the change introduces raw HTML, bypass APIs, unsafe markdown or MDX rendering, `srcdoc`, dangerous URL schemes, or server trust decisions pushed into the client.
- Consider security-by-design regressions even when they are not classic OWASP checklist items: missing ownership checks, bypassed middleware, unsafe trust in internal headers, weaker tenant scoping, unsafe webhook assumptions, or security-relevant defaults becoming more permissive.

## Constraints

- Do not drift into general correctness, performance, or style review.
- Do not report unchanged legacy issues except as supporting context for a changed exploit path.
- Do not report hardening gaps without a concrete exploit path.
- Treat user-controlled content in AI prompts as out of scope for this skill.
- Do not write files or make destructive changes while validating a vulnerability.

## Reference Routing

- Read `references/review-playbook.md` during Step 2 for threat-model questions, attack surfaces, and stack-specific heuristics.
- Read `references/false-positive-filter.md` during Step 4 before validating any candidate.
- Read `references/subtask-templates.md` before launching sub-tasks and again before formatting the final report.
