---
name: update-origin
description: Updates the current branch from an origin branch via standard merge, with a recoverable backup and safe conflict resolution. Use when the user runs /update-origin or asks to update, sync, or merge their branch with main (or another origin branch).
allowed-tools: Bash(git:*), Read, Edit, Grep, Glob
argument-hint: "[origin-branch]"
---

# Update Branch From Origin

Merge `origin/<origin-branch>` (= `$ARGUMENTS`, default `main`) into the current branch, always behind a recoverable backup.

Copy this checklist into your reply and check items off as you go:

```
Update Progress:
- [ ] Preflight passed (clean tree, not detached, branch ≠ target, push.default safe)
- [ ] Backup branch created
- [ ] Synced with origin/<current-branch> (if it has new commits)
- [ ] Merged origin/<target>
- [ ] Conflicts resolved
- [ ] Result verified clean
- [ ] Pushed (only if user confirmed)
- [ ] Backup deleted (success) or kept (recovery)
```

## Guardrails (exact — do not vary)

1. **The working tree MUST be clean.** Run `git status --porcelain`; any output → stop and tell the user to commit or stash first. Do nothing else.
2. Stop if HEAD is detached or the current branch equals `<origin-branch>`.
3. **Back up before touching anything:** `git branch backup/$(git branch --show-current)-$(git rev-parse --short HEAD)`. Tell the user the exact name; call it `<backup>` below.
4. Never delete `<backup>` unless the final tree is verified clean and the update succeeded.
5. **Never rebase, never force-push** (`--force`, `--force-with-lease`, `+refspec` — all forbidden). Several developers and agents work on the same branch; rewriting published history clobbers their work. A rejected push means new remote commits to merge in, never to overwrite.
6. **Push only the current branch — never a bare push.** A bare `git push` obeys `push.default`, and under `matching` it pushes *every* same-named local branch. Always `git push origin HEAD`. Preflight hardening: run `git config push.default`; if `matching` or empty, warn the user and offer `git config push.default current` for this repo.

## Phase 1 — Sync and merge

1. `git fetch origin`.
2. If `origin/<current-branch>` exists and has commits not on HEAD (`git rev-list --count HEAD..origin/<current-branch>` > 0), others pushed while you worked → `git merge origin/<current-branch>` first.
3. `git merge origin/<origin-branch>`.

Any conflict → Phase 2. Both merges clean → Phase 3.

## Phase 2 — Resolve

Per conflict, **default to keeping both sides** — reconcile the origin and local changes so neither intent is lost. Then `git add` the resolved files and `git commit --no-edit`; repeat if the next merge also conflicts.

**Reconcile silently** (do NOT ask) for ordinary, combinable conflicts:
- Both sides added different imports, functions, or non-overlapping list entries → keep both.
- Both edited nearby lines with compatible intent → merge the edits.

**Ask the user** only when the sides genuinely contradict and "keep both" is wrong:
- The same key/value set to two incompatible things.
- One side deletes a file the other side substantively edits.
- Conflicting schema, migration, or lockfile ordering.

Present the specific conflict and concrete options. If resolution becomes unworkable, `git merge --abort` leaves the branch untouched — report and stop.

## Phase 3 — Finish

1. **Verify the result:** `git status` clean, `git log --oneline -5` shows the merge. If it is not clean, do not proceed — go to recovery (step 4).
2. Offer the push (run it solely on user confirmation): `git push origin HEAD`. If rejected because the remote moved again → `git fetch origin`, `git merge origin/<current-branch>`, resolve per Phase 2, push again.
3. **Success** → delete the backup: `git branch -D <backup>`.
4. **Anything wrong before pushing** → keep `<backup>` and give recovery steps:
   ```bash
   git merge --abort 2>/dev/null
   git reset --hard <backup>
   ```
   **Already pushed** → the merge is published; do not reset — fix forward with a new commit or `git revert`.
5. Summarize: merges performed, conflicts resolved, push status, and whether the backup was deleted or kept.
