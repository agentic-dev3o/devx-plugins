#!/usr/bin/env python3
"""Bookkeeping for the dead-code-fixer skill.

Every candidate, vote and removal of a run lives in `.dead-code/` at the
repository root, so the orchestrating session never holds them in context and
a run survives context compaction. Agents read one unit file each and write
one output file each; this script builds the units, validates the outputs,
computes the verification tally, and decides what comes next. Every command
ends with a `next:` line.

Usage: python3 ledger.py <command> [options]   (from anywhere inside the repo)

Commands, in the order a round uses them:
  init      start a run: scope, protected paths, gate commands, mode
  note      add a fact every verifier must know (public API, conventions)
  import    load analyzer output (knip, vulture, cargo, staticcheck, deadcode,
            debride, phpstan, sarif, tsv)
  shard     split the files no analyzer covers into scan units
  refs      count references to every open candidate across tracked files
  dispatch  write the next units of a stage, print the Workflow args
  ingest    validate the agents' outputs for a stage and record them
  confirm   record the user's go-ahead for deletions
  check     refuse working-tree changes outside the current wave's files
  settle    close a removal wave after the gate: --ok, or --fail <unit>
  mark      override statuses (adjudication, reverted commits)
  round     close the round; start the next or finish
  status    counts and the next step
  report    write .dead-code/report.md

Stdlib only, Python 3.8+.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

LEDGER = ".dead-code"
SCHEMA_VERSION = 1

# Every candidate meets the lenses in this order, and a lens only sees the
# candidates the previous one voted dead. Deletion needs all three (tally()).
LENSES = ("references", "dynamic", "boundary")

# Each lens must vote dead at or above this confidence. Anthropic's code-review
# plugin filtered its findings at the same threshold.
MIN_CONFIDENCE = 80

# Candidates per verifier unit: enough to amortise an agent's start-up, few
# enough that reading each declaration and its references stays far below the
# 100k-token prompt size above which Haiku 5.5 bills five times more.
VERIFY_BATCH = 8

# Candidates per removal unit, and removal units per wave. Workflows run 16
# agents at once by default; 12 leaves headroom and keeps a red wave small
# enough to localise by restoring one unit at a time.
REMOVE_BATCH = 6
WAVE_UNITS = 12

# A scanner reads its whole shard. Anthropic's own scanners size a unit to about
# 25 files; 30k tokens of source plus the agent's prompt and output keeps every
# Haiku 5.5 request under the 100k-token price step.
SHARD_MAX_FILES = 25
SHARD_MAX_TOKENS = 30_000

# Claude 4.7+ tokenizers (Haiku 5.5 included) produce roughly one token per
# three bytes of source code. Rounding bytes-per-token down overestimates.
BYTES_PER_TOKEN = 3

# An agent unit that fails this many times is given up on.
MAX_RETRIES = 3

# Larger files are not searched for references (bundles, lockfiles, dumps);
# `refs` names them so a reviewer can decide.
MAX_REF_FILE_BYTES = 20_000_000

SOURCE_EXTS = {
    ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro",
    ".py", ".pyi", ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".groovy", ".cs", ".fs", ".vb",
    ".php", ".rb", ".swift", ".m", ".mm", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh",
    ".ex", ".exs", ".erl", ".clj", ".cljs", ".dart", ".lua", ".jl", ".hs", ".ml",
}

# Never scanned, never a candidate: dependencies, build output, generated code,
# and database migrations (history, not dead code).
NEVER_SCAN = [
    "node_modules/*", "*/node_modules/*", "vendor/*", "*/vendor/*", "third_party/*", "*/third_party/*",
    "dist/*", "*/dist/*", "build/*", "*/build/*", "target/*", "*/target/*", "out/*", "*/out/*",
    ".next/*", "*/.next/*", ".nuxt/*", "*/.nuxt/*", "coverage/*", "*/coverage/*",
    "*.min.js", "*.min.css", "*.d.ts", "*.pb.go", "*_pb2.py", "*_pb2_grpc.py", "*.pb.*",
    "*.g.dart", "*.freezed.dart", "*.generated.*", "*_generated.*", "*.gen.*",
    "generated/*", "*/generated/*", "__generated__/*", "*/__generated__/*",
    "migrations/*", "*/migrations/*", "*/db/migrate/*",
]

# Not searched for references: third-party code only mentions an app's names by
# coincidence, and committed build output is a copy of the source, so a hit there
# would keep every symbol alive. Generated code and migrations are searched.
REFS_IGNORE = [
    "node_modules/*", "*/node_modules/*", "vendor/*", "*/vendor/*", "third_party/*", "*/third_party/*",
    "dist/*", "*/dist/*", "build/*", "*/build/*", "target/*", "*/target/*", "out/*", "*/out/*",
    ".next/*", "*/.next/*", ".nuxt/*", "*/.nuxt/*", "coverage/*", "*/coverage/*",
    "*.min.js", "*.min.css", "*.map", "*.lock", "package-lock.json", "pnpm-lock.yaml", "go.sum",
]

DEFAULT_TESTS = [
    "*.test.*", "*.spec.*", "*_test.*", "*_spec.*", "test_*.py", "conftest.py", "*.stories.*",
    "test/*", "*/test/*", "tests/*", "*/tests/*", "__tests__/*", "*/__tests__/*", "spec/*", "*/spec/*",
    "testdata/*", "*/testdata/*", "fixtures/*", "*/fixtures/*", "e2e/*", "*/e2e/*", "*/__mocks__/*",
]

KINDS = {"file", "export", "function", "method", "class", "type", "variable", "member", "dependency"}
SCAN_KINDS = {"function", "method", "class", "type", "variable", "member"}
VERDICTS = {"dead", "alive", "unsure"}
WORD = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
# Module names such as `old-pricing` are imported by path, so they are matched as hyphenated tokens.
HYPHENATED = re.compile(r"[A-Za-z0-9_$]+(?:-[A-Za-z0-9_$]+)+")
GENERIC_STEMS = {"index", "__init__", "mod", "main", "lib", "init"}
IN_FLIGHT = ("new", "pending", "queued", "planned", "applied")

# Candidate statuses:
#   new          imported, references not counted yet
#   referenced   (scanner-only candidates) the name is used: not a candidate
#   test-only    only test files use it: reported, never deleted
#   protected    under a protected path: reported, never deleted
#   pending      waiting for its next lens;  queued: in a dispatched verify unit
#   dead         every lens voted dead with enough confidence
#   likely-dead  dead votes, one below MIN_CONFIDENCE: reported
#   alive        a lens found a use;  unsure: a lens could not decide (reported)
#   planned      in a removal unit;  applied: removed in the tree, gate not run
#   removed      committed after a green gate
#   reverted     the gate failed with it removed: it was alive after all
#   skipped      the remover could not apply it;  gone: vanished since import
#   dependency   unused package from an analyzer: reported with the analyzer


# --------------------------------------------------------------------------- io

def die(msg: str, code: int = 1) -> None:
    sys.stderr.write(f"ledger.py: {msg}\n")
    sys.exit(code)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd: list, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True)
    if check and proc.returncode != 0:
        die(f"`{' '.join(cmd)}` failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc


def git_root() -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True)
    if proc.returncode != 0:
        die("not inside a git repository; a run needs git to scope files and roll back removals")
    return Path(proc.stdout.decode().strip())


def tracked_files(root: Path, pathspecs: list | None = None) -> list:
    out = run(["git", "ls-files", "-z", "--"] + (pathspecs or []), root).stdout.decode("utf-8", "replace")
    return [p for p in out.split("\0") if p]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as err:
        raise ValueError(f"{path.name}: invalid JSON ({err.msg} at line {err.lineno})") from err


def say_next(text: str) -> None:
    print(f"next: {text}")


def matches(path: str, globs: list) -> bool:
    base = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(path, g) or ("/" not in g and fnmatch.fnmatchcase(base, g)) for g in globs)


def rel(root: Path, path: str, base: str = "") -> str:
    """An analyzer's path as a repository-relative POSIX path."""
    if path.startswith("file://"):
        path = path[len("file://"):]
    p = Path(path)
    if not p.is_absolute():
        p = root / base / p
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def stem_term(path: str) -> str:
    """The name other files import a module by: its stem, or its directory for index-like files."""
    parts = path.split("/")
    stem = parts[-1].split(".", 1)[0]
    return parts[-2] if stem in GENERIC_STEMS and len(parts) > 1 else stem


