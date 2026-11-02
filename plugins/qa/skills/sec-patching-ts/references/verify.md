# Trust but verify

Steps 1, 3, 4 and 6 of the skill. The package manager is trusted to resolve a patched version. Everything below
is verified by reading the evidence yourself. Run every `npm` command from the repository root: in a directory
without a `package.json`, npm walks up to a parent project.

## Contents
- Intake (Step 1)
- Verify the vulnerability (Step 3)
- Assess the risk (Step 3)
- Decide (Steps 3 and 4)
- Accept the risk (Steps 1, 8 and 9)
- Verify the patch (Step 4)
- Verify the application (Step 4)
- Verdicts (Step 4)
- Lockfile checks (Step 6)
- Verify a moved version (Step 6)
- Malware
- What these checks do not prove

## Intake (Step 1)

Collect the advisories every source names. Sources other than the production audit describe the default branch,
so Step 3 decides what applies.

- **Arguments and session context:** GHSA/CVE ids, `package@version` pairs, audit files, and the ids in any other
  report (SARIF, Snyk, a pasted table, a Dependabot PR title).
- **Dependabot** (a 403 or 404 means the source is unavailable):

  ```bash
  gh api -X GET repos/<owner>/<repo>/dependabot/alerts --paginate -f state=open,dismissed -f ecosystem=npm -f per_page=100 --jq '.[]|{number,state,ghsa:.security_advisory.ghsa_id,pkg:.dependency.package.name,scope:.dependency.scope,dismissed_reason,dismissed_comment}'
  ```

- **CI security job:** a run URL argument wins. Otherwise find the security workflow (`gh workflow list`; names
  such as security, audit, osv, snyk, trivy, dependency-review) and its latest completed run on the default
  branch (`gh run list --workflow <file> --branch <default> --limit 5`). Read its report artifact
  (`gh run download <id> -n <artifact> -D <scratch dir>`), or grep the failing job's log
  (`gh api -X GET repos/<owner>/<repo>/actions/jobs/<id>/logs`) for the ids.
- **Earlier risk acceptances:** Dependabot alerts dismissed as `not_used`, `tolerable_risk` or `inaccurate`, and
  the ignore files of the scanners the project runs, as "Earlier acceptances" below defines them. Record each
  id, where it was accepted, and its expiry.

## Verify the vulnerability (Step 3)

Keep an advisory when items 1 and 2 hold and its severity reaches `--severity` (malware always does). Rule out the
others, and keep the reason for the PR: withdrawn, unknown advisory, not in production, already patched, below
threshold. An advisory that an unexpired earlier acceptance covers follows "Earlier acceptances".

1. **The advisory exists.** Every audit output carries a `https://github.com/advisories/GHSA-…` URL. npm's
   numeric `source` id is not a GHSA. Look up each advisory:

   ```bash
   gh api -X GET /advisories/<GHSA-id> --jq '{ghsa_id,cve_id,type,severity,withdrawn_at,summary,source_code_location,references,epss,cvss:.cvss_severities,vulnerabilities:[.vulnerabilities[]|{name:.package.name,range:.vulnerable_version_range,patched:.first_patched_version,functions:.vulnerable_functions}]}'
   gh api -X GET advisories -f cve_id=<CVE-id> -f ecosystem=npm --jq '.[].ghsa_id'
   ```

   Rule out an advisory with `withdrawn_at` set. An id that does not resolve is a wrong or forged report: rule
   it out and say so. `type: unreviewed` is weaker evidence: keep it, and label it in the PR. `type: malware`
   goes to the Malware section.
2. **Production is affected.** Find the installed instances in the production lockfile with the
   "Instances" command of `package-managers.md`. Check that each installed version is in the
   `vulnerable_version_range`. GitHub writes ranges with commas (`>= 1.0.0, < 1.2.6`), and npm wants spaces:
   `npm view '<pkg>@>=1.0.0 <1.2.6' version --json` lists the published versions in range. An advisory can carry
   one entry per major line: use the entry whose range contains the installed version.
