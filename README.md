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

Every command in this marketplace comes from real, daily usage — refined over months, not as experiments, but as core tools in an actual development workflow.

- **Curated** — Only what survives daily use makes it here
- **Updated** — Continuously improved based on friction points
- **Tested** — Used hundreds of times across real projects
- **Minimal** — No bloat, no clever abstractions, just what works

---

## Installation

**1. Add the marketplace**

```
/plugin marketplace add agentic-dev3o/devx-plugins
```

**2. Browse and install plugins**

```
/plugin
```

---

## Plugins

| Plugin | What it does | Install |
|--------|-------------|---------|
| [**devx-git**](plugins/git/) | Conventional commits & PR creation | `/plugin install devx-git@devx-plugins` |
| [**devx-qa**](plugins/qa/) | Architecture analysis with ASCII diagrams & CLAUDE.md sync | `/plugin install devx-qa@devx-plugins` |
| [**secrets-guard**](plugins/secrets-guard/) | Blocks Claude from accessing sensitive files (70+ patterns) | `/plugin install secrets-guard@devx-plugins` |
| [**landing-page**](plugins/landing-page/) | Structured copywriting & Astro 5 landing page generation | `/plugin install landing-page@devx-plugins` |
| [**devx-ralph**](#devx-ralph) | Predicate-driven agentic loop for structured implementation | Premium — see below |

---

### devx-ralph

**Predicate-driven agentic loop** — Define success criteria, let Claude iterate until they pass.

Ralph-Loop is a premium plugin included in the **[DevX Course](https://dev3o.com/#pricing)**.

| Command | Purpose |
|---------|---------|
| `/devx-ralph:plan <task>` | Generate structured plan with verifiable predicates |
| `/devx-ralph:ralph` | Execute the agentic loop until all predicates pass |
| `/devx-ralph:archive` | Archive completed plans |

**Orchestrator mode** — Run with isolated sessions to avoid context rot, auto-commit after each task, token efficient.

**[Get access at dev3o.com](https://dev3o.com/#pricing)**

---

## Philosophy

**Battle-tested** — Every command exists because it solved a real problem, repeatedly.

**Opinionated** — Conventional commits. Proper PR descriptions. ASCII diagrams. Decisions are made so you don't waste time configuring.

**Honest** — If something doesn't work well, it gets fixed or removed.

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