def term_of(c: dict) -> str:
    """The token whose occurrences count as references: a name, or a module's import name."""
    if c["kind"] == "file":
        stem = stem_term(c["file"])
        return stem if WORD.fullmatch(stem) or HYPHENATED.fullmatch(stem) else ""
    name = c["symbol"].split("(", 1)[0].rsplit(".", 1)[-1].rsplit("::", 1)[-1]
    m = WORD.search(name)
    return m.group(0) if m else ""


def count_term(path: Path, term: str) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return sum(1 for w in WORD.findall(text) if w == term)


class Ledger:
    """The run's state (state.json) and its candidates (candidates.json)."""

    def __init__(self, root: Path):
        self.root = root
        self.dir = root / LEDGER
        self.state_path = self.dir / "state.json"
        self.cands_path = self.dir / "candidates.json"
        self.state: dict = {}
        self.cands: dict = {}

    def exists(self) -> bool:
        return self.state_path.exists()

    def load(self) -> "Ledger":
        if not self.exists():
            die(f"no run in {self.dir}; start one with `ledger.py init`")
        self.state = read_json(self.state_path)
        if self.state.get("schema") != SCHEMA_VERSION:
            die(f"{self.state_path} comes from another version of this script; start over with `init --force`")
        self.cands = (read_json(self.cands_path) or {}).get("items", {})
        return self

    def save(self) -> None:
        write_json(self.state_path, self.state)
        write_json(self.cands_path, {"items": self.cands})

    def next_id(self, prefix: str) -> str:
        counters = self.state["counters"]
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}{counters[prefix]:0{4 if prefix == 'c' else 3}d}"

    def unit_path(self, unit: str) -> Path:
        return self.dir / "units" / f"{unit}.json"

    def out_path(self, unit: str, stage: str) -> Path:
        return self.dir / "out" / (f"{unit}.json" if stage == "remove" else f"{unit}.jsonl")

    def units(self, stage: str | None = None, status: str | None = None) -> list:
        found = [u for u in self.state["units"].values()
                 if (stage is None or u["stage"] == stage) and (status is None or u["status"] == status)]
        return sorted(found, key=lambda u: u["id"])

    def is_test(self, path: str) -> bool:
        return matches(path, self.state["tests"])

    def is_protected(self, path: str) -> bool:
        return matches(path, self.state["protect"])

    def in_scope(self, path: str) -> bool:
        scope = self.state["scope"]
        return not scope or any(path == s or path.startswith(s + "/") for s in scope)


# ------------------------------------------------------------------- candidates

def add_candidate(lg: Ledger, *, file: str, symbol: str, kind: str, source: str, line=None,
                  detail: str = "", markers=None, exported=None) -> str | None:
    """Record a candidate unless the same declaration is already known; return its id when new."""
    if kind not in KINDS or not file:
        return None
    if kind != "dependency" and not lg.in_scope(file):
        return None
    key = {"file": f"{file}::<file>", "dependency": f"{file}::dep::{symbol}"}.get(kind, f"{file}::{symbol}")
    known = lg.state["keys"]
    if key in known:
        c = lg.cands.get(known[key])
        if c is not None and source not in c["sources"]:
            c["sources"].append(source)
            c["detail"] = f"{c['detail']}; {detail}" if c["detail"] and detail else (c["detail"] or detail)
        return None
    cid = lg.next_id("c")
    lg.cands[cid] = {
        "id": cid, "key": key, "file": file, "line": line if isinstance(line, int) and line > 0 else None,
        "symbol": symbol, "kind": kind, "sources": [source], "detail": detail,
        "markers": list(markers or []), "exported": exported,
        "status": "dependency" if kind == "dependency" else "new", "round": lg.state["round"],
        "refs": None, "votes": {}, "also_edit": [], "unit": None, "retries": 0, "commit": None, "note": "",
    }
    known[key] = cid
    return cid


def set_status(c: dict, status: str, note: str = "") -> None:
    c["status"] = status
    if note:
        c["note"] = note


# ----------------------------------------------------------------------- init

def cmd_init(args) -> None:
    root = git_root()
    lg = Ledger(root)
    if lg.exists() and not args.force:
        lg.load()
        print(f"a run already exists in {lg.dir} (round {lg.state['round']}, started {lg.state['created']})")
        say_next("resume it with `ledger.py status`, or start over with `ledger.py init --force ...` "
                 "(the old run moves to .dead-code.prev)")
        return
    if lg.dir.exists():
        prev = root / f"{LEDGER}.prev"
        if prev.exists():
            shutil.rmtree(prev)
        shutil.move(str(lg.dir), str(prev))
    lg.dir.mkdir(parents=True)
    # Ignores the ledger and itself: nothing here ever shows in git status or a commit.
    (lg.dir / ".gitignore").write_text("*\n", encoding="utf-8")
    head = run(["git", "rev-parse", "HEAD"], root, check=False).stdout.decode().strip()
    branch = run(["git", "branch", "--show-current"], root, check=False).stdout.decode().strip()
    scope = []
    for s in args.scope:
        s = Path(s).as_posix().strip("/")
        s = s[2:] if s.startswith("./") else s
        if s and s != ".":
            scope.append(s)
    mode = "report" if args.report_only else "fix"
    if mode == "fix" and not (args.gate_fast or args.gate_full):
        print("no gate command: deletions could not be verified, so this run is report-only; "
              "re-run with --gate-fast/--gate-full to remove code")
        mode = "report"
    lg.state = {
        "schema": SCHEMA_VERSION, "created": now(), "root": str(root), "base_sha": head, "branch": branch,
        "scope": scope, "protect": list(args.protect), "tests": DEFAULT_TESTS + list(args.tests),
        "gate": {"fast": args.gate_fast, "full": args.gate_full}, "mode": mode,
        "max_rounds": args.max_rounds, "round": 1, "finished": False, "confirmed": None,
        "notes": list(args.note), "analyzers": {}, "skipped": {}, "units": {}, "current_wave": None,
        "counters": {}, "keys": {}, "history": [], "emptied": [], "refs_round": None,
    }
    lg.save()
    print(f"run started in {lg.dir} on {branch or 'detached HEAD'} at {head[:12]}")
    print(f"scope: {', '.join(scope) or 'whole repository'} | mode: {mode} | "
          f"gate: fast={args.gate_fast or '-'} full={args.gate_full or '-'}")
    say_next("run the analyzers that fit the stack and `ledger.py import` each; "
             "then `ledger.py shard --ext ...` for the languages no analyzer covers")


def cmd_note(args) -> None:
    lg = Ledger(git_root()).load()
    lg.state["notes"].append(args.text.strip())
    lg.save()
    print(f"{len(lg.state['notes'])} note(s) reach every verifier from now on")
    say_next(next_step(lg))


# ---------------------------------------------------------------------- shard

