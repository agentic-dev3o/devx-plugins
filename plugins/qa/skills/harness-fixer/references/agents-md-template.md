# AGENTS.md Template

AGENTS.md is read by non-Claude agents (Codex, Cursor, others). Keep it aligned with CLAUDE.md — drift here means different tools enforce different rules on the same codebase.

## Skeleton

```markdown
# Agent Instructions

This file applies to non-Claude-Code agents. For Claude Code, see `CLAUDE.md` and `.claude/rules/`.

## Project Shape
<same project shape as CLAUDE.md>

## Critical Rules
<same numbered list as CLAUDE.md>

## Domain Rules

For domain-specific conventions, see:

- `apps/web/**` — frontend conventions in `.claude/rules/frontend.md`
- `packages/backend/**` — backend conventions in `.claude/rules/backend.md`
- `packages/backend/src/**`, `apps/web/src/**` — security model in `.claude/rules/security.md`

Agents that cannot load `.claude/rules/` automatically should inline the relevant rule file before working in those paths.
```

## Sync Discipline

When a rule is promoted to CLAUDE.md, update AGENTS.md in the same change. The two files form the always-on critical-rules layer for the project — drift between them creates inconsistent behavior across tools.

## When AGENTS.md Is Not Needed

If the project is Claude-only and no teammate uses another agent, skip AGENTS.md. Adding it creates a maintenance burden without a consumer.

## When AGENTS.md Diverges from CLAUDE.md

A few tool-specific notes are legitimate (different file path conventions, different invocation syntax). Mark them clearly:

```markdown
## Tool-Specific Notes

### Codex
- <note>

### Cursor
- <note>
```

Keep this section minimal. Universal rules stay in the main numbered list — duplicating them tool-by-tool is the path to drift.
