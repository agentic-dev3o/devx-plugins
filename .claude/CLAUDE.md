# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a Claude Code plugin marketplace containing multiple plugins. Each plugin provides slash commands, agents, and skills that extend Claude Code functionality.

## Architecture

```
devx-plugins/
├── .claude-plugin/
│   └── marketplace.json      # Plugin registry (lists all plugins)
└── plugins/
    ├── git/                   # devx-git plugin
    │   ├── .claude-plugin/
    │   │   └── plugin.json   # Plugin manifest
    │   └── commands/         # Slash commands
    │       ├── ci.md         # /commit - conventional commits
    │       └── pr.md         # /pr - create pull requests
    └── qa/                    # devx-qa plugin
        ├── .claude-plugin/
        │   └── plugin.json
        ├── commands/         # Slash commands
        ├── agents/           # Autonomous agents
        └── skills/           # Knowledge/skill definitions
```

## Plugin Structure

Each plugin follows this pattern:
- **`.claude-plugin/plugin.json`** - Required manifest with name, description, version, author
- **`commands/*.md`** - Slash commands (markdown with YAML frontmatter)
- **`agents/*.md`** - Agent definitions (optional)
- **`skills/`** - Skill definitions with SKILL.md and supporting files (optional)

## Command Development Guidelines

Commands are markdown files with YAML frontmatter. Key frontmatter fields:
- `description` - Brief text shown in `/help` (keep under 60 chars)
- `allowed-tools` - Scope tool access (e.g., `Bash(git:*)` not `Bash(*)`)
- `argument-hint` - Document expected arguments
- `model` - Use simple names: `haiku`, `sonnet`, `opus`

Commands are instructions FOR Claude, not messages TO users. Use imperative tone.

Inline bash execution uses `!` syntax: `!`git status``

## Adding a New Plugin

1. Create directory: `plugins/<plugin-name>/`
2. Create manifest: `plugins/<plugin-name>/.claude-plugin/plugin.json`
3. Add commands in `commands/` directory
4. Register in `.claude-plugin/marketplace.json` if publishing

## Current Plugins

| Plugin | Purpose | Commands |
|--------|---------|----------|
| devx-git | Git workflow automation | `/commit`, `/pr` |
| devx-qa | Code quality analysis | `/explain`, `/claudemd` |
