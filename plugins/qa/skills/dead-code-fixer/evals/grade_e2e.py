#!/usr/bin/env python3
"""Grade nested end-to-end runs of /devx-qa:dead-code-fixer against the fixtures' ground truth.

Usage: grade_e2e.py <eval-dir> <label>
Prints, per fixture: cost, models used, dead code removed or left, live code lost (must be empty),
the ledger's final statuses, commits, gates, and the orchestrator's main-thread tool calls.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

DECL = {
    "py-app": r"^\s*(def|class)\s+{name}\b",
    "rb-app": r"^\s*def\s+{name}\b",
    "rust-lib": r"^\s*(pub(\(crate\))?\s+)?(extern\s+\"C\"\s+)?fn\s+{name}\b",
    "js-app": r"^\s*export\s+(async\s+)?(function|const|class)\s+{name}\b",
    "js-hard": r"^\s*export\s+(async\s+)?(function|const|class)\s+{name}\b",
    "py-hard": r"^\s*(def|class)\s+{name}\b",
}


def present(root: Path, item: dict, fixture: str) -> bool:
    path = root / item["file"]
    if item.get("kind") == "file":
        return path.exists()
    if not path.exists():
        return False
    return bool(re.search(DECL[fixture].format(name=re.escape(item["symbol"])), path.read_text(), re.M))


def result_line(jsonl: Path) -> dict:
    last = {}
    if not jsonl.exists():
        return last
    for raw in jsonl.read_text(errors="replace").splitlines():
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if d.get("type") == "result":
            last = d
    return last


def tool_uses(jsonl: Path) -> dict:
    counts = {}
    if not jsonl.exists():
        return counts
    for raw in jsonl.read_text(errors="replace").splitlines():
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if d.get("type") == "assistant" and not d.get("parent_tool_use_id"):
            for block in (d.get("message") or {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = block["name"]
                    if name == "Bash":
                        cmd = block["input"].get("command", "")
                        name = "Bash:ledger" if "ledger.py" in cmd else ("Bash:git" if cmd.startswith("git") else "Bash:other")
                    counts[name] = counts.get(name, 0) + 1
    return counts


def main() -> None:
    base, label = Path(sys.argv[1]), sys.argv[2]
    out = {}
    for done in sorted((base / "runs" / label).glob("*.done.json")):
        fixture = done.name.split(".")[0]
        root = base / "runs" / label / fixture
        truth = json.loads((base / "fixtures" / f"{fixture}.truth.json").read_text())
        res = result_line(base / "runs" / label / f"{fixture}.jsonl")
        cands = {}
        cpath = root / ".dead-code/candidates.json"
        if cpath.exists():
            cands = {c["symbol"]: c["status"] for c in json.loads(cpath.read_text())["items"].values()}
        dead = truth["dead"]
        alive = truth["alive"]
        name = lambda d: d.get("symbol") or Path(d["file"]).stem
        log = subprocess.run(["git", "log", "--oneline", "main..HEAD"], cwd=root, capture_output=True, text=True).stdout
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
        gates = {k: subprocess.run(["bash", "-c", truth[k]], cwd=root, capture_output=True).returncode == 0
                 for k in ("gate_fast", "gate_full")}
        out[fixture] = {
            "exit": json.loads(done.read_text()),
            "cost_usd": res.get("total_cost_usd"), "turns": res.get("num_turns"), "is_error": res.get("is_error"),
            "models": sorted((res.get("modelUsage") or {}).keys()),
            "dead_removed": [name(d) for d in dead if not present(root, d, fixture)],
            "dead_left": [name(d) for d in dead if present(root, d, fixture)],
            "alive_lost": [name(a) for a in alive if not present(root, a, fixture)],
            "ledger_status": {name(d): cands.get(name(d)) for d in dead + alive},
            "branch": branch, "commits": log.strip().splitlines(), "dirty": status.strip().splitlines(),
            "gates": gates, "main_thread_tools": tool_uses(base / "runs" / label / f"{fixture}.jsonl"),
            "final_text": (res.get("result") or "")[:1500],
        }
    (base / "runs" / f"grade-{label}.json").write_text(json.dumps(out, indent=1) + "\n")
    for fx, r in out.items():
        print(f"== {fx}: exit={r['exit']['exit']} {r['exit']['seconds']}s cost=${r['cost_usd']} turns={r['turns']} models={r['models']}")
        print(f"   dead removed={r['dead_removed']} left={r['dead_left']} | ALIVE LOST={r['alive_lost']}")
        print(f"   ledger={r['ledger_status']}")
        print(f"   branch={r['branch']} commits={len(r['commits'])} dirty={r['dirty']} gates={r['gates']}")
        print(f"   tools={r['main_thread_tools']}")


if __name__ == "__main__":
    main()