3. **Exposure.** Record for each confirmed advisory:
   - **Ships or dev-only:** the instance is dev-only when every path from the project goes through
     `devDependencies`.
   - **Reached by the application:** `vulnerable_functions`, the summary and the description name the vulnerable
     API and its preconditions (for example `_.template` with the `variable` option, or a parser fed untrusted
     input). Grep the application's own source, excluding `node_modules` and build output, for imports of the
     package (`from '<pkg>'`, `from '<pkg>/…'`, `require('<pkg>')`, `import('<pkg>')`), for that API, and for the
     preconditions. Record: `reachable`, `not reached`, `preconditions absent` (name them), `transitive, not
     assessed` or `dev-only`. An instance that other shipped packages also depend on (the instances command lists
     them) is `transitive, not assessed`, unless the application's own code reaches the vulnerable path.
4. **Target.** The target is the lowest version at or above `first_patched_version` in the installed major. A
   0.x minor counts as a major. List the candidates with `npm view '<pkg>@>=<patched> <<next major>' version --json`.
   One match prints a string, and none gives E404.
   - Skip a deprecated version (`npm view <pkg>@<v> deprecated`) when a later version in the same major is not
     deprecated. lodash 4.18.0 "Bad release" leads to 4.18.1, and mkdirp 0.5.2 to 0.5.4 ("Legacy versions…")
     lead to 0.5.5. A notice on every later version of the major, such as tar 6.x's, does not count.
   - Skip versions that another confirmed advisory still covers, when that advisory has a fix in the same major.
   - A transitive instance with no candidate may still be fixed by a bump-parent that keeps the parent in its
     major (package-managers.md). Its version then crosses its own major, and it gets the whole "Verify the
     application" check.

   Otherwise there is no hotfix-sized fix: "Decide" chooses between accept and escalate.

## Assess the risk (Step 3)

The GitHub advisory gives `cvss` (`cvss_v4.vector_string` when present, else `cvss_v3.vector_string`) and `epss`.
In `epss`, `percentage` is the probability of exploitation in the next 30 days and `percentile` its rank, both
fractions between 0 and 1: 0.21 means 21 %. `epss` is null for an advisory without a CVE, and for many recent
ones. Read the vector:

| Metric | Easier to exploit | Harder |
|---|---|---|
| Attack vector `AV` | `N` network | `A` adjacent, `L` local, `P` physical |
| Attack complexity `AC` (v4 also `AT`) | `L` low (`AT:N`) | `H` high (`AT:P`) |
| Privileges required `PR` | `N` none | `L`, `H` |
| User interaction `UI` | `N` none | `R` required (v4 `P` passive, `A` active) |

The impact is `C`, `I` and `A` in v3, or `VC`, `VI` and `VA` in v4, each `H`, `L` or `N`.

**Likelihood.** Take the first row that applies:
1. **Unlikely:** the instance is dev-only, the vulnerable path is not reached, or its preconditions are absent
   from this code.
2. **Likely:** EPSS ≥ 10 % or percentile ≥ 0.95. Or an easy vector (all of `AV:N`, `AC:L`, `PR:N`, `UI:N`, and
   `AT:N` in v4) on a path this application exposes to untrusted input.
3. **Unlikely:** a hard vector (`AC:H`, `AT:P`, `UI` not `N`, `PR:H`, or `AV` local or physical), with EPSS below
   1 %. Without EPSS, this row does not apply.
4. **Possible:** anything else, including "transitive, not assessed".

**Impact.** It is high when the advisory rates C, I or A `H`, and this application holds that asset: user data or
secrets for C, data it writes or code it runs for I, a service others depend on for A. It is low otherwise.
Without a CVSS vector, the advisory's severity stands in: high or critical counts as an `H` rating. For
example, an availability flaw in a CLI run only by developers has low impact.

**Risk.**
- **High:** likely, or possible with high impact.
- **Low:** unlikely, or possible with low impact.

Write the inputs in one line per advisory, for the PR. For example: `CVSS AV:N AC:L PR:N UI:R · C:H I:N A:N ·
EPSS 0.7 % (p53) · ships, not reached → low`.

