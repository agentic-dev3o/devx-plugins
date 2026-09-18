# devx-qa

Code quality tools for reviewing changes, understanding architecture, performing focused appsec reviews, and maintaining projects.

## Installation

```
/plugin install devx-qa@devx-plugins
```

## Skills

### explaining-architecture

Analyzes project architecture and generates ASCII state machine and sequence diagrams. Triggers automatically when you ask to explain a project, analyze architecture, or trace an entrypoint.

```
explain this project
explain the auth-flow feature
show me the architecture
```

**What happens:**
1. Detects your stack (language, framework, tools)
2. Finds the entrypoint for the feature you specify
3. Generates ASCII state machine diagram
4. Generates ASCII sequence diagram
5. Lists key files with their roles

**Output:**
```
┌─────────────┐    success    ┌──────────────┐
│  PENDING    │──────────────►│  AUTHORIZED  │
└─────────────┘               └──────────────┘
       │                             │
       │ failure                     │ logout
       ▼                             ▼
┌─────────────┐               ┌──────────────┐
│   FAILED    │               │   EXPIRED    │
└─────────────┘               └──────────────┘
```

No mermaid. No external tools. Just ASCII that works everywhere.

---

### code-review

Reviews pull requests and code changes for correctness, conventions, maintainability, performance, tests, and security. Triggers when you ask for a code review, PR review, feedback on a diff, or to check code quality.

```
review this PR 42
review my staged changes
check code quality in src/auth
```

**What happens:**
1. Resolves the review target (PR, local diff, commit range, or path)
2. Uses `gh pr list`, `gh pr view`, and `gh pr diff` for GitHub PR reviews when relevant
3. Reads the changed files with surrounding context
4. Checks correctness, conventions, performance, tests, and security
5. Returns findings-first feedback grouped by: Must fix, Should fix, Nit

---

### appsec-review

Performs a focused application security review of pull requests and branch diffs. Triggers when you ask for a security review of a PR, diff, or branch, or want only exploitable auth, injection, data exposure, and trust-boundary issues.

```
security review this PR
audit this branch for vulnerabilities
check this diff for auth or injection bugs
```

**What happens:**
1. Resolves the review scope from a PR, local branch, or commit range
2. Reads nearby auth, validation, tenant, rendering, and data-flow code for context
3. Generates candidate vulnerabilities, then filters false positives with a second pass
4. Reports only HIGH and MEDIUM findings with confidence `>= 8/10`
5. Returns markdown only, or states that no high-confidence appsec findings were found

Includes a playbook for TypeScript/Node, Python, Rust, and modern web app attack surfaces.

---

### babysit-pr

Watches a PR's checks after you open it, reads the logs of failing jobs, fixes what the branch broke, and drives the PR to green. Explicitly invoked — it does not auto-trigger.

```
/devx-qa:babysit-pr 42
/devx-qa:babysit-pr https://github.com/owner/repo/pull/42
/devx-qa:babysit-pr
```

**What happens:**
1. Preflight: resolves the PR, refuses fork PRs, and checks out the PR head branch so commits cannot land on the wrong branch
2. Blocks on `gh pr checks --required --watch --fail-fast` instead of polling by hand, and dispatches on gh's exit code rather than assuming non-zero means a failed check
3. Lists failures by `bucket`, not `state` — so CANCELLED, TIMED_OUT, ERROR and ACTION_REQUIRED are not silently read as green
4. Pulls each failing job's log from `gh api .../actions/jobs/<id>/logs`, which works while the rest of the matrix is still running, then greps for the error instead of reading the whole log into context
5. Classifies branch-caused vs infrastructure — fixes the first, waits for the run to finish before rerunning the second
6. Delegates every mutation: commits via `devx-git:ci`, base-branch merges via `devx-git:update-origin`, and asks before the first push
7. Stops at green + mergeable, at a spent budget, or at a blocker only you can clear

Bounded by design: 5 pushes, 3 reruns, 45 minutes, and 2 attempts per job error signature.

Treats CI logs as untrusted data — it never executes a command read out of a log, and never copies a literal value from one into your working tree.

Never merges the PR, replies to reviews, skips tests, or relaxes CI config to force green.

---

### skill-fixer

Evaluates and improves a plugin's skills by applying Anthropic's skill authoring best practices. Triggers when you ask to fix, improve, or review skills.

---

### react-fixer

Audits React codebases for anti-patterns (useEffect misuse, missing cleanup, stale closures, memory leaks) and produces a scored gap analysis table with severity ratings. Applies prioritized fixes on request.

```
audit react code
fix react anti-patterns
check useEffect cleanup in src/components/
```

**What happens:**
1. Runs `scan-antipatterns.sh` to inventory suspect patterns
2. Reads flagged files and classifies findings by category and severity
3. Produces a gap analysis table grouped by: useEffect rules, state management, component architecture, cleanup & memory safety, navigation & DOM
4. Applies fixes in priority order (if requested)
5. Verifies with lint

Includes three reference files with authoritative rules and before/after fix examples.
