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