## Decide (Steps 3 and 4)

| Cheapest fix | High risk | Low risk |
|---|---|---|
| A patch release in the installed minor | patch | patch |
| A minor release, or a same-major parent bump, with no breaking change or compatibility concern found in Step 4 | patch | patch |
| A minor release, or a same-major parent bump, with one | patch, and let Step 7 adapt or defer | accept |
| Only a major release, or no fix | escalate | accept |

- A cheap, verified fix is always applied, whatever the risk, unless an earlier acceptance covers it (below).
- One change that fixes several advisories, such as a shared parent bump, is decided once, by the highest risk
  among them.
- A high risk is never accepted. When its fix is deferred later (a rejected or kept-deferred verdict, a Step 7
  regression, a re-audit that still reports it), escalate it.
- An escalated advisory is deferred, and named first in the report and the PR: "upgrade <pkg> to <version> now".
- Malware is never accepted: see Malware.

## Accept the risk (Steps 1, 8 and 9)

An acceptance records why this advisory stays open: the risk line, the reason ("not reached: <evidence>", or
"major upgrade, low risk"), and an expiry 90 days out. When it expires, the scanners report the advisory again and
the decision is re-made. In interactive mode, write it only after the user approves it. Unattended, only propose
it, in the PR or in the report when no PR is opened, with the exact entries ready to paste.

Record it where the project's scanners read it:

- **Trivy**, when CI runs `aquasecurity/trivy-action` or `trivy`, in the ignore file it uses: the action's
  `trivyignores`, a `--ignorefile`, or by default `.trivyignore` in the directory Trivy runs from (the repository
  root for the action, whatever its `scan-ref`). Use the id Trivy reports: the CVE when there is one, else the
  GHSA. Write one block per id, each with its own comment line and its own risk line.

  ```
  # <pkg>@<version>: <reason>. Risk low (<risk line>). Reviewed <YYYY-MM-DD>, <PR link>
  <CVE-or-GHSA-id> exp:<YYYY-MM-DD>
  ```

  For a `.trivyignore.yaml`, which works only through `--ignorefile`, add an entry with `id`,
  `purls: [pkg:npm/<name>@<version>]`, `statement` and `expired_at`.
- **Dependabot:** dismiss the open alert. Use `not_used` when the code does not reach the vulnerable path, and
  `tolerable_risk` otherwise:

  ```bash
  gh api -X PATCH repos/<owner>/<repo>/dependabot/alerts/<number> -f state=dismissed -f dismissed_reason=<not_used|tolerable_risk> -f dismissed_comment='<reason, risk line, expiry, PR link: 280 characters at most>'
  ```

  A dismissal has no expiry: put the date in the comment.
- **Another scanner the CI already runs** (`osv-scanner.toml` `[[IgnoredVulns]]`, pnpm `auditConfig`, an
  `audit-ci` allowlist): use its ignore file, in its documented format, with an expiry where supported.

Never create a scanner configuration the project does not use. Without one, the PR and the report carry the
acceptance.

**Earlier acceptances** (Step 1) are unexpired entries in the files above or in `.snyk`, and Dependabot alerts
dismissed as `not_used`, `tolerable_risk` or `inaccurate`. A dismissal as `fix_started` or `no_bandwidth`
accepts nothing.

The team's acceptance is honored: the advisory is ruled out as "accepted earlier (<where>)", even when a cheap
fix exists. The report then lists that acceptance as no longer needed. Two exceptions:
- the user named the advisory: decide it with the table above;
- your own assessment rates the risk high: escalate it, even when a cheap fix exists, and quote the acceptance it
  contradicts.

An expired entry is treated as open.

## Verify the patch (Step 4)

Do this for each target `<pkg>@<target>`, comparing it with the installed version `<pkg>@<old>`. Gather the
evidence in this order.

### 1. Trace the fix to the published version

