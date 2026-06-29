---
name: ci
description: Stages the changes produced in this session, excludes junk and secrets, and generates a conventional commit. Triggered when the user runs /devx-git:ci or asks to commit.
model: sonnet
allowed-tools: Bash(git:*)
---

# Conventional Commit

Be autonomous. Commit the work this session produced **without asking for confirmation**.
Do not halt on junk or unrelated files — exclude them, commit the rest, and report.

## Workflow

1. Survey the working tree:
   ```bash
   git status --short
   git branch --show-current
   ```

2. Decide what belongs in this commit (see Selecting Files below). Sort every dirty path
   into one of four buckets:
   - **Commit** — changes produced by the work done in this session (files you edited or
     created, plus their direct byproducts like lockfiles, generated output, or migrations).
   - **Exclude (secret)** — `.env`, keys, credentials. Never commit these; call them out
     explicitly (see Junk & Secret Detection).
   - **Exclude (junk)** — build artifacts, caches, dependencies, OS/editor cruft (see
     Junk & Secret Detection).
   - **Exclude (unrelated)** — pre-existing dirty files unrelated to this session's work.

3. Stage **only** the Commit bucket, with explicit pathspecs — never `git add -A` or `git add .`:
   ```bash
   git add -- <path1> <path2> ...
   git diff --cached --stat
   git diff --cached
   ```

4. Analyze the staged diff — determine type, scope, subject.

5. Commit immediately (no confirmation needed). Add a second `-m` for a body when the
   change is non-trivial:
   ```bash
   git commit -m "<type>(<scope>): <subject>"
   ```

6. Report:
   - the commit hash and message,
   - a short list of anything **excluded** and why — call out junk that should be added
     to `.gitignore` and any secrets that were left uncommitted, as **information** for the
     user. Do not block on these.

## Selecting Files

Prefer precision over completeness. The goal is a commit that matches the work you actually
did this session.

- **You have session context** (you edited files in this conversation): stage exactly those
  files and their direct byproducts. Leave everything else for the user.
- **No session context** (e.g. `/devx-git:ci` run cold at the start of a session): treat all dirty
  tracked + untracked paths as the Commit bucket, minus anything caught by Junk & Secret
  Detection.
- **Ambiguous** (a dirty file might or might not relate to the work): if it plausibly belongs
  to the change, include it; if it clearly doesn't, exclude it and mention it in the report.
- **Distinct concerns** in one working tree: it's fine to stage only the cohesive subset that
  forms one logical commit and tell the user what you left for a follow-up commit.

## Junk & Secret Detection

Never stage these, even if they appear to be part of the work. Exclude them and note them in
the report.

**Secrets** (call out explicitly — these are the important ones):
`.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `*credentials*`, `*.p12`, `*.keystore`

**Junk / build / cache** (suggest adding to `.gitignore`):

| Category | Paths |
|----------|-------|
| JS/TS | `node_modules/`, `.npm/`, `.yarn/`, `.pnp.*`, `dist/`, `build/` |
| Python | `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.venv/`, `venv/`, `.eggs/`, `*.egg-info/` |
| Java/Kotlin | `target/`, `.gradle/`, `build/` |
| Go | `vendor/` (when go.sum exists) |
| Rust | `target/` |
| IDE/Editor | `.idea/`, `.vscode/`, `*.swp`, `*.swo`, `.DS_Store`, `Thumbs.db` |
| General | `*.log`, `tmp/`, `.cache/` |

This is not exhaustive. Apply judgment for any untracked directory that looks like build
output, cache, or dependency vendoring.

## Commit Message

Format: `<type>(<scope>): <subject>` — standard [Conventional Commits](https://conventionalcommits.org). Add a body for complex changes.

Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `style`, `chore`, `build`.

## Examples

### Selecting what to commit

This session you implemented a rate limiter. `git status --short` shows a mix of your work,
a secret, a dependency directory, and an unrelated pre-existing edit:

```
 M src/middleware/rateLimit.ts       # you wrote this
 M src/server.ts                     # you wired it up here
?? src/middleware/rateLimit.test.ts  # you added this test
?? .env.local                        # secret, untouched by you
?? node_modules/                     # dependency directory
 M README.md                         # pre-existing edit, unrelated to this work
```

Sort the paths, then stage **only** the Commit bucket with explicit pathspecs:

```bash
git add -- src/middleware/rateLimit.ts src/server.ts src/middleware/rateLimit.test.ts
git commit -m "feat(middleware): add sliding-window rate limiter"
```

Then report what was left out:

> Committed `a1b2c3d` — feat(middleware): add sliding-window rate limiter
> Left out:
> - `.env.local` — looks like a secret; not committed. Add it to `.gitignore`.
> - `node_modules/` — dependency directory; add it to `.gitignore`.
> - `README.md` — modified but unrelated to this change; left for you.

### Commit messages

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
