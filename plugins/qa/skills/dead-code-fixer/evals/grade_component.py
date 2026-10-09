#!/usr/bin/env python3
"""Grade the component evaluation of the dead-code-fixer Haiku agents against ground truth.

Usage: grade_component.py <eval-dir> [label]
Writes <eval-dir>/component/grade-<label>.json and prints a summary.
"""
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

LENSES = ("references", "dynamic", "boundary")
MIN_CONF = 80
# Ground truth per verifier candidate: D dead, A alive, E either (dead, but a round-1 alive vote is by design).
LABELS = {
    "js-app": {"barrel": "D", "old-pricing": "E", "report": "D", "stale": "D", "formatLegacy": "D"},
    "py-app": {"dead_fn": "D", "DeadClass": "D", "method": "D", "handle_create": "A", "handle_delete": "A",
               "report_view": "A", "legacy_helper": "D"},
    "rust-lib": {"private_dead": "D", "tested_only": "A", "helper_dead": "D"},
    "rb-app": {"total": "A", "subtotal": "A", "legacy_discount": "D", "on_event": "A", "handle_paid": "A",
               "handle_failed": "A", "stale_helper": "D", "format_money": "A", "old_badge": "D"},
    "js-hard": {"globals": "A", "en": "A", "fr": "A", "sync": "D", "formatLegacy": "D", "process": "D",
                "onSave": "A", "exportCsv": "A"},
    "py-hard": {"CsvExporter": "A", "clean_email": "A", "clean_name": "A", "nightly_cleanup": "A",
                "_sync_inventory": "D", "send_welcome": "A", "_old_slugify": "D", "_warm": "D"},
}
SCAN_EXPECT = {
    "rb-app": {"want": {"Cart", "total", "subtotal", "legacy_discount", "Orders", "on_event", "handle_paid",
                        "handle_failed", "stale_helper", "Helpers", "format_money", "old_badge"},
               "forbid": {"initialize", "to_s"}},
    "py-app": {"want": {"ROUTES", "route", "used_fn", "dead_fn", "DeadClass", "method", "Dispatcher", "handle_create",
                        "handle_delete", "report_view", "test_only_fn", "legacy_helper", "load", "run"},
               "forbid": {"main", "register", "__init__"}},
}
DECL = {
    "py-app": r"^\s*(def|class)\s+{name}\b",
    "rb-app": r"^\s*def\s+{name}\b",
    "rust-lib": r"^\s*(pub(\(crate\))?\s+)?fn\s+{name}\b",
    "js-app": r"^\s*export\s+(function|const|class)\s+{name}\b",
    "js-hard": r"^\s*export\s+(function|const|class)\s+{name}\b",
    "py-hard": r"^\s*(def|class)\s+{name}\b",
}


def jsonl(path: Path):
    rows, bad = [], 0
    if not path.exists():
        return None, 0
    for raw in path.read_text(errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
            rows.append(d) if isinstance(d, dict) else None
        except json.JSONDecodeError:
            bad += 1
    return rows, bad


def grade_verifiers(comp: Path, trials: int) -> dict:
    report = {}
    for fixture, labels in LABELS.items():
        if not (comp / "repos" / fixture).exists() or not any(OUT.glob(f"{fixture}-references-*")):
            continue
        cands = json.loads((comp / "repos" / fixture / ".dead-code/candidates.json").read_text())["items"]
        sym = {c["id"]: c["symbol"] for c in cands.values()}
        per_trial = []
        lens_stats = {lens: defaultdict(int) for lens in LENSES}
        for t in range(1, trials + 1):
            votes = defaultdict(dict)
            for lens in LENSES:
                rows, bad = jsonl(OUT / f"{fixture}-{lens}-t{t}.jsonl")
                st = lens_stats[lens]
                if rows is None:
                    st["missing_unit"] += 1
                    continue
                st["bad_lines"] += bad
                for r in rows:
                    s = sym.get(r.get("id"))
                    if s is None or r.get("verdict") not in ("dead", "alive", "unsure") or not isinstance(r.get("confidence"), int):
                        st["invalid"] += 1
                        continue
                    votes[s][lens] = (r["verdict"], r["confidence"], r.get("evidence", ""))
                    label = labels.get(s)
                    dead_vote = r["verdict"] == "dead" and r["confidence"] >= MIN_CONF
                    if label == "A":
                        st["alive_items"] += 1
                        st["alive_voted_dead"] += dead_vote
                    elif label == "D":
                        st["dead_items"] += 1
                        st["dead_voted_dead"] += dead_vote
            decided = {}
            for s, label in labels.items():
                v = votes.get(s, {})
                decided[s] = "dead" if all(l in v and v[l][0] == "dead" and v[l][1] >= MIN_CONF for l in LENSES) else "kept"
            false_dead = [s for s, l in labels.items() if l == "A" and decided[s] == "dead"]
            found = [s for s, l in labels.items() if l == "D" and decided[s] == "dead"]
            missed = [s for s, l in labels.items() if l == "D" and decided[s] != "dead"]
            per_trial.append({"trial": t, "false_dead": false_dead, "found": found, "missed": missed,
                              "missing_votes": sorted(s for s in labels if len(votes.get(s, {})) < 3)})
        report[fixture] = {"trials": per_trial, "lenses": {k: dict(v) for k, v in lens_stats.items()}}
    return report


def grade_scanners(comp: Path, trials: int) -> dict:
    report = {}
    for fixture, exp in SCAN_EXPECT.items():
        res = []
        for t in range(1, trials + 1):
            rows, bad = jsonl(OUT / f"{fixture}-scan-t{t}.jsonl")
            if rows is None:
                res.append({"trial": t, "missing": True})
                continue
            names = {r.get("symbol") for r in rows if "symbol" in r}
            res.append({"trial": t, "recall": round(len(names & exp["want"]) / len(exp["want"]), 2),
                        "missed": sorted(exp["want"] - names), "forbidden_listed": sorted(names & exp["forbid"]),
                        "extra": sorted(names - exp["want"] - exp["forbid"]), "bad_lines": bad})
        report[fixture] = res
    return report


def sh(cmd: str, cwd: Path) -> bool:
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True).returncode == 0