1. **The fix commit.** Take it from the advisory's `references`:
   - a `github.com/<o>/<r>/commit/<sha>` URL;
   - a `/pull/<n>` URL: `gh api -X GET repos/<o>/<r>/pulls/<n> --jq '{merged,merge_commit_sha}'`;
   - a repository advisory, which links no commit: search the commits between the two releases for the fix.

   Read the fix with
   `gh api -X GET repos/<o>/<r>/commits/<sha> --jq '{message:.commit.message,files:[.files[]|{filename,patch}]}'`.
   It must change the vulnerable code the advisory describes. A test for it is a good sign.
2. **The repository.** Run `npm view <pkg>@<target> repository.url gitHead --json`. The repository must be the
   advisory's `source_code_location` after GitHub's redirect (`gh api -X GET repos/<o>/<r> --jq .full_name`), or a
   repository the advisory's references link to. For example, minimist moved from substack/minimist to
   minimistjs/minimist. Any other repository, or none, means: needs a human.
3. **The tag.** Try `v<target>`, then `<target>`, then `<pkg>@<target>`, each resolved exactly with
   `gh api -X GET repos/<o>/<r>/commits/<tag> --jq .sha`.
4. **The published code contains the fix.** Run `gh api -X GET repos/<o>/<r>/compare/<fix-sha>...<gitHead> --jq .status`,
   or compare with the tag when there is no `gitHead`:
   - `ahead` or `identical` means it does.
   - `behind` or `diverged` means it does not.
   - HTTP 404 "No common ancestor" means a build tag with its own history. lodash, for example, publishes 4.18.1
     from `4.18.1-npm`. Accept it when that tag is in the same repository and the code diff shows the fix.
   - HTTP 404 "Not Found" means `gitHead` is not in the repository: a gap in the trace.

When gh is unavailable, skip this trace. Say so, and rely on the registry record and the code diff.

### 2. Read the registry record

```bash
npm view <pkg> 'time[<target>]'
npm view <pkg>@<target> _npmUser scripts dependencies dist.attestations dist.unpackedSize deprecated --json
npm view <pkg>@<old> _npmUser scripts dependencies dist.attestations dist.unpackedSize --json
```

Red flags:

| Signal | Why it matters |
|---|---|
| Published less than 72 hours ago | Most malicious versions are live for minutes to hours before removal, and 72 h is npm's unpublish window. A fresh security fix is common, so this alone means "needs a human", not "rejected" |
| The previous version in the same major had `dist.attestations` and this one has none | Provenance downgrade: published outside the project's CI (axios 1.14.1, nx 21.5.0). Old maintenance lines often never had provenance, so compare within the line |
| A new or changed `preinstall`, `install`, `postinstall` or `prepare` script, or a `gypfile` | The classic worm vector |
| A new dependency in a patch or minor release that is itself young (`npm view <dep> time.created` within 90 days), has install scripts, or is never imported by the package's code | The axios 1.14.1 pattern: plain-crypto-js was a day old, ran a postinstall, and no axios code required it. An established dependency that the code imports is routine |
| A dependency spec pointing at git, a URL, a file or a `user/repo` shorthand | Bypasses the registry |
| `unpackedSize` more than tripled | An embedded bundle or binary |
| A version unpublished within 72 h before the target (keys in `npm view <pkg> time --json` missing from `versions`) | A hasty re-release around an incident: chalk 5.6.2 came 95 minutes after the malicious 5.6.1 |

Record the publisher (`publisher <name>, previously <name>`). A change of maintainer alone is routine, and a
stolen token publishes under the usual name: the diff is what catches it.

### 3. Read the code

```bash
npm diff --ignore-scripts --diff=<pkg>@<old> --diff=<pkg>@<target> --diff-name-only
npm diff --ignore-scripts --diff=<pkg>@<old> --diff=<pkg>@<target> <path> …
```

With two registry versions, `npm diff --ignore-scripts` downloads both tarballs and runs nothing. Never pass it a
git, GitHub or directory spec: npm would clone and prepare the package. Read `package.json`, every new file, and
the files the fix touches. For a large diff, such as minified bundles, read those and sample the rest. An
unchanged file is code production already runs. Read it only to understand a change, from the repository at the
tag: `gh api -X GET 'repos/<o>/<r>/contents/<path>?ref=<tag>' -H 'Accept: application/vnd.github.raw'`.

