# Analyzers

Run every analyzer through the ledger: `ledger.py analyze --tool <tool> [--base <dir>] [--output <file>] -- <command>`. The ledger runs the command without a shell, keeps the report in `.dead-code/analyzers/`, imports it, and records the command so `ledger.py analyze --again` repeats it in later rounds. `--base` is the directory the command runs in, relative to the repository root; the ledger reads the report's paths relative to it. `--output` names the file a tool writes its report to, when it does not print it.

`npx -y`, `uvx` and `go run ...@latest` run a tool without adding it to the project. Never add a dependency or a configuration file to the project to make an analyzer run without asking the user first. When a finding names a file that does not exist, `analyze` says so: re-run with the right `--base`.

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
ledger.py analyze --tool knip -- npx -y knip@6 --reporter json --no-progress
```

- When knip is already in `devDependencies`, run the project's own version (`-- npx knip --reporter json --no-progress`), which picks up the project's knip configuration.
- Exit code 1 means it found issues; 2 means it failed, and `analyze` prints its stderr. A configuration error usually means a framework plugin needs a config file. Do not create one without asking; scan those files instead.
- Monorepos: knip reads the workspaces itself and reports paths from the root. Limit it to one package with `--workspace <dir>`.
- It reports unused files, exports, types, enum and namespace members, and dependencies. Since version 6 it no longer reports class members: add scanners (`--ext ts --ext tsx`) when unused methods matter.
- Blind spots: computed `import()`, CommonJS `module.fn()` access, and `.vue` or `.svelte` files without their compiler installed. The dynamic lens covers them.
- Never run `knip --fix`: removals go through the verifiers and the gate.

## Python: vulture

```bash
ledger.py analyze --tool vulture -- uvx vulture <source directories, without the tests> --min-confidence 60
```

- Leave the test directories out. Vulture then reports code that only tests use, and the reference count files it as test-only instead of deleting it.
- Pass the project's whitelist file along when it has one (`whitelist.py`, `vulture_whitelist.py`).
- Exit code 3 means it found dead code. The import drops unused imports and arguments: the project's linter fixes those (`ruff check --select F401,F841 --fix`).
- Blind spots: `getattr` access, decorators that register functions, and Django or Flask conventions. The lenses cover them.

## Go: deadcode and staticcheck

```bash
ledger.py analyze --tool deadcode -- go run golang.org/x/tools/cmd/deadcode@latest -test -json ./...
ledger.py analyze --tool staticcheck -- go run honnef.co/go/tools/cmd/staticcheck@latest -checks U1000 -f json ./...
```

- In a repository whose `go.mod` sits in a subdirectory, add `--base <that directory>`.
- deadcode follows calls from the `main` packages and exits 0 even when it finds dead code. In a library without a `main` package it stops with `no main packages`; use staticcheck alone there.
- staticcheck U1000 reports unexported identifiers only, because exported ones always count as used.
- Both analyze one GOOS, GOARCH and build-tag combination, so code behind other tags looks dead to them. The boundary lens checks build tags.

## Rust: rustc

```bash
ledger.py analyze --tool cargo -- cargo check --workspace --all-targets --message-format=json
```

- rustc reports paths relative to the workspace root: when the workspace is in a subdirectory, add `--base <that directory>`.
- The import keeps `dead_code` warnings only, including groups such as `multiple methods are never used`. `cargo clippy --fix` handles the other `unused_*` lints.
- rustc never reports a library's `pub` items. To catch unused `pub` items across a workspace, scan as well (`ledger.py shard --ext rs`) and let the reference count decide.

## PHP: PHPStan with shipmonk dead-code-detector

Only when `shipmonk/dead-code-detector` is already in `composer.json`:

```bash
ledger.py analyze --tool phpstan -- vendor/bin/phpstan analyse --error-format=json --no-progress
```

- The import keeps the `shipmonk.dead*` errors: methods, constants, enum cases and properties. The detector understands Symfony, Laravel, Doctrine, PHPUnit and Twig.
- Without it, scan: `ledger.py shard --ext php`.

## Ruby: debride

Only when `debride` is installed:

```bash
ledger.py analyze --tool debride -- debride --json lib app
```

- It matches method names only and always exits 0. Rails callbacks and `send` are its blind spots; the dynamic lens covers them.
- Without it, scan: `ledger.py shard --ext rb`.

## Java, Kotlin and C#: SARIF

When the project already runs one of these tools, import its SARIF log and keep the dead-code rules:

Java, with PMD:

```bash
ledger.py analyze --tool sarif --output .dead-code/pmd.sarif --rule UnusedPrivateMethod --rule UnusedPrivateField -- pmd check -d src/main/java -R category/java/bestpractices.xml/UnusedPrivateMethod,category/java/bestpractices.xml/UnusedPrivateField -f sarif -r .dead-code/pmd.sarif --no-progress
```

Kotlin, with the detekt command-line tool (`detekt` or `detekt-cli`):

```bash
ledger.py analyze --tool sarif --output .dead-code/detekt.sarif --rule UnusedPrivateClass --rule UnusedPrivateMember --rule UnusedPrivateProperty -- detekt --input src/main/kotlin --build-upon-default-config --report sarif:.dead-code/detekt.sarif
```

C#, only when the repository's `.editorconfig` already raises IDE0051 and IDE0052 to warnings (`dotnet_diagnostic.IDE0051.severity = warning`); otherwise scan. Give both paths absolute, because MSBuild resolves `ErrorLog` relative to each project:

```bash
ledger.py analyze --tool sarif --output <root>/.dead-code/dotnet.sarif --rule IDE0051 --rule IDE0052 -- dotnet build -p:EnforceCodeStyleInBuild=true "-p:ErrorLog=<root>/.dead-code/dotnet.sarif%2Cversion=2.1"
```

- Each tool signals findings its own way (PMD exits 4, detekt 2), and `analyze` knows which exit codes still mean a complete report. A dotnet build that fails leaves an incomplete log, so it counts as a failure.
- With a solution of several projects, every project overwrites the same `ErrorLog`: build them one at a time, with a different report name for each.
- The import decodes `file:` URIs and resolves `uriBaseId`, so paths with spaces or accents land on the right file.
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
