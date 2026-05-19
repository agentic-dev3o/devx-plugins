# Harness Audit Checklist

Use this checklist during Step 2 of the workflow. Gather evidence from the files inventoried in Step 1 and score each dimension.

## 1. CLAUDE.md size and shape

| Check | Target | Failure signal |
|-------|--------|----------------|
| Line count | < 30 lines | > 100 lines = HIGH; 30–100 = MEDIUM |
| Tone | Imperative directives ("Use X", "Run Y", "Never Z") | Descriptive prose ("We use X because…") = MEDIUM |
| Scope | Project-wide rules only | Domain-specific sections (frontend-only, backend-only) = MEDIUM |
| Buried critical rules | Top of file | "Critical Rules" section near the bottom = MEDIUM |
| Architecture dumps | Not present | Full dependency lists, full directory trees = HIGH |
| Stale content | None | References to tools or files no longer in the repo = MEDIUM |
| Concrete commands | Present (lint, test, package manager) | Vague ("run the build") = LOW |

CLAUDE.md loads as a user message and competes with conversation context for attention. Brevity is what makes the model reference it in reasoning.

## 2. AGENTS.md alignment

Apply only when the project supports Codex, Cursor, or other non-Claude agents.

| Check | Target | Failure signal |
|-------|--------|----------------|
| Drift from CLAUDE.md | Critical rules identical | Rules disagree between files = HIGH |
| Domain rules duplicated | Referenced by path, not inlined | Duplicates full rule text from `.claude/rules/` = MEDIUM |
| Tool-specific notes | Clearly marked | Mixed with universal rules = LOW |
| Existence when other agents are used | Present | Missing while teammates use Codex/Cursor = MEDIUM |
| Existence when only Claude is used | Absent (or minimal) | Unused AGENTS.md adds maintenance cost = LOW |

## 3. Rules segmentation

| Check | Target | Failure signal |
|-------|--------|----------------|
| `.claude/rules/` exists | Yes when project has multiple domains | Missing in monorepo / multi-stack = HIGH |
| `paths:` frontmatter | Present on domain-specific rules | All rules load globally = MEDIUM |
| Path scope matches code layout | Yes | Generic globs that match nothing or everything = MEDIUM |
| Single domain per file | Yes | One file covers frontend + backend + security = MEDIUM |
| Overlap with CLAUDE.md | None | Rules restate CLAUDE.md content = LOW |
| File length | < 60 lines per rule | Sprawling files indicate a missed split = LOW |

The rule of thumb: if the model is editing file X, exactly one rules file (or two non-overlapping ones) should fire.

## 4. Permissions hygiene

| Check | Target | Failure signal |
|-------|--------|----------------|
| `deny` rules present | Destructive ops + secrets denied | Missing `Bash(git push *)`, `Bash(rm -rf *)`, `Read(./.env)` = HIGH |
| Secret files denied | `.env`, `.env.*`, credential paths | Readable = HIGH |
| Allow patterns scoped | `Bash(bun:*)`, `Bash(git status:*)` | `Bash(*)` = HIGH |
| MCP tools scoped | `mcp__server__specific_tool` | Broad `mcp__server__*` for risky servers = MEDIUM |
| Permission mode | `dontAsk` once allowlist is mature | `default` with mature allowlist = LOW (just efficiency) |
| Publish commands denied | Yes | `npm publish`, `cargo publish`, etc. allowed = HIGH |

`deny` always wins — even `bypassPermissions` mode respects it. That makes deny rules the hard safety layer.

## 5. Local overrides

| Check | Target | Failure signal |
|-------|--------|----------------|
| `.gitignore` includes `.claude/*.local.*` | Yes | Missing = HIGH (personal config will leak) |
| `CLAUDE.local.md` in `.gitignore` | Yes (if used) | Missing = HIGH |
| Personal vs team split | `settings.json` = team, `settings.local.json` = personal | Personal MCP servers committed = MEDIUM |
| Credentials in MCP config | Environment refs only | Hardcoded secrets = HIGH |

## 6. Memory ergonomics

| Check | Target | Failure signal |
|-------|--------|----------------|
| Monorepo subtree CLAUDE.md | Present in distinct packages | Single root CLAUDE.md tries to cover all subtrees = MEDIUM |
| `claudeMdExcludes` | Configured if monorepo has unrelated teams' rules | Missing in large monorepo = LOW |
| Auto-memory pollution | Not in repo | Auto-memory files committed = MEDIUM |
| Skills / agents location | Under `.claude/skills/` or `.claude/agents/` | Workflow content stuffed in CLAUDE.md = MEDIUM |

## Severity glossary

- **HIGH** — active risk: security gap, autonomy blocker, leaked credentials, secrets readable
- **MEDIUM** — quality issue: drift between files, wasted context, ambiguous scopes
- **LOW** — stylistic or efficiency tuning
