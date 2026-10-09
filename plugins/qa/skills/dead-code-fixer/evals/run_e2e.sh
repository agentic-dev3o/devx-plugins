#!/usr/bin/env bash
# Run /devx-qa:dead-code-fixer end to end on one fixture, in a nested headless Claude Code session.
#
# Usage: run_e2e.sh <label> <fixture> [skill arguments...]
#   EVAL_DIR   where fixtures and runs live (default /tmp/dc-eval); build the fixtures first:
#              python3 build_fixtures.py "$EVAL_DIR/fixtures"
#   PLUGIN_DIR the plugin to test (default: this checkout's plugins/qa)
#   MODEL      the orchestrating model (default opus)
# The run happens in a throwaway copy; grade it with: python3 grade_e2e.py "$EVAL_DIR" <label>
set -uo pipefail
label=$1; fixture=$2; shift 2
here=$(cd "$(dirname "$0")" && pwd)
base=${EVAL_DIR:-/tmp/dc-eval}
plugin=${PLUGIN_DIR:-$(cd "$here/../../.." && pwd)}
run="$base/runs/$label/$fixture"
rm -rf "$run"
mkdir -p "$(dirname "$run")"
cp -a "$base/fixtures/$fixture" "$run"
cd "$run" || exit 2
start=$(date +%s)
# The installed copy of devx-qa is disabled so the session loads only the plugin under test.
CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 timeout 5400 claude -p \
  --plugin-dir "$plugin" \
  --settings '{"enabledPlugins":{"devx-qa@devx-plugins":false}}' \
  --model "${MODEL:-opus}" \
  --permission-mode bypassPermissions \
  --output-format stream-json --verbose \
  "/devx-qa:dead-code-fixer $*" \
  > "$base/runs/$label/$fixture.jsonl" 2> "$base/runs/$label/$fixture.err"
code=$?
echo "{\"fixture\": \"$fixture\", \"exit\": $code, \"seconds\": $(( $(date +%s) - start ))}" > "$base/runs/$label/$fixture.done.json"
echo "$fixture exit=$code"
