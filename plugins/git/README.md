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
6. Offers a push — `--force-with-lease` on the rebase path, a plain fast-forward after the merge fallback — only if you confirm
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
