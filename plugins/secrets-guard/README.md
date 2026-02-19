# secrets-guard

PreToolUse hook that blocks Claude from reading, writing, or accessing sensitive files.

## Installation

```
/plugin install secrets-guard@devx-plugins
```

**Requires:** `jq` (available in all major package managers).

## What it guards

- Environment files (`.env`, `.env.local`, `.flaskenv`)
- Private keys & certificates (`.pem`, `.key`, SSH keys)
- Cloud credentials (`.aws/credentials`, `.kube/config`, `.config/gcloud/`)
- App secrets (`credentials.json`, `secrets.yml`, `master.key`)
- Shell history (`.bash_history`, `.zsh_history`)
- And [70+ more patterns](patterns.txt)

## How it works

The hook intercepts every `Read`, `Write`, `Edit`, `NotebookEdit`, `Bash`, `Glob`, and `Grep` call. File paths and commands are matched against a regex pattern list. On match, the tool call is blocked before execution.

## Known limitation

Bash command checking uses string-pattern matching. It cannot detect obfuscated access via variable indirection, encoding, glob expansion, symlinks, or command substitution. This hook is a **deterrent layer**, not a sandbox.

For process-level isolation, see [sandbox-shell](https://github.com/agentic-dev3o/sandbox-shell) — a sandboxed shell (macOS only) that restricts what Claude Code can execute at the OS level.
