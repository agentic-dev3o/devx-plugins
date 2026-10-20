#!/usr/bin/env bash
# Run one component unit as the real plugin agent, with its own model, tools and prompt.
# Usage: run_unit.sh <plugin-dir> <scanner|verifier|remover> <unit.json> <log-dir>
plugin=$1; role=$2; unit=$3; logs=$4
name=$(basename "$unit" .json)
case $role in verifier) effort=high;; *) effort=medium;; esac
root=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['root'])" "$unit")
cd "$root" || exit 2
timeout 1200 claude -p --plugin-dir "$plugin" \
  --settings '{"enabledPlugins":{"devx-qa@devx-plugins":false}}' \
  --agent "devx-qa:dead-code-$role" --model haiku --effort $effort \
  --permission-mode bypassPermissions --output-format json \
  "Your work unit is $unit. Read it first: it holds the repository root, your inputs, and the exact output path. Do what your instructions say for this unit, write the output file, then return your receipt." \
  > "$logs/$name.json" 2> "$logs/$name.err"
echo "$name exit=$?"
