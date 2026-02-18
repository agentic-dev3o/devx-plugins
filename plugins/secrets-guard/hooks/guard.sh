#!/usr/bin/env bash
# secrets-guard: PreToolUse hook that blocks access to sensitive files.
# Reads tool invocation JSON from stdin, checks file paths and commands
# against patterns.txt, and denies access on match.
#
# Known limitation: Bash command checking uses string-pattern matching.
# It cannot detect obfuscated access via variable indirection, encoding,
# glob expansion, symlinks, or command substitution. This hook is a
# deterrent layer, not a sandbox.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATTERNS_FILE="$SCRIPT_DIR/../patterns.txt"

# Require jq for JSON parsing
if ! command -v jq &>/dev/null; then
  printf '{"decision":"block","reason":"secrets-guard: jq is required but not installed"}\n'
  exit 0
fi

# Fail-closed: if patterns file is missing, block for safety
if [[ ! -f "$PATTERNS_FILE" ]]; then
  printf '{"decision":"block","reason":"secrets-guard: patterns.txt not found — blocking for safety"}\n'
  exit 0
fi

# Read the hook input from stdin
input="$(cat)"

# Extract text to check in a single jq call (no eval, no subshell per field)
check_text="$(printf '%s' "$input" | jq -r '
  .tool_name as $t |
  if   $t == "Read" or $t == "Write" or $t == "Edit" then
    (.tool_input.file_path // "")
  elif $t == "NotebookEdit" then
    (.tool_input.notebook_path // "")
  elif $t == "Glob" then
    [(.tool_input.pattern // ""), (.tool_input.path // "")] | join("\n")
  elif $t == "Grep" then
    [(.tool_input.path // ""), (.tool_input.glob // "")] | join("\n")
  elif $t == "Bash" then
    (.tool_input.command // "")
  else
    empty
  end
')"

# Nothing to check — allow
if [[ -z "$check_text" ]]; then
  exit 0
fi

# Load patterns: strip comments and blank lines, join with |
regex="$(grep -vE '^\s*(#|$)' "$PATTERNS_FILE" | paste -sd '|' -)"

# No patterns loaded — allow
if [[ -z "$regex" ]]; then
  exit 0
fi

# Check for matches
matched_pattern="$(printf '%s\n' "$check_text" | grep -oE "$regex" | head -n1 || true)"

if [[ -n "$matched_pattern" ]]; then
  jq -nc --arg pattern "$matched_pattern" '{
    "decision": "block",
    "reason": "secrets-guard: access denied — matched sensitive pattern: " + $pattern
  }'
  exit 0
fi

# No match — allow
exit 0
