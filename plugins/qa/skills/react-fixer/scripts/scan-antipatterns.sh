#!/usr/bin/env bash
# scan-antipatterns.sh — Quick grep-based scanner for common React anti-patterns
# Usage: ./scan-antipatterns.sh [target_dir]
#
# Outputs flagged files with line numbers grouped by anti-pattern category.
# False positives are expected — use this as a starting point for manual review.

set -uo pipefail

TARGET="${1:-.}"
SEP="────────────────────────────────────────"

rgsearch() {
  rg "$@" --glob '*.ts' --glob '*.tsx' --glob '*.jsx' --glob '*.js' 2>/dev/null
}

echo "React Anti-Pattern Scanner"
echo "Target: $TARGET"
echo "$SEP"

# --- useEffect Anti-Patterns ---

echo ""
echo "## useEffect setting state from props/state (derived state)"
echo ""
rgsearch -n 'useEffect' "$TARGET" -l | while read -r file; do
  rg -n 'useEffect' "$file" -A 5 2>/dev/null | rg 'set[A-Z]\w*\(' 2>/dev/null | head -20
done
echo ""

echo "## useEffect with biome-ignore / eslint-disable for deps"
echo ""
rgsearch -n 'biome-ignore.*useExhaustiveDependencies|eslint-disable.*exhaustive-deps' "$TARGET" || echo "(none found)"
echo ""

echo "## useEffect -> useCallback -> useEffect indirection"
echo ""
rgsearch -n 'useEffect' "$TARGET" -l | while read -r file; do
  rg -n 'useEffect\(' "$file" -A 3 2>/dev/null | rg -o '\[([a-zA-Z_]\w*)\]' 2>/dev/null | tr -d '[]' | sort -u | while read -r dep; do
    if [ -n "$dep" ] && rg -q "const $dep = useCallback" "$file" 2>/dev/null; then
      echo "  $file: useEffect depends on useCallback '$dep'"
    fi
  done
done
echo ""

# --- Cleanup Anti-Patterns ---

echo "## setTimeout without cleanup"
echo ""
rgsearch -n 'setTimeout' "$TARGET" | rg -v 'clearTimeout|return.*clear|useEffect|\.test\.|\.spec\.' 2>/dev/null || echo "(none found)"
echo ""

echo "## setInterval without cleanup"
echo ""
rgsearch -n 'setInterval' "$TARGET" | rg -v 'clearInterval|return.*clear' 2>/dev/null || echo "(none found)"
echo ""

echo "## addEventListener without removeEventListener"
echo ""
rgsearch -n 'addEventListener' "$TARGET" | rg -v 'removeEventListener' 2>/dev/null || echo "(none found)"
echo ""

# --- Navigation Anti-Patterns ---

echo "## window.location.href (should use router navigate)"
echo ""
rgsearch -n 'window\.location\.(href|assign|replace)' "$TARGET" || echo "(none found)"
echo ""

# --- Component Anti-Patterns ---

echo "## Files with multiple .map() callbacks (review for extraction)"
echo ""
rgsearch -n '\.map\(\s*\(' "$TARGET" -c | while IFS=: read -r file count; do
  if [ "$count" -gt 2 ]; then
    echo "  $file — $count map callbacks"
  fi
done
echo ""

echo "## Inline functions in JSX onClick/onChange (high count per file)"
echo ""
rgsearch -n 'on(Click|Change|Submit)=\{?\(\)' "$TARGET" -c | while IFS=: read -r file count; do
  if [ "$count" -gt 5 ]; then
    echo "  $file — $count inline handlers"
  fi
done
echo ""

# --- State Anti-Patterns ---

echo "## useState initialized from props (potential mirror state)"
echo ""
rgsearch -n 'useState\(\s*(props\.|{.*}|[a-z]+\??\.)' "$TARGET" | head -20
echo ""

echo "## Clipboard API without error handling"
echo ""
rgsearch -n 'navigator\.clipboard' "$TARGET" | rg -v 'try|catch|\.then.*\.catch' 2>/dev/null || echo "(none found)"
echo ""

echo "$SEP"
echo "Scan complete. Review flagged files for true positives."
