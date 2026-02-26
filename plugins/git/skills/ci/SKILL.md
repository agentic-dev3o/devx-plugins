---
name: ci
description: Stages all changes, guards against unignored junk files, and generates a conventional commit. Triggered when the user runs /commit or asks to commit.
---

# Conventional Commit

## Workflow

1. Check for unignored junk files **before staging anything**:
   ```bash
   git status --short
   ```
   Scan untracked files for paths that should never be committed (see Gitignore Guard below).
   If any are found, create or update `.gitignore` to cover them, then continue.

2. Stage all changes and gather context:
   ```bash
   git add -A
   git diff --cached --stat
   git diff --cached
   git branch --show-current
   ```

3. Analyze diff — determine type, scope, subject

4. Commit immediately (no confirmation needed):
   ```bash
   git commit -m "<type>(<scope>): <subject>"
   ```

5. Show the commit hash and message summary

## Gitignore Guard

Before staging, scan `git status` output for untracked paths matching common junk patterns.
If any match, add a rule to `.gitignore` (create the file if missing) before proceeding.

**Patterns to catch:**

| Category | Paths |
|----------|-------|
| JS/TS | `node_modules/`, `.npm/`, `.yarn/`, `.pnp.*`, `dist/`, `build/` |
| Python | `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.venv/`, `venv/`, `.eggs/`, `*.egg-info/` |
| Java/Kotlin | `target/`, `.gradle/`, `build/` |
| Go | `vendor/` (when go.sum exists) |
| Rust | `target/` |
| IDE/Editor | `.idea/`, `.vscode/`, `*.swp`, `*.swo`, `.DS_Store`, `Thumbs.db` |
| Env/Secrets | `.env`, `.env.*`, `*.pem`, `*.key` |
| General | `*.log`, `tmp/`, `.cache/` |

This is not exhaustive. Apply judgment for any untracked directory that looks like build output, cache, or dependency vendoring.

## Commit Message

Format: `<type>(<scope>): <subject>` — standard [Conventional Commits](https://conventionalcommits.org). Add a body for complex changes.

Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `style`, `chore`, `build`.

## Examples

**Input** (diff stat):
```
src/auth/jwt.ts | 45 +++
src/auth/middleware.ts | 12 ++
```
**Output**:
```
feat(auth): add JWT token refresh endpoint
```

**Input** (diff stat):
```
src/api/websocket.ts | 8 ++--
```
**Output**:
```
fix(api): resolve race condition in websocket handler

- Add mutex lock for connection state
- Implement proper cleanup on disconnect
```

**Input** (diff stat):
```
package.json | 6 +++---
yarn.lock    | 120 ++++----
```
**Output**:
```
chore: update dependencies to latest versions
```
