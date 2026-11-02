# Package-manager commands

Read the top section, then the section for the repository's package manager. The commands were verified against
npm 11.20, pnpm 9 to 12, Yarn Berry 4.18, Yarn Classic 1.22 and Bun 1.4.

Every audit, instances and resolve command below works from the lockfile alone, with no `node_modules`. An audit
exits non-zero when it finds vulnerabilities, and that is not an error. Read settings with `<pm> config get
<key>`, never by opening `.npmrc` or `.yarnrc.yml`, which hold registry tokens.

## Contents
- Choosing the change
- npm
- pnpm
- Yarn Berry
- Yarn Classic
- Bun

## Choosing the change

For each vulnerable instance, use the first form that works:

| Change | When | Effect |
|---|---|---|
| **refresh** | Every declared range already admits the target | The lockfile moves; for a direct dependency, pnpm and Bun also raise the spec's floor |
| **bump-direct** | A direct dependency's spec excludes the target | The spec moves to the target, keeping its style (`^`, `~`, exact). Same major only |
| **bump-parent** | A transitive instance whose parent's range excludes every patched version | The parent moves to the lowest version in its own major whose range admits one. Find it with `npm view '<parent>@>=<current> <<next major>' dependencies.<pkg>`. The parent may itself be direct or transitive |
| **override** | No parent version in its major admits a fix, and the target is in the major the parent requests | Pin the exact target, scoped to that parent |
| **none** | None of the above, or a spec this page does not cover (`catalog:`, `workspace:`, `npm:` aliases, URLs, complex ranges) | No hotfix-sized fix: `verify.md` "Decide" chooses accept or escalate |

A bump-parent can move the transitive package across a major (`mkdirp` 0.5.1 → 0.5.2 takes `minimist` from
0.0.8 to ^1.2.5). The package manager then lands it on the newest version in the parent's new range, not on the
target, and nothing moves it lower. Step 6 verifies the version it lands on, and it gets the whole "Verify the
application" check.

## npm

- **Version.** Run `npm --version`. Compare it with a `packageManager` or `engines.npm` pin only. npm 10 and 11
  write the same lockfile, so the npm bundled with CI's Node is not a mismatch.
- **Lockfile.** It is `package-lock.json`, or `npm-shrinkwrap.json` when that file exists. Any write turns a
  lockfileVersion 1 into version 3: pass `--lockfile-version=1` on every resolve command, or accept the upgrade
  and say so in the PR. npm 11 runs dependency install scripts by default, so always pass `--ignore-scripts`.
- **Audit.** `npm audit --json --package-lock-only`.
- **Instances.** `npm ls <pkg> --all --package-lock-only`.
- **Resolve flags.** Put these right after the subcommand, so the pre-approved prefixes match:
  `npm install --package-lock-only --ignore-scripts --no-audit --no-fund …`, and the same for `npm update`.
  `--package-lock-only` prints `up to date` even when it changed the lockfile: judge by `git diff`.
- **Workspaces.** Find the workspace that declares a dependency with
  `npm query '.workspace:has(> #<pkg>)' --package-lock-only`, and add `-w <workspace>` to `install`. Without it,
  npm adds the package to the root manifest.

| Change | Commands |
|---|---|
| refresh, direct | `npm install … <pkg>@<target>`, then `git restore -- <the package.json files>`, then `npm install …` with no package, so only the lockfile changes |
| refresh, transitive | Run `npm view <pkg> 'time[<target>]'`, then `npm update … --before=<that time + 1 s> <pkg>`, so it lands on the target and not on something newer. When several copies move, use the newest target's time. If the project sets `min-release-age` or `before` and the target is younger than that, this `--before` steps over the gate: it is a release-age exclusion, so it revokes autonomy and the PR says so. Never `npm install <transitive>@<v>`: it adds a direct dependency and leaves the nested copy |
| bump-direct | `npm install … --save-exact=false --save-prefix=^ <pkg>@<target>`, or `--save-prefix=~`, or `--save-exact` for an exact spec, with `-w` in a workspace. Pass the save style explicitly, because the project configuration overrides it. Never pass `-D`, `-P` or `-O`: they move the dependency to another section |
| bump-parent | bump-direct or refresh, with the parent's name and version |
| override | In the ROOT `package.json`: `"overrides": { "<parent>@<parentVersion>": { "<pkg>": "<target>" } }`, with an exact version, never `>=`. Then `npm install …`, then `npm ls <pkg> --all --package-lock-only`, which must exit 0 and show `overridden`. In a workspaces repository, also run the transitive refresh. Never override a root direct dependency (`EOVERRIDE`): bump it |

