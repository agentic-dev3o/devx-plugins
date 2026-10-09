#!/usr/bin/env python3
"""Write component-evaluation units for the Haiku agents.

verify: for each fixture, one unit per lens and trial holding every pending candidate (no pruning),
        so each lens is scored on its own.
scan:   one unit per trial over the fixture's source files (scanner recall/precision).
remove: one fresh copy of the fixture per trial, with a removal unit for its ground-truth dead declarations.

Usage: make_units.py <eval-dir> <trials> [<component-subdir> <label> [fixture ...]]
Prints the JSON list of {unit, role, path} the workflow consumes.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

LENSES = ("references", "dynamic", "boundary")
KEEP = ("id", "file", "line", "symbol", "kind", "detail", "markers", "exported", "refs")
SCAN_FILES = {"rb-app": ["lib/cart.rb", "lib/helpers.rb", "lib/orders.rb", "main.rb"],
              "py-app": ["app/core.py", "app/legacy.py", "app/main.py", "app/plugins/__init__.py",
                         "app/plugins/export_csv.py"]}


def main(base: Path, trials: int, sub: str = "component", label: str = "", only=()) -> None:
    comp = base / sub
    sfx = f"-{label}" if label else ""
    units_dir, out_dir = comp / f"units{sfx}", comp / f"out{sfx}"
    for d in (units_dir, out_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    plan = []
    for repo in sorted((comp / "repos").iterdir()):
        name = repo.name
        if only and name not in only:
            continue
        state = json.loads((repo / ".dead-code/state.json").read_text())
        cands = json.loads((repo / ".dead-code/candidates.json").read_text())["items"].values()
        pending = [{k: c[k] for k in KEEP if c.get(k) not in (None, [], "")} for c in cands if c["status"] == "pending"]
        for lens in LENSES:
            for t in range(1, trials + 1):
                unit = f"{name}-{lens}-t{t}"
                spec = {"unit": unit, "stage": "verify", "lens": lens, "root": str(repo),
                        "output": str(out_dir / f"{unit}.jsonl"), "notes": state["notes"], "candidates": pending}
                (units_dir / f"{unit}.json").write_text(json.dumps(spec, indent=1) + "\n")
                plan.append({"unit": unit, "role": "verifier", "path": str(units_dir / f"{unit}.json")})
        if name in SCAN_FILES:
            for t in range(1, trials + 1):
                unit = f"{name}-scan-t{t}"
                spec = {"unit": unit, "stage": "scan", "root": str(repo), "output": str(out_dir / f"{unit}.jsonl"),
                        "files": SCAN_FILES[name]}
                (units_dir / f"{unit}.json").write_text(json.dumps(spec, indent=1) + "\n")
                plan.append({"unit": unit, "role": "scanner", "path": str(units_dir / f"{unit}.json")})
        truth = json.loads((base / "fixtures" / f"{name}.truth.json").read_text())
        dead = [d for d in truth["dead"] if d.get("kind") != "file"]
        if not dead:
            continue
        by_symbol = {c["symbol"]: c for c in cands}
        for t in range(1, trials + 1):
            unit = f"{name}-remove-t{t}"
            copy = comp / f"remove{sfx}" / unit
            shutil.rmtree(copy, ignore_errors=True)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(base / "fixtures" / name, copy, symlinks=True)
            edits = []
            for d in dead:
                c = by_symbol.get(d["symbol"])
                line = c["line"] if c else None
                if line is None:
                    for n, text in enumerate((copy / d["file"]).read_text().splitlines(), 1):
                        if d["symbol"] in text:
                            line = n
                            break
                edits.append({"id": (c or {}).get("id", d["symbol"]), "file": d["file"], "line": line,
                              "symbol": d["symbol"], "kind": (c or {}).get("kind", "function"),
                              "also_edit": [], "remove": "the declaration"})
            spec = {"unit": unit, "stage": "remove", "wave": 1, "root": str(copy),
                    "output": str(out_dir / f"{unit}.json"),
                    "allowed_files": sorted({e["file"] for e in edits}), "deleted_by_orchestrator": [], "edits": edits}
            (units_dir / f"{unit}.json").write_text(json.dumps(spec, indent=1) + "\n")
            plan.append({"unit": unit, "role": "remover", "path": str(units_dir / f"{unit}.json")})
    (comp / f"plan{sfx}.json").write_text(json.dumps(plan, indent=1) + "\n")
    print(json.dumps({"units": len(plan), "by_role": {r: sum(p["role"] == r for p in plan)
                                                      for r in ("verifier", "scanner", "remover")}}))


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]), *(sys.argv[3:5] if len(sys.argv) > 4 else ("component", "")),
         only=tuple(sys.argv[5:]))
