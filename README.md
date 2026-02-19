<p align="center">
  <a href="https://dev3o.com">
    <img src=".assets/dev3o.svg" alt="Dev3o" width="200" />
  </a>
</p>

<h1 align="center">DevX Plugins</h1>

<p align="center">
  <strong>AI writes the code. You design the system.</strong>
</p>

<p align="center">
  Battle-tested Claude Code plugins, curated from daily use.
</p>

<p align="center">
  <a href="https://dev3o.substack.com">
    <img src="https://img.shields.io/badge/Newsletter-Subscribe-orange?style=for-the-badge&logo=substack" alt="Subscribe to Newsletter" />
  </a>
</p>

<p align="center">
  <a href="#installation">Installation</a> •
  <a href="#plugins">Plugins</a> •
  <a href="#philosophy">Philosophy</a>
</p>

---

## Why These Plugins

Most plugins in the wild are vibe-coded in an afternoon and never touched again.

**These are different.**

Every command in this marketplace comes from real, daily usage. They've been refined over months of working with Claude Code — not as experiments, but as core tools in an actual development workflow.

- **Curated** — Only what survives daily use makes it here
- **Updated** — Continuously improved based on friction points
- **Tested** — Not "it worked once" — used hundreds of times across real projects
- **Minimal** — No bloat, no clever abstractions, just what works

---

## Installation

**1. Add the marketplace**

```
/plugin marketplace add agentic-dev3o/devx-plugins
```

**2. Install plugins**

Use the interactive plugin browser:
```
/plugin
```

Or install directly:
```
/plugin install devx-git@devx-plugins
/plugin install devx-qa@devx-plugins
/plugin install secrets-guard@devx-plugins
/plugin install devx-ralph@devx-plugins  # Premium - requires yearly membership
```

---

## Plugins

### devx-git

Git workflow automation for developers who commit often and want clean history.

#### `/devx-git:ci`

Conventional commits from staged changes. No more thinking about commit message format.

```
/devx-git:ci
```

**What happens:**
1. Analyzes your staged diff
2. Determines type (`feat`, `fix`, `refactor`, etc.), scope, and subject
3. Shows preview for your confirmation
4. Commits

**Output:**
```
feat(auth): add JWT token refresh endpoint
fix(api): resolve race condition in websocket handler
chore: update dependencies to latest versions
```

> ⚠️ **GPG Signed Commits (macOS Sandbox)**
>
> If you use GPG commit signing with Claude Code's sandbox mode, GPG needs access to its Unix socket. Add this to your `~/.claude/settings.json`:
>
> ```json
> {
>   "sandbox": {
>     "network": {
>       "allowUnixSockets": [
>         "~/.gnupg/S.gpg-agent"
>       ]
>     }
>   }
> }
> ```
>
> This allows GPG to communicate with its agent while keeping git sandboxed. Only tested on macOS.

---

#### `/devx-git:pr [base-branch]`

Create GitHub pull requests with proper descriptions. Defaults to `main`.

```
/devx-git:pr
/devx-git:pr develop
```

**What happens:**
1. Verifies clean working tree
2. Analyzes all commits since base branch
3. Pushes branch if needed
4. Creates PR with summary (the **why**) and test plan
5. Returns the PR URL

---

### devx-qa

Code quality tools for understanding and maintaining projects.

#### `/devx-qa:explain [feature]`

Architecture analysis with ASCII diagrams. No external dependencies.