- **Sync check.** Stage the changed manifests and the lockfile (`git add -- <only paths git status lists>`). Run
  `npm install …` with no package, then `git diff --exit-code -- package-lock.json`, then
  `npm ls --all --package-lock-only`. Both checks must exit 0. `npm ci` alone is not proof.
- **Release-age gate.** Read it with `npm config get min-release-age` (days, npm 11.10+) and
  `npm config get before`. A young target fails with `ETARGET … with a date before`, and `npm update` silently
  stays below it. Add `--min-release-age-exclude=<pkg>` to that single command only, once for the target and once
  for each of its new dependencies that is younger than the gate. Then check that the target's dependency
  entries are all in the lockfile.
- **Install for the gates.** `npm ci --ignore-scripts`, then `npm audit signatures --json`: an `invalid` or
  `missing` entry revokes autonomy. Run the project's TypeScript with `npm exec --no -- tsc`, and its scripts with
  `npm run`.
- **Files that may change:** the `package.json` files and the lockfile.

## pnpm

- **Version.** pnpm 10+ switches to the version pinned in `packageManager` by itself, and `pnpm --version` then
  prints it. With no pin, use the version CI installs (`pnpm/action-setup`). Another major churns the lockfile.
- **Audit.** `pnpm audit --json`. Its `findings[].paths` are the instances.
- **Instances.** `pnpm why <pkg>`, with `-r` in a workspace.
- **Resolve flags.** Use `--lockfile-only`, plus `--ignore-scripts` where accepted. In a workspace, put `-r` or
  `--filter <project>` AFTER the subcommand. pnpm 10 silently does nothing at the root for a dependency that only
  a workspace declares.
- **Where overrides live.** pnpm 9: `package.json` `pnpm.overrides`. pnpm 10: the one the repository already
  uses, or `pnpm-workspace.yaml` `overrides:` by default. pnpm 11+: `pnpm-workspace.yaml` only. Quote YAML keys
  that contain `@`, `>` or `<`. Key overrides by the installed version: GitHub's comma ranges
  (`>= 1.1.0, < 2.0.8`) are silently ignored.

| Change | Commands |
|---|---|
| refresh, transitive | Override-then-drop. Add `'<pkg>@<installed version>': <target>` under `overrides:`, then run `pnpm install --lockfile-only --ignore-scripts`. Remove exactly the override you added, but keep any `minimumReleaseAgeExclude` entries pnpm wrote. Delete `pnpm-workspace.yaml` only if you created it and it is now empty. Run the install again: the lockfile keeps the target |
| refresh or bump-direct, direct | `pnpm update <pkg>@<target> --lockfile-only`. It resolves exactly the target and keeps the spec's style and section. Never `pnpm add`: pnpm 11+ drops the prefix |
| bump-parent | the same forms, with the parent's name and version |
| override | `'<parent>@<parentVersion>><pkg>@<installed version>': <target>`, with an exact value and never `>=`. Then `pnpm install --lockfile-only --ignore-scripts` |

- **Sync check.** Stage the changed files (only paths git status lists). Run
  `pnpm install --lockfile-only --ignore-scripts`, then `git diff --exit-code -- pnpm-lock.yaml`.
