---
name: explaining-architecture
description: Analyzes project architecture and generates ASCII state machine and sequence diagrams. Use when the user asks to explain a project, analyze architecture, trace an entrypoint, show a state machine, or generate a sequence diagram.
---

# Project Explain

Analyze project architecture and produce ASCII state machine and sequence diagrams for a given codebase or feature.

Target: `$ARGUMENTS`

## Workflow

Copy this checklist and track progress:

```
Architecture Analysis:
- [ ] Step 1: Analyze project composition
- [ ] Step 2: Find entrypoint
- [ ] Step 3: Build state machine graph
- [ ] Step 4: Generate sequence diagram
- [ ] Step 5: Output synthesis
```

### Step 1: Analyze Project Composition

Run language statistics: `tokei || echo 'not installed'`

If tokei is unavailable, use Glob to count files by extension and estimate composition.

Detect and read the first package manifest found (`package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`, `requirements.txt`, `pom.xml`, `build.gradle`). Identify framework from config files and directory structure.

### Step 2: Find Entrypoint

If `$ARGUMENTS` is specified, locate that feature or module first.

Otherwise search for the main entrypoint: `main` field in manifest, common files (`main.*`, `index.*`, `app.*`, `cmd/main.go`), or framework-specific entries (`pages/_app.tsx`, `src/main.rs`, `manage.py`).

From the entrypoint, trace initialization, configuration loading, service bootstrapping, and main event loop or request handler.

### Step 3: Build State Machine Graph

Analyze the target for state variables, transition triggers, guards, side effects, and terminal states. Generate an ASCII acyclic graph using box-drawing characters (`─ │ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼ ► ◄ ▲ ▼`). Max 80 chars wide.

### Step 4: Generate Sequence Diagram

Identify actors (client, controllers, services, data layer, external APIs). Generate an ASCII sequence diagram showing control flow between them. Max 80 chars wide.

### Step 5: Output Synthesis

Present findings using this template:

```
╔════════════════════════════════════════╗
║ PROJECT: <name>                        ║
╠════════════════════════════════════════╣
║ Language: <primary>                    ║
║ Framework: <detected>                  ║
║ Type: <CLI/API/Web/Library>            ║
╚════════════════════════════════════════╝
```

Then include in order:
1. **Stack Summary** — language, framework, major libraries, build tools, test framework
2. **State Machine Diagram** — acyclic graph from Step 3
3. **Sequence Diagram** — control flow from Step 4
4. **Key Files** — entrypoint, config, controller, service paths

## Constraints

- ASCII diagrams only (no mermaid), max 80 chars wide
- Focus on specified feature path for large projects
