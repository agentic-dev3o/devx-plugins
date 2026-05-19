# Settings Recipes

Drop-in `.claude/settings.json` patterns by stack. Always combine `allow` with `deny` — `allow` without `deny` is an open door, and `deny` always wins (even in `bypassPermissions` mode).

## Contents

- Minimum Viable `deny`
- Stack recipes: Node / bun, Python (uv / poetry), Rust (cargo), Go
- MCP Scoping
- Pattern Reminders (wildcard syntax)
- `.claude/settings.local.json` Is Personal
- Permission Mode (`dontAsk`)
- Sandbox (macOS / Linux)

## Minimum Viable `deny`

Every project should deny at least these:

```json
{
  "permissions": {
    "deny": [
      "Bash(git push:*)",
      "Bash(git push)",
      "Bash(rm -rf:*)",
      "Bash(rm -rf *)",
      "Bash(sudo:*)",
      "Read(./.env)",
      "Read(./.env.*)",
      "Read(**/credentials*)",
      "Read(**/secrets/**)"
    ]
  }
}
```

## Node / TypeScript (bun)

```json
{
  "permissions": {
    "allow": [
      "Bash(bun:*)",
      "Bash(bunx:*)",
      "Bash(npm run lint)",
      "Bash(npm test)",
      "Bash(git status:*)",
      "Bash(git diff:*)",
      "Bash(git log:*)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Bash(gh pr:*)",
      "Bash(gh issue:*)"
    ],
    "deny": [
      "Bash(bun publish:*)",
      "Bash(npm publish:*)",
      "Bash(git push:*)",
      "Bash(rm -rf:*)",
      "Read(./.env)",
      "Read(./.env.*)"
    ]
  }
}
```

## Python (uv / poetry)

```json
{
  "permissions": {
    "allow": [
      "Bash(uv:*)",
      "Bash(poetry:*)",
      "Bash(pytest:*)",
      "Bash(ruff:*)",
      "Bash(mypy:*)",
      "Bash(git status:*)",
      "Bash(git diff:*)",
      "Bash(git commit:*)"
    ],
    "deny": [
      "Bash(uv publish:*)",
      "Bash(poetry publish:*)",
      "Bash(twine upload:*)",
      "Bash(git push:*)",
      "Bash(rm -rf:*)",
      "Read(./.env)",
      "Read(**/credentials*)"
    ]
  }
}
```

## Rust (cargo)

```json
{
  "permissions": {
    "allow": [
      "Bash(cargo:*)",
      "Bash(rustfmt:*)",
      "Bash(git status:*)",
      "Bash(git diff:*)",
      "Bash(git commit:*)"
    ],
    "deny": [
      "Bash(cargo publish:*)",
      "Bash(git push:*)",
      "Bash(rm -rf:*)",
      "Read(./.env)"
    ]
  }
}
```

## Go

```json
{
  "permissions": {
    "allow": [
      "Bash(go:*)",
      "Bash(gofmt:*)",
      "Bash(golangci-lint:*)",
      "Bash(git status:*)",
      "Bash(git diff:*)",
      "Bash(git commit:*)"
    ],
    "deny": [
      "Bash(git push:*)",
      "Bash(rm -rf:*)",
      "Read(./.env)"
    ]
  }
}
```

## MCP Scoping

Prefer specific tools over server wildcards:

```json
{
  "permissions": {
    "allow": [
      "mcp__playwright__browser_navigate",
      "mcp__playwright__browser_snapshot",
      "mcp__playwright__browser_console_messages",
      "mcp__convex__status",
      "mcp__convex__runOneoffQuery"
    ]
  }
}
```

Allow broad `mcp__server__*` only after running the workflow once and confirming the server's full tool surface is acceptable.

## Pattern Reminders

| Pattern | Matches | Note |
|---------|---------|------|
| `Bash(bun *)` | `bun test`, `bun run lint` | Space before `*` = word boundary |
| `Bash(bun*)` | `bun test`, `bunx` | No space = prefix match (looser) |
| `Bash(git commit *)` | `git commit -m "..."` | Scoped to one subcommand |
| `mcp__playwright__*` | All Playwright MCP tools | Server-level wildcard |
| `WebFetch(domain:docs.x.com)` | Fetch from one host | Domain-scoped |
| `Read(./.env.*)` | `.env.local`, `.env.prod` | Single-segment glob |
| `Read(**/secrets/**)` | Any path containing `secrets/` | Recursive glob |

## `.claude/settings.local.json` Is Personal

Never commit. Use it for:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "permissions": {
    "allow": [
      "WebFetch(domain:internal.mycorp.com)",
      "Bash(my-personal-script:*)"
    ]
  }
}
```

Required `.gitignore` entries:

```
.claude/*.local.*
CLAUDE.local.md
```

## Permission Mode

After the allowlist is mature, switch to `dontAsk` so the agent stops prompting for anything not explicitly approved:

```json
{
  "permissions": {
    "defaultMode": "dontAsk"
  }
}
```

`dontAsk` + complete allowlist + deny rules = a fully autonomous agent within declared boundaries. Until the allowlist is stable, leave it at `default`.

## Sandbox (macOS / Linux)

For long autonomous loops, enable the OS-level sandbox:

```json
{
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "network": {
      "allowLocalBinding": true,
      "allowUnixSockets": ["~/.gnupg/S.gpg-agent"]
    }
  }
}
```

The sandbox protects against Claude making mistakes during agentic flows. It does **not** protect against malicious code (npm postinstall, supply chain) — use dev containers for that threat model.