```
/devx-qa:explain
/devx-qa:explain auth-flow
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

#### `/devx-qa:claudemd [full|quick]`

Keep your CLAUDE.md in sync with codebase evolution.

```
/devx-qa:claudemd
/devx-qa:claudemd quick
```

**What happens:**
1. Finds your CLAUDE.md (or creates one)
2. Analyzes commits since last update
3. Detects new patterns, stack changes, architecture shifts
4. Proposes additions and removals in diff format
5. Asks for confirmation before applying

Your project memory stays current without manual maintenance.

---

### secrets-guard

PreToolUse hook that blocks Claude from reading, writing, or accessing sensitive files.

```
/plugin install secrets-guard@devx-plugins
```

**What it guards:**
- Environment files (`.env`, `.env.local`, `.flaskenv`)
- Private keys & certificates (`.pem`, `.key`, SSH keys)
- Cloud credentials (`.aws/credentials`, `.kube/config`, `.config/gcloud/`)
- App secrets (`credentials.json`, `secrets.yml`, `master.key`)
- Shell history (`.bash_history`, `.zsh_history`)
- And [70+ more patterns](plugins/secrets-guard/patterns.txt)

**How it works:**

The hook intercepts every `Read`, `Write`, `Edit`, `NotebookEdit`, `Bash`, `Glob`, and `Grep` call. File paths and commands are matched against a regex pattern list. On match, the tool call is blocked before execution.

**Requires:** `jq` (available in all major package managers).

> **Known limitation:** Bash command checking uses string-pattern matching. It cannot detect obfuscated access via variable indirection, encoding, glob expansion, symlinks, or command substitution. This hook is a **deterrent layer**, not a sandbox.
>
> For process-level isolation, see [sandbox-shell](https://github.com/agentic-dev3o/sandbox-shell) — a sandboxed shell (MacOS only) that restricts what Claude Code can execute at the OS level.

---

### devx-ralph

**Predicate-driven agentic loop** — Define success criteria, let Claude iterate until they pass.

> **Premium Plugin** — Available to yearly community members at [dev3o.com](https://dev3o.com)

#### `/devx-ralph:plan <task>`

Generate a structured implementation plan with verifiable predicates.

```
/devx-ralph:plan add user authentication with JWT
```

**What happens:**
1. Asks clarifying questions (definition of done, verification command, TDD preference)
2. Analyzes your codebase for patterns and architecture
3. Generates ASCII state machine and sequence diagrams
4. Breakdown to multi-task with shell predicates for success rate
5. Write the detail specification plan use for the half loop

---

#### `/devx-ralph:ralph`

Execute the agentic loop — implements tasks until all predicates pass.

```
/devx-ralph:ralph
```

**What happens:**
1. Reads current plan and identifies next pending task
2. Implements the task (TDD if specified)
3. Runs the predicate to verify completion
4. On success: marks task complete, moves to next
5. On failure: analyzes error, retries with feedback
6. After all tasks pass: enters review phase to catch drift

**Status lifecycle:** `draft` → `running` → `review` → `complete`

---

#### `/devx-ralph:archive`

Archive completed plans and prepare for new work.

```
/devx-ralph:archive
```

Plans are archived to `.claude/ralph-plan/archive/` with incremental numbering.

---

#### Orchestrator Mode

For large plans, run with isolated sessions to avoid context rot:

```bash
~/.claude/plugins/devx-ralph/scripts/ralph-loop.sh
```

**Benefits:**
- Fresh context for each task (no context rot)
- Auto-commit after each task completion
- Token efficient

---

#### Join the Community

devx-ralph is available exclusively to yearly community members.

**[Join at dev3o.com](https://dev3o.com)** to get access to:
- devx-ralph plugin
- Priority support
- Early access to new plugins
- Direct feedback channel

---

## Philosophy

**Battle-tested** — Every command exists because it solved a real problem, repeatedly. Nothing theoretical.

**Opinionated** — Conventional commits. Proper PR descriptions. ASCII diagrams. Decisions are made so you don't waste time configuring.

**Honest** — If something doesn't work well, it gets fixed or removed. No dead code, no abandoned features.

**Minimal** — No dependencies. No build steps. Just markdown that Claude understands.

---

## Author

Built by [Pierre Tomasina](https://github.com/pierozi) — building tools for AI-native development.

**Dev3o** — Teaching developers the 10% that AI can't figure out.

---

<p align="center">
  <a href="https://dev3o.com">Website</a> •
  <a href="https://x.com/pierozi">X</a> •
  <a href="https://www.linkedin.com/in/pierretomasina/">LinkedIn</a>
</p>