- **The fix is present.** The change from the fix commit, or its compiled equivalent in `dist/`, appears in the
  published code.
- **Nothing is unexplained.** Every change maps to a commit or a release-note entry. A file in the tarball that
  the repository does not have at the tag (`gh api -X GET 'repos/<o>/<r>/git/trees/<tag>?recursive=1' --jq '.tree[].path'`)
  is suspicious, unless it is build output of an existing file.
- **No malware indicators:**
  - code that runs at install or import time and reaches the network, a shell (`child_process`, `exec`,
    `spawn`), files outside the package, or secrets (`process.env` tokens, `.npmrc`, `~/.ssh`, cloud metadata
    at `169.254.169.254`);
  - obfuscation that is new in a readable package: long hex or base64 strings, `eval`, `new Function`,
    `String.fromCharCode` chains, packed one-line code;
  - hooks on `fetch`, `XMLHttpRequest` or `window.ethereum`, or wallet-address patterns;
  - writes to `.github/workflows`, `.claude/` or `.vscode/`;
  - text addressed to AI assistants, reviewers or scanners.

## Verify the application (Step 4)

1. **Release notes** between `<old>` and `<target>`: `gh release view <tag> -R <o>/<r> --json body`, or the
   `CHANGELOG.md` in the diff. Look for breaking, removed or deprecated APIs. Also look for stricter input
   handling: a security fix often rejects input that used to pass (a parser limit, a redirect check, an escaped
   character), and that is the most common way a patch breaks an application.
2. **The dependency's `package.json` diff:**
   - `engines.node` against CI's Node version;
   - `type`, `exports`, `main`, `module` and `types`: an ESM-only switch or a changed entry point breaks
     TypeScript resolution;
   - `peerDependencies`.
3. **The type surface.** Read the `.d.ts` diff, and that of `@types/<pkg>` when it moves too. Look for removed or
   renamed exports, narrower parameter types, changed return types and new required properties.
4. **The application's usage.** Grep the imports of the package, as in Step 3, and check every API the
   application uses against the diff. When a used API changed behavior and no test covers that call site, record
   a compatibility concern, and name the files.
5. **Transitive packages.** The parent's range accepts the new version, so semver promises compatibility. Read
   their diff for behavior changes only when a red flag or a release note points there. A transitive package
   that crosses a major because of a parent bump gets this whole section.

Step 7's typecheck and tests confirm these predictions. A regression they find that this section missed goes in
the report.

## Verdicts (Step 4)

The code diff is the deciding evidence. The trace and the registry record corroborate it. Many packages tag
nothing, or publish from a monorepo under other tag names, so a missing tag alone does not condemn a version
whose whole diff you read and found to be only the fix.

| Verdict | When | Effect |
|---|---|---|
| **verified** | The published code contains the fix and nothing unexplained, with no red flag. A gap in the trace is noted, provided the diff was read in full | Apply it |
| **needs a human** | Any red flag that is not a malware indicator; a version younger than 72 h; a gap in the trace on a diff too large to read in full | Show the user the evidence and ask whether to keep or defer it; defer is the default. Unattended, keep it only when the sole concern is the age of a fix target whose diff is clean. A kept version revokes autonomy, and its evidence goes at the top of the PR |
| **rejected** | A malware indicator, the fix absent from the published code, or provenance lost within the major | Defer the advisory. For malicious code, follow Malware |

A compatibility concern, such as an API this application uses that changed behavior, does not block a patch
release: apply it, let the gates test it, name the call sites in the PR, and revoke autonomy. On a minor release
or a parent bump, "Decide" applies.

Record the evidence in one line per check, for the PR. For example: `fix 3469357 in tag 4.17.21 ✓ · published
from 4.17.21-npm, same repo ✓ · publisher bnjmnt4n, as for 4.17.20 · 5 y old ✓ · no scripts, no new deps ✓
· diff: template.js variable check, as in the fix ✓ · app: no _.template use`.

