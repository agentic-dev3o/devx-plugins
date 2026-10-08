# Analyzers

Run each analyzer from the repository root unless noted. Write its report inside `.dead-code/`, which git ignores, then import it with `ledger.py import`. Never write a report to the repository root: knip, for one, reads a `knip.json` there as its own configuration.

`npx -y`, `uvx` and `go run ...@latest` run a tool without adding it to the project. Never add a dependency or a configuration file to the project to make an analyzer run without asking the user first.

## Contents

- Choosing what to run
- JavaScript and TypeScript: knip
- Python: vulture
- Go: deadcode and staticcheck
- Rust: rustc
- PHP: PHPStan with shipmonk dead-code-detector
- Ruby: debride
- Java, Kotlin and C#: SARIF
- Anything else: scanners or TSV
- Unused dependencies

## Choosing what to run

For each language with source files in scope, run its analyzer when it works here. Cover the languages without one with the scanners: `ledger.py shard --ext <ext>`. Running both on one language is fine, because the ledger merges duplicate candidates. Prefer analyzers: they follow the real call graph, take seconds, and cost no tokens.

## JavaScript and TypeScript: knip

```bash
npx -y knip@6 --reporter json --no-progress > .dead-code/knip.json
ledger.py import --tool knip .dead-code/knip.json
```

- When knip is already in `devDependencies`, run the project's own version (`npx knip ...`), which picks up the project's knip configuration.
- Exit code 1 means it found issues; 2 means it failed. Read stderr: a configuration error usually means a framework plugin needs a config file. Do not create one without asking; scan those files instead.
- Monorepos: knip reads the workspaces itself. Limit it to one package with `--workspace <dir>`.
- It reports unused files, exports, types, enum and namespace members, and dependencies. Since version 6 it no longer reports class members: add scanners (`--ext ts --ext tsx`) when unused methods matter.
- Blind spots: computed `import()`, CommonJS `module.fn()` access, and `.vue` or `.svelte` files without their compiler installed. The dynamic lens covers them.
- Never run `knip --fix`: removals go through the verifiers and the gate.

## Python: vulture

```bash
uvx vulture <source directories, without the tests> --min-confidence 60 > .dead-code/vulture.txt
ledger.py import --tool vulture .dead-code/vulture.txt
```

- Leave the test directories out. Vulture then reports code that only tests use, and the reference count files it as test-only instead of deleting it.
- Pass the project's whitelist file along when it has one (`whitelist.py`, `vulture_whitelist.py`).
- Exit code 3 means it found dead code. The import drops unused imports and arguments: the project's linter fixes those (`ruff check --select F401,F841 --fix`).
- Blind spots: `getattr` access, decorators that register functions, and Django or Flask conventions. The lenses cover them.

## Go: deadcode and staticcheck

```bash
go run golang.org/x/tools/cmd/deadcode@latest -test -json ./... > .dead-code/deadcode.json
go run honnef.co/go/tools/cmd/staticcheck@latest -checks U1000 -f json ./... > .dead-code/staticcheck.jsonl
ledger.py import --tool deadcode .dead-code/deadcode.json
ledger.py import --tool staticcheck .dead-code/staticcheck.jsonl
```

- deadcode follows calls from the `main` packages and exits 0 even when it finds dead code. In a library without a `main` package it stops with `no main packages`; use staticcheck alone there.
- staticcheck U1000 reports unexported identifiers only, because exported ones always count as used.
- Both analyze one GOOS, GOARCH and build-tag combination, so code behind other tags looks dead to them. The boundary lens checks build tags.

## Rust: rustc

```bash
cargo check --workspace --all-targets --message-format=json > .dead-code/cargo.jsonl
ledger.py import --tool cargo .dead-code/cargo.jsonl
```

- The import keeps `dead_code` warnings only. `cargo clippy --fix` handles the other `unused_*` lints.
- rustc never reports a library's `pub` items. To catch unused `pub` items across a workspace, scan as well (`ledger.py shard --ext rs`) and let the reference count decide.
- Messages repeat once per target; the import deduplicates them.

## PHP: PHPStan with shipmonk dead-code-detector

Only when `shipmonk/dead-code-detector` is already in `composer.json`:

```bash
vendor/bin/phpstan analyse --error-format=json --no-progress > .dead-code/phpstan.json
ledger.py import --tool phpstan .dead-code/phpstan.json
```

- The import keeps the `shipmonk.dead*` errors: methods, constants, enum cases and properties. The detector understands Symfony, Laravel, Doctrine, PHPUnit and Twig.
- Without it, scan: `ledger.py shard --ext php`.

## Ruby: debride

Only when `debride` is installed:

```bash
debride --json lib app > .dead-code/debride.json
ledger.py import --tool debride .dead-code/debride.json
```

- It matches method names only and always exits 0. Rails callbacks and `send` are its blind spots; the dynamic lens covers them.
- Without it, scan: `ledger.py shard --ext rb`.

## Java, Kotlin and C#: SARIF

When the project already runs one of these tools, have it write SARIF into `.dead-code/` and import it, keeping the dead-code rules:

- PMD: `pmd check -d src/main/java -R category/java/bestpractices.xml/UnusedPrivateMethod,category/java/bestpractices.xml/UnusedPrivateField -f sarif -r .dead-code/pmd.sarif --no-progress`
- detekt: add `-r sarif:.dead-code/detekt.sarif`; the rules are UnusedPrivateClass, UnusedPrivateMember and UnusedPrivateProperty.
- .NET: `dotnet build -p:EnforceCodeStyleInBuild=true "-p:ErrorLog=.dead-code/dotnet.sarif%2Cversion=2.1"` reports IDE0051 and IDE0052 once `.editorconfig` raises them to warnings.

```bash
ledger.py import --tool sarif .dead-code/pmd.sarif --rule UnusedPrivateMethod --rule UnusedPrivateField
```

- These tools see private members only. Scan as well (`--ext java --ext kt --ext cs`) to cover public declarations.
- Spring, Jakarta, Jackson, Lombok and DI annotations reach code through reflection. The dynamic lens checks them; never shortcut it for annotated code.

## Anything else: scanners or TSV

- Swift, Dart, Elixir, Scala, C, C++, Lua and the rest: `ledger.py shard --ext <ext>`.
- Any other tool that prints a file, a line and a name: convert its output to tab-separated lines `file	line	symbol	kind	detail`, where `kind` is one of `file`, `export`, `function`, `method`, `class`, `type`, `variable`, `member` or `dependency`, and run `ledger.py import --tool tsv <file> --source <tool name>`.

## Unused dependencies

knip reports unused packages itself, and the report lists them for the user; no agent removes a dependency. For other ecosystems, add them as `dependency` lines through TSV, with the manifest as the file:

- Python: `uvx deptry . --json-output .dead-code/deptry.json`, run inside the project's environment; DEP002 means unused.
- Rust: `cargo machete --with-metadata`.
- PHP: `composer-unused`.
