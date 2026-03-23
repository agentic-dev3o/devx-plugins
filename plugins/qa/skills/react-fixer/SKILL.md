---
name: react-fixer
description: >-
  This skill should be used when the user asks to "fix react anti-patterns",
  "audit react code", "find useEffect misuse", "check react performance",
  "review react hooks", "scan for react issues", "clean up react components",
  "fix memory leaks in react", "check useEffect cleanup", "find stale closures",
  or wants to identify and fix common React anti-patterns in a codebase.
  Produces a scored gap analysis table with severity ratings and prioritized fixes.
---

# React Fixer

Audit React codebases for anti-patterns that degrade performance, cause memory leaks,
or reduce maintainability. Produce a gap analysis table and apply fixes.

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

For each confirmed finding, assign exactly one category from the rules in
`references/useeffect-patterns.md`, `references/component-patterns.md`, or
`references/cleanup-patterns.md`.

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

Common fix patterns — consult reference files for detailed before/after examples:

- **Derived state in useEffect** → Move to render-time `useMemo` or plain expression
- **setTimeout without cleanup** → Wrap in `useEffect` with `clearTimeout` in return
- **Inline map render logic** → Extract to a named component with props
- **window.location.href** → Replace with `useNavigate()` from React Router
- **Reactive state clearing** → Clear at the event source, not in a watching effect
- **useCallback+useEffect indirection** → Inline the logic in the effect with direct deps

### Step 5: Verify

Run lint (`bun run lint` or project-specific command) after applying fixes.
Confirm no regressions by checking that modified components still render correctly.

## Anti-Pattern Categories (Quick Reference)

Summary for classification. Authoritative rules with code examples live in the reference files.

### useEffect Rules

| Rule | Description |
|------|-------------|
| External sync only | Effects for I/O, timers, subscriptions — never for derived state |
| No mirror state | Never `useEffect(() => setState(transform(props)), [props])` |
| Cleanup required | Every timer, listener, or subscription needs a return cleanup |
| Minimal deps | Deps should be primitives or memoized refs; no inline objects |
| No reactive clearing | Do not clear state X by watching state Y in an effect |

### State Management

| Rule | Description |
|------|-------------|
| Derive during render | Compute values inline or with `useMemo`, not effect+setState |
| useMemo for expensive ops | Map/Set creation, filtering large arrays, complex computation |
| useCallback strategically | Only for callbacks passed to memoized children or as effect deps |
| No prop mirroring | Do not copy props into state unless editing a form (document why) |

### Component Architecture

| Rule | Description |
|------|-------------|
| Extract map callbacks | Complex `.map()` render logic → named child component |
| Single Responsibility | One concern per component; split God components |
| Stable event handlers | Use `useCallback` or ref pattern to avoid stale closures |

### Cleanup & Memory Safety

| Rule | Description |
|------|-------------|
| setTimeout/setInterval | Always `clearTimeout`/`clearInterval` in effect cleanup |
| AbortController | Use for raw `fetch()` calls; SDK-managed fetches are exempt |
| No stale closures | Include all read values in deps or use ref escape hatch |

### Navigation & DOM

| Rule | Description |
|------|-------------|
| Router navigation | Use `useNavigate()`, never `window.location.href` for SPA routes |
| DOM via refs | Imperative DOM access through `useRef`, not `document.querySelector` |

## Additional Resources

### Reference Files

Consult these for detailed rules, before/after examples, and edge cases:
- **`references/useeffect-patterns.md`** — Full useEffect rules with code examples
- **`references/component-patterns.md`** — Extraction, memoization, SRP patterns
- **`references/cleanup-patterns.md`** — Timer, listener, subscription cleanup

### Scripts

- **`scripts/scan-antipatterns.sh`** — Grep-based scanner for common anti-patterns

## Constraints

- Never add unrelated refactors alongside a fix
- Preserve existing code style and conventions
- Do not add comments, types, or docstrings to unchanged code
- If a suppressed lint rule has a valid comment explaining intent, respect it
- When in doubt about intent, flag the finding but do not auto-fix
