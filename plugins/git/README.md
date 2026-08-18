# devx-git

Git workflow automation for developers who commit often and want clean history.

## Installation

```
/plugin install devx-git@devx-plugins
```

## Commands

### `/devx-git:ci`

Autonomous conventional commits. Picks out this session's work, skips junk and secrets, and commits — no manual staging, no thinking about commit message format.

```
/devx-git:ci
```

**What happens:**
1. Surveys the working tree and sorts changes: this session's work vs. junk, secrets, and unrelated edits
2. Stages only the session's work with explicit paths (never `git add -A`)
3. Determines type (`feat`, `fix`, `refactor`, etc.), scope, and subject
4. Commits immediately, then reports anything it left out (and why)

**Output:**
```
feat(auth): add JWT token refresh endpoint
fix(api): resolve race condition in websocket handler
chore: update dependencies to latest versions
```

---

### `/devx-git:pr [base-branch]`

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

### `/devx-git:update-origin [origin-branch]`

Update the current branch from an origin branch via standard merge — never rebase, never force-push — with safe conflict resolution and automatic backup/recovery. Defaults to `main`. Merges keep published history intact, so the update stays safe when several developers or agents work on the same branch.

```
/devx-git:update-origin
/devx-git:update-origin develop
```

**What happens:**
1. Requires a clean working tree (stops otherwise)
2. Creates a backup branch of your current branch
3. Merges `origin/<your-branch>` first if teammates or agents pushed new commits, then merges the target origin branch
4. Resolves conflicts by reconciling both sides — asks only on genuinely risky contradictions
5. Offers a plain `git push origin HEAD` — only if you confirm; a rejected push is resolved with another merge
6. Deletes the backup automatically when safe; keeps it (with restore instructions) if anything went wrong

---

## GPG Signed Commits (macOS Sandbox)

If you use GPG commit signing with Claude Code's sandbox mode, GPG needs access to its Unix socket. Add this to your `~/.claude/settings.json`:

```json
{
  "sandbox": {
    "network": {
      "allowUnixSockets": [
        "~/.gnupg/S.gpg-agent"
      ]
    }
  }
}
```

This allows GPG to communicate with its agent while keeping git sandboxed. Only tested on macOS.
