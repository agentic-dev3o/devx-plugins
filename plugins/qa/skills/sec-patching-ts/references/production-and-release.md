# Production, pull request, merge and release

Steps 2 and 9 to 12 of the skill. Write every value you find (SHA, environment, branch names) into the
checklist as a literal, because shell variables do not survive between Bash calls.

## Contents
- Find the production commit
- Drift and PR base
- How production ships
- Open the PR (Step 9)
- Babysit (Step 10)
- Merge (`--automerge`, Step 11)
- Release (`--release`, Step 12)

## Find the production commit

Collect these signals in order, and stop at the first strong one:

1. **`--prod-ref`**: `git rev-parse --verify '<ref>^{commit}'` (run `git fetch origin <ref>` first if it is
   unknown). Strong.
2. **The deploy workflow's last successful deploy.** Find the workflow in `.github/workflows/` whose job deploys
   to production. Such a job has an `environment:` named production, prod or live, or runs a deploy command
   (`vercel deploy --prod`, `flyctl deploy`, `wrangler deploy`, `kubectl`, `helm`, `aws`/`gcloud`/`az` deploys,
   `railway up`). Then:

   ```bash
   gh run list --workflow <file> --status success --limit 5 --json databaseId,headSha,event,createdAt
   gh run view <id> --json jobs --jq '.jobs[]|{name,conclusion}'
   ```

   Take the newest run whose deploy job concluded `success`, because a successful run can have skipped its
   deploy job. Strong.
3. **GitHub Deployments**, which platform integrations (Vercel, Render, Railway) create. List the environments
   with `gh api -X GET 'repos/<owner>/<repo>/environments' --jq '.environments[].name'`, then:

   ```bash
   gh api graphql -f owner=<owner> -f name=<repo> -f env='<environment>' -f query='query($owner:String!,$name:String!,$env:String!){repository(owner:$owner,name:$name){deployments(environments:[$env],first:30,orderBy:{field:CREATED_AT,direction:DESC}){nodes{commitOid createdAt creator{login} latestStatus{state logUrl}}}}}' --jq '[.data.repository.deployments.nodes[]|select(.latestStatus.state=="SUCCESS")][0]'
   ```

   Use `commitOid`. It is strong when the deploy workflow or a platform bot created the deployment, and weak
   otherwise.
4. **The latest release tag**: `gh release list --exclude-drafts --exclude-pre-releases --limit 5`, resolved with
   `gh api -X GET repos/<owner>/<repo>/commits/refs/tags/<tag> --jq .sha`. Weak: a tag proves a release, not a
   deployment.
5. **Nothing found:** ask the user. Never assume the default branch's tip.

When two signals disagree, the evidence is contradictory: ask the user. A hotfix built on the wrong base
ships a rollback of everything after it. Unattended, continue on weak or contradictory evidence with autonomy
revoked, and stop when nothing was found.

## Drift and PR base

Run each command alone:

```bash
git merge-base --is-ancestor <prod-sha> origin/<default>
git rev-list --count <prod-sha>..origin/<default>
git log --oneline <prod-sha>..origin/<default>
```

The count is the drift, and the log lists the unreleased commits.

Choose the PR base:

1. **`--base <branch>`:** it must contain the production commit. If its tip is ahead of production, merging ships
   those commits too: say so, and with `--release` stop unless the user confirms.
2. **Drift 0:** the default branch.
3. **Drift above 0:** an existing remote branch whose tip is the production commit
   (`git branch -r --points-at <prod-sha>`), such as `release/*`, `hotfix/*` or `production`.
4. **Otherwise:** a new release line, `release/<tag>` when `git tag --points-at <prod-sha>` prints a tag, or
   `release/<short-sha>`. The name must be free (`git ls-remote --heads origin <name>` prints nothing).
   Before creating it in Step 9, read its rules:
   `gh api -X GET repos/<owner>/<repo>/rules/branches/<name> --jq '[.[].type]'`. If `creation` is listed, you
   may not create the branch: ask a maintainer. Then create it with
   `git push origin <prod-sha>:refs/heads/<name>`.

