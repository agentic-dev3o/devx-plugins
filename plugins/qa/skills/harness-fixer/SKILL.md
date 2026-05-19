---
name: fixing-harness
description: >-
  Audits a project's agentic harness (CLAUDE.md, AGENTS.md, .claude/rules,
  .claude/settings.json) and refactors it into a layered, path-scoped
  configuration that loads only what is relevant. Rewrites CLAUDE.md and
  AGENTS.md as a thin critical-rules layer, segments domain rules with `paths:`
  frontmatter, and adds deny-first permission guardrails.
  Triggers on: fix harness, audit claude.md, refactor agentic configuration,
  improve agent rules, segment rules by path, review settings.json,
  harness review, claude.md is too long.
disable-model-invocation: true
---

# Fixing the Agentic Harness

Target: `$ARGUMENTS` (optional path; defaults to project root)

## Objective

Refactor the project's harness so the model sees only the rules it needs for the files it touches. CLAUDE.md (and AGENTS.md when present) become a thin always-on critical-rules layer. Domain rules move to `.claude/rules/*.md` with `paths:` frontmatter. Permissions and MCP scope live in `.claude/settings.json` with explicit `deny` guardrails.

The goal is inference weight, not exhaustive documentation: 10 sharp directives the model references in reasoning beat 200 lines it half-skims.

## Workflow

Progress checklist:

```
Harness Audit & Fix:
- [ ] Step 1: Inventory current harness
- [ ] Step 2: Audit against best practices
- [ ] Step 3: Produce gap analysis
- [ ] Step 4: Propose refactor plan (confirm with user)
- [ ] Step 5: Apply changes (CLAUDE.md, AGENTS.md, rules, settings)
- [ ] Step 6: Verify with /memory
```

### Step 1: Inventory Current Harness

Read in parallel where present:

- `CLAUDE.md`, `./.claude/CLAUDE.md`, `CLAUDE.local.md`
- `AGENTS.md` (Codex / Cursor / other agents)
- `.claude/settings.json`, `.claude/settings.local.json`
- `.claude/rules/**/*.md` — note `paths:` frontmatter on each
- `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`
- `.mcp.json`, `.gitignore`

Capture the actual directory layout (top-level apps, packages, services). Use `tokei` if available, otherwise `find` or `ls`. The layout drives the path scopes proposed in Step 4 — generic globs that don't match real directories are dead weight.

### Step 2: Audit Against Best Practices

Load [references/audit-checklist.md](references/audit-checklist.md) and score each dimension:

1. **CLAUDE.md size and shape** — under 30 lines, directives not prose, no domain dump
2. **AGENTS.md alignment** — mirrors CLAUDE.md when present, no drift
3. **Rules segmentation** — path-scoped, one domain per file, no overlap
4. **Permissions hygiene** — explicit `deny` for destructive ops and secrets, scoped allow patterns, MCP tools narrowed
5. **Local overrides** — `.claude/settings.local.json` and `CLAUDE.local.md` in `.gitignore`
6. **Memory ergonomics** — no monolithic root CLAUDE.md drowning monorepo subtrees

### Step 3: Produce Gap Analysis

Output a markdown table:

| Dimension | Status | Severity | Evidence | Suggested fix |
|-----------|--------|----------|----------|---------------|

Status values: **Respected**, **Violated**, **Partially respected**, **N/A**

Severity values:

- **HIGH** — no `deny` rules, secrets readable, CLAUDE.md > 100 lines, no rules layer in a multi-domain project
- **MEDIUM** — CLAUDE.md 30–100 lines, rules without path scoping, broad `Bash(*)` allow, AGENTS.md drift
- **LOW** — stylistic issues, missing nice-to-haves (CLAUDE.local.md, sandbox config)

End with a **Top fixes** list ordered by impact.

### Step 4: Propose Refactor Plan

Present the proposed file layout before writing anything:

```
CLAUDE.md                       (X lines today -> Y lines after)
AGENTS.md                       (if other agents are in use)
.claude/rules/
├── <domain-1>.md   paths: <glob>
├── <domain-2>.md   paths: <glob>
└── ...
.claude/settings.json           (deny rules + scoped allow)
.gitignore                      (add .claude/*.local.*, CLAUDE.local.md)
```

Confirm with the user before applying. Path scopes must match real directories surfaced in Step 1.

### Step 5: Apply Changes

For each file:

1. **Rewrite CLAUDE.md** using [references/claude-md-template.md](references/claude-md-template.md). Keep only project-wide directives. Move domain-specific content to rules files. Target under 30 lines.

2. **Sync AGENTS.md** using [references/agents-md-template.md](references/agents-md-template.md) when other agents are in use. Mirror the critical rules; reference domain rules by path rather than duplicating them.

3. **Create path-scoped rules** in `.claude/rules/<domain>.md` using patterns from [references/path-scoping-patterns.md](references/path-scoping-patterns.md). Each rule file has `paths:` frontmatter listing globs and contains only directives that apply inside those paths.

4. **Harden `.claude/settings.json`** using [references/settings-recipes.md](references/settings-recipes.md). Add `deny` for destructive ops and secret files. Tighten allow patterns. Scope MCP tools.

5. **Update `.gitignore`** to include `.claude/*.local.*` and `CLAUDE.local.md` if missing.

Preserve concrete content the user relies on — package manager command, lint command, framework gates. Surface anything you plan to delete before deleting it.

### Step 6: Verify

Validate the rewrite, then fix anything that fails and re-verify:

1. **Line budget** — `wc -l CLAUDE.md` should be under 30. If not, return to Step 5 and move more content into rules.
2. **Path scope sanity** — for each new rules file, confirm at least one file in the repo matches its `paths:` glob (`git ls-files | grep -E <pattern>`). If zero matches, the glob is wrong.
3. **Deny rules in place** — `grep -c '"deny"' .claude/settings.json` should return ≥ 1. The deny list must include destructive ops and secret reads.
4. **`.gitignore` covers locals** — `grep -E '\.claude/\*\.local|CLAUDE\.local\.md' .gitignore` should return matches.
5. **Memory check** — ask the user to run `/memory` and confirm CLAUDE.md plus only the path-scoped rules relevant to the current cwd are listed as loaded.

If any check fails, fix it and re-run from check 1. Do not declare the refactor complete with a failing check.

## Constraints

- Do not delete existing rules the user has not approved removing — move to rules files instead
- Do not invent project conventions; only restructure what is already documented
- Preserve concrete commands (lint, package manager, framework codegen) from the original CLAUDE.md
- When a rule is borderline domain-specific, prefer the rules layer — promotion to CLAUDE.md should be earned, not assumed
- If the project has no `.claude/` directory yet, create it; do not assume team policies the user has not stated
- Never weaken a deny rule without explicit user approval
