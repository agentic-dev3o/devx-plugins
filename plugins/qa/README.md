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

### dead-code-fixer

Finds and removes dead code across a whole repository, including one far too large for a single context window. Your session (Opus 5.5 or Fable recommended) orchestrates; Haiku 5.5 subagents do the bulk reading; a bookkeeping script, `ledger.py`, keeps every candidate, vote and removal on disk and tells the orchestrator its next step. Explicitly invoked — it does not auto-trigger.

```
/devx-qa:dead-code-fixer
/devx-qa:dead-code-fixer packages/api
/devx-qa:dead-code-fixer --report-only
/devx-qa:dead-code-fixer --yes          # approve deletions up front, for unattended runs
```

**What happens:**
1. Preflight: resume an interrupted run if one exists; otherwise a clean tree, a `dead-code/<date>` branch, the project's own type-check and test commands (or the toolchain's standard ones) run green before anything changes, and the public boundary (published API, entry points, framework conventions) written down as facts every verifier receives
2. Detect: knip, vulture, rustc, deadcode/staticcheck, PHPStan, debride or SARIF (PMD, detekt, .NET) run through the ledger, which keeps their reports and re-runs them each round; Haiku scanners inventory the languages no analyzer covers; one deterministic pass counts every mention of every candidate across all tracked files, configs and templates included, with prose counted apart
3. Verify: three Haiku verifiers per candidate, one lens each — real references, runtime reachability (reflection, string dispatch, decorators, config, templates), outside consumers (public API, entry points, remote callers). Each lens only sees what the previous one voted dead; deletion needs all three at confidence ≥ 80, tallied by the script, never by a model
4. Spot-check and confirm: the orchestrator re-reads the riskiest confirmed-dead candidates itself — the script refuses to remove anything before it does — then asks before the first deletion (`--yes` answers for you)
5. Remove in waves of file-disjoint units: Haiku removers delete, the script compares each unit's diff with what it was given and rejects anything else, the type-check gates every wave, and one commit per green wave. A unit that breaks the gate is reverted and recorded as alive; when the error names no unit, the script finds the culprits by re-running the gate on halves of the wave
6. Iterate: the test suite gates each round; when it fails, the script reverts the round's wave commits one at a time to find the one at fault, and `git revert` undoes it. Rounds repeat until one removes nothing — deleting code orphans more code
7. Report: removed, reverted by the gate, left for a human, test-only code, unused dependencies, and what was not scanned and why

The fan-out runs as the `devx-qa:dead-code-fanout` workflow (16 agents at a time, one completion notice per stage), with a fallback to plain subagents when workflows are unavailable. Every unit is sized so each Haiku 5.5 request stays below 100k tokens, the threshold above which Haiku 5.5 costs five times more.

**Requirements:** git, Python 3.8+, and Claude Code 2.1.293 or later, where the `haiku` alias resolves to Haiku 5.5 on the Anthropic API. On Bedrock, Vertex AI or Foundry the alias still means Haiku 4.5; set `ANTHROPIC_DEFAULT_HAIKU_MODEL` to change it.

**Permissions:** a run spans many turns, and the skill's pre-approved tools only cover the first. Use auto mode, or allow `Bash(python3 "<skill dir>/scripts/ledger.py" *)` (the directory contains the plugin version; the ledger runs the gate commands recorded at the start, so approve it only where you trust them), `Workflow(devx-qa:dead-code-fanout)`, the `git switch`, `status`, `log` and `revert` commands, and `Edit(./**)` or `acceptEdits` mode for the agents and removers. Unattended runs (`claude -p`) also need `--yes` and `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, so the session waits for long workflows.

Never pushes, never rewrites history (`git revert` only), never deletes migrations, generated or vendored code, and never edits code to make a gate pass. Repository text is treated as data: a comment telling agents what to delete changes nothing.

`scripts/test_ledger.py` checks the bookkeeping script end to end without a model; `evals/` builds six fixture repositories with ground truth and runs and grades the whole skill on them headless (see `EVALUATIONS.md`).

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
