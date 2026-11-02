# Baseline, patch, gates and review

Steps 5 to 8 of the skill. The commands for each package manager are in `package-managers.md`.

## Contents
- Baseline (Step 5)
- Patch (Step 6)
- Re-audit and gates (Step 7)
- Commit and review (Step 8)

## Baseline (Step 5)

1. At the production commit, create the work branch: `git switch -c security/patch-<YYYY-MM-DD>`. Add `-2`, `-3`
   and so on when the name is taken locally (`git branch --list`) or on origin (`git ls-remote --heads`).
2. Find the gates CI runs on pull requests in `.github/workflows/`, following local composite actions and
   reusable workflows. Keep install, codegen, typecheck, lint, build and unit tests. Drop, and note, the steps
   that need secrets, services, deploys or browser end-to-end suites. If CI is opaque, use the `package.json`
   scripts (typecheck, lint, build, test), never dev, start, watch, or a publish, release or deploy script.
   Without a typecheck script, run the project's own TypeScript as `package-managers.md` shows, with `--noEmit`
   (`-b` when the tsconfig has `references`). Run test runners non-interactively (`vitest run`, `jest --ci`), and
   bypass turbo and nx caches (`--force`, `--skip-nx-cache`).
3. Use CI's Node version (`setup-node`, `.nvmrc`, `engines`), and record it when the local major differs.
4. Install with scripts disabled, as `package-managers.md` shows. Then run the root project's own
   `prepare`/`postinstall` and codegen with `<pm> run`.
5. Run each gate in its own Bash call, with `run_in_background: true` and `timeout: 900000`, and wait for its
   completion notice before starting the next. Never pipe an install, a resolve or a gate into `tail` or `head`:
   the exit code would be lost. Record each exit code and the ids of failing tests.
6. A gate that cannot complete (a red install, typecheck or build, a crashed or hung runner, or the timeout)
   gives no baseline, and autonomy is revoked. Ask whether to exclude that gate; unattended, exclude it and say
   so.

With a confirmed malware advisory, do items 1 to 3 only: installing the production tree would let tests and tools
import the payload. The gates then run once, after the patch.

## Patch (Step 6)

1. With `bun.lockb`, save `bun pm ls --all` first, to compare later. Apply the plan with the commands of
   `package-managers.md`, lockfile-only and with scripts disabled, in this order: refresh, bump-direct,
   bump-parent, override. When the project's release-age gate refuses a target, follow `package-managers.md`:
   add only an exact, per-command or per-package exclusion, which revokes autonomy. Never lower or disable the
   gate in configuration.
2. Run the sync check of `package-managers.md`. It must be clean.
3. Run `git status --porcelain`. Only the files `package-managers.md` lists may change: restore anything else, and
   find out why it changed.
4. List every version the lockfile changed with `git diff <prod-sha> -- <lockfile>` (for `bun.lockb`, compare
   with the list from item 1), and apply "Lockfile checks" in `verify.md`. Every version that moved without
   Step 4 verifying it gets "Verify a moved version" in `verify.md`: transitive refreshes, parent-bump subtrees,
   newest-in-range landings and packages new to the tree.

## Re-audit and gates (Step 7)

1. Re-run the audit. Every planned advisory must be gone, and no new one may appear. If one remains, go back to
   Step 6 for that package, twice at most, then defer it.
2. Install with scripts disabled. For npm, also run `npm audit signatures`.
3. Run the same gates with the same Node version, as in Step 5, and compare them with the baseline. Re-run a test
   that fails once: if it passes, it is flaky, so note it.
4. On a regression, work from the production commit, because all items share the manifests and the lockfile:
   - If the error names a bumped package (a stack frame, a type, an import), defer that item with the first
     error line. Restore with `git restore --source=<prod-sha> -- <manifests> <lockfile>`, and redo Steps 6 and
     7 with the remaining items.
   - Otherwise bisect the same way: redo Step 6 with half of the items, run the failing gate, and narrow down.
   - After three rounds without green, stop and report.

   Prefer deferring a package to adapting code. Adapt source only for a small, mechanical change (a renamed type,
   a moved import) that Step 4 predicted, and only when the user agrees. Unattended: defer.

## Commit and review (Step 8)

1. Commit the patch as "Commit" in `pr-template.md` shows.
2. Write each approved risk acceptance as "Accept the risk" in `verify.md` shows, and commit it separately:
   `chore(security): accept risk for <ids>`.
3. Call the Skill tool with skill `code-review` and these args:
   `high --fix <prod-sha>..HEAD -- Dependency versions are out of scope: never run a package manager, and never edit package.json, lockfiles or scanner ignore files. Advisories this commit defers or accepts are out of scope too: report them, never work around them in source.`
   Always pass the range: without it the review may diff against `main`. A repository's own `code-review` skill
   replaces the built-in one: call it the same way, and say so in the report. Wait for the review to finish.
4. If the review changed a manifest, the lockfile or an ignore file, restore them: a version the review picked is
   unverified. If it installed anything, re-run Step 7's install with scripts disabled. Keep source fixes that
   repair a real defect in the patch, and revert cleanups (`git restore -- <file>`). After a kept change, run
   Step 7 again and commit `fix(deps): address review findings`. An unfixed finding about the patch revokes
   autonomy, unless it only contests a choice this skill makes on purpose (a refresh that keeps the declared
   range, an honored or proposed acceptance, a deferred major): answer those in the PR.
