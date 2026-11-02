# sec-patching-ts end-to-end eval

Runs `/devx-qa:sec-patching-ts` unattended (`claude -p`) on real and synthetic repositories, then grades what each
run left behind. `evals.json` beside this folder holds the four scenarios the synthetic cases are built from.

The cases (repositories, refs, expected decisions) are not in this repository. They live in a flow directory, by
default `.claude/hillclimb/sec-patching-ts/`, which `.gitignore` excludes:

| file | what |
|---|---|
| `cases.json` | each case: args, fixture, Bun version, package manager, lockfiles, expectations, oracle commands |
| `_state.json` | metrics, perf columns, prices, and the harness files the integrity gate digests |
| `grading.md`, `metrics.md` | every check and why |
| `fixtures/advisories.json` | advisory data frozen at fixture build, which risk lines are compared against |
| `baseline/`, `v<N>/` | `results.jsonl`, `errors.jsonl`, `traces/`, `grades/` per variant |

## How a case runs

1. **Fixture**, cached under `--work` (default `~/.cache/devx-evals/sec-patching-ts/fixtures/`): a bare copy of a
   local repository with only `main` (pinned to a sha) and the tags it reaches, pruned so later history is
   unreachable, or a synthetic npm app built by `lib/synthetic.mjs`.
2. **Run directory**, `<work>/runs/<flow>/<variant>/<case>_rep<k>/`: a fresh `origin.git` and a clone in `work/`, so the
   run is local-only. Canary secrets go in untracked `.npmrc` and `.env.local`.
3. **Session**: `claude -p "/devx-qa:sec-patching-ts <args>"` with the model and effort given, only this checkout's
   `plugins/qa` (`--plugin-dir`), the repository's project settings and none of the user's, the default
   permission mode with `--permission-prompts none` (a command outside the skill's `allowed-tools` is denied and
   counted), the Bun version the case's CI pins first on `PATH`, and a hard wall-clock ceiling that kills the
   session's process group.
4. **Grade** (`lib/grade.mjs`): guardrails from every Bash call and the canary; end state from git, the
   lockfiles and the manifests; the package manager's own sync check and audit rerun on a worktree; the report
   checked for risk lines, escalations, ready-to-paste acceptances and the PR body.

A finished session is never paid for twice: resuming grades its run directory again (`--rerun` forces a new
session). `--keep` keeps `node_modules` after grading.

## Commands

```bash
E=plugins/qa/skills/sec-patching-ts/evals
node $E/run-eval.mjs --approve-harness --fixtures-only     # after reviewing the harness: record its sha, build fixtures
node $E/run-eval.mjs --agent null   --flow .claude/hillclimb/sec-patching-ts-audit --cases .claude/hillclimb/sec-patching-ts/cases.json
node $E/run-eval.mjs --agent oracle --flow .claude/hillclimb/sec-patching-ts-audit --cases .claude/hillclimb/sec-patching-ts/cases.json
node $E/run-eval.mjs --variant baseline --only R3,T1,T3,N1  # the skill itself; defaults: claude-opus-5-5, xhigh
```

`--agent null` and `--agent oracle` grade a do-nothing run and the expected end state without any model call:
the null run must score 0 and the oracle 1 on every case, or the grader or a case is wrong.

Other flags: `--reps N`, `--concurrency N` (default 2), `--timeout-s N` (default 5400), `--max-budget-usd N` per
session (default 40), `--plugin-dir DIR`, `--work DIR`, `--rebuild-fixtures`.

Advisory data is live, so runs days apart can see different advisories. Compare variants run close together.
