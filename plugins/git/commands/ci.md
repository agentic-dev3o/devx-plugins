---
allowed-tools: Bash(git:*)
description: Create conventional commit from staged changes. Use when user runs /commit or asks to commit staged changes.
model: claude-haiku-4-5
---

# Commit

Create a Conventional Commit from staged changes.

## Git Context

- Staged: !`git diff --cached --stat`
- Diff: !`git diff --cached`
- Branch: !`git branch --show-current`

## Workflow

1. **Verify staged changes exist**
   - If none: show `git status --short`, prompt user to stage files, exit

2. **Analyze diff** → determine type, scope, subject

3. **Generate message** using format:
   ```
   <type>(<scope>): <subject>
   
   [optional body for complex changes]
   ```

4. **Show preview** → confirm with user

5. **Commit** if confirmed:
   ```bash
   git commit -m "<message>"
   ```

## Type Selection

| Type | Use for |
|------|---------|
| `feat` | New functionality |
| `fix` | Bug fixes |
| `refactor` | Code restructuring (no behavior change) |
| `perf` | Performance improvements |
| `test` | Test additions/updates |
| `docs` | Documentation only |
| `style` | Formatting (no logic change) |
| `chore` | Maintenance, deps, config |
| `build` | CI/CD, Docker, build system |

## Scope

Scope is optional. When used, it should be a short noun describing the affected area (e.g., `auth`, `api`, `ui`, `db`). Infer from file paths and project structure. Omit if changes span multiple unrelated areas.

## Subject Rules

- Imperative mood: "add" not "added"
- No capital, no period
- Max 50 chars
- Be specific

## Examples

**Simple:**
```
feat(auth): add JWT token refresh endpoint
```

**With body:**
```
fix(api): resolve race condition in websocket handler

- Add mutex lock for connection state
- Implement proper cleanup on disconnect
```

**No scope (broad change):**
```
chore: update dependencies to latest versions
```

**Trivial:**
```
fix typo in README
```