- **Release-age gate.** `minimumReleaseAge` is in minutes, and pnpm 11+ defaults to 1440. Under the default,
  range resolution skips young versions. An exact version is accepted, and pnpm writes
  `minimumReleaseAgeExclude: ['<pkg>@<v>']` into `pnpm-workspace.yaml`. Keep that entry, or CI's frozen install
  fails. When the gate is set explicitly, add an exact `<name>@<version>` entry for the target and for each
  package the error lists. Either way, autonomy is revoked. Never set the gate to 0.
- **Install for the gates.** `pnpm install --frozen-lockfile --ignore-scripts`. Run the project's TypeScript with
  `pnpm exec tsc`, and its scripts with `pnpm run`.
- **Files that may change:** the `package.json` files, `pnpm-lock.yaml` and `pnpm-workspace.yaml`.
- **Never** run `pnpm audit --fix`, which writes `>=` overrides that cross majors.

## Yarn Berry

- **Version.** Berry repositories commit their release (`yarnPath` in `.yarnrc.yml`), and `yarn --version` must
  print it. Never run `corepack enable`. A newer Berry rewrites `.yarnrc.yml`, so check `git status` after the
  first command. If `.yarnrc.yml` or the lockfile header changed, restore them and stop.
- **Audit.** `yarn npm audit --all --recursive --json`. It prints one JSON object per line.
- **Instances.** `yarn why <pkg> -R`.
- **Resolve flags.** Always use `--mode=update-lockfile`. It resolves without linking or running scripts.
  `YARN_IGNORE_SCRIPTS` is ignored since 4.15.

| Change | Commands |
|---|---|
| refresh | `yarn up -R --mode=update-lockfile <pkg>`. It moves every descriptor to the newest version in its range, not the minimum, so Step 6 verifies the version it lands on |
| bump-direct | `yarn up --mode=update-lockfile '<pkg>@^<target>'` (or `~`), or `<pkg>@<target>` for an exact spec. A range resolves to its newest version. Never run a bare `yarn up <pkg>`: it jumps to the latest major. `yarn up` edits every workspace that lists the package |
| bump-parent | the same forms, with the parent's name |
| override | In the ROOT `package.json`: `"resolutions": { "<pkg>@npm:<range the parent requests>": "<target>" }`, then `yarn install --mode=update-lockfile`. Never use a bare name or `**/`. Range selectors such as `"<pkg>@<1.2.3"` are silently ignored |

- **Sync check.** Stage the changed files (only paths git status lists). Run
  `yarn install --check-resolutions --mode=update-lockfile`, then `git diff --exit-code -- yarn.lock`. Never
  combine `--immutable` with `--mode`. In zero-install repositories (`.yarn/cache` committed), the PR includes
  the swapped `.zip` files.
- **Release-age gate.** Read it with `yarn config get npmMinimalAgeGate`. It defaults to 1 day since 4.15. Range
  resolution silently stays below a young target, and an exact young version fails with `YN0016 … quarantined`.
  Add `--no-time-gate` to that single `yarn up`, and never edit `.yarnrc.yml`. Yarn checks the gate only when it
  resolves, so CI's immutable install accepts the locked version. This revokes autonomy.
- **Install for the gates.** `yarn install --immutable --mode=skip-build`. Then run the project's TypeScript with
  `yarn run tsc`, its own scripts with `yarn run`, and workspace scripts with
  `yarn workspaces foreach -A -t run <script>`. That command exits 0 when no workspace has the script, so check
  that one does.
- **Files that may change:** the `package.json` files, `yarn.lock`, `.pnp.*` when committed, and `.yarn/cache`.

## Yarn Classic

- **Audit.** `yarn audit --json`, one JSON object per line. Its endpoint is retiring and may rate-limit or answer
  410. If it does, rely on the Step 1 sources. Check each package they name against the lockfile with
  `gh api -X GET 'advisories?ecosystem=npm&affects=<pkg>@<version>'`, writing a scope's leading `@` as `%40`
  (`=@` is denied). Then check again with `&type=malware` added, because the default omits malware advisories.
  Say so in the PR.
