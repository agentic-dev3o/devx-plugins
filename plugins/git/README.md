# devx-git

Git workflow automation for developers who commit often and want clean history.

## Installation

```
/plugin install devx-git@devx-plugins
```

## Commands

### `/devx-git:ci`

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

### `/devx-git:rebase [origin-branch]`

Update the current branch with an origin branch via rebase, with safe conflict resolution and automatic backup/recovery. Defaults to `main`.

```
/devx-git:rebase
/devx-git:rebase develop
```

**What happens:**
1. Requires a clean working tree (stops otherwise)
2. Creates a backup branch of your current branch
3. Rebases onto the origin branch (`git pull --rebase`)
4. On conflict, triages whether to resolve in place or abort to a single merge based on how many commits remain
5. Resolves conflicts by reconciling both sides — asks only on genuinely risky contradictions
6. Offers a `--force-with-lease` push (rebase rewrites history) — only runs it if you confirm
7. Deletes the backup automatically when safe; keeps it (with restore instructions) if anything went wrong

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