Release tooling (semantic-release, release-please, changesets) usually does not run on such a branch. In that
case, Step 12 ships by tag or dispatch, or hands over.

## How production ships

Read the `on:` block of the deploy workflow as text:

| Trigger | Mechanism | Merging into the base deploys |
|---|---|---|
| `push: tags` | **tag** | no |
| `release: [published]` | **release** | no |
| `workflow_dispatch` | **dispatch**: read its inputs | no |
| `push: branches` matching the base | **branch push** | yes |
| Release tooling whose workflow runs on push to the base | **tooling**: the tool tags or releases, which triggers the deploy | yes |
| No deploy workflow, but a platform config (`vercel.json`, `netlify.toml`, `render.yaml`, `fly.toml`, `wrangler.toml`) or deployments from a platform bot | **platform git** | yes when the base is the platform's production branch |

Record `unknown` when you cannot tell. That revokes autonomy.

## Open the PR (Step 9)

1. Check that a workflow runs on `pull_request` for the base: read `branches` and `branches-ignore` as text. If
   none does, say so in the PR body and revoke autonomy.
2. If Step 2 chose a new release line, create it as "Drift and PR base" shows.
3. Run `git push -u origin HEAD`.
4. Open the PR with `gh pr create --base <base> --head <work-branch>`, with the title and body from
   `pr-template.md`, the body passed through a quoted heredoc. Add the `security` and `dependencies` labels only
   when `gh label list` shows they exist.
5. Dismiss the Dependabot alerts of each acceptance the user approved, as "Accept the risk" in `verify.md` shows,
   with the PR link in the comment. Unattended, list them in the PR instead.

## Babysit (Step 10)

Follow the babysit-pr skill, which SKILL.md Step 10 points to, with these changes:

- Pushes to the work branch are already authorized. Commit fixes yourself, as in Step 8, not with `devx-git:ci`.
- Fetch job logs with `gh api -X GET repos/<owner>/<repo>/actions/jobs/<id>/logs --allow-escape-sequences`.
- Never take its `BEHIND`/`DIRTY` path (`devx-git:update-origin`): merging new base commits would bring
  unverified versions. Stop, revoke autonomy ("base moved"), and report.
- A failure caused by a bumped package is a Step 7 regression: defer the package as Step 7 does, and never patch
  around it. A test that fails in CI but passed on the production commit's CI run
  (`gh run list --commit <prod-sha> --workflow <file>`) is a regression, not infrastructure.
- If "no checks reported" persists ten minutes after the push, CI does not run on this base: stop.
- A security-scan check that fails only on advisories this run left open is expected: accepted earlier, proposed
  for acceptance, escalated, deferred, or below `--severity`. Never add an ignore entry or bump a package to turn
  it green: report it as waiting for those decisions.
- Babysitting is green when every check passes and `mergeStateStatus` is `CLEAN`, `HAS_HOOKS`, or `BLOCKED` with
  `reviewDecision` `REVIEW_REQUIRED`. Do not stop there with `--automerge`: go on to Merge.

## Merge (`--automerge`, Step 11)

If merging into the base deploys, and `--release` is absent or the patch is development-only, do not merge:
report "ready; merging deploys to production". When a condition below fails, report the PR as ready for a human,
and name the blocker.

1. Read the PR's readiness:

   ```bash
   gh api graphql -F owner=<owner> -F name=<repo> -F number=<pr> -f query='query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){state isDraft headRefOid mergeable mergeStateStatus reviewDecision isMergeQueueEnabled viewerCanMergeAsAdmin commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100){nodes{__typename ... on CheckRun{name conclusion isRequired(pullRequestNumber:$number)} ... on StatusContext{context state isRequired(pullRequestNumber:$number)}}}}}}}}}}'
   ```

