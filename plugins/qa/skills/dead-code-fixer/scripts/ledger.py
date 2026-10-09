#!/usr/bin/env python3
"""Bookkeeping for the dead-code-fixer skill.

Every candidate, vote and removal of a run lives in `.dead-code/` at the
repository root, so the orchestrating session never holds them in context and
a run survives context compaction. Agents read one unit file each and write
one output file each; this script builds the units, validates the outputs,
computes the verification tally, and decides what comes next. Every command
ends with a `next:` line.

Usage: python3 ledger.py <command> [options]   (from anywhere inside the repo)

Commands, in the order a run uses them:
  init       start a run: scope, protected paths, gate commands, mode
  gate       run the recorded fast or full gate (baseline, every wave, every round)
  note       add a fact every verifier must know (public API, conventions)
  analyze    run an analyzer, import its report, remember it for later rounds
  import     load a report you produced yourself (knip, vulture, cargo, staticcheck,
             deadcode, debride, phpstan, sarif, tsv)
  shard      split the files no analyzer covers into scan units
  refs       count references to every open candidate across tracked files
  dispatch   write the next units of a stage, print the Workflow args
  ingest     validate the agents' outputs for a stage and record them
  spotcheck  pick dead candidates for the orchestrator to re-check itself
  confirm    record the user's go-ahead for deletions (or --no)
  check      refuse working-tree changes outside the current wave's files
  commit     commit a wave after a green fast gate and settle it
  settle     close a wave by hand: --fail <unit> names the unit that broke the gate,
             --find narrows it down by re-running the gate on halves of the wave
  restore    put the files of failed or rejected units back to HEAD
  bisect     find the wave commit of a round that breaks the full gate
  mark       override statuses (adjudication, reverted commits)
  show       print candidates with ids, references and votes
  ignore     let `check` ignore artifacts of the project's build or tests
  round      close the round; start the next (with the files it emptied as candidates) or finish
  status     counts and the next step
  report     write .dead-code/report.md

Stdlib only, Python 3.8+.
"""

from __future__ import annotations

import argparse
import codecs
import fnmatch
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import urllib.parse
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

# Units per dispatch. A workflow run stops at 1,000 agents; the margin covers the run's own bookkeeping.
DISPATCH_CAP = 900

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
# coincidence, and minified bundles, source maps and lockfiles hold no first-party
# use. Everything else tracked is searched, first-party build/ and out/ included:
# an extra hit can only keep code alive, never delete it.
REFS_IGNORE = [
    "node_modules/*", "*/node_modules/*", "vendor/*", "*/vendor/*", "third_party/*", "*/third_party/*",
    "*.min.js", "*.min.css", "*.map", "*.lock", "package-lock.json", "pnpm-lock.yaml", "go.sum",
]

DEFAULT_TESTS = [
    "*.test.*", "*.spec.*", "*_test.*", "*_spec.*", "test_*.py", "conftest.py", "*.stories.*",
    "test/*", "*/test/*", "tests/*", "*/tests/*", "__tests__/*", "*/__tests__/*", "spec/*", "*/spec/*",
    "testdata/*", "*/testdata/*", "fixtures/*", "*/fixtures/*", "e2e/*", "*/e2e/*", "*/__mocks__/*",
]

