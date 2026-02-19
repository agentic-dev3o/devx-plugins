#!/usr/bin/env bash
# Automated test matrix for secrets-guard hook (guard.sh)
# Tests various tool inputs against the guard and asserts expected outcomes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$SCRIPT_DIR/hooks/guard.sh"

passed=0
failed=0
errors=()

# ── Helpers ──────────────────────────────────────────────────────────────────

run_guard() {
  local input="$1"
  printf '%s' "$input" | bash "$GUARD" 2>/dev/null
}

run_guard_exitcode() {
  local input="$1"
  printf '%s' "$input" | bash "$GUARD" 2>/dev/null
  return $?
}

make_read() {
  jq -nc --arg path "$1" '{"tool_name":"Read","tool_input":{"file_path":$path}}'
}

make_write() {
  jq -nc --arg path "$1" '{"tool_name":"Write","tool_input":{"file_path":$path}}'
}

make_edit() {
  jq -nc --arg path "$1" '{"tool_name":"Edit","tool_input":{"file_path":$path}}'
}

make_notebook() {
  jq -nc --arg path "$1" '{"tool_name":"NotebookEdit","tool_input":{"notebook_path":$path}}'
}

make_bash() {
  jq -nc --arg cmd "$1" '{"tool_name":"Bash","tool_input":{"command":$cmd}}'
}

make_glob() {
  jq -nc --arg pattern "$1" --arg path "$2" '{"tool_name":"Glob","tool_input":{"pattern":$pattern,"path":$path}}'
}

make_grep() {
  jq -nc --arg path "$1" --arg glob "$2" '{"tool_name":"Grep","tool_input":{"pattern":"search","path":$path,"glob":$glob}}'
}

assert_deny() {
  local label="$1"
  local input="$2"
  local output
  output="$(run_guard "$input")" || true

  local decision
  decision="$(printf '%s' "$output" | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null)" || true

  if [[ "$decision" == "deny" ]]; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    errors+=("FAIL [DENY expected]: $label — got: ${output:-<empty>}")
  fi
}

assert_allow() {
  local label="$1"
  local input="$2"
  local output
  output="$(run_guard "$input")" || true

  # Allow = empty output (exit 0 with no stdout)
  if [[ -z "$output" ]]; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    errors+=("FAIL [ALLOW expected]: $label — got: $output")
  fi
}

assert_deny_json_valid() {
  local label="$1"
  local input="$2"
  local output
  output="$(run_guard "$input")" || true

  # Check JSON structure has all required fields
  local has_event has_decision has_reason
  has_event="$(printf '%s' "$output" | jq -r '.hookSpecificOutput.hookEventName // empty' 2>/dev/null)" || true
  has_decision="$(printf '%s' "$output" | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null)" || true
  has_reason="$(printf '%s' "$output" | jq -r '.hookSpecificOutput.permissionDecisionReason // empty' 2>/dev/null)" || true

  if [[ "$has_event" == "PreToolUse" && "$has_decision" == "deny" && -n "$has_reason" ]]; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    errors+=("FAIL [valid deny JSON]: $label — got: ${output:-<empty>}")
  fi
}

# ── Test Matrix ──────────────────────────────────────────────────────────────

echo "secrets-guard test matrix"
echo "========================="
echo ""

# ── 1. Environment files (DENY) ─────────────────────────────────────────────
echo "--- Environment files ---"

assert_deny "Read .env" \
  "$(make_read "/app/.env")"

assert_deny "Read .env.local" \
  "$(make_read "/app/.env.local")"

assert_deny "Read .env.production" \
  "$(make_read "/app/.env.production")"

assert_deny "Read nested .env" \
  "$(make_read "/project/apps/web/.env")"

assert_deny "Write .env" \
  "$(make_write "/app/.env")"

assert_deny "Edit .env" \
  "$(make_edit "/app/.env")"

assert_deny "Read .flaskenv" \
  "$(make_read "/app/.flaskenv")"

# ── 2. Private keys & certificates (DENY) ───────────────────────────────────
echo "--- Private keys ---"

assert_deny "Read .pem file" \
  "$(make_read "/certs/server.pem")"

assert_deny "Read .key file" \
  "$(make_read "/ssl/private.key")"

assert_deny "Read .p12 file" \
  "$(make_read "/certs/cert.p12")"

assert_deny "Read id_rsa" \
  "$(make_read "/home/user/.ssh/id_rsa")"

assert_deny "Read id_ed25519" \
  "$(make_read "/home/user/.ssh/id_ed25519")"

# ── 3. SSH directory (DENY) ─────────────────────────────────────────────────
echo "--- SSH ---"

assert_deny "Read .ssh/config" \
  "$(make_read "/home/user/.ssh/config")"

assert_deny "Read .ssh/known_hosts" \
  "$(make_read "/home/user/.ssh/known_hosts")"

# ── 4. App secrets (DENY) ───────────────────────────────────────────────────
echo "--- App secrets ---"

assert_deny "Read credentials.json" \
  "$(make_read "/app/credentials.json")"

assert_deny "Read token.json" \
  "$(make_read "/app/token.json")"

assert_deny "Read secrets.yml" \
  "$(make_read "/app/secrets.yml")"

