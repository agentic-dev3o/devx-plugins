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
- [ ] Preflight passed (clean tree, not detached, branch ≠ origin, push.default safe)
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
6. **Push only the current branch — never a bare push.** A bare `git push` obeys `push.default`; under `matching` it force-updates *every* local branch whose name matches a remote one (e.g. a stale local `main`), and `--force-with-lease` will *not* stop it if you fetched recently (the lease only blocks unfetched concurrent changes). Always push with an explicit refspec — `origin HEAD` resolves to "current branch → its same-named remote branch" and is immune to `push.default`. As preflight hardening, run `git config push.default`; if it is `matching` or empty, warn the user and offer `git config push.default current` for this repo.

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
2. Update the remote (offer only; run it solely on user confirmation). **Always scope the push to the current branch with an explicit refspec — never a bare `git push` (see Guardrail 6):**
   - **Rebase path** (history rewritten) → `git push --force-with-lease origin HEAD`. For belt-and-suspenders, pin the lease: `git push --force-with-lease=<branch>:<sha> origin HEAD:<branch>`.
   - **Merge-fallback path** (Phase 2 abort) → history was not rewritten, so `git push origin HEAD` fast-forwards; force is unnecessary.
3. **Success** → delete the backup: `git branch -D <backup>`.
4. **Anything wrong** → keep `<backup>` and give recovery steps:
   ```bash
   git rebase --abort 2>/dev/null; git merge --abort 2>/dev/null
   git reset --hard <backup>
   ```
5. Summarize: rebase vs. merge path, conflicts resolved, push status, and whether the backup was deleted or kept.
