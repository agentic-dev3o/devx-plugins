---
description: Sync CLAUDE.md with recent git changes
argument-hint: [scope: full|quick]
allowed-tools: Bash(git:*), Read, Grep, Glob, Write, Edit, AskUserQuestion
---

# CLAUDE.md Sync

Analyze project evolution since last CLAUDE.md update and propose lean, focused changes.

## Step 1: Validate Environment

Check git repository exists:
!`git rev-parse --git-dir 2>/dev/null && echo "GIT_OK" || echo "NOT_GIT"`

If NOT_GIT: Stop and inform user this command requires a git repository.

## Step 2: Locate Memory File

Find CLAUDE.md location:
!`test -f CLAUDE.md && echo "ROOT" || (test -f .claude/CLAUDE.md && echo "DOTCLAUDE" || echo "NONE")`

Set target path based on result:
- ROOT → `./CLAUDE.md`
- DOTCLAUDE → `./.claude/CLAUDE.md`
- NONE → Will create `./CLAUDE.md`

## Step 3: Get Change Window

Last CLAUDE.md modification:
!`git log -1 --format="%H %as" -- CLAUDE.md .claude/CLAUDE.md 2>/dev/null || echo "NEW"`

If result is "NEW" or empty: analyze last 30 commits.
Otherwise: get commits since that commit hash.

## Step 4: Gather Evolution Signals

Recent commits (scope: $1 or default "full"):
!`git log --oneline -30 --no-merges`

Changed files since last memory update:
!`git diff --stat $(git log -1 --format="%H" -- CLAUDE.md .claude/CLAUDE.md 2>/dev/null || echo "HEAD~30")..HEAD --name-only 2>/dev/null | head -50`

Read current CLAUDE.md if it exists.

Analyze for:
- **New patterns**: directories added, naming conventions changed
- **Stack changes**: deps added/removed (check package.json, Cargo.toml, etc.)
- **Architecture shifts**: new modules, restructured code
- **Workflow changes**: new scripts in package.json, CI updates

## Step 5: Propose Changes

Evaluate current CLAUDE.md against codebase state:

### Remove (if found):
- References to deleted files or renamed modules
- Outdated commands that no longer exist
- Verbose explanations (condense to bullets)
- Info duplicated from README or package.json

### Add (if missing):
- New conventions visible in recent commits
- New key commands or workflows
- Non-obvious patterns that would help Claude

### Keep (always):
- Project identity (1-2 sentences max)
- Active key commands
- Current conventions still in use

### Format constraints:
- Target: 40-60 lines
- Hard max: 80 lines
- Terse bullets over sentences
- Code paths as inline code

## Step 6: Present Diff & Confirm

Show proposed changes in diff format:

```
## Proposed Changes

- [removed item]
+ [added item]
~ [modified: old → new]
```

Use AskUserQuestion to confirm:
- Question: "Apply these changes to CLAUDE.md?"
- Header: "Confirm"
- Options:
  - Apply (Update CLAUDE.md with proposed changes)
  - Skip (Keep current CLAUDE.md unchanged)
  - Modify (Let me adjust before applying)

## Step 7: Apply Changes

If user confirms "Apply":
1. Apply changes using Edit tool (or Write if creating new)
2. Report: line count, key changes made
3. Suggest commit: `git add CLAUDE.md && git commit -m "docs(memory): sync CLAUDE.md with codebase"`

If user selects "Modify":
- Ask what to adjust
- Revise and re-present

If user selects "Skip":
- Exit without changes

## Edge Cases

**No CLAUDE.md exists**:
- Generate minimal template: project name, stack, 3 key commands
- Use AskUserQuestion to confirm creation

**No changes needed**:
- Report "CLAUDE.md is current with codebase"
- Show last update date

**Major refactor detected** (>50% of files changed):
- Warn user: "Significant codebase changes detected"
- Suggest full CLAUDE.md review rather than incremental update