- **Instances.** `yarn why <pkg>`.
- `yarn --version` prints 1.x. Every command carries `--ignore-scripts`. Never pass Berry's `--mode`: Classic
  ignores it and runs every install script. Classic cannot pin a minimal version inside a range, so Step 6
  verifies the version it lands on.

| Change | Commands |
|---|---|
| refresh, transitive | Delete that package's entry block from `yarn.lock` with the Edit tool, then run `yarn install --ignore-scripts`. `yarn upgrade <transitive>` does nothing |
| refresh or bump-direct | `yarn upgrade '<pkg>@^<target>' --ignore-scripts` (or `~`), or `<pkg>@<target>` for an exact spec |
| bump-parent | A direct parent: `yarn upgrade <parent>@<to> --ignore-scripts`. A transitive parent: the transitive refresh, applied to the parent's block. Never `yarn upgrade` a transitive package with a version: that adds it to `package.json` |
| override | ROOT `package.json` `"resolutions": { "<parent>/**/<pkg>": "<target>" }`, then `yarn install --ignore-scripts`. `yarn why <pkg>` must show the target. A version-qualified key is silently ignored |

- **Sync check.** Stage the changed files (only paths git status lists). Run `yarn install --ignore-scripts`,
  then `git diff --exit-code -- yarn.lock`. `--frozen-lockfile` is not proof.
- **Install for the gates.** `yarn install --frozen-lockfile --ignore-scripts`. Then run the project's TypeScript with
  `yarn run tsc`, and the root scripts with `yarn run`, per workspace.
- **Files that may change:** the `package.json` files and `yarn.lock`.

## Bun

- **Version.** Bun ignores `packageManager`, so compare `bun --version` with CI's `oven-sh/setup-bun`
  `bun-version`. Nested overrides switch `bun.lock` to a format that Bun 1.3 cannot read, so use them only when CI
  runs Bun 1.4+. `bun.lockb` is binary: never pass `--save-text-lockfile`.
- **Audit.** `bun audit --json`.
- **Instances.** `bun why <pkg>`. List every version with `bun pm ls --all`.
- **Resolve flags.** Use `--lockfile-only --ignore-scripts`, plus `--filter <workspace>` or `-r` in a workspace.

| Change | Commands |
|---|---|
| refresh, transitive, one copy | Override-then-drop: add `"overrides": { "<pkg>": "<target>" }` to the root `package.json`, run `bun install --lockfile-only --ignore-scripts`, remove exactly what you added, then install again |
| refresh, transitive, several copies | `bun update <pkg> --lockfile-only --ignore-scripts`. It moves each copy to the newest version in its range |
| refresh or bump-direct, direct | `bun update <pkg>@<target> --lockfile-only --ignore-scripts`. Never `bun add`: it drops the prefix and re-sorts the manifest |
| bump-parent | the same forms, with the parent's name |
| override | Root `package.json`: `"overrides": { "<parent>": { "<pkg>": "<target>" } }` on Bun 1.4+. On 1.3, use a top-level `"<pkg>": "<target>"`, and only when every copy may take that exact version |

- **Sync check.** Stage the changed files. Run `bun install --lockfile-only --ignore-scripts`, then
  `git diff --exit-code -- <bun.lock or bun.lockb>`. `--frozen-lockfile` is not proof.
- **Release-age gate.** `bunfig.toml` `minimumReleaseAge` is in seconds. Add
  `--minimum-release-age-excludes=<pkg>` to that single command, which revokes autonomy. Never edit
  `bunfig.toml`.
- **Install for the gates.** `bun install --frozen-lockfile --ignore-scripts`. This also stops the postinstall
  scripts of Bun's default-trusted packages. Run project scripts with `bun run --filter <root package name>
  <script>`, and the project's TypeScript with `bun run tsc`.
- **Files that may change:** the `package.json` files and the lockfile.
- **Never** run `bun audit fix`: it picks deprecated versions and runs scripts.