## Lockfile checks (Step 6)

In `git diff <prod-sha> -- <lockfile>`, every new or changed entry must:
- resolve from a registry host the production lockfile already uses, over `https`;
- carry an `sha512` integrity (npm, pnpm, Bun) or a checksum (Yarn Berry);
- come from no `git+`, `github:`, `http://`, tarball-URL, `file:` or `link:` source;
- add no new install-script marker (`hasInstallScript: true` in npm).

The lockfile's format version must also be unchanged. A failure points at a package-manager version mismatch or
a changed registry configuration: find the cause before going on.

## Verify a moved version (Step 6)

Some versions move without being targets: refreshes of transitive packages, a parent bump's subtree, and the
newest-in-range landings of Yarn and Bun. Give each of them:
- the registry record (section 2 above);
- the diff of its code files and its `package.json`, skipping tests, docs and source maps;
- a full read when a red flag fires, or when the version is younger than 72 h.

**A package new to the tree** has no installed version to diff against:
- An established package (created more than 90 days ago, with no install script): diff it against its previous
  published version (`npm view <pkg> versions --json`).
- A package created within 90 days, or a first release: needs a human. The event-stream incident arrived through
  a brand-new flatmap-stream.

Moved versions get the same verdicts, but the age exception is for fix targets only. A moved version that needs a
human is handled like a rejected one: re-resolve it to the previous clean version.
- With npm, when that version is newer than every target, restore the manifests and the lockfile from the
  production commit. Redo the Step 6 resolves with `--before=<newest target's publish time + 1 s>` on each
  command. No manifest changes: `npm update --before` alone never moves a locked version down.
- Otherwise use an exact override, as `package-managers.md` shows.

When no older version fits the ranges, defer the plan item that pulled it in.

## Malware

**A malware advisory on production** (`type: malware`, or npm's title `Malware in <pkg>`) means the installed
version is malicious.

- Never install the production tree: Step 5 skips the baseline.
- Choose the target as for any advisory, excluding every version a malware advisory covers. When no other
  advisory needs a later version, it is the last version published before the malicious one
  (`npm view <pkg> time --json`). Verify it like any target. The malicious version is usually unpublished
  (`npm view axios@1.14.1` gives E404), so diff the target against the clean version published before it.
- A direct dependency gets an exact pin, and a transitive one an exact override.
- When every version is malicious (a range of `>= 0`), never remove the package yourself, because code may
  depend on it. Report it at the top.
- Autonomy is revoked.
- Put this incident notice first in the report and in the PR:
  - Any machine that installed the version may be compromised: CI runners, developers' machines, the production
    build.
  - Rotate the secrets those machines could reach, from a clean machine.
  - Purge the package-manager and CI caches.
  - Review CI logs since the version entered the lockfile. Date that with `git log -S '<string>' -- <lockfile>`.
    The string is `/<name>/-/<basename>-<version>.tgz` for npm and Yarn Classic (`@scope/name/-/name-<version>.tgz`
    when scoped), `<name>@npm:<version>` for Yarn Berry, and `<name>@<version>` for pnpm and Bun.

**A target rejected for malware indicators** never reached production, so no rotation is needed. Tell the user,
and suggest reporting it to the maintainers and to npm (https://www.npmjs.com/support).

## What these checks do not prove

- Valid provenance is not proof of safety: a hijacked CI publishes with valid attestations. Its disappearance is
  a strong signal; its presence proves little.
- `npm audit signatures` detects tampering between the registry and you, not a hijacked maintainer.
- Disabled install scripts do not stop code that runs on import. Reading the diff and the 72-hour floor do.
- An LLM's reachability analysis is not proof. That is why it decides only between accepting and escalating a
  costly fix, and never skips a cheap one that the team has not accepted.
- Never approve install scripts (`npm approve-scripts`, `pnpm approve-builds`, `trustedDependencies`) on the
  user's behalf.