# The source extensions each analyzer examines, for the report's coverage section.
ANALYZER_EXTS = {
    "knip": {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro"},
    "vulture": {".py", ".pyi"}, "cargo": {".rs"}, "staticcheck": {".go"}, "deadcode": {".go"},
    "phpstan": {".php"}, "debride": {".rb"}, "sarif": {".java", ".kt", ".kts", ".cs"},
}

KINDS = {"file", "export", "function", "method", "class", "type", "variable", "member", "dependency"}
SCAN_KINDS = {"function", "method", "class", "type", "variable", "member"}
VERDICTS = {"dead", "alive", "unsure"}
# Identifiers, Unicode included. A leading `$` (PHP properties, Kotlin and Dart string templates,
# Svelte stores) is kept as written and also counted under the bare name.
WORD = re.compile(r"\$*[^\W\d][\w$]*")
# Module names such as `old-pricing` are imported by path, so they are matched as hyphenated tokens.
HYPHENATED = re.compile(r"[\w$]+(?:-[\w$]+)+")
# `\nrefresh` in a string literal is an escape followed by `refresh`, not one identifier.
ESCAPES = re.compile(r"\\[nrtfvb0]")
# Mentions in prose are reported separately: documentation is never a use.
PROSE_EXTS = {".md", ".markdown", ".rst", ".adoc", ".org"}
PROSE_TXT = ("readme", "changelog", "changes", "history", "news", "notes", "authors", "contributing", "license")


def is_prose(path: str) -> bool:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    return suffix in PROSE_EXTS or (suffix == ".txt" and name.startswith(PROSE_TXT))
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
    """Tracked regular files; symlinks are left out so no file is read or edited twice."""
    out = run(["git", "ls-files", "-s", "-z", "--"] + (pathspecs or []), root).stdout.decode("utf-8", "replace")
    files = []
    for entry in out.split("\0"):
        meta, _, path = entry.partition("\t")
        if path and not meta.startswith("120000"):
            files.append(path)
    return files


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


def as_globs(paths: list, root: Path) -> list:
    """User path arguments as root-relative globs; a plain directory covers everything under it."""
    out = []
    for p in paths:
        g = repo_path(root, p)
        out.append(g)
        if not any(ch in g for ch in "*?[") and (root / g).is_dir():
            out.append(g.rstrip("/") + "/*")
    return out


def repo_path(root: Path, path: str) -> str:
    """A path the user typed, relative to the current directory, as a root-relative POSIX path.

    Globs are kept as typed (root-relative) when they do not name an existing path."""
    p = Path(path)
    full = p if p.is_absolute() else Path.cwd() / p
    try:
        return full.resolve().relative_to(root.resolve()).as_posix().strip("/") or "."
    except ValueError:
        return p.as_posix()


def rel(root: Path, path: str, base: str = "") -> str:
    """An analyzer's path as a repository-relative POSIX path."""
    if path.startswith("file:"):
        path = urllib.parse.unquote(urllib.parse.urlparse(path).path)
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
    name = c["symbol"].split("(", 1)[0].rsplit(".", 1)[-1].rsplit("::", 1)[-1].rsplit("#", 1)[-1]
    m = WORD.search(name)
    return m.group(0).lstrip("$") if m else ""


def tokens(line: str, hyphenated: bool = False) -> list:
    """The identifier tokens of one line; `$name` also counts as `name`."""
    line = ESCAPES.sub(" ", line)
    out = []
    for w in WORD.findall(line):
        out.append(w)
        if w.startswith("$") and len(w.lstrip("$")) > 0:
            out.append(w.lstrip("$"))
    if hyphenated:
        out.extend(HYPHENATED.findall(line))
    return out


def decode(data: bytes):
    """Text of a file, honouring UTF-8/16/32 byte-order marks; None for binary data."""
    for bom, enc in ((codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
                     (codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"),
                     (codecs.BOM_UTF16_BE, "utf-16-be")):
        if data.startswith(bom):
            return data[len(bom):].decode(enc, "ignore")
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "ignore")


def read_lines(path: Path):
    """A file's lines split on newlines only (form feeds and U+2028 stay inside a line), or None."""
    try:
        text = decode(path.read_bytes())
    except OSError:
        return None
    return None if text is None else text.replace("\r\n", "\n").split("\n")


def count_term(path: Path, term: str) -> int:
    lines = read_lines(path)
    return 0 if lines is None else sum(tokens(line).count(term) for line in lines)


def aliases(c: dict) -> set:
    """Spellings by which frameworks refer to a declaration without writing its name."""
    term = term_of(c)
    if not term or c["kind"] in ("file", "dependency"):
        return set()
    out = set()
    if c["kind"] in ("class", "type") and term[:1].isupper():
        snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", term).lower()
        out |= {snake, snake + "s", snake.replace("_", "-")}  # has_many :line_items, <line-item>
        if term.endswith("Attribute") and len(term) > len("Attribute"):
            out.add(term[: -len("Attribute")])  # C# [Foo] for FooAttribute
    if c["kind"] in ("member", "variable") and term[:1].islower():
        cap = term[:1].upper() + term[1:]
        out |= {"get" + cap, "is" + cap, "set" + cap}  # accessors generated by Lombok and friends
    out.discard(term)
    return {a for a in out if len(a) > 3}


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
    if kind != "dependency" and (not lg.in_scope(file) or matches(file, NEVER_SCAN) or file.startswith("..")):
        return None
    line = line if isinstance(line, int) and line > 0 else None
    decl = ""
    if line and kind not in ("file", "dependency"):
        lines = read_lines(lg.root / file) or []
        decl = lines[line - 1].strip()[:200] if line <= len(lines) else ""
    # Two same-named declarations in one file (methods of two classes) stay two candidates.
    key = {"file": f"{file}::<file>", "dependency": f"{file}::dep::{symbol}"}.get(kind, f"{file}::{symbol}::{decl}")
    known = lg.state["keys"]
    if key in known:
        c = lg.cands.get(known[key])
        if c is not None and source not in c["sources"]:
            c["sources"].append(source)
            c["detail"] = f"{c['detail']}; {detail}" if c["detail"] and detail else (c["detail"] or detail)
        return None
    cid = lg.next_id("c")
    lg.cands[cid] = {
        "id": cid, "key": key, "file": file, "line": line, "decl": decl,
        "symbol": symbol, "kind": kind, "sources": [source], "detail": detail,
        "markers": list(markers or []), "exported": exported,
        "status": "dependency" if kind == "dependency" else "new", "round": lg.state["round"],
        "refs": None, "votes": {}, "also_edit": [], "unit": None, "retries": 0, "commit": None, "note": "",
        "pinned": False,
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
    scope = [s for s in (repo_path(root, s) for s in args.scope) if s and s != "."]
    mode = "report" if args.report_only else "fix"
    if mode == "fix" and not (args.gate_fast or args.gate_full):
        print("no gate command: deletions could not be verified, so this run is report-only; "
              "re-run with --gate-fast/--gate-full to remove code")
        mode = "report"
    lg.state = {
        "schema": SCHEMA_VERSION, "created": now(), "root": str(root), "base_sha": head, "branch": branch,
        "scope": scope, "protect": as_globs(args.protect, root), "tests": DEFAULT_TESTS + list(args.tests),
        "gate": {"fast": args.gate_fast, "full": args.gate_full}, "mode": mode,
        "max_rounds": args.max_rounds, "round": 1, "finished": False, "confirmed": None,
        "notes": list(args.note), "analyzers": {}, "skipped": {}, "units": {}, "current_wave": None,
        "counters": {}, "keys": {}, "history": [], "emptied": [], "refs_round": None, "ignore": [], "gates": [], "restore": [],
    }
    # Whatever is already untracked was there before this run; tracked changes are never ignored.
    lg.state["ignore"] = [p for p in run(["git", "ls-files", "-o", "--exclude-standard", "-z"], root).stdout
                          .decode("utf-8", "replace").split("\0") if p and not p.startswith(LEDGER)]
    lg.save()
    print(f"run started in {lg.dir} on {branch or 'detached HEAD'} at {head[:12]}")
    if Path.cwd().resolve() != root.resolve():
        print(f"warning: the session runs in {Path.cwd()}, not at the repository root {root}: agents must read and "
              "write under the root, so start Claude Code there or `/add-dir` it")
    print(f"scope: {', '.join(scope) or 'whole repository'} | mode: {mode} | "
          f"gate: fast={args.gate_fast or '-'} full={args.gate_full or '-'}")
    say_next("baseline: `ledger.py gate fast` and `ledger.py gate full` (both must be green); then "
             "`ledger.py analyze` the analyzers that fit the stack, and `ledger.py shard --ext ...` for the "
             "languages none covers" if mode == "fix" else
             "`ledger.py analyze` the analyzers that fit the stack, then `ledger.py shard --ext ...` for the "
             "languages none covers")


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
        raise ReportError("not a knip JSON report (no `issues` key); run knip with `--reporter json`")
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
                    parent = e.get("parent") or e.get("namespace")
                    label = f"{parent}.{e['name']}" if parent else e["name"]
                    cid = add_candidate(lg, file=file, symbol=label, kind=kind, line=e.get("line"), source="knip",
                                        detail=f"knip: unused {key}")
                added += bool(cid)
    return added


VULTURE = re.compile(r"^(?P<file>.+?):(?P<line>\d+): unused (?P<what>[a-z ]+?) '(?P<name>[^']+)' "
                     r"\((?P<conf>\d+)% confidence")
VULTURE_KINDS = {"function": "function", "method": "method", "class": "class", "variable": "variable",
                 "attribute": "member", "property": "member"}


def is_parameter(path: Path, line: int, name: str) -> bool:
    """Whether `name` is a parameter of a function defined on that line."""
    lines = read_lines(path) or []
    text = lines[line - 1] if 0 < line <= len(lines) else ""
    m = re.match(r"\s*(async\s+)?def\s+\w+\s*\((.*)", text)
    return bool(m and name in WORD.findall(m.group(2).split(")")[0]))


def import_vulture(lg: Ledger, text: str, base: str) -> int:
    added = ignored = 0
    for line in text.splitlines():
        m = VULTURE.match(line.strip())
        if not m:
            continue
        kind = VULTURE_KINDS.get(m["what"])
        if kind == "variable" and is_parameter(lg.root / rel(lg.root, m["file"], base), int(m["line"]), m["name"]):
            kind = None  # vulture reports unused arguments as variables on their `def` line
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
        if len(names) != len(spans):
            names = [span_identifier(s) for s in spans]
        pairs = [(n, s) for n, s in zip(names, spans) if n]
        for name, span in pairs:
            added += bool(add_candidate(lg, file=rel(lg.root, span.get("file_name", ""), base), symbol=name,
                                        kind=kind, line=span.get("line_start"), source="cargo",
                                        detail=f"rustc: {text_msg}"))
    return added


def span_identifier(span: dict) -> str:
    """The identifier a rustc span highlights, read from the span's own source text."""
    for t in span.get("text") or []:
        piece = (t.get("text") or "")[max(0, (t.get("highlight_start") or 1) - 1):max(0, (t.get("highlight_end") or 1) - 1)]
        m = WORD.search(piece)
        if m:
            return m.group(0)
    return ""


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
        raise ReportError("not a `deadcode -json` report (expected a JSON array of packages)")
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
        raise ReportError("not a `debride --json` report (no `missing` key)")
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
        raise ReportError("not a PHPStan JSON report (run `phpstan analyse --error-format=json`)")
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


SARIF_SKIP = re.compile(r"\b(unused (formal )?parameters?|unused arguments?|unused imports?|unnecessary imports?|"
                        r"using directives?|local variables?|unusedformalparameter|unusedlocalvariable|ide0060|"
                        r"ide0005|unnecessaryimport|unusedimports?)\b")


def sarif_kind(text: str):
    t = re.sub(r"['\"`][^'\"`]*['\"`]", " ", text).lower()  # a symbol named importLegacy says nothing
    if SARIF_SKIP.search(t):
        return None  # linter territory, not a declaration this skill removes
    for words, kind in ((("method",), "method"), (("function",), "function"),
                        (("field", "property", "member", "constant"), "member"), (("class",), "class"),
                        (("type", "interface", "enum", "struct"), "type")):
        if any(w in t for w in words):
            return kind
    return "member"


def import_sarif(lg: Ledger, data, base: str, rules: list) -> int:
    if not isinstance(data, dict) or "runs" not in data:
        raise ReportError("not a SARIF log (no `runs` key)")
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
            uri = sarif_uri(run_, phys.get("artifactLocation") or {})
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


def sarif_uri(run_: dict, loc: dict, depth: int = 0) -> str:
    """A SARIF artifact location as a path: decoded, joined to its uriBaseId, or taken from artifacts[index]."""
    if not loc.get("uri") and isinstance(loc.get("index"), int):
        arts = run_.get("artifacts") or []
        if 0 <= loc["index"] < len(arts):
            loc = (arts[loc["index"]] or {}).get("location") or {}
    uri = loc.get("uri", "")
    base_id = loc.get("uriBaseId")
    if base_id and depth < 5 and not urllib.parse.urlparse(uri).scheme:
        base = ((run_.get("originalUriBaseIds") or {}).get(base_id)) or {}
        prefix = sarif_uri(run_, base, depth + 1) if base else ""
        uri = (prefix.rstrip("/") + "/" + uri) if prefix else uri
    if uri.startswith("file:"):
        return urllib.parse.unquote(urllib.parse.urlparse(uri).path)
    return urllib.parse.unquote(uri)


def identifier_at(path: Path, line, column) -> str:
    try:
        text = (read_lines(path) or [])[int(line) - 1]
    except (IndexError, TypeError, ValueError):
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


class ReportError(Exception):
    """An analyzer report the importer cannot read."""


def load_report(lg: Ledger, tool: str, text: str, base: str, source: str, rules: list) -> int:
    """Import one analyzer report; returns the number of new candidates."""
    if tool in ("knip", "deadcode", "debride", "phpstan", "sarif"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            raise ReportError(f"the {tool} report is not JSON ({err.msg}); did the analyzer print warnings into it?")
        return {"knip": lambda: import_knip(lg, data, base), "deadcode": lambda: import_deadcode(lg, data, base),
                "debride": lambda: import_debride(lg, data, base), "phpstan": lambda: import_phpstan(lg, data, base),
                "sarif": lambda: import_sarif(lg, data, base, rules)}[tool]()
    if tool == "vulture":
        return import_vulture(lg, text, base)
    if tool == "cargo":
        return import_cargo(lg, text, base)
    if tool == "staticcheck":
        return import_staticcheck(lg, text, base)
    return import_tsv(lg, text, base, source or "tsv")


def record_import(lg: Ledger, name: str, before: int) -> None:
    """Book an import and warn about findings whose files do not exist here."""
    new = [c for c in lg.cands.values() if int(c["id"][1:]) > before]
    added = len(new)
    lg.state["analyzers"][name] = lg.state["analyzers"].get(name, 0) + added
    lg.state["imported_round"] = lg.state["round"]
    missing = [c["file"] for c in new if c["kind"] != "dependency" and not (lg.root / c["file"]).exists()]
    lg.save()
    deps = sum(1 for c in lg.cands.values() if c["kind"] == "dependency")
    print(f"{name}: {added} new candidate(s); {len(lg.cands)} known, {deps} of them unused dependencies")
    if missing:
        print(f"warning: {len(missing)} finding(s) name files that do not exist, e.g. {missing[0]}: if the analyzer "
              "ran in a subdirectory, import again with --base <that directory>")


def cmd_import(args) -> None:
    lg = Ledger(git_root()).load()
    try:
        text = decode(Path(args.file).read_bytes()) or ""
    except OSError as err:
        die(f"cannot read {args.file}: {err}")
    before = lg.state["counters"].get("c", 0)
    try:
        load_report(lg, args.tool, text, args.base, args.source, args.rule)
    except ReportError as err:
        die(str(err))
    record_import(lg, args.source or args.tool, before)
    say_next(next_step(lg))


# Programs `analyze` may start for each tool. The ledger runs behind a pre-approved permission rule,
# so it refuses anything else: other commands go through the normal permission prompt and `import`.
ANALYZER_PROGRAMS = {
    "knip": {"npx", "pnpm", "pnpx", "yarn", "bunx", "knip"}, "vulture": {"uvx", "vulture", "pipx", "python", "python3"},
    "cargo": {"cargo"}, "staticcheck": {"go", "staticcheck"}, "deadcode": {"go", "deadcode"},
    "phpstan": {"phpstan", "php", "composer"}, "debride": {"debride", "bundle"},
    "sarif": {"pmd", "detekt", "detekt-cli", "dotnet", "gradle", "gradlew", "mvn", "mvnw", "jb"},
}
# What a package runner must start, so that `npx` or `go run` cannot run anything else.
ANALYZER_PACKAGES = {"knip": {"knip"}, "vulture": {"vulture"}, "debride": {"debride"},
                     "phpstan": {"phpstan", "vendor/bin/phpstan"}, "deadcode": {"golang.org/x/tools/cmd/deadcode"},
                     "staticcheck": {"honnef.co/go/tools/cmd/staticcheck"}}
RUNNERS = {"npx", "pnpx", "bunx", "uvx", "pipx", "pnpm", "yarn", "bundle", "composer", "go", "python", "python3", "php"}


def analyzer_allowed(tool: str, argv: list) -> bool:
    """Whether a command starts the analyzer it claims to: the ledger runs it behind a pre-approved rule."""
    if not argv or tool not in ANALYZER_PROGRAMS:
        return False
    program = Path(argv[0]).name
    if program not in ANALYZER_PROGRAMS[tool]:
        return False
    if tool == "cargo":
        return next((a for a in argv[1:] if not a.startswith("-")), "") in ("check", "clippy", "build")
    if tool == "sarif" and program == "dotnet":
        return next((a for a in argv[1:] if not a.startswith("-")), "") == "build"
    if program not in RUNNERS:
        return True
    words = [a for a in argv[1:] if not a.startswith("-")]
    if program in ("python", "python3"):
        return argv[1:3] == ["-m", "vulture"] and tool == "vulture"
    if program in ("pnpm", "yarn", "bundle", "composer", "pipx") and words[:1] in (["exec"], ["dlx"], ["run"]):
        words = words[1:]
    if program == "go":
        if words[:1] != ["run"]:
            return False
        words = words[1:]
    first = words[0] if words else ""
    return first.rsplit("@", 1)[0] in ANALYZER_PACKAGES.get(tool, set()) if "@" in first[1:] else \
        first in ANALYZER_PACKAGES.get(tool, set())

# Exit codes that still mean "the report is complete": knip 1 and vulture 3 mean findings.
FINDINGS_EXIT = {"knip": {0, 1}, "vulture": {0, 3}, "staticcheck": {0, 1}, "phpstan": {0, 1}, "debride": {0},
                 "deadcode": {0}, "cargo": {0, 101}, "tsv": {0}}
# SARIF producers each signal "found issues" their own way: PMD exits 4, detekt 2, a dotnet build
# with warnings 0 (1 there is a failed build, whose log is incomplete), Gradle and Maven tasks 1.
SARIF_EXIT = {"pmd": {0, 4}, "detekt": {0, 2}, "detekt-cli": {0, 2}, "dotnet": {0}}


def findings_exit(job: dict) -> set:
    if job["tool"] == "sarif":
        return SARIF_EXIT.get(Path(job["argv"][0]).name, {0, 1})
    return FINDINGS_EXIT.get(job["tool"], {0})


def cmd_analyze(args) -> None:
    """Run an analyzer, keep its report in the ledger, import it, and remember the command for later rounds."""
    lg = Ledger(git_root()).load()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if args.again:
        jobs = lg.state.get("analyzer_cmds", [])
        if not jobs:
            die("no analyzer was recorded with `ledger.py analyze`; run them again and `import` their reports")
    else:
        if not args.tool or not args.command:
            die("usage: ledger.py analyze --tool <tool> [--base DIR] [--output FILE] -- <command> [args...]")
        if not analyzer_allowed(args.tool, args.command):
            die(f"`analyze --tool {args.tool}` does not start {args.tool} as references/analyzers.md shows; run that "
                f"command yourself, write its report inside {LEDGER}/, and `ledger.py import --tool {args.tool} <report>`")
        jobs = [{"tool": args.tool, "base": args.base, "source": args.source, "rules": args.rule,
                 "output": args.output, "argv": args.command}]
    failed = []
    for job in jobs:
        cwd = lg.root / job["base"] if job["base"] else lg.root
        name = job["source"] or job["tool"]
        if not analyzer_allowed(job["tool"], job["argv"]):
            print(f"{name}: the recorded command does not start {job['tool']}; skipped")
            failed.append(name)
            continue
        dest = lg.dir / "analyzers" / f"{name}-r{lg.state['round']}.out"
        dest.parent.mkdir(exist_ok=True)
        print(f"running {name}: {' '.join(shlex.quote(a) for a in job['argv'])}")
        if job["output"]:
            (cwd / job["output"]).unlink(missing_ok=True)  # never import a report left by an earlier run
        try:
            proc = subprocess.run(job["argv"], cwd=str(cwd), capture_output=True, timeout=args.timeout)
        except FileNotFoundError:
            print(f"{name}: `{job['argv'][0]}` is not installed; cover these files with the scanners instead")
            failed.append(name)
            continue
        except subprocess.TimeoutExpired:
            print(f"{name}: timed out after {args.timeout}s; re-run with a larger --timeout or narrow it")
            failed.append(name)
            continue
        report = (cwd / job["output"]).read_bytes() if job["output"] and (cwd / job["output"]).exists() else proc.stdout
        dest.write_bytes(report)
        ok = proc.returncode in findings_exit(job)
        # Line-based tools print nothing when they find nothing; JSON and SARIF reports are never empty.
        if ok and not report.strip() and job["tool"] in ("vulture", "staticcheck", "cargo", "tsv"):
            record_import(lg, name, lg.state["counters"].get("c", 0))
            if not args.again and job not in lg.state.setdefault("analyzer_cmds", []):
                lg.state["analyzer_cmds"].append(job)
            lg.save()
            continue
        if not ok or not report.strip():
            tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-8:]
            failed.append(name)
            print(f"{name}: failed (exit code {proc.returncode}); cover its languages with the scanners:\n  "
                  + "\n  ".join(tail))
            continue
        before = lg.state["counters"].get("c", 0)
        try:
            load_report(lg, job["tool"], decode(report) or "", job["base"], job["source"], job["rules"])
        except ReportError as err:
            print(f"{name}: {err}; cover its languages with the scanners")
            failed.append(name)
            continue
        record_import(lg, name, before)
        if not args.again and job not in lg.state.setdefault("analyzer_cmds", []):
            lg.state["analyzer_cmds"].append(job)
            lg.save()
    if args.again:
        lg.state["analyzed_round"] = lg.state["round"]  # attempted: a failing analyzer must not stall the run
        lg.save()
    say_next(next_step(lg))


# ----------------------------------------------------------------------- refs

def count_references(lg: Ledger, todo: list):
    """One pass over every tracked text file, counting each candidate's name and its aliases.

    Returns ({term: {"files": Counter(path), "samples": [(path, line)], "decl": Counter((path, line))}},
    files too large to read, files that could not be decoded). `decl` counts occurrences on the
    candidates' own declaration lines, which are not uses.
    """
    terms = set()
    for c in todo:
        terms |= ({term_of(c)} | aliases(c))
    terms.discard("")
    path_terms = {t for t in terms if not WORD.fullmatch(t)}
    decl_lines = defaultdict(set)
    for c in todo:
        if c["kind"] != "file" and c.get("line"):
            decl_lines[c["file"]].add((c["line"], term_of(c)))
    found = {t: {"files": Counter(), "samples": [], "decl": Counter(), "prose": 0} for t in terms}
    too_big, unread = [], []
    for path in tracked_files(lg.root):
        if matches(path, REFS_IGNORE):
            continue
        full = lg.root / path
        try:
            if full.stat().st_size > MAX_REF_FILE_BYTES:
                too_big.append(path)
                continue
            text = decode(full.read_bytes())
        except OSError:
            unread.append(path)  # listed by git but not on disk: sparse checkout, deleted, unreadable
            continue
        if text is None:
            continue
        flat = ESCAPES.sub(" ", text)
        present = {t for w in WORD.findall(flat) for t in (w, w.lstrip("$"))} & terms
        if path_terms:
            present |= set(HYPHENATED.findall(flat)) & path_terms
        if not present:
            continue
        wanted = decl_lines.get(path, set())
        prose = is_prose(path)
        hyphenated = bool(present & path_terms)
        for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
            for word in tokens(line, hyphenated):
                if word in present:
                    f = found[word]
                    f["files"][path] += 1
                    if (n, word) in wanted:
                        f["decl"][(path, n)] += 1
                    elif prose and f["prose"] < 4:
                        f["prose"] += 1
                        f["samples"].append((path, n))
                    elif not prose and len(f["samples"]) - f["prose"] < 24:
                        f["samples"].append((path, n))
    return found, too_big, unread


DECL_HINT = re.compile(r"\b(def|class|function|fn|func|interface|type|enum|struct|trait|module|const|let|var|val|"
                       r"object|protocol|public|private|protected|internal|static|export)\b")


def relocate(lg: Ledger, c: dict) -> bool:
    """Point a candidate at the line that now declares it; False when the file or name is gone.

    Removals only delete lines, so a declaration moves up: prefer its recorded text, then a
    declaration-looking line at or above the old position, never a call site below it."""
    path = lg.root / c["file"]
    if c["kind"] == "file":
        return path.exists()
    term = term_of(c)
    lines = read_lines(path)
    if lines is None or not term:
        return False
    hits = [n for n, line in enumerate(lines, 1) if term in tokens(line)]
    if not hits:
        return False
    old = c.get("line") or 1
    same = [n for n in hits if c.get("decl") and lines[n - 1].strip()[:200] == c["decl"]]
    looks = [n for n in hits if DECL_HINT.search(lines[n - 1])]
    for pool in ([n for n in same if n <= old], same, [n for n in looks if n <= old], looks,
                 [n for n in hits if n <= old], hits):
        if pool:
            c["line"] = min(pool, key=lambda n: abs(n - old))
            break
    if not c.get("decl"):
        c["decl"] = lines[c["line"] - 1].strip()[:200]
    return True


def classify(lg: Ledger, c: dict, refs: dict) -> str:
    """Status of a candidate that no lens has judged yet, from its reference counts."""
    if lg.is_protected(c["file"]):
        return "protected"
    code = refs["other"] + refs["same_file"]
    if refs["tests"] and not code:
        return "test-only"
    if c["sources"] == ["scan"] and code:
        return "referenced"
    return "pending"


def cmd_refs(args) -> None:
    lg = Ledger(git_root()).load()
    revisit = {"new", "referenced", "alive", "unsure", "likely-dead"}
    todo = [c for c in lg.cands.values()
            if c["status"] in revisit and c["kind"] != "dependency" and not c.get("pinned")]
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
    found, too_big, unread = count_references(lg, live)
    decl_by_term = defaultdict(set)  # every declaration line of a name in a file: twins are not uses
    for c in live:
        if c["kind"] != "file" and c.get("line"):
            decl_by_term[(c["file"], term_of(c))].add(c["line"])
    moved = Counter()
    empty = {"files": Counter(), "samples": [], "decl": Counter()}
    for c in live:
        term = term_of(c)
        f = found.get(term, empty)
        decl = sum(f["decl"].get((c["file"], n), 0) for n in decl_by_term.get((c["file"], term), ()))
        in_file = f["files"].get(c["file"], 0)
        same = 0 if c["kind"] == "file" else in_file - decl  # a module naming itself does not import itself
        counts = Counter()
        samples = [s for s in f["samples"] if s[1] not in decl_by_term.get((s[0], term), ()) or s[0] != c["file"]]
        for alias in aliases(c):
            a = found.get(alias, empty)
            counts["convention"] += sum(a["files"].values())
            samples += a["samples"][:4]
        for p, n in f["files"].items():
            if p == c["file"]:
                continue
            kind = "docs" if is_prose(p) else ("tests" if lg.is_test(p) else "other")
            counts[kind] += n
        samples = sorted(samples, key=lambda s: (s[0] == c["file"], is_prose(s[0]), lg.is_test(s[0])))
        code = same + counts["tests"] + counts["other"] + counts["convention"]
        refs = {"total": code + counts["docs"], "code": code, "same_file": same, "tests": counts["tests"],
                "other": counts["other"] + counts["convention"], "docs": counts["docs"],
                "convention": counts["convention"], "in_file": in_file,
                "sample": [f"{p}:{n}" for p, n in samples[:8]]}
        if unread or too_big:
            refs["unsearched_files"] = len(unread) + len(too_big)
        before = (c.get("refs") or {}).get("total")
        c["refs"] = refs
        old = c["status"]
        if not term:
            set_status(c, "unsure", "its name cannot be searched as a token; check it by hand")
        elif old in ("alive", "unsure", "likely-dead"):
            if before is not None and refs["total"] < before:  # a removal took references away: judge again
                c["votes"], c["also_edit"], c["round"], c["retries"] = {}, [], lg.state["round"], 0
                status = classify(lg, c, refs)
                set_status(c, status, f"references dropped from {before} to {refs['total']} since its last vote")
        else:
            set_status(c, classify(lg, c, refs))
        if c["status"] != old:
            moved[f"{old}->{c['status']}"] += 1
    lg.state["refs_round"] = lg.state["round"]
    lg.state["unsearched"] = unread[:200]
    lg.save()
    print(f"references counted for {len(live)} candidate(s) over every tracked file; {gone} gone")
    if moved:
        print("moved: " + ", ".join(f"{k} {n}" for k, n in sorted(moved.items())))
    if too_big:
        print(f"not searched (over {MAX_REF_FILE_BYTES // 1_000_000} MB): " + ", ".join(too_big[:5]))
    if unread:
        print(f"warning: {len(unread)} tracked file(s) could not be read (sparse checkout?), e.g. {unread[0]}; "
              "mentions inside them were not counted")
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
        units = lg.units("verify", "ready") + plan_verify(lg)
    else:
        units = plan_remove(lg)
        if units is None:
            lg.save()
            return
    if not units:
        print(f"nothing to dispatch for {args.stage}")
        say_next(next_step(lg))
        return
    held = units[DISPATCH_CAP:]  # a workflow run stops at 1,000 agents: the rest waits for the next dispatch
    units = units[:DISPATCH_CAP]
    (lg.dir / "out").mkdir(exist_ok=True)
    for u in units:
        u["status"] = "dispatched"
        u["dispatched_at"] = now()
        # Only this dispatch's agent may author the output: drop anything written ahead of it.
        lg.out_path(u["id"], u["stage"]).unlink(missing_ok=True)
    lg.save()
    agent_units = [u["id"] for u in units if u.get("agent", True)]
    if not agent_units:
        print("this wave only deletes whole files; no agent is needed")
        say_next("ledger.py ingest remove")
        return
    print(f"{len(agent_units)} {args.stage} unit(s) dispatched" + (f"; {len(held)} more wait for the next dispatch"
                                                                   if held else ""))
    print("workflow-args: " + json.dumps({"stage": args.stage, "ledger": str(lg.dir), "units": agent_units}))
    say_next(f"start the `devx-qa:dead-code-fanout` workflow with exactly those args; when its completion notice "
             f"arrives, `ledger.py ingest {args.stage}`")


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
    if spotcheck_due(lg):
        print("spot-check the dead candidates before deleting anything")
        say_next("ledger.py spotcheck")
        return None
    if not lg.state.get("confirmed"):
        print("deletions need the user's go-ahead first")
        say_next(next_step(lg))
        return None
    if open_removal_units(lg):
        print(f"wave {lg.state['current_wave']} is waiting for its gate")
        say_next(next_step(lg))
        return None
    if baseline_step(lg):
        die(f"no green baseline yet: {baseline_step(lg)}")
    ready = lg.units("remove", "ready")
    if not ready:
        build_removal_waves(lg)
        ready = lg.units("remove", "ready")
    if not ready:
        return []
    dirty = changed_paths(lg, untracked=False)
    if dirty:
        print(f"{len(dirty)} tracked file(s) changed since the last commit, e.g. {dirty[0]}")
        say_next("each wave is checked against its own diff: `ledger.py check` lists the changes outside a wave and "
                 "`ledger.py restore` puts them back; then `ledger.py dispatch remove` again")
        return None
    wave = min(u["wave"] for u in ready)
    lg.state["current_wave"] = wave
    units = [u for u in ready if u["wave"] == wave]
    for u in units:  # earlier waves may have shifted lines: point every edit at its declaration again
        spec = read_json(lg.unit_path(u["id"]))
        for e in spec["edits"]:
            c = lg.cands.get(e["id"])
            if c and c["kind"] != "file" and relocate(lg, c):
                e["line"] = c["line"]
        write_json(lg.unit_path(u["id"]), spec)
    return units


def build_removal_waves(lg: Ledger) -> None:
    dead = [c for c in lg.cands.values() if c["status"] == "dead"]
    if not dead:
        return
    dying = {c["file"] for c in dead if c["kind"] == "file"}
    for c in dead:  # sites inside files that are about to disappear need no edit
        c["also_edit"] = [e for e in c["also_edit"] if e["file"] not in dying and (lg.root / e["file"]).exists()]
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
        # A declaration inside a dead file goes with that file: it is never edited separately.
        files = [c for c in members if c["kind"] == "file"]
        covered = {c["id"]: next(f["id"] for f in files if f["file"] == c["file"])
                   for c in members if c["kind"] != "file" and c["file"] in dying}
        rest = sorted((c for c in members if c["id"] not in covered), key=lambda c: (c["file"], c.get("line") or 0))
        wave = base
        for i in range(0, len(rest), REMOVE_BATCH):
            chunk = rest[i:i + REMOVE_BATCH]
            riders = [lg.cands[cid] for cid, fid in covered.items() if fid in {c["id"] for c in chunk}]
            wave += 1  # chunks of one component share files, so they never share a wave
            while load[wave] >= WAVE_UNITS:
                wave += 1
            load[wave] += 1
            unit = lg.next_id("r")
            deletes = sorted(c["file"] for c in chunk if c["kind"] == "file")
            edit_files = sorted(set().union(*(files_of(c) for c in chunk)) - set(deletes))
            edits = [dict(brief(c), also_edit=c["also_edit"],
                          remove="nothing in this file: the orchestrator deletes it; fix only the also_edit sites"
                          if c["kind"] == "file" else "the declaration")
                     for c in chunk if c["kind"] != "file" or c["also_edit"]]
            write_json(lg.unit_path(unit), {
                "unit": unit, "stage": "remove", "wave": wave, "root": str(lg.root),
                "output": str(lg.out_path(unit, "remove")), "allowed_files": edit_files,
                "deleted_by_orchestrator": deletes, "edits": edits,
            })
            lg.state["units"][unit] = {"id": unit, "stage": "remove", "status": "ready", "round": lg.state["round"],
                                       "lens": None, "wave": wave, "retries": 0, "items": len(chunk) + len(riders),
                                       "candidates": [c["id"] for c in chunk + riders], "agent": bool(edits),
                                       "allowed": edit_files, "deletes": deletes,
                                       "covered": {c["id"]: covered[c["id"]] for c in riders}}
            for c in chunk + riders:
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
    changed = changed_paths(lg)
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
        good, errors, skipped = 0, [], 0
        for n, d in jsonl(out):
            if isinstance(d, str):
                errors.append(f"line {n}: {d}")
                continue
            if "skipped" in d:
                lg.state.setdefault("unscanned", {})[str(d["skipped"])[:300]] = str(d.get("reason", ""))[:120]
                skipped += 1
                continue
            problems = [msg for ok, msg in (
                (d.get("file") in files, "`file` is not in this shard"),
                (isinstance(d.get("line"), int) and not isinstance(d.get("line"), bool) and d["line"] > 0,
                 "`line` must be a positive integer"),
                (isinstance(d.get("symbol"), str) and WORD.search(d["symbol"]), "`symbol` must be a name"),
                (d.get("kind") in SCAN_KINDS, f"`kind` must be one of {', '.join(sorted(SCAN_KINDS))}"),
            ) if not ok]
            if problems:
                errors.append(f"line {n}: " + "; ".join(problems))
                continue
            good += 1
            raw = d.get("markers")
            markers = [str(m)[:80] for m in raw][:5] if isinstance(raw, list) else []
            added += bool(add_candidate(lg, file=d["file"], symbol=d["symbol"], kind=d["kind"], line=d["line"],
                                        source="scan", detail="scanner", markers=markers,
                                        exported=d["exported"] if isinstance(d.get("exported"), bool) else None))
        if errors and len(errors) > good:
            requeue(u, f"{len(errors)} invalid line(s), first: {errors[0]}")
            continue
        if not good and not skipped and not errors and any((lg.root / f).stat().st_size > 200
                                                          for f in files if (lg.root / f).exists()):
            requeue(u, "empty output for a shard with code in it")
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


def editable(lg: Ledger, path: str, tracked: set) -> bool:
    """Whether a remover may touch this path: tracked, first-party, unprotected, inside the repository."""
    return (path in tracked and not path.startswith(("..", "/", ".git/", LEDGER))
            and not matches(path, NEVER_SCAN) and not lg.is_protected(path))


def valid_edits(lg: Ledger, raw, tracked: set) -> list:
    edits = []
    for e in raw if isinstance(raw, list) else []:
        if isinstance(e, dict) and isinstance(e.get("file"), str):
            path = rel(lg.root, e["file"])
            if editable(lg, path, tracked):
                line = e.get("line")
                ok_line = isinstance(line, int) and not isinstance(line, bool) and line > 0
                edits.append({"file": path, "line": line if ok_line else None,
                              "action": str(e.get("action", ""))[:200]})
    return edits


def ingest_verify(lg: Ledger) -> None:
    units = lg.units("verify", "dispatched")
    if not units:
        die("no dispatched verify unit; run `ledger.py dispatch verify` first")
    votes, lost_total, no_output = 0, 0, []
    tracked = set(tracked_files(lg.root))
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
            if c["status"] != "queued":
                continue  # marked by the orchestrator while the unit ran: its decision stands
            evidence = str(d["evidence"])[:600]
            c["votes"][u["lens"]] = {"verdict": d["verdict"], "confidence": conf, "evidence": evidence,
                                     "unit": u["id"]}
            c["retries"] = 0
            for e in valid_edits(lg, d.get("also_edit"), tracked):
                if e not in c["also_edit"]:
                    c["also_edit"].append(e)
            status = tally(c)
            if status == "alive" and evidence.lower().lstrip("`*_ ").startswith("test-only"):
                status = "test-only"  # used by tests alone: reported for a human, never deleted
            set_status(c, status)
            votes += 1
        for cid in expected - seen:
            c = lg.cands[cid]
            if c["status"] != "queued":
                continue
            c["retries"] += 1
            if c["retries"] >= MAX_RETRIES:
                set_status(c, "unsure", f"no valid {u['lens']} vote after {c['retries']} attempts")
            else:
                set_status(c, "pending")
        lost_total += len(expected - seen)
        u["status"] = "ingested"
        if not out.exists():
            no_output.append(u["id"])
        elif errors:
            print(f"{u['id']}: {len(errors)} invalid line(s), first: {errors[0]}")
    lg.save()
    counts = Counter(lg.cands[cid]["status"] for u in units for cid in u["candidates"])
    print(f"verify: {votes} vote(s) recorded; now " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if lost_total:
        print(f"{lost_total} candidate(s) got no valid vote: back to pending, or unsure after {MAX_RETRIES} tries")
    if no_output and len(no_output) == len(units):
        print("no unit wrote an output file: the agents may lack permission to Write into "
              f"{lg.dir / 'out'}, or the workflow has not finished")
    elif no_output:
        print("units without an output file: " + ", ".join(no_output))
    say_next(stray_step(lg))


# Lines that declare a name, across the languages the skill meets. Used to catch a remover
# that deleted a declaration it was not given.
DECLARES = (
    re.compile(r"^(\s*)(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
               r"(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(?:extern\s+\"[^\"]*\"\s+)?(?:static\s+)?"
               r"(?:def\s+(?:self\.)?|(?:const\s+)?(?:fn|enum)\s+|(?:class|function\*?|func|interface|type|struct|"
               r"trait|module|const|let|var|val|object|protocol)\s+)(?:\([^)]*\)\s*)?([A-Za-z_$][\w$]*)"),
    re.compile(r"^(\s*)(?:(?:public|private|protected|internal|static|final|abstract|override|virtual|async|"
               r"sealed|readonly|open)\s+)+[\w<>\[\],.?]+\s+([A-Za-z_]\w*)\s*\("),
    # Members without a keyword: TypeScript class methods, Java package-private methods.
    re.compile(r"^(\s+)(?:[\w<>\[\],.?]+\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[^{]+)?\{"),
)
NOT_NAMES = {"if", "for", "while", "switch", "catch", "return", "else", "do", "try", "with", "elif", "function"}
# Top-level import and export forms: deleting one serves a removed declaration.
DEPENDENT = re.compile(r"^(import\b|from\s+\S+\s+import\b|use\s|using\s|require(_relative)?\b|#include\b|"
                       r"export\s*[{*]|export\s+default\s+[\w$]+\s*;?\s*$|@import\b|"
                       r"(const|let|var)\s+[\w${}, ]+=\s*require\()")
# Openers of multi-line import blocks: Go `import (`, Python `from x import (`, JS `import {`, Rust `use a::{`.
IMPORT_OPEN = re.compile(r"^(import\s*\(|from\s+\S+\s+import\s*\(|import\s*(type\s*)?\{|export\s*\{|use\s+[\w:]+::\{|"
                         r"(const|let|var)\s*\{)")


def declared(line: str):
    for pattern in DECLARES:
        m = pattern.match(line)
        if m and m.group(2) not in NOT_NAMES:
            return len(m.group(1).expandtabs(4)), m.group(2)
    return None


def in_import_block(head: list, n: int) -> bool:
    """Whether line n (1-based) of the committed file sits inside a multi-line import or export block."""
    for i in range(n, max(0, n - 80), -1):
        text = head[i - 1]
        if IMPORT_OPEN.match(text):
            return True
        if i != n and (re.match(r"^\s*[)}]", text) or (text[:1].strip() and not text.startswith(("#", "//")))):
            return False
    return False


def indent_of(text: str) -> int:
    return len(text.expandtabs(4)) - len(text.expandtabs(4).lstrip())


def bracket_end(head: list, a: int):
    """Line where the brackets opened at line a close again, or None."""
    depth = 0
    for i in range(a, min(len(head), a + 5000) + 1):
        depth += sum(head[i - 1].count(ch) for ch in "{([") - sum(head[i - 1].count(ch) for ch in "})]")
        if depth <= 0:
            return i
    return None


def block_end(head: list, a: int, indent: int) -> int:
    """Last line of the block indented under line a. Triple-quoted strings and comments written
    shallower than the block (a column-0 `#`) do not end it."""
    end, quote = a, None
    for i in range(a + 1, len(head) + 1):
        text = head[i - 1]
        if quote:
            end = i
            if text.count(quote) % 2:
                quote = None
            continue
        if not text.strip():
            continue
        ind = indent_of(text)
        if ind <= indent and text.strip().startswith(("#", "//")):
            code = next((j for j in range(i + 1, len(head) + 1)
                         if head[j - 1].strip() and not head[j - 1].strip().startswith(("#", "//"))), None)
            if code and indent_of(head[code - 1]) > indent:
                continue
        if ind > indent:
            end = i
            quote = next((q for q in ('"""', "\'\'\'") if text.count(q) % 2), None)
            continue
        if ind == indent and text.strip() in ("end", "end;", "}", "};", ")", "]", "fi", "esac"):
            end = i
        break
    return end


def extent(head: list, a: int) -> tuple:
    """First and last line (1-based) of the declaration at line a: its comments and decorators,
    its signature, however many lines it spans, and its body."""
    line = head[a - 1]
    indent = indent_of(line)
    start = a
    while start > 1:
        prev = head[start - 2].strip()
        if prev and not prev.startswith("#!") and prev.startswith(("@", "#[", "#", "//", "/*", "*", "--", "[")):
            start -= 1
        elif prev.startswith((")", "]")):  # the end of a multi-line decorator or attribute
            depth, j = 0, start - 1
            while j >= 1:
                t = head[j - 1]
                depth += sum(t.count(ch) for ch in "})]") - sum(t.count(ch) for ch in "{([")
                if depth <= 0:
                    break
                j -= 1
            if j >= 1 and head[j - 1].strip().startswith(("@", "#[")):
                start = j
            else:
                break
        else:
            break
    opens = sum(line.count(ch) for ch in "{([") - sum(line.count(ch) for ch in "})]")
    nxt = next((i for i in range(a + 1, min(len(head), a + 3) + 1) if head[i - 1].strip()), None)
    if not (opens > 0 or (nxt and head[nxt - 1].strip().startswith(("{", "where")))):
        return start, block_end(head, a, indent)
    if opens <= 0 and "}" in line:
        return start, a
    i = bracket_end(head, a) if opens > 0 else a
    if i is None:
        return start, len(head)
    tail = head[i - 1].split(" #")[0].split("//")[0].rstrip()
    if "{" in "".join(head[a - 1:i]) and tail.endswith("}"):
        return start, i  # the body closed with the signature's brackets
    if tail.endswith((":", "=")):  # Python `) -> T:`, Kotlin `) =`
        return start, block_end(head, i, indent)
    j = next((k for k in range(i + 1, len(head) + 1) if head[k - 1].strip()), None)
    if j and head[j - 1].strip().startswith(("where", "{")):  # Rust `where`, a brace on its own line
        k = next((k for k in range(j, len(head) + 1) if "{" in head[k - 1]), None)
        if k:
            return start, bracket_end(head, k) or len(head)
    if j and indent_of(head[j - 1]) > indent:  # Ruby `def f(a,\n b)`, then an indented body
        return start, block_end(head, i, indent)
    return start, i


def hunks(root: Path, path: str) -> list:
    """(first old line, deleted lines, added lines) for each hunk of the working tree against HEAD."""
    out = run(["git", "diff", "-U0", "--no-color", "--no-ext-diff", "HEAD", "--", path], root, check=False).stdout
    found, cur = [], None
    for raw in out.decode("utf-8", "replace").splitlines():
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", raw)
        if m:
            cur = (int(m.group(1)), [], [])
            found.append(cur)
        elif cur is not None and raw.startswith("-") and not raw.startswith("---"):
            cur[1].append(raw[1:])
        elif cur is not None and raw.startswith("+") and not raw.startswith("+++"):
            cur[2].append(raw[1:])
    return found


def head_lines(lg: Ledger, path: str) -> list:
    data = run(["git", "show", f"HEAD:{path}"], lg.root, check=False).stdout
    return (decode(data) or "").replace("\r\n", "\n").split("\n")


# Imports that run code when loaded instead of binding a name: deleting one changes behavior
# even when nothing else changes, so it never counts as serving a removed declaration.
SIDE_EFFECT = re.compile(r"""^(import\s*['"]|import\s+_\s|_\s+"|require\s*\(|require(_relative)?\s|export\s*\*\s*from\b|"""
                         r"""@import\b)""")
# Python's `import a.b` loads a submodule, often to register something (`import app.signals`).
PY_SUBMODULE = re.compile(r"^import\s+\w+(\.\w+)+\s*$")
# Words that only wire a name into a list, an export or a visibility change.
LINK_WORDS = {"export", "exports", "module", "default", "__all__", "pub", "mod", "as", "type", "private", "protected",
              "public", "module_function", "self"}


def bound_names(text: str) -> set:
    """Names an import or require line binds, or an empty set when it cannot tell."""
    line = re.sub(r"""(["'`])(?:\\.|(?!\1).)*\1""", " ", text.strip())  # module paths are strings
    m = re.match(r"^from\s+\S+\s+import\s+(.*)", line)
    if m:  # Python `from m import a, b as c`
        return {x.split()[-1] for x in m.group(1).strip("()\\ ").split(",") if x.strip() and x.strip() != "*"}
    m = re.match(r"^import\s+(?:type\s+)?(.*?)\s+from\b", line)
    if m:  # JS `import x, { a as b } from "m"`, `import * as ns from "m"`
        return {x.split()[-1] for x in re.split(r"[,{}]", m.group(1)) if x.strip() and x.strip() != "*"}
    m = re.match(r"^(?:const|let|var)\s+(.*?)=\s*require\(", line)
    if m:
        return {x.split(":")[-1].strip() for x in m.group(1).strip("{} ").split(",") if x.strip()}
    m = re.match(r"^(?:pub\s+)?use\s+(.*?);?$", line)
    if m:  # Rust `use a::{b, c as d};`, PHP `use A\\B;`
        body = m.group(1)
        inner = re.search(r"\{(.*)\}", body)
        parts = inner.group(1).split(",") if inner else [re.split(r"::|\\\\", body)[-1]]
        return {x.split()[-1].split("::")[-1] for x in parts if x.strip() and x.strip() != "*"}
    m = re.match(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*;?$", line)
    if m:  # Python `import json`, Java `import a.b.C;`
        return {m.group(2) or (m.group(1).split(".")[-1] if line.endswith(";") else m.group(1).split(".")[0])}
    return set()


def serves(text: str, n: int, head: list, names: set, after: set, sites: list, readded=frozenset(),
           python: bool = False) -> bool:
    """Whether deleting line n of the committed file followed from removing `names`. `readded` holds
    the words of the lines the same hunk put back (an import that keeps some of its names)."""
    line = re.sub(r"\s+(#|//).*$", "", text.strip())  # a trailing comment
    words = set(tokens(line)) | set(tokens(line, hyphenated=True))
    if DEPENDENT.match(line) or in_import_block(head, n):
        if names & words:
            return True  # the import or re-export of a removed name or file
        if SIDE_EFFECT.match(line) or (python and PY_SUBMODULE.match(line)) or \
                (in_import_block(head, n) and line.startswith("_")):
            return False
        bound = bound_names(line) if DEPENDENT.match(line) else {w for w in words if w not in ("as", "type")}
        return not ((bound - readded) & after)  # left unused by the deletion; a compiler checks the forms it cannot read
    if declared(line):
        return False  # a declaration outside the planned ones, even one with a planned name
    if not names & words:
        return False
    if not words - names - LINK_WORDS:
        return True  # `stale,` in an export list, `"stale",` in __all__
    return any(abs(n - s) <= 10 for s in sites)  # a registration the verifiers listed


def wrappers(head: list, spans: list, names: set) -> list:
    """Blocks that wrap only removed declarations, or extend a removed type, so go with them:
    Go `const (` groups, Rust `impl Name` and Swift `extension Name` blocks."""
    out = []
    for n, text in enumerate(head, 1):
        line = text.strip()
        opener = re.match(r"^(?:(?:pub|export)\s+)?(?:const|var|let|type|enum|object|class)\b[^=]*[({]\s*$", line)
        extends = re.match(r"^(?:unsafe\s+)?(?:impl\b.*|extension\s+.*)[{]\s*$", line)
        if not (opener or extends) or any(s <= n <= e for s, e in spans):
            continue
        end = bracket_end(head, n)
        if not end or end <= n:
            continue
        if extends and names & set(tokens(line.split(" for ")[-1])):
            out.append((n, end))
            continue
        inner = [i for i in range(n + 1, end) if head[i - 1].strip() and not head[i - 1].strip().startswith(("//", "#"))]
        if opener and inner and all(any(s <= i <= e for s, e in spans) for i in inner):
            out.append((n, end))
    return out


def stray_deletions(lg: Ledger, u: dict, applied: list) -> list:
    """What a removal unit changed beyond deleting its declarations and the lines that served them."""
    names = {term_of(c) for c in applied} - {""}
    problems = []
    for path in u["deletes"]:
        if run(["git", "diff", "--quiet", "HEAD", "--", path], lg.root, check=False).returncode == 1:
            problems.append(f"{path} was edited, but the orchestrator deletes it")
    for path in sorted(set(u["allowed"]) - set(u["deletes"])):
        head = head_lines(lg, path)
        spans = [extent(head, c["line"]) for c in applied
                 if c["file"] == path and c["kind"] != "file" and isinstance(c.get("line"), int) and 0 < c["line"] <= len(head)]
        spans += wrappers(head, spans, {term_of(c) for c in applied if c["file"] == path and c["kind"] != "file"})
        sites = [e["line"] for c in applied for e in c.get("also_edit", []) if e["file"] == path and e.get("line")]
        after = set(tokens("\n".join(read_lines(lg.root / path) or [])))
        for first, deleted, added in hunks(lg.root, path):
            gone = [(first + i, text) for i, text in enumerate(deleted)]
            # A planned deletion may leave a neighbour's separator to fix (`RED,` -> `RED;`, `a: 1,` -> `a: 1`).
            loose = len(deleted) > len(added) and any(s <= n <= e for n, _ in gone for s, e in spans)
            same = (lambda x, y: x.rstrip().rstrip(",;") == y.rstrip().rstrip(",;")) if loose else \
                (lambda x, y: x.rstrip() == y.rstrip())
            fresh = []
            for line in added:  # a line deleted and re-added unchanged (final newline, CRLF) is no change
                twin = next((k for k, (_, d) in enumerate(gone) if same(d, line)), None)
                if twin is None:
                    fresh.append(line)
                else:
                    gone.pop(twin)
            if not any(t.strip() for _, t in gone) and not any(t.strip() for t in fresh):
                continue  # blank lines only
            where = f"{path}:{first}"
            kept_words = set(tokens("\n".join(t for _, t in gone)))
            if any(set(tokens(line)) - kept_words for line in fresh if line.strip()):
                problems.append(f"{where} adds code")
                continue
            readded = set(tokens("\n".join(fresh)))
            python = path.endswith((".py", ".pyi"))
            served = [not t.strip() or serves(t, n, head, names, after, sites, readded, python) for n, t in gone]
            if any(line.strip() for line in fresh) and not all(served):
                problems.append(f"{where} rewrites code instead of deleting it")
                continue
            ok = [good or any(s <= n <= e for s, e in spans) for (n, _), good in zip(gone, served)]
            bad = next(((n, t) for (n, t), good in zip(gone, ok) if not good), None)
            if bad:
                d = declared(bad[1])
                problems.append(f"{path}:{bad[0]} deletes " + (f"`{d[1]}`, which this unit does not remove"
                                                               if d and d[1] not in names else
                                                               "code outside the planned declarations"))
    return problems


def ingest_remove(lg: Ledger) -> None:
    wave = lg.state.get("current_wave")
    units = [u for u in lg.units("remove", "dispatched") if u["wave"] == wave]
    if not units:
        die("no dispatched removal unit; run `ledger.py dispatch remove` first")
    changed = set(changed_paths(lg))
    applied = skipped = rejected = 0
    restores = []
    for u in units:
        result = {}
        if u.get("agent", True):
            try:
                result = read_json(lg.out_path(u["id"], "remove"))
            except ValueError as err:
                result = None
                print(f"{u['id']}: {err}")
            if not isinstance(result, dict):
                fail_unit(lg, u, "its remover returned nothing usable")
                restores.append(u)
                print(f"{u['id']}: no valid output")
                continue
        done = {x for x in listed(result, "applied") if isinstance(x, str)}
        why = {s.get("id"): str(s.get("reason", ""))[:200] for s in listed(result, "skipped") if isinstance(s, dict)}
        covered = u.get("covered", {})
        ok, blocked_files = [], set()
        for cid in u["candidates"]:
            c = lg.cands[cid]
            if cid in covered:
                continue  # decided with the file that holds it
            if c["kind"] == "file":
                if cid in why:  # the remover could not fix the files that import it: keep the file
                    set_status(c, "skipped", why[cid] or "its remover skipped it")
                    blocked_files.add(cid)
                    skipped += 1
                else:
                    ok.append(c)
            elif cid not in done:
                set_status(c, "skipped", why.get(cid) or "its remover did not report it applied")
                skipped += 1
            elif c["file"] not in changed or still_declared(lg, c):
                set_status(c, "skipped", "reported applied, but its declaration is still in the file")
                skipped += 1
            else:
                ok.append(c)
        problems = stray_deletions(lg, u, ok)
        if problems:
            fail_unit(lg, u, "its remover changed more than it was given: " + "; ".join(problems[:3]))
            rejected += 1
            restores.append(u)
            print(f"{u['id']}: rejected, {'; '.join(problems[:3])}")
            continue
        for c in ok:
            if c["kind"] == "file" and (lg.root / c["file"]).exists():
                rm = run(["git", "rm", "-q", "--", c["file"]], lg.root, check=False)
                if rm.returncode != 0:
                    set_status(c, "skipped", "git rm failed: " + rm.stderr.decode(errors="replace").strip())
                    blocked_files.add(c["id"])
                    skipped += 1
                    continue
            set_status(c, "applied")
            applied += 1
        deleted = {c["id"] for c in ok if c["kind"] == "file" and c["id"] not in blocked_files}
        for cid, fid in covered.items():  # declarations inside a deleted file share its fate
            c = lg.cands[cid]
            if fid in deleted and not (lg.root / c["file"]).exists():
                set_status(c, "applied")
                applied += 1
            else:
                set_status(c, "skipped", "its file was kept")
        lg.state["emptied"].extend(p for p in listed(result, "emptied_files") if isinstance(p, str))
        u["status"] = "ingested"
    lg.save()
    print(f"remove wave {wave}: {applied} applied, {skipped} skipped, {rejected} unit(s) rejected")
    if restores:
        lg.state["restore"] = sorted(set(lg.state.get("restore", []))
                                     | set().union(*(set(u["allowed"]) | set(u["deletes"]) for u in restores)))
        lg.save()
    say_next("ledger.py restore, then `ledger.py check`" if restores else "ledger.py check")


def listed(result: dict, key: str) -> list:
    value = result.get(key) if isinstance(result, dict) else None
    return value if isinstance(value, list) else []


def still_declared(lg: Ledger, c: dict) -> bool:
    """Whether the candidate's own declaration line survived (twins with other text do not count)."""
    if c.get("decl"):
        now = [line.strip()[:200] for line in (read_lines(lg.root / c["file"]) or [])]
        before = [line.strip()[:200] for line in head_lines(lg, c["file"])]
        return now.count(c["decl"]) >= before.count(c["decl"])
    return count_term(lg.root / c["file"], term_of(c)) >= count_head(lg, c["file"], term_of(c))


def count_head(lg: Ledger, path: str, term: str) -> int:
    """Occurrences of a name in the committed version of a file, the state each wave starts from."""
    data = run(["git", "show", f"HEAD:{path}"], lg.root, check=False).stdout
    text = decode(data) or ""
    return sum(tokens(line).count(term) for line in text.replace("\r\n", "\n").split("\n"))


def fail_unit(lg: Ledger, u: dict, why: str) -> None:
    """Send a removal unit's candidates back to `dead` for another wave, or give up on them."""
    for cid in u["candidates"]:
        c = lg.cands[cid]
        c["remove_retries"] = c.get("remove_retries", 0) + 1
        c["unit"] = None
        give_up = c["remove_retries"] >= MAX_RETRIES
        set_status(c, "skipped" if give_up else "dead", why if give_up else "")
    u["status"] = "failed"


# ---------------------------------------------------------------- check/settle

def changed_paths(lg: Ledger, untracked: bool = True) -> list:
    """Paths changed in the working tree, minus the ledger and the artifacts `ledger.py ignore` lists."""
    mode = "--untracked-files=all" if untracked else "--untracked-files=no"
    entries = run(["git", "status", "--porcelain=v1", "-z", mode], lg.root).stdout \
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
    return [p for p in paths if not p.startswith(LEDGER) and not matches(p, lg.state.get("ignore", []))]


def open_removal_units(lg: Ledger) -> list:
    return [u for u in lg.units("remove", "ingested") if u["wave"] == lg.state.get("current_wave")]


def cmd_check(args) -> None:
    lg = Ledger(git_root()).load()
    units = open_removal_units(lg)
    allowed = set()
    for u in units:
        allowed.update(u["allowed"], u["deletes"])
    changed = changed_paths(lg)
    unexpected = sorted(p for p in changed if p not in allowed)
    inside = sorted(p for p in changed if p in allowed)
    if unexpected:
        print(f"{len(unexpected)} change(s) outside the files this step may touch:")
        for p in unexpected[:30]:
            print(f"  {p}")
        tracked = [p for p in unexpected if run(["git", "cat-file", "-e", f"HEAD:{p}"], lg.root,
                                                check=False).returncode == 0]
        untracked = sorted(set(unexpected) - set(tracked))
        if tracked:
            lg.state["restore"] = sorted(set(lg.state.get("restore", [])) | set(tracked))
            lg.save()
        say_next(("`ledger.py restore` puts the tracked ones back; " if tracked else "")
                 + (f"untracked: {', '.join(untracked[:5])}: if the project's build or tests made them, "
                    "`ledger.py ignore \"<glob>\"`, otherwise stop and tell the user; " if untracked else "")
                 + "say which unit strayed, then `ledger.py check` again")
        sys.exit(1)
    if not units:
        print("no change in the working tree apart from the ledger")
        say_next(next_step(lg))
        return
    n = sum(1 for u in units for cid in u["candidates"] if lg.cands[cid]["status"] == "applied")
    print(f"{len(inside)} changed file(s), all inside wave {lg.state['current_wave']}; {n} removal(s) applied")
    say_next("ledger.py gate fast")


def head_sha(lg: Ledger) -> str:
    return run(["git", "rev-parse", "HEAD"], lg.root, check=False).stdout.decode().strip()


def shell(command: str) -> list:
    return ["bash", "-c", command] if shutil.which("bash") else ["sh", "-c", command]


def run_command(lg: Ledger, command: str, timeout: int) -> tuple:
    """(green|red|timeout, output) of a shell command run at the root, in its own process group so
    that a timeout stops the whole tree of processes, not just the shell."""
    proc = subprocess.Popen(shell(command), cwd=str(lg.root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        output, _ = proc.communicate(timeout=timeout)
        return ("green" if proc.returncode == 0 else "red"), output or b""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        output, _ = proc.communicate()
        return "timeout", output or b""


def run_gate(lg: Ledger, kind: str, timeout: int) -> tuple:
    """Run a recorded gate; returns (outcome green|red|timeout, output bytes, seconds, new untracked files)."""
    command = lg.state["gate"].get(kind) or (lg.state["gate"].get("fast") if kind == "full" else "")
    if not command:
        die(f"no {kind} gate was recorded; `ledger.py init --force` with --gate-{kind}, or skip it")
    before = set(changed_paths(lg))
    started = datetime.now(timezone.utc)
    outcome, output = run_command(lg, command, timeout)
    seconds = int((datetime.now(timezone.utc) - started).total_seconds())
    artifacts = sorted(p for p in set(changed_paths(lg)) - before
                       if run(["git", "cat-file", "-e", f"HEAD:{p}"], lg.root, check=False).returncode != 0)
    if artifacts:
        lg.state.setdefault("ignore", []).extend(artifacts)
    touched = sorted(p for p in set(changed_paths(lg, untracked=False)) - before)
    return outcome, output or b"", seconds, artifacts, touched


def cmd_gate(args) -> None:
    """Run a recorded gate command; artifacts it leaves untracked are ignored from then on."""
    lg = Ledger(git_root()).load()
    if lg.state.get("restore"):
        die("files are waiting to be restored first: `ledger.py restore`")
    log = lg.dir / "gates" / f"{args.kind}-r{lg.state['round']}-{len(lg.state.setdefault('gates', [])) + 1}.log"
    log.parent.mkdir(exist_ok=True)
    print(f"running the {args.kind} gate: {lg.state['gate'].get(args.kind) or lg.state['gate'].get('fast')}")
    outcome, output, seconds, artifacts, touched = run_gate(lg, args.kind, args.timeout)
    log.write_bytes(output)
    wave = lg.state.get("current_wave") if open_removal_units(lg) else None
    lg.state.setdefault("gates", []).append({"kind": args.kind, "round": lg.state["round"], "wave": wave, "outcome": outcome,
                              "seconds": seconds, "timeout": args.timeout, "head": head_sha(lg), "at": now()})
    if args.kind == "full" and outcome == "green" and not wave:
        lg.state["full_gate_head"] = head_sha(lg)
    if not wave and not lg.state["history"]:
        lg.state.setdefault("baseline", {})[args.kind] = outcome
    wave_files = {p for u in open_removal_units(lg) for p in u["allowed"] + u["deletes"]}
    strays = [p for p in touched if p not in wave_files]
    if strays:  # a formatter or a lockfile update: put them back before anything is committed
        lg.state["restore"] = sorted(set(lg.state.get("restore", [])) | set(strays))
    lg.save()
    tail = (decode(output) or "").strip().splitlines()[-25:]
    print(f"{args.kind} gate {outcome.upper()} in {seconds}s (full log: {log})")
    if outcome != "green" and tail:
        print("\n".join("  " + line for line in tail))
    if artifacts:
        print(f"{len(artifacts)} new untracked file(s) left by the gate are ignored from now on, e.g. {artifacts[0]}")
    if strays:
        print(f"the gate modified tracked file(s) outside the wave, to be restored: {', '.join(strays[:5])}")
    say_next(next_step(lg))


def cmd_commit(args) -> None:
    """Commit the current wave (its files only), then settle it."""
    lg = Ledger(git_root()).load()
    units = open_removal_units(lg)
    if not units:
        die("no removal wave is waiting to be committed")
    last = (lg.state.get("gates") or [{}])[-1]
    if last.get("wave") != lg.state["current_wave"] or last.get("outcome") != "green":
        die("the fast gate has not passed for this wave; run `ledger.py gate fast` first")
    files = sorted({p for u in units for p in u["allowed"] + u["deletes"]})
    present = [p for p in files if (lg.root / p).exists()]
    if present:
        run(["git", "add", "-A", "--"] + present, lg.root)
    staged = run(["git", "diff", "--cached", "--name-only", "-z"], lg.root).stdout.decode().split("\0")
    staged = [p for p in staged if p]
    if not staged:
        print("nothing to commit: every removal of this wave was skipped")
        settle(lg, units, None)
        return
    stray = sorted(set(staged) - set(files))
    if stray:
        die(f"the index holds files outside this wave: {', '.join(stray[:5])}; unstage them first")
    n = sum(1 for u in units for cid in u["candidates"] if lg.cands[cid]["status"] == "applied")
    msg = (f"refactor(dead-code): remove {n} unused declaration{'s' if n != 1 else ''} "
           f"(round {lg.state['round']}, wave {lg.state['current_wave']})")
    proc = run(["git", "commit", "-q", "-m", msg], lg.root, check=False)
    if proc.returncode != 0:
        print("git commit failed (a commit hook may have rejected the wave):")
        print("\n".join("  " + line for line in (proc.stdout + proc.stderr).decode(errors="replace").splitlines()[-15:]))
        say_next("never bypass the hook with --no-verify and never edit code for it: treat this as a red gate, "
                 "`ledger.py settle --fail <unit>` for the units it names, or stop and ask the user")
        return
    sha = run(["git", "rev-parse", "HEAD"], lg.root).stdout.decode().strip()
    lg.state["branch"] = run(["git", "branch", "--show-current"], lg.root).stdout.decode().strip() or lg.state["branch"]
    touched = run(["git", "show", "--name-only", "-z", "--format=", sha], lg.root).stdout.decode().split("\0")
    touched = [t for t in touched if t]
    extra = sorted(set(touched) - set(files))
    if extra:
        print(f"warning: a commit hook added files outside the wave to {sha[:12]}: {', '.join(extra[:5])}")
    print(f"committed {sha[:12]}: {msg}")
    settle(lg, units, sha)


def settle(lg: Ledger, units: list, sha, first: str = "") -> None:
    """Close the current wave: applied candidates become removed."""
    removed = 0
    for u in units:
        for cid in u["candidates"]:
            c = lg.cands[cid]
            if c["status"] == "applied":
                set_status(c, "removed")
                c["commit"] = sha
                removed += 1
        u["status"] = "settled"
    lg.state["history"].append({"round": lg.state["round"], "wave": lg.state["current_wave"], "removed": removed,
                                "commit": sha, "at": now()})
    lg.state["current_wave"] = None
    lg.save()
    print(f"wave settled: {removed} removal(s)" + (f" in {sha[:12]}" if sha else ""))
    say_next(first + next_step(lg))


def cmd_settle(args) -> None:
    lg = Ledger(git_root()).load()
    units = open_removal_units(lg)
    if not units:
        if lg.state.get("current_wave") is not None and args.ok:
            settle(lg, [], args.commit or None)  # every unit failed: close the wave with nothing removed
            return
        die("no removal wave is waiting for its gate")
    if args.find:
        if lg.state.get("restore"):
            die("files are waiting to be restored first: `ledger.py restore`, then `ledger.py gate fast`")
        find_culprits(lg, units, args.timeout)
        return
    by_id = {u["id"]: u for u in units}
    if args.fail:
        for unit in args.fail:
            if unit not in by_id:
                die(f"{unit} is not an open unit of wave {lg.state['current_wave']} ({', '.join(by_id)})")
        for unit in args.fail:
            fail_open_unit(lg, by_id[unit], args.note or "the gate failed with it removed")
        lg.state.setdefault("gates", []).append({"kind": "fast", "round": lg.state["round"], "wave": lg.state["current_wave"],
                                  "outcome": "stale", "head": head_sha(lg), "at": now()})
        if not open_removal_units(lg):
            settle(lg, [], None, first="`ledger.py restore` first; then ")
            return
        lg.save()
        say_next("ledger.py restore, then `ledger.py gate fast` (green: `ledger.py commit`; red: --fail the next "
                 "unit, or, when the error names none, `ledger.py settle --find`)")
        return
    if not args.ok:
        die("pass --ok (the gate is green), --fail <unit>, or --find")
    settle(lg, units, args.commit or None)


def fail_open_unit(lg: Ledger, u: dict, note: str) -> None:
    """The gate proved this unit's removals wrong: they are alive, and its files go back to HEAD."""
    for cid in u["candidates"]:
        c = lg.cands[cid]
        if c["status"] == "applied":
            set_status(c, "reverted", note)
            c["pinned"] = True
    u["status"] = "failed"
    lg.state["restore"] = sorted(set(lg.state.get("restore", [])) | set(u["allowed"]) | set(u["deletes"]))
    print(f"{u['id']} reverted: " + ", ".join(f"{cid} {lg.cands[cid]['symbol']}" for cid in u["candidates"]))


def find_culprits(lg: Ledger, units: list, timeout: int) -> None:
    """Bisect the open wave: find the units whose removals break the fast gate, keep the others applied."""
    files = sorted({p for u in units for p in u["allowed"] + u["deletes"]})
    patches = {}
    for u in units:
        paths = sorted(set(u["allowed"]) | set(u["deletes"]))
        patches[u["id"]] = run(["git", "diff", "--binary", "HEAD", "--"] + paths, lg.root).stdout
    in_head = [p for p in files if run(["git", "cat-file", "-e", f"HEAD:{p}"], lg.root, check=False).returncode == 0]
    runs = 0

    def apply(subset):
        if in_head:
            run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"] + in_head, lg.root)
        for u in subset:
            if patches[u["id"]].strip():
                proc = subprocess.run(["git", "apply", "--index", "--whitespace=nowarn", "-"], cwd=str(lg.root),
                                      input=patches[u["id"]], capture_output=True)
                if proc.returncode != 0:
                    die(f"could not re-apply {u['id']}: {proc.stderr.decode(errors='replace').strip()}")

    def red(subset):
        nonlocal runs
        apply(subset)
        runs += 1
        outcome = run_gate(lg, "fast", timeout)[0]
        if outcome == "timeout":
            apply(units)
            die("the fast gate timed out while narrowing the wave; re-run with a larger --timeout")
        return outcome == "red"

    def search(subset):
        if len(subset) == 1:
            return subset
        half = len(subset) // 2
        left, right = subset[:half], subset[half:]
        r1, r2 = red(left), red(right)
        found = (search(left) if r1 else []) + (search(right) if r2 else [])
        return found or subset  # broken only together: fail them all

    print(f"narrowing wave {lg.state['current_wave']}: {len(units)} unit(s)")
    if not red(units):
        print("the fast gate is green with every unit applied")
        lg.save()
        say_next("ledger.py gate fast")
        return
    if red([]):
        apply(units)
        die("the fast gate fails even without any of this wave's removals (a flaky gate, the environment, or a "
            "red baseline): every unit stays open; stop and tell the user")
    culprits = search(units)
    keep = [u for u in units if u not in culprits]
    if keep and red(keep):
        apply(units)
        die("the fast gate gives different results for the same removals (a flaky gate): every unit stays open; "
            "stop and tell the user")
    apply(keep)
    for u in culprits:
        fail_open_unit(lg, u, "the fast gate failed with this unit's removals, and passed without them")
    # The tree already holds exactly the kept units: the failed units' files need no restore.
    lg.state["restore"] = sorted(set(lg.state.get("restore", [])) - set(files))
    lg.state.setdefault("gates", []).append({"kind": "fast", "round": lg.state["round"], "wave": lg.state["current_wave"],
                              "outcome": "stale", "head": head_sha(lg), "at": now()})
    print(f"{len(culprits)} unit(s) failed after {runs} gate run(s); {len(keep)} kept")
    if not open_removal_units(lg):
        settle(lg, [], None)
        return
    lg.save()
    say_next("ledger.py gate fast")


def cmd_restore(args) -> None:
    """Put the files of failed or rejected units back to their committed state."""
    lg = Ledger(git_root()).load()
    paths = lg.state.get("restore", [])
    in_head = [p for p in paths if run(["git", "cat-file", "-e", f"HEAD:{p}"], lg.root, check=False).returncode == 0]
    if in_head:
        run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"] + in_head, lg.root)
    lg.state["restore"] = []
    lg.save()
    print(f"restored {len(in_head)} file(s) to HEAD" + (": " + ", ".join(in_head[:8]) if in_head else ""))
    say_next(next_step(lg))


def cmd_confirm(args) -> None:
    lg = Ledger(git_root()).load()
    if args.no:
        lg.state["confirmed"] = False
        lg.state["finished"] = True
        lg.save()
        print("deletions declined (or nobody could answer): the run ends as a report")
        say_next("ledger.py report")
        return
    if spotcheck_due(lg):
        die("spot-check the dead candidates first: `ledger.py spotcheck`")
    lg.state["confirmed"] = now()
    lg.save()
    print("the user approved deletions")
    say_next(next_step(lg))


RISK = {"file": 0, "class": 1, "type": 2}


def spotcheck_due(lg: Ledger) -> bool:
    """Dead candidates exist that no spot-check of this round has covered."""
    done = lg.state.get("spotchecks", {}).get(str(lg.state["round"]), {})
    return any(c["status"] == "dead" for c in lg.cands.values()) and done.get("status") != "done"


def cmd_spotcheck(args) -> None:
    """Pick dead candidates for the orchestrator to re-check itself before anything is deleted."""
    lg = Ledger(git_root()).load()
    rnd = str(lg.state["round"])
    checks = lg.state.setdefault("spotchecks", {})
    entry = checks.setdefault(rnd, {"status": "open", "picked": []})
    if args.wrong:
        c = lg.cands.get(args.wrong)
        if c is None or c["status"] != "dead":
            die(f"{args.wrong} is not a dead candidate")
        set_status(c, "alive", f"spot-check: {args.note or 'a use the lenses missed'}")
        c["pinned"] = True
        lg.state["spot_failures"] = lg.state.get("spot_failures", 0) + 1
        entry.update(status="open", picked=[])
        lg.save()
        if lg.state["spot_failures"] >= 2:
            lg.state["finished"] = True
            lg.save()
            print("a second spot-check found a live candidate: verification is miscalibrated for this codebase")
            say_next("stop deleting; `ledger.py report` and tell the user which uses the lenses missed")
            return
        print(f"{args.wrong} marked alive and pinned")
        say_next("`ledger.py note \"<the pattern the lenses missed>\"`, send the dead candidates that share it back "
                 "with `ledger.py mark --ids <ids> --status pending`, verify them again, then `ledger.py spotcheck`")
        return
    if args.ok:
        if not entry["picked"]:
            die("run `ledger.py spotcheck` first to pick the candidates")
        entry["status"] = "done"
        lg.save()
        print(f"spot-check of round {rnd} recorded")
        say_next(next_step(lg))
        return
    dead = [c for c in lg.cands.values() if c["status"] == "dead"]
    if not dead:
        print("no dead candidate to spot-check")
        say_next(next_step(lg))
        return
    dead.sort(key=lambda c: (RISK.get(c["kind"], 3), -((c["refs"] or {}).get("other", 0)), c["id"]))
    picks = dead[:args.count]
    entry.update(status="open", picked=[c["id"] for c in picks])
    lg.save()
    print(f"re-check these {len(picks)} yourself; read the code, do not trust the votes:")
    for c in picks:
        show_candidate(c)
    say_next("for each: if you find a use, `ledger.py spotcheck --wrong <id> --note \"<file:line of the use>\"`; "
             "when all hold, `ledger.py spotcheck --ok`")


def show_candidate(c: dict) -> None:
    refs = c.get("refs") or {}
    where = f"{c['file']}:{c['line']}" if c.get("line") else c["file"]
    print(f"  {c['id']} [{c['status']}] {c['kind']} `{c['symbol']}` at {where}"
          f" (refs: code {refs.get('other', 0)}, same file {refs.get('same_file', 0)}, tests {refs.get('tests', 0)},"
          f" docs {refs.get('docs', 0)})")
    for s in refs.get("sample", [])[:4]:
        print(f"      mention: {s}")
    for lens in LENSES:
        v = c["votes"].get(lens)
        if v:
            print(f"      {lens}: {v['verdict']} {v['confidence']} - {v['evidence'][:220]}")
    if c.get("note"):
        print(f"      note: {c['note'][:220]}")


def cmd_show(args) -> None:
    lg = Ledger(git_root()).load()
    picked = list(lg.cands.values())
    if args.ids:
        wanted = set(args.ids.split(","))
        picked = [c for c in picked if c["id"] in wanted]
    if args.status:
        picked = [c for c in picked if c["status"] == args.status]
    if args.symbol:
        picked = [c for c in picked if term_of(c) == args.symbol or c["symbol"] == args.symbol]
    if args.commit:
        picked = [c for c in picked if c.get("commit") and (c["commit"].startswith(args.commit)
                                                            or args.commit.startswith(c["commit"]))]
    for c in sorted(picked, key=lambda c: c["id"])[:args.limit]:
        show_candidate(c)
    if len(picked) > args.limit:
        print(f"  ... {len(picked) - args.limit} more (--limit)")
    if not picked:
        print("no candidate matches")


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
        u = lg.state["units"].get(c.get("unit") or "")
        if c["status"] in ("planned", "applied") and u and u["status"] != "ready":
            die(f"{cid} is in removal unit {u['id']}, already {u['status']}: finish that wave, "
                f"or `ledger.py settle --fail {u['id']}`")
        if c["status"] == "planned" and u:
            drop_from_unit(lg, u, cid)
        set_status(c, args.status, args.note)
        # A human decision sticks: later reference drops do not send it back to the lenses.
        c["pinned"] = args.status not in ("pending", "dead")
        if args.status in ("pending", "dead"):
            c["unit"], c["retries"], c["remove_retries"] = None, 0, 0
            if args.status == "pending":
                c["votes"], c["also_edit"] = {}, []
    lg.save()
    print(f"{len(ids)} candidate(s) marked {args.status}")
    say_next(next_step(lg))


def drop_from_unit(lg: Ledger, u: dict, cid: str) -> None:
    """Take a candidate out of a removal unit that has not been dispatched yet. Declarations that
    were to go with a dropped file are released too: they will be planned as edits of their own."""
    u["candidates"].remove(cid)
    covered = u.setdefault("covered", {})
    covered.pop(cid, None)
    for rid in [r for r, fid in covered.items() if fid == cid]:
        del covered[rid]
        if rid in u["candidates"]:
            u["candidates"].remove(rid)
        rider = lg.cands[rid]
        rider["unit"] = None
        if rider["status"] == "planned":
            set_status(rider, "dead", "its file was kept; to be removed on its own")
    spec = read_json(lg.unit_path(u["id"]))
    spec["edits"] = [e for e in spec["edits"] if e["id"] != cid]
    keep = [lg.cands[x] for x in u["candidates"]]
    u["deletes"] = spec["deleted_by_orchestrator"] = sorted(c["file"] for c in keep if c["kind"] == "file")
    u["allowed"] = spec["allowed_files"] = sorted({c["file"] for c in keep} | {e["file"] for c in keep
                                                                                 for e in c["also_edit"]})
    u["agent"] = bool(spec["edits"])
    if not u["candidates"]:
        u["status"] = "settled"
    write_json(lg.unit_path(u["id"]), spec)


def cmd_ignore(args) -> None:
    lg = Ledger(git_root()).load()
    lg.state.setdefault("ignore", []).extend(args.globs)
    lg.save()
    print(f"changes matching {', '.join(args.globs)} are ignored by check from now on")
    say_next(next_step(lg))


def cmd_round(args) -> None:
    lg = Ledger(git_root()).load()
    busy = Counter(c["status"] for c in lg.cands.values() if c["status"] in IN_FLIGHT)
    if busy and not args.force:
        die("the round is not finished: " + ", ".join(f"{k} {v}" for k, v in busy.items()))
    if changed_paths(lg, untracked=False) and not args.force:
        die("tracked files have uncommitted changes: `ledger.py check` lists them, `ledger.py restore` puts them back")
    removed = removed_this_round(lg)
    if needs_full_gate(lg) and not args.force:
        die("run the full gate on this round's removals first: `ledger.py gate full`")
    if removed == 0 or lg.state["round"] >= lg.state["max_rounds"]:
        lg.state["finished"] = True
        lg.save()
        print(f"round {lg.state['round']} " + ("removed nothing: fixed point reached" if removed == 0
                                                 else f"was the last of {lg.state['max_rounds']}"))
        say_next("ledger.py report")
        return
    orphans = emptied_files(lg)
    lg.state["round"] += 1
    proposed = [path for path in orphans if add_candidate(
        lg, file=path, symbol=stem_term(path), kind="file", source="emptied",
        detail=f"round {lg.state['round'] - 1} left it without declarations")]
    lg.save()
    print(f"round {lg.state['round']} started: last round's {removed} removal(s) may have orphaned more code")
    if proposed:
        print(f"{len(proposed)} file(s) left without declarations are now candidates: {', '.join(proposed[:8])}")
    say_next(next_step(lg))


# Files a package, crate or program needs even when they declare nothing.
STRUCTURAL = {"__init__.py", "__main__.py", "lib.rs", "main.rs", "mod.rs", "build.rs"}


def emptied_files(lg: Ledger) -> list:
    """Tracked files this round's removals left with nothing but comments, imports and package lines."""
    seen = set(lg.state.get("emptied", []))
    seen |= {c["file"] for c in lg.cands.values() if c["status"] == "removed" and c["kind"] != "file"
             and c.get("commit") in {h["commit"] for h in lg.state["history"] if h["round"] == lg.state["round"]}}
    out = []
    for path in sorted(seen):
        full = lg.root / path
        if Path(path).name in STRUCTURAL or Path(path).suffix.lower() not in SOURCE_EXTS \
                or not full.is_file() or full.is_symlink():
            continue
        if run(["git", "ls-files", "--error-unmatch", "--", path], lg.root, check=False).returncode != 0:
            continue
        if not declares_nothing(read_lines(full), python=path.endswith((".py", ".pyi"))):
            continue
        out.append(path)
    return out


def declares_nothing(lines, python: bool = False) -> bool:
    """True when every line is blank, a comment, an import that binds a name, or a package header.
    Anything that runs when the file loads (a side-effect import, a call, a `//go:` directive) is code."""
    if lines is None:
        return False
    block = None  # the closing token of a comment, docstring or import block being skipped
    for raw in lines:
        line = raw.strip()
        if block in (")", "}"):  # inside a multi-line import
            if line.startswith(("_ ", "_\t")):
                return False  # Go `_ "pkg"`: imported for its side effects
            if block in line:
                block = None
            continue
        while line:
            if block:
                if block not in line:
                    line = ""
                    break
                line = line.split(block, 1)[1].strip()  # whatever follows the comment on its line
                block = None
                continue
            if line.startswith("<?php"):
                line = line[5:].strip()
                continue
            if line.startswith("/*"):
                rest = line[2:]
                if "*/" in rest:
                    line = rest.split("*/", 1)[1].strip()
                    continue
                block, line = "*/", ""
                break
            if line.startswith(('"""', "'''")):
                quote, rest = line[:3], line[3:]
                if quote in rest:
                    line = rest.split(quote, 1)[1].strip()
                    continue
                block, line = quote, ""
                break
            break
        if not line or line in ("?>", "--", '"use strict";', "'use strict';"):
            continue
        if line.startswith(("//go:", "#[", "#define", "#if", "#el", "#end", "#pragma")):
            return False
        if line.startswith(("//", "-- ", "#")):
            continue
        if ";" in line.rstrip(";") or (SIDE_EFFECT.match(line) and not line.startswith("export")) \
                or (python and PY_SUBMODULE.match(line)) \
                or re.search(r"\)\s*[.\[(]", line):
            return False  # two statements on a line, an import run for its effect, a call on what it loaded
        if IMPORT_OPEN.match(line) and not line.startswith(("const", "let", "var")):
            close = "}" if "{" in line else ")"
            if close not in line:
                block = close
                continue
        if DEPENDENT.match(line) and not re.match(r"^(require|@import|#include)", line) \
                or re.match(r"^(package|namespace)\s+[\w.\\]+\s*;?$", line):
            continue
        return False
    return True


def removed_this_round(lg: Ledger) -> int:
    """Removals of the current round that are still in place (a reverted commit no longer counts)."""
    commits = {h["commit"] for h in lg.state["history"] if h["round"] == lg.state["round"] and h.get("commit")}
    return sum(1 for c in lg.cands.values() if c["status"] == "removed" and c.get("commit") in commits)


def needs_full_gate(lg: Ledger) -> bool:
    """This round removed code, and the full gate has not passed on the current commit."""
    return bool(removed_this_round(lg) and lg.state["gate"].get("full")
                and lg.state.get("full_gate_head") != head_sha(lg))


def cmd_bisect(args) -> None:
    """Find the wave commit of this round that breaks the full gate."""
    lg = Ledger(git_root()).load()
    applied = [h["commit"] for h in lg.state["history"] if h["round"] == lg.state["round"] and h.get("commit")
               and any(c.get("commit") == h["commit"] and c["status"] == "removed" for c in lg.cands.values())]
    gate = lg.state["gate"].get("full") or lg.state["gate"].get("fast")
    if not applied or not gate:
        die("this round has no wave commit still in place (or no gate) to search")
    if changed_paths(lg, untracked=False):
        die("tracked files have changes: `ledger.py check` lists them, `ledger.py restore` puts them back")
    # Revert the waves newest first, keeping each revert, until the suite passes: the last wave
    # reverted is the culprit. Reverting in the reverse order of the commits always applies, even
    # when consecutive waves edited the same file. Waves already reverted are not in `applied`.
    culprit, reverted, timed_out = None, [], False
    try:
        for sha in reversed(applied):
            if run(["git", "revert", "--no-commit", sha], lg.root, check=False).returncode != 0:
                print(f"{sha[:12]} does not revert on top of the newer waves; the search stops there")
                break
            reverted.append(sha)
            outcome = run_command(lg, gate, args.timeout)[0]
            print(f"without {len(reverted)} newest wave(s), down to {sha[:12]}: {outcome}")
            if outcome == "timeout":
                timed_out = True
                break
            if outcome == "green":
                culprit = sha
                break
    finally:
        run(["git", "revert", "--abort"], lg.root, check=False)
        run(["git", "reset", "-q", "--hard", "HEAD"], lg.root, check=False)
    if timed_out:
        say_next(f"the suite timed out: `ledger.py bisect --timeout {2 * args.timeout}`")
        return
    if culprit is None:
        say_next("no wave commit of this round explains the failure (flaky, or broken before the round): run "
                 "`ledger.py gate full` again; if it stays red, stop and tell the user")
        return
    alone = run(["git", "revert", "--no-commit", culprit], lg.root, check=False).returncode == 0
    run(["git", "revert", "--abort"], lg.root, check=False)
    run(["git", "reset", "-q", "--hard", "HEAD"], lg.root, check=False)
    print(f"the suite passes once {culprit[:12]} is reverted; its removals:")
    for c in lg.cands.values():
        if c.get("commit") == culprit:
            show_candidate(c)
    mark = (f"if the failure names one of these symbols, `ledger.py mark --ids <that id> --status reverted --note "
            f"\"<test and error>\"` and the others `--status dead`; otherwise `ledger.py mark --commit {culprit[:12]} "
            f"--status reverted`")
    newer = reverted[:-1]
    if alone or not newer:
        say_next(f"`git revert --no-edit {culprit[:12]}`; then, {mark}; then `ledger.py gate full`")
        return
    # The culprit's revert conflicts with newer waves' edits: revert them together, then plan the
    # innocent newer waves again.
    shas = " ".join(sha[:12] for sha in reverted)
    again = "; ".join(f"`ledger.py mark --commit {sha[:12]} --status dead`" for sha in newer)
    say_next(f"`git revert --no-edit {shas}` (newest first: {culprit[:12]} cannot be reverted alone); then, "
             f"{mark}; then {again}, so the newer waves are removed again; then `ledger.py gate full`")


# ------------------------------------------------------------- status/report

DETECT = ("detect: `ledger.py analyze --tool <tool> -- <command>` for each stack (references/analyzers.md), "
          "`ledger.py shard --ext <ext>` for the languages none covers, then `ledger.py refs`")


def next_step(lg: Ledger) -> str:
    st = lg.state
    statuses = Counter(c["status"] for c in lg.cands.values())
    dispatched = lg.units(status="dispatched")
    if dispatched:
        stage = dispatched[0]["stage"]
        return (f"wait for the {stage} workflow's completion notice, then `ledger.py ingest {stage}` (if no "
                f"workflow is running any more, ingest anyway: units without output are dispatched again)")
    if st.get("restore"):
        return "ledger.py restore"
    if open_removal_units(lg):
        last = next((g for g in reversed(st.get("gates") or []) if g.get("wave") == st.get("current_wave")
                     and g.get("kind") == "fast"), {})
        outcome = last.get("outcome")
        if outcome == "green":
            return "ledger.py commit"
        if outcome == "red":
            return ("find the unit that broke the gate (`ledger.py status --wave` lists each unit's symbols): "
                    "`ledger.py settle --fail <unit> --note \"<the error line>\"`, or `ledger.py settle --find`")
        if outcome == "timeout":
            return f"ledger.py gate fast --timeout {2 * (last.get('timeout') or 1800)}"
        return "ledger.py check, then `ledger.py gate fast`"
    if st["finished"] or st.get("confirmed") is False:
        return "ledger.py report"
    baseline = baseline_step(lg)
    if baseline:
        return baseline
    last_full = next((g for g in reversed(st.get("gates") or []) if g.get("kind") == "full"), {})
    if last_full.get("outcome") == "timeout" and last_full.get("head") == head_sha(lg):
        return f"ledger.py gate full --timeout {2 * (last_full.get('timeout') or 1800)}"
    if st["history"] and last_full.get("outcome") == "red" and last_full.get("head") == head_sha(lg):
        return "ledger.py bisect"
    if st["round"] > 1 and st.get("analyzed_round") != st["round"] and st.get("imported_round") != st["round"] \
            and st["analyzers"].keys() - {"scan"}:
        return ("ledger.py analyze --again" if st.get("analyzer_cmds") else
                "re-run this run's analyzers and `ledger.py import` their reports")
    if lg.units("scan", "ready"):
        return "ledger.py dispatch scan"
    if not lg.cands and st.get("refs_round") != st["round"]:
        return DETECT
    if statuses["new"] or (lg.cands and st.get("refs_round") != st["round"]):
        return "ledger.py refs"
    if statuses["pending"] or lg.units("verify", "ready"):
        return "ledger.py dispatch verify"
    if spotcheck_due(lg):
        return "ledger.py spotcheck"
    if st["mode"] == "report":
        return "ledger.py report"
    if statuses["dead"] or lg.units("remove", "ready"):
        if not st["confirmed"]:
            return ("`ledger.py report`, show the user its summary and ask before deleting anything; on yes, "
                    "`ledger.py confirm`; on no, or when nobody can answer, `ledger.py confirm --no`")
        return "ledger.py dispatch remove"
    if needs_full_gate(lg):
        return "ledger.py gate full"
    return "ledger.py round"


def baseline_step(lg: Ledger):
    """What a run that may remove code still needs before anything is removed: a green baseline."""
    st = lg.state
    if st["mode"] != "fix" or st["history"]:
        return None
    for kind in ("fast", "full"):
        if not st["gate"].get(kind):
            continue
        outcome = st.get("baseline", {}).get(kind)
        if outcome == "red":
            return ("the baseline is red: stop and tell the user; continue only with `ledger.py init --force "
                    "--report-only ...` or with a gate command that is green")
        if outcome == "timeout":
            return f"ledger.py gate {kind} --timeout 3600"
        if outcome != "green":
            return f"ledger.py gate {kind}"
    return None


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
            names = ", ".join(f"{cid} {lg.cands[cid]['symbol']} ({lg.cands[cid]['status']})" for cid in u["candidates"])
            print(f"  {u['id']}: {names}")
            print(f"      edits {' '.join(u['allowed']) or '-'}" + (f" | deletes {' '.join(u['deletes'])}" if u["deletes"] else ""))
    say_next(next_step(lg))


def votes_line(c: dict) -> str:
    parts = [f"{lens}: {v['verdict']} {v['confidence']} ({v['evidence']})"
             for lens, v in ((lens, c["votes"].get(lens)) for lens in LENSES) if v]
    return "; ".join(parts) or c.get("note", "")


def coverage_lines(lg: Ledger) -> list:
    """What the run examined and what it did not, computed from the tree, the analyzers and the scan units."""
    st = lg.state
    covered_exts = set()
    for tool in st["analyzers"]:
        covered_exts |= ANALYZER_EXTS.get(tool, set())
    scanned, gave_up = set(), set()
    for u in lg.units("scan"):
        (scanned if u["status"] == "ingested" else gave_up if u["status"] == "failed" else set()).update(u["files"])
    groups = defaultdict(list)
    for path in tracked_files(lg.root, st["scope"] or None):
        suffix = Path(path).suffix
        if suffix not in SOURCE_EXTS:
            continue
        if matches(path, NEVER_SCAN):
            groups["left out: vendored, generated or migrations"].append(path)
        elif lg.is_test(path):
            groups["left out: tests (their uses still count as references)"].append(path)
        elif lg.is_protected(path):
            groups["left out: protected"].append(path)
        elif path in scanned:
            groups["scanned by the Haiku scanners"].append(path)
        elif path in gave_up:
            groups["NOT examined: the scanner gave up after three tries"].append(path)
        elif suffix in covered_exts:
            groups["examined by " + "/".join(sorted(t for t in st["analyzers"] if suffix in ANALYZER_EXTS.get(t, ())))
                   ].append(path)
        else:
            groups["NOT examined: no analyzer and no scan"].append(path)
    lines = []
    for label, paths in sorted(groups.items()):
        tops = Counter(p.split("/", 1)[0] if "/" in p else "." for p in paths)
        lines.append(f"- {label}: {len(paths)} file(s) (" + ", ".join(f"`{d}` {n}" for d, n in tops.most_common(6)) + ")")
    for path, reason in sorted(st.get("unscanned", {}).items())[:20]:
        lines.append(f"- NOT examined by its scanner: `{path}` ({reason})")
    if st.get("unsearched"):
        lines.append(f"- references not searched in {len(st['unsearched'])} unreadable tracked file(s), e.g. "
                     f"`{st['unsearched'][0]}` (sparse checkout?)")
    for job in st.get("analyzer_cmds", []):
        lines.append(f"- analyzer `{job['source'] or job['tool']}`: `{' '.join(job['argv'])}`"
                     + (f" in `{job['base']}`" if job["base"] else ""))
    agents = Counter(u["stage"] for u in st["units"].values())
    lines.append("- agent units: " + (", ".join(f"{k} {v}" for k, v in sorted(agents.items())) or "none"))
    return lines


def cmd_report(args) -> None:
    lg = Ledger(git_root()).load()
    st = lg.state
    by = defaultdict(list)
    for c in sorted(lg.cands.values(), key=lambda c: (c["file"], c.get("line") or 0)):
        by[c["status"]].append(c)

    def loc(c):
        return f"{c['id']} `{c['file']}:{c['line']}`" if c.get("line") else f"{c['id']} `{c['file']}`"

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
    human = [c for c in lg.cands.values() if c.get("pinned") and c["status"] == "alive"]
    if human:
        lines += ["", "## Kept alive by the orchestrator's own check", ""] + [
            f"- {loc(c)} `{c['symbol']}`: {c['note']}" for c in human]
    emptied = sorted(p for p in set(st["emptied"]) if (lg.root / p).exists())
    if emptied:
        lines += ["", "## Files left without declarations", ""] + [f"- `{p}`" for p in emptied]
    lines += ["", "## Coverage", ""] + coverage_lines(lg)
    if st["notes"]:
        lines += ["", "## Facts given to the verifiers", ""] + [f"- {n}" for n in st["notes"]]
    out = Path(args.out) if args.out else lg.dir / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {out}")
    print("summary: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(by.items())))
    for c in by.get("dead", [])[:args.examples]:
        print(f"  dead: {c['id']} {c['file']}:{c.get('line') or '-'} {c['kind']} {c['symbol']}")
    step = next_step(lg)
    if step == "ledger.py report":
        step = "present the summary and the report path to the user"
    elif step.startswith("`ledger.py report`"):
        step = ("show the user this summary and ask before deleting anything; on yes, `ledger.py confirm`; "
                "on no, or when nobody can answer, `ledger.py confirm --no`")
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
    s.add_argument("--no", action="store_true", help="the user declined, or nobody can answer: report only")
    s.set_defaults(func=cmd_confirm)

    s = sub.add_parser("analyze", help="run an analyzer, import its report, remember it for later rounds")
    s.add_argument("--tool", choices=["knip", "vulture", "cargo", "staticcheck", "deadcode", "debride", "phpstan",
                                      "sarif", "tsv"])
    s.add_argument("--base", default="", help="directory to run in, relative to the repo root")
    s.add_argument("--source", default="", help="name to record (default: the tool)")
    s.add_argument("--rule", action="append", default=[], help="SARIF ruleId to keep (repeatable)")
    s.add_argument("--output", default="", help="file the command writes its report to, instead of stdout")
    s.add_argument("--timeout", type=int, default=1800, help="seconds before giving up (default 1800)")
    s.add_argument("--again", action="store_true", help="re-run every analyzer this run recorded")
    s.add_argument("command", nargs=argparse.REMAINDER, help="-- then the analyzer command")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("gate", help="run the recorded fast or full gate")
    s.add_argument("kind", choices=["fast", "full"])
    s.add_argument("--timeout", type=int, default=1800, help="seconds before calling it a timeout (default 1800)")
    s.set_defaults(func=cmd_gate)

    s = sub.add_parser("commit", help="commit the current wave after a green fast gate, then settle it")
    s.set_defaults(func=cmd_commit)

    s = sub.add_parser("spotcheck", help="pick dead candidates to re-check yourself; --ok or --wrong <id>")
    s.add_argument("--ok", action="store_true", help="every picked candidate is dead indeed")
    s.add_argument("--wrong", default="", help="a picked candidate you found alive")
    s.add_argument("--note", default="", help="the use you found")
    s.add_argument("--count", type=int, default=3)
    s.set_defaults(func=cmd_spotcheck)

    s = sub.add_parser("show", help="print candidates with ids, references and votes")
    s.add_argument("--ids", default="")
    s.add_argument("--status", default="")
    s.add_argument("--symbol", default="")
    s.add_argument("--commit", default="")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("bisect", help="find the wave commit of this round that breaks the full gate")
    s.add_argument("--timeout", type=int, default=1800, help="seconds per gate run")
    s.set_defaults(func=cmd_bisect)

    s = sub.add_parser("check", help="refuse changes outside the current wave's files")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("settle", help="close the current removal wave after its gate")
    s.add_argument("--ok", action="store_true", help="the gate is green")
    s.add_argument("--fail", action="append", default=[], help="unit whose removals broke the gate (repeatable)")
    s.add_argument("--note", default="", help="the error that proved it alive")
    s.add_argument("--commit", default="", help="sha of the commit holding the wave")
    s.add_argument("--find", action="store_true", help="narrow a red wave down to the units that break the gate")
    s.add_argument("--timeout", type=int, default=1800, help="seconds per gate run with --find")
    s.set_defaults(func=cmd_settle)

    s = sub.add_parser("restore", help="put failed and rejected units' files back to HEAD")
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("mark", help="override candidate statuses")
    s.add_argument("--ids", default="", help="comma-separated candidate ids")
    s.add_argument("--commit", default="", help="every candidate removed in this commit")
    s.add_argument("--status", required=True, choices=["alive", "unsure", "likely-dead", "dead", "pending",
                                                        "reverted", "skipped", "test-only", "protected"])
    s.add_argument("--note", default="")
    s.set_defaults(func=cmd_mark)

    s = sub.add_parser("ignore", help="let check ignore build or test artifacts the gate creates")
    s.add_argument("globs", nargs="+", help="root-relative glob, e.g. '*/__pycache__/*'")
    s.set_defaults(func=cmd_ignore)

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
