---
description: Analyze project architecture with ASCII state machine and sequence diagrams
argument-hint: [feature-or-entrypoint]
allowed-tools: Bash(tokei:*,find:*,wc:*,cat:*,head:*), Read, Grep, Glob
---

# Project Explain

Target: $ARGUMENTS

## Step 1: Analyze Project Composition

Run tokei for language statistics (fallback to file counting if unavailable):

!`tokei --output json 2>/dev/null || tokei 2>/dev/null || (echo "tokei not found, counting files:" && find . -type f \( -name "*.ts" -o -name "*.js" -o -name "*.py" -o -name "*.go" -o -name "*.rs" -o -name "*.java" \) 2>/dev/null | head -50 | xargs wc -l 2>/dev/null | tail -5)`

Detect package manifests and read the first one found:
- `package.json` for Node.js dependencies
- `Cargo.toml` for Rust
- `go.mod` for Go
- `pyproject.toml` / `requirements.txt` for Python
- `pom.xml` / `build.gradle` for Java

Identify framework from config files and directory structure patterns.

## Step 2: Find Entrypoint

If $ARGUMENTS is specified, locate that feature/module first.

If $ARGUMENTS is empty, search for main entrypoint in this order:
1. `main` field in package.json or Cargo.toml
2. Common files: `main.*`, `index.*`, `app.*`, `cmd/main.go`
3. Framework-specific: `pages/_app.tsx`, `src/main.rs`, `manage.py`

From the entrypoint, trace:
- Initialization sequence
- Configuration loading
- Service bootstrapping
- Main event loop or request handler

## Step 3: Build State Machine Graph

Analyze the target feature for:
- State variables and possible values
- Transition triggers (events, conditions)
- Guards and side effects
- Terminal states

Generate an ASCII acyclic graph using box-drawing characters:

```
┌───────────┐
│   STATE   │
└─────┬─────┘
      │ event
      ▼
┌───────────┐
│ NEXT_STATE│
└───────────┘
```

Use: ─ │ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼ ► ◄ ▲ ▼

## Step 4: Generate Sequence Diagram

Identify actors:
- Client/User
- Controllers/Handlers
- Services/Business Logic
- Data Access Layer
- External APIs

Generate ASCII sequence diagram showing control flow:

```
┌──────┐     ┌─────────┐
│Actor1│     │ Actor2  │
└──┬───┘     └────┬────┘
   │   message    │
   │─────────────►│
   │◄─────────────│
```

## Step 5: Output Synthesis

Present findings in this structure:

**1. Project Overview**
```
╔════════════════════════════════════════╗
║ PROJECT: <name>                        ║
╠════════════════════════════════════════╣
║ Language: <primary>                    ║
║ Framework: <detected>                  ║
║ Type: <CLI/API/Web/Library>            ║
╚════════════════════════════════════════╝
```

**2. Stack Summary**
List: language, framework, major libraries, build tools, test framework

**3. State Machine Diagram**
The acyclic graph from Step 3

**4. Sequence Diagram**
Control flow diagram from Step 4

**5. Key Files**
```
entrypoint:  <path>
config:      <path>
controller:  <path>
service:     <path>
```

## Constraints

- All diagrams in ASCII only (no mermaid)
- Max 80 chars wide for diagrams
- Focus on specified feature path for large projects
- Gracefully handle missing tools (tokei)
