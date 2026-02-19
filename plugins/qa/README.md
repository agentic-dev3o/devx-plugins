# devx-qa

Code quality tools for understanding and maintaining projects.

## Installation

```
/plugin install devx-qa@devx-plugins
```

## Commands

### `/devx-qa:explain [feature]`

Architecture analysis with ASCII diagrams. No external dependencies.

```
/devx-qa:explain
/devx-qa:explain auth-flow
```

**What happens:**
1. Detects your stack (language, framework, tools)
2. Finds the entrypoint for the feature you specify
3. Generates ASCII state machine diagram
4. Generates ASCII sequence diagram
5. Lists key files with their roles

**Output:**
```
┌─────────────┐    success    ┌──────────────┐
│  PENDING    │──────────────►│  AUTHORIZED  │
└─────────────┘               └──────────────┘
       │                             │
       │ failure                     │ logout
       ▼                             ▼
┌─────────────┐               ┌──────────────┐
│   FAILED    │               │   EXPIRED    │
└─────────────┘               └──────────────┘
```

No mermaid. No external tools. Just ASCII that works everywhere.

---

### `/devx-qa:claudemd [full|quick]`

Keep your CLAUDE.md in sync with codebase evolution.

```
/devx-qa:claudemd
/devx-qa:claudemd quick
```

**What happens:**
1. Finds your CLAUDE.md (or creates one)
2. Analyzes commits since last update
3. Detects new patterns, stack changes, architecture shifts
4. Proposes additions and removals in diff format
5. Asks for confirmation before applying

Your project memory stays current without manual maintenance.
