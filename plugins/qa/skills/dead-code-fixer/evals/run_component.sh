#!/usr/bin/env bash
# Run every component unit through the real plugin agents, three trials each.
# Usage: run_component.sh <label> <plugin-dir>
#   EVAL_DIR   scratch directory holding fixtures/ (default /tmp/dc-eval)
#   COMPONENT  subdirectory prepared by prepare_component.sh (default component)
#   JOBS       agents run at once (default 8)
# Grade with: python3 grade_component.py "$EVAL_DIR" <label> "$COMPONENT" <label>
set -euo pipefail
label=$1; plugin=$(cd "$2" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
base=${EVAL_DIR:-/tmp/dc-eval}
sub=${COMPONENT:-component}
comp="$base/$sub"
python3 "$here/make_units.py" "$base" 3 "$sub" "$label"
mkdir -p "$comp/logs-$label"
python3 -c "
import json, sys
for p in json.load(open(sys.argv[1])):
    print(sys.argv[2], p['role'], p['path'], sys.argv[3])
" "$comp/plan-$label.json" "$plugin" "$comp/logs-$label" | xargs -P "${JOBS:-8}" -L 1 "$here/run_unit.sh"