def cmd_shard(args) -> None:
    lg = Ledger(git_root()).load()
    root = lg.root
    exts = {e if e.startswith(".") else "." + e for e in args.ext} if args.ext else SOURCE_EXTS
    skipped = defaultdict(Counter)
    kept = []
    for path in tracked_files(root, lg.state["scope"] or None):
        top = path.split("/", 1)[0] if "/" in path else "."
        name = path.rsplit("/", 1)[-1]
        suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if suffix not in exts:
            reason = "covered by an analyzer or left out by --ext" if suffix in SOURCE_EXTS else "not source"
        elif matches(path, NEVER_SCAN):
            reason = "vendored, generated or migration"
        elif lg.is_test(path):
            reason = "test"
        elif lg.is_protected(path):
            reason = "protected"
        elif matches(path, args.exclude):
            reason = "excluded"
        else:
            try:
                kept.append((path, max(1, (root / path).stat().st_size // BYTES_PER_TOKEN)))
                continue
            except OSError:
                reason = "unreadable"
        skipped[reason][top] += 1
    shards, current, tokens = [], [], 0
    for path, tok in kept:
        if current and (len(current) >= args.max_files or tokens + tok > args.max_tokens):
            shards.append(current)
            current, tokens = [], 0
        current.append(path)
        tokens += tok
    if current:
        shards.append(current)
    for files in shards:
        unit = lg.next_id("s")
        write_json(lg.unit_path(unit), {
            "unit": unit, "stage": "scan", "root": str(root), "output": str(lg.out_path(unit, "scan")),
            "files": files,
        })
        lg.state["units"][unit] = {"id": unit, "stage": "scan", "status": "ready", "round": lg.state["round"],
                                   "lens": None, "wave": None, "retries": 0, "items": len(files),
                                   "candidates": [], "files": files}
    for reason, counter in skipped.items():
        merged = Counter(lg.state["skipped"].get(reason, {}))
        merged.update(counter)
        lg.state["skipped"][reason] = dict(merged)
    lg.save()
    print(f"{len(kept)} file(s) to scan in {len(shards)} shard(s), about {sum(t for _, t in kept):,} tokens")
    for reason, counter in sorted(skipped.items()):
        print(f"not scanned, {reason}: {sum(counter.values())} ("
              + ", ".join(f"{d} {n}" for d, n in counter.most_common(6)) + ")")
    big = [p for p, t in kept if t > args.max_tokens]
    if big:
        print(f"{len(big)} file(s) fill a shard on their own; their scanner reads them in pages: " + ", ".join(big[:5]))
    say_next("ledger.py dispatch scan" if shards else next_step(lg))


# --------------------------------------------------------------------- import

def import_knip(lg: Ledger, data, base: str) -> int:
    if not isinstance(data, dict) or "issues" not in data:
        die("not a knip JSON report (no `issues` key); run knip with `--reporter json`")
    added = 0
    for entry in data.get("files") or []:  # knip 5 listed unused files at the top level
        name = entry if isinstance(entry, str) else (entry or {}).get("name")
        if name:
            path = rel(lg.root, name, base)
            added += bool(add_candidate(lg, file=path, symbol=stem_term(path), kind="file", source="knip",
                                        detail="knip: unused file"))
    groups = (("files", "file"), ("exports", "export"), ("nsExports", "export"), ("types", "type"),
              ("nsTypes", "type"), ("enumMembers", "member"), ("namespaceMembers", "member"),
              ("classMembers", "member"), ("dependencies", "dependency"), ("devDependencies", "dependency"),
              ("optionalPeerDependencies", "dependency"))
    for issue in data["issues"]:
        file = rel(lg.root, issue.get("file", ""), base)
        for key, kind in groups:
            entries = issue.get(key) or []
            if isinstance(entries, dict):  # knip 5: {parent: [members]}
                entries = [dict(e, parent=p) for p, es in entries.items() for e in es]
            for e in entries:
                e = e if isinstance(e, dict) else {"name": str(e)}
                if not e.get("name"):
                    continue
                if kind == "file":
                    path = rel(lg.root, e["name"], base)
                    cid = add_candidate(lg, file=path, symbol=stem_term(path), kind="file", source="knip",
                                        detail="knip: unused file")
                else:
                    label = f"{e['parent']}.{e['name']}" if e.get("parent") else e["name"]
                    cid = add_candidate(lg, file=file, symbol=label, kind=kind, line=e.get("line"), source="knip",
                                        detail=f"knip: unused {key}")
                added += bool(cid)
    return added


VULTURE = re.compile(r"^(?P<file>.+?):(?P<line>\d+): unused (?P<what>[a-z ]+?) '(?P<name>[^']+)' "
                     r"\((?P<conf>\d+)% confidence")
VULTURE_KINDS = {"function": "function", "method": "method", "class": "class", "variable": "variable",
                 "attribute": "member", "property": "member"}


def import_vulture(lg: Ledger, text: str, base: str) -> int:
    added = ignored = 0
    for line in text.splitlines():
        m = VULTURE.match(line.strip())
        if not m:
            continue
        kind = VULTURE_KINDS.get(m["what"])
        if kind is None:
            ignored += 1  # imports and arguments: the project's linter fixes those (ruff F401, F841, ARG)
            continue
        added += bool(add_candidate(lg, file=rel(lg.root, m["file"], base), symbol=m["name"], kind=kind,
                                    line=int(m["line"]), source="vulture",
                                    detail=f"vulture: unused {m['what']} ({m['conf']}%)"))
    if ignored:
        print(f"left {ignored} unused import/argument finding(s) to the project's linter")
    return added


CARGO_KINDS = {"associated function": "function", "associated constant": "variable", "associated items": "member",
               "function": "function", "methods": "method", "method": "method", "struct": "class",
               "enum": "type", "union": "type", "trait": "type", "type alias": "type", "constant": "variable",
               "static": "variable", "fields": "member", "field": "member", "variants": "member",
               "variant": "member", "macro": "function"}


def import_cargo(lg: Ledger, text: str, base: str) -> int:
    added = 0
    for raw in text.splitlines():
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            continue
        msg = m.get("message") if isinstance(m, dict) and m.get("reason") == "compiler-message" else None
        if not msg or (msg.get("code") or {}).get("code") != "dead_code":
            continue
        text_msg = msg.get("message", "")
        head = re.sub(r"^(multiple|the following)\s+", "", text_msg.split("`", 1)[0].strip().lower())
        kind = next((CARGO_KINDS[k] for k in sorted(CARGO_KINDS, key=len, reverse=True) if head.startswith(k)),
                    "function")
        names = re.findall(r"`([^`]+)`", text_msg)
        spans = [s for s in msg.get("spans", []) if s.get("is_primary")]
        pairs = list(zip(names, spans)) if len(names) == len(spans) else ([(names[0], spans[0])] if names and spans else [])
        for name, span in pairs:
            added += bool(add_candidate(lg, file=rel(lg.root, span.get("file_name", ""), base), symbol=name,
                                        kind=kind, line=span.get("line_start"), source="cargo",
                                        detail=f"rustc: {text_msg}"))
    return added


STATICCHECK = re.compile(r"^(?P<what>func|type|field|const|var)\s+(?P<name>\S+)\s+is unused")
STATICCHECK_KINDS = {"func": "function", "type": "type", "field": "member", "const": "variable", "var": "variable"}


def import_staticcheck(lg: Ledger, text: str, base: str) -> int:
    added = 0
    for raw in text.splitlines():
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found = STATICCHECK.match(m.get("message", "")) if isinstance(m, dict) and m.get("code") == "U1000" else None
        if not found:
            continue
        name, loc = found["name"], m.get("location") or {}
        kind = "method" if name.startswith("(") else STATICCHECK_KINDS[found["what"]]
        added += bool(add_candidate(lg, file=rel(lg.root, loc.get("file", ""), base), symbol=name.split(".")[-1],
                                    kind=kind, line=loc.get("line"), source="staticcheck",
                                    detail=f"staticcheck U1000: {m.get('message')}"))
    return added


def import_deadcode(lg: Ledger, data, base: str) -> int:
    if not isinstance(data, list):
        die("not a `deadcode -json` report (expected a JSON array of packages)")
    added = 0
    for pkg in data:
        for fn in (pkg or {}).get("Funcs") or []:
            if fn.get("Generated"):
                continue
            name, pos = fn.get("Name", ""), fn.get("Position") or {}
            added += bool(add_candidate(lg, file=rel(lg.root, pos.get("File", ""), base), symbol=name.split(".")[-1],
                                        kind="method" if "." in name else "function", line=pos.get("Line"),
                                        source="deadcode", detail=f"deadcode: unreachable {name}"))
    return added


def import_debride(lg: Ledger, data, base: str) -> int:
    if not isinstance(data, dict) or "missing" not in data:
        die("not a `debride --json` report (no `missing` key)")
    added = 0
    for klass, methods in (data["missing"] or {}).items():
        for entry in methods or []:
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            name, where = str(entry[0]), str(entry[1])
            file, _, lines = where.rpartition(":")
            line = int(lines.split("-", 1)[0]) if lines.split("-", 1)[0].isdigit() else None
            added += bool(add_candidate(lg, file=rel(lg.root, file or where, base), symbol=name, kind="method",
                                        line=line, source="debride", detail=f"debride: {klass}#{name} never called"))
    return added


PHPSTAN_KINDS = {"deadMethod": "method", "deadConstant": "variable", "deadEnumCase": "member",
                 "deadProperty": "member"}


def import_phpstan(lg: Ledger, data, base: str) -> int:
    if not isinstance(data, dict) or "files" not in data:
        die("not a PHPStan JSON report (run `phpstan analyse --error-format=json`)")
    added = 0
    for file, entry in (data["files"] or {}).items():
        for m in (entry or {}).get("messages", []):
            ident = str(m.get("identifier", ""))
            if not ident.startswith("shipmonk.dead"):
                continue
            kind = next((k for p, k in PHPSTAN_KINDS.items() if ident.startswith("shipmonk." + p)), "member")
            names = re.findall(r"::\$?([A-Za-z_][A-Za-z0-9_]*)", m.get("message", ""))
            if not names:
                continue
            added += bool(add_candidate(lg, file=rel(lg.root, file, base), symbol=names[-1], kind=kind,
                                        line=m.get("line"), source="phpstan", detail=f"{ident}: {m.get('message')}"))
    return added


def sarif_kind(text: str):
    t = text.lower()
    if any(w in t for w in ("parameter", "argument", "import", "using directive", "local variable")):
        return None  # linter territory, not a declaration this skill removes
    for words, kind in ((("method",), "method"), (("function",), "function"),
                        (("field", "property", "member", "constant"), "member"), (("class",), "class"),
                        (("type", "interface", "enum", "struct"), "type")):
        if any(w in t for w in words):
            return kind
    return "member"


def import_sarif(lg: Ledger, data, base: str, rules: list) -> int:
    if not isinstance(data, dict) or "runs" not in data:
        die("not a SARIF log (no `runs` key)")
    added = 0
    for run_ in data["runs"] or []:
        tool = (((run_ or {}).get("tool") or {}).get("driver") or {}).get("name", "sarif")
        for r in (run_ or {}).get("results") or []:
            rule = str(r.get("ruleId", ""))
            if rules and rule not in rules:
                continue
            text = ((r.get("message") or {}).get("text")) or ""
            kind = sarif_kind(f"{rule} {text}")
            locs = r.get("locations") or []
            phys = (locs[0].get("physicalLocation") or {}) if locs else {}
            uri = (phys.get("artifactLocation") or {}).get("uri", "")
            region = phys.get("region") or {}
            if kind is None or not uri:
                continue
            path = rel(lg.root, uri, base)
            quoted = re.search(r"['\"`]([^'\"`]+)['\"`]", text)
            symbol = quoted.group(1).split("(", 1)[0].rsplit(".", 1)[-1] if quoted else ""
            if not WORD.fullmatch(symbol or "-"):
                symbol = identifier_at(lg.root / path, region.get("startLine"), region.get("startColumn"))
            if symbol:
                added += bool(add_candidate(lg, file=path, symbol=symbol, kind=kind, line=region.get("startLine"),
                                            source=tool, detail=f"{tool} {rule}: {text[:160]}"))
    return added


def identifier_at(path: Path, line, column) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").splitlines()[int(line) - 1]
    except (OSError, IndexError, TypeError, ValueError):
        return ""
    m = WORD.search(text, max(0, int(column or 1) - 1))
    return m.group(0) if m else ""


def import_tsv(lg: Ledger, text: str, base: str, source: str) -> int:
    added = 0
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        cols = raw.split("\t")
        if len(cols) < 4 or not cols[1].strip().isdigit():
            die(f"tsv line {n}: expected `file<TAB>line<TAB>symbol<TAB>kind[<TAB>detail]`")
        file, line, symbol, kind = (c.strip() for c in cols[:4])
        if kind not in KINDS:
            die(f"tsv line {n}: kind `{kind}` is not one of {', '.join(sorted(KINDS))}")
        added += bool(add_candidate(lg, file=rel(lg.root, file, base), symbol=symbol, kind=kind, line=int(line),
                                    source=source, detail=cols[4].strip() if len(cols) > 4 else source))
    return added


def cmd_import(args) -> None:
    lg = Ledger(git_root()).load()
    path = Path(args.file)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as err:
        die(f"cannot read {path}: {err}")
    if args.tool in ("knip", "deadcode", "debride", "phpstan", "sarif"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            die(f"{path} is not JSON ({err.msg}); did the analyzer print warnings into the report?")
        added = {"knip": lambda: import_knip(lg, data, args.base),
                 "deadcode": lambda: import_deadcode(lg, data, args.base),
                 "debride": lambda: import_debride(lg, data, args.base),
                 "phpstan": lambda: import_phpstan(lg, data, args.base),
                 "sarif": lambda: import_sarif(lg, data, args.base, args.rule)}[args.tool]()
    elif args.tool == "vulture":
        added = import_vulture(lg, text, args.base)
    elif args.tool == "cargo":
        added = import_cargo(lg, text, args.base)
    elif args.tool == "staticcheck":
        added = import_staticcheck(lg, text, args.base)
    else:
        added = import_tsv(lg, text, args.base, args.source or "tsv")
    name = args.source or args.tool
    lg.state["analyzers"][name] = lg.state["analyzers"].get(name, 0) + added
    lg.save()
    deps = sum(1 for c in lg.cands.values() if c["kind"] == "dependency")
    print(f"{name}: {added} new candidate(s); {len(lg.cands)} known, {deps} of them unused dependencies")
    say_next(next_step(lg))


# ----------------------------------------------------------------------- refs

def count_references(lg: Ledger, todo: list):
    """One pass over every tracked text file, counting each candidate name.

    Returns ({term: {"files": Counter(path), "samples": [(path, line)], "decl": Counter((path, line))}},
    files too large to read). `decl` only counts occurrences on the candidates' own declaration lines.
    """
    terms = {term_of(c) for c in todo} - {""}
    path_terms = {t for t in terms if not WORD.fullmatch(t)}
    decl_lines = defaultdict(set)
    for c in todo:
        if c["kind"] != "file" and c.get("line"):
            decl_lines[c["file"]].add((c["line"], term_of(c)))
    found = {t: {"files": Counter(), "samples": [], "decl": Counter()} for t in terms}
    too_big = []
    for path in tracked_files(lg.root):
        if matches(path, REFS_IGNORE):
            continue
        full = lg.root / path
        try:
            if full.stat().st_size > MAX_REF_FILE_BYTES:
                too_big.append(path)
                continue
            data = full.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", "ignore")
        present = set(WORD.findall(text)) & terms
        if path_terms:
            present |= set(HYPHENATED.findall(text)) & path_terms
        if not present:
            continue
        wanted = decl_lines.get(path, set())
        hyphenated = bool(present & path_terms)
        for n, line in enumerate(text.splitlines(), 1):
            tokens = WORD.findall(line) + (HYPHENATED.findall(line) if hyphenated else [])
            for word in tokens:
                if word in present:
                    f = found[word]
                    f["files"][path] += 1
                    if (n, word) in wanted:
                        f["decl"][(path, n)] += 1
                    elif len(f["samples"]) < 24:
                        f["samples"].append((path, n))
    return found, too_big


def relocate(lg: Ledger, c: dict) -> bool:
    """Point a candidate at the line that now declares it; False when the file or name is gone."""
    path = lg.root / c["file"]
    if c["kind"] == "file":
        return path.exists()
    term = term_of(c)
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return False
    hits = [n for n, line in enumerate(lines, 1) if term and term in WORD.findall(line)]
    if not hits:
        return False
    if c.get("line") not in hits:
        c["line"] = min(hits, key=lambda n: abs(n - (c.get("line") or 1)))
    return True


def cmd_refs(args) -> None:
    lg = Ledger(git_root()).load()
    revisit = {"new", "referenced", "alive", "unsure", "likely-dead"}
    todo = [c for c in lg.cands.values() if c["status"] in revisit and c["kind"] != "dependency"]
    if not todo:
        lg.state["refs_round"] = lg.state["round"]
        lg.save()
        print("no candidate needs its references counted")
        say_next(next_step(lg))
        return
    live, gone = [], 0
    for c in todo:
        if relocate(lg, c):
            live.append(c)
        else:
            set_status(c, "gone", "the file or the name no longer exists")
            gone += 1
    found, too_big = count_references(lg, live)
    moved = Counter()
    empty = {"files": Counter(), "samples": [], "decl": Counter()}
    for c in live:
        f = found.get(term_of(c), empty)
        decl = f["decl"].get((c["file"], c.get("line")), 0) if c["kind"] != "file" else 0
        in_file = f["files"].get(c["file"], 0)
        same = 0 if c["kind"] == "file" else in_file - decl  # a module naming itself does not import itself
        tests = sum(n for p, n in f["files"].items() if p != c["file"] and lg.is_test(p))
        other = sum(n for p, n in f["files"].items() if p != c["file"] and not lg.is_test(p))
        samples = sorted((s for s in f["samples"] if s != (c["file"], c.get("line"))),
                         key=lambda s: (s[0] == c["file"], lg.is_test(s[0])))
        refs = {"total": same + tests + other, "same_file": same, "tests": tests, "other": other,
                "in_file": in_file, "sample": [f"{p}:{n}" for p, n in samples[:8]]}
        before = (c.get("refs") or {}).get("total")
        c["refs"] = refs
        old = c["status"]
        if not term_of(c):
            set_status(c, "unsure", "its name cannot be searched as a token; check it by hand")
        elif old in ("alive", "unsure", "likely-dead"):
            if before is not None and refs["total"] < before:  # a removal took references away: vote again
                c["votes"], c["also_edit"], c["round"], c["retries"] = {}, [], lg.state["round"], 0
                set_status(c, "pending", f"references dropped from {before} to {refs['total']} since its last vote")
        elif lg.is_protected(c["file"]):
            set_status(c, "protected")
        elif refs["tests"] and not refs["other"] and not refs["same_file"]:
            set_status(c, "test-only")
        elif c["sources"] == ["scan"] and (refs["other"] or refs["same_file"]):
            set_status(c, "referenced")
        else:
            set_status(c, "pending")
        if c["status"] != old:
            moved[f"{old}->{c['status']}"] += 1
    lg.state["refs_round"] = lg.state["round"]
    lg.save()
    print(f"references counted for {len(live)} candidate(s) over every tracked file; {gone} gone")
    if moved:
        print("moved: " + ", ".join(f"{k} {n}" for k, n in sorted(moved.items())))
    if too_big:
        print(f"not searched (over {MAX_REF_FILE_BYTES // 1_000_000} MB): " + ", ".join(too_big[:5]))
    say_next(next_step(lg))


# ------------------------------------------------------------------- dispatch

def next_lens(c: dict):
    return next((lens for lens in LENSES if lens not in c["votes"]), None)


def brief(c: dict) -> dict:
    keep = ("id", "file", "line", "symbol", "kind", "detail", "markers", "exported", "refs")
    return {k: c[k] for k in keep if c.get(k) not in (None, [], "")}


def cmd_dispatch(args) -> None:
    lg = Ledger(git_root()).load()
    if lg.units(status="dispatched"):
        die("units are still dispatched; ingest them before dispatching more: " + next_step(lg))
    if args.stage == "scan":
        units = lg.units("scan", "ready")
    elif args.stage == "verify":
        units = plan_verify(lg)
    else:
        units = plan_remove(lg)
        if units is None:
            return
    if not units:
        print(f"nothing to dispatch for {args.stage}")
        say_next(next_step(lg))
        return
    (lg.dir / "out").mkdir(exist_ok=True)
    for u in units:
        u["status"] = "dispatched"
        # Only this dispatch's agent may author the output: drop anything written ahead of it.
        lg.out_path(u["id"], u["stage"]).unlink(missing_ok=True)
    lg.save()
    agent_units = [u["id"] for u in units if u.get("agent", True)]
    if not agent_units:
        print("this wave only deletes whole files; no agent is needed")
        say_next("ledger.py ingest remove")
        return
    print(f"{len(agent_units)} {args.stage} unit(s) dispatched")
    print("workflow-args: " + json.dumps({"stage": args.stage, "ledger": str(lg.dir), "units": agent_units}))
    say_next(f"Workflow name `devx-qa:dead-code-fanout` with exactly those args; when it completes, "
             f"`ledger.py ingest {args.stage}`")


def plan_verify(lg: Ledger) -> list:
    by_lens = defaultdict(list)
    for c in lg.cands.values():
        if c["status"] == "pending" and next_lens(c):
            by_lens[next_lens(c)].append(c)
    units = []
    for lens in LENSES:
        group = sorted(by_lens.get(lens, []), key=lambda c: (c["file"], c.get("line") or 0))
        for i in range(0, len(group), VERIFY_BATCH):
            batch = group[i:i + VERIFY_BATCH]
            unit = lg.next_id("v")
            write_json(lg.unit_path(unit), {
                "unit": unit, "stage": "verify", "lens": lens, "root": str(lg.root),
                "output": str(lg.out_path(unit, "verify")), "notes": lg.state["notes"],
                "candidates": [brief(c) for c in batch],
            })
            u = {"id": unit, "stage": "verify", "status": "ready", "round": lg.state["round"], "lens": lens,
                 "wave": None, "retries": 0, "items": len(batch), "candidates": [c["id"] for c in batch]}
            lg.state["units"][unit] = u
            for c in batch:
                c["unit"] = unit
                set_status(c, "queued")
            units.append(u)
    return units


def plan_remove(lg: Ledger):
    if lg.state["mode"] != "fix":
        print("this run is report-only; nothing is removed")
        say_next("ledger.py report")
        return None
    if not lg.state.get("confirmed"):
        print("deletions need the user's go-ahead first")
        say_next(next_step(lg))
        return None
    if open_removal_units(lg):
        print(f"wave {lg.state['current_wave']} is waiting for its gate")
        say_next(next_step(lg))
        return None
    ready = lg.units("remove", "ready")
    if not ready:
        build_removal_waves(lg)
        ready = lg.units("remove", "ready")
    if not ready:
        return []
    wave = min(u["wave"] for u in ready)
    lg.state["current_wave"] = wave
    return [u for u in ready if u["wave"] == wave]


def build_removal_waves(lg: Ledger) -> None:
    dead = [c for c in lg.cands.values() if c["status"] == "dead"]
    if not dead:
        return
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def files_of(c):
        return {c["file"]} | {e["file"] for e in c["also_edit"]}

    for c in dead:
        fs = sorted(files_of(c))
        for f in fs[1:]:
            parent[find(f)] = find(fs[0])
        find(fs[0])
    components = defaultdict(list)
    for c in dead:
        components[find(c["file"])].append(c)
    base = max([u["wave"] for u in lg.units("remove")] + [0])
    load = Counter()
    for members in sorted(components.values(), key=len, reverse=True):
        members.sort(key=lambda c: (c["file"], c.get("line") or 0))
        wave = base
        for i in range(0, len(members), REMOVE_BATCH):
            chunk = members[i:i + REMOVE_BATCH]
            wave += 1  # chunks of one component share files, so they never share a wave
            while load[wave] >= WAVE_UNITS:
                wave += 1
            load[wave] += 1
            unit = lg.next_id("r")
            deletes = sorted(c["file"] for c in chunk if c["kind"] == "file")
            allowed = sorted(set().union(*(files_of(c) for c in chunk)))
            edits = [dict(brief(c), also_edit=c["also_edit"],
                          remove="nothing in this file: the orchestrator deletes it; fix only the also_edit sites"
                          if c["kind"] == "file" else "the declaration")
                     for c in chunk if c["kind"] != "file" or c["also_edit"]]
            write_json(lg.unit_path(unit), {
                "unit": unit, "stage": "remove", "wave": wave, "root": str(lg.root),
                "output": str(lg.out_path(unit, "remove")), "allowed_files": allowed,
                "deleted_by_orchestrator": deletes, "edits": edits,
            })
            lg.state["units"][unit] = {"id": unit, "stage": "remove", "status": "ready", "round": lg.state["round"],
                                       "lens": None, "wave": wave, "retries": 0, "items": len(chunk),
                                       "candidates": [c["id"] for c in chunk], "agent": bool(edits),
                                       "allowed": allowed, "deletes": deletes}
            for c in chunk:
                c["unit"] = unit
                set_status(c, "planned")
    print(f"{len(dead)} dead candidate(s) planned in {sum(load.values())} removal unit(s) over {len(load)} wave(s)")


# --------------------------------------------------------------------- ingest

def cmd_ingest(args) -> None:
    lg = Ledger(git_root()).load()
    {"scan": ingest_scan, "verify": ingest_verify, "remove": ingest_remove}[args.stage](lg)


def jsonl(path: Path):
    """Yield (line number, object or error message) for each non-blank line of a JSONL file."""
    for n, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError as err:
            yield n, f"not JSON ({err.msg})"
            continue
        yield n, d if isinstance(d, dict) else "not a JSON object"


def stray_step(lg: Ledger) -> str:
    """The next step, unless an agent of a read-only stage changed the working tree."""
    changed = changed_paths(lg.root)
    if changed:
        print(f"warning: {len(changed)} path(s) changed during a read-only stage, e.g. {changed[0]}")
        return "ledger.py check"
    return next_step(lg)


def requeue(u: dict, why: str) -> None:
    u["retries"] += 1
    u["status"] = "failed" if u["retries"] >= MAX_RETRIES else "ready"
    print(f"{u['id']}: {why}; " + ("given up" if u["status"] == "failed" else "ready to dispatch again"))


def ingest_scan(lg: Ledger) -> None:
    units = lg.units("scan", "dispatched")
    if not units:
        die("no dispatched scan unit; run `ledger.py dispatch scan` first")
    added = 0
    for u in units:
        out = lg.out_path(u["id"], "scan")
        if not out.exists():
            requeue(u, "no output file")
            continue
        files = set(u["files"])
        good, errors = 0, []
        for n, d in jsonl(out):
            if isinstance(d, str):
                errors.append(f"line {n}: {d}")
                continue
            if "skipped" in d:
                lg.state["skipped"].setdefault("unread by its scanner", {})[str(d["skipped"])] = 1
                continue
            problems = [msg for ok, msg in (
                (d.get("file") in files, "`file` is not in this shard"),
                (isinstance(d.get("line"), int) and d["line"] > 0, "`line` must be a positive integer"),
                (isinstance(d.get("symbol"), str) and WORD.search(d["symbol"]), "`symbol` must be a name"),
                (d.get("kind") in SCAN_KINDS, f"`kind` must be one of {', '.join(sorted(SCAN_KINDS))}"),
            ) if not ok]
            if problems:
                errors.append(f"line {n}: " + "; ".join(problems))
                continue
            good += 1
            markers = [str(m)[:80] for m in d.get("markers", []) if isinstance(d.get("markers"), list)][:5]
            added += bool(add_candidate(lg, file=d["file"], symbol=d["symbol"], kind=d["kind"], line=d["line"],
                                        source="scan", detail="scanner", markers=markers,
                                        exported=d["exported"] if isinstance(d.get("exported"), bool) else None))
        if errors and len(errors) > good:
            requeue(u, f"{len(errors)} invalid line(s), first: {errors[0]}")
            continue
        if errors:
            print(f"{u['id']}: dropped {len(errors)} invalid line(s), first: {errors[0]}")
        u["status"] = "ingested"
    lg.state["analyzers"]["scan"] = lg.state["analyzers"].get("scan", 0) + added
    lg.save()
    print(f"scan: {added} new declaration(s) recorded")
    say_next(stray_step(lg))


def tally(c: dict) -> str:
    for lens in LENSES:
        v = c["votes"].get(lens)
        if v is None:
            return "pending"
        if v["verdict"] != "dead":
            return v["verdict"]
        if v["confidence"] < MIN_CONFIDENCE:
            return "likely-dead"
    return "dead"


def valid_edits(lg: Ledger, raw) -> list:
    edits = []
    for e in raw if isinstance(raw, list) else []:
        if isinstance(e, dict) and isinstance(e.get("file"), str):
            path = rel(lg.root, e["file"])
            if (lg.root / path).is_file():
                edits.append({"file": path, "line": e["line"] if isinstance(e.get("line"), int) else None,
                              "action": str(e.get("action", ""))[:200]})
    return edits


def ingest_verify(lg: Ledger) -> None:
    units = lg.units("verify", "dispatched")
    if not units:
        die("no dispatched verify unit; run `ledger.py dispatch verify` first")
    votes, lost_total = 0, 0
    for u in units:
        out = lg.out_path(u["id"], "verify")
        expected, seen, errors = set(u["candidates"]), set(), []
        for n, d in (jsonl(out) if out.exists() else []):
            if isinstance(d, str):
                errors.append(f"line {n}: {d}")
                continue
            cid, conf = d.get("id"), d.get("confidence")
            if cid not in expected or cid in seen:
                errors.append(f"line {n}: id {cid!r} is not an unanswered candidate of this unit")
                continue
            if d.get("verdict") not in VERDICTS or isinstance(conf, bool) or not isinstance(conf, int) \
                    or not 0 <= conf <= 100 or not str(d.get("evidence", "")).strip():
                errors.append(f"line {n}: needs verdict dead|alive|unsure, an integer confidence 0-100, evidence")
                continue
            seen.add(cid)
            c = lg.cands[cid]
            c["votes"][u["lens"]] = {"verdict": d["verdict"], "confidence": conf,
                                     "evidence": str(d["evidence"])[:600], "unit": u["id"]}
            for e in valid_edits(lg, d.get("also_edit")):
                if e not in c["also_edit"]:
                    c["also_edit"].append(e)
            set_status(c, tally(c))
            votes += 1
        for cid in expected - seen:
            c = lg.cands[cid]
            c["retries"] += 1
            if c["retries"] >= MAX_RETRIES:
                set_status(c, "unsure", f"no valid {u['lens']} vote after {c['retries']} attempts")
            else:
                set_status(c, "pending")
        lost_total += len(expected - seen)
        u["status"] = "ingested"
        if not out.exists():
            print(f"{u['id']}: no output file")
        elif errors:
            print(f"{u['id']}: {len(errors)} invalid line(s), first: {errors[0]}")
    lg.save()
    counts = Counter(lg.cands[cid]["status"] for u in units for cid in u["candidates"])
    print(f"verify: {votes} vote(s) recorded; now " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if lost_total:
        print(f"{lost_total} candidate(s) got no valid vote: back to pending, or unsure after {MAX_RETRIES} tries")
    say_next(stray_step(lg))


def ingest_remove(lg: Ledger) -> None:
    wave = lg.state.get("current_wave")
    units = [u for u in lg.units("remove", "dispatched") if u["wave"] == wave]
    if not units:
        die("no dispatched removal unit; run `ledger.py dispatch remove` first")
    changed = set(changed_paths(lg.root))
    applied = skipped = 0
    for u in units:
        result = {}
        if u.get("agent", True):
            try:
                result = read_json(lg.out_path(u["id"], "remove"))
            except ValueError as err:
                result = None
                print(f"{u['id']}: {err}")
            if not isinstance(result, dict):
                for cid in u["candidates"]:
                    c = lg.cands[cid]
                    c["retries"] += 1
                    c["unit"] = None
                    set_status(c, "dead" if c["retries"] < MAX_RETRIES else "skipped",
                               "" if c["retries"] < MAX_RETRIES else "its remover returned nothing twice")
                files = " ".join(sorted(set(u["allowed"])))
                u["status"] = "failed"
                print(f"{u['id']}: no valid output; restore its files before the gate: "
                      f"git restore --source=HEAD --staged --worktree -- {files}")
                continue
        done = {x for x in result.get("applied", []) if isinstance(x, str)}
        why = {s.get("id"): str(s.get("reason", ""))[:200] for s in result.get("skipped", []) if isinstance(s, dict)}
        for cid in u["candidates"]:
            c = lg.cands[cid]
            if c["kind"] == "file":
                if (lg.root / c["file"]).exists():
                    rm = run(["git", "rm", "-q", "--", c["file"]], lg.root, check=False)
                    if rm.returncode != 0:
                        set_status(c, "skipped", "git rm failed: " + rm.stderr.decode(errors="replace").strip())
                        skipped += 1
                        continue
                set_status(c, "applied")
                applied += 1
            elif cid not in done:
                set_status(c, "skipped", why.get(cid) or "its remover did not report it applied")
                skipped += 1
            elif c["file"] not in changed or count_term(lg.root / c["file"], term_of(c)) >= (c["refs"] or {}).get(
                    "in_file", 0):
                set_status(c, "skipped", "reported applied, but its declaration is still in the file")
                skipped += 1
            else:
                set_status(c, "applied")
                applied += 1
        lg.state["emptied"].extend(p for p in result.get("emptied_files", []) if isinstance(p, str))
        u["status"] = "ingested"
    lg.save()
    print(f"remove wave {wave}: {applied} applied, {skipped} skipped")
    say_next("ledger.py check")


# ---------------------------------------------------------------- check/settle

def changed_paths(root: Path) -> list:
    entries = run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], root).stdout \
        .decode("utf-8", "replace").split("\0")
    paths, i = [], 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC" and i < len(entries):  # a rename carries its source path next
            paths.append(entries[i])
            i += 1
    return [p for p in paths if not p.startswith(LEDGER)]


def open_removal_units(lg: Ledger) -> list:
    return [u for u in lg.units("remove", "ingested") if u["wave"] == lg.state.get("current_wave")]


def cmd_check(args) -> None:
    lg = Ledger(git_root()).load()
    units = open_removal_units(lg)
    allowed = set()
    for u in units:
        allowed.update(u["allowed"], u["deletes"])
    changed = changed_paths(lg.root)
    unexpected = sorted(p for p in changed if p not in allowed)
    inside = sorted(p for p in changed if p in allowed)
    # Whole-file deletions were staged by `git rm` in `ingest remove`; `git add` refuses a path that is gone.
    (lg.dir / "stage.txt").write_text("".join(p + "\0" for p in inside if (lg.root / p).exists()),
                                      encoding="utf-8")
    if unexpected:
        print(f"{len(unexpected)} change(s) outside the files this step may touch:")
        for p in unexpected[:30]:
            print(f"  {p}")
        say_next("restore them (`git restore --source=HEAD --staged --worktree -- <paths>`; delete untracked "
                 "ones), note which unit strayed, then `ledger.py check` again")
        sys.exit(1)
    if not units:
        print("no change in the working tree apart from the ledger")
        say_next(next_step(lg))
        return
    n = sum(1 for u in units for cid in u["candidates"] if lg.cands[cid]["status"] == "applied")
    print(f"{len(inside)} changed file(s), all inside wave {lg.state['current_wave']}; {n} removal(s) applied")
    gate = lg.state["gate"]["fast"] or lg.state["gate"]["full"]
    say_next(f"run `{gate}`. Green: `git add -A --pathspec-from-file={LEDGER}/stage.txt --pathspec-file-nul`, "
             f"commit, `ledger.py settle --ok --commit <sha>`. Red: name the unit that broke it "
             f"(`ledger.py status --wave` maps files to units), `ledger.py settle --fail <unit> --note <error>`")


def cmd_settle(args) -> None:
    lg = Ledger(git_root()).load()
    units = open_removal_units(lg)
    if not units:
        die("no removal wave is waiting for its gate")
    by_id = {u["id"]: u for u in units}
    if args.fail:
        for unit in args.fail:
            u = by_id.get(unit)
            if u is None:
                die(f"{unit} is not an open unit of wave {lg.state['current_wave']} ({', '.join(by_id)})")
            for cid in u["candidates"]:
                if lg.cands[cid]["status"] == "applied":
                    set_status(lg.cands[cid], "reverted", args.note or "the gate failed with it removed")
            u["status"] = "failed"
            print(f"{unit} reverted ({', '.join(u['candidates'])}); restore its files with:")
            print("  git restore --source=HEAD --staged --worktree -- " + " ".join(sorted(set(u["allowed"]) | set(u["deletes"]))))
        lg.save()
        say_next("restore those files, re-run the gate, then `ledger.py settle --ok --commit <sha>` "
                 "(or --fail another unit)")
        return
    if not args.ok:
        die("pass --ok (the gate is green) or --fail <unit>")
    removed = 0
    for u in units:
        for cid in u["candidates"]:
            c = lg.cands[cid]
            if c["status"] == "applied":
                set_status(c, "removed")
                c["commit"] = args.commit or None
                removed += 1
        u["status"] = "settled"
    lg.state["history"].append({"round": lg.state["round"], "wave": lg.state["current_wave"], "removed": removed,
                                "commit": args.commit or None, "at": now()})
    lg.state["current_wave"] = None
    lg.save()
    print(f"wave settled: {removed} removal(s)" + (f" in {args.commit}" if args.commit else ""))
    say_next(next_step(lg))


def cmd_confirm(args) -> None:
    lg = Ledger(git_root()).load()
    lg.state["confirmed"] = now()
    lg.save()
    print("the user approved deletions")
    say_next(next_step(lg))


def cmd_mark(args) -> None:
    lg = Ledger(git_root()).load()
    ids = [i for i in args.ids.split(",") if i]
    if args.commit:
        if len(args.commit) < 7:
            die("give at least 7 characters of the commit sha")
        ids += [c["id"] for c in lg.cands.values() if c.get("commit") and len(c["commit"]) >= 7
                and (c["commit"].startswith(args.commit) or args.commit.startswith(c["commit"]))]
    if not ids:
        die("name the candidates with --ids c0001,c0002 or --commit <sha>")
    for cid in ids:
        c = lg.cands.get(cid)
        if c is None:
            die(f"unknown candidate {cid}")
        set_status(c, args.status, args.note)
        if args.status in ("pending", "dead"):
            c["unit"], c["retries"] = None, 0
            if args.status == "pending":
                c["votes"] = {}
    lg.save()
    print(f"{len(ids)} candidate(s) marked {args.status}")
    say_next(next_step(lg))


def cmd_round(args) -> None:
    lg = Ledger(git_root()).load()
    busy = Counter(c["status"] for c in lg.cands.values() if c["status"] in IN_FLIGHT)
    if busy and not args.force:
        die("the round is not finished: " + ", ".join(f"{k} {v}" for k, v in busy.items()))
    removed = sum(h["removed"] for h in lg.state["history"] if h["round"] == lg.state["round"])
    if removed == 0 or lg.state["round"] >= lg.state["max_rounds"]:
        lg.state["finished"] = True
        lg.save()
        print(f"round {lg.state['round']} " + ("removed nothing: fixed point reached" if removed == 0
                                                 else f"was the last of {lg.state['max_rounds']}"))
        say_next("ledger.py report")
        return
    lg.state["round"] += 1
    lg.save()
    print(f"round {lg.state['round']} started: last round's {removed} removal(s) may have orphaned more code")
    say_next("re-run the same analyzers and `ledger.py import` them, then `ledger.py refs`")


# ------------------------------------------------------------- status/report

def next_step(lg: Ledger) -> str:
    st = lg.state
    statuses = Counter(c["status"] for c in lg.cands.values())
    dispatched = lg.units(status="dispatched")
    if dispatched:
        return f"wait for the {dispatched[0]['stage']} workflow to complete, then `ledger.py ingest {dispatched[0]['stage']}`"
    if open_removal_units(lg):
        return "ledger.py check"
    if lg.units("scan", "ready"):
        return "ledger.py dispatch scan"
    if statuses["new"] or (lg.cands and st.get("refs_round") != st["round"]):
        return "ledger.py refs"
    if statuses["pending"]:
        return "ledger.py dispatch verify"
    if st["finished"] or st["mode"] == "report":
        return "ledger.py report"
    if statuses["dead"] or lg.units("remove", "ready"):
        if not st["confirmed"]:
            return ("`ledger.py report`, show the user its summary and ask before deleting anything; "
                    "on yes, `ledger.py confirm`")
        return "ledger.py dispatch remove"
    if any(h["round"] == st["round"] for h in st["history"]):
        gate = st["gate"]["full"] or st["gate"]["fast"]
        return (f"run the full gate `{gate}`; green: `ledger.py round`; red: `git bisect run` it over this "
                f"round's commits, `git revert` the culprit, then `ledger.py mark --commit <sha> --status reverted`")
    return "ledger.py round"


def cmd_status(args) -> None:
    lg = Ledger(git_root()).load()
    st = lg.state
    statuses = Counter(c["status"] for c in lg.cands.values())
    print(f"round {st['round']}/{st['max_rounds']} | mode {st['mode']} | scope {', '.join(st['scope']) or 'all'} "
          f"| branch {st['branch']} from {st['base_sha'][:12]}")
    print("candidates: " + (", ".join(f"{k} {v}" for k, v in sorted(statuses.items())) or "none"))
    units = Counter(f"{u['stage']}:{u['status']}" for u in st["units"].values())
    if units:
        print("units: " + ", ".join(f"{k} {v}" for k, v in sorted(units.items())))
    print(f"gate: fast={st['gate']['fast'] or '-'} | full={st['gate']['full'] or '-'}")
    commits = [h["commit"] for h in st["history"] if h["round"] == st["round"] and h.get("commit")]
    if commits:
        print("this round's wave commits, oldest first: " + " ".join(commits))
    if args.wave:
        for u in open_removal_units(lg):
            print(f"  {u['id']}: " + " ".join(u["allowed"]) + (f" | deletes {' '.join(u['deletes'])}" if u["deletes"] else ""))
    say_next(next_step(lg))


def votes_line(c: dict) -> str:
    parts = [f"{lens}: {v['verdict']} {v['confidence']} ({v['evidence']})"
             for lens, v in ((lens, c["votes"].get(lens)) for lens in LENSES) if v]
    return "; ".join(parts) or c.get("note", "")


def cmd_report(args) -> None:
    lg = Ledger(git_root()).load()
    st = lg.state
    by = defaultdict(list)
    for c in sorted(lg.cands.values(), key=lambda c: (c["file"], c.get("line") or 0)):
        by[c["status"]].append(c)

    def loc(c):
        return f"`{c['file']}:{c['line']}`" if c.get("line") else f"`{c['file']}`"

    lines = ["# Dead code report", "",
             f"- Repository `{st['root']}`, branch `{st['branch']}` from `{st['base_sha'][:12]}`",
             f"- Scope: {', '.join(st['scope']) or 'whole repository'}; mode: {st['mode']}; round {st['round']}",
             "- Sources: " + (", ".join(f"{k} ({v})" for k, v in st["analyzers"].items()) or "none"),
             "", "## Summary", "", "| Status | Count |", "|---|---|"]
    lines += [f"| {s} | {len(by[s])} |" for s in (
        "removed", "dead", "reverted", "likely-dead", "unsure", "alive", "test-only", "protected", "dependency",
        "referenced", "skipped", "gone", "pending", "queued", "planned", "applied") if by.get(s)]
    sections = (
        ("Removed", "removed", lambda c: f"- {loc(c)} {c['kind']} `{c['symbol']}`"
                                         + (f" ({c['commit'][:12]})" if c.get("commit") else "")),
        ("Confirmed dead, not removed yet", "dead", lambda c: f"- {loc(c)} {c['kind']} `{c['symbol']}`"),
        ("Reverted: the gate proved these alive", "reverted", lambda c: f"- {loc(c)} `{c['symbol']}`: {c['note']}"),
        ("For a human: probably dead", "likely-dead", lambda c: f"- {loc(c)} `{c['symbol']}`: {votes_line(c)}"),
        ("For a human: undecided", "unsure", lambda c: f"- {loc(c)} `{c['symbol']}`: {votes_line(c)}"),
        ("Used only by tests", "test-only",
         lambda c: f"- {loc(c)} `{c['symbol']}` ({(c['refs'] or {}).get('tests', 0)} test reference(s))"),
        ("Unused dependencies: remove with the package manager, then run the gate", "dependency",
         lambda c: f"- `{c['symbol']}` in `{c['file']}` ({', '.join(c['sources'])})"),
        ("Unreferenced, but under a protected path", "protected", lambda c: f"- {loc(c)} `{c['symbol']}`"),
        ("Skipped by the remover", "skipped", lambda c: f"- {loc(c)} `{c['symbol']}`: {c['note']}"),
    )
    for title, status, fmt in sections:
        if by.get(status):
            lines += ["", f"## {title}", ""] + [fmt(c) for c in by[status]]
    if st["emptied"]:
        lines += ["", "## Files left without declarations", ""] + [f"- `{p}`" for p in sorted(set(st["emptied"]))]
    lines += ["", "## Coverage", ""]
    for reason, tops in sorted(st["skipped"].items()):
        lines.append(f"- not scanned, {reason}: " + ", ".join(f"`{d}` ({n})" for d, n in sorted(tops.items())[:12]))
    agents = Counter(u["stage"] for u in st["units"].values())
    lines.append("- agent units: " + (", ".join(f"{k} {v}" for k, v in sorted(agents.items())) or "none"))
    if st["notes"]:
        lines += ["", "## Facts given to the verifiers", ""] + [f"- {n}" for n in st["notes"]]
    out = Path(args.out) if args.out else lg.dir / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {out}")
    print("summary: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(by.items())))
    for c in by.get("dead", [])[:args.examples]:
        print(f"  dead: {c['file']}:{c.get('line') or '-'} {c['kind']} {c['symbol']}")
    step = next_step(lg)
    if step == "ledger.py report":
        step = "present the summary and the report path to the user"
    elif step.startswith("`ledger.py report`"):
        step = "show the user this summary and ask before deleting anything; on yes, `ledger.py confirm`"
    say_next(step)


# ----------------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="start a run")
    s.add_argument("--scope", action="append", default=[], help="path to sweep (repeatable); default: whole repo")
    s.add_argument("--protect", action="append", default=[], help="glob reported but never removed (repeatable)")
    s.add_argument("--tests", action="append", default=[], help="extra test-file glob (repeatable)")
    s.add_argument("--gate-fast", default="", help="command run after every removal wave (typecheck, build)")
    s.add_argument("--gate-full", default="", help="command run at the end of every round (test suite)")
    s.add_argument("--note", action="append", default=[], help="fact every verifier must know (repeatable)")
    s.add_argument("--report-only", action="store_true", help="detect and verify; never remove")
    s.add_argument("--max-rounds", type=int, default=3, help="removal rounds before stopping (default 3)")
    s.add_argument("--force", action="store_true", help="start over; the old run moves to .dead-code.prev")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("note", help="add a fact every verifier must know")
    s.add_argument("text")
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("import", help="load an analyzer's output")
    s.add_argument("--tool", required=True,
                   choices=["knip", "vulture", "cargo", "staticcheck", "deadcode", "debride", "phpstan", "sarif", "tsv"])
    s.add_argument("file", help="the analyzer's output file")
    s.add_argument("--base", default="", help="directory the analyzer ran in, relative to the repo root")
    s.add_argument("--source", default="", help="name to record for --tool tsv")
    s.add_argument("--rule", action="append", default=[], help="SARIF ruleId to keep (repeatable; default all)")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("shard", help="split the files no analyzer covers into scan units")
    s.add_argument("--ext", action="append", default=[], help="only these extensions (repeatable), e.g. php")
    s.add_argument("--exclude", action="append", default=[], help="glob to leave out (repeatable)")
    s.add_argument("--max-files", type=int, default=SHARD_MAX_FILES)
    s.add_argument("--max-tokens", type=int, default=SHARD_MAX_TOKENS)
    s.set_defaults(func=cmd_shard)

    s = sub.add_parser("refs", help="count references to every open candidate")
    s.set_defaults(func=cmd_refs)

    s = sub.add_parser("dispatch", help="write the next units of a stage and print the Workflow args")
    s.add_argument("stage", choices=["scan", "verify", "remove"])
    s.set_defaults(func=cmd_dispatch)

    s = sub.add_parser("ingest", help="validate and record the agents' outputs for a stage")
    s.add_argument("stage", choices=["scan", "verify", "remove"])
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("confirm", help="record the user's go-ahead for deletions")
    s.set_defaults(func=cmd_confirm)

    s = sub.add_parser("check", help="refuse changes outside the current wave's files")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("settle", help="close the current removal wave after its gate")
    s.add_argument("--ok", action="store_true", help="the gate is green")
    s.add_argument("--fail", action="append", default=[], help="unit whose removals broke the gate (repeatable)")
    s.add_argument("--note", default="", help="the error that proved it alive")
    s.add_argument("--commit", default="", help="sha of the commit holding the wave")
    s.set_defaults(func=cmd_settle)

    s = sub.add_parser("mark", help="override candidate statuses")
    s.add_argument("--ids", default="", help="comma-separated candidate ids")
    s.add_argument("--commit", default="", help="every candidate removed in this commit")
    s.add_argument("--status", required=True, choices=["alive", "unsure", "likely-dead", "dead", "pending",
                                                        "reverted", "skipped", "test-only", "protected"])
    s.add_argument("--note", default="")
    s.set_defaults(func=cmd_mark)

    s = sub.add_parser("round", help="close the round; start the next or finish")
    s.add_argument("--force", action="store_true", help="even with candidates still in flight")
    s.set_defaults(func=cmd_round)

    s = sub.add_parser("status", help="counts and the next step")
    s.add_argument("--wave", action="store_true", help="list the files of each open removal unit")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("report", help="write the markdown report")
    s.add_argument("--out", default="", help="report path (default .dead-code/report.md)")
    s.add_argument("--examples", type=int, default=10, help="dead candidates to print as examples")
    s.set_defaults(func=cmd_report)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
