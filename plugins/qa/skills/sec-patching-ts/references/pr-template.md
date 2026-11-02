# Commit, pull request and report

Steps 8, 9 and 13 of the skill.

## Commit

Stage exact paths, never `-A`. Stage the manifests, the lockfile, the config entries the patch needed (an
override, an exact age-gate exclusion), a changeset, and source files only when Step 7 adapted them. Approved risk
acceptances go in their own `chore(security): accept risk for <ids>` commit. Never stage `.npmrc`, `.env*`,
`.claude/`, `.vscode/` or `.github/workflows/`.

```
fix(deps): patch <n> vulnerable packages for production

- <pkg> <from> → <to> (<GHSA-…>, <CVE-…>, <severity>)
Deferred: <pkg> (<reason>), …
Production: <prod-sha>
```

semantic-release and release-please cut a patch release for `fix`, and nothing for `chore(deps)`. When every
patched package is development-only, use `chore(deps-dev):` and do not release. With `--release`, when the
deploy checks the `package.json` `version`, bump its patch number in the same commit.

With `.changeset/config.json`, write `.changeset/security-patch-<YYYY-MM-DD>.md` first. Give each published
package whose runtime dependencies changed a `patch` entry, followed by one line naming the advisories. Skip it
when every touched package is private. When `.changeset/pre.json` exists, stop and ask.

## Title

`fix(deps): security patch for production (<n> advisories, <highest severity>)`, or
`chore(deps-dev): security patch (<n> advisories, <highest severity>)`. A squash merge takes the title as the
commit subject, so the prefix decides whether release tooling releases.

## Body

Pass the body to `gh pr create` through a quoted heredoc (`--body "$(cat <<'EOF' … EOF)"`), so nothing in it is
expanded. Keep each table under about 50 rows, and never paste raw audit JSON or logs.

```markdown
> [!CAUTION]                      ← only when autonomy was revoked, malware was found, or a risk was escalated
> Autonomy revoked: <reasons>. A human must review and merge this PR.
> <the malware incident notice from verify.md>
> Escalated: <pkg> needs <version> (high risk: <risk line>). Schedule the upgrade now.

## Production base
- Production commit `<sha>` (<signal>, <strong|weak>); drift on `<default>`: <n> commits
- Targets `<base>`; ships by <"merging deploys" | "tag <next> after merge" | "a human">

## Advisories fixed
| Package | From → To | Change | Advisory | Severity | Risk (CVSS · EPSS · exposure) | Verdict |
|---|---|---|---|---|---|---|

## Verification (trust but verify)
One block per target, one line per check, from verify.md:
- **<pkg> <from> → <to>**: fix <sha> in tag <tag> ✓ · publisher <name> (previously <name>) · age <n> d ✓ · provenance ✓ · scripts and deps unchanged ✓ · diff: <what changed, and that it matches the fix> · app: <usage and impact>
Other versions the patch moved: <pkg from → to: registry ✓, files ✓>, …

## Risk accepted
| Package | Advisory | Risk line | Why the fix waits | Reason | Recorded in (or proposed entry) | Expires |
|---|---|---|---|---|---|---|
<the proposed entries in a code block, as verify.md "Accept the risk" writes them: one comment line and one id
line per advisory>
Unattended runs write nothing: paste these entries, and dismiss the listed Dependabot alerts, only after review.

## Deferred and ruled out
| Package | Advisory | Reason (rejected verdict, regression, not in production, accepted earlier, withdrawn…) |
|---|---|---|

## Gates
| Gate | Baseline (`<sha>`) | Patched |
|---|---|---|
Node <version> locally (CI: <version>). Not run locally: <secret-bound steps, e2e>.

## Review
/code-review high --fix on `<prod-sha>..HEAD`: <fixed n, skipped n, one line each>

## Follow-ups
- <majors to schedule, the default-branch PR, Dependabot PRs this supersedes>
```

## Report (Step 13)

Write it for someone who watched none of the run:
- the outcome in one sentence;
- the production commit and how it was found;
- the PR links;
- what was fixed: package, from → to, advisory, severity, the risk line, verdict;
- what was accepted (where it was recorded, and its expiry), escalated, deferred or ruled out, with reasons;
- the gates, baseline vs patched;
- the review fixes;
- why autonomy was revoked;
- the deploy result;
- follow-ups: escalations first; with drift, the default branch still lacks the fix and its next deploy would
  undo it; majors to schedule; honored acceptances that a cheap fix now makes unnecessary; secret rotation after
  malware.

When no PR was opened (local-only, `--report-only`, or a stop before Step 9), end the report with the PR body
above, filled in. It keeps the risk lines, the verification lines, the proposed acceptance entries (one per id,
ready to paste, each with its expiry) and the review findings.