2. Merge only when all of these hold:
   - Autonomy is on, and babysitting ended green.
   - `headRefOid` is the SHA you verified.
   - The base has not moved: after `git fetch origin <base>`, `git merge-base --is-ancestor origin/<base> <headRefOid>`
     exits 0. Otherwise revoke autonomy ("base moved") and do not merge.
   - When merging deploys, production has not moved since Step 2: re-run "Find the production commit".
   - Every required context is `SUCCESS`, `SKIPPED` or `NEUTRAL`. A required check that never reported is
     absent from the rollup, so compare with
     `gh api -X GET repos/<owner>/<repo>/rules/branches/<base> --jq '.[]|select(.type=="required_status_checks")'`.
   - `reviewDecision` is not `CHANGES_REQUESTED`: a human objected, and `--admin` never overrides that.
   - `mergeable` is `MERGEABLE`, `isDraft` is false, and `isMergeQueueEnabled` is false.
   - `mergeStateStatus` is `CLEAN` or `HAS_HOOKS`: merge without `--admin`. Or it is `BLOCKED` with every
     required check green and `reviewDecision` `REVIEW_REQUIRED`: the review is the only blocker. That case needs
     `--admin`, and `viewerCanMergeAsAdmin` must be true. Any other state means: do not merge.
3. Pick the first method the repository allows, in the order squash, merge, rebase
   (`gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed`). Then run:

   ```bash
   gh pr merge <pr> -R <owner>/<repo> --squash [--admin] --match-head-commit <headRefOid> --subject "<PR title> (#<pr>)"
   ```

   Never `--auto`, never `--delete-branch`. If the head moved, babysit again first.
4. Confirm with `gh pr view <pr> -R <owner>/<repo> --json state,mergeCommit`, and record the merge SHA.

## Release (`--release`, Step 12)

A development-only patch is never released.

1. **Re-detect production.** If it moved since Step 2, someone deployed meanwhile: stop. When merging deploys,
   the Merge section already did this.
2. **Check that the merge carries only the hotfix.** Run `git fetch origin <base>`, then
   `git rev-list --count <prod-sha>..<merge-sha>`. The count must be 1 for a squash merge, or the PR's commit
   count plus the merge commit otherwise. A higher count would ship unreleased commits: stop and hand over.
3. **Next version.** Bump the patch number of the tag on the production commit, in its scheme (`vX.Y.Z`,
   `X.Y.Z`, `<pkg>@X.Y.Z`). `git ls-remote --tags origin refs/tags/<next>` must print nothing.
4. **Ship:**

   | Mechanism | Action |
   |---|---|
   | tag | `git tag -a <next> <merge-sha> -m "<next>: security patch"`, then `git push origin refs/tags/<next>`: exactly one tag |
   | release | Write the notes to a file, then `gh release create <next> --target <merge-sha> --notes-file <file> --latest=<true only when no higher release exists>` |
   | dispatch | `gh workflow run <file> --ref <base or tag> -f <input>=<value>` |
   | branch push, platform git | Merging was the release: find the run with `gh run list --workflow <file> --commit <merge-sha>` |
   | tooling | Never tag or release yourself. Watch the tool's run. release-please opens a release PR: merge it under the Merge rules once its diff changes only versions and changelogs; its head is then the SHA you verified |
   | only path deploys the drifted default branch | Stop: shipping would carry unreleased commits. Report the manual path |

5. **Watch.** Run `gh run watch <run-id> --exit-status --interval 30 --compact` with `run_in_background: true`,
   and wait for the completion notice. A run waiting for an environment reviewer: report who
   (`gh api -X GET repos/<owner>/<repo>/environments/<env> --jq '.protection_rules'`) and stop. Never approve it
   yourself.
6. **Verify.** Re-run the production detection: a successful deployment of `<merge-sha>` is the proof. When the
   repository exposes a version or health URL, check it too. With only the run's success, report "deployed, not
   independently verified".

At any stop above, or when a ruleset forbids the tag or credentials are missing, hand over without working
around the block. When a deploy fails, report the failed run and the rollback path the repository uses. Never
roll back yourself.