def grade_removers(base: Path, comp: Path, trials: int) -> dict:
    report = {}
    for fixture in LABELS:
        truth = json.loads((base / "fixtures" / f"{fixture}.truth.json").read_text())
        dead = [d for d in truth["dead"] if d.get("kind") != "file"]
        alive = truth["alive"]
        res = []
        for t in range(1, trials + 1):
            unit = f"{fixture}-remove-t{t}"
            root = REMOVE / unit
            if not root.exists():
                continue
            out = OUT / f"{unit}.json"
            try:
                result = json.loads(out.read_text())
                contract = isinstance(result.get("applied"), list)
            except Exception:
                result, contract = {}, False
            changed = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout.split("\n")
            changed = [c[3:] for c in changed if c.strip()]
            allowed = {d["file"] for d in dead}
            strays = [c for c in changed if c not in allowed]
            numstat = subprocess.run(["git", "diff", "--numstat"], cwd=root, capture_output=True, text=True).stdout
            added = sum(int(l.split()[0]) for l in numstat.splitlines() if l.split()[0].isdigit())
            pat = DECL[fixture]
            still_dead = [d["symbol"] for d in dead
                          if re.search(pat.format(name=re.escape(d["symbol"])), (root / d["file"]).read_text(), re.M)]
            lost_alive = [a["symbol"] for a in alive if (root / a["file"]).exists()
                          and a["file"] in allowed
                          and not re.search(r"\b" + re.escape(a["symbol"]) + r"\b", (root / a["file"]).read_text())]
            gate_fast = sh(truth["gate_fast"], root)
            gate_full = sh(truth["gate_full"], root)
            blank_runs = 0
            for f in allowed:
                text = (root / f).read_text()
                blank_runs += len(re.findall(r"\n\s*\n\s*\n\s*\n", text)) if fixture != "py-app" else len(re.findall(r"\n\s*\n\s*\n\s*\n\s*\n", text))
                blank_runs += text.endswith("\n\n")
            res.append({"trial": t, "contract": contract, "gate_fast": gate_fast, "gate_full": gate_full,
                        "dead_left": still_dead, "alive_lost": lost_alive, "strays": strays, "lines_added": added,
                        "blank_line_runs": blank_runs, "applied": result.get("applied")})
        report[fixture] = res
    return report


OUT = REMOVE = None


def main() -> None:
    global OUT, REMOVE
    base = Path(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 else "baseline"
    comp = base / (sys.argv[3] if len(sys.argv) > 3 else "component")
    sfx = f"-{sys.argv[4]}" if len(sys.argv) > 4 else ""
    OUT, REMOVE = comp / f"out{sfx}", comp / f"remove{sfx}"
    trials = 3
    grade = {"verifiers": grade_verifiers(comp, trials), "scanners": grade_scanners(comp, trials),
             "removers": grade_removers(base, comp, trials)}
    (comp / f"grade-{label}.json").write_text(json.dumps(grade, indent=1) + "\n")
    print(f"== verifiers ({label}): per trial false deletions / dead found / dead missed")
    tot_fd = tot_found = tot_dead = 0
    for fx, r in grade["verifiers"].items():
        for tr in r["trials"]:
            tot_fd += len(tr["false_dead"]); tot_found += len(tr["found"])
            tot_dead += len(tr["found"]) + len(tr["missed"])
            print(f"  {fx} t{tr['trial']}: false_dead={tr['false_dead']} found={len(tr['found'])} missed={tr['missed']}"
                  + (f" missing_votes={tr['missing_votes']}" if tr["missing_votes"] else ""))
        for lens, st in r["lenses"].items():
            print(f"    {lens}: alive voted dead {st.get('alive_voted_dead', 0)}/{st.get('alive_items', 0)}, "
                  f"dead voted dead {st.get('dead_voted_dead', 0)}/{st.get('dead_items', 0)}, "
                  f"invalid {st.get('invalid', 0) + st.get('bad_lines', 0)}, missing units {st.get('missing_unit', 0)}")
    print(f"  TOTAL false deletions {tot_fd}; recall {tot_found}/{tot_dead}")
    print("== scanners")
    for fx, rs in grade["scanners"].items():
        for r in rs:
            print(f"  {fx} {r}")
    print("== removers")
    for fx, rs in grade["removers"].items():
        for r in rs:
            print(f"  {fx} {r}")


if __name__ == "__main__":
    main()
