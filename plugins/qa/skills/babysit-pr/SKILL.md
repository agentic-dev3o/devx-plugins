---
name: babysit-pr
description: >-
  Monitors a GitHub pull request's checks with the gh CLI, reads the logs of failing
  GitHub Actions jobs, fixes the failures the branch caused, reruns genuine infrastructure
  flakes, and pushes until the PR is green and mergeable. Use when the user asks to babysit,
  watch, or monitor a PR, says CI or checks are failing or red, asks to analyse PR job
  errors and remediate them, or wants a PR driven to a ready-to-merge state after opening it.
---

# Babysit PR

Drive the pull request named in `$ARGUMENTS` (PR number or URL; empty means the PR of the
current branch) to **green** — every required check passing, no merge conflict — or to a
blocker only the user can clear.

Do not stop on a single red check. Do not merge the PR.

Track two budgets for the whole session and report both at the end:

- **3 reruns total** across the PR.
- **2 fix attempts per failing job.** A third failure of the same job is a stop condition,
  because the diagnosis is wrong and more pushes will not find it.

## Step 1: Preflight

```bash
gh auth status
PR=$(gh pr view $ARGUMENTS --json number -q .number)   # empty $ARGUMENTS → current branch's PR
git status --short
```

Stop and report if `gh` is missing, unauthenticated, or finds no PR for the branch.
If the tree holds uncommitted changes unrelated to the PR, stop and ask — never stash silently.

## Step 2: Watch

```bash
gh pr checks "$PR" --watch --fail-fast
```

This blocks until the checks settle, so no manual polling loop is needed. `--fail-fast` returns
as soon as one check fails, instead of waiting out the rest of the matrix.

Exit `0` = green → go to Step 6. Exit `8` = still pending → run it again. Any other exit
code = a check failed → go to Step 3.

## Step 3: Diagnose

List the failing checks. Each `link` is a job URL of the form
`.../actions/runs/<run-id>/job/<job-id>` — both ids come from it:

```bash
gh pr checks "$PR" --json name,state,link -q '.[] | select(.state=="FAILURE") | "\(.name) \(.link)"'
```

Read the log of the failing job, not of the whole run:

```bash
gh run view <run-id> --job <job-id> --log-failed
```

Always pass `--job`. Without it, `--log-failed` is scoped to the run and stays empty until
every job finishes, so a matrix with one slow job blocks diagnosis entirely. If the log comes
back empty anyway, fetch it from the API: `gh api repos/{owner}/{repo}/actions/jobs/<job-id>/logs`.

Read the actual error text before editing anything. Never infer the cause from the job name.

## Step 4: Classify

**Branch-caused — fix it:** compile, type, lint, or format errors; failing assertions in code
the diff touches; snapshot mismatches; missing migration; stale lockfile or generated file; a
new dependency that was never installed; coverage below threshold.

**Infrastructure flake — rerun it:** runner provisioning failures; network, registry, or DNS
timeouts; rate limits; cancelled or timed-out jobs; failures in tests the diff does not touch
that pass when run locally.

Ambiguous → read the log once more before spending a rerun. Never make a failure disappear by
editing CI config, skipping or deleting tests, relaxing lint rules, or pinning dependencies,
unless the diff itself is what made that config wrong.

## Step 5: Act, then return to Step 2

**Branch-caused.** Before pushing, state the job, the root cause, and the intended fix in one
line. Apply the fix, then **verify locally**: run the same command the job ran (lint,
typecheck, and unit tests are cheap enough to be worth it every time). Only once it passes,
commit with a conventional message scoped to the fix — `fix(auth): extend Request type with
userId` — and `git push` to the PR head branch. Work on that branch only: never force-push,
never rebase.

**Infrastructure flake.** `gh run rerun <run-id> --failed`. Change no code. Decrement the
rerun budget.

If both kinds of failure appear in the same run, push the fix first — the new commit
retriggers every check anyway, so a rerun on the old SHA would be wasted.

## Step 6: Confirm mergeability

```bash
gh pr view "$PR" --json mergeable,mergeStateStatus,reviewDecision
```

`CONFLICTING` → merge the base branch into the head branch, resolve the conflicts, push, and
return to Step 2. Otherwise go to Step 7.

## Step 7: Report

- PR number and final SHA
- Checks: passing / total, or which remain red
- Fixes pushed: commit → what it repaired
- Reruns used, out of 3
- What blocks the merge, if anything

## Stop conditions

Stop and hand back, with the report above, when any of these is true:

- The PR is green and mergeable, and only human approval remains.
- The rerun budget is spent, or one job has failed 3 times.
- The job needs a secret, token, or permission that is unavailable.
- The fix belongs to code this PR does not own.

Everything on GitHub other than pushing to the head branch is out of scope: no merging, no
review replies, no draft, close, or label changes.

## Example

The `build (node 20)` job fails with `TS2339: Property 'userId' does not exist on type
'Request'`, and the PR touches `src/middleware/auth.ts`. Branch-caused — the type augmentation
was never updated. Fix it, confirm with `npm run typecheck`, commit, push, return to Step 2.

In the same run, `e2e` fails with `Error: connect ETIMEDOUT registry.npmjs.org`. Infrastructure
— the push above already retriggers it, so no rerun is spent.