assert_deny "Read secrets.yaml" \
  "$(make_read "/app/secrets.yaml")"

assert_deny "Read master.key" \
  "$(make_read "/app/master.key")"

# ── 5. Cloud credentials (DENY) ─────────────────────────────────────────────
echo "--- Cloud credentials ---"

assert_deny "Read .aws/credentials" \
  "$(make_read "/home/user/.aws/credentials")"

assert_deny "Read .kube/config" \
  "$(make_read "/home/user/.kube/config")"

assert_deny "Read .docker/config.json" \
  "$(make_read "/home/user/.docker/config.json")"

# ── 6. Infrastructure (DENY) ────────────────────────────────────────────────
echo "--- Infrastructure ---"

assert_deny "Read .tfvars" \
  "$(make_read "/infra/prod.tfvars")"

assert_deny "Read terraform.tfstate" \
  "$(make_read "/infra/terraform.tfstate")"

# ── 7. Shell history (DENY) ─────────────────────────────────────────────────
echo "--- Shell history ---"

assert_deny "Read .bash_history" \
  "$(make_read "/home/user/.bash_history")"

assert_deny "Read .zsh_history" \
  "$(make_read "/home/user/.zsh_history")"

# ── 8. Bash commands referencing sensitive files (DENY) ─────────────────────
echo "--- Bash commands ---"

assert_deny "Bash cat .env" \
  "$(make_bash "cat /app/.env")"

assert_deny "Bash cat .pem" \
  "$(make_bash "cat /certs/server.pem")"

assert_deny "Bash source .env" \
  "$(make_bash "source .env.local")"

assert_deny "Bash grep in .aws/credentials" \
  "$(make_bash "grep key ~/.aws/credentials")"

assert_deny "Bash scp id_rsa" \
  "$(make_bash "scp user@host:~/.ssh/id_rsa .")"

# ── 9. Glob patterns (DENY) ─────────────────────────────────────────────────
echo "--- Glob patterns ---"

assert_deny "Glob for .env files" \
  "$(make_glob "**/.env" "/app")"

assert_deny "Glob path in .ssh" \
  "$(make_glob "*.pub" "/home/user/.ssh/")"

# ── 10. Grep patterns (DENY) ────────────────────────────────────────────────
echo "--- Grep patterns ---"

assert_deny "Grep in .env path" \
  "$(make_grep "/app/.env" "")"

assert_deny "Grep with .pem glob" \
  "$(make_grep "/app" "*.pem")"

# ── 11. NotebookEdit (DENY) ─────────────────────────────────────────────────
echo "--- Notebook ---"

assert_deny "NotebookEdit .env path" \
  "$(make_notebook "/app/.env.ipynb")"

# ── 12. Safe files (ALLOW) ──────────────────────────────────────────────────
echo "--- Safe files (should ALLOW) ---"

assert_allow "Read README.md" \
  "$(make_read "/app/README.md")"

assert_allow "Read package.json" \
  "$(make_read "/app/package.json")"

assert_allow "Read src/index.ts" \
  "$(make_read "/app/src/index.ts")"

assert_allow "Read .gitignore" \
  "$(make_read "/app/.gitignore")"

assert_allow "Write src/app.py" \
  "$(make_write "/app/src/app.py")"

assert_allow "Edit tsconfig.json" \
  "$(make_edit "/app/tsconfig.json")"

assert_allow "Bash ls" \
  "$(make_bash "ls -la /app")"

assert_allow "Bash git status" \
  "$(make_bash "git status")"

assert_allow "Bash npm install" \
  "$(make_bash "npm install express")"

assert_allow "Glob for ts files" \
  "$(make_glob "**/*.ts" "/app")"

assert_allow "Grep in src" \
  "$(make_grep "/app/src" "*.ts")"

assert_deny "Read .env.example (intentionally blocked)" \
  "$(make_read "/app/.env.example")"

# ── 13. JSON output validation (for deny cases) ─────────────────────────────
echo "--- JSON output validation ---"

assert_deny_json_valid "Deny JSON has required fields" \
  "$(make_read "/app/.env")"

assert_deny_json_valid "Deny JSON for .pem" \
  "$(make_read "/certs/server.pem")"

# ── 14. Edge cases ──────────────────────────────────────────────────────────
echo "--- Edge cases ---"

assert_allow "Read file named 'environment'" \
  "$(make_read "/app/environment")"

assert_allow "Read .envrc (not in patterns)" \
  "$(make_read "/app/.envrc")"

assert_deny "Read .secret file" \
  "$(make_read "/app/.secret")"

assert_deny "Read .secrets file" \
  "$(make_read "/app/.secrets")"

assert_allow "Unknown tool (should allow)" \
  '{"tool_name":"WebSearch","tool_input":{"query":"test"}}'

assert_allow "Empty file_path" \
  '{"tool_name":"Read","tool_input":{"file_path":""}}'

# ── Results ──────────────────────────────────────────────────────────────────
echo ""
echo "========================="
echo "Results: $passed passed, $failed failed"
echo ""

if [[ ${#errors[@]} -gt 0 ]]; then
  for err in "${errors[@]}"; do
    echo "  $err"
  done
  echo ""
  exit 1
fi

echo "All tests passed."
