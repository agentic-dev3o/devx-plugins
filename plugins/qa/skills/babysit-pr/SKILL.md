---
name: babysit-pr
description: >-
  Watches a GitHub PR's CI, diagnoses failing jobs, fixes branch-caused failures,
  reruns genuine flakes, and pushes until the PR is green and mergeable.
  Triggers on: babysit PR, watch CI, PR jobs are failing, fix failing checks,
  analyse PR job errors, make the PR ready to merge.
---

# Babysit PR

Target: `$ARGUMENTS` (PR number or URL; empty means the PR of the current branch)

Loop until the PR is green and mergeable, or until a blocker only the user can clear.
Do not stop on a single red check. Do not merge the PR.

## Loop

1. `gh pr checks $PR --watch --fail-fast --interval 20` — blocks until checks settle.
   Exit 0 = green, 8 = still pending, non-zero otherwise = failure.
2. Failure → **Diagnose**, then **Classify**.
3. Branch-caused → fix, commit, `git push`, back to 1.
4. Flake/infra → `gh run rerun <run-id> --failed`, back to 1. Budget: 3 reruns per PR, total.
5. Green → `gh pr view $PR --json mergeable,mergeStateStatus,reviewDecision`.
   `CONFLICTING` → merge the base branch, resolve, push, back to 1.
6. Report and stop.

## Diagnose

Get the failing job URLs (they carry both run id and job id):

```bash
gh pr checks $PR --json name,state,link -q '.[] | select(.state=="FAILURE") | "\(.name) \(.link)"'
```

Read the log of the failed job, not the whole run:

```bash
gh run view <run-id> --job <job-id> --log-failed
```

`gh run view --log-failed` without `--job` is run-scoped and stays empty until every job
finishes — always pass `--job` so you can diagnose while the rest of the matrix still runs.
If the zip-based fetch returns nothing: `gh api repos/{owner}/{repo}/actions/jobs/<job-id>/logs`.

Read the actual error before editing anything. When the failing step is cheap (lint, typecheck,
unit tests), run the same command locally to confirm the fix instead of pushing to find out.

## Classify

**Branch-caused — fix it:** compile/type/lint/format errors, failing assertions touching the
diff, snapshot mismatches, missing migration, stale lockfile or generated file, new dependency
not installed, coverage threshold.

**Flake/infra — rerun it:** runner provisioning, network/registry/DNS timeouts, rate limits,
cancelled or timed-out jobs, failures in tests the diff does not touch and that pass locally.

Ambiguous → diagnose once more before spending a rerun. Never make a failure disappear by
editing CI config, skipping or deleting tests, relaxing lint rules, or pinning dependencies —
unless the diff itself caused that config to be wrong.

## Rules

- Work on the PR head branch only. Never force-push, never rebase.
- Unrelated uncommitted changes in the tree → stop and ask before touching anything.
- One commit per fix, conventional format, e.g. `fix(ci): correct type error in auth handler`.
- Read-only on GitHub apart from pushing: no merge, no review replies, no draft/close/label changes.

Stop and hand back when: the 3-rerun budget is spent, the job needs a secret or permission you
lack, the fix belongs to code the PR does not own, the same failure survives two fix attempts,
or CI is green and the only thing left is human approval.

## Report

- PR number and final SHA
- Checks: passing/total, or which are still red
- Fixes pushed: commit → what it repaired
- Reruns used, out of 3
- What blocks the merge, if anything
