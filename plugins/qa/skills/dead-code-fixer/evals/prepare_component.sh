#!/usr/bin/env bash
# Prepare the component evaluation: one ledger per fixture, analyzers run and references counted,
# every candidate pending. Usage: prepare_component.sh   (EVAL_DIR, COMPONENT as in run_component.sh)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
L="$here/../scripts/ledger.py"
base=${EVAL_DIR:-/tmp/dc-eval}
comp="$base/${COMPONENT:-component}"
rm -rf "$comp" && mkdir -p "$comp/repos" && cd "$comp/repos"
prep() { name=$1; shift; cp -a "$base/fixtures/$name" "$name"; cd "$name"; python3 "$L" init --report-only "$@" >/dev/null; }
quiet() { grep -v "^next" || true; }

prep js-app --note "Private Node.js app (package.json private: true); src/index.js is the only entry point."
python3 "$L" analyze --tool knip -- npx -y knip@6 --reporter json --no-progress | quiet; python3 "$L" refs | head -1; cd ..

prep js-hard --note "Private Node.js app (package.json private: true); src/index.js is the entry point; public/index.html loads src/globals.js in the browser."
python3 "$L" analyze --tool knip -- npx -y knip@6 --reporter json --no-progress | quiet
# Two live handlers no analyzer flags, injected to test the verifiers on HTML bindings.
printf 'src/handlers.js\t1\tonSave\tfunction\theuristic: unused export\nsrc/export.js\t1\texportCsv\tfunction\theuristic: unused export\n' > .dead-code/inj.tsv
python3 "$L" import --tool tsv .dead-code/inj.tsv --source heuristic | head -1; python3 "$L" refs | head -1; cd ..

prep py-app --note "Private Python app; app/main.py is the only entry point (python3 -m app.main)."
python3 "$L" analyze --tool vulture -- uvx vulture app --min-confidence 60 | quiet; python3 "$L" refs | head -1; cd ..

prep py-hard --note "Published Python package shopkit (pyproject [project]); app/api.py __all__ is its public API; entry points are declared in pyproject.toml; app/main.py is the CLI entry point."
python3 "$L" analyze --tool vulture -- uvx vulture app --min-confidence 60 | quiet; python3 "$L" refs | head -1; cd ..

prep rust-lib --note "Published library crate 'pricing' (no publish = false); pub items reachable from src/lib.rs are public API; crate-type includes cdylib."
python3 "$L" analyze --tool cargo -- cargo check --all-targets --message-format=json | quiet; python3 "$L" refs | head -1; cd ..

prep rb-app --note "Private Ruby script; main.rb is the only entry point; views/*.erb templates are rendered by main.rb."
# What a scanner would list, fixed so the verifiers are scored on the same candidates every time.
printf 'lib/cart.rb\t6\ttotal\tmethod\tscan\nlib/cart.rb\t16\tsubtotal\tmethod\tscan\nlib/cart.rb\t20\tlegacy_discount\tmethod\tscan\nlib/orders.rb\t3\ton_event\tmethod\tscan\nlib/orders.rb\t7\thandle_paid\tmethod\tscan\nlib/orders.rb\t11\thandle_failed\tmethod\tscan\nlib/orders.rb\t15\tstale_helper\tmethod\tscan\nlib/helpers.rb\t2\tformat_money\tmethod\tscan\nlib/helpers.rb\t6\told_badge\tmethod\tscan\n' > .dead-code/scan.tsv
python3 "$L" import --tool tsv .dead-code/scan.tsv --source analyzer | head -1; python3 "$L" refs | head -1; cd ..
