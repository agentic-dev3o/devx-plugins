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

### fixing-skills

Evaluates and improves a plugin's skills by applying Anthropic's skill authoring best practices. Triggers when you ask to fix, improve, or review skills.

---

### fixing-react-antipatterns

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

---

### claudemd

Keeps CLAUDE.md in sync with codebase evolution. Triggers when you ask to update or sync CLAUDE.md.

**What happens:**
1. Finds your CLAUDE.md (or creates one)
2. Analyzes commits since last update
3. Detects new patterns, stack changes, architecture shifts
4. Proposes additions and removals in diff format
5. Asks for confirmation before applying

Your project memory stays current without manual maintenance.
