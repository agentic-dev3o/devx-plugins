---
name: fixing-react-antipatterns
description: >-
  Audits React codebases for anti-patterns (useEffect misuse, missing cleanup,
  stale closures, derived-state-in-effects, memory leaks) and produces a scored
  gap analysis table with severity ratings. Applies prioritized fixes on request.
  Triggers on: audit react code, fix react anti-patterns, review react hooks,
  scan for react issues, check useEffect cleanup, fix memory leaks in react.
---

# Fixing React Anti-Patterns

Target: `$ARGUMENTS` (path to scan, defaults to `src/`)

## Workflow

Progress checklist:

```
React Anti-Pattern Audit:
- [ ] Step 1: Scan for anti-patterns
- [ ] Step 2: Classify findings
- [ ] Step 3: Produce gap analysis table
- [ ] Step 4: Apply fixes (if requested)
- [ ] Step 5: Verify with lint
```

### Step 1: Scan for Anti-Patterns

Run `scripts/scan-antipatterns.sh` against the target directory to get a quick
inventory of suspect patterns. Then read flagged files to confirm true positives.

Use the Explore agent for deeper analysis when the script flags ambiguous cases.

### Step 2: Classify Findings

For each confirmed finding, assign exactly one category using the authoritative rules
and before/after examples in the reference files:
- [references/useeffect-patterns.md](references/useeffect-patterns.md) — effect misuse, derived state, deps
- [references/component-patterns.md](references/component-patterns.md) — extraction, memoization, SRP
- [references/cleanup-patterns.md](references/cleanup-patterns.md) — timers, listeners, subscriptions, navigation

Severity levels:
- **HIGH** — Memory leaks, infinite loops, data loss, security (e.g. uncleaned timers, stale closure causing wrong data)
- **MEDIUM** — Extra render cycles, obscured dependencies, poor readability (e.g. useEffect for derived state, inline map logic)
- **LOW** — Style or minor perf (e.g. inline arrow in static list, missing useCallback on trivial handler)

### Step 3: Produce Gap Analysis Table

Output a markdown table with these columns:

| Practice | Status | Severity | File:Line | Evidence |
|----------|--------|----------|-----------|----------|

Status values: **Respected**, **Violated**, **Partially respected**, **N/A**

Group rows by category:
1. useEffect rules
2. State management
3. Component architecture
4. Cleanup & memory safety
5. Navigation & DOM

End with a **Score summary** per category (X/10) and a **Top fixes** list ordered by impact.

### Step 4: Apply Fixes

When the user requests fixes, apply them in priority order. For each fix:

1. Read the file and surrounding context
2. Apply the minimal change — no over-engineering, no unrelated refactors
3. Preserve existing code style (semicolons, quotes, imports)

Consult the reference files for detailed before/after examples of each fix pattern.

### Step 5: Verify

Run lint (`bun run lint` or project-specific command) after applying fixes.
Confirm no regressions by checking that modified components still render correctly.

## Constraints

- Never add unrelated refactors alongside a fix
- Preserve existing code style and conventions
- Do not add comments, types, or docstrings to unchanged code
- If a suppressed lint rule has a valid comment explaining intent, respect it
- When in doubt about intent, flag the finding but do not auto-fix
