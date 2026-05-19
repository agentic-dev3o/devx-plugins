# CLAUDE.md Template

Use this as the skeleton when rewriting CLAUDE.md. Target under 30 lines.

## Skeleton

```markdown
## Project Shape
- <one line per top-level package or app, with what it is and the framework>
- <how packages reference each other — e.g. `@org/backend` for backend imports>
- <where to run framework CLIs from (shadcn from apps/web, etc.)>

## Critical Rules
1. <package manager and how to install (e.g. "Use `bun`, never `npm` or `yarn`")>
2. <project-wide language conventions (e.g. "No semicolons in TypeScript")>
3. <lint command + when to run it ("Run `bun run lint` before completing work")>
4. <framework codegen gate ("Run `bunx convex dev --once` after any packages/backend/src/convex/** change")>
5. <git conventions ("Use `git mv` for file moves to preserve history")>
6. <UI / icon library if a strong preference exists>
7. <verification loop for UI changes — Playwright MCP, screenshot, etc.>
8. <official docs the agent must consult ("Always refer to official docs for X, never assume")>
```

Numbered rules read more weight in the model's reasoning than bulleted prose.

## What Goes Here vs. Rules

| Belongs in CLAUDE.md | Move to `.claude/rules/<domain>.md` |
|----------------------|-------------------------------------|
| Package manager command | Backend module naming patterns |
| Lint command + when to run | Frontend component conventions |
| Universal type rules | Security model per layer |
| Architectural top-level layout | Database migration patterns |
| Critical workflow gates (codegen, schema) | Test layout per domain |
| Hard safety rules | API endpoint conventions |

## Voice

- Imperative: "Use X", "Run Y", "Never Z"
- No prose explaining *why* unless it prevents a known footgun
- Numbered list for rules — easier for the model to reference
- File paths and exact commands beat descriptions

## Length Discipline

If a rule will not fit while staying under 30 lines, it almost certainly belongs in a rules file. The rare exception is a hard safety rule (e.g. "Never modify migrations on `main`") which earns its place regardless of budget.

## The Promotion Pattern

Rules do not start in CLAUDE.md — they earn their way there:

1. A footgun bites you during a session
2. You add it to the relevant `.claude/rules/` file
3. It keeps recurring across different contexts
4. After three repeats, promote it to CLAUDE.md Critical Rules

When in doubt, leave it in the rules layer. CLAUDE.md should only hold battle-tested, project-wide directives.
