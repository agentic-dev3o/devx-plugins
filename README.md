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
