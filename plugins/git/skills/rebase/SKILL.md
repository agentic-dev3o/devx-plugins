---
name: rebase
description: Updates the current branch onto an origin branch via rebase, with a recoverable backup, safe conflict resolution, and recovery steps. Use when the user runs /rebase or asks to rebase/update their branch onto main (or another origin branch).
disable-model-invocation: true
allowed-tools: Bash(git:*), Read, Edit, Grep, Glob
argument-hint: "[origin-branch]"
---

# Update Branch With Origin

Rebase the current branch onto `<origin-branch>` (= `$ARGUMENTS`, default `main`), always behind a recoverable backup.

Copy this checklist into your reply and check items off as you go:

```
Rebase Progress:
- [ ] Preflight passed (clean tree, not detached, branch ≠ origin)
- [ ] Backup branch created
- [ ] Rebase attempted
- [ ] Conflicts triaged + resolved (or merged as fallback)
- [ ] Result verified clean
- [ ] Force-with-lease push (only if user confirmed)
- [ ] Backup deleted (success) or kept (recovery)
```

## Guardrails (exact — do not vary)

1. **The working tree MUST be clean.** Run `git status --porcelain`; any output → stop and tell the user to commit or stash first. Do nothing else.
2. Stop if HEAD is detached or the current branch equals `<origin-branch>`.
3. **Back up before touching anything:** `git branch backup/$(git branch --show-current)-$(git rev-parse --short HEAD)`. Tell the user the exact name; call it `<backup>` below.
4. Never delete `<backup>` unless the final tree is verified clean and the update succeeded.
5. Never force-push without explicit user confirmation.

## Phase 1 — Rebase

`git fetch origin`, then `git pull --rebase origin <origin-branch>`.
- No conflict → Phase 4.
- Conflict → Phase 2.

## Phase 2 — Triage: resolve or abort

Inspect commits left to replay and the conflict shape (`git status`). State the decision and why before proceeding.
- **≤5 commits, mechanical conflicts** → resolve in place (Phase 3).
- **>5 commits, the same files re-conflicting across commits, or sprawling/risky** → `git rebase --abort`, then `git merge origin/<origin-branch>` and resolve the whole set at once (Phase 3 rules, single commit).

## Phase 3 — Resolve

Per conflict, **default to keeping both sides** — reconcile the origin and local changes so neither intent is lost. Then `git add` the resolved files and `git rebase --continue`; repeat until done.

**Reconcile silently** (do NOT ask) for ordinary, combinable conflicts:
- Both sides added different imports, functions, or non-overlapping list entries → keep both.
- Both edited nearby lines with compatible intent → merge the edits.

**Ask the user** only when the sides genuinely contradict and "keep both" is wrong:
- The same key/value set to two incompatible things.
- One side deletes a file the other side substantively edits.
- Conflicting schema, migration, or lockfile ordering.

Present the specific conflict and concrete options. If resolution becomes unworkable, `git rebase --abort` and take the merge fallback in Phase 2.

## Phase 4 — Finish

1. **Verify the result:** `git status` clean, `git log --oneline -5` correct. If it is not clean, do not proceed — go to recovery (step 4).
2. The branch now diverges from its remote. **Offer** `git push --force-with-lease`; run it only if the user confirms.
3. **Success** → delete the backup: `git branch -D <backup>`.
4. **Anything wrong** → keep `<backup>` and give recovery steps:
   ```bash
   git rebase --abort 2>/dev/null; git merge --abort 2>/dev/null
   git reset --hard <backup>
   ```
5. Summarize: rebase vs. merge path, conflicts resolved, push status, and whether the backup was deleted or kept.
