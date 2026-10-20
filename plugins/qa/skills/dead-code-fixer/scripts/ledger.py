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
import ast
import codecs
import contextlib
import copy
import difflib
import fnmatch
import functools
import glob
import hashlib
import json
import os
import posixpath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.parse
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

LEDGER = ".dead-code"
SCHEMA_VERSION = 2

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
    "migrations/*", "*/migrations/*", "*/db/migrate/*", "*/Migrations/*", "*/migration/*", "*/db/migration/*",
    "*/alembic/versions/*",
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
    "*/Tests/*", "*/Test/*", "*Tests/*", "*.Tests/*", "*/src/*Test/*", "*Test.*", "*Tests.*", "*Spec.*",
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
HYPHENATED = re.compile(r"(?<![\w$-])[\w$]+(?:-[\w$]+)+")
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


# Every git call reads paths literally (a route file named `[id].ts` is not a glob), and none takes
# diff options from the environment, which would add context lines to the diffs the parsers read.
GIT_ENV = {k: v for k, v in os.environ.items() if k not in ("GIT_DIFF_OPTS", "GIT_EXTERNAL_DIFF")}
GIT_ENV["GIT_LITERAL_PATHSPECS"] = "1"


def run(cmd: list, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    if cmd[:1] == ["git"]:  # a restore or a revert never reaches into a submodule's own work
        cmd = ["git", "-c", "submodule.recurse=false"] + cmd[1:]
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, env=GIT_ENV if cmd[:1] == ["git"] else None)
    if check and proc.returncode != 0:
        die(f"`{' '.join(cmd)}` failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc


def git_root() -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True)
    if proc.returncode != 0:
        die("not inside a git repository; a run needs git to scope files and roll back removals")
    return Path(proc.stdout.decode().strip())


def tracked_files(root: Path, pathspecs: list | None = None, editable: bool = False) -> list:
    """Tracked regular files; symlinks are left out so no file is read or edited twice, and
    submodules because their files belong to another repository. `editable` also leaves out the
    files git hides from `status` (assume-unchanged, skip-worktree): the run could neither check
    nor roll back a change to those, and they may hold the user's local edits."""
    out = run(["git", "ls-files", "-s", "-v", "-z", "--"] + (pathspecs or []), root).stdout.decode("utf-8", "replace")
    files = []
    for entry in out.split("\0"):
        meta, _, path = entry.partition("\t")
        tag, _, mode = meta.partition(" ")
        if path and not mode.startswith(("120000", "160000")) and (tag == "H" or not editable):
            files.append(path)
    return files


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path: Path, data) -> None:
    write_bytes(path, (json.dumps(data, indent=1) + "\n").encode("utf-8"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as err:
        raise ValueError(f"{path.name}: invalid JSON ({err.msg} at line {err.lineno})") from err
    except (OSError, UnicodeDecodeError, ValueError) as err:  # a folder in its place, bytes, a huge integer
        raise ValueError(f"{path.name}: cannot be read ({clean(err, 120)})") from err


def say_next(text: str) -> None:
    print(f"next: {text}")


CONTROL = re.compile("[\x00-\x1f\x7f\x85\u2028\u2029]")
SURROGATE = re.compile("[\ud800-\udfff]")


def clean(text, limit: int = 300) -> str:
    """Untrusted text (agent output, file names, analyzer messages) made safe to print: on one line,
    so that nothing it holds can pass for a `next:` line, and cut to `limit` characters."""
    text = SURROGATE.sub("?", CONTROL.sub(" ", str(text)))  # a lone surrogate cannot be printed or written
    return text if len(text) <= limit else text[:limit - 3] + "..."


@functools.lru_cache(maxsize=None)
def glob_forms(g: str) -> tuple:
    """A glob and the forms it implies: `*/x/*` and `**/x/*` also match `x/*` at the root, and `a/**/b`
    also matches `a/b`."""
    out = [g]
    for prefix in ("**/", "*/"):
        if g.startswith(prefix):
            out.append(g[len(prefix):])
            break
    out += [v.replace("/**/", "/") for v in out if "/**/" in v]
    return tuple(out)


def matches(path: str, globs: list) -> bool:
    """Whether a path is one of `globs`, literally or as an fnmatch glob (where `*` crosses `/`); a glob
    without `/` also matches the file name anywhere."""
    base = path.rsplit("/", 1)[-1]
    return any(path == g or any(fnmatch.fnmatchcase(path, form) for form in glob_forms(g))
               or ("/" not in g and fnmatch.fnmatchcase(base, g)) for g in globs)


def in_ledger(path: str) -> bool:
    return path == LEDGER or path.startswith(LEDGER + "/")


def as_globs(paths: list, root: Path) -> list:
    """User path arguments as root-relative globs. A path that exists is taken literally (`app/[slug]` is
    a folder, not a character class) and a folder covers everything under it; `.` at the root is all."""
    out = []
    for p in paths:
        g = repo_path(root, p)
        if g == ".":
            out.append("*")
        elif (root / g).exists():
            out.append(glob.escape(g))
            if (root / g).is_dir():
                out.append(glob.escape(g.rstrip("/")) + "/*")
        else:
            out.append(g)
    return out


def repo_path(root: Path, path: str) -> str:
    """A path the user typed, relative to the current directory, as a root-relative POSIX path.

    A glob (`*`, `?` or `[`, naming no existing path) is anchored the same way, with its `.` and `..` read
    lexically and an absolute one losing the root's prefix; one outside the repository stays as typed and
    matches nothing."""
    p = Path(path)
    full = p if p.is_absolute() else Path.cwd() / p
    if any(ch in path for ch in "*?[") and not full.exists():
        text = posixpath.normpath(full.as_posix())
        for top in dict.fromkeys((root.as_posix().rstrip("/"), root.resolve().as_posix().rstrip("/"))):
            if text == top:
                return "."
            if text.startswith(top + "/"):
                return text[len(top) + 1:]
        return p.as_posix()
    try:
        return full.resolve().relative_to(root.resolve()).as_posix().strip("/") or "."
    except ValueError:
        return p.as_posix()


def rel(root: Path, path: str, base: str = "") -> str:
    """An analyzer's path as a repository-relative POSIX path. A path that is a symlink, or goes through a
    symlinked folder of the repository (an alias is not the file it points to), or that ends outside the
    repository, comes back absolute: never a tracked file, so add_candidate leaves it out. A symlink above
    the repository (the whole checkout under a linked folder) changes nothing."""
    if path.startswith("file:"):
        path = urllib.parse.unquote(urllib.parse.urlparse(path).path)
    p = Path(path)
    if not p.is_absolute():
        p = root / base / p
    try:
        if p.is_symlink():
            return p.as_posix()
        real = p.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, RuntimeError, OSError):  # outside the repository, or a symlink loop
        return p.as_posix()
    lexical = posixpath.normpath(p.as_posix())
    if lexical != real and not lexical.endswith("/" + real):
        return lexical  # through a symlinked folder inside the repository: an alias, never what it points to
    return real


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
    if HYPHENATED.fullmatch(name):
        return name  # a Lisp name: `old-format` is one name
    m = WORD.search(name)
    return m.group(0).lstrip("$") if m else ""


def tokens(line: str, hyphenated: bool = False) -> list:
    """The identifier tokens of a line, as written and also as a string escape leaves them (`"\\nrefresh"`
    holds `refresh`, while `\\App\\normalize_phone` keeps its name): `$name` also counts as `name`, and a
    name with an inner `$` (`Outer$Inner`, `"$first$last"`) also as its parts. Extra spellings can only
    add references, which keeps code alive, never the reverse."""
    words = WORD.findall(line)
    escaped = Counter(WORD.findall(ESCAPES.sub(" ", line))) - Counter(words)
    out = []
    for w in words + list(escaped.elements()):
        out.append(w)
        bare = w.lstrip("$")
        if bare and bare != w:
            out.append(bare)
        if "$" in bare:
            out.extend(p for p in bare.split("$") if p and not p[0].isdigit())
    if hyphenated:
        out.extend(HYPHENATED.findall(line))
    return out


def decode(data: bytes):
    """Text of a file, honouring UTF-8/16/32 byte-order marks; None for binary data."""
    for bom, enc in ((codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
                     (codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"),
                     (codecs.BOM_UTF16_BE, "utf-16-be")):
        if data.startswith(bom):
            return data[len(bom):].decode(enc, "replace")
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")  # U+FFFD is no word character: `legacy_col\xa0FROM` stays two words


_LINES: dict = {}


def read_lines(path: Path):
    """A file's lines split on newlines only (form feeds and U+2028 stay inside a line), or None. Read
    once per version of the file within a command: one per finding would re-read big files thousands
    of times."""
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
        if key not in _LINES:
            text = decode(path.read_bytes())
            _LINES[key] = None if text is None else text.replace("\r\n", "\n").split("\n")
    except OSError:
        return None
    return _LINES[key]


_INDEX: dict = {}


def line_index(path: Path):
    """{token: [line numbers]} of a file, built once per version of it; None when it cannot be read."""
    lines = read_lines(path)
    if lines is None:
        return None
    key = (str(path), id(lines))
    if key not in _INDEX:
        index = defaultdict(list)
        for n, line in enumerate(lines, 1):
            for t in set(tokens(line)):
                index[t].append(n)
        _INDEX[key] = index
    return _INDEX[key]


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
        self.foreign: list = []  # findings this command left out: git does not track their file
        self._tracked = self._in_head = self._head = None
        self._digests: dict = {}

    def tracked(self) -> set:
        """The files a run may edit: tracked regular files git shows in `status`, listed once per command."""
        if self._tracked is None:
            self._tracked = set(tracked_files(self.root, editable=True))
        return self._tracked

    def in_head(self, path: str) -> bool:
        """Whether the last commit holds this path (submodules and symlinks included)."""
        if self._in_head is None:
            out = run(["git", "ls-tree", "-r", "-z", "--name-only", "HEAD"], self.root, check=False).stdout
            # With surrogateescape, like the paths status_entries queues for a restore: a name that is not UTF-8
            # round-trips to git, where a replacement character would match no file. (tracked_files keeps
            # "replace": under its mangled name such a file is never found on disk, so a run never edits it.)
            self._in_head = set(os.fsdecode(out).split("\0"))
        return path in self._in_head

    def head(self) -> str:
        """HEAD's sha, read once per command (no command reads it again after committing)."""
        if self._head is None:
            self._head = head_sha(self)
        return self._head

    def integrity_path(self) -> Path:
        """Where the digests of the ledger's files live: in git's own folder, out of the working tree that
        agents write to. An agent that rewrites state.json cannot also produce its sha256."""
        out = run(["git", "rev-parse", "--git-path", "dead-code-ledger.json"], self.root).stdout.decode().strip()
        return Path(out) if Path(out).is_absolute() else self.root / out

    def integrity_record(self) -> dict:
        """The integrity record when it has the shape this script writes, lists of digests; in any other shape (an
        agent's write, a damaged file) it vouches for nothing."""
        try:
            record = read_json(self.integrity_path())
        except (ValueError, RecursionError):
            return {}
        if not isinstance(record, dict) or not all(isinstance(record.get(k, []), list) and
                                                   all(isinstance(d, str) for d in record.get(k, []))
                                                   for k in ("state", "candidates")):
            return {}
        return record

    def exists(self) -> bool:
        return self.state_path.exists()

    def load(self) -> "Ledger":
        if not self.exists():
            die(f"no run in {self.dir}; start one with `ledger.py init`")
        if run(["git", "ls-files", "--", LEDGER], self.root).stdout.strip():
            die(f"{LEDGER}/ is tracked by git, so the run in it is not this ledger's to trust: ask the user "
                f"(`git rm -r --cached {LEDGER}` untracks it)")
        state = self.state_path.read_bytes()
        cands = self.cands_path.read_bytes() if self.cands_path.exists() else b""
        try:
            self.state = json.loads(state)
            self.cands = (json.loads(cands) if cands else {}).get("items", {})
        except (ValueError, RecursionError, AttributeError) as err:
            die(f"{self.dir} holds unreadable state ({err}); start over with `ledger.py init --force`")
        if not isinstance(self.state, dict) or self.state.get("schema") != SCHEMA_VERSION:
            die(f"{self.state_path} comes from another version of this script; start over with `init --force`")
        record = self.integrity_record()
        if digest(state) not in record.get("state", []) or digest(cands) not in record.get("candidates", []):
            die(f"{self.dir} was changed by something other than ledger.py (an agent's write?), so its gate commands, "
                "votes and plans can no longer be trusted: tell the user; `ledger.py init --force` starts over")
        if self.state.get("root") != str(self.root):
            die(f"{self.state_path} belongs to a run in {self.state.get('root')}; start over with `init --force`")
        self._digests = {"state": digest(state), "candidates": digest(cands)}
        return self

    def save(self) -> None:
        cands = (json.dumps({"items": self.cands}, indent=1) + "\n").encode("utf-8")
        state = (json.dumps(self.state, indent=1) + "\n").encode("utf-8")
        new = {"state": digest(state), "candidates": digest(cands)}
        # While the two files are rewritten both versions are valid, so a kill in between leaves a run that loads.
        both = {k: sorted({new[k], self._digests.get(k)} - {None}) for k in new}
        write_json(self.integrity_path(), dict(both, root=str(self.root)))
        # state.json last: it is what every command reads first, so a kill between the two writes leaves
        # candidates a later command can still reach, never state pointing at candidates that do not exist.
        write_bytes(self.cands_path, cands)
        write_bytes(self.state_path, state)
        write_json(self.integrity_path(), {"state": [new["state"]], "candidates": [new["candidates"]],
                                           "root": str(self.root)})
        self._digests = new

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
    if kind != "dependency":
        # Only a tracked file can be checked against HEAD and rolled back: a path outside the
        # repository, behind a symlink, or in the user's untracked work is never edited.
        if file not in lg.tracked():
            lg.foreign.append(file)
            return None
        if not lg.in_scope(file) or matches(file, NEVER_SCAN):
            return None
    line = line if isinstance(line, int) and not isinstance(line, bool) and line > 0 else None
    symbol = clean(symbol, 200)
    decl = ""
    if line and kind not in ("file", "dependency"):
        lines = read_lines(lg.root / file) or []
        term = term_of({"kind": kind, "symbol": symbol, "file": file})
        if term and line <= len(lines) and term not in tokens(lines[line - 1]):
            # Analyzers such as vulture name a decorated definition by its first decorator line.
            line = next((n for n in range(line + 1, min(len(lines), line + 30) + 1) if term in tokens(lines[n - 1])), line)
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
        "pinned": False, "line_sha": lg.head() if line else None,
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
    # Every later step treats a tracked change outside a wave as an agent's stray and puts it back,
    # so a run starts from a clean tree: then nothing it discards can be the user's work.
    dirty = [e[3:] for e in os.fsdecode(run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=no",
                                            "--ignore-submodules=dirty"], root).stdout).split("\0")
             if len(e) > 3]
    old = verified_state(lg) if lg.exists() else None
    lg.state = {"restored": []}  # copies made here, carried into the new run
    if dirty and args.force and old is not None:
        dirty = put_back_open_wave(lg, dirty, old)
    if dirty and args.force and lg.exists() and old is None:
        die(f"tracked files have uncommitted changes, e.g. {clean(dirty[0])}, and the previous run's state cannot be "
            "read or verified: they may be its unverified removals, never to be committed, or someone's own work: "
            "stop and ask the user")
    if dirty:
        die("tracked files have uncommitted changes (`git status`): ask the user to commit them first; "
            "the run never stashes or discards work it did not make")
    carry = [e for e in ((old or {}).get("restored") or []) + lg.state["restored"] if isinstance(e, dict)]
    # The copies of discarded changes are never deleted: the old run's go into the new one (verified or quarantined),
    # and an older .dead-code.prev is deleted only once it holds none that were not carried.
    prev, aside = root / f"{LEDGER}.prev", None
    if lg.dir.exists():
        if prev.is_dir() and not prev.is_symlink() and not any(holds_files(p) for p in copy_tops(prev)):
            shutil.rmtree(prev)
        elif prev.exists() or prev.is_symlink():  # copies no run carried yet, or not a folder the ledger made
            aside = free_name(prev)
            os.rename(prev, aside)
        shutil.move(str(lg.dir), str(prev))
    lg.dir.mkdir(parents=True)
    copies = carry_copies(root, carry)
    kept = quarantine(root, [prev, aside])
    if aside is not None and aside.is_dir() and not aside.is_symlink():
        if any(holds_files(p) for p in copy_tops(aside)):
            print(f"warning: {aside.name} still holds copies that could not be moved into the new run: it is kept")
        else:
            shutil.rmtree(aside)
    elif aside is not None:
        print(f"note: {prev.name} was not a folder the ledger made (a file or a link): it is kept as {aside.name}")
    if copies:
        print(f"{len(copies)} folder(s) of copies the previous run kept are carried into {LEDGER}/restored/")
    if kept:
        print(f"{len(kept)} folder(s) of copies the ledger cannot vouch for are kept in "
              f"{', '.join(e['folder'] for e in kept[:3])}: they may hold someone's work (the report lists them)")
    lg.state = {"restored": copies + kept}
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
    carried = lg.state["restored"]
    lg.state = {
        "schema": SCHEMA_VERSION, "created": now(), "root": str(root), "base_sha": head, "branch": branch,
        "scope": scope, "protect": as_globs(args.protect, root), "tests": DEFAULT_TESTS + list(args.tests),
        "gate": {"fast": args.gate_fast, "full": args.gate_full}, "mode": mode,
        "max_rounds": args.max_rounds, "round": 1, "finished": False, "confirmed": None,
        "notes": list(args.note), "analyzers": {}, "skipped": {}, "units": {}, "current_wave": None,
        "counters": {}, "keys": {}, "history": [], "emptied": [], "refs_round": None, "ignore": [], "gates": [], "restore": [],
        "restored": carried,
    }
    # Whatever is already untracked was there before this run. These paths are matched exactly, never
    # as globs, and only against untracked files: a change to a tracked file always counts. Their sizes
    # and times are kept too: an agent that edits the user's untracked work is reported.
    lg.state["untracked"] = sorted(p for p in os.fsdecode(run(["git", "ls-files", "-o", "--exclude-standard", "-z"],
                                                              root).stdout).split("\0") if p and not in_ledger(p))
    lg.state["hidden"] = hidden_snapshot(lg)
    lg.state["preexisting"] = {}
    for p in lg.state["untracked"]:
        try:
            st = (root / p).stat()
            lg.state["preexisting"][p] = [st.st_size, st.st_mtime_ns]
        except OSError:
            pass
    lg.save()
    files = tracked_files(root)
    for g in args.protect:
        if not any(matches(f, [x]) for x in as_globs([g], root) for f in files):
            print(f"warning: --protect {clean(g, 120)} matches no tracked file (stored as "
                  f"{', '.join(clean(x, 120) for x in as_globs([g], root))})")
    hidden = set(files) - set(tracked_files(root, editable=True))
    if hidden:
        print(f"note: {len(hidden)} tracked file(s) are marked assume-unchanged or skip-worktree, e.g. "
              f"{clean(sorted(hidden)[0])}: the run leaves them out, since it could neither check nor roll back "
              "a change to them")
    print(f"run started in {lg.dir} on {branch or 'detached HEAD'} at {head[:12]}")
    if Path.cwd().resolve() != root.resolve():
        print(f"warning: the session runs in {Path.cwd()}, not at the repository root {root}: agents must read and "
              "write under the root, so start Claude Code there or `/add-dir` it")
    print(f"scope: {', '.join(scope) or 'whole repository'} | mode: {mode} | "
          f"gate: fast={args.gate_fast or '-'} full={args.gate_full or '-'}")
    gates = " and ".join(f"`ledger.py gate {k}`" for k in ("fast", "full") if lg.state["gate"][k])
    say_next(f"baseline: {gates} (it must be green); then "
             "`ledger.py analyze` the analyzers that fit the stack, and `ledger.py shard --ext ...` for the "
             "languages none covers" if mode == "fix" else
             "`ledger.py analyze` the analyzers that fit the stack, then `ledger.py shard --ext ...` for the "
             "languages none covers")


def verified_state(lg: Ledger):
    """The run's state as last saved by this script, when its integrity record vouches for it; else None."""
    try:
        raw = lg.state_path.read_bytes()
        old = json.loads(raw) if digest(raw) in lg.integrity_record().get("state", []) else None
    except (OSError, ValueError, RecursionError, AttributeError, TypeError):
        return None
    return old if isinstance(old, dict) else None


def put_back_open_wave(lg: Ledger, dirty: list, old: dict) -> list:
    """`init --force` over a run that left its own changes uncommitted: the files of its open wave (dispatched,
    ingested or failed units), of its restore queue, and of a bisect cut short. When every uncommitted change
    is one of those, they are that run's unverified removals, never to be committed: they are put back with a
    copy, as any restore does. Returns the changes still in the way."""
    wave = old.get("current_wave")
    files = set(old.get("restore") or []) | set((old.get("bisecting") or {}).get("files") or [])
    for u in (old.get("units") or {}).values():
        if isinstance(u, dict) and u.get("stage") == "remove" and u.get("wave") == wave \
                and u.get("status") in ("dispatched", "ingested", "failed"):
            files |= set(u.get("allowed") or []) | set(u.get("deletes") or [])
    if not files or not set(dirty) <= files or gitlinks(lg, dirty) or any(layout_changed(lg, p) for p in dirty):
        return dirty
    folder = save_copy(lg, dirty, {p: "the previous run's own uncommitted change (an unverified removal), put back "
                                      "by `init --force`" for p in dirty})
    in_head = [p for p in dirty if lg.in_head(p)]
    if in_head:
        run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"] + in_head, lg.root)
    added = [p for p in dirty if p not in in_head]
    if added:
        run(["git", "restore", "--staged", "--"] + added, lg.root, check=False)
    print(f"the previous run's last changes were never committed: its {len(dirty)} file(s) are back at HEAD"
          + (", and what they held is kept (see the report)" if folder else ""))
    return []


def carry_copies(root: Path, entries: list) -> list:
    """The copies of discarded changes a previous run recorded, moved from .dead-code.prev into the new run
    with their causes: a copy is kept as long as the user may still want it. One whose files changed since it
    was saved stays behind, and quarantine() carries it as unverified: whatever is left in a copy folder of
    .dead-code.prev is then exactly what was not carried."""
    out, stamp = [], now().replace(":", "")
    for e in entries:
        moved = dict(e, folder=str(e.get("folder", "")).replace(LEDGER + "/", LEDGER + ".prev/", 1))
        src = root / moved["folder"]
        if not src.is_dir() or src.is_symlink() or not copy_intact(root, moved):
            continue
        dest = root / LEDGER / "restored" / f"earlier-{stamp}-{len(out) + 1:03d}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(src, dest)
        except OSError:
            continue  # left for quarantine()
        out.append(dict(e, folder=dest.relative_to(root).as_posix(), carried=True))
    return out


def copy_tops(folder: Path) -> list:
    """The folders of a ledger folder where save_copy keeps copies (restored, restored.d, restored.2, ...), or
    whatever took their names."""
    try:
        return sorted(p for p in folder.iterdir() if p.name == "restored" or p.name.startswith("restored."))
    except OSError:
        return []


def holds_files(path: Path) -> bool:
    """Whether there is anything at `path` but empty folders."""
    if path.is_symlink() or not path.is_dir():
        return path.is_symlink() or path.exists()
    return any(p.is_symlink() or not p.is_dir() for p in path.rglob("*"))


def free_name(path: Path) -> Path:
    """`path` with the first suffix .1, .2, ... that names nothing yet."""
    n = 1
    while path.with_name(f"{path.name}.{n}").exists() or path.with_name(f"{path.name}.{n}").is_symlink():
        n += 1
    return path.with_name(f"{path.name}.{n}")


def quarantine(root: Path, folders: list) -> list:
    """What the copy folders of the replaced runs (.dead-code.prev, and an older one moved aside) still hold once
    carry_copies took the copies it could verify: a copy changed since it was saved, the copies of a run whose
    state cannot be verified, files the ledger never recorded (a copy a killed command saved, an agent's plant).
    None of it is deleted: each folder moves into the new run as restored/unverified-<time>-<n>/<its name>, with
    the digests of its files, and the report lists it as possibly holding someone's work."""
    out, stamp = [], now().replace(":", "")
    for top in folders:
        if top is None or top.is_symlink() or not top.is_dir():
            continue
        for src in copy_tops(top):
            if not holds_files(src):
                continue
            n = len(out) + 1
            while (root / LEDGER / "restored" / f"unverified-{stamp}-{n:03d}").exists():
                n += 1
            dest = root / LEDGER / "restored" / f"unverified-{stamp}-{n:03d}"
            dest.mkdir(parents=True)
            try:
                os.rename(src, dest / src.name)
            except OSError as err:
                print(f"warning: {top.name}/{clean(src.name)} could not be moved into the new run ({clean(err, 120)}): "
                      "it stays where it is")
                dest.rmdir()
                continue
            hashes = {}
            for p in dest.rglob("*"):
                try:
                    if p.is_file() and not p.is_symlink():
                        hashes[p.relative_to(dest).as_posix()] = digest(p.read_bytes())
                except OSError:
                    pass  # unreadable: listed with the files the ledger did not write
            out.append({"folder": dest.relative_to(root).as_posix(), "head": "", "at": now(), "files": {},
                        "hashes": hashes, "carried": True,
                        "unverified": f"what {top.name}/{clean(src.name)} held that the ledger could not vouch for"})
    return out


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


def python_scopes(path: Path):
    """For a Python file, ({(name, line)} bound inside a function or lambda, parameters included,
    {(name, line)} bound in a class body), or None when it does not parse here."""
    try:
        with warnings.catch_warnings():  # `PYTHONWARNINGS=error` must not make a valid file unreadable
            warnings.simplefilter("ignore")
            tree = ast.parse(path.read_bytes())
    except (SyntaxError, ValueError, OSError, RecursionError, MemoryError, Warning):
        return None
    local, members = set(), set()

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = child.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
                    if arg is not None:
                        local.add((arg.arg, arg.lineno))
                visit(child, "function")
            elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                visit(child, "function")  # a comprehension's names live in a scope of their own
            elif isinstance(child, ast.ClassDef):
                visit(child, "class")
            else:
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store) and scope != "module":
                    (local if scope == "function" else members).add((child.id, child.lineno))
                if isinstance(child, ast.ExceptHandler) and child.name and scope == "function":
                    local.add((child.name, child.lineno))
                visit(child, scope)
    visit(tree, "module")
    return local, members


def import_vulture(lg: Ledger, text: str, base: str) -> int:
    added = ignored = 0
    scopes = {}
    for line in text.splitlines():
        m = VULTURE.match(line.strip())
        if not m:
            continue
        kind, file, n = VULTURE_KINDS.get(m["what"]), rel(lg.root, m["file"], base), int(m["line"])
        if kind == "variable":
            # Parameters and locals are the linter's (ruff ARG, F841), and deleting a local such as
            # `result = db.commit()` drops a call; a name bound in a class body is a member.
            if file not in scopes:
                scopes[file] = python_scopes(lg.root / file)
            found = scopes[file]
            if found is None:  # it does not parse here: keep only a module-level assignment to that name
                lines = read_lines(lg.root / file) or []
                line = lines[n - 1] if 0 < n <= len(lines) else ""
                kind = kind if re.match(re.escape(m["name"]) + r"\s*(?::[^=]*)?=(?!=)", line) else None
            elif (m["name"], n) in found[0]:
                kind = None
            elif (m["name"], n) in found[1]:
                kind = "member"
        if kind is None:
            ignored += 1  # imports, arguments and locals: the project's linter fixes those (ruff F401, F841, ARG)
            continue
        added += bool(add_candidate(lg, file=file, symbol=m["name"], kind=kind, line=n, source="vulture",
                                    detail=f"vulture: unused {m['what']} ({m['conf']}%)"))
    if ignored:
        print(f"left {ignored} unused import, argument or local finding(s) to the project's linter")
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


STATICCHECK = re.compile(r"^(?P<what>func|type|field|const|var)\s+(?P<name>.+?)\s+is unused")
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
        names = re.findall(r"[A-Za-z_]\w*", name.rsplit("]", 1)[-1].rsplit(")", 1)[-1])  # `(*Cache[K, V]).evict`
        added += bool(names) and bool(add_candidate(lg, file=rel(lg.root, loc.get("file", ""), base), symbol=names[-1] if names else "",
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
    """Book an import and warn about findings whose files git does not track here."""
    new = [c for c in lg.cands.values() if int(c["id"][1:]) > before]
    added = len(new)
    lg.state["analyzers"][name] = lg.state["analyzers"].get(name, 0) + added
    lg.state["imported_round"] = lg.state["round"]
    missing = [c["file"] for c in new if c["kind"] != "dependency" and not (lg.root / c["file"]).exists()]
    lg.save()
    deps = sum(1 for c in lg.cands.values() if c["kind"] == "dependency")
    print(f"{name}: {added} new candidate(s); {len(lg.cands)} known, {deps} of them unused dependencies")
    if lg.foreign:
        print(f"warning: {len(lg.foreign)} finding(s) left out because git does not track their file here, e.g. "
              f"{clean(lg.foreign[0])} (outside the repository, behind a symlink, or untracked): if the analyzer ran in a "
              "subdirectory, import again with --base <that directory>")
        lg.foreign.clear()
    if missing:
        print(f"warning: {len(missing)} finding(s) name tracked files missing on disk (sparse checkout?), "
              f"e.g. {missing[0]}")


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


# Programs `analyze` may start for each tool, in the forms references/analyzers.md shows: no program
# from a path an agent could write, no runner option that names another package, interpreter or index,
# no package from a path, a URL or git. This keeps `analyze` from being a shortcut to any command. It is
# no security boundary: the gate commands `init` records run under the same pre-approved rule.
ANALYZER_PROGRAMS = {
    "knip": {"npx", "pnpm", "pnpx", "yarn", "bunx", "knip"}, "vulture": {"uvx", "vulture", "pipx"},
    "cargo": {"cargo"}, "staticcheck": {"go", "staticcheck"}, "deadcode": {"go", "deadcode"},
    "phpstan": {"phpstan", "php", "composer"}, "debride": {"debride", "bundle"},
    "sarif": {"pmd", "detekt", "detekt-cli", "dotnet", "gradle", "gradlew", "mvn", "mvnw", "jb"},
}
# What a package runner must start, so that `npx` or `go run` cannot run anything else.
ANALYZER_PACKAGES = {"knip": {"knip"}, "vulture": {"vulture"}, "debride": {"debride"},
                     "phpstan": {"phpstan", "vendor/bin/phpstan"}, "deadcode": {"golang.org/x/tools/cmd/deadcode"},
                     "staticcheck": {"honnef.co/go/tools/cmd/staticcheck"}}
RUNNERS = {"npx", "pnpx", "bunx", "uvx", "pipx", "pnpm", "yarn", "bundle", "composer", "go", "php"}
# A runner's own options that make it fetch or run something other than the package it names.
RUNNER_OPTIONS = {"--package", "-p", "--call", "-c", "--from", "--with", "--with-editable", "--with-requirements",
                  "--python", "--index", "--index-url", "--extra-index-url", "--find-links", "-f", "--spec",
                  "-toolexec", "-exec", "-modfile", "-overlay", "--require", "-r", "--node-options", "-d"}
# Options of the analyzers themselves that load code from elsewhere.
TOOL_OPTIONS = {"cargo": ("--config", "-Z"), "detekt": ("--plugins",), "detekt-cli": ("--plugins",),
                "phpstan": ("--autoload-file", "-a"), "gradle": ("--init-script", "-I"), "gradlew": ("--init-script", "-I"),
                "dotnet": ("-t:", "-target:", "--target", "/t:", "/target:")}
TOOL_PATHS = ("vendor/bin/", "node_modules/.bin/", "./vendor/bin/", "./node_modules/.bin/")
# The sub-commands through which a runner starts a package's program.
RUNNER_SUBCOMMANDS = {"go": ("run",), "pnpm": ("exec", "dlx", "run"), "yarn": ("exec", "dlx", "run"),
                      "composer": ("exec", "run"), "bundle": ("exec",), "pipx": ("run",)}
PACKAGE = re.compile(r"[\w@][\w.@/+-]*")  # a name, a scope, a module path, a version: no `:`, so no URL or file:


def analyzer_allowed(tool: str, argv: list) -> bool:
    """Whether a command starts the analyzer it claims to: the ledger runs it behind a pre-approved rule."""
    if not argv or tool not in ANALYZER_PROGRAMS:
        return False
    if "/" in argv[0] and not argv[0].startswith(TOOL_PATHS) and argv[0] not in ("./gradlew", "./mvnw"):
        return False  # a program at some other path, which an agent could have written
    program = Path(argv[0]).name
    if program not in ANALYZER_PROGRAMS[tool]:
        return False
    banned = TOOL_OPTIONS.get(program, ())
    if banned and any(a.startswith(banned) for a in argv[1:]):
        return False
    if program in ("mvn", "mvnw") and any("exec:" in a or "exec." in a for a in argv[1:]):
        return False
    if tool == "cargo":
        return next((a for a in argv[1:] if not a.startswith(("-", "+"))), "") in ("check", "clippy", "build")
    if tool == "sarif" and program == "dotnet":
        return next((a for a in argv[1:] if not a.startswith("-")), "") == "build"
    if program not in RUNNERS:
        return True
    words = list(argv[1:])
    for step in (1, 2):  # the runner's own options, then those after its sub-command (`go run -exec`, `pnpm dlx`)
        while words and words[0].startswith("-"):
            if words[0].split("=", 1)[0] in RUNNER_OPTIONS:
                return False
            words = words[1:]
        if step == 2 or program not in RUNNER_SUBCOMMANDS:
            break
        if words[:1] and words[0] in RUNNER_SUBCOMMANDS[program]:
            words = words[1:]
        elif program == "go":
            return False
        else:
            break
    first = words[0] if words else ""
    if not PACKAGE.fullmatch(first) or ".." in first:
        return False
    return (first.rsplit("@", 1)[0] if "@" in first[1:] else first) in ANALYZER_PACKAGES.get(tool, set())

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
    if lg.units(status="dispatched"):
        die("a stage is still dispatched: its agents may be editing; wait for its workflow, then `ledger.py ingest "
            "<stage>` first")
    if user_files_changed(lg) or hidden_changes(lg):
        die("files changed where `git status` cannot show them: `ledger.py check` first")
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
        problem = job_problem(lg, jobs[0])
        if problem:
            die(problem)
    failed = []
    for job in jobs:
        lg.foreign.clear()
        cwd = lg.root / job["base"] if job["base"] else lg.root
        name = job["source"] or job["tool"]
        problem = job_problem(lg, job)
        if problem:
            print(f"{name}: {problem}; skipped")
            failed.append(name)
            continue
        dest = own_folder(lg, "analyzers") / f"{name}-r{lg.state['round']}.out"
        print(f"running {name}: {' '.join(shlex.quote(a) for a in job['argv'])}")
        if job["output"]:
            (cwd / job["output"]).unlink(missing_ok=True)  # never import a report left by an earlier run
        before = status_entries(lg)
        try:
            code, stdout, stderr = run_tool(job["argv"], cwd, args.timeout)
        except FileNotFoundError:
            print(f"{name}: `{job['argv'][0]}` is not installed; cover these files with the scanners instead")
            failed.append(name)
            continue
        finally:
            tool_leftovers(lg, before, "an analyzer changed it")
        if code is None:
            print(f"{name}: timed out after {args.timeout}s; re-run with a larger --timeout or narrow it")
            failed.append(name)
            continue
        proc = subprocess.CompletedProcess(job["argv"], code, stdout, stderr)
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


def inside(path: Path, top: Path) -> bool:
    try:
        path.resolve().relative_to(top.resolve())
        return True
    except (ValueError, RuntimeError, OSError):
        return False


def job_problem(lg: Ledger, job: dict) -> str:
    """Why `analyze` must not run a recorded or requested job, or "" when it may."""
    if not analyzer_allowed(job["tool"], job["argv"]):
        return (f"`analyze --tool {job['tool']}` does not start {job['tool']} as references/analyzers.md shows; run "
                f"that command yourself, write its report inside {LEDGER}/, and `ledger.py import --tool {job['tool']} "
                "<report>`")
    cwd = lg.root / job["base"] if job["base"] else lg.root
    if not inside(cwd, lg.root) or not cwd.is_dir():
        return f"--base {job['base']} is not a folder of the repository"
    if job["output"] and (not inside(cwd / job["output"], lg.dir) or (cwd / job["output"]).is_dir()):
        return f"--output must name a file inside {LEDGER}/ (it is deleted before every run)"
    return ""


def run_tool(argv: list, cwd: Path, timeout: int) -> tuple:
    """(exit code, stdout, stderr) of an analyzer, with None for the code on a timeout. It runs in its own
    process group, so that a timeout ends the tool and whatever it started (npx's node, go run's binary)."""
    proc = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        kill_group(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
        return None, out, err
    except BaseException:
        kill_group(proc)
        raise


def tool_leftovers(lg: Ledger, before: list, cause: str) -> None:
    """After a tool run outside a wave (an analyzer, a gate, bisect's suite): the untracked files it left
    are recorded as known, and the tracked files it changed are queued to go back."""
    known = set(before)
    new = [(code, p) for code, p in status_entries(lg) if (code, p) not in known]
    artifacts = sorted(p for code, p in new if code == "??")
    if artifacts:
        lg.state["untracked"] = sorted(set(lg.state.get("untracked", [])) | set(artifacts))
    follow_tools(lg)  # its ignored artifacts (caches, build output) are the project's own
    changed = sorted({p for code, p in new if code != "??"} - wave_files(lg))
    if changed:
        queue_restore(lg, changed, cause)
        print(f"{len(changed)} tracked file(s) changed by the tool, to be restored: {', '.join(clean(p) for p in changed[:5])}")


# ----------------------------------------------------------------------- refs

def count_references(lg: Ledger, todo: list):
    """One pass over every tracked text file, counting each candidate's name and its aliases.

    Returns ({term: {"files": Counter(path), "samples": [(path, line)], "decl": Counter((path, line))}},
    files too large to read, files that could not be read or decoded, files missing on disk). `decl`
    counts the declaring occurrence on the candidates' own declaration lines, which is not a use.
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
    too_big, unread, missing = [], [], []
    for path in tracked_files(lg.root):
        if matches(path, REFS_IGNORE):
            continue
        full = lg.root / path
        try:
            if full.stat().st_size > MAX_REF_FILE_BYTES:
                too_big.append(path)
                continue
            text = decode(full.read_bytes())
        except FileNotFoundError:
            missing.append(path)  # listed by git but not on disk: a sparse checkout, or deleted
            continue
        except OSError:
            unread.append(path)
            continue
        if text is None:
            if Path(path).suffix.lower() in SOURCE_EXTS:
                unread.append(path)  # source without a byte-order mark that looks binary (UTF-16?)
            continue
        present = set(tokens(text, hyphenated=bool(path_terms))) & terms
        if not present:
            continue
        wanted = decl_lines.get(path, set())
        prose = is_prose(path)
        hyphenated = bool(present & path_terms)
        for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
            on_decl = set()
            for word in tokens(line, hyphenated):
                if word in present:
                    f = found[word]
                    f["files"][path] += 1
                    if (n, word) in wanted and word not in on_decl:
                        on_decl.add(word)  # only the declaring occurrence: a twin's line can also call it
                        f["decl"][(path, n)] += 1
                    elif prose and f["prose"] < 4:
                        f["prose"] += 1
                        f["samples"].append((path, n))
                    elif not prose and len(f["samples"]) - f["prose"] < 24:
                        f["samples"].append((path, n))
    return found, too_big, unread, missing


DECL_HINT = re.compile(r"\b(def|class|function|fn|func|interface|type|enum|struct|trait|module|const|let|var|val|"
                       r"object|protocol|public|private|protected|internal|static|export)\b")


def trace(lg: Ledger, path: str, line: int, sha: str, term: str = "") -> tuple:
    """Where line `line` of `path` at commit `sha` is in the working tree now: ("ok", line), ("gone", None) when
    that line was deleted since, or ("changed", None) when it was rewritten or the diff cannot be read. With
    `term`, a rewritten line is followed to the one line of what replaced it that still mentions `term`, if there
    is exactly one."""
    proc = run(DIFF + [sha, "--", path], lg.root, check=False)
    found = read_diff(proc.stdout) if proc.returncode == 0 else None
    if found is None:
        return "changed", None
    shift = 0
    for first, count, new_first, new_count, _, _, _, _ in found:
        if count == 0:  # lines added after line `first`
            if first >= line:
                break
            shift += new_count
            continue
        if first > line:
            break
        if line < first + count:
            if not new_count:
                return "gone", None
            lines = read_lines(lg.root / path) or [] if term else []
            hits = [k for k in range(new_first, new_first + new_count) if k <= len(lines)
                    and term in tokens(lines[k - 1])]
            return ("ok", hits[0]) if len(hits) == 1 else ("changed", None)
        shift += new_count - count
    return "ok", line + shift


def follow(lg: Ledger, path: str, line: int, sha: str, term: str = ""):
    """Where line `line` of `path` at commit `sha` is now, or None (see trace)."""
    return trace(lg, path, line, sha, term)[1]


RELOCATED = {"gone": "its file, its name or its own line no longer exists",
             "changed": "its declaration line changed since it was judged: check by hand whether it is still dead",
             "ambiguous": "identical declarations share its text in this file: check by hand which is dead"}


def relocate(lg: Ledger, c: dict) -> str:
    """Point a candidate at the line that now declares it: "ok"; "gone" when its file, its name or its own
    line is gone; "changed" when its own line was rewritten; "ambiguous" when identical twins leave no way to
    tell which one it is (see RELOCATED).

    A line recorded at a known commit is followed through the diff since then, and only that: a declaration
    whose own line went never lands on a same-named twin. A candidate without one (an old state) is searched
    by text: removals only delete lines, so a declaration moves up; prefer its recorded text, then a
    declaration-looking line at or above the old position, never a call site below it."""
    path = lg.root / c["file"]
    if c["kind"] == "file":
        return "ok" if path.exists() else "gone"
    term = term_of(c)
    index = line_index(path)
    hits = index.get(term, []) if index is not None and term else []
    if not hits:
        return "gone"
    lines = read_lines(path)
    if c.get("line") and c.get("line_sha"):
        where, n = trace(lg, c["file"], c["line"], c["line_sha"])
        if where != "ok":
            return where
        if n not in hits:
            return "changed"
    else:
        old = c.get("line") or 1
        same = [k for k in hits if c.get("decl") and lines[k - 1].strip()[:200] == c["decl"]]
        if len(same) > 1:
            return "ambiguous"  # `def save(self):` twice: picking the wrong one deletes live code
        looks = [k for k in hits if DECL_HINT.search(lines[k - 1])]
        pool = next(p for p in (same, [k for k in looks if k <= old], looks, [k for k in hits if k <= old], hits) if p)
        n = min(pool, key=lambda k: abs(k - old))
    c["line"], c["line_sha"] = n, lg.head()
    c["decl"] = lines[n - 1].strip()[:200]
    return "ok"


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
        where = relocate(lg, c)
        if where == "ok":
            live.append(c)
        else:
            set_status(c, "gone" if where == "gone" else "unsure", RELOCATED[where])
            gone += where == "gone"
    found, too_big, unread, missing = count_references(lg, live)
    category = {}

    def kind_of(p):
        if p not in category:
            category[p] = "docs" if is_prose(p) else ("tests" if lg.is_test(p) else "other")
        return category[p]
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
            if p != c["file"]:
                counts[kind_of(p)] += n
        samples = sorted(samples, key=lambda s: (s[0] == c["file"], kind_of(s[0]) == "docs", kind_of(s[0]) == "tests"))
        code = same + counts["tests"] + counts["other"] + counts["convention"]
        refs = {"total": code + counts["docs"], "code": code, "same_file": same, "tests": counts["tests"],
                "other": counts["other"] + counts["convention"], "docs": counts["docs"],
                "convention": counts["convention"], "in_file": in_file,
                "sample": [f"{p}:{n}" for p, n in samples[:8]]}
        if unread or too_big or missing:
            refs["unsearched_files"] = len(unread) + len(too_big) + len(missing)
        before = (c.get("refs") or {}).get("total")
        c["refs"] = refs
        old = c["status"]
        # Files git lists but the disk lacks (a sparse checkout) may hold its uses: no lens could see them.
        blind = f"{len(missing)} tracked file(s) are not on disk (sparse checkout?), so its uses there are unknown"
        if not term:
            set_status(c, "unsure", "its name cannot be searched as a token; check it by hand")
        elif old in ("alive", "unsure", "likely-dead"):
            if before is not None and refs["total"] < before:  # a removal took references away: judge again
                c["votes"], c["also_edit"], c["round"], c["retries"] = {}, [], lg.state["round"], 0
                status = classify(lg, c, refs)
                set_status(c, "unsure" if status == "pending" and missing else status, blind if missing else
                           f"references dropped from {before} to {refs['total']} since its last vote")
        else:
            status = classify(lg, c, refs)
            set_status(c, "unsure" if status == "pending" and missing else status, blind if missing else "")
        if c["status"] != old:
            moved[f"{old}->{c['status']}"] += 1
    lg.state["refs_round"] = lg.state["round"]
    lg.state["unsearched"] = (missing + unread)[:200]
    lg.save()
    print(f"references counted for {len(live)} candidate(s) over every tracked file; {gone} gone")
    if moved:
        print("moved: " + ", ".join(f"{k} {n}" for k, n in sorted(moved.items())))
    if too_big:
        print(f"not searched (over {MAX_REF_FILE_BYTES // 1_000_000} MB): " + ", ".join(too_big[:5]))
    if missing:
        print(f"warning: {len(missing)} tracked file(s) are not on disk (sparse checkout?), e.g. {clean(missing[0])}: "
              "no lens can see the uses they may hold, so every candidate stays unsure, for a human; check out "
              "the whole repository to remove code")
    if unread:
        print(f"warning: {len(unread)} tracked file(s) could not be read or decoded, e.g. {clean(unread[0])}; "
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
    if lg.state.get("restore"):
        die("files are waiting to be restored first: `ledger.py restore`")
    # No agent is working, and every wave was committed: a tracked change now is someone else's work.
    # Agents' strays are caught when their stage is ingested, so these are never put back by the ledger.
    if hidden_changes(lg):
        die("files changed where `git status` cannot show them: `ledger.py check` first")
    dirty = [p for p in changed_paths(lg, untracked=False) if p not in wave_files(lg)]
    if dirty:
        die(f"{len(dirty)} tracked file(s) have uncommitted changes that no agent of this run made, e.g. {clean(dirty[0])}: "
            "stop and ask the user to commit or discard them; the ledger never discards them itself")
    if args.stage == "scan":
        units = lg.units("scan", "ready")
    elif args.stage == "verify":
        units = lg.units("verify", "ready") + plan_verify(lg)
    else:
        units = plan_remove(lg)
        lg.save()  # what planning dropped or skipped stays so, even when nothing is left to dispatch
        if units is None:
            return
    if not units:
        print(f"nothing to dispatch for {args.stage}")
        say_next(next_step(lg))
        return
    held = units[DISPATCH_CAP:]  # a workflow run stops at 1,000 agents: the rest waits for the next dispatch
    units = units[:DISPATCH_CAP]
    own_folder(lg, "out")
    for u in units:
        u["status"] = "dispatched"
        u["dispatched_at"] = now()
        write_unit(lg, u)
        # Only this dispatch's agent may author the output: drop anything written ahead of it.
        out = lg.out_path(u["id"], u["stage"])
        if out.is_dir() and not out.is_symlink():
            shutil.rmtree(out, ignore_errors=True)
        else:
            out.unlink(missing_ok=True)
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


def remove_edits(lg: Ledger, u: dict) -> list:
    """A removal unit's edits, from the ledger's state: one per declaration, and one per deleted file
    whose importers need fixing, with the also_edit sites in the files the unit may edit."""
    covered = u.get("covered", {})
    edits = []
    for cid in u["candidates"]:
        c = lg.cands[cid]
        sites = [e for e in c["also_edit"] if e["file"] in u["allowed"]]
        if cid not in covered and (c["kind"] != "file" or sites):
            edits.append(dict(brief(c), also_edit=sites,
                              remove="nothing in this file: the orchestrator deletes it; fix only the also_edit sites"
                              if c["kind"] == "file" else "the declaration"))
    return edits


def own_folder(lg: Ledger, name: str) -> Path:
    """The ledger's own folder `name` under .dead-code/, made if missing. A file or a link standing there was not
    made by the ledger (agents can write under .dead-code/): it is moved aside, never followed or written
    through, and the move is said, so the command goes on instead of failing on it every time."""
    folder = lg.dir / name
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        k = 1
        while (lg.dir / f"{name}.aside-{k}").exists() or (lg.dir / f"{name}.aside-{k}").is_symlink():
            k += 1
        os.rename(folder, lg.dir / f"{name}.aside-{k}")
        print(f"note: {LEDGER}/{name} was a file or a link the ledger did not make: moved aside to {name}.aside-{k}")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_unit(lg: Ledger, u: dict) -> None:
    """Write a unit's file from the ledger's state as it is dispatched. Nothing reads it back: agents
    can write anywhere, so a unit file can be stale or forged, and only the state counts."""
    spec = {"unit": u["id"], "stage": u["stage"], "root": str(lg.root), "output": str(lg.out_path(u["id"], u["stage"]))}
    if u["stage"] == "scan":
        spec["files"] = u["files"]
    elif u["stage"] == "verify":
        spec.update(lens=u["lens"], notes=lg.state["notes"], candidates=[brief(lg.cands[cid]) for cid in u["candidates"]])
    else:
        spec.update(wave=u["wave"], allowed_files=u["allowed"], deleted_by_orchestrator=u["deletes"],
                    edits=remove_edits(lg, u))
    own_folder(lg, "units")
    write_json(lg.unit_path(u["id"]), spec)


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
            u = {"id": unit, "stage": "verify", "status": "ready", "round": lg.state["round"], "lens": lens,
                 "wave": None, "retries": 0, "items": len(batch), "candidates": [c["id"] for c in batch]}
            lg.state["units"][unit] = u
            for c in batch:
                c["unit"] = unit
                set_status(c, "queued")
            units.append(u)
    return units


def wrong_branch(lg: Ledger) -> str:
    """A refusal when the checked-out branch is not the run's, else ""."""
    want = lg.state.get("branch")
    have = run(["git", "branch", "--show-current"], lg.root, check=False).stdout.decode().strip()
    if not want or have == want:
        return ""
    return f"the run works on {want}, but {have or 'a detached HEAD'} is checked out: `git switch {want}`"


def plan_remove(lg: Ledger):
    if lg.state["mode"] != "fix":
        print("this run is report-only; nothing is removed")
        say_next("ledger.py report")
        return None
    if lg.state.get("finished"):
        print("the run is finished: nothing more is removed")
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
    if wrong_branch(lg):
        die(wrong_branch(lg))
    if baseline_step(lg):
        die(f"no green baseline yet: {baseline_step(lg)}")
    ready = lg.units("remove", "ready")
    if not ready:
        build_removal_waves(lg)
        ready = lg.units("remove", "ready")
    if not ready:
        return []
    wave = min(u["wave"] for u in ready)
    lg.state["current_wave"] = wave
    lg.state["wave_base"] = head_sha(lg)  # what `commit` checks every removal against
    units = [u for u in ready if u["wave"] == wave]
    for u in units:  # earlier waves shifted lines: follow every declaration and every also_edit site
        for cid in list(u["candidates"]):
            c = lg.cands[cid]
            if cid in u.get("covered", {}):
                continue
            where = relocate(lg, c) if c["kind"] != "file" else "ok"
            if where != "ok":
                drop_from_unit(lg, u, cid)
                c["unit"] = None
                set_status(c, "gone" if where == "gone" else "unsure", RELOCATED[where])
                continue
            for e in c["also_edit"]:
                if e.get("line") and e.get("sha"):  # a line an earlier wave rewrote is followed by the name it holds
                    e["line"], e["sha"] = follow(lg, e["file"], e["line"], e["sha"], term_of(c)), lg.head()
    # Statuses change after planning (a mark, a relocation just above): what would delete one that must stay waits.
    held, sources = held_by_file(lg), {}
    for u in units:
        for cid in list(u["candidates"]):
            c = lg.cands[cid]
            why = "" if cid not in u["candidates"] or cid in u.get("covered", {}) else kept_whole(lg, c, held, sources)
            if why:
                drop_from_unit(lg, u, cid)
                c["unit"] = None
                set_status(c, "unsure", why)
                print(f"{cid} `{clean(c['symbol'], 80)}` stays: {why}")
    return [u for u in units if u["candidates"]]


def held_by_file(lg: Ledger) -> dict:
    """{file: [candidates]} of the declarations that must stay whatever else goes: found alive, unsure, reverted,
    referenced, likely-dead or test-only, or pinned by a human."""
    held = defaultdict(list)
    for c in lg.cands.values():
        if c["kind"] not in ("file", "dependency") and (c["status"] in ("alive", "unsure", "reverted", "referenced",
                                                                         "likely-dead", "test-only")
                                                        or c.get("pinned") and c["status"] not in ("dead", "removed")):
            held[c["file"]].append(c)
    return held


def kept_whole(lg: Ledger, c: dict, held: dict, sources: dict) -> str:
    """Why a dead candidate must stay after all, or "": removing it would delete one that must stay (held_by_file),
    in the file it deletes, or within what the diff guard lets its removal delete on HEAD: its declaration's extent
    and the blocks that go with it (a class holding a live method, the same declaration under a second name)."""
    others = [o for o in held.get(c["file"], []) if o is not c]
    if not others or c["kind"] == "dependency":
        return ""
    if c["kind"] == "file":
        # A name only mentioned elsewhere (`referenced`, never judged) holds no file its three lenses found
        # unreachable: nothing outside can use a declaration in a file nothing loads.
        judged = [o for o in others if o["status"] != "referenced" or o.get("pinned")]
        if not judged:
            return ""
        return (f"{judged[0]['id']} `{clean(judged[0]['symbol'], 80)}` in it is {judged[0]['status']}: the file "
                "stays, and its dead declarations go one by one")
    where, line = followed(lg, c)
    if where != "ok":
        return ""  # its own line moved where it cannot be followed: relocate() keeps it from any wave
    if c["file"] not in sources:
        src = Source(head_lines(lg, c["file"]), c["file"])
        sources[c["file"]] = src, {k for a, b in statements(src) for k in range(a, b + 1)}
    src, items = sources[c["file"]]
    if line > len(src.head) or line in items:
        return ""  # an item of an import or export, which the guard judges item by item
    spans = [extent(src, line, term_of(c))]
    if c["kind"] in ("class", "type"):
        m = TYPE_WORD.search(src.code[line - 1])
        spans += wrappers(src, spans, [(term_of(c), m.group(1) if m else "", indent_of(src.head[line - 1]))])
    lines = {k for a, b in spans for k in range(a, b + 1)}
    for o in others:
        where, n = followed(lg, o)
        if where == "ok":
            inside = n in lines
        else:  # its line cannot be followed: any code there naming it counts (any at all, when it has no name)
            inside = where != "gone" and (not term_of(o) or any(term_of(o) in tokens(src.code[k - 1]) for k in lines))
        if inside:
            return (f"{o['id']} `{clean(o['symbol'], 80)}` within its lines is {o['status']} (a declaration inside "
                    "it, or the same one under another name): it stays, and its dead parts go one by one")
    return ""


def followed(lg: Ledger, c: dict) -> tuple:
    """("ok", line): where the line a candidate was recorded on is in HEAD, which the tree matches while a wave is
    planned; ("gone", None) when that line was deleted since; ("unknown", None) when it cannot be told."""
    line, sha = c.get("line"), c.get("line_sha")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1 or not sha:
        return "unknown", None
    if sha == lg.head():
        return "ok", line
    where, n = trace(lg, c["file"], line, sha)
    return (where, n) if where in ("ok", "gone") else ("unknown", None)


def removable(lg: Ledger, c: dict, blobs: dict) -> str:
    """Why a dead candidate must not be planned, or "" when it may be: `mark`, or an old state, can put
    anything in `dead`, so planning checks again what deleting needs."""
    if c["kind"] == "dependency":
        return "a dependency is removed with the package manager, never by an agent"
    if tally(c) != "dead":
        return "it lacks three dead votes at the required confidence"
    if c["file"] not in lg.tracked():
        return "its file is not one this run can check and roll back (untracked, gone, or hidden from git status)"
    if lg.is_protected(c["file"]) or matches(c["file"], NEVER_SCAN):
        return "its file is protected, vendored, generated or a migration"
    if c["file"] not in blobs:
        blobs[c["file"]] = run(["git", "cat-file", "blob", f"HEAD:{c['file']}"], lg.root, check=False).stdout
    if c["kind"] != "file" and not diffable(blobs[c["file"]]):
        return "its file is binary or UTF-16, so no removal in it could be checked line by line"
    for e in c.get("also_edit", []):
        if e["file"] not in blobs:
            blobs[e["file"]] = run(["git", "cat-file", "blob", f"HEAD:{e['file']}"], lg.root, check=False).stdout
        if not diffable(blobs[e["file"]]):
            return f"an edit it needs is in {clean(e['file'], 120)}, which is binary or UTF-16, so it could not be checked"
    return ""


def build_removal_waves(lg: Ledger) -> None:
    dead, blobs = [], {}
    for c in [c for c in lg.cands.values() if c["status"] == "dead"]:
        why = removable(lg, c, blobs)
        if why:
            set_status(c, "skipped", why)
        else:
            dead.append(c)
    # A file, or a declaration (a class, a module, an impl), that still holds a declaration found alive, unsure or
    # reverted is not dead as a whole: it stays, and its dead declarations go one by one.
    held, sources, kept = held_by_file(lg), {}, []
    for c in list(dead):
        why = kept_whole(lg, c, held, sources)
        if why:
            set_status(c, "unsure", why)
            dead.remove(c)
            kept.append(c)
    if kept:
        print(f"{len(kept)} dead candidate(s) stay, since removing them would remove what must stay, e.g. "
              f"{kept[0]['id']} `{clean(kept[0]['symbol'], 80)}`: {kept[0]['note']}")
    if not dead:
        return
    # A site inside a file about to be deleted needs no edit, but it ties the two removals together:
    # they share a component, and the file goes first, so no wave edits what another one deletes.
    dying = {c["file"] for c in dead if c["kind"] == "file"}
    for c in dead:
        c["also_edit"] = [e for e in c["also_edit"] if (lg.root / e["file"]).exists()]
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
        rest = sorted((c for c in members if c["id"] not in covered),
                      key=lambda c: (c["kind"] != "file", c["file"], c.get("line") or 0))
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
            edit_files = sorted(set().union(*(files_of(c) for c in chunk)) - dying)
            u = {"id": unit, "stage": "remove", "status": "ready", "round": lg.state["round"], "lens": None,
                 "wave": wave, "retries": 0, "items": len(chunk) + len(riders),
                 "candidates": [c["id"] for c in chunk + riders], "allowed": edit_files, "deletes": deletes,
                 "covered": {c["id"]: covered[c["id"]] for c in riders}}
            u["agent"] = bool(remove_edits(lg, u))
            lg.state["units"][unit] = u
            for c in chunk + riders:
                c["unit"] = unit
                set_status(c, "planned")
    print(f"{len(dead)} dead candidate(s) planned in {sum(load.values())} removal unit(s) over {len(load)} wave(s)")


# --------------------------------------------------------------------- ingest

def cmd_ingest(args) -> None:
    lg = Ledger(git_root()).load()
    {"scan": ingest_scan, "verify": ingest_verify, "remove": ingest_remove}[args.stage](lg)


def jsonl(path: Path):
    """Yield (line number, object or error message) for each non-blank line of a JSONL file; nothing when it
    is not a regular file that can be read (an agent that wrote a folder there wrote no output)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() and not path.is_symlink() else ""
    except OSError:
        text = ""
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError as err:
            yield n, f"not JSON ({err.msg})"
            continue
        except ValueError as err:  # an integer of more than 4,300 digits, for one
            yield n, f"not usable JSON ({clean(err, 80)})"
            continue
        except RecursionError:
            yield n, "nested too deeply"
            continue
        yield n, d if isinstance(d, dict) else "not a JSON object"


def stray_step(lg: Ledger) -> str:
    """The next step, unless an agent of a read-only stage changed the working tree."""
    changed = changed_paths(lg)
    if changed:
        print(f"warning: {len(changed)} path(s) changed during a read-only stage, e.g. {clean(changed[0])}")
        return "ledger.py check"
    hidden = hidden_changes(lg)
    if hidden:
        print(f"warning: {len(hidden)} change(s) git status does not show, e.g. {hidden[0]}")
        return "ledger.py check"
    return next_step(lg)


def requeue(u: dict, why: str) -> None:
    u["retries"] += 1
    u["status"] = "failed" if u["retries"] >= MAX_RETRIES else "ready"
    print(f"{u['id']}: {why}; " + ("given up" if u["status"] == "failed" else "ready to dispatch again"))


# What a scanner may give as a symbol: a name, possibly qualified (`Cart.total`, `A::b`, `A#b`).
SYMBOL = re.compile(r"[\w$.:#?!=-]{1,200}")


def ingest_scan(lg: Ledger) -> None:
    units = lg.units("scan", "dispatched")
    if not units:
        die("no dispatched scan unit; run `ledger.py dispatch scan` first")
    added = 0
    for u in units:
        out = lg.out_path(u["id"], "scan")
        if not out.is_file():
            requeue(u, "no output file")
            continue
        files = set(u["files"])
        good, errors, skipped = 0, [], 0
        for n, d in jsonl(out):
            if isinstance(d, str):
                errors.append(f"line {n}: {d}")
                continue
            if "skipped" in d:
                lg.state.setdefault("unscanned", {})[clean(d["skipped"])] = clean(d.get("reason", ""), 120)
                skipped += 1
                continue
            problems = [msg for ok, msg in (
                (isinstance(d.get("file"), str) and d["file"] in files, "`file` is not in this shard"),
                (isinstance(d.get("line"), int) and not isinstance(d.get("line"), bool) and d["line"] > 0,
                 "`line` must be a positive integer"),
                (isinstance(d.get("symbol"), str) and SYMBOL.fullmatch(d["symbol"]) and WORD.search(d["symbol"]),
                 "`symbol` must be a bare name"),
                (isinstance(d.get("kind"), str) and d["kind"] in SCAN_KINDS,
                 f"`kind` must be one of {', '.join(sorted(SCAN_KINDS))}"),
            ) if not ok]
            if problems:
                errors.append(f"line {n}: " + "; ".join(problems))
                continue
            good += 1
            raw = d.get("markers")
            markers = [clean(m, 80) for m in raw][:5] if isinstance(raw, list) else []
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
    return (path in tracked and not path.startswith(("..", "/", ".git/")) and not in_ledger(path)
            and not matches(path, NEVER_SCAN) and not lg.is_protected(path))


_TERMS: dict = {}


def mentions(path: Path, term: str) -> bool:
    """Whether a file names `term`, its names read once per version of it."""
    lines = read_lines(path)
    if lines is None:
        return False
    key = (str(path), id(lines))
    if key not in _TERMS:
        _TERMS[key] = {t for line in lines for t in tokens(line, hyphenated=True)}
    return term in _TERMS[key]


_COMMENTS = {}


def only_comment(lg: Ledger, path: str, line: int) -> bool:
    """Whether line `line` of `path` holds nothing but a comment: no remover need change it, and the guard refuses
    any rewrite of it, so a site there would only get its unit rejected. Lexed once per version of the file."""
    full = lg.root / path
    lines = read_lines(full)
    if lines is None or not 0 < line <= len(lines) or not lines[line - 1].strip():
        return False
    try:
        st = full.stat()
    except OSError:
        return False
    key = (str(full), st.st_mtime_ns, st.st_size)
    if key not in _COMMENTS:
        _COMMENTS[key] = lex(lines, path)[1]  # comments blanked, strings kept: a string entry is a site
    return not _COMMENTS[key][line - 1].strip()


def valid_edits(lg: Ledger, raw, tracked: set, term: str) -> list:
    """A vote's also_edit sites that a remover may touch: editable files that mention the candidate, at a line
    that is not only a comment. Each line is recorded with the commit it refers to, so that later waves can
    follow it."""
    edits = []
    for e in raw if isinstance(raw, list) else []:
        if not (isinstance(e, dict) and isinstance(e.get("file"), str)):
            continue
        try:
            path = rel(lg.root, e["file"])
        except (RuntimeError, OSError, ValueError):
            continue
        if editable(lg, path, tracked) and term and mentions(lg.root / path, term):
            line = e.get("line")
            ok_line = isinstance(line, int) and not isinstance(line, bool) and line > 0
            if ok_line and only_comment(lg, path, line):
                continue  # a comment that names it: no site to edit
            edits.append({"file": path, "line": line if ok_line else None, "sha": lg.head() if ok_line else None,
                          "action": clean(e.get("action", ""), 200)})
    return edits


def ingest_verify(lg: Ledger) -> None:
    units = lg.units("verify", "dispatched")
    if not units:
        die("no dispatched verify unit; run `ledger.py dispatch verify` first")
    votes, lost_total, no_output = 0, 0, []
    tracked = lg.tracked()
    for u in units:
        out = lg.out_path(u["id"], "verify")
        expected, seen, errors = set(u["candidates"]), set(), []
        for n, d in (jsonl(out) if out.is_file() else []):
            if isinstance(d, str):
                errors.append(f"line {n}: {d}")
                continue
            cid, conf = d.get("id"), d.get("confidence")
            if not isinstance(cid, str) or cid not in expected or cid in seen:
                errors.append(f"line {n}: id {clean(cid, 40)!r} is not an unanswered candidate of this unit")
                continue
            if not isinstance(d.get("verdict"), str) or d["verdict"] not in VERDICTS or isinstance(conf, bool) \
                    or not isinstance(conf, int) or not 0 <= conf <= 100 or not str(d.get("evidence", "")).strip():
                errors.append(f"line {n}: needs verdict dead|alive|unsure, an integer confidence 0-100, evidence")
                continue
            seen.add(cid)
            c = lg.cands[cid]
            if c["status"] != "queued":
                continue  # marked by the orchestrator while the unit ran: its decision stands
            evidence = clean(d["evidence"], 600)
            c["votes"][u["lens"]] = {"verdict": d["verdict"], "confidence": conf, "evidence": evidence,
                                     "unit": u["id"]}
            c["retries"] = 0
            for e in valid_edits(lg, d.get("also_edit"), tracked, term_of(c)):
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
        if not out.is_file():
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


# ----------------------------------------------------------------------------------- the removal guard
#
# `stray_deletions` reads what a remover wrote against HEAD before anything else trusts it. A removal may
# delete its declarations whole, with their comments and decorators; the imports, exports, registrations and
# list entries that served them, each judged on its own; and, in a line that also holds live code, the items that
# name them (outside imports and exports, only at a line a verifier listed). A declaration that shares its line
# with live ones loses only its own item. Anything else fails the unit: a change git does not show, any other
# added or rewritten line, a live line deleted, a declaration left half in place, a line added or deleted where
# the layout is code (inside a string, next to a backslash that joins two lines). It reads source text, not syntax
# trees: where it cannot tell, it refuses.

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
# Top-level import and export forms, and the openers of multi-line import blocks (`declares_nothing` reads them).
DEPENDENT = re.compile(r"^(import\b|from\s+\S+\s+import\b|use\s|using\s|require(_relative)?\b|#include\b|"
                       r"export\s*[{*]|export\s+default\s+[\w$]+\s*;?\s*$|@import\b|"
                       r"(const|let|var)\s+[\w${}, ]+=\s*require\()")
IMPORT_OPEN = re.compile(r"^(import\s*\(|from\s+\S+\s+import\s*\(|import\s*(type\s*)?\{|export\s*\{|use\s+[\w:]+::\{|"
                         r"(const|let|var)\s*\{)")
# Imports that run code when loaded instead of binding a name, and Python's `import a.b`, which loads a submodule
# (often to register something): a file holding one still does something (`declares_nothing`).
SIDE_EFFECT = re.compile(r"""^(import\s*['"]|import\s+_\s|_\s+"|require\s*\(|require(_relative)?\s|export\s*\*\s*from\b|"""
                         r"""@import\b)""")
PY_SUBMODULE = re.compile(r"^import\s+\w+(\.\w+)+(\s+as\s+\w+)?\s*$")


def declared(line: str):
    for pattern in DECLARES:
        m = pattern.match(line)
        if m and m.group(2) not in NOT_NAMES:
            return len(m.group(1).expandtabs(4)), m.group(2)
    return None


def indent_of(text: str) -> int:
    return len(text.expandtabs(4)) - len(text.expandtabs(4).lstrip())


def net(code: str) -> int:
    """The brackets a line (comments and literals blanked) opens, minus those it closes."""
    return sum(code.count(ch) for ch in "{([") - sum(code.count(ch) for ch in "})]")


# How each language writes comments and literals, so that a bracket inside one never counts.
JS_FAMILY = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro"}
C_FAMILY = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".m", ".mm"}
HASH_COMMENTS = {".py", ".pyi", ".rb", ".ex", ".exs", ".jl", ".cr", ".nim", ".r", ".pl", ".pm"}
DASH_COMMENTS = {".lua", ".hs", ".sql", ".elm"}
LINE_COMMENTS = {".php": ("//", "#"), ".clj": (";",), ".cljs": (";",), ".erl": ("%",), ".vb": ("'",)}
BLOCK_COMMENTS = {".hs": ("{-", "-}"), ".elm": ("{-", "-}"), ".ml": ("(*", "*)"), ".fs": ("(*", "*)"),
                  ".jl": ("#=", "=#"), ".vue": ("<!--", "-->"), ".svelte": ("<!--", "-->"), ".astro": ("<!--", "-->")}
NESTED_COMMENTS = {".rs", ".swift", ".kt", ".kts", ".scala", ".dart", ".hs", ".elm", ".ml", ".fs", ".jl"}
# `'` opens a character literal here, never a string: a Rust lifetime (`'a`) or a Haskell prime opens nothing.
CHAR_QUOTES = C_FAMILY | {".java", ".cs", ".rs", ".go", ".kt", ".kts", ".scala", ".swift", ".fs", ".hs", ".elm",
                          ".ml", ".jl"}
TRIPLE_QUOTES = {".py": ('"""', "'''"), ".pyi": ('"""', "'''"), ".ex": ('"""', "'''"), ".exs": ('"""', "'''"),
                 ".dart": ('"""', "'''"), ".groovy": ('"""', "'''"), ".kt": ('"""',), ".kts": ('"""',),
                 ".scala": ('"""',), ".swift": ('"""',), ".java": ('"""',), ".cs": ('"""',), ".jl": ('"""',)}
# Strings that may run over several lines; elsewhere a quote still open ends with its line.
MULTILINE_STRINGS = {".rs", ".php", ".rb", ".ex", ".exs", ".jl", ".clj", ".cljs", ".erl", ".ml", ".sql", ".cr"}
# Where `"..."` strings hold code, and how it opens: `"${a}"`, `"\(a)"`, `"#{a}"`.
INTERPOLATION = {".kt": "${", ".kts": "${", ".groovy": "${", ".dart": "${", ".swift": "\\(", ".rb": "#{",
                 ".ex": "#{", ".exs": "#{", ".cr": "#{"}
CHAR_LITERAL = re.compile(r"'(?:\\u\{[0-9a-fA-F]+\}|\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\[0-7]{1,3}|\\.|[^\\'])'")
RUST_RAW = re.compile(r'[bc]?r(#*)"')
RUST_PREFIXED = re.compile(r'[bc]"')
CPP_RAW = re.compile(r'(?:u8|[uUL])?R"([^()\\\s"]{0,16})\(')
CS_VERBATIM = re.compile(r'(?:\$@|@\$|@)"')
SWIFT_RAW = re.compile(r'(#+)("""|")')
RUBY_HEREDOC = re.compile(r"<<([~-]?)(['\"`]?)([A-Za-z_]\w*)\2")
PHP_HEREDOC = re.compile(r"<<<[ \t]*(['\"]?)([A-Za-z_]\w*)\1")
LUA_LONG = re.compile(r"\[(=*)\[")
# Where a backslash at the end of a line continues a one-line string on the next one; in C and C++ it also
# continues a `//` comment, since the compiler splices the lines before it reads comments.
SPLICES = JS_FAMILY | C_FAMILY | {".py", ".pyi", ".lua"}
# Dialects whose files may hold JSX or HTML text, where a lone backtick is no template literal: a template
# literal that runs over lines there gets no more trust than a quote (see `lex`).
MARKUP = {".js", ".jsx", ".tsx", ".vue", ".svelte", ".astro"}
# Ruby's `%q(...)`, `%w[...]`, `%r{...}` and Elixir's sigils (`~s(...)`, `~r/.../`): a bracket delimiter nests
# and closes with its pair, any other closes with itself.
PAIRS = {"(": ")", "[": "]", "{": "}", "<": ">"}
RUBY_PERCENT = re.compile(r"%([qQwWiIrsx]?)([^\w\s])")
ELIXIR_SIGIL = re.compile(r"~(?:[a-z]|[A-Z][A-Z0-9]*)(\"\"\"|'''|[/|\"'(\[{<])")
# Ruby's punctuation globals (`$'`, the text after the last match; `$/`, the line separator) open nothing.
RUBY_GLOBAL = re.compile(r"\$[-'\"`/\\;,.<>_~=*$?:!@&+]")
# Where PHP code starts again after inline HTML.
PHP_OPEN = re.compile(r"<\?(?:php\b|=|(?=\s|$))", re.I)
# A `/` at the start of a line or right after one of these opens a regular expression in JavaScript and Ruby;
# after an operand (`a / b`, `f() / 2`, `x[0] / y`, `"a" / 2`) it divides. `<` is left out: `</p>` closes a tag.
REGEX_AFTER = set("(,=:[!&|?{;+-*%~^>")
REGEX_KEYWORDS = {"return", "typeof", "case", "in", "of", "new", "delete", "void", "throw", "yield", "await",
                  "instanceof", "else", "do", "if", "unless", "when", "and", "or", "not", "elsif", "while", "until"}
CODE, LITERAL, COMMENT = 0, 1, 2


def lex(lines: list, path: str = "") -> tuple:
    """(code, text, carried): the lines with comments and literals blanked out column for column, with comments
    blanked only, and how each line starts: 0 in code; 1 inside a string, comment, heredoc or inline HTML opened
    above it by an opener nothing else looks like (a triple quote, a raw string, a heredoc, a comment that starts
    its line); 2 inside one that may be a misread (a quote that runs over lines, which an apostrophe can open, a
    template literal where JSX text may hold a backtick, a comment opened after code). A bracket in `split("(")`,
    in a regular expression or in a comment never decides where a declaration ends, and a name inside a string
    still counts as a mention. A string, comment or heredoc still open at the end of a line carries over; a
    one-line string left open ends with its line, unless a backslash continues it. A block comment opened after
    code on its line reads as a literal on its later lines: what it may hide never passes for a comment."""
    suffix = Path(path).suffix.lower()
    js, ruby, php, elixir = suffix in JS_FAMILY, suffix == ".rb", suffix == ".php", suffix in (".ex", ".exs")
    marks = ("#",) if suffix in HASH_COMMENTS else ("--",) if suffix in DASH_COMMENTS else \
        LINE_COMMENTS.get(suffix, ("//",))
    blocks = ([("/*", "*/")] if "//" in marks or suffix == ".sql" else []) + \
        ([BLOCK_COMMENTS[suffix]] if suffix in BLOCK_COMMENTS else [])
    nests = suffix in NESTED_COMMENTS
    triples = TRIPLE_QUOTES.get(suffix, ())
    triple_escapes = suffix not in (".kt", ".kts", ".scala", ".cs")
    interp = INTERPOLATION.get(suffix)
    multiline = suffix in MULTILINE_STRINGS
    splices = suffix in SPLICES
    # Frames: ["code", closer of the interpolation it is in, nesting], ["str", closer, escapes, multi-line,
    # interpolation opener, doubled-quote escapes, trusted, delimiter that nests, nesting], ["comment", opener when
    # comments nest, closer, trusted, line it opened on].
    stack = [["code", None, 0]]
    pending, heredoc, rdoc, html, spliced, before = [], None, False, php, False, ""
    kinds = bytearray()
    code_out, text_out, carried = [], [], []

    def paint(a, b, kind):
        kinds[a:b] = bytes([kind]) * (b - a)

    def string(i, width, closer, escapes, multi, inner=None, doubled=False, trusted=True, nest=None):
        paint(i, i + width, LITERAL)
        stack.append(["str", closer, escapes, multi, inner, doubled, trusted, nest, 0])
        return i + width

    for row, line in enumerate(lines):
        n = len(line)
        kinds = bytearray(n)
        if heredoc is not None or rdoc or html or spliced:
            carried.append(1)
        elif len(stack) == 1:
            carried.append(0)
        else:
            carried.append(2 if any(f[0] == "str" and not f[6] or f[0] == "comment" and not f[3] for f in stack) else 1)
        i, lead, misses = 0, n - len(line.lstrip()), 0
        if spliced:  # the rest of a `//` comment that a backslash continued
            paint(0, n, COMMENT)
            spliced, i = line.endswith("\\"), n
        elif heredoc is not None:
            i = heredoc_end(line, heredoc)
            paint(0, n if i < 0 else i, LITERAL)
            if i < 0:
                i = n
            else:  # PHP code may go on after the closing name (`SQL);`)
                heredoc = pending.pop(0) if pending else None
        elif rdoc:
            paint(0, n, COMMENT)
            rdoc, i = not line.startswith("=end"), n
        elif ruby and len(stack) == 1 and re.match(r"=begin(\s|$)", line):
            paint(0, n, COMMENT)
            rdoc, i = True, n
        elif html:  # PHP's inline HTML, up to `<?php`
            m = PHP_OPEN.search(line)
            i = m.end() if m else n
            paint(0, i, LITERAL)
            html = m is None
        while i < n:
            frame = stack[-1]
            if frame[0] == "comment":
                opener, closer = frame[1], frame[2]
                kind = COMMENT if frame[3] or frame[4] == row else LITERAL
                j = line.find(closer, i)
                k = line.find(opener, i) if opener else -1
                if k >= 0 and (j < 0 or k < j):
                    paint(i, k + len(opener), kind)
                    stack.append(["comment", opener, closer, frame[3], frame[4]])
                    i = k + len(opener)
                    continue
                end = n if j < 0 else j + len(closer)
                paint(i, end, kind)
                if j >= 0:
                    stack.pop()
                i = end
                continue
            if frame[0] == "str":
                closer, escapes, inner, doubled, nest = frame[1], frame[2], frame[4], frame[5], frame[7]
                j = i
                while j < n:
                    if escapes and line[j] == "\\" and not (inner and line.startswith(inner, j)):
                        j += 2
                        continue
                    if nest and line[j] == nest:
                        frame[8] += 1
                    elif line.startswith(closer, j):
                        if nest and frame[8]:
                            frame[8] -= 1
                        elif doubled and line.startswith(closer, j + len(closer)):
                            j += 2 * len(closer)
                            continue
                        else:
                            break
                    elif inner and line.startswith(inner, j):
                        if inner == "{" and line.startswith("{{", j):
                            j += 2
                            continue
                        break
                    j += 1
                if j >= n:
                    paint(i, n, LITERAL)
                    i = n
                elif line.startswith(closer, j):
                    paint(i, j + len(closer), LITERAL)
                    stack.pop()
                    i = j + len(closer)
                else:  # an interpolation: code until its closer
                    paint(i, j + len(inner), LITERAL)
                    stack.append(["code", ")" if inner == "\\(" else "}", 0])
                    i = j + len(inner)
                continue
            ch = line[i]
            if frame[1] is not None:  # code inside an interpolation, which its closer ends
                if ch == frame[1] and frame[2] == 0:
                    paint(i, i + 1, LITERAL)
                    stack.pop()
                    i += 1
                    continue
                if ch == ("{" if frame[1] == "}" else "("):
                    frame[2] += 1
                elif ch == frame[1]:
                    frame[2] -= 1
            if php and len(stack) == 1 and line.startswith("?>", i):  # inline HTML, up to `<?php`
                m = PHP_OPEN.search(line, i + 2)
                end = m.end() if m else n
                paint(i, end, LITERAL)
                html, i = m is None, end
                continue
            if suffix == ".lua" and line.startswith("--[", i):
                m = LUA_LONG.match(line, i + 2)
                if m:
                    paint(i, m.end(), COMMENT)
                    stack.append(["comment", None, "]" + m.group(1) + "]", i <= lead, row])
                    i = m.end()
                    continue
            block = next((b for b in blocks if line.startswith(b[0], i)), None)
            if block and not line.startswith("(*)", i):
                paint(i, i + len(block[0]), COMMENT)
                stack.append(["comment", block[0] if nests else None, block[1], i <= lead, row])
                i += len(block[0])
                continue
            if any(line.startswith(mark, i) for mark in marks) and not (php and line.startswith("#[", i)):
                end = line.find("?>", i) if php else -1  # `?>` ends a PHP line comment
                paint(i, n if end < 0 else end, COMMENT)
                if end >= 0:
                    i = end
                    continue
                spliced = suffix in C_FAMILY and line.endswith("\\")
                break
            prev = line[i - 1] if i else ""
            after_word = prev.isalnum() or prev in ("_", "$")
            m = None
            if ruby and ch == "<":
                m = RUBY_HEREDOC.match(line, i)
                if m and not (m.group(1) or m.group(2) or m.group(3).isupper()):
                    m = None  # `<<x` with a lowercase name is a shift
                if m:
                    pending.append(("ruby", m.group(3)))
            elif php and ch == "<":
                m = PHP_HEREDOC.match(line, i)
                if m:
                    pending.append(("php", m.group(2)))
            if m:
                paint(i, m.end(), LITERAL)
                i = m.end()
                continue
            if ruby and ch == "$" and RUBY_GLOBAL.match(line, i):
                i += 2
                continue
            if (ruby or elixir) and ch == "?" and not after_word and prev not in (")", "]", "}") and i + 1 < n \
                    and not line[i + 1].isspace():  # a character literal: `?'`, `?\n`
                width = 3 if line[i + 1] == "\\" else 2
                if i + width >= n or not (line[i + width].isalnum() or line[i + width] == "_"):
                    paint(i, min(n, i + width), LITERAL)
                    i += width
                    continue
            if ruby and ch == "%" and not after_word and prev not in (")", "]", "}"):
                m = RUBY_PERCENT.match(line, i)
                if m and (m.group(1) or regex_allowed(line, i, kinds)):
                    delim = m.group(2)
                    i = string(i, m.end() - i, PAIRS.get(delim, delim), True, True,
                               None if m.group(1) in ("q", "w", "i", "s") else "#{", False, True,
                               delim if delim in PAIRS else None)
                    continue
            if elixir and ch == "~":
                m = ELIXIR_SIGIL.match(line, i)
                if m:
                    delim = m.group(1)
                    i = string(i, m.end() - i, delim if len(delim) == 3 else PAIRS.get(delim, delim), True, True,
                               "#{" if line[i + 1].islower() else None, False, True, delim if delim in PAIRS else None)
                    continue
            if not after_word and suffix == ".rs" and ch in "bcr":
                m = RUST_RAW.match(line, i)
                if m:
                    i = string(i, m.end() - i, '"' + m.group(1), False, True)
                    continue
                if RUST_PREFIXED.match(line, i):
                    i = string(i, 2, '"', True, True)
                    continue
            if not after_word and suffix in C_FAMILY and ch in "uULR":
                m = CPP_RAW.match(line, i)
                if m:
                    i = string(i, m.end() - i, ")" + m.group(1) + '"', False, True)
                    continue
            if not after_word and suffix == ".dart" and ch == "r" and line[i + 1:i + 2] in ("'", '"'):
                quote = line[i + 1:i + 4] if line[i + 1:i + 4] in ("'''", '"""') else line[i + 1]
                i = string(i, 1 + len(quote), quote, False, len(quote) == 3)
                continue
            if suffix == ".cs" and ch in "@$":
                m = CS_VERBATIM.match(line, i)
                if m:
                    i = string(i, m.end() - i, '"', False, True, "{" if "$" in m.group(0) else None, True)
                    continue
                if line.startswith('$"', i) and not line.startswith('$"""', i):
                    i = string(i, 2, '"', True, False, "{")
                    continue
            if suffix == ".swift" and ch == "#":
                m = SWIFT_RAW.match(line, i)
                if m:
                    i = string(i, m.end() - i, m.group(2) + m.group(1), False, m.group(2) == '"""')
                    continue
            triple = next((q for q in triples if line.startswith(q, i)), None)
            if triple:
                i = string(i, 3, triple, triple_escapes, True)
                continue
            if ch == "`":
                if js:
                    i = string(i, 1, "`", True, True, "${", False,
                               suffix not in MARKUP or template_at(line, i, kinds, before))
                    continue
                if suffix == ".go":
                    i = string(i, 1, "`", False, True)
                    continue
                if suffix in (".kt", ".kts", ".scala", ".fs", ".swift", ".sql", ".hs"):
                    i = string(i, 1, "`", False, False)
                    continue
            if ch == "/" and (js or ruby) and misses < 32 and (regex_allowed(line, i, kinds) or ruby and prev == " " and
                                                              i > 1 and (line[i - 2].isalnum() or line[i - 2] == "_")
                                                              and line[i + 1:i + 2] not in ("", " ", "=")):
                end = regex_end(line, i)  # Ruby's `gsub /'/, ...` passes a regular expression too
                if end > 0:
                    paint(i, end, LITERAL)
                    i = end
                    continue
                misses += 1  # each miss reads the rest of the line: a line of them must not cost its square
            if suffix == ".lua" and ch == "[":
                m = LUA_LONG.match(line, i)
                if m:
                    i = string(i, m.end() - i, "]" + m.group(1) + "]", False, True)
                    continue
            if ch == '"':
                doubled = suffix in (".vb", ".sql")
                i = string(i, 1, '"', not doubled, multiline, interp, doubled, not multiline or suffix == ".rs")
                continue
            if ch == "'":
                if suffix in CHAR_QUOTES:
                    m = None if after_word and suffix in (".hs", ".elm", ".ml", ".fs", ".jl") else \
                        CHAR_LITERAL.match(line, i)
                    if m:
                        paint(i, m.end(), LITERAL)
                        i = m.end()
                        continue
                elif not (js and after_word) and suffix not in (".clj", ".cljs"):  # `Don't` in JSX text
                    i = string(i, 1, "'", suffix != ".sql", multiline, None, suffix == ".sql", not multiline)
                    continue
            i += 1
        for k, frame in enumerate(stack):  # a one-line string left open ends with its line, with what it holds
            if frame[0] == "str" and not frame[3]:
                if splices and k == len(stack) - 1 and ((n - len(line.rstrip("\\"))) % 2 or
                                                          suffix == ".lua" and re.search(r"\\z\s*$", line)):
                    break  # a backslash before the line break continues it
                del stack[k:]
                break
        if heredoc is None and pending:
            heredoc = pending.pop(0)
        code_out.append(blanked(line, kinds, NOT_CODE))
        text_out.append(blanked(line, kinds, COMMENTED))
        if code_out[-1].strip():
            before = code_out[-1].rstrip()
    return code_out, text_out, carried


NOT_CODE, COMMENTED = re.compile(rb"[\x01\x02]+"), re.compile(rb"\x02+")


def blanked(line: str, kinds: bytearray, runs) -> str:
    """The line with the runs of `kinds` that `runs` matches turned into spaces, column for column."""
    out, last = [], 0
    for m in runs.finditer(kinds):
        out += [line[last:m.start()], " " * (m.end() - m.start())]
        last = m.end()
    return "".join(out) + line[last:] if out else line


def heredoc_end(line: str, heredoc: tuple) -> int:
    """Where the line that closes a heredoc stops being part of it, or -1: Ruby's name alone on its line, PHP's
    (7.3 and later) also indented or followed by code (`SQL);`), which this column starts."""
    kind, name = heredoc
    if kind == "ruby":
        return len(line) if line.strip() == name else -1
    m = re.match(r"\s*" + re.escape(name) + r"(?!\w)", line)
    return m.end() if m else -1


TEMPLATE_KEYWORDS = {"return", "yield", "await", "throw", "case", "typeof", "in", "of", "else", "do", "void", "new",
                     "default"}


def template_at(line: str, i: int, kinds: bytearray, before: str) -> bool:
    """Whether the backtick at column i stands where code would open a template literal, in a file that may hold
    JSX or HTML text: right after a tag (`gql`, `styled.div`, `styled(Button)`), or after an operator, an opening
    bracket or a keyword (`= `, `(`, `return `), on its line or, when it starts its line, at the end of the code
    line `before` it. After `>`, or a word and a blank, it may be text (`<kbd>`</kbd>`, `Press ` to open`)."""
    if i and (line[i - 1].isalnum() or line[i - 1] in "_$)]"):
        return True
    j = i - 1
    while j >= 0 and (line[j].isspace() or kinds[j] == COMMENT):
        j -= 1
    if j < 0:
        line, j = before, len(before) - 1
    elif kinds[j] != CODE:
        return False
    if j < 0:
        return False
    if line[j] in "=(,:?[{+-*/%!&|^~;":
        return True
    k = j
    while k >= 0 and (line[k].isalnum() or line[k] in "_$"):
        k -= 1
    return line[k + 1:j + 1] in TEMPLATE_KEYWORDS


def regex_allowed(line: str, i: int, kinds: bytearray) -> bool:
    """Whether the `/` at column i stands where an operand starts, so that it opens a regular expression."""
    j = i - 1
    while j >= 0 and (line[j].isspace() or kinds[j] == COMMENT):
        j -= 1
    if j < 0:
        return True
    if kinds[j] != CODE:
        return False  # right after a string or another regular expression: a division
    if line[j] in REGEX_AFTER:
        return True
    if line[j].isalnum() or line[j] in "_$":
        k = j
        while k >= 0 and (line[k].isalnum() or line[k] in "_$"):
            k -= 1
        return line[k + 1:j + 1] in REGEX_KEYWORDS
    return False


def regex_end(line: str, i: int) -> int:
    """End of the regular expression whose `/` is at column i, flags included; -1 when it does not close on its
    line, so that the `/` was a division after all."""
    j, in_class, n = i + 1, False, len(line)
    if line[j:j + 1] in ("/", "*", ""):
        return -1
    while j < n:
        c = line[j]
        if c == "\\":
            j += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "/":
            j += 1
            while j < n and (line[j].isalnum() or line[j] == "_"):
                j += 1
            return j
        j += 1
    return -1


class Source:
    """A committed file as the guard reads it: its lines (`head`), the same lines with comments and literals
    blanked out (`code`) or with comments only (`text`), how each line starts (`carried`, see `lex`), the bracket
    depth before each line (`depth[k - 1]` for line k), and the innermost bracket open where each line starts."""

    def __init__(self, head: list, path: str):
        self.head, self.path, self.suffix = head, path, Path(path).suffix.lower()
        self.code, self.text, self.carried = lex(head, path)
        self.depth = [0]
        for line in self.code:
            self.depth.append(self.depth[-1] + net(line))
        self.contexts = bracket_contexts(self.code, self.suffix)
        self._statements, self._shapes = None, {}

    def shape(self, k: int) -> str:
        """Line k with comments blanked and every literal character turned into `0`: the code's structure,
        with strings as opaque operands (`"a,b"` holds no separator). Read once per line: the rules that try each
        place a cut may sit ask for it again."""
        if k not in self._shapes:
            self._shapes[k] = "".join(c if c != " " else ("0" if t != " " else " ")
                                      for c, t in zip(self.code[k - 1], self.text[k - 1]))
        return self._shapes[k]

    def statement(self, a: int, name: str):
        """For a Python file that this interpreter parses, the first and last line of the statement that starts at
        line a and binds `name` (a def or class with its decorators, an assignment), as the syntax tree has them;
        (a, a - 1), which nothing of the file can fill, when another statement shares one of its lines
        (`STALE = 1; audit()`, `if x: STALE = 1`); None for any other file or line."""
        if self._statements is None:
            self._statements = python_statements(self.head) if self.suffix in (".py", ".pyi") else {}
        for node, first, ancestors, others in self._statements.get(a, ()):
            if name and name not in bound_names(node):
                continue
            last = node.end_lineno
            if any(x.lineno == first for x in ancestors) or any(lo <= last and first <= hi for lo, hi in others):
                return a, a - 1
            return first, last
        return None


def python_statements(head: list) -> dict:
    """{line: [(statement, first line, its enclosing statements, the line ranges of the statements around it)]}
    for every statement of a Python file by the line it starts on, outermost first, a def or class from its first
    decorator (and its `def` line); empty when the file does not parse here, or holds a lone CR, which Python reads
    as a line break and `head` does not."""
    text = "\n".join(head)
    if "\r" in text:
        return {}
    try:
        with warnings.catch_warnings():  # `PYTHONWARNINGS=error` must not make a valid file unreadable
            warnings.simplefilter("ignore")
            tree = ast.parse(text.encode("utf-8", "surrogateescape"))
    except (SyntaxError, ValueError, OSError, RecursionError, MemoryError, Warning):
        return {}
    out = defaultdict(list)

    def first_line(node):
        return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])

    def visit(node, ancestors):
        for field in ("body", "orelse", "finalbody", "handlers", "cases"):
            items = getattr(node, field, None)
            if not isinstance(items, list):
                continue
            stmts = [x for x in items if isinstance(x, ast.stmt)]
            spans = [(first_line(x), x.end_lineno) for x in stmts]
            for k, x in enumerate(stmts):
                for line in {spans[k][0], x.lineno}:  # a decorated def is found from its decorators and its `def`
                    out[line].append((x, spans[k][0], ancestors, spans[:k] + spans[k + 1:]))
            for x in items:  # except handlers and match cases hold statements without being one
                visit(x, ancestors + ([x] if isinstance(x, (ast.stmt, ast.excepthandler)) else []))
    try:
        visit(tree, [])
    except RecursionError:
        return {}
    return out


def bound_names(node) -> set:
    """The names a Python statement binds at its own level."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(getattr(node, "name", None), ast.Name):  # Python 3.12's `type Alias = ...`
        return {node.name.id}
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] \
        if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
    out = set()
    for t in targets:
        for x in ast.walk(t):
            if isinstance(x, ast.Name):
                out.add(x.id)
            elif isinstance(x, ast.Attribute):
                out.add(x.attr)
    return out


# Where `{` after a type name opens a literal (`= Config{...}`, `map[string]H{...}`, `new List<T> {...}`); in the
# other languages a name before `{` passes a block (Ruby, Kotlin and Swift trailing closures).
TYPED_LITERALS = {".go", ".rs", ".cs", ".java"} | C_FAMILY
BLOCK_START = re.compile(r"\s*(?:\}\s*)?(?:if|else|while|for|match|switch|loop|unless|until|when|catch|try|do|fn|"
                         r"func|function|def|class|struct|impl|trait|enum|interface|namespace|module)\b")
BLOCK_END = {"unsafe", "async", "move", "static", "const", "finally", "get", "set", "init", "where", "delegate", "loop",
             "else", "try", "do"}
NEW_TYPE = re.compile(r"\bnew\s+[\w.<>\[\], ]+$")
TYPE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.[]*<>"
BRACKETS = re.compile(r"[()\[\]{}]")


def bracket_contexts(code: list, suffix: str) -> list:
    """For each line, the innermost bracket open where it starts, as (char, whether it holds a list), or None. A
    `(` or `[` always holds one. A `{` does after `=`, `(`, `,`, `:`, `[`, `return` or `default` (an object, a
    dict, a hash), and after a type name where literals are typed; anywhere else it opens a block (`) {`,
    `=> {`, `class A {`, `if x = y {`). Each `{` reads at most a few hundred characters before it, so a long line
    costs no more than a short one per bracket."""
    typed, python = suffix in TYPED_LITERALS, suffix in (".py", ".pyi")
    out, stack, before, starts = [], [], "", None
    for line in code:
        out.append(stack[-1] if stack else None)
        lead, opens = len(line) - len(line.lstrip()), None
        for m in BRACKETS.finditer(line):
            ch, j = m.group(0), m.start()
            if ch in "([":
                stack.append((ch, True))
            elif ch == "{":
                if python:
                    stack.append(("{", True))
                    continue
                if j > lead:
                    if opens is None:
                        opens = BLOCK_START.match(line)
                    head, cut, start = line, j, opens and opens.end() <= j
                else:
                    head, cut, start = before, len(before), starts
                window = head[max(0, cut - 300):cut].rstrip()  # what stands before it, its last word apart
                k = len(window)
                while k and (window[k - 1].isalnum() or window[k - 1] == "_"):
                    k -= 1
                whole = k or cut <= 300 or not (head[cut - 301].isalnum() or head[cut - 301] == "_")
                block = start or whole and window[k:] in BLOCK_END
                stack.append(("{", not block and list_before(window, typed)))
            elif stack:
                stack.pop()
        if line.strip():
            before, starts = line.rstrip(), BLOCK_START.match(line)
    return out


def list_before(text: str, typed: bool) -> bool:
    """Whether a `{` after `text` opens a literal: `text` ends with `=`, `(`, `,`, `:`, `[`, `?`, `return`,
    `default` or `yield`, and, where literals are typed, also with one of the first six and a type name
    (`= Config`, `return &Point`, `= new List<T>`)."""
    if ends_list(text, not typed):
        return True
    if not typed:
        return False
    rest = text.rstrip(TYPE_CHARS)
    if len(rest) < len(text):
        rest = rest[:-1] if rest.endswith("&") else rest
        if ends_list(rest.rstrip(), False):
            return True
    m = NEW_TYPE.search(text)
    return bool(m) and ends_list(text[:m.start()].rstrip(), False)


def ends_list(text: str, words: bool) -> bool:
    """Whether `text` ends with `=`, `(`, `,`, `:`, `[`, `?` or `return` (and, with `words`, `default` or
    `yield`), as a whole word."""
    if text[-1:] and text[-1] in "=(,:[?":
        return True
    for w in ("return", "default", "yield") if words else ("return",):
        if text.endswith(w) and not (text[-len(w) - 1:-len(w)].isalnum() or text[-len(w) - 1:-len(w)] == "_"):
            return True
    return False


def bracket_end(code: list, a: int):
    """Line where the brackets opened at line a close again, or None."""
    depth = 0
    for i in range(a, min(len(code), a + 5000) + 1):
        depth += net(code[i - 1])
        if depth <= 0:
            return i
    return None


CLOSING_LINE = re.compile(r"(?:end|fi|esac|done)\b[\s;,).\]}]*$|[})\]][\s;,)\]}]*$")
# Languages whose blocks are their indentation: a line inside an open bracket belongs to the declaration above
# it whatever its own indentation (`return [` followed by items at column 0).
INDENTED = {".py", ".pyi", ".hs", ".elm", ".fs", ".nim"}
WHERE_LANGS = {".rs", ".swift", ".kt", ".kts", ".cs"}
# A line that starts like this continues the declaration above it at the same indentation.
CONTINUES = re.compile(r"[})\]]|\{|(?:else|elif|elsif|except|finally|catch|rescue|ensure|end|fi|esac|done)\b"
                       r"(?!\s*=[^=>])")
DECLARATION_START = re.compile(
    r"\s*(?:@\w|#\[|(?:export|public|private|protected|internal|static|async|abstract|final|override|open|sealed|"
    r"pub(?:\([^)]*\))?|unsafe|extern)\s|(?:def|class|function|fn|func|fun|impl|interface|type|struct|enum|trait|"
    r"module|namespace|const|let|var|val|object|protocol|extension|import|from|use|using|package|mod)\b)")


def block_end(src: Source, a: int, indent: int) -> int:
    """Last line of the block indented under line a, with a closing `end` or bracket at its own indentation, and
    the `rescue`, `ensure` or `else` sections that go on at that indentation.
    Blankness is read on `code`, so neither a comment nor a docstring ends the block, and indentation on the file
    itself, so a live line that starts with a comment or a string never looks indented. A line inside a bracket
    opened under line a belongs to the block whatever its indentation."""
    end, depth = a, max(0, net(src.code[a - 1]))
    for i in range(a + 1, len(src.head) + 1):
        text = src.code[i - 1].strip()
        if not text:
            continue
        inside, depth = depth > 0 or src.carried[i - 1] == 1, max(0, depth + net(src.code[i - 1]))
        ind = indent_of(src.head[i - 1])
        if ind > indent or inside:  # `""".trimIndent()` closes a raw string opened in the block
            end = i
            continue
        if ind == indent and CLOSING_LINE.match(text):
            end = i
        elif ind == indent and CONTINUES.match(text):  # Ruby's `rescue` or `ensure` under the `def`
            end = i
            continue
        break
    return end


def assigns(code: str) -> bool:
    """Whether a line assigns at its top level (`x = f()`, not `f(a = 1)`, `a == b` or `=>`)."""
    depth = 0
    for j, ch in enumerate(code):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "=" and depth == 0 and code[j - 1:j] not in ("=", "<", ">", "!") and \
                code[j + 1:j + 2] not in ("=", ">"):
            return True
    return False


def brace_after(src: Source, i: int, indent: int):
    """Where the body closes when it opens on a line after line i: a `{` alone at the declaration's indentation
    (Allman style), or the `{` after a `where` clause; None when the declaration ends at line i."""
    sig = src.code[i - 1].rstrip()
    if not sig.strip() or sig.endswith((";", ",", "=", "(", "[", "{", "=>")):
        return None
    j = next((k for k in range(i + 1, min(len(src.head), i + 3) + 1) if src.code[k - 1].strip()), None)
    if not j:
        return None
    first = src.code[j - 1].strip()
    if first.startswith("{") and indent_of(src.head[j - 1]) == indent and not assigns(sig):
        return bracket_end(src.code, j)
    if src.suffix in WHERE_LANGS and re.match(r"where(\s|$)", first):
        for k in range(j, min(len(src.head), j + 12) + 1):
            if "{" in src.code[k - 1]:
                return bracket_end(src.code, k)
            if k > j and src.code[k - 1].strip() and indent_of(src.head[k - 1]) <= indent:
                break
    return None


def body_end(src: Source, a: int, indent: int) -> int:
    """Last line of the signature and body of the declaration at line a; line a itself when its brackets never
    close, so that a misread extends nothing."""
    line = src.code[a - 1].rstrip()
    opens = net(line)
    if opens > 0:
        i = bracket_end(src.code, a)
        if i is None:
            return a
        tail = src.code[i - 1].rstrip()
        if "{" in "".join(src.code[a - 1:i]) and tail.endswith("}"):
            return i  # the body closed with the signature's brackets
        if tail.endswith((":", "=")):  # Python `) -> T:`, Kotlin `) =`
            return block_end(src, i, indent)
        later = brace_after(src, i, indent)
        if later:
            return later
        j = next((k for k in range(i + 1, len(src.head) + 1) if src.code[k - 1].strip()), None)
        if j and indent_of(src.head[j - 1]) > indent:  # Ruby `def f(a,\n b)`, then an indented body
            return block_end(src, i, indent)
        return i
    if opens < 0 or line.endswith(";") or line.endswith("}") and src.suffix not in KEYWORD_BODIES:
        return a  # a body opened and closed on its line, or a statement: a prototype, an overload signature
    j = split_signature(src, a, indent)
    if j:
        return body_end(src, j, indent)
    return brace_after(src, a, indent) or block_end(src, a, indent)


def split_signature(src: Source, a: int, indent: int):
    """The line that opens the parameter list of a C or C++ function whose name ends line a, when that list opens
    on a line of its own (`NvBool`, then `memmgrIsFlaSupported`, then `(`), or None."""
    if src.suffix not in C_FAMILY or not re.fullmatch(r"\s*(?:[A-Za-z_][\w:<>,*&\s]*[\s*&])?[A-Za-z_][\w:~]*\s*",
                                                      src.code[a - 1]):
        return None
    j = next((k for k in range(a + 1, min(len(src.head), a + 3) + 1) if src.code[k - 1].strip()), None)
    return j if j and src.code[j - 1].strip().startswith("(") and indent_of(src.head[j - 1]) == indent else None


# Languages whose bodies are their indentation or end with a keyword: a `{...}` on a `def` line is a hash or a
# dict (`def initialize(request, options = {})`), never the body.
KEYWORD_BODIES = INDENTED | {".rb", ".ex", ".exs", ".cr", ".lua", ".jl", ".erl", ".r"}
# A line that starts like this at or below a declaration's indentation still belongs to it inside its brackets:
# a preprocessor line (C, C++, C#), a label (`out:`, Go's `outer:`), a C++ access specifier (`public:`).
PREPROCESSOR = re.compile(r"\s*#\s*(?:if|ifdef|ifndef|elif|elifdef|elifndef|else|endif|pragma|region|endregion|line|"
                          r"error|warning|nullable)\b")
LABEL = re.compile(r"\s*(?:(?:public|private|protected)\s+(?:slots|Q_SLOTS)|[A-Za-z_]\w*)\s*:(?!:)\s*(?://.*|/\*.*)?$")
PREPROCESSED, LABELED = C_FAMILY | {".cs"}, C_FAMILY | JS_FAMILY | {".go", ".java", ".cs", ".php"}


# A line of a parameter list: a name followed by `,`, `)`, `:`, `=` or `?`, or a destructuring pattern.
PARAMETER = re.compile(r"(?:\.\.\.)?[A-Za-z_$][\w$]*\s*(?:[,):=?]|$)|[\[{]")


def params_end(src: Source, a: int) -> int:
    """The line where the parameter list that line a opens closes, or a when line a opens none."""
    depth = 0
    if "(" not in src.code[a - 1] or re.search(r"[\[{]", src.code[a - 1].split("(", 1)[0]):
        return a
    for k in range(a, min(len(src.code), a + 50) + 1):
        for ch in src.code[k - 1]:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth <= 0:
                    return k if depth == 0 and k > a else a
    return a


def declares(text: str) -> bool:
    """Whether a line, read as it is written, starts a declaration, an import, an attribute or a decorator."""
    return bool(declared(text) or DECLARATION_START.match(text))


def capped(src: Source, a: int, end: int, indent: int) -> int:
    """`end`, or the line before the first line after line a that cannot belong to the declaration, with the
    comments and decorators right above that line. Lines are read as the file writes them, whatever the lexer made
    of the strings and comments around them: a line at or above the declaration's indentation that declares
    something ends it, and so does any other that holds code there, unless it continues the declaration (a closing
    bracket, `{`, `else`, `end` or `where` at its own indentation, a parameter of its signature; inside its
    brackets, a preprocessor line, a label, an access specifier, a template literal or PHP's `?>`) or the lexer
    reads it as the rest of a heredoc, a raw or triple-quoted string or a comment that started its own line, which
    no misread opens. A misread string or comment can thus only make a declaration shorter."""
    where, base, split = src.suffix in WHERE_LANGS, src.depth[a - 1], split_signature(src, a, indent)
    params = params_end(src, split or a)
    for k in range(a + 1, end + 1):
        raw = src.head[k - 1]
        ind = indent_of(raw)
        if not raw.strip() or ind > indent:
            continue
        code, state = src.code[k - 1].strip(), src.carried[k - 1]
        if state == 1:  # the rest of a heredoc, raw string or comment, then the code after it closes
            if not (declared(raw) or declares(code.lstrip(";,)]} "))):
                continue
        elif not declares(raw):
            lead = code if state == 0 else raw.strip()
            if ind == indent and (CONTINUES.match(lead) or where and re.match(r"where(\s|$)", lead) or k == split):
                continue
            if state == 0 and k <= params and PARAMETER.match(code):
                continue  # a parameter written at the declaration's own indentation
            first = len(raw) - len(raw.lstrip())  # a template literal or PHP's `?>` before inline HTML
            literal = raw[first:first + 1] in ("`", "?") and src.code[k - 1][first:first + 1] == " "
            if state == 0 and (not code and not src.text[k - 1].strip()  # a comment that starts its line
                               or src.suffix in INDENTED and src.depth[k - 1] > base
                               or src.depth[k - 1] > base and (literal or src.suffix in PREPROCESSED and
                                                               PREPROCESSOR.match(raw) or src.suffix in LABELED and
                                                               LABEL.match(raw))):
                continue
        return max(a, leading(src, k) - 1)
    return end


DECORATED = JS_FAMILY | {".py", ".pyi", ".java", ".kt", ".kts", ".scala", ".swift", ".dart", ".groovy"}
DOC_ATTRIBUTE = re.compile(r"@(?:doc|spec|impl|deprecated|typedoc|since)\b")
# Comments that belong to the whole file, never to the declaration below them.
FILE_DIRECTIVE = re.compile(r"\s*(?:#!|#.*\bcoding[:=]|///\s*<reference\b|//\s*\+build\b|//go:build\b|"
                            r"/\*\*?\s*@(?:jsx|flow)\b|//\s*@(?:jsx|flow)\b)")


def attribute_line(src: Source, k: int) -> bool:
    """Whether line k is a decorator or an attribute in the file's language: `@x` where decorators exist (never
    PHP's `@` operator or a Ruby `@ivar`), Rust and PHP `#[`, C# `[`, C++ `[[`, a Sorbet `sig`, Elixir docs."""
    code, s = src.code[k - 1].strip(), src.suffix
    if s in (".ex", ".exs"):
        return DOC_ATTRIBUTE.match(code) is not None
    openers = (("@",) if s in DECORATED else ()) + (("#[",) if s in (".rs", ".php") else ()) + \
        (("[",) if s in (".cs", ".fs", ".vb") else ()) + (("[[",) if s in C_FAMILY else ()) + \
        (("sig {", "sig{", "sig do") if s == ".rb" else ())
    return bool(openers) and code.startswith(openers)


def opening_line(src: Source, k: int):
    """The line where the brackets that close on line k opened, or None."""
    depth = 0
    for j in range(k, max(0, k - 200), -1):
        line = src.code[j - 1]
        depth += sum(line.count(ch) for ch in "})]") - sum(line.count(ch) for ch in "{([")
        if depth <= 0:
            return j
    return None


def leading(src: Source, a: int) -> int:
    """First line of the comments, decorators and attributes written right above line a. A comment counts only
    when the lexer blanked all of it (`/* boot */ init();` and `* HEIGHT;` are code) and the line, read as written,
    declares nothing (a misread comment may hide a live function), and a file-level directive (a shebang, a
    coding line, a build constraint, an inner `#![...]`) never goes with a declaration."""
    start = a
    while start > 1:
        k = start - 1
        raw = src.head[k - 1]
        if not raw.strip() or FILE_DIRECTIVE.match(raw):
            break
        code = src.code[k - 1].strip()
        if not code:
            if not src.text[k - 1].strip():  # a comment and nothing else
                if declares(raw):
                    break
                start = k
                continue
            j = k  # the end of a string: it goes when a decorator or attribute opened it (Elixir `@doc """`)
            while j > 1 and not src.code[j - 1].strip():
                j -= 1
            if src.code[j - 1].strip() and attribute_line(src, j):
                start = j
                continue
            break
        if attribute_line(src, k):
            start = k
            continue
        if code.endswith((")", "]", "}")):  # the last line of a multi-line decorator or attribute
            j = opening_line(src, k)
            if j and j < k and attribute_line(src, j) and not any(declared(src.head[x - 1])
                                                                  for x in range(j + 1, k + 1)):
                start = j
                continue
        break
    return start


OVERLOAD = re.compile(r"@(?:typing\.|t\.)?overload\b")
PROTOTYPE = re.compile(r"\s*(?!(?:return|else|case|throw|delete|new|goto|co_return)\b)(?:extern\s+)?"
                       r"[\w:<>,*&\s]+?[\s*&]([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?;\s*$")


def decl_name(src: Source, k: int) -> str:
    found = declared(src.head[k - 1])
    if found:
        return found[1]
    m = PROTOTYPE.match(src.code[k - 1]) if src.suffix in C_FAMILY else None
    return m.group(1) if m else ""


# A TypeScript function, overload signature or declaration (`function f(a: string): string;`).
TS_FUNCTION = re.compile(r"\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?function\b")


def companions(src: Source, a: int, start: int, end: int, name: str) -> tuple:
    """[start, end] widened over the declarations that are one with line a's: TypeScript function overload
    signatures with their implementation, Python `@overload` stubs above it and its property's setter and deleter
    below it, and C or C++ prototypes right above it with its parameter types. A type and a value of the same
    name (`type User` and `const User`) are two declarations, and so are two overloads (`int area(int)` and
    `int area(double)`): removing one never takes the other."""
    s = src.suffix
    ts, py, c = s in (".ts", ".tsx", ".mts", ".cts"), s in (".py", ".pyi"), s in C_FAMILY
    if not (ts or py or c) or not name or ts and not TS_FUNCTION.match(src.head[a - 1]):
        return start, end
    indent = indent_of(src.head[a - 1])

    def decorators(top, k):
        return [src.code[x - 1].strip() for x in range(top, k)]

    while start > 1:  # above: overload signatures, `@overload` stubs, prototypes
        k = next((j for j in range(start - 1, 0, -1) if src.code[j - 1].strip()), None)
        j = next((x for x in range(k, 0, -1) if src.code[x - 1].strip() and indent_of(src.head[x - 1]) <= indent),
                 None) if k else None
        if not j or indent_of(src.head[j - 1]) != indent or decl_name(src, j) != name:
            break
        top = leading(src, j)
        signature, params = src.code[j - 1].rstrip().endswith(";"), c_params(src, j, name) if c else None
        if not (ts and signature and TS_FUNCTION.match(src.head[j - 1])
                or c and signature and params is not None and params == c_params(src, a, name)
                or py and any(OVERLOAD.match(d) for d in decorators(top, j))):
            break
        start = top
    last, stub = a, py and any(OVERLOAD.match(d) for d in decorators(leading(src, a), a))
    while True:  # below: the implementation after signatures or stubs, a property's setter and deleter
        j = next((x for x in range(end + 1, len(src.head) + 1) if src.code[x - 1].strip()), None)
        if not j or indent_of(src.head[j - 1]) != indent:
            break
        d = j
        while py and d <= len(src.head) and src.code[d - 1].strip().startswith("@"):
            d += 1
        if d > len(src.head) or decl_name(src, d) != name:
            break
        marks = decorators(j, d)
        accessor = any(re.match(r"@" + re.escape(name) + r"\.(?:setter|deleter|getter)\b", m) for m in marks)
        if not (ts and src.code[last - 1].rstrip().endswith(";") and TS_FUNCTION.match(src.head[d - 1])
                or py and (stub or accessor)):
            break
        span = src.statement(d, name)
        if span and span[0] > span[1]:
            break  # it shares a line with another statement
        end = span[1] if span else capped(src, d, body_end(src, d, indent), indent)
        last, stub = d, py and any(OVERLOAD.match(m) for m in marks)
    return start, end


# Words that are no type of a C or C++ parameter (`const char *s`), and the built-in types, after which no name
# is left out (`unsigned int`).
C_QUALIFIERS = {"const", "volatile", "struct", "union", "enum", "class", "typename", "register", "restrict",
                "__restrict", "__restrict__"}
C_BUILTINS = {"void", "char", "short", "int", "long", "float", "double", "signed", "unsigned", "bool", "_Bool",
              "wchar_t", "char8_t", "char16_t", "char32_t", "auto"}
C_TOKEN = re.compile(r"[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*|::|\.\.\.|[*&\[\]()<>]")


def c_params(src: Source, k: int, name: str):
    """The parameter types of the C or C++ function `name` declared at line k, parameter names and default
    values left out, with the qualifiers after them (`const`, `noexcept`, `&`): equal for a prototype and the
    definition it declares (`int f(int);` and `int f(int x) {`), different for two overloads. None when they
    cannot be read."""
    text = " ".join(src.code[x - 1] for x in range(k, min(len(src.code), k + 20) + 1))
    m = re.search(r"(?<![\w$])" + re.escape(name) + r"\s*\(", text)
    if not m:
        return None
    depth, j = 0, m.end() - 1
    for x in range(j, len(text)):
        depth += {"(": 1, ")": -1}.get(text[x], 0)
        if depth == 0:
            break
    else:
        return None
    after = re.split(r"[{;:=]|->|\b(?:override|final|try)\b", text[x + 1:], maxsplit=1)[0]
    params, part, level = [], "", 0
    for ch in text[j + 1:x] + ",":
        level += 1 if ch in "([{<" else -1 if ch in ")]}>" else 0
        if ch == "," and level == 0:
            params.append(part)
            part = ""
        else:
            part += ch
    types = []
    for p in params:
        level, cut = 0, len(p)
        for y, ch in enumerate(p):  # a default value (`int x = 0`) is the declaration's alone
            level += 1 if ch in "([{<" else -1 if ch in ")]}>" else 0
            if ch == "=" and level == 0:
                cut = y
                break
        toks = [re.sub(r"\s+", "", w) for w in C_TOKEN.findall(p[:cut])]
        last = toks[-1] if toks else ""
        if len(toks) > 1 and re.fullmatch(r"[A-Za-z_]\w*", last) and last not in C_BUILTINS | C_QUALIFIERS \
                and any(re.fullmatch(r"[A-Za-z_][\w:]*", w) and w not in C_QUALIFIERS for w in toks[:-1]):
            toks = toks[:-1]  # the parameter's name
        types.append(" ".join(toks))
    if types in ([""], ["void"]):
        types = []
    return tuple(types), tuple(re.findall(r"\b(?:const|volatile|noexcept)\b|&&?", after))


# Languages where `;` ends a statement and `}` a body, so that a line can hold a declaration and other code.
SEMICOLON_LANGS = JS_FAMILY | C_FAMILY | {".java", ".cs", ".go", ".rs", ".kt", ".kts", ".swift", ".scala", ".dart",
                                          ".php", ".groovy"}


def shares_line(src: Source, a: int, end: int) -> bool:
    """Whether the first or the last line of the declaration at line a also holds code that is no part of it:
    another statement after a `;` at its own level (`const STALE = 1; audit();`), a word after its closing brace
    (`} audit();`, but `} as const`), or the brace that closes what holds it (`} }`). Deleting that line would
    delete that code too."""
    if src.suffix not in SEMICOLON_LANGS:
        return False
    for k in sorted({a, end}):
        code = src.code[k - 1]
        depth, closed = (0 if k == a else src.depth[k - 1] - src.depth[a - 1]), False
        for j, ch in enumerate(code):
            if ch.isspace():
                continue
            if closed and (ch.isalpha() or ch in "_$") and src.suffix not in C_FAMILY:  # `} Point;` is C's typedef
                word = WORD.match(code, j)
                if not word or word.group(0) not in ("as", "satisfies"):
                    return True
            closed = False
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth < 0:
                    return True
                closed = depth == 0 and ch == "}"
            elif ch == ";" and depth == 0 and code[j + 1:].strip():
                return True
    return False


def extent(src: Source, a: int, name: str = "") -> tuple:
    """First and last line (1-based) of the declaration at line a: its comments and decorators, its signature
    however many lines it spans, and its body. It never runs into the next declaration at its own depth or
    above, nor into that one's comments and decorators. A Python file this interpreter parses gives the syntax
    tree's own range. (a, a - 1), which no line fills, when the declaration shares a line with other code: no
    deletion of whole lines removes it alone."""
    span = src.statement(a, name)
    if span:
        return span if span[0] > span[1] else companions(src, a, leading(src, span[0]), span[1], name)
    indent = indent_of(src.head[a - 1])
    end = capped(src, a, body_end(src, a, indent), indent)
    if shares_line(src, a, end):
        return a, a - 1
    return companions(src, a, leading(src, a), end, name)


IMPL = re.compile(r"(?:unsafe\s+)?impl\s+(?:(?P<trait>[\w:]+)\s+for\s+)?(?P<type>[\w:]+)")
EXTENSION = re.compile(r"(?:(?:public|private|internal|fileprivate|open)\s+)?extension\s+(?P<type>[\w.]+)")
GROUP = re.compile(r"(?:const|var|type)\s*\($")
TYPE_WORD = re.compile(r"\b(struct|enum|union|class|type|trait|protocol|interface)\b")


def enclosing(src: Source, a: int) -> int:
    """The line that opened the innermost bracket line a sits in (the `mod` or type block that holds it), or 0 at
    the top level."""
    d = src.depth[a - 1]
    return next((k for k in range(a - 1, 0, -1) if src.depth[k - 1] < d), 0) if d > 0 else 0


def wrappers(src: Source, spans: list, removed: list) -> list:
    """Blocks that go with removed declarations, with their comments and attributes: a Go `const (`, `var (` or
    `type (` group whose every line is removed; a Rust `impl` or Swift `extension` block of a removed type; a Rust
    `impl` of a removed trait. The block must sit at the removed declaration's indentation, in the same block (the
    same `mod` or type: `mod live`'s `impl Drop for Cache` is not `mod legacy`'s), and name it by a path of this
    file (`Name`, `self::Name`), never another module's (`std::error::Error`, `fmt::Display`). `removed` holds
    (name, the keyword of its declaration line, its indentation, the line that opened its block)."""
    out = []
    local = ("self::", "crate::") if Path(src.path).name in ("lib.rs", "main.rs") else ("self::",)

    def leaf(path):
        if not path or "." in path or ("::" in path and not path.startswith(local)):
            return ""
        return path.rsplit("::", 1)[-1]

    for n in range(1, len(src.head) + 1):
        line = src.code[n - 1].strip()
        if not line.endswith(("{", "(")) or any(s <= n <= e for s, e in spans):
            continue
        group = GROUP.match(line)
        header = line
        while re.search(r"<[^<>]*>", header):  # generic parameters and bounds name no type
            header = re.sub(r"<[^<>]*>", "", header)
        m = IMPL.match(header) if src.suffix == ".rs" else EXTENSION.match(header) if src.suffix == ".swift" else None
        if not (group or (m and line.endswith("{"))):
            continue
        end = bracket_end(src.code, n)
        if not end or end <= n:
            continue
        if group:
            inner = [i for i in range(n + 1, end) if src.code[i - 1].strip()]
            if inner and all(any(s <= i <= e for s, e in spans) for i in inner):
                out.append((n, end))
            continue
        ind, typ = indent_of(src.head[n - 1]), leaf(m.group("type"))
        trait, home = leaf(m.groupdict().get("trait") or ""), enclosing(src, n)
        if any(at == ind and block == home
               and ((name == typ and word in ("struct", "enum", "union", "class", "type", "protocol"))
                    or (trait and name == trait and word in ("trait", "protocol")))
               for name, word, at, block in removed):
            out.append((leading(src, n), end))
    return out


def diffable(data: bytes) -> bool:
    """Whether a line diff of this content means what it says: text in an 8-bit encoding."""
    return b"\0" not in data[:8192] and not data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))


HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
# A diff of one file that this script can parse whatever the user's settings say.
DIFF = ["git", "diff", "-U0", "--inter-hunk-context=0", "--text", "--no-color", "--no-ext-diff", "--no-textconv"]
# File header lines that change more than the content: the guard never accepts them.
FILE_CHANGE = re.compile(rb"^(old mode|new mode|deleted file mode|new file mode|rename from|copy from|Binary files) ",
                         re.M)


def read_diff(out: bytes, errors: str = "replace"):
    """The hunks of a one-file `git diff`, each [first old line, old count, first new line, new count, [(old line
    number, deleted text)], [added text], whether the old side ends without a newline, whether the new side does].
    Each hunk is read by the counts in its header, so a deleted `-- comment` or an added `++i;` is never taken for
    a header, and lines are split on newlines only. Context lines only advance the count. None when the output
    does not add up, or holds a NUL byte (content git could not diff as text, such as a file rewritten in UTF-16).
    `errors` decodes bytes that are no UTF-8: the guard keeps each one apart ("surrogateescape")."""
    if b"\0" in out:
        return None
    found, cur, left, old, last = [], None, (0, 0), 0, ""
    for raw in out.split(b"\n"):
        if raw.startswith(b"\\"):  # "\ No newline at end of file", about the line before it
            if cur is not None and last:
                cur[6] = cur[6] or last in "- "
                cur[7] = cur[7] or last in "+ "
            continue
        if left == (0, 0):
            m = HUNK.match(raw)
            if m:
                old = int(m.group(1))
                cur = [old, int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1), [], [], False, False]
                found.append(cur)
                left, last = (cur[1], cur[3]), ""
            continue  # file headers
        text = raw[1:].decode("utf-8", errors)
        if raw[:1] == b"-" and left[0]:
            cur[4].append((old, text))
            old, left, last = old + 1, (left[0] - 1, left[1]), "-"
        elif raw[:1] == b"+" and left[1]:
            cur[5].append(text)
            left, last = (left[0], left[1] - 1), "+"
        elif raw[:1] == b" " and left[0] and left[1]:
            old, left, last = old + 1, (left[0] - 1, left[1] - 1), " "
        else:
            return None
    return found if left == (0, 0) else None


def parse_diff(out: bytes):
    """The hunks of a one-file `git diff` as (first old line, old count, new count, [(old line number, deleted
    text)], [added text]); None when it cannot be read (see read_diff)."""
    found = read_diff(out)
    return None if found is None else [(h[0], h[1], h[3], h[4], h[5]) for h in found]


def diff_text(text: str, first: bool, noeol: bool) -> str:
    """A diff line as `head_lines` and `read_lines` hold it: no byte-order mark on line 1, no CR before its
    newline."""
    if first and text.startswith("\ufeff"):
        text = text[1:]
    return text if noeol or not text.endswith("\r") else text[:-1]


def hunks(root: Path, path: str, head: list, work: list) -> tuple:
    """(problem, hunks) of a file's change against HEAD, each hunk (first old line, [(old line number, deleted
    text)], [added text]), its text normalized as `head` and `work` hold it. The hunks must rebuild the working
    tree from HEAD exactly: a change git does not show (a file marked assume-unchanged or skip-worktree, an
    `ident` attribute, a filter) fails the check instead of passing it."""
    proc = run(DIFF + ["HEAD", "--", path], root, check=False)
    if proc.returncode != 0:
        return "git could not diff it", None
    m = FILE_CHANGE.search(proc.stdout.split(b"\n@@", 1)[0])
    if m:
        return f"git reports more than a content change ({m.group(1).decode()})", None
    found = read_diff(proc.stdout, "surrogateescape")
    if found is None:
        return "git's diff of it does not add up", None
    old = [(t, True) for t in head[:-1]] + ([(head[-1], False)] if head[-1] else [])
    out, rebuilt, pos = [], [], 0
    for first, count, new_first, new_count, deleted, added, old_noeol, new_noeol in found:
        if count != len(deleted) or new_count != len(added):
            return "git's diff of it holds context lines", None
        dels = [(n, diff_text(t, n == 1, old_noeol and k == len(deleted) - 1)) for k, (n, t) in enumerate(deleted)]
        adds = [diff_text(t, new_first + k == 1, new_noeol and k == len(added) - 1) for k, t in enumerate(added)]
        stop = first - 1 if count else first
        if stop < pos or stop + len(dels) > len(old) or [t for t, _ in old[stop:stop + len(dels)]] != [t for _, t in dels]:
            return "git's diff of it does not match its committed version", None
        rebuilt += old[pos:stop] + [(t, True) for t in adds[:-1]] + ([(adds[-1], not new_noeol)] if adds else [])
        pos = stop + len(dels)
        out.append((first, dels, adds))
    rebuilt += old[pos:]
    if "".join(t + ("\n" if nl else "") for t, nl in rebuilt) != "\n".join(work):
        return ("git's diff of it does not match the file (marked assume-unchanged or skip-worktree, or rewritten "
                "by an attribute or a filter)"), None
    return "", out


def exact_lines(data: bytes):
    """A file's lines as the guard compares them, split on newlines only, CRLF read as LF, a UTF-8 byte-order mark
    left out (`stray_deletions` compares it apart): each byte that is no UTF-8 stays itself (a lone surrogate), so
    that two lines are equal only when their bytes are (`autoris\\xe9` is not `autoris\\xe8`, which U+FFFD would
    make one). None for binary data."""
    if b"\0" in data[:8192] or data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return None
    if data.startswith(codecs.BOM_UTF8):
        data = data[len(codecs.BOM_UTF8):]
    return data.decode("utf-8", "surrogateescape").replace("\r\n", "\n").split("\n")


# Escapes that Java (and Scala, Groovy) decode before reading anything else, comments included: one that stands
# for a line break, a quote, `*`, `/` or a backslash turns what looks like a comment or a string into code
# (`// note \u000a audit();`). Kotlin decodes escapes only inside literals.
UNICODE_ESCAPED = {".java", ".scala", ".sc", ".groovy"}
UNICODE_ESCAPE = re.compile(r"(?<!\\)(?:\\\\)*\\u+(?:000[aAdD]|002[27aAfF]|005[cC])")
PY_CODING = re.compile(r"[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")
# Longer lines are not read: a generated data line costs time in proportion to its length.
MAX_LINE = 1_000_000


def unreadable(path: str, head: list) -> str:
    """Why the guard cannot read a committed file the way its compiler does, or "": a line too long to read, a
    unicode escape Java decodes into a line break or a quote, a Python coding cookie other than UTF-8 or Latin-1
    (UTF-7 hides code in what reads as a comment: `# +AAo-audit()`), a C or C++ comment marker split by a
    backslash-newline, or a `//` comment that a backslash followed by blanks may continue on the next line, which
    compilers read differently."""
    suffix = Path(path).suffix.lower()
    for n, line in enumerate(head, 1):
        if len(line) > MAX_LINE:
            return f"line {n} holds {len(line)} characters, more than this check reads"
        if suffix in UNICODE_ESCAPED and UNICODE_ESCAPE.search(line):
            return f"line {n} holds a unicode escape that Java reads as a line break or a quote, even in a comment"
    if suffix in (".py", ".pyi"):
        for n, line in enumerate(head[:2], 1):
            m = PY_CODING.match(line)
            if m:
                name = m.group(1).lower().replace("_", "-")
                try:
                    known = codecs.lookup(name).name
                except LookupError:
                    known = ""
                if not (name.startswith(("utf-8-", "latin-1-", "iso-8859-1-", "iso-latin-1-"))
                        or known in ("utf-8", "utf-8-sig", "ascii", "iso8859-1")):
                    return f"its coding cookie ({clean(m.group(1), 40)}) is not UTF-8 or Latin-1"
                break
            if line.strip() and not line.lstrip().startswith("#"):
                break  # Python reads a cookie on line 2 only below a comment or a blank line
    if suffix in C_FAMILY:
        for n, line in enumerate(head[:-1], 1):
            body = line.rstrip()
            if not body.endswith("\\"):
                continue
            nxt = head[n].lstrip()
            if body[-2:-1] in ("/", "*") and nxt[:1] in ("*", "/"):
                return f"line {n} splits a comment marker with a backslash before its line break"
            if body != line and "//" in body:
                return f"line {n} ends a `//` comment with a backslash and blanks, which compilers read differently"
    return ""


def head_lines(lg: Ledger, path: str, rev: str = "HEAD") -> list:
    """Lines of a committed version of a file (`rev`), or of the staged one (rev ""), split on newlines only."""
    data = run(["git", "cat-file", "blob", f"{rev}:{path}"], lg.root, check=False).stdout
    return (decode(data) or "").replace("\r\n", "\n").split("\n")


# Characters some languages end a line on while git and this script do not: code after one hides behind what
# looks like a comment, a blank or another line.
HIDDEN_BREAK = re.compile("[\x0b\x0c\x1c-\x1e\x85\u2028\u2029]|\r(?!$)")


def hidden_code(text: str) -> bool:
    """Whether a line holds a line break git does not see with code after it."""
    parts = HIDDEN_BREAK.split(text)
    return len(parts) > 1 and any(p.strip() for p in parts[1:])


def twin_key(text: str) -> str:
    """A line as twins compare: trailing blanks do not count, unless they follow a backslash, which escapes them."""
    stripped = text.rstrip()
    return text if stripped.endswith("\\") else stripped


# Changed lines above which a hunk's twins are paired with difflib's heuristics for frequent lines (`}`, blank
# lines): an exact pairing of a whole file takes time quadratic in its length.
TWINS_EXACT = 4000


def twin_opcodes(deleted: list, added: list) -> list:
    """difflib opcodes pairing a hunk's deleted lines with its added ones by `twin_key`: an `equal` pair is a line
    put back unchanged (an end-of-line conversion). The unchanged ends are set aside first, so that a file written
    back whole with other line endings costs no more than what changed in it. Any pairing is safe: a worse one only
    leaves more lines to justify."""
    a, b = [twin_key(t) for t in deleted], [twin_key(t) for t in added]
    p, m = 0, min(len(a), len(b))
    while p < m and a[p] == b[p]:
        p += 1
    q = 0
    while q < m - p and a[len(a) - 1 - q] == b[len(b) - 1 - q]:
        q += 1
    ops = [("equal", 0, p, 0, p)] if p else []
    mid_a, mid_b = a[p:len(a) - q], b[p:len(b) - q]
    if mid_a or mid_b:
        sm = difflib.SequenceMatcher(None, mid_a, mid_b, autojunk=max(len(mid_a), len(mid_b)) > TWINS_EXACT)
        ops += [(op, i1 + p, i2 + p, j1 + p, j2 + p) for op, i1, i2, j1, j2 in sm.get_opcodes()]
    return ops + ([("equal", len(a) - q, len(a), len(b) - q, len(b))] if q else [])


def starts_statement(line: str, s: str) -> bool:
    """Whether a line (comments blanked, stripped) starts an import or export statement in this language."""
    if s in JS_FAMILY:
        return re.match(r"import\b(?!\s*[(.])|export\s*(?:type\s*)?[{*]|export\s+default\s+[\w$.]+\s*;?$|"
                        r"export\s*=\s*[\w$.]+\s*;?$|(?:const|let|var)\s+[\w${}:,\s]+=\s*require\s*\(|"
                        r"require\s*\(", line) is not None
    if s in (".py", ".pyi"):
        return re.match(r"import\s|from\s+\S+\s+import\b", line) is not None
    if s == ".rs":
        return re.match(r"(?:pub(?:\([^)]*\))?\s+)?(?:use\s|mod\s+\w+\s*;|extern\s+crate\s)", line) is not None
    if s == ".cs":
        return re.match(r"(?:global\s+)?using\s+(?:(?:static\s+)?[\w.]+\s*;|\w+\s*=\s*[^;(]+;)", line) is not None
    if s == ".php":
        return re.match(r"use\s|(?:require|require_once|include|include_once)\b", line) is not None
    if s == ".rb":
        return re.match(r"(?:require|require_relative|load)\b|(?:include|extend|prepend)\s+[A-Z]", line) is not None
    if s in C_FAMILY:
        return re.match(r"#\s*(?:include|import)\b|@import\b", line) is not None
    if s in (".ex", ".exs"):
        return re.match(r"(?:alias|import|require|use)\s", line) is not None
    if s == ".lua":
        return re.match(r"(?:local\s+\w+\s*=\s*)?require\b", line) is not None
    if s in (".go", ".java", ".kt", ".kts", ".scala", ".groovy", ".swift", ".hs", ".elm", ".dart"):
        return re.match(r"(?:@\w+\s+)*import\b|(?:export|part)\s", line) is not None
    return False


def statements(src: Source) -> list:
    """(first, last) of every import and export statement of a file, multi-line ones whole: a statement ends where
    its brackets close and, in Python, where no backslash continues it."""
    out, k, n = [], 1, len(src.head)
    while k <= n:
        if not starts_statement(src.text[k - 1].strip(), src.suffix):
            k += 1
            continue
        j, depth = k, 0
        while True:
            depth += net(src.code[j - 1])
            if (depth <= 0 and not src.code[j - 1].rstrip().endswith("\\")) or j >= n or j - k >= 500:
                break
            j += 1
        out.append((k, j))
        k = j + 1
    return out


def split_spans(shape: str) -> list:
    """(start, end) columns of the pieces of a line's shape between its top-level commas."""
    out, depth, start = [], 0, 0
    for j, ch in enumerate(shape):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append((start, j))
            start = j + 1
    out.append((start, len(shape)))
    return out


def js_names(spec: str):
    """(name, bound) for what a JavaScript import or require binds (`a`, `{ b as c }`, `* as ns`, `{ d: e }`), or
    None when it cannot tell."""
    out = []
    for part in re.split(r"[{},]", spec):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(?:type\s+)?(?:\*\s*as\s+)?([\w$]+)(?:\s*(?:\bas\b|:)\s*([\w$]+))?$", part)
        if not m:
            return None
        out.append((m.group(1), m.group(2) or m.group(1)))
    return out or None


def export_pairs(spec: str):
    """(local, exported) for each name of an `export { a, b as c }` list, or None when it cannot tell."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(?:type\s+)?([\w$]+)(?:\s+as\s+([\w$]+))?$", part)
        if not m:
            return None
        out.append((m.group(1), m.group(2) or m.group(1)))
    return out


def use_leaves(tree: str):
    """The names a Rust `use` tree binds (`a::{b, c as d, e::{f, self}}` binds b, d, f and e), or None for a glob
    or an `as _`, whose uses this script cannot see."""
    tree = tree.strip()
    m = re.match(r"(.*?)(?:::)?\{(.*)\}$", tree, re.S)
    if m:
        out = set()
        for a, b in split_spans(m.group(2)):
            part = m.group(2)[a:b].strip()
            if part == "self":
                leaf = m.group(1).rstrip(":").rsplit("::", 1)[-1]
                if not re.fullmatch(r"[A-Za-z_]\w*", leaf):
                    return None
                out.add(leaf)
            elif part:
                sub = use_leaves(part)
                if sub is None:
                    return None
                out |= sub
        return out
    if tree.endswith("*"):
        return None
    m = re.match(r"(.*?)\s+as\s+(\w+)$", tree)
    if m:
        return None if m.group(2) == "_" else {m.group(2)}
    leaf = tree.rsplit("::", 1)[-1]
    return {leaf} if re.fullmatch(r"[A-Za-z_]\w*", leaf) else None


def go_package(path: str) -> str:
    """The name a Go import path binds by convention: its last element, or the one before a `/v2`, with a `.v3`
    version dropped; "" when that is no identifier (`go-yaml`): the package may be named otherwise."""
    parts = path.split("/")
    name = parts[-2] if len(parts) > 1 and re.fullmatch(r"v\d+", parts[-1]) else parts[-1]
    name = re.sub(r"\.v\d+$", "", name)
    return name if re.fullmatch(r"[A-Za-z_]\w*", name) else ""


def rust_mod_files(path: str, name: str) -> set:
    """The files `mod name;` in `path` loads: name.rs or name/mod.rs beside a crate root (lib.rs, main.rs, a
    mod.rs, a file directly in src/bin, examples, tests or benches), under the folder named after any other file."""
    folder, base = posixpath.split(path)
    root = base in ("lib.rs", "main.rs", "mod.rs", "build.rs") or posixpath.basename(folder) in (
        "bin", "examples", "tests", "benches")
    if not root:
        folder = posixpath.join(folder, base[:-3] if base.endswith(".rs") else base)
    return {posixpath.join(folder, name + ".rs"), posixpath.join(folder, name, "mod.rs")}


def parse_statement(t: str, s: str, nested: bool) -> tuple:
    """(kind, names, module) of one import or export statement joined on one line, comments blanked. kind:
    "import" (names: (name, bound) pairs, None when it cannot tell), "side" (it runs code when loaded), "export"
    (names: (local, exported) pairs, None for `export *`), "mixin" (a Ruby include, a PHP trait use), "mod" (a
    Rust module), or "" for a form this script does not know. module: the module path it names, or ""."""
    t = t.strip()
    m = None
    if s in JS_FAMILY:
        m = re.match(r"""import\s*(["'`])(.*?)\1\s*;?$""", t)
        if m:
            return "side", [], m.group(2)
        m = re.match(r"""import\s+(?:type\s+)?(.+?)\s+from\s*(["'`])(.*?)\2\s*;?$""", t)
        if m:
            return "import", js_names(m.group(1)), m.group(3)
        m = re.match(r"""import\s+([\w$]+)\s*=\s*require\s*\(\s*(["'`])(.*?)\2\s*\)\s*;?$""", t)
        if m:
            return "import", [(m.group(1), m.group(1))], m.group(3)
        m = re.match(r"""(?:const|let|var)\s+(.+?)\s*=\s*require\s*\(\s*(["'`])(.*?)\2\s*\)\s*;?$""", t)
        if m:
            return "import", js_names(m.group(1)), m.group(3)
        m = re.match(r"""require\s*\(\s*(["'`])(.*?)\1\s*\)\s*;?$""", t)
        if m:
            return "side", [], m.group(2)
        m = re.match(r"""export\s*\*\s*(?:as\s+[\w$]+\s*)?from\s*(["'`])(.*?)\1\s*;?$""", t)
        if m:
            return "export", None, m.group(2)
        m = re.match(r"""export\s*(?:type\s*)?\{(.*?)\}\s*(?:from\s*(["'`])(.*?)\2)?\s*;?$""", t)
        if m:
            return "export", export_pairs(m.group(1)), m.group(3) or ""
        m = re.match(r"export\s+default\s+([\w$.]+)\s*;?$", t) or re.match(r"export\s*=\s*([\w$.]+)\s*;?$", t)
        if m:
            return "export", [(m.group(1).rsplit(".", 1)[-1], "default")], ""
    elif s in (".py", ".pyi"):
        t = re.sub(r"\\\s*", " ", t)
        m = re.match(r"from\s+(\.*[\w.]*)\s+import\s+\(?(.*?)\)?\s*;?$", t)
        if m:
            out = []
            for part in m.group(2).split(","):
                mm = re.match(r"\s*(\w+)(?:\s+as\s+(\w+))?\s*$", part)
                if part.strip() and not mm:
                    return "import", None, m.group(1)  # `*`: what it binds is unknown
                if mm:
                    out.append((mm.group(1), mm.group(2) or mm.group(1)))
            return "import", out or None, m.group(1)
        m = re.match(r"import\s+(.+?)\s*;?$", t)
        if m:
            out, side = [], False
            for part in m.group(1).split(","):
                mm = re.match(r"\s*([\w.]+)(?:\s+as\s+(\w+))?\s*$", part)
                if not mm:
                    return "", None, ""
                side = side or "." in mm.group(1)  # `import a.b` loads a submodule, often to register something
                out.append((mm.group(1), mm.group(2) or mm.group(1).split(".")[0]))
            return ("side" if side else "import"), out, out[0][0] if len(out) == 1 else ""
    elif s == ".go":
        body = t[6:].strip() if t.startswith("import") else ""
        if body.startswith("(") and body.endswith(")"):
            body = body[1:-1]
        specs = re.findall(r'(?:([A-Za-z_]\w*|\.)\s+)?"([^"]*)"', body)
        if not specs or re.sub(r'(?:(?:[A-Za-z_]\w*|\.)\s+)?"[^"]*"|[\s;]', "", body):
            return "", None, ""
        kind, out = "import", []
        for alias, path in specs:
            if alias == "_":
                kind = "side"  # imported for its init functions
                continue
            name = alias if alias and alias != "." else "" if alias else go_package(path)
            if not name:
                return kind, None, ""
            out.append((path, name))
        return kind, out, ""
    elif s == ".rs":
        m = re.match(r"(pub(?:\([^)]*\))?\s+)?use\s+(.+?)\s*;$", t)
        if m:
            leaves = use_leaves(m.group(2))
            return "export" if m.group(1) else "import", None if leaves is None else [(x, x) for x in sorted(leaves)], ""
        m = re.match(r"(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;$", t)
        if m:
            return "mod", [(m.group(1), m.group(1))], ""
        m = re.match(r"extern\s+crate\s+(\w+)(?:\s+as\s+(\w+))?\s*;$", t)
        if m:
            return "import", [(m.group(1), m.group(2) or m.group(1))], ""
    elif s in (".java", ".kt", ".kts", ".scala", ".groovy"):
        m = re.match(r"import\s+(static\s+)?([\w.]+?)(\.\*|\._)?\s*(?:\bas\s+(\w+))?\s*;?$", t)
        if m:
            leaf = m.group(2).rsplit(".", 1)[-1]
            return "import", None if m.group(3) else [(leaf, m.group(4) or leaf)], ""
        m = re.match(r"import\s+[\w.]+\.\{(.*)\}\s*;?$", t)  # Scala `import a.b.{C, D => E}`
        if m:
            out = []
            for part in m.group(1).split(","):
                mm = re.match(r"\s*(\w+)(?:\s*=>\s*(\w+))?\s*$", part)
                if not mm or "_" in (mm.group(1), mm.group(2)):
                    return "import", None, ""
                out.append((mm.group(1), mm.group(2) or mm.group(1)))
            return "import", out, ""
    elif s == ".cs":
        if re.match(r"(?:global\s+)?using\s+(?:static\s+)?[\w.]+\s*;$", t):
            return "import", None, ""  # a namespace or a type's static members
        m = re.match(r"(?:global\s+)?using\s+(\w+)\s*=\s*[^;]+;$", t)
        if m:
            return "import", [(m.group(1), m.group(1))], ""
    elif s == ".php":
        m = re.match(r"""(?:require|require_once|include|include_once)\b\s*\(?\s*(["'])(.*?)\1\s*\)?\s*;$""", t)
        if m or re.match(r"(?:require|require_once|include|include_once)\b", t):
            return "side", [], m.group(2) if m else ""
        m = re.match(r"use\s+(.+?)\s*;$", t)
        if m and nested:  # `use SoftDeletes;` inside a class: a trait, not an import
            names = [x.strip().rsplit("\\", 1)[-1] for x in m.group(1).split(",")]
            return ("mixin", [(x, x) for x in names], "") if all(re.fullmatch(r"\w+", x) for x in names) else \
                ("", None, "")
        if m:
            body = re.sub(r"^(?:function|const)\s+", "", m.group(1))
            group = re.match(r"(.*?)\\?\{(.*)\}$", body)
            out = []
            for part in (group.group(2) if group else body).split(","):
                pairs = item_names(part, s, "import")
                if not pairs:
                    return "import", None, ""
                out += pairs
            return "import", out, ""
    elif s == ".rb":
        m = re.match(r"""(require_relative|require|load)\s*\(?\s*(["'])(.*?)\2\s*\)?$""", t)
        if m:
            return "side", [], "" if m.group(1) == "load" else ("./" if m.group(1) == "require_relative" else "") + \
                m.group(3)
        m = re.match(r"(?:include|extend|prepend)\s+([\w:]+(?:\s*,\s*[\w:]+)*)$", t)
        if m:
            return "mixin", [(x.strip().rsplit("::", 1)[-1],) * 2 for x in m.group(1).split(",")], ""
    elif s in C_FAMILY:
        m = re.match(r"""#\s*(?:include|import)\s*"([^"]+)"\s*$""", t)
        if m or re.match(r"#\s*(?:include|import)\s*<|@import\b", t):
            return "side", [], "./" + m.group(1) if m else ""
    elif s in (".ex", ".exs"):
        m = re.match(r"alias\s+([\w.]+)\.\{(.*)\}$", t)
        if m:
            return "import", [(x.strip().rsplit(".", 1)[-1],) * 2 for x in m.group(2).split(",")], ""
        m = re.match(r"alias\s+([\w.]+)(?:\s*,\s*as:\s*(\w+))?$", t)
        if m:
            leaf = m.group(1).rsplit(".", 1)[-1]
            return "import", [(leaf, m.group(2) or leaf)], ""
        if re.match(r"use\s", t):
            return "side", [], ""
        if re.match(r"(?:import|require)\s", t):
            return "import", None, ""
    elif s == ".dart":
        m = re.match(r"""(import|export|part)\s+(["'])(.*?)\2\s*(.*?)\s*;$""", t)
        if m and m.group(1) != "import":
            return ("export", None, m.group(3)) if m.group(1) == "export" else ("side", [], m.group(3))
        if m:
            alias = re.match(r"(?:deferred\s+)?as\s+(\w+)$", m.group(4))
            show = re.match(r"show\s+([\w\s,]+)$", m.group(4))
            names = [alias.group(1)] if alias else [x.strip() for x in show.group(1).split(",") if x.strip()] \
                if show else None
            return "import", None if names is None else [(x, x) for x in names], m.group(3)
    elif s == ".swift":
        m = re.match(r"((?:@\w+\s+)*)import\s+(?:(?:typealias|struct|class|enum|protocol|let|var|func)\s+)?[\w.]+\s*;?$", t)
        if m:
            return "export" if "@_exported" in m.group(1) else "import", None, ""
    elif s == ".lua":
        m = re.match(r"""local\s+(\w+)\s*=\s*require\s*\(?\s*(["'])(.*?)\2\s*\)?\s*;?$""", t)
        if m:
            return "import", [(m.group(1), m.group(1))], m.group(3)
        m = re.match(r"""require\s*\(?\s*(["'])(.*?)\1\s*\)?\s*;?$""", t)
        if m:
            return "side", [], m.group(2)
    elif s in (".hs", ".elm"):
        m = re.match(r"import\s+(?:qualified\s+)?[\w.]+(?:\s+as\s+(\w+))?(?:\s*\((.*)\))?\s*$", t)
        if m and m.group(1) and m.group(2) is None:
            return "import", [(m.group(1), m.group(1))], ""
        if m and m.group(2) is not None and not m.group(1):
            names = [x.strip() for x in m.group(2).split(",")]
            if all(re.fullmatch(r"\w+", x) for x in names):
                return "import", [(x, x) for x in names], ""
        if m:
            return "import", None, ""
    return "", None, ""


def item_names(part: str, s: str, kind: str):
    """(name, bound) pairs for one item of an import or export list (one line of a multi-line one, or the item a
    rewrite takes out), or None when it cannot tell."""
    part = part.strip()
    if not part:
        return None
    if s == ".rs":
        leaves = use_leaves(part)
        return None if leaves is None else [(x, x) for x in sorted(leaves)]
    if s == ".go":
        found = parse_statement("import " + part, s, False)
        return found[1] if found[0] == "import" else None
    if s == ".php":
        m = re.match(r"(?:function\s+|const\s+)?\\?([\w\\]+?)(?:\s+as\s+(\w+))?$", part)
        return [(m.group(1).rsplit("\\", 1)[-1], m.group(2) or m.group(1).rsplit("\\", 1)[-1])] if m else None
    if kind == "export":
        return export_pairs(part) or None
    m = re.match(r"(?:type\s+)?(?:\*\s*as\s+)?([\w$]+)(?:\s*(?:\bas\b|=>)\s*([\w$]+))?$", part)
    return [(m.group(1), m.group(2) or m.group(1))] if m else None


JS_EXTS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro", ".json")
JS_TWINS = {".js": (".js", ".ts", ".tsx", ".jsx"), ".jsx": (".jsx", ".tsx"), ".mjs": (".mjs", ".mts"),
            ".cjs": (".cjs", ".cts")}


class Catalog:
    """Every tracked path, read once per unit and indexed by file name, to resolve the modules imports name."""

    def __init__(self, root: Path):
        self.root, self._files, self._by_name = root, None, None

    def files(self) -> set:
        if self._files is None:
            self._files = set(tracked_files(self.root))
        return self._files

    def ending(self, tails: list) -> set:
        """Tracked paths equal to one of `tails`, or ending with `/<tail>`."""
        if self._by_name is None:
            self._by_name = defaultdict(list)
            for p in self.files():
                self._by_name[posixpath.basename(p)].append(p)
        return {p for t in tails for p in self._by_name.get(posixpath.basename(t), []) if p == t or p.endswith("/" + t)}


def module_files(module: str, s: str, path: str, catalog: Catalog) -> set:
    """The repository files an import's module path names: a relative path, a path alias (`@/lib/x`, `~/x`), a
    Python module of two names or more, a Ruby or C path. Empty for anything that may be a package from elsewhere
    (`react`, `json`): the guard never takes such an import for one of a deleted file."""
    if not module:
        return set()
    here = posixpath.dirname(path)
    if s in JS_FAMILY or s == ".dart":
        if s == ".dart" and module.startswith("package:"):
            return catalog.ending(["lib/" + module.split("/", 1)[1]]) if "/" in module else set()
        relative = module.startswith((".", "/")) or (s == ".dart" and ":" not in module)
        alias = re.match(r"(?:@/|~/|#/?|\$/)", module)
        if not relative and not alias and ("/" not in module or module.startswith("@")):
            return set()  # a package
        base = posixpath.normpath(posixpath.join(here, module)) if relative else module[alias.end() if alias else 0:]
        stem, ext = posixpath.splitext(base)
        options = [stem + e for e in JS_TWINS[ext]] if ext in JS_TWINS else [base] if ext in JS_EXTS + (".dart",) \
            else [base + e for e in JS_EXTS] + [base + "/index" + e for e in JS_EXTS]
        return {o for o in options if o in catalog.files()} if relative else catalog.ending(options)
    if s in (".py", ".pyi"):
        dots = len(module) - len(module.lstrip("."))
        name = module[dots:].replace(".", "/")
        if dots:
            base = here
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            stem = posixpath.join(base, name) if name else base
            return {f for f in (stem + ".py", stem + ".pyi", stem + "/__init__.py") if f in catalog.files()}
        if "/" not in name:
            return {f for f in (name + ".py", name + "/__init__.py", "src/" + name + ".py", "src/" + name + "/__init__.py")
                    if f in catalog.files()}
        return catalog.ending([name + ".py", name + ".pyi", name + "/__init__.py"])
    if s == ".rb":  # `require_relative "x"` is "./x"; `require "x"` searches the load path, lib/ first
        name = module[2:] if module.startswith("./") else module
        name += "" if name.endswith(".rb") else ".rb"
        if module.startswith("./"):
            return {posixpath.normpath(posixpath.join(here, name))} & catalog.files()
        return catalog.ending([name]) if "/" in name else {f for f in ("lib/" + name, name) if f in catalog.files()}
    if s in C_FAMILY or s == ".php":  # `#include "x.h"`: next to the file first, then the include paths
        name = module[2:] if module.startswith("./") else module
        return {posixpath.normpath(posixpath.join(here, name))} & catalog.files() or catalog.ending([name])
    if s == ".lua":
        name = module.replace(".", "/") + ".lua"
        return catalog.ending([name]) if "/" in module.replace(".", "/") else \
            {f for f in (name, "src/" + name, "lua/" + name) if f in catalog.files()}
    return set()


def deletion_cuts(old: str, new: str):
    """The pieces of `old` whose deletion leaves `new`, as (start, end) columns, or None when `new` is not `old`
    with pieces deleted. The unchanged ends of the line are set aside first, so that a long line costs no more than
    what changed in it; a change of more than a few thousand characters is not compared at all, nor one that
    leaves the line longer or keeps characters out of their order."""
    p, m = 0, min(len(old), len(new))
    while p < m and old[p] == new[p]:
        p += 1
    q = 0
    while q < m - p and old[len(old) - 1 - q] == new[len(new) - 1 - q]:
        q += 1
    a, b = old[p:len(old) - q], new[p:len(new) - q]
    if not b:
        return [(p, len(old) - q)] if a else []
    if len(a) > 4000 or len(b) > len(a):
        return None
    rest = iter(a)
    if not all(ch in rest for ch in b):
        return None  # `new` is no subsequence of `old`: something was added
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    if any(op not in ("equal", "delete") for op, *_ in ops):
        return None
    return [(p + i1, p + i2) for op, i1, i2, _, _ in ops if op == "delete"]


def placements(old: str, cuts: list, k: int) -> list:
    """Every place cut k can sit without changing what the deletion leaves: `f(a, a)` may lose either `a`."""
    i, j = cuts[k]
    low = cuts[k - 1][1] if k else 0
    high = cuts[k + 1][0] if k + 1 < len(cuts) else len(old)
    out, x, y = [(i, j)], i, j
    while x > low and old[x - 1] == old[y - 1]:
        x, y = x - 1, y - 1
        out.append((x, y))
    x, y = i, j
    while y < high and old[x] == old[y]:
        x, y = x + 1, y + 1
        out.append((x, y))
    return out


LINK_WORDS = {"export", "exports", "module", "default", "__all__", "pub", "mod", "as", "type", "private", "protected",
              "public", "module_function"}
LITERAL_WORDS = {"true", "false", "null", "nil", "None", "True", "False", "undefined", "NULL", "nullptr"}
# A line that starts like this only wires names into an export or a visibility list.
LINK_START = re.compile(r"\s*(?:export\b|module\s*\.\s*exports\b|exports\s*\.|__all__\b|pub\b|mod\b|private\b|"
                        r"protected\b|public\b|module_function\b)")
# Words that open a list of names without a bracket: `import a, b`, `private :a, :b`.
LIST_START = re.compile(r"(?:^|\s)(?:import|export|use|private|protected|public|module_function|include|extend)\s*$")
CONTROL_WORDS = {"return", "throw", "raise", "if", "elif", "else", "while", "for", "do", "yield", "await", "delete",
                 "new", "assert", "goto", "case", "try", "catch", "var", "let", "const", "def", "function", "class",
                 "unless", "until", "not", "and", "or", "break", "continue", "go", "defer", "echo", "print", "puts"}
SYMBOLS = {".rb", ".ex", ".exs", ".cr"}
# Languages that never reach a name through a string: there, only code uses an import (a Go struct tag
# `json:"name"` is no use of package json); elsewhere a string may (`__all__ = ["x"]`, `getattr(m, "x")`).
STATIC_NAMES = {".go", ".rs", ".java", ".kt", ".kts", ".scala", ".cs", ".swift", ".dart"} | C_FAMILY
# Where an import that binds what this script cannot name (`using System.Text;`, `import a.b.*;`) is the
# compiler's to judge: dropping one that is still needed fails the build, and never changes what code calls.
COMPILE_CHECKED = {".java", ".cs"}
COLLAPSE = (re.compile(r"(?P<head>.*?(?:::|\\))\{(?P<items>[^{}]*)\}(?P<tail>\s*;\s*)$"),
            re.compile(r"(?P<head>\s*from\s+\S+\s+import\s*)\((?P<items>[^()]*)\)(?P<tail>\s*)$"))
# How the guard reads a stretch of code: numbers, names, operators (longest first), any other character.
TOKEN = re.compile(r"\d\w*(?:\.\d\w*)?|[\w$]+|\.\.\.|===|!==|==|!=|<=|>=|::|->|\?\.|=>|\+=|-=|\*=|/=|:=|&&|\|\||"
                   r"\*\*|\S")
RUBY_SYMBOL = re.compile(r":[A-Za-z_][\w$]*[?!]?")
# A Ruby or Elixir call without parentheses, up to its first argument: `before_action :stale`, `private :stale`.
RUBY_CALL = re.compile(r"\s*([A-Za-z_][\w.]*[?!]?)\s+(?=[:\"'\w@$&*])")
OPENERS, CLOSERS = {"(", "[", "{"}, {")", "]", "}"}
# What qualifies a name: `views.stale`, `Legacy::Stale`, `$this->stale`, `App\Legacy\Stale`, `a?.stale`.
QUALIFIERS = {".", "::", "->", "?.", "\\"}
# Prefixes written against a string literal, part of it: `r"..."`, `b'...'`, `f"..."`, `u8"..."`.
STRING_PREFIXES = {"r", "b", "u", "f", "rb", "br", "fr", "rf", "u8", "l"}
# Words after which `(` opens no call (`return (a, b)` is a tuple, `if (a, b)` a condition) and `[` a list.
NOT_CALLED = {"return", "in", "not", "and", "or", "if", "elif", "while", "for", "yield", "await", "else", "assert",
              "del", "is", "case", "when", "unless", "until", "switch", "catch", "with", "throw", "raise", "typeof",
              "void", "function", "func", "lambda", "match"}
# A comment that tells a compiler, a framework or a tool what to do: a Go or cgo directive, a Ruby magic comment, a
# Haskell pragma, an `@` annotation (Doctrine and Symfony docblocks, JSDoc types). It goes only inside a planned extent.
DIRECTIVE_COMMENT = re.compile(r"\s*(?://\s*(?:go:|export\b|line\b|nolint\b|lint:)|(?://|/?\*)?\s*#\s*cgo\b|\{-#|"
                               r"#\s*(?:frozen_string_literal|encoding|warn_indent|shareable_constant_value|typed)\s*:)"
                               r"|.*(?:^|[\s*/#!(])@[A-Za-z_\\]")
# A line that declares a type or a function: its commas separate parameters, parents or options, not declarators.
TYPE_OR_FUNCTION = re.compile(r"(?:[\w$@]+\s+)*?(?:class|struct|interface|enum|trait|impl|union|record|object|protocol|"
                              r"extension|module|namespace|type|def|defp|defmacro|fn|func|function|fun|sub)\b"
                              r"(?!\s*[=,;:)\]}])")
DESTRUCTURES = re.compile(r"(?:(?:export|declare|const|let|var|val|static|final|pub|readonly|local|public|private|"
                          r"protected|internal|mut)\s+)*[\[{(]")
# A `=` that assigns: not `==`, `!=`, `<=`, `>=`, `=>`, `:=`, `+=` and the like.
ASSIGN = re.compile(r"(?<![=!<>:+\-*/%&|^~])=(?![=>~])")


def code_tokens(code: str, text: str, symbols: bool) -> list:
    """The tokens of a stretch of code (`code` with comments and literals blanked, `text` with comments only), as
    (kind, value, start, end): "word", "num", "lit" (a literal as written, quotes and prefix included, adjacent ones
    as one), "sym" (a Ruby or Elixir symbol, where `symbols`: its name) or "op"."""
    out, k, n = [], 0, len(code)
    while k < n:
        ch = code[k]
        if ch.isspace():
            if text[k].isspace():
                k += 1
                continue
            e = k  # a literal: the code is blank there and the text is not
            while e < n and code[e].isspace():
                e += 1
            end = e
            while text[end - 1].isspace():
                end -= 1
            if out and out[-1][0] == "word" and out[-1][3] == k and out[-1][1].lower() in STRING_PREFIXES:
                k = out.pop()[2]
            out.append(("lit", text[k:end], k, end))
            k = e
            continue
        m = RUBY_SYMBOL.match(code, k) if symbols and ch == ":" else None
        if m and (k == 0 or not (code[k - 1].isalnum() or code[k - 1] in "_$:)]}")):
            out.append(("sym", m.group(0)[1:].rstrip("?!"), k, m.end()))
            k = m.end()
            continue
        m = TOKEN.match(code, k)
        tok = m.group(0)
        out.append(("num" if tok[0].isdigit() else "word" if tok[0].isalnum() or tok[0] in "_$" else "op", tok, k,
                    m.end()))
        k = m.end()
    return out


def closer(toks: list, i: int) -> int:
    """Index of the token that closes the bracket opened at toks[i], or -1."""
    depth = 0
    for j in range(i, len(toks)):
        if toks[j][0] == "op" and toks[j][1] in OPENERS:
            depth += 1
        elif toks[j][0] == "op" and toks[j][1] in CLOSERS:
            depth -= 1
            if not depth:
                return j
    return -1


def split_items(toks: list) -> list:
    """The items of a list of tokens, split at its top-level commas; empty ones left out."""
    out, cur, depth = [], [], 0
    for t in toks:
        if t[0] == "op" and t[1] in OPENERS:
            depth += 1
        elif t[0] == "op" and t[1] in CLOSERS:
            depth -= 1
        elif t[0] == "op" and t[1] == "," and not depth:
            if cur:
                out.append(cur)
            cur = []
            continue
        cur.append(t)
    return out + ([cur] if cur else [])


def keyed(toks: list) -> tuple:
    """(key, value tokens) of one item: `key: v`, `"key": v`, `key => v`, `:key => v`, `key=v`; the key is None when
    the item has none."""
    if len(toks) > 2 and toks[1][0] == "op" and (toks[1][1] == "=>" and toks[0][0] in ("word", "lit", "sym", "num")
                                                  or toks[1][1] == ":" and toks[0][0] in ("word", "lit", "num")
                                                  or toks[1][1] == "=" and toks[0][0] == "word"):
        return toks[0], toks[2:]
    return None, toks


def top_level(shape: str) -> str:
    """A line's shape with what its brackets hold blanked out: what it says at its own level."""
    out, depth = [], 0
    for ch in shape:
        if ch in ")]}":
            depth = max(0, depth - 1)
        out.append(ch if not depth else " ")
        depth += ch in "([{"
    return "".join(out)


def squash(name: str) -> str:
    """A name as qualifiers compare: `Legacy`, `legacy`, `LegacyHelpers` and `legacy_helpers` alike."""
    return re.sub(r"[_$-]", "", name).lower()


class FileCheck:
    """The guard's reading of one edited file: what the unit removes from it, and whether every deleted and changed
    line follows from that."""

    def __init__(self, path: str, head: list, work: list, found: list, applied: list, deleted: set,
                 catalog: Catalog):
        self.path, self.head, self.work, self.found, self.deleted = path, head, work, found, deleted
        self.catalog = catalog
        self.src = src = Source(head, path)
        self.s = src.suffix
        # `import os` written in a docstring or a comment is no statement.
        self.stmts = [st for st in statements(src) if not src.carried[st[0] - 1]]
        self.stmt_at = {k: st for st in self.stmts for k in range(st[0], st[1] + 1)}
        # A candidate on an import or export line (an unused re-export) is an item of it, which the rules for
        # those lines judge; every other one is a declaration, deleted whole.
        self.mine = [c for c in applied if c["file"] == path and c["kind"] != "file" and isinstance(c.get("line"), int)
                     and not isinstance(c.get("line"), bool) and 0 < c["line"] <= len(head)
                     and c["line"] not in self.stmt_at]
        self.spans = [extent(src, c["line"], term_of(c)) for c in self.mine]
        # The names this file may lose: its own removed declarations, and those whose verifiers listed it; and what
        # may qualify each one (`views.stale`, `Legacy::Stale`): its type for a member, else its module or folder.
        self.names, self.owners, local = set(), defaultdict(set), set()
        for c in applied:
            term = term_of(c)
            if term and (c["file"] == path or any(e["file"] == path for e in c.get("also_edit", []))):
                self.names.add(term)
                parts = re.split(r"\.|::|#", c["symbol"].split("(", 1)[0])
                self.owners[term] |= {squash(parts[-2])} if len(parts) > 1 else \
                    {squash(stem_term(c["file"])), squash(posixpath.basename(posixpath.dirname(c["file"])))}
                if len(parts) == 1 or c["file"] == path:
                    local.add(term)
        # Names of members declared in other files only: there a bare `admin` is a namesake, never LegacyUser.admin.
        self.foreign = self.names - local
        self._openers = None
        self.terms = {term_of(c) for c in self.mine} - {""}
        # A declaration line that also declares what the unit keeps is no span: only its removed items may be cut
        # out of it, and its comments and decorators, which belong to the whole line, stay.
        self.crowded = {}
        for c in self.mine:
            other = self.crowded_by(c)
            if other:
                self.crowded[c["line"]] = other
        whole = [span for c, span in zip(self.mine, self.spans) if c["line"] not in self.crowded]
        types = []
        for c in self.mine:
            if c["kind"] in ("class", "type") and c["line"] not in self.crowded:
                m = TYPE_WORD.search(src.code[c["line"] - 1])
                types.append((term_of(c), m.group(1) if m else "", indent_of(head[c["line"] - 1]),
                              enclosing(src, c["line"])))
        self.planned = {k for a, b in whole + wrappers(src, whole, types) for k in range(a, b + 1)}
        self.sites = sorted({e["line"] for c in applied for e in c.get("also_edit", [])
                             if e["file"] == path and isinstance(e.get("line"), int)})
        self.info = {st: parse_statement(" ".join(src.text[k - 1].strip() for k in range(st[0], st[1] + 1)), self.s,
                                         indent_of(head[st[0] - 1]) > 0) for st in self.stmts}
        imports = {k for st, (kind, _, _) in self.info.items() if kind in ("import", "side")
                   for k in range(st[0], st[1] + 1)}
        # Uses are read in code only; mentions also in strings where a string can name code, never in comments.
        views = 0 if self.s in STATIC_NAMES else 1
        self.uses, self.mentions = defaultdict(set), defaultdict(set)
        for k in range(1, len(head) + 1):
            for w in set(tokens(src.code[k - 1])):
                self.uses[w].add(k)
            if k not in imports:
                for w in set(tokens((src.code, src.text)[views][k - 1])):
                    self.mentions[w].add(k)
        # What the removal leaves: an import may count as unused only when none of its names is left anywhere in
        # the file, comments and strings included, since a misread comment may hide a live use. Where the compiler
        # rejects an import still in use (Go, Rust, Java...), code alone counts (a Go `json:"name"` tag is no use).
        self.after = set(tokens("\n".join(lex(work, path)[0] if views == 0 else work)))
        self.removed = {}  # line: text, of the lines deleted outright (not put back, possibly rewritten)

    def importable(self, name: str) -> bool:
        """Whether an import of `name` may go: a removed name, or one only the removed code used, read on HEAD in
        code (a mention in a comment or a string of the removed code is no use); either way gone from the file."""
        only_removed = bool(self.uses.get(name, set()) & self.planned) and \
            not self.mentions.get(name, set()) - self.planned
        return (name in self.names or only_removed) and name not in self.after

    def import_item_ok(self, st: tuple, name: str, bound: str) -> bool:
        if st and self.s in (".py", ".pyi") and self.src.text[st[0] - 1].lstrip().startswith("from"):
            module = self.info[st][2]
            sub = module_files(module + ("" if module.endswith(".") else ".") + name, self.s, self.path, self.catalog)
            if sub:  # `from app import signals` loads a module: it may go only with that module
                return sub <= self.deleted
        return self.importable(bound)

    def check(self) -> list:
        src, problems = self.src, []
        gone, regions, layout, shift = {}, [], [], 0
        for first, dels, adds in self.found:
            base = dels[0][0] if dels else first + 1  # the old line the hunk starts at, or comes before
            ops = twin_opcodes([t for _, t in dels], adds)
            layout.append((base, dels, ops))
            for op, i1, i2, j1, j2 in ops:
                if op != "equal":  # a line deleted and added back unchanged, in order, is no change
                    gone.update(dels[i1:i2])
                    regions.append((base + i1, dels[i1:i2], adds[j1:j2], base + shift + j1))
            shift += len(adds) - len(dels)
        self.removed = dict(gone)
        rewritten, made = {}, {}  # old line: its new text; new line: the old line it rewrites
        for at, olds, news, new_at in regions:
            pos = 0
            for x, new in enumerate(news):
                if not new.strip() and not HIDDEN_BREAK.search(new):
                    continue  # a blank line, judged where it stands (`layout_problems`)
                # A changed line outside the planned declarations may only lose items that name removed code.
                k = next((y for y in range(pos, len(olds)) if olds[y][0] not in self.planned
                          and self.rewrite_ok(olds[y][0], olds[y][1], new)), None)
                if k is None:  # the unit fails: the rest is not compared, so that a rewritten file costs one pass
                    return problems + [f"{self.path}:{at} " + ("adds a line break git does not see (a form feed, "
                                                               "U+2028 or a lone CR)" if HIDDEN_BREAK.search(new)
                                                               else "adds or rewrites code")]
                rewritten[olds[k][0]] = new
                made[new_at + x] = olds[k][0]
                gone.pop(olds[k][0], None)
                pos = k + 1
        for n, new in rewritten.items():  # a dropped comma: the line must now be the last item of its list
            if src.code[n - 1].rstrip().endswith(",") and new.rstrip() == self.head[n - 1].rstrip()[:-1]:
                below = next((src.shape(k).strip() for k in range(n + 1, len(self.head) + 1)
                              if src.shape(k).strip() and k not in gone), "")
                if not below.startswith((")", "]", "}")):
                    problems.append(f"{self.path}:{n} drops the comma between two items that stay")
        for n in sorted(set(gone) | set(rewritten)):
            if hidden_code(self.head[n - 1]):
                problems.append(f"{self.path}:{n} deletes a line that holds a line break git does not see, with "
                                "code after it")
        problems += self.layout_problems(layout, made)
        accepted = self.served(gone)
        source = self.s in SOURCE_EXTS
        for n in sorted(gone):
            if n in accepted or n in self.planned or n in self.crowded:
                continue
            if not gone[n].strip():  # a blank line: harmless where no string, comment or heredoc holds it
                if not source or src.carried[n - 1]:
                    problems.append(f"{self.path}:{n} deletes a blank line inside a string, a comment or a heredoc"
                                    if source else f"{self.path}:{n} deletes a blank line from a file whose strings "
                                    "this script cannot read")
                continue
            d = declared(gone[n])
            problems.append(f"{self.path}:{n} deletes " + (f"`{d[1]}`, which this unit does not remove"
                                                           if d and d[1] not in self.names else
                                                           "code outside the planned declarations"))
        crowded = set()
        for c, (a, b) in zip(self.mine, self.spans):
            n, term = c["line"], term_of(c)
            if n in self.crowded and n not in self.planned:  # unless another removed declaration holds it
                if n in gone and n not in crowded:
                    problems.append(f"{self.path}:{n} also declares {self.crowded[n]}, which this unit does not "
                                    f"remove: only `{term}` may be cut out of the line")
                elif n not in gone and term in tokens(rewritten.get(n, self.head[n - 1])):
                    problems.append(f"{self.path}:{n} declares `{term}`, which this unit removes, but it stayed")
                crowded.add(n)
                continue
            kept = next((k for k in range(a, b + 1) if src.text[k - 1].strip() and k not in gone), None)
            if kept:
                problems.append(f"{self.path}:{kept} belongs to `{term}`, which this unit removes, but it "
                                "stayed: a removal deletes the whole declaration")
        return problems

    def layout_problems(self, layout: list, made: dict) -> list:
        """Where adding or deleting a line changes code by the layout alone: next to a line that a trailing
        backslash joins to the next one (C and its macros, the shells and Python splice them, comments included:
        deleting the blank line under `// C:\\temp\\` joins the next statement to the comment, adding one frees
        what the comment swallowed), and a blank line added inside a string, a comment or a heredoc, or to a file
        whose strings this script cannot read."""
        src, head, work = self.src, self.head, self.work
        n_old = len(head) - (head[-1] == "")
        seq, pos = [], 1  # the new file's lines as the old line each one keeps or rewrites, None for a line added
        for base, dels, ops in layout:
            seq += range(pos, base)
            for op, i1, i2, j1, j2 in ops:
                if op == "equal":
                    seq += [dels[i][0] for i in range(i1, i2)]
                else:
                    seq += [made.get(len(seq) + 1 + y) for y in range(j2 - j1)]
            pos = base + len(dels)
        seq += range(pos, n_old + 1)
        if len(seq) != len(work) - (work[-1] == ""):
            return [f"{self.path}: its lines could not be paired with the committed ones, so its changes cannot be "
                    "checked"]
        joined = {k for k in range(1, n_old) if head[k - 1].rstrip().endswith("\\")}  # line k goes on at k + 1
        source, last = self.s in SOURCE_EXTS, 0
        for i, k in enumerate(seq):
            nxt = seq[i + 1] if i + 1 < len(seq) else -1
            joins = nxt != -1 and work[i].rstrip().endswith("\\")
            if joins and not (k in joined and nxt == k + 1) or k in joined and not (joins and nxt == k + 1) \
                    or k and k - 1 in joined and not (i and seq[i - 1] == k - 1):
                return [f"{self.path}:{k or last + 1} changes the line that a backslash at the end of a line joins "
                        "to it"]
            if k:
                last = k
            elif not work[i].strip() and (not source or last < n_old and src.carried[last]):
                return [f"{self.path}:{last + 1} adds a blank line inside a string, a comment or a heredoc" if source
                        else f"{self.path}:{last + 1} adds a blank line to a file whose strings this script cannot "
                        "read"]
        return []

    def served(self, gone: dict) -> set:
        """The deleted lines outside the planned declarations that served them, each one on its own: imports and
        exports of what goes, list entries and link lines naming it, prototypes, statements that register it at a
        listed site, and the comments that document one of those."""
        src = self.src
        accepted = set()
        for st in self.stmts:
            first, last = st
            lines = [k for k in range(first, last + 1) if src.text[k - 1].strip() and k not in self.planned]
            hit = [k for k in lines if k in gone]
            if not hit:
                continue
            if len(hit) == len(lines):  # the whole statement goes: it is judged as one
                if self.statement_served(st):
                    accepted.update(range(first, last + 1))
            elif first < last:  # some items of a multi-line statement go
                accepted.update(k for k in hit if first < k < last and self.item_line_served(st, k))
        rest = sorted(n for n, t in gone.items() if t.strip() and n not in self.planned and n not in self.stmt_at
                      and n not in self.crowded)
        code = [n for n in rest if src.text[n - 1].strip()]
        for n in code:
            if self.prototype(n) or not declared(self.head[n - 1]) and (self.list_entry(n) or self.link_line(n)):
                accepted.add(n)
        # Statements over several lines, first with the lines already accepted alone (`component: LegacyPage,` in a
        # route object), then without them (a registration under a deleted entry).
        for first, last in self.statement_runs(code, gone):
            if first < last and (self.registration(first, last) or self.list_entry(first, last)):
                accepted.update(range(first, last + 1))
        for first, last in self.statement_runs([n for n in code if n not in accepted], gone):
            if self.registration(first, last) or first < last and self.list_entry(first, last):
                accepted.update(range(first, last + 1))
        for n in reversed(rest):  # bottom up: a comment above another one goes with it
            if n not in accepted and not src.text[n - 1].strip() and self.comment_served(n, gone, accepted):
                accepted.add(n)
        return accepted

    def comment_served(self, n: int, gone: dict, accepted: set) -> bool:
        """Whether the comment at line n went with what it documents: the next line that is not blank, deleted
        for a reason (or, at the end of the file, the line above it). A comment whose next line stays documents or
        annotates that line; a directive or an annotation never goes on its own."""
        raw = self.head[n - 1]
        if FILE_DIRECTIVE.match(raw) or DIRECTIVE_COMMENT.match(raw):
            return False
        k = next((k for k in range(n + 1, len(self.head) + 1) if self.head[k - 1].strip()), None) or \
            next((k for k in range(n - 1, 0, -1) if self.head[k - 1].strip()), None)
        return k is not None and k in gone and (k in accepted or k in self.planned)

    def statement_served(self, st: tuple) -> bool:
        """An import or export statement deleted whole: it imports or re-exports a deleted module, or binds only
        names that go, or hands on only removed names."""
        first, last = st
        if re.search(r";\s*\S", " ".join(self.src.code[k - 1].strip() for k in range(first, last + 1))):
            return False  # a second statement shares its line
        kind, items, module = self.info[st]
        if not kind:
            return False
        files = module_files(module, self.s, self.path, self.catalog)
        if kind in ("import", "side", "export") and files and files <= self.deleted:
            return True
        if kind == "side":
            return False  # it runs code when loaded
        if kind == "export":
            return bool(items) and all(a in self.names or b in self.names for a, b in items)
        if kind == "mod":  # `mod x;` loads a file: it goes with that file, never with a declaration named x
            return bool(items) and all(rust_mod_files(self.path, b) & self.deleted for _, b in items)
        if kind == "mixin":
            return bool(items) and all(b in self.names for _, b in items)
        if items is None:
            return self.s in COMPILE_CHECKED
        return bool(items) and all(self.import_item_ok(st, a, b) for a, b in items)

    def item_line_served(self, st: tuple, k: int) -> bool:
        """Line k of a multi-line import or export statement, deleted while its brackets stay: every item on it
        goes."""
        kind, _, module = self.info[st]
        if kind not in ("import", "side", "export") or ";" in self.src.code[k - 1]:
            return False
        files = module_files(module, self.s, self.path, self.catalog)
        if files and files <= self.deleted:
            return True
        shape, text = self.src.shape(k), self.src.text[k - 1]
        pieces = [text[a:b] for a, b in split_spans(shape) if shape[a:b].strip()]
        return bool(pieces) and all(self.item_ok("export" if kind == "export" else "import", st, p) for p in pieces)

    def item_ok(self, kind: str, st, text: str) -> bool:
        """Whether one item of an import or export list may go: in an import, what it binds may; in an export, it
        hands on a removed name."""
        pairs = item_names(text, self.s, kind)
        if not pairs:
            return False
        if kind == "export":
            return all(a in self.names or b in self.names for a, b in pairs)
        return all(self.import_item_ok(st, a, b) for a, b in pairs)

    def rewrite_ok(self, n: int, old: str, new: str) -> bool:
        """Whether line n (outside the planned declarations) came back as `new` only by losing what named removed
        code: a separator next to a deleted entry; in an import or export statement, whole items free to go;
        elsewhere, at a line a verifier listed, whole items of a list or of a call's arguments that name removed
        code; in a line that also declares live names (`crowded`), only the items it removes. A line inside a
        string, a comment or a heredoc never changes."""
        if hidden_code(old) or old[:len(old) - len(old.lstrip())] != new[:len(new) - len(new.lstrip())] \
                or self.src.carried[n - 1]:
            return False  # a re-indented line changes what it belongs to
        if n in self.crowded:
            return self.declarators_cut(n, old, new)
        if self.separator_fix(n, old, new):
            return True
        st = self.stmt_at.get(n)
        kind = self.info[st][0] if st else ""
        kind = kind if kind in ("import", "export") else ""
        if not kind and n not in self.sites:
            return False  # outside imports and exports, only a line a verifier listed loses items
        if kind and self.collapsed(st, kind, old, new):
            return True
        cuts = deletion_cuts(old, new)
        if not cuts:
            return False
        return all(any(self.cut_ok(n, st, kind, i, j) for i, j in placements(old, cuts, x)) for x in range(len(cuts)))

    def cut_ok(self, n: int, st, kind: str, i: int, j: int) -> bool:
        """Whether columns i..j of line n are whole items of a list and one separator, each item free to go, never
        a name without the alias it binds (`, strictAuth` out of `allowAll, strictAuth as guard` would hand guard to
        allowAll). Outside import and export statements, the list is a list literal, an object or a call's
        arguments (`in_list`), each item names removed code (`entry`), and no `;` goes."""
        shape, text = self.src.shape(n), self.src.text[n - 1]
        body = shape[i:j].strip()
        if not body or not kind and (";" in body or not self.in_list(n, i)):
            return False
        lead, trail = body.startswith(","), body.endswith(",")
        core = body[1 if lead else 0:len(body) - 1 if trail else len(body)].strip()
        if not core or (lead and trail) or core[0] == "," or core[-1] == "," or net(core) != 0:
            return False
        before, after = shape[:i].rstrip(), shape[j:].lstrip()
        b, a = before[-1:], after[:1]
        listed = (st is not None and st[0] < n < st[1]) or bool(self.src.contexts[n - 1] and self.src.contexts[n - 1][1])
        opener = b in ("(", "[", "{") or (not b and listed) or LIST_START.search(text[:i]) is not None \
            or self.command(n) == i
        if lead:  # `a, stale`: the list goes on after the cut only with a closer, a separator or its end
            if not b or b in "([{,":
                return False
            if a not in ("", ")", "]", "}", ",", ";") and not re.match(r"from\b", after):
                return False
        elif trail:  # `stale, a`
            if not (opener or b == ",") or a == ",":
                return False
        elif not opener or a not in ("", ")", "]", "}", ";"):  # the only item
            return False
        x, y = i, j
        while x < y and shape[x].isspace():
            x += 1
        while y > x and shape[y - 1].isspace():
            y -= 1
        x, y = x + (1 if lead else 0), y - (1 if trail else 0)
        code = self.src.code[n - 1]
        return all(shape[x + a0:x + b0].strip() and (self.item_ok(kind, st, text[x + a0:x + b0].strip()) if kind else
                                                     self.entry(code[x + a0:x + b0], text[x + a0:x + b0]))
                   for a0, b0 in split_spans(shape[x:y]))

    def in_list(self, n: int, i: int) -> bool:
        """Whether column i of line n sits right inside a list literal, an object or a dict, or a call's arguments:
        never a block (`{ requireMfa(); }`), a tuple or other parentheses (`("admin", stale)` would become the string
        "admin"), parameters or a subscript."""
        src = self.src
        open_ = []
        for k, ch in enumerate(src.code[n - 1][:i]):
            if ch in "([{":
                open_.append(k)
            elif ch in ")]}" and open_:
                open_.pop()
        if not open_ and 0 <= self.command(n) <= i:
            return True  # the arguments of a call without parentheses: `before_action :stale, :require_admin`
        where = (n, open_[-1]) if open_ else self.opener(n)
        return bool(where) and self.bracket_kind(*where) in ("list", "call")

    def bracket_kind(self, line: int, col: int) -> str:
        """What the bracket at column col of a line opens: "list" (a list literal, an object, a dict), "call" (a
        call's arguments, a class's parents), "tuple" (Python parentheses that are no call), or "" (a block, a
        declaration's parameters, a subscript, other parentheses)."""
        src = self.src
        code = src.code[line - 1]
        above = next((src.code[k - 1].rstrip() for k in range(line - 1, 0, -1) if src.code[k - 1].strip()), "")
        before = code[:col].rstrip() or above
        word = re.search(r"[\w$]+$", before)
        called = bool(re.search(r"[\w$)\]]$", before)) and not (word and word.group(0) in NOT_CALLED)
        if code[col] == "(":
            found = declared(src.head[line - 1])
            if found and word and word.group(0) == found[1] and not re.match(r"\s*(?:\w+\s+)*class\s", code):
                return ""
            return "call" if called else "tuple" if self.s in (".py", ".pyi") else ""
        if code[col] == "[":
            return "" if called else "list"
        ctx = bracket_contexts([above, code[:col + 1], ""], self.s)[2]
        return "list" if ctx and ctx[1] else ""

    def command(self, n: int) -> int:
        """Where the arguments start when line n is a Ruby or Elixir call without parentheses (`before_action
        :stale, only: [:show]`, `private :stale`), else -1."""
        m = RUBY_CALL.match(self.src.text[n - 1]) if self.s in SYMBOLS else None
        return m.end() if m and m.group(1) not in CONTROL_WORDS | NOT_CALLED else -1

    def opener(self, n: int):
        """(line, column) of the innermost bracket still open where line n starts, or None; read once per file."""
        if self._openers is None:
            self._openers, stack = [], []
            for k, code in enumerate(self.src.code, 1):
                self._openers.append(stack[-1] if stack else None)
                for col, ch in enumerate(code):
                    if ch in "([{":
                        stack.append((k, col))
                    elif ch in ")]}" and stack:
                        stack.pop()
        return self._openers[n - 1]

    def enum_body(self, n: int) -> bool:
        """Whether line n sits right inside the braces of an enum."""
        where = self.opener(n)
        if not where or self.src.code[where[0] - 1][where[1]] != "{":
            return False
        before = self.src.code[where[0] - 1][:where[1]]
        if not before.strip():
            before = next((self.src.code[k - 1] for k in range(where[0] - 1, 0, -1) if self.src.code[k - 1].strip()), "")
        return re.search(r"\benum\b", before) is not None

    def collapsed(self, st: tuple, kind: str, old: str, new: str) -> bool:
        """`use a::{b, stale};` rewritten to `use a::b;`, `from m import (a, stale)` to `from m import a`: the
        group's brackets go with all its other items, when every one of them may go."""
        for pattern in COLLAPSE:
            m = pattern.match(old)
            if not m:
                continue
            items = [x.strip() for x in m.group("items").split(",") if x.strip()]
            for keep in items:
                if new.rstrip() == (m.group("head") + keep + m.group("tail")).rstrip():
                    others = [x for x in items if x != keep]
                    return bool(others) and all(self.item_ok(kind, st, x) for x in others)
        return False

    def separator_fix(self, n: int, old: str, new: str) -> bool:
        """`a: 1,` -> `a: 1` next to a deleted entry, or `RED,` -> `RED;` when an enum's last constant goes: a comma
        only, inside a list, an object, an enum or an import or export statement, where it ends no statement. A `;`
        never goes (a JavaScript `a;` guards the next line), nor a comma inside other Python parentheses
        (`("admin",)` is a tuple, `("admin")` a string)."""
        a, b = old.rstrip(), new.rstrip()
        swap = b == a[:-1] + ";"
        src = self.src
        if not a.endswith(",") or not (b == a[:-1] or swap) or src.depth[n - 1] <= 0 \
                or net(src.code[n - 1]) != 0 or not src.code[n - 1].rstrip().endswith(","):
            return False
        ctx, enum, st = src.contexts[n - 1], self.enum_body(n), self.stmt_at.get(n)
        names = st is not None and st[0] < n < st[1] and self.info[st][0] in ("import", "export")
        if swap and not enum or not (names or ctx and ctx[1] or enum) \
                or not names and ctx and ctx[0] == "(" and self.s in (".py", ".pyi"):
            return False
        above = next((k for k in range(n - 1, 0, -1) if self.head[k - 1].strip()), None)
        below = next((k for k in range(n + 1, len(self.head) + 1) if self.head[k - 1].strip()), None)
        return above in self.removed or below in self.removed

    def crowded_by(self, c: dict) -> str:
        """What else the declaration line of candidate c declares, that the unit keeps, or "": the type a one-line
        enum or class member sits in (`enum Flag { Live, OldA }`), another declarator (`const stale = 1, live =
        2;`, `int stale, live;`, `STALE = LIVE = 0`, `attr_reader :live, :stale`), a destructuring, a second
        statement. Deleting such a line whole deletes live code."""
        n = c["line"]
        found = declared(self.head[n - 1])
        if found and found[1] != term_of(c) and found[1] not in self.terms:
            return f"`{found[1]}`"
        flat = top_level(self.src.shape(n))
        python = self.s in (".py", ".pyi", ".rb", ".cr")
        while not python:  # `<...>` against a name holds a type's parameters: `Map<String, Integer> stale`
            bare = re.sub(r"(?<=[\w$])<[^<>=;]*>", lambda m: " " * len(m.group(0)), flat)
            if bare == flat:
                break
            flat = bare
        body = flat.strip()
        if self.s in (".py", ".pyi") and re.match(r"(?:async\s+)?(?:def|class)\b", body):
            return ""  # what follows its colon on the line (`def f(): a; b`) is its own body
        if re.search(r";\s*\S", body):
            return "a second statement"
        if not body or TYPE_OR_FUNCTION.match(body):
            return ""
        if DESTRUCTURES.match(body) and ASSIGN.search(body):
            return "the other names it destructures"
        if python:  # the targets: `A = B = 0`, `a, b = 1, 2`; with no `=`, the names a call declares
            parts = ASSIGN.split(body)
            pieces = [p for t in (parts[:-1] if len(parts) > 1 else parts) for p in t.split(",")
                      if not re.match(r"\s*(?:[\w?!]+:\s|\S+\s*=>)", p)]  # not an option: `class_name: "X"`
        elif body.endswith(",") and re.match(r"(?:export\s+)?(?:const|let|var|val)\b", body):
            return "the declarators on the lines below it"
        else:
            pieces = [ASSIGN.split(p, 1)[0] for p in body.split(",")]
        pieces = [p for p in pieces if WORD.search(p)]
        for p in pieces if len(pieces) > 1 else ():
            words = [w.lstrip("$") for w in WORD.findall(p)]
            if not set(words) & self.terms:  # its name: Go writes the type after the last one (`a, b int`)
                return f"`{words[0] if self.s == '.go' and p is pieces[-1] else words[-1]}`"
        return ""

    def declarators_cut(self, n: int, old: str, new: str) -> bool:
        """Whether a line that also declares live names (`crowded`) lost only the items the unit removes: a
        declarator (`stale = 1`), an enum member, an attribute symbol (`:stale`), each with one comma, or the only
        member of its brackets. The line's keywords, its type and its other items stay."""
        cuts = deletion_cuts(old, new)
        if not cuts:
            return False
        terms, shape = {term_of(c) for c in self.mine if c["line"] == n}, self.src.shape(n)

        def item(i, j):
            body = shape[i:j].strip()
            lead, trail = body.startswith(","), body.endswith(",")
            core = body[1 if lead else 0:len(body) - 1 if trail else len(body)].strip()
            if not core or ";" in body or "," in top_level(core) or net(core) != 0:
                return False
            before, after = shape[:i].rstrip(), shape[j:].lstrip()
            if lead == trail:  # no comma: the only member of its brackets (`enum Flag { OldA }`)
                if lead or not (before.endswith(("{", "(", "[")) and after.startswith(("}", ")", "]"))):
                    return False
            elif lead and (not before or before[-1] in "([{,") or trail and (not after or after[0] in ",;)]}"):
                return False
            target = ASSIGN.split(top_level(core), 1)[0]
            words = WORD.findall(target)
            return bool(words) and words[0].lstrip("$") in terms and \
                not re.sub(r"[\s*&$:]", "", target[:target.find(words[0])])
        return all(any(item(i, j) for i, j in placements(old, cuts, x)) for x in range(len(cuts)))

    def value(self, toks: list) -> str:
        """What one value (tokens, its key set aside) names: "ref" (removed code by name: `stale`, `views.stale`,
        `...stale`, `::stale`, `Stale::class`), "call" (a call of removed code passing literals only: `stale()`), "data"
        (removed code by its own string or symbol: `"stale"`, `:stale`), "wrap" (a call of live code passing removed
        code beside a literal key or route: `path("old/", stale)`), "group" (see `group`), "lit" (a literal, or a
        list of literals), "sym" (a symbol of something else), or "" (anything live). A name names removed code
        when its qualifier, if any, is that code's own type or module: `user.admin` is no `LegacyUser.admin`."""
        while len(toks) > 1 and toks[0][0] == "op" and toks[0][1] in ("...", "*", "**", "&", "::", "\\"):
            toks = toks[1:]  # a spread, a pointer, a function reference (`::stale`), a global name (`\App\Stale`)
        if not toks:
            return ""
        if len(toks) == 2 and toks[0][1] in ("-", "+") and toks[1][0] == "num":
            return "lit"
        if len(toks) == 1 and (toks[0][0] in ("lit", "num", "sym") or toks[0][1] in LITERAL_WORDS):
            kind, tok = toks[0][:2]
            if kind == "lit":
                m = re.fullmatch(r"""(["'`])([\w$-]+)\1""", tok)  # the whole literal, its quotes on this line
                return "data" if m and m.group(2) in self.names - self.foreign else "lit"
            if kind == "sym":
                return "data" if tok in self.names else "sym"
            return "lit"
        if toks[0][0] == "op" and toks[0][1] in OPENERS:
            return self.group(toks[1:-1])[0] if closer(toks, 0) == len(toks) - 1 else ""
        chain, i = [], 0
        while i < len(toks) and toks[i][0] == "word":
            chain.append(toks[i][1].lstrip("$"))
            i += 1
            if i + 1 < len(toks) and toks[i][0] == "op" and toks[i][1] in QUALIFIERS and toks[i + 1][0] == "word":
                i += 1
                continue
            break
        if not chain:
            return ""
        if len(chain) > 1 and chain[-1] == "class":  # `Stale::class`, `Stale.class`
            chain = chain[:-1]
        named = chain[-1] in self.names and (squash(chain[-2]) in self.owners[chain[-1]] if len(chain) > 1
                                             else chain[-1] not in self.foreign)
        if i == len(toks):
            return "ref" if named else ""
        if toks[i][1] != "(" or closer(toks, i) != len(toks) - 1:
            return ""
        inner, literals = self.group(toks[i + 1:-1])
        if named:
            return "call" if inner == "lit" else ""
        if any(w in self.names for w in chain):
            return ""  # a member of removed code, or of a namesake: `legacy.middleware()`, `user.stale(x)`
        return "wrap" if inner == "group" and literals else ""

    def group(self, toks: list) -> tuple:
        """(class, literals) for what a list, a tuple, an object or an argument list holds: "group" when it names
        removed code beside literals and keyed literals only (`("old", stale)`, `{ path: "/old", page: Stale }`),
        or, when it names it by strings or symbols, beside nothing else (`["stale", "billing"]` keeps billing);
        "lit" when it holds literals only; "" when it holds live code. `literals`: how many literal items."""
        refs = datas = literals = 0
        for item in split_items(toks):
            c = self.value(keyed(item)[1])
            if c in ("ref", "call", "wrap", "group"):
                refs += 1
            elif c == "data":
                datas += 1
            elif c in ("lit", "sym"):
                literals += 1
            else:
                return "", 0
        if refs:
            return "group", literals
        return ("group" if datas and not literals else "" if datas else "lit"), literals

    def entry(self, code: str, text: str, calls: bool = True) -> bool:
        """Whether one entry of a list, an object or an argument list names removed code as its value, with nothing
        live beside it: `stale`, `views.stale`, `"stale"`, `:stale`, `legacy: legacyHandler`, `("old", stale)`, and
        where `calls`, `stale()` and `path("old/", stale)`. A key never names it (`admin: true`, `secure=True`)."""
        c = self.value(keyed(code_tokens(code, text, self.s in SYMBOLS))[1])
        return c in ("ref", "data", "group") or calls and c in ("call", "wrap")

    def list_entry(self, n: int, end: int = 0) -> bool:
        """Lines n..end (n alone by default) as entries of a list, a dict, an object literal or an argument list that
        only name removed code (see `entry`): `"stale",` in `__all__`, `legacy: legacyHandler,`, `path("old/",
        old_view),` on one line or several. Never a statement of a block, a line inside a string or a comment (`WHERE
        status <> 'banned'`), nor a line that goes on the item above it (`"a" +`, two strings one after the other)."""
        src, end = self.src, end or n
        ctx = src.contexts[n - 1]
        shape = " ".join(src.shape(k) for k in range(n, end + 1))
        body = shape.strip()
        if any(src.carried[k - 1] for k in range(n, end + 1)) or not ctx or not ctx[1] or not body \
                or net(body) != 0 or ";" in body or len(body) > 4000:
            return False
        kind = self.bracket_kind(*self.opener(n)) if self.opener(n) else ""
        if not (kind in ("list", "tuple") or kind == "call" and any(n <= x <= end for x in self.sites)):
            return False  # a call's argument goes only where a verifier listed it: the others would shift
        if body.startswith(","):
            if ctx[0] == "(" and self.s in (".py", ".pyi"):
                return False  # `("admin"` then `, stale)`: the tuple would lose its only comma
        else:
            above = next((src.shape(k).rstrip() for k in range(n - 1, 0, -1) if src.shape(k).strip()), "")
            if not above.endswith((",", "(", "[", "{")):
                return False
        last = not body.endswith(",")
        if last:  # the last entry: the next line closes the list
            nxt = next((src.shape(k).strip() for k in range(end + 1, len(self.head) + 1) if src.shape(k).strip()), "")
            if not nxt.startswith({"(": ")", "[": "]", "{": "}"}[ctx[0]]):
                return False
        code = " ".join(src.code[k - 1] for k in range(n, end + 1))
        text = " ".join(src.text[k - 1] for k in range(n, end + 1))
        pieces = [(a, b) for a, b in split_spans(shape) if shape[a:b].strip()]
        return bool(pieces) and all(self.entry(code[a:b], text[a:b], ctx[0] != "{" or not last) for a, b in pieces)

    def link_line(self, n: int) -> bool:
        """A line that only wires removed names into an export or a visibility list: `module.exports.stale =
        stale;`, `private :stale`, `pub mod legacy;`, `__all__ += ["stale"]`. Every name it lists goes
        (`private :stale, :grant_admin` keeps grant_admin private)."""
        src = self.src
        shape = src.shape(n)
        if src.carried[n - 1] or not LINK_START.match(shape) or net(shape) != 0 \
                or re.search(r";\s*\S", shape.strip()) or len(shape) > 4000:
            return False
        toks = code_tokens(src.code[n - 1], src.text[n - 1], self.s in SYMBOLS)
        toks = toks[:-1] if toks and toks[-1][1] == ";" else toks
        i = 0
        while i < len(toks) and (toks[i][0] == "word" and toks[i][1] in LINK_WORDS or toks[i][1] == "."):
            i += 1
        if 2 <= i < len(toks) and toks[i][0] == "word" and toks[i - 1][1] == "." and toks[i - 2][1] == "exports":
            i += 1  # the name it exports under: `module.exports.legacy = stale`
        if i < len(toks) and toks[i][1] in ("=", "+="):
            i += 1
        items = split_items(toks[i:])
        if len(items) == 1 and items[0][0][1] in OPENERS and closer(items[0], 0) == len(items[0]) - 1:
            items = split_items(items[0][1:-1])  # `= ["stale"]`, `= { stale }`
        return bool(items) and all(self.value(keyed(item)[1]) in ("ref", "data") for item in items)

    def prototype(self, n: int) -> bool:
        """A C or C++ declaration of a removed function, without its body: `int stale(int);`. With the parameter
        types of a definition this unit removes from the file, since another overload may share the name (`int
        area(int);` stays when `int area(double)` goes); with none here, only when the file declares nothing else
        of that name."""
        m = PROTOTYPE.match(self.src.code[n - 1]) if self.s in C_FAMILY else None
        if not (m and m.group(1) in self.names):
            return False
        name = m.group(1)
        mine = [c["line"] for c in self.mine if term_of(c) == name]
        if mine:
            params = c_params(self.src, n, name)
            return params is not None and any(c_params(self.src, k, name) == params for k in mine)
        header = re.compile(r"\s*(?!(?:return|else|case|throw|delete|new|goto|co_return)\b)[\w:<>,*&\s]+?[\s*&]" +
                            re.escape(name) + r"\s*\(")
        return sum(1 for code in self.src.code if header.match(code)) == 1

    def statement_runs(self, lines: list, gone: dict) -> list:
        """The deleted code lines `lines` as statements [first, last], each judged on its own: a statement goes on
        to the next deleted line while its brackets are open, while its line ends with a comma, a backslash or an
        opening bracket, or when the next line starts with `.`, `?.` or a closing bracket, with only blank lines and
        deleted comments between them. Any other line starts the next statement: `before_action :stale` and
        `before_action :require_admin` are two."""
        src, out, depth = self.src, [], 0
        for n in lines:
            if out:
                p = out[-1][1]
                tail, lead = src.code[p - 1].rstrip(), src.code[n - 1].lstrip()
                if (depth > 0 or tail.endswith((",", "\\", "(", "[", "{")) or lead.startswith((".", "?.", ")", "]", "}"))) \
                        and all(not self.head[k - 1].strip() or k in gone and not src.text[k - 1].strip()
                                for k in range(p + 1, n)):
                    out[-1][1] = n
                    depth += net(src.code[n - 1])
                    continue
            out.append([n, n])
            depth = net(src.code[n - 1])
        return out

    def registration(self, first: int, last: int) -> bool:
        """Whether lines first..last, all deleted, are one statement that registers removed code at a site the
        verifiers listed: `app.use(stale);`, `register("legacy", stale)`, `before_action :stale, only: [:show]`,
        `LegacyPlugin.install()`. A call of removed code (`authorize`, `self.check_permissions()`) registers
        nothing, and one that also passes live code (`app.use(stale, csrf())`) may only lose the removed item."""
        src = self.src
        if not any(first <= x <= last for x in self.sites) or declared(self.head[first - 1]) \
                or any(src.carried[k - 1] for k in range(first, last + 1)):
            return False
        code = " ".join(src.code[k - 1] for k in range(first, last + 1))
        if net(code) != 0 or len(code) > 4000:
            return False
        toks = code_tokens(code, " ".join(src.text[k - 1] for k in range(first, last + 1)), self.s in SYMBOLS)
        toks = toks[:-1] if toks and toks[-1][1] == ";" else toks
        chain, i = [], 0
        while i < len(toks) and toks[i][0] == "word":
            chain.append(toks[i][1].lstrip("$"))
            i += 1
            if i + 1 < len(toks) and toks[i][0] == "op" and toks[i][1] in QUALIFIERS and toks[i + 1][0] == "word":
                i += 1
                continue
            break
        if not chain or chain[0] in CONTROL_WORDS or any(w in self.names for w in chain[1:]) \
                or len(chain) == 1 and chain[0] in self.names or any(t[1] == ";" for t in toks):
            return False
        rest = toks[i:]
        if rest and rest[0][1] == "(":
            if closer(rest, 0) != len(rest) - 1:
                return False  # more after the call: `app.use(stale).listen(80)`
            rest = rest[1:-1]
        elif rest and self.s not in SYMBOLS:
            return False  # only Ruby and Elixir call without parentheses: `before_action :stale`
        ok, named = self.registers(rest)
        return ok and (named or chain[0] in self.names - self.foreign)  # `LegacyPlugin.install()`

    def registers(self, toks: list) -> tuple:
        """(ok, named) for the arguments of a registration: each one passes removed code (named), a literal, or an
        option (`only: [:show]`); never live code, a call of live code, or a symbol of something else
        (`before_action :stale, :require_admin` registers require_admin too)."""
        named = False
        for item in split_items(toks):
            key, val = keyed(item)
            c = self.value(val)
            if c in ("ref", "data", "group", "call"):
                named = True
            elif c != "lit" and not (key and c == "sym"):
                return False, False
        return True, named


def stray_deletions(lg: Ledger, u: dict, applied: list, catalog=None) -> list:
    """What a removal unit changed beyond deleting its declarations and the lines that served them."""
    problems = []
    for path in u["deletes"]:
        if run(["git", "diff", "--quiet", "HEAD", "--", path], lg.root, check=False).returncode == 1:
            problems.append(f"{path} was edited, but the orchestrator deletes it")
    deleted = {c["file"] for c in applied if c["kind"] == "file"}
    catalog = catalog or Catalog(lg.root)
    for path in sorted(set(u["allowed"]) - set(u["deletes"])):
        # What git cannot diff line by line is never accepted: the check fails closed.
        blob = run(["git", "cat-file", "blob", f"HEAD:{path}"], lg.root, check=False)
        if blob.returncode != 0:
            problems.append(f"{path} is not in the last commit, so its changes cannot be checked")
            continue
        if not (lg.root / path).is_file():
            problems.append(f"{path} was deleted, but the unit only edits it")
            continue
        if not diffable(blob.stdout):
            problems.append(f"{path} is binary or UTF-16, so its changes cannot be checked line by line")
            continue
        try:
            data = (lg.root / path).read_bytes()
        except OSError:
            data = b"\0"
        head, work = exact_lines(blob.stdout) or [""], exact_lines(data)
        if work is None:
            problems.append(f"{path} is no longer text, so its changes cannot be checked")
            continue
        if blob.stdout.startswith(codecs.BOM_UTF8) != data.startswith(codecs.BOM_UTF8):
            problems.append(f"{path}: its remover added or dropped a byte-order mark, which changes what reads the "
                            "file (a shebang, PHP's output)")
            continue
        problem = unreadable(path, head) if data != blob.stdout else ""
        if problem:
            problems.append(f"{path}: {problem}, so its changes cannot be checked")
            continue
        problem, found = hunks(lg.root, path, head, work)
        if problem:
            problems.append(f"{path}: {problem}, so its changes cannot be checked")
        elif found:
            problems += FileCheck(path, head, work, found, applied, deleted, catalog).check()
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
        try:
            outcome = ingest_removal_unit(lg, u, changed)
        except Exception as err:  # an output this code did not foresee fails its unit, never the whole wave
            outcome = f"its output could not be read ({type(err).__name__}: {clean(err, 120)})"
        if isinstance(outcome, tuple):
            applied, skipped = applied + outcome[0], skipped + outcome[1]
            continue
        fail_unit(lg, u, outcome)
        restores.append(u)
        stray = outcome.startswith("its remover changed")
        rejected += stray
        print(f"{u['id']}: {'rejected' if stray else 'failed'}, {outcome}")
    lg.save()
    print(f"remove wave {wave}: {applied} applied, {skipped} skipped, {rejected} unit(s) rejected")
    if restores:
        for u in restores:
            queue_restore(lg, set(u["allowed"]) | set(u["deletes"]), f"unit {u['id']}'s edits, rejected at ingest: "
                                                                     "the run's own wrong removal")
        lg.save()
    say_next("ledger.py restore, then `ledger.py check`" if restores else "ledger.py check")


def ingest_removal_unit(lg: Ledger, u: dict, changed: set):
    """Record one removal unit's output: (applied, skipped), or why the whole unit fails."""
    result = {}
    if u.get("agent", True):
        try:
            result = read_json(lg.out_path(u["id"], "remove"))
        except (ValueError, RecursionError) as err:
            return f"its remover returned nothing usable ({clean(err, 120)})"
        if not isinstance(result, dict):
            return "its remover returned nothing usable"
    done = {x for x in listed(result, "applied") if isinstance(x, str)}
    why = {s["id"]: clean(s.get("reason", ""), 200) for s in listed(result, "skipped")
           if isinstance(s, dict) and isinstance(s.get("id"), str)}
    covered = u.get("covered", {})
    applied = skipped = 0
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
    files = sorted(set(u["allowed"]) | set(u["deletes"]))
    seen = file_blobs(lg, files)  # what the guard is about to read
    problems = stray_deletions(lg, u, ok)
    if problems:
        return "its remover changed more than it was given: " + "; ".join(clean(p) for p in problems[:3])
    for c in ok:
        if c["kind"] == "file" and (lg.root / c["file"]).exists():
            rm = run(["git", "rm", "-q", "--", c["file"]], lg.root, check=False)
            if rm.returncode != 0:
                set_status(c, "skipped", "git rm failed: " + clean(rm.stderr.decode(errors="replace").strip()))
                blocked_files.add(c["id"])
                skipped += 1
                continue
        set_status(c, "applied")
        applied += 1
    deleted = {c["id"] for c in ok if c["kind"] == "file" and c["id"] not in blocked_files}
    # What the guard accepted, file by file: only this content may be gated and committed as the wave. A file
    # that changed while the guard read it is left out, so that `check` reads it again.
    gone = {c["file"] for c in ok if c["id"] in deleted}
    now_ = file_blobs(lg, files)
    u["checked"] = {p: now_[p] for p in files if now_[p] == seen[p] or p in gone and now_[p] == "-"}
    for cid, fid in covered.items():  # declarations inside a deleted file share its fate
        c = lg.cands[cid]
        if fid in deleted and not (lg.root / c["file"]).exists():
            set_status(c, "applied")
            applied += 1
        else:
            set_status(c, "skipped", "its file was kept")
    # A remover can only empty the files it may edit: whatever else it lists is not its unit's to report.
    for p in listed(result, "emptied_files"):
        p = rel(lg.root, p) if isinstance(p, str) else ""
        if p in u["allowed"] and p not in lg.state["emptied"]:
            lg.state["emptied"].append(p)
    u["status"] = "ingested"
    return applied, skipped


def file_blobs(lg: Ledger, paths: list, rev=None) -> dict:
    """{path: blob} of these paths: in the working tree as `git add` would store them (rev None), in the index
    (rev ""), or in a commit; "-" where the path is absent, "?" where it holds no regular file (a folder, a
    symlink, a submodule, a conflict)."""
    found = {p: "-" for p in paths}
    if rev is None:
        present = []
        for p in paths:
            full = lg.root / p
            try:
                if full.is_symlink() or full.exists() and not full.is_file():
                    found[p] = "?"
                elif full.is_file():
                    present.append(p)
            except OSError:  # a folder on the way that cannot be read
                found[p] = "?"
        # The names go to git as arguments, never one per line: a file name may hold a newline or end in a CR.
        proc = run(["git", "hash-object", "--"] + present, lg.root, check=False) if present else None
        blobs = proc.stdout.decode().split() if proc else []
        if proc and (proc.returncode != 0 or len(blobs) != len(present)):  # one vanished meanwhile: one at a time
            blobs = [run(["git", "hash-object", "--", p], lg.root, check=False).stdout.decode().strip()
                     or ("?" if os.path.lexists(lg.root / p) else "-") for p in present]
        found.update(zip(present, blobs))
    elif paths:
        cmd = ["git", "ls-files", "-s", "-z", "--"] if rev == "" else ["git", "ls-tree", "-z", rev, "--"]
        for entry in run(cmd + list(paths), lg.root, check=False).stdout.decode("utf-8", "replace").split("\0"):
            meta, _, path = entry.partition("\t")
            parts = meta.split()
            if path in found and len(parts) >= 3:
                regular = parts[0] in ("100644", "100755") and (parts[2] == "0" if rev == "" else parts[1] == "blob")
                found[path] = parts[1 if rev == "" else 2] if regular else "?"
    return found


def listed(result: dict, key: str) -> list:
    value = result.get(key) if isinstance(result, dict) else None
    return value if isinstance(value, list) else []


def declaration_gone(before: list, after: list, c: dict) -> bool:
    """Whether `after` lost the candidate against `before`: one copy fewer of its recorded declaration
    line (twins with other text do not count), or, when that line is not in `before` (an earlier wave
    rewrote it), one mention fewer of its name."""
    decl = c.get("decl")
    if decl and any(line.strip()[:200] == decl for line in before):
        def count(lines):
            return sum(1 for line in lines if line.strip()[:200] == decl)
    else:
        term = term_of(c)

        def count(lines):
            return sum(tokens(line).count(term) for line in lines)
    return count(after) < count(before)


def line_deletions(lg: Ledger, spec: list):
    """{old line number: the lines its hunk writes in its place} for each line a one-file diff deletes (`spec` as
    for `git diff`), or None when the diff cannot be read. A line put back unchanged up to trailing blanks or a CR
    is not deleted: a declaration that only changed its line ending is still there. Git leaves those out itself,
    and the few a hunk still holds are paired by count, not by place: linear on any file, and a wrong pairing can
    only keep a line, never delete one."""
    found = parse_diff(run(DIFF + ["--ignore-space-at-eol"] + spec, lg.root, check=False).stdout)
    if found is None:
        return None
    out = {}
    for _, _, _, deleted, added in found:
        back = Counter(twin_key(t) for _, t in deleted) & Counter(twin_key(t) for t in added)
        put, written = Counter(back), []
        for t in added:
            if put[twin_key(t)]:
                put[twin_key(t)] -= 1
            else:
                written.append(t)
        for n, t in deleted:
            if back[twin_key(t)]:
                back[twin_key(t)] -= 1
            else:
                out[n] = written
    return out


def deleted_lines(lg: Ledger, spec: list):
    """The old line numbers a one-file diff deletes (see line_deletions), or None when it cannot be read."""
    found = line_deletions(lg, spec)
    return None if found is None else set(found)


def line_removed(lg: Ledger, c: dict, spec: list, before: list, after: list) -> bool:
    """Whether a one-file diff (`spec` as for `git diff`, from the file's lines `before` to `after`) removes the
    candidate's own line: deletes it, and where its hunk writes other lines in its place (the rest of a list the
    candidate was one item of, a rewritten statement), none of them names the candidate and the file names it
    less often than before (a name moved elsewhere was not removed)."""
    found = line_deletions(lg, spec)
    if not found or c["line"] not in found:
        return False
    written = found[c["line"]]
    if not written:
        return True
    term = term_of(c)
    if not term or any(term in tokens(t, hyphenated=True) for t in written):
        return False

    def count(lines):
        return sum(tokens(line, hyphenated=True).count(term) for line in lines)
    return count(after) < count(before)


def still_declared(lg: Ledger, c: dict) -> bool:
    """Whether the candidate's own declaration survived in the working tree: the file holds as many copies of it
    as HEAD (a twin's deletion does not count), or its line, which plan_remove pointed at in HEAD, is still there
    or was rewritten keeping its name (one item of a list that lost another)."""
    before, after = head_lines(lg, c["file"]), read_lines(lg.root / c["file"]) or []
    if not declaration_gone(before, after, c):
        return True
    return bool(c.get("line")) and not line_removed(lg, c, ["HEAD", "--", c["file"]], before, after)


def unremoved(lg: Ledger, units: list, base: str, rev: str = "") -> list:
    """Applied candidates of these units whose removal `rev` (the index "", or a commit) does not hold, against
    commit `base`: judged as still_declared judges the working tree. A declaration whose file `rev` no longer
    holds was not removed either: the wave never deletes that file (a rename, or a commit hook took it out)."""
    out = []
    for u in units:
        for cid in u["candidates"]:
            c = lg.cands[cid]
            if c["status"] != "applied":
                continue
            held = run(["git", "cat-file", "-e", f"{rev}:{c['file']}"], lg.root, check=False).returncode == 0
            if c["kind"] == "file" or cid in u.get("covered", {}):  # a file, or a declaration that goes with one
                kept = held
            elif not held:
                kept = True
            else:
                before, after = head_lines(lg, c["file"], base), head_lines(lg, c["file"], rev)
                spec = (["--cached", base] if rev == "" else [base, rev]) + ["--", c["file"]]
                kept = not declaration_gone(before, after, c) or \
                    bool(c.get("line")) and not line_removed(lg, c, spec, before, after)
            if kept:
                out.append(c)
    return out


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

def status_entries(lg: Ledger, untracked: bool = True) -> list:
    """(status code, path) for each change in the working tree, minus the ledger and the untracked files
    the run knows (there at init, left by a gate or an analyzer, or listed by `ledger.py ignore`); a change
    to a tracked file always counts. A rename or copy gives both its paths. Inside a submodule, which the
    run never edits, only a moved commit counts."""
    mode = "--untracked-files=all" if untracked else "--untracked-files=no"
    entries = os.fsdecode(run(["git", "status", "--porcelain=v1", "-z", "--ignore-submodules=dirty", mode],
                              lg.root).stdout).split("\0")  # a name that is not UTF-8 round-trips (Ledger.in_head)
    known = set(lg.state.get("untracked", []))
    out, i = [], 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, found = entry[:2], [entry[3:]]
        if ("R" in code or "C" in code) and i < len(entries):  # the source path comes next
            found.append(entries[i])
            i += 1
        if code == "??" and entry[3:] in known:
            continue
        out += [(code, p) for p in found if not in_ledger(p)]
    return out


def changed_paths(lg: Ledger, untracked: bool = True) -> list:
    return [p for _, p in status_entries(lg, untracked)]


def queue_restore(lg: Ledger, paths, cause: str) -> None:
    """Put paths on the restore list, with why each goes back: the saved copy is labelled with it."""
    causes = lg.state.setdefault("restore_causes", {})
    for p in paths:
        causes.setdefault(p, cause)
    lg.state["restore"] = sorted(set(lg.state.get("restore", [])) | set(paths))


def hidden_snapshot(lg: Ledger) -> dict:
    """What `git status` cannot show, to compare after every stage: the ignored paths, with what an ignored file
    holds (file_print) and a fingerprint of an ignored folder (folder_print: a stand-in module planted in .venv or
    node_modules, or in a folder whose own .gitignore says `*`), .git/info/exclude, and the tracked files git is
    told to skip (assume-unchanged, skip-worktree)."""
    out = run(["git", "ls-files", "-o", "-i", "--exclude-standard", "--directory", "-z"], lg.root, check=False).stdout
    listed = {p for p in os.fsdecode(out).split("\0") if p and not in_ledger(p.rstrip("/"))}
    ignored = {}
    for p in sorted(listed):
        full = lg.root / p
        ignored[p] = folder_print(lg.root, p, listed) if full.is_dir() and not full.is_symlink() else file_print(full)
    exclude = run(["git", "rev-parse", "--git-path", "info/exclude"], lg.root, check=False).stdout.decode().strip()
    exclude_path = Path(exclude) if Path(exclude).is_absolute() else lg.root / exclude
    try:
        excluded = digest(exclude_path.read_bytes())
    except OSError:
        excluded = ""
    skipped = {p: file_print(lg.root / p) for p in sorted(set(tracked_files(lg.root)) - lg.tracked())}
    return {"ignored": ignored, "exclude": excluded, "skipped": skipped}


def file_print(full: Path) -> str:
    """What a file holds, as far as a snapshot tells: its digest up to 1 MB, else its size and time (an edit sets
    the time); "-" when it cannot be read. Only a regular file is read: a FIFO would block the command."""
    try:
        st = full.lstat()
        if full.is_file() and not full.is_symlink() and st.st_size <= 1_000_000:
            return digest(full.read_bytes())
        return f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return "-"


# An ignored folder is fingerprinted file by file (size and time) up to this many files. A bigger one (node_modules,
# a full .venv) is fingerprinted by the size and time of each of its folders, which change whenever an entry is added,
# removed or renamed there: a planted module is still seen, an edit inside an existing file no longer is. Either way
# the work is one walk that reads no file: about 0.35 s for 120,000 files in 20,000 folders, 1.1 s for 480,000.
FOLDER_FILES = 20_000


def folder_print(root: Path, top: str, listed: set) -> str:
    """A digest of what an ignored folder holds, leaving out its subfolders git lists on their own (a folder whose
    .gitignore says `*` is listed with its entries): the size and time of each file and the name of each folder,
    or, past FOLDER_FILES files, the size and time of each folder."""
    dirs, files, unread, todo = [], [], [], [top]
    while todo:
        d = todo.pop()
        dirs.append(d)
        try:
            with os.scandir(os.path.join(root, d)) as entries:
                for e in entries:
                    if e.is_dir(follow_symlinks=False):
                        if d + e.name + "/" not in listed:
                            todo.append(d + e.name + "/")
                    elif len(files) <= FOLDER_FILES:
                        files.append(d + e.name)
        except OSError:
            unread.append(f"{d}\tunreadable")
    whole = len(files) <= FOLDER_FILES
    parts = unread + (dirs if whole else [])
    for p in files if whole else dirs:
        try:
            st = os.lstat(os.path.join(root, p))
            parts.append(f"{p}\t{st.st_size}\t{st.st_mtime_ns}")
        except OSError:
            parts.append(f"{p}\t-")
    return digest("\n".join(sorted(parts)).encode("utf-8", "surrogateescape"))


def newest_inside(root: Path, top: str) -> str:
    """The entry of a folder changed last (a file before the folder its writing changed): where to look first."""
    best, when = top, (-1, 0)
    for base, dirs, files in os.walk(os.path.join(root, top)):
        for name, is_file in [(d, 0) for d in dirs] + [(f, 1) for f in files]:
            try:
                t = (os.lstat(os.path.join(base, name)).st_mtime_ns, is_file)
            except OSError:
                continue
            if t > when:
                best, when = os.path.relpath(os.path.join(base, name), root), t
    return best


def follow_tools(lg: Ledger) -> None:
    """After the project's own gate or analyzer ran (never after an agent stage), take what it changed where
    `git status` cannot see, and in the untracked files there before the run, as the new reference: a test
    suite that rewrites its own cache is no stray. Refusing to run a gate while those changed keeps an agent's
    change from being laundered this way; so does keeping the reference while a stage is dispatched, since its
    agents may be writing while the tool runs."""
    if lg.units(status="dispatched"):
        return
    if "hidden" in lg.state:
        lg.state["hidden"] = hidden_snapshot(lg)
    touched = [p for p in user_files_changed(lg) if p not in (lg.state.get("touched_by_tools") or [])]
    if touched:  # said once, and kept for the report: git cannot bring back an untracked file
        lg.state["touched_by_tools"] = sorted(set(lg.state.get("touched_by_tools") or []) | set(touched))
        print(f"warning: the tool that just ran changed or deleted {len(touched)} untracked file(s) there before the "
              f"run (the user's own), e.g. {clean(touched[0])}: tell the user; the report lists them")
    for p in list(lg.state.get("preexisting") or {}):
        try:
            st = (lg.root / p).stat()
            lg.state["preexisting"][p] = [st.st_size, st.st_mtime_ns]
        except OSError:
            del lg.state["preexisting"][p]


def hidden_changes(lg: Ledger) -> list:
    """What changed since the last snapshot where `git status` cannot see it."""
    before = lg.state.get("hidden")
    if not isinstance(before, dict):
        return []
    now_ = hidden_snapshot(lg)
    out = []
    for key, what in (("ignored", "ignored path"), ("skipped", "file git is told to skip")):
        old, new = before.get(key) or {}, now_[key]
        out += [f"{what} {clean(p)} " + ("appeared" if p not in old else "vanished" if p not in new else "changed")
                + (f" (changed last inside it: {clean(newest_inside(lg.root, p))})" if p.endswith("/") and p in new
                   else "")
                for p in sorted(set(old) | set(new)) if old.get(p) != new.get(p)]
    if now_["exclude"] != before.get("exclude"):
        out.append(".git/info/exclude changed")
    return out


def user_files_changed(lg: Ledger) -> list:
    """The untracked files present at init (the user's own work) that changed or vanished since."""
    out = []
    for p, (size, mtime) in sorted((lg.state.get("preexisting") or {}).items()):
        try:
            st = (lg.root / p).stat()
            if (st.st_size, st.st_mtime_ns) != (size, mtime):
                out.append(p)
        except OSError:
            out.append(p)
    return out


def open_removal_units(lg: Ledger) -> list:
    return [u for u in lg.units("remove", "ingested") if u["wave"] == lg.state.get("current_wave")]


def wave_files(lg: Ledger) -> set:
    """The files the open wave may change."""
    return {p for u in open_removal_units(lg) for p in u["allowed"] + u["deletes"]}


def checked_record(lg: Ledger) -> dict:
    """What the guard last accepted for each file of the open wave (see file_blobs): recorded at ingest, and by
    `check` after a change. A file missing here was never checked (a state saved before this record existed)."""
    record = {}
    for u in open_removal_units(lg):
        record.update(u.get("checked") or {})
    return record


def wave_changes(lg: Ledger) -> tuple:
    """The open wave's files whose working tree is not what the guard accepted: (files the wave deletes that are
    back, other files that changed since), each sorted."""
    record, files = checked_record(lg), sorted(wave_files(lg))
    gone = {lg.cands[cid]["file"] for u in open_removal_units(lg) for cid in u["candidates"]
            if lg.cands[cid]["kind"] == "file" and lg.cands[cid]["status"] == "applied"}
    now_ = file_blobs(lg, files)
    back = [p for p in files if p in gone and now_[p] != "-"]
    return back, [p for p in files if p not in back and record.get(p) != now_[p]]


def unchecked_step(lg: Ledger) -> str:
    """A refusal while the open wave's files are not what the guard accepted, else "": no gate may test them and
    no commit take them before `check` has read them again (a gate passed on them would vouch for nothing)."""
    back, changed = wave_changes(lg)
    if back:
        return (f"{', '.join(clean(p) for p in back[:5])}, which this wave deletes, {'is' if len(back) == 1 else 'are'} "
                "back: `ledger.py check` first")
    if changed:
        return (f"this wave's files changed since they were checked ({', '.join(clean(p) for p in changed[:5])}): "
                "`ledger.py check` first, which checks the change against what the wave removes")
    return ""


def recheck(lg: Ledger, paths: list) -> dict:
    """Run the guard again on files of the open wave that changed since it accepted them, as ingest ran it on the
    unit's own edits: record the content it accepts, and return {path: why} for the rest."""
    problems = {}
    for u in open_removal_units(lg):
        mine = sorted(set(paths) & (set(u["allowed"]) | set(u["deletes"])))
        if not mine:
            continue
        # As at ingest: the unit's removals still in the tree (one undone since is no longer the unit's to delete).
        applied = [c for c in (lg.cands[cid] for cid in u["candidates"] if cid not in u.get("covered", {}))
                   if c["status"] == "applied" and (c["kind"] == "file" or not still_declared(lg, c))]
        gone = {c["file"] for c in applied if c["kind"] == "file"}
        catalog = Catalog(lg.root)
        catalog.files().update(gone)  # the modules the wave deletes, as ingest saw them before `git rm`
        seen = file_blobs(lg, mine)
        for p in mine:
            if p in gone:  # deleted as planned (`check` stops before this when it is back)
                found = [] if seen[p] == "-" else [f"{p} is back, but this wave deletes it"]
            elif p in u["deletes"]:  # a file the unit was to delete but kept: it may not change at all
                found = [f"{p} was edited, but this wave keeps it as the last commit has it"] \
                    if run(["git", "diff", "--quiet", "HEAD", "--", p], lg.root, check=False).returncode == 1 else []
            else:
                found = stray_deletions(lg, {"allowed": [p], "deletes": []}, applied, catalog)
            if found:
                problems[p] = found[0]
            elif file_blobs(lg, [p])[p] == seen[p]:  # unchanged while the guard read it
                u.setdefault("checked", {})[p] = seen[p]
    return problems


def cmd_check(args) -> None:
    lg = Ledger(git_root()).load()
    moved = moved_head(lg)
    if moved:
        say_next(moved_step(lg, moved))
        sys.exit(1)
    if lg.units(status="dispatched"):
        die("a stage is still dispatched: its agents may be editing; wait for its workflow, then `ledger.py ingest "
            "<stage>`, which checks what they changed")
    units = open_removal_units(lg)
    allowed = wave_files(lg)
    entries = status_entries(lg)
    unexpected = sorted({(code, p) for code, p in entries if p not in allowed}, key=lambda e: e[1])
    inside = sorted({p for _, p in entries if p in allowed})
    unseen = [f"the untracked file {clean(p)}, there before the run, changed or vanished" for p in user_files_changed(lg)]
    unseen += hidden_changes(lg)
    for line in unseen[:30]:
        print(f"warning: {line}")
    ask = ("these changed where `git status` cannot show them (an agent's plant, or the user's own work): stop and ask "
           "the user; for each change they say is theirs or the project's, `ledger.py ignore \"<path>\"` with the path "
           "as listed (a glob accepts only what it names)")
    if unseen and not unexpected:
        say_next(ask + ", then `ledger.py check` again")
        sys.exit(1)
    if unexpected:
        print(f"{len(unexpected)} change(s) outside the files this step may touch:")
        for code, p in unexpected[:30]:
            print(f"  {code} {clean(p)}")
        back = sorted({p for code, p in unexpected if code != "??"})  # tracked, or added to the index
        links = gitlinks(lg, back)
        back = [p for p in back if p not in links]
        if links:
            print(f"submodule(s) {', '.join(clean(p) for p in sorted(links)[:5])} point at another commit: the run never "
                  "restores a submodule; ask the user")
        new = sorted({p for code, p in unexpected if code == "??"})
        if back:
            queue_restore(lg, back, "changed outside the open wave while the run worked: an agent's stray, "
                                    "or someone's own edit")
            lg.save()
        if unseen:  # their question comes first, and no untracked file is ignored without the user's answer
            say_next(ask + ("; ask about the untracked files listed too" if new else "")
                     + (f"; `ledger.py restore` puts {len(back)} back to the last commit and saves what they held"
                        if back else "") + "; then `ledger.py check` again")
            sys.exit(1)
        say_next((f"`ledger.py restore` puts {len(back)} back to the last commit and saves what they held; "
                  if back else "")
                 + (f"untracked: {', '.join(clean(p) for p in new[:5])}: when the project's build, tests or an "
                    "analyzer made them, `ledger.py ignore \"<glob>\"`; otherwise stop and ask the user; " if new else "")
                 + "these changed while the run worked, so an agent strayed or someone edited them: tell the user "
                   "what changed, then `ledger.py check` again")
        sys.exit(1)
    # The wave's own files must hold what the guard accepted: a change made since ingest is checked again, and
    # never reaches the gate or a commit unchecked.
    returned, changed = wave_changes(lg) if units else ([], [])
    if returned:
        owners = sorted({u["id"] for u in units for p in returned if p in u["deletes"]})
        one = len(returned) == 1
        print(f"{', '.join(clean(p) for p in returned[:5])}: this wave deletes {'it' if one else 'them'}, but "
              f"{'it is' if one else 'they are'} back (an editor that saved its buffer, a build step, or someone's own "
              "work)")
        say_next("stop and ask the user; once it is moved away or deleted, `ledger.py check` again; or, to keep that "
                 f"file after all, `ledger.py settle {' '.join('--fail ' + u for u in owners)}`, then `ledger.py restore` "
                 "(which saves what is there now)")
        sys.exit(1)
    known = checked_record(lg)  # what a state from before this record lacks is read here for the first time
    problems = recheck(lg, changed) if changed else {}
    if changed:
        accepted = [p for p in changed if p not in problems and p in known]
        if accepted:
            were = "it was" if len(accepted) == 1 else "they were"
            print(f"{', '.join(clean(p) for p in accepted[:5])}: changed since {were} checked, and the guard accepts "
                  "the change (it only removes what the wave plans)")
        tested = tested_blobs(lg)
        if tested and tested != checked_digest(lg):  # the gate passed on other content
            lg.state["gates"].append({"kind": "fast", "round": lg.state["round"], "wave": lg.state["current_wave"],
                                      "outcome": "stale", "head": head_sha(lg), "at": now()})
        if problems:
            queue_restore(lg, sorted(problems), "changed after its removers finished, beyond what the wave removes: "
                                                "maybe someone's own change")
        lg.save()
    if problems:
        print(f"{len(problems)} file(s) of the wave changed since they were checked, beyond what the wave removes:")
        for p, why in sorted(problems.items())[:30]:
            print(f"  {clean(p)}: {clean(why)}")
        say_next(f"`ledger.py restore` puts {len(problems)} back to the last commit and saves what they held (their "
                 "removals go back to dead for a later wave); they changed after the removers finished, so someone or "
                 "a tool edited them: tell the user what changed, then `ledger.py check` again")
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
    """(green|red|timeout, output) of a shell command run at the root. Its output goes to a file, so that
    the shell's own exit decides even when it leaves a background process holding the output open. It
    runs in its own process group, which is ended afterwards, on a timeout, or when the ledger is stopped;
    the group is recorded meanwhile, with a token its environment carries, so that the next command ends it
    if this one is killed outright."""
    checkpoint()
    record, token = group_record(lg), os.urandom(16).hex()
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(shell(command), cwd=str(lg.root), stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True, env=dict(os.environ, **{GATE_TOKEN: token}))
        try:
            record_group(record, proc.pid, token)
            try:
                Stop.immediate = True
                checkpoint()  # a signal that came in while the command started
                outcome = "green" if proc.wait(timeout=timeout) == 0 else "red"
            except subprocess.TimeoutExpired:
                outcome = "timeout"
            finally:
                Stop.immediate = False
        finally:
            kill_group(proc)  # whatever it left running in the background, or all of it when the ledger stops
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            forget_group(record)
        out.seek(0)
        return outcome, out.read()


def kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass


# A running gate's process group is recorded in git's own folder, next to the integrity record, and every gate's
# environment carries a token of its own: an agent can write a record, never give a process an environment.
GROUP_FILE = "dead-code-gate.json"
GATE_TOKEN = "DEAD_CODE_LEDGER_GATE"


def group_record(lg: Ledger) -> Path:
    return lg.integrity_path().with_name(GROUP_FILE)


def process_stamp(pid: int) -> str:
    """When process `pid` started, as the system says, so that a recorded pid is never mistaken for a newer
    process that reused it; "" when it is gone or the system cannot tell."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        pass
    try:
        proc = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True)
    except OSError:
        return ""
    return proc.stdout.decode(errors="replace").strip() if proc.returncode == 0 else ""


def record_group(path: Path, pid: int, token: str) -> None:
    """Note the process group a gate runs in, until it ends: its leader with when it started, the token in its
    environment, and the ledger command that runs it, with when that started."""
    try:
        write_json(path, {"pid": pid, "stamp": process_stamp(pid), "token": token,
                          "owner": [os.getpid(), process_stamp(os.getpid())]})
    except OSError:
        pass


def forget_group(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def end_orphans(lg: Ledger) -> None:
    """End the process group of a gate that a killed ledger command left running, which could still write into
    the tree. The record only names a group to check, since anything can write a file: the group is ended once
    the command that ran it is gone, and only when one of its processes carries that gate's token (gate_group)."""
    path = group_record(lg)
    try:
        record = json.loads(path.read_text())
        pid, stamp, token = int(record["pid"]), str(record["stamp"]), str(record["token"])
        owner, owner_stamp = int(record["owner"][0]), str(record["owner"][1])
    except FileNotFoundError:
        return
    except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError):
        forget_group(path)  # not a record this script wrote: it names nothing to end
        return
    if running(owner, owner_stamp):
        return  # its command still runs (outside the lock?): never end another command's gate
    if pid > 1 and token and gate_group(pid, stamp, token):
        try:
            os.killpg(pid, signal.SIGKILL)
            print(f"ended the gate a killed ledger command left running (process group {pid})")
        except OSError:
            pass
    forget_group(path)


def gate_group(pgid: int, stamp: str, token: str) -> bool:
    """Whether process group `pgid` is still the one of the gate recorded: one of its processes carries that gate's
    token in its environment, which only the gate and what it started inherit. Its leader counts only while it is
    the very process recorded (its start time), another member also once the leader has exited (a background job
    can still write into the tree). Without /proc only the leader can be checked, with `ps -E`; whatever cannot be
    shown is never taken for the gate."""
    marker = f"{GATE_TOKEN}={token}"
    if not os.path.isdir("/proc/self"):
        if not stamp or process_stamp(pgid) != stamp:
            return False
        try:
            proc = subprocess.run(["ps", "-E", "-ww", "-o", "command=", "-p", str(pgid)], capture_output=True)
        except OSError:
            return False
        return proc.returncode == 0 and marker in proc.stdout.decode(errors="replace").split()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            fields = Path(f"/proc/{entry}/stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) != pgid or (int(entry) == pgid and fields[19] != stamp):
                continue
            if marker.encode() in Path(f"/proc/{entry}/environ").read_bytes().split(b"\0"):
                return True
        except (OSError, IndexError, ValueError):
            continue
    return False


def running(pid: int, stamp: str) -> bool:
    """Whether process `pid` is the very one recorded (its start time) and has not exited: a killed command whose
    parent has not reaped it yet still shows in /proc, as a zombie."""
    if not stamp or process_stamp(pid) != stamp:
        return False
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True  # no /proc: the start time is all the system tells


class Stop:
    """A signal that ends the ledger while the tree is mid-change, held until stopping is safe: never inside a
    git command (a git killed while it holds .git/index.lock leaves the lock behind), at once while a gate runs,
    whose whole process group is then ended."""
    pending = None
    immediate = False


def checkpoint() -> None:
    """Stop here if a signal came in since the last step."""
    if Stop.pending is not None:
        signum, Stop.pending = Stop.pending, None
        raise SystemExit(f"ledger.py: stopped by signal {signum}")


@contextlib.contextmanager
def signals_raise():
    """While the tree is mid-change, turn SIGINT, SIGTERM and SIGHUP (an interrupted tool call, a closed session)
    into SystemExit at safe points, so that `finally` blocks put the tree back before the process ends. A signal
    the caller ignores (`nohup`) stays ignored."""
    def stop(signum, frame):
        if Stop.immediate:
            Stop.immediate = False
            raise SystemExit(f"ledger.py: stopped by signal {signum}")
        Stop.pending = signum
    saved = {}
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        kind = getattr(signal, name, None)
        if kind is not None and signal.getsignal(kind) is not signal.SIG_IGN:
            saved[kind] = signal.signal(kind, stop)
    try:
        yield
    finally:
        for kind, handler in saved.items():
            signal.signal(kind, handler)


def gate_command(lg: Ledger, kind: str) -> str:
    """The recorded command for a gate; when only one gate was recorded, it stands in for the other."""
    return lg.state["gate"].get(kind) or lg.state["gate"].get("full" if kind == "fast" else "fast") or ""


def run_gate(lg: Ledger, kind: str, timeout: int) -> tuple:
    """Run a recorded gate: (outcome green|red|timeout|rewritten, output bytes, seconds, new untracked files,
    tracked files it changed). "rewritten": it changed the open wave's own files, which a formatter or a
    code generator does, or wrote again a file the wave deletes; those files are put back as they were, with a
    copy of what the gate left, since no removal in them could be committed."""
    command = gate_command(lg, kind)
    if not command:
        die("no gate command was recorded; `ledger.py init --force` with --gate-fast or --gate-full")
    with signals_raise():  # a stop ends the gate at once, and never a git command half way
        files = sorted(p for p in wave_files(lg) if lg.in_head(p))
        wave_before = worktree_patch(lg, files) if files else b""
        blobs = file_blobs(lg, files)
        before = set(status_entries(lg))
        started = datetime.now(timezone.utc)
        outcome, output = run_command(lg, command, timeout)
        seconds = int((datetime.now(timezone.utc) - started).total_seconds())
        new = [(code, p) for code, p in status_entries(lg) if (code, p) not in before]
        # A wave path is never an artifact: a file the wave deletes, written again, is a rewrite of the wave.
        artifacts = sorted(p for code, p in new if code == "??" and p not in wave_files(lg))
        if artifacts:
            lg.state["untracked"] = sorted(set(lg.state.get("untracked", [])) | set(artifacts))
        touched = sorted({p for code, p in new if code != "??"} - set(files))
        follow_tools(lg)
        after = file_blobs(lg, files)
        back = [p for p in files if blobs[p] == "-" and after[p] != "-"]  # git's diff does not see those
        if back or files and worktree_patch(lg, files) != wave_before:
            outcome = "rewritten"
            lg.state["rewritten"] = [p for p in files if after[p] != blobs[p]] or files
            save_copy(lg, files, {p: "the wave's files as the gate left them: the gate rewrote them, or someone "
                                     "edited them while it ran" for p in files})
            # A folder where the wave has a file is never deleted: it stays, and `check` stops on it.
            if not any((lg.root / p).is_dir() and not (lg.root / p).is_symlink() for p in files):
                run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"] + files, lg.root)
                if wave_before.strip():  # which deletes again what the wave deletes
                    subprocess.run(["git", "apply", "--index", "--whitespace=nowarn", "-"], cwd=str(lg.root),
                                   input=wave_before, capture_output=True, env=GIT_ENV)
    return outcome, output or b"", seconds, artifacts, touched


def cmd_gate(args) -> None:
    """Run a recorded gate command; artifacts it leaves untracked are ignored from then on."""
    lg = Ledger(git_root()).load()
    if lg.units(status="dispatched"):
        die("a stage is still dispatched: its agents may be editing; wait for its workflow, then `ledger.py ingest "
            "<stage>` first")
    moved = moved_head(lg)
    if moved:  # a gate would test what someone committed with the wave as if it were the wave
        die(moved_step(lg, moved))
    if user_files_changed(lg) or hidden_changes(lg):
        die("files changed where `git status` cannot show them: `ledger.py check` first")
    if open_removal_units(lg) and wrong_branch(lg):
        die(wrong_branch(lg))
    if lg.state.get("restore"):
        die("files are waiting to be restored first: `ledger.py restore`")
    dirty = [p for p in changed_paths(lg, untracked=False) if p not in wave_files(lg)]
    if dirty:  # a gate passes or fails on the run's own changes, never on someone else's
        die(f"tracked files changed outside the open wave, e.g. {clean(dirty[0])}: `ledger.py check` first")
    unchecked = unchecked_step(lg) if open_removal_units(lg) else ""
    if unchecked:  # and on the wave's own files only as the guard accepted them
        die(unchecked)
    log = own_folder(lg, "gates") / f"{args.kind}-r{lg.state['round']}-{len(lg.state.setdefault('gates', [])) + 1}.log"
    print(f"running the {args.kind} gate: {gate_command(lg, args.kind) or '-'}")
    outcome, output, seconds, artifacts, touched = run_gate(lg, args.kind, args.timeout)
    log.write_bytes(output)
    wave = lg.state.get("current_wave") if open_removal_units(lg) else None
    lg.state.setdefault("gates", []).append({"kind": args.kind, "round": lg.state["round"], "wave": wave, "outcome": outcome,
                              "seconds": seconds, "timeout": args.timeout, "head": head_sha(lg), "at": now()})
    if args.kind == "fast" and wave and outcome == "green" and wave_blobs(lg) == checked_digest(lg):
        lg.state["gates"][-1]["tested"] = checked_digest(lg)  # only this content may be committed as the wave
    if args.kind == "full" and outcome == "green" and not wave:
        lg.state["full_gate_head"] = head_sha(lg)
    if not wave and not lg.state["history"]:
        lg.state.setdefault("baseline", {})[args.kind] = outcome
    strays = [p for p in touched if p not in wave_files(lg)]
    if strays:  # a formatter or a lockfile update: put them back before anything is committed
        queue_restore(lg, strays, "the gate command changed it")
    lg.save()
    checkpoint()  # a stop asked for while git read the tree after the gate: the gate's result is saved first
    tail = (decode(output) or "").strip().splitlines()[-25:]
    print(f"{args.kind} gate {outcome.upper()} in {seconds}s (full log: {log})")
    if outcome != "green" and tail:
        print("\n".join("  " + line for line in tail))
    if artifacts:
        print(f"{len(artifacts)} new untracked file(s) left by the gate are ignored from now on, e.g. {clean(artifacts[0])}")
    if strays:
        print(f"the gate modified tracked file(s) outside the wave, to be restored: {', '.join(clean(p) for p in strays[:5])}")
    if outcome == "rewritten":
        rewritten = lg.state.get("rewritten", [])
        left = [p for p in rewritten if (lg.root / p).is_dir() and not (lg.root / p).is_symlink()]
        print(f"the gate rewrote this wave's own files ({', '.join(clean(p) for p in rewritten[:5])}): "
              "a formatter, `--fix`, or a code generator; " + (
                  "they are back as the removers left them" if not left else
                  f"a folder now stands at {', '.join(clean(p) for p in left[:5])}, so they are left as the gate "
                  "left them"))
    say_next(next_step(lg))


def blobs_digest(files: list, found: dict) -> str:
    """A digest of what these files hold, as file_blobs gives it; a file missing from `found` was never checked."""
    return digest("".join(f"{p}\t{found.get(p, 'unchecked')}\n" for p in files).encode("utf-8", "surrogateescape"))


def wave_blobs(lg: Ledger, rev=None) -> str:
    """A digest of what the open wave's files hold, in the working tree, the index or a commit (see file_blobs).
    A green fast gate records it when it is what the guard accepted: only that content may be committed."""
    files = sorted(wave_files(lg))
    return blobs_digest(files, file_blobs(lg, files, rev))


def checked_digest(lg: Ledger) -> str:
    """What wave_blobs gives while the open wave's files hold what the guard accepted (see checked_record)."""
    return blobs_digest(sorted(wave_files(lg)), checked_record(lg))


def changed_between(lg: Ledger, old: str, new: str) -> list:
    """The paths two commits (or trees) differ in: a renamed file gives both its paths."""
    out = run(["git", "diff", "--no-renames", "--name-only", "-z", old, new], lg.root, check=False).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def moved_head(lg: Ledger) -> str:
    """HEAD's sha when it moved since the open wave was planned and holds changes to that wave's files, else ""."""
    base = lg.state.get("wave_base")
    if not base or not open_removal_units(lg):
        return ""
    head = head_sha(lg)
    if not head or head == base:
        return ""
    return head if set(changed_between(lg, base, head)) & wave_files(lg) else ""


def tested_blobs(lg: Ledger) -> str:
    """What the last green fast gate of the open wave tested (see wave_blobs), or "" when none says."""
    last = next((g for g in reversed(lg.state.get("gates") or []) if g.get("kind") == "fast"), {})
    if last.get("wave") == lg.state.get("current_wave") and last.get("outcome") == "green":
        return last.get("tested") or ""
    return ""


def holds_wave(lg: Ledger, head: str) -> bool:
    """Whether commit `head` is the open wave's own: the one a settle cut short recorded it in, or one commit on top
    of the wave's base that changes only the wave's files and holds them exactly as the guard accepted them and the
    fast gate tested them (a commit the ledger made but could not record, or one made by hand)."""
    base, files = lg.state.get("wave_base"), sorted(wave_files(lg))
    if not base or not head or head == base:
        return False
    if any(lg.cands[cid]["status"] == "removed" and lg.cands[cid].get("commit") == head
           for u in open_removal_units(lg) for cid in u["candidates"]):
        return True
    since = set(changed_between(lg, base, head))
    if not since or not since <= set(files) or tested_blobs(lg) != checked_digest(lg):
        return False
    parent = run(["git", "rev-parse", "-q", "--verify", f"{head}^"], lg.root, check=False).stdout.decode().strip()
    record = checked_record(lg)
    return parent == base and all(record.get(p) == blob for p, blob in file_blobs(lg, files, head).items())


def moved_step(lg: Ledger, head: str) -> str:
    """The next step when HEAD moved under an open wave: commit, when HEAD holds this wave (see holds_wave)."""
    if holds_wave(lg, head):
        return "ledger.py commit (HEAD already holds this wave, as it was checked and tested)"
    return (f"HEAD moved since wave {lg.state.get('current_wave')} opened ({head[:12]}) and holds changes to its files "
            "that no gate tested: stop and ask the user")


def drop_lost(lg: Ledger, lost: list, where: str = "in the tree any more") -> None:
    """Candidates ingested as applied whose removal the index (or the commit) does not hold: back to dead for a
    later wave, or given up once their removal was undone MAX_RETRIES times."""
    for c in lost:
        c["unit"] = None
        c["remove_retries"] = c.get("remove_retries", 0) + 1
        if c["remove_retries"] >= MAX_RETRIES:
            set_status(c, "skipped", f"its removal was undone before the commit {c['remove_retries']} times: the "
                                     "gate or a build step regenerates its file?")
        else:
            set_status(c, "dead", "its removal was no longer in the tree when the wave was committed")
    again = sum(1 for c in lost if c["status"] == "dead")
    if lost:
        print(f"{len(lost)} removal(s) ingested as applied are not {where}, e.g. {lost[0]['id']} "
              f"{clean(lost[0]['symbol'], 80)}: " + (
                  "back to dead for a later wave" if again == len(lost) else
                  f"given up after {MAX_RETRIES} undone removals" if not again else
                  f"{again} back to dead for a later wave, {len(lost) - again} given up after {MAX_RETRIES} undone "
                  "removals"))


def cmd_commit(args) -> None:
    """Commit the current wave (its files only, as the guard accepted them and the fast gate tested them), then
    settle it."""
    lg = Ledger(git_root()).load()
    units = open_removal_units(lg)
    if not units:
        die("no removal wave is waiting to be committed")
    last = next((g for g in reversed(lg.state.get("gates") or []) if g.get("kind") == "fast"), {})
    if last.get("wave") == lg.state["current_wave"] and last.get("outcome") == "rejected":
        die(next_step(lg))
    branch = run(["git", "branch", "--show-current"], lg.root, check=False).stdout.decode().strip()
    if lg.state.get("branch") and branch != lg.state["branch"]:
        die(f"the run commits on {lg.state['branch']}, but {branch or 'a detached HEAD'} is checked out: "
            f"`git switch {lg.state['branch']}`")
    files = sorted(wave_files(lg))
    # Nothing is staged before HEAD is known to be the wave's base or the wave's own commit: any other commit
    # is not the wave's, and bisect must never revert it.
    base, head = lg.state.get("wave_base") or head_sha(lg), head_sha(lg)
    ours = holds_wave(lg, head)
    recorded = False
    for u in units:  # removals a settle cut short recorded: what HEAD, or the index, holds decides them again
        for cid in u["candidates"]:
            if lg.cands[cid]["status"] == "removed":
                recorded = recorded or lg.cands[cid].get("commit") == head
                set_status(lg.cands[cid], "applied")
                lg.cands[cid]["commit"] = None
    if ours:  # committed already: by a commit cut short before it settled, or by hand
        drop_lost(lg, unremoved(lg, units, base, head), f"in {head[:12]}")
        held, now_, staged = file_blobs(lg, files, head), file_blobs(lg, files), file_blobs(lg, files, "")
        left = [p for p in files if now_[p] != held[p] or staged[p] != held[p]]
        print(f"this wave's removals are already recorded in {head[:12]}: a commit was cut short before it settled"
              if recorded else f"this wave's removals are already committed in {head[:12]}")
        if left:  # neither staged, committed nor discarded here
            print(f"warning: {', '.join(clean(p) for p in left[:5])} changed after {head[:12]}: that change is not part "
                  "of the wave, and stays as it is")
        settle(lg, units, head, first=f"ask the user about {', '.join(clean(p) for p in left[:5])}, changed after the "
                                       "wave's commit (to commit or discard it is theirs to decide); then " if left else "")
        return
    if head != base and set(changed_between(lg, base, head)) & set(files):
        die(f"HEAD moved since wave {lg.state['current_wave']} opened, and {head[:12]} holds part of this wave or other "
            "changes with it: stop and ask the user")
    if last.get("wave") != lg.state["current_wave"] or last.get("outcome") != "green":
        die("the fast gate has not passed for this wave; run `ledger.py gate fast` first")
    if user_files_changed(lg) or hidden_changes(lg):
        die("files changed where `git status` cannot show them: `ledger.py check` first")
    dirty = [p for p in changed_paths(lg, untracked=False) if p not in files]
    if dirty:  # a commit hook could sweep them in (`git add -u`)
        die(f"tracked files changed outside the open wave, e.g. {clean(dirty[0])}: `ledger.py check` first")
    if head != last.get("head"):  # another commit, of other files, since the gate: the wave was not tested on it
        die(f"HEAD moved since the fast gate passed (it is now {head[:12]}): run `ledger.py gate fast` again")
    unchecked = unchecked_step(lg)
    if unchecked:  # an edit since the guard read the wave's files: no gate run may vouch for it
        die(unchecked)
    record = checked_record(lg)
    if last.get("tested") != blobs_digest(files, record):
        die("the fast gate did not test this wave's files as they were last checked: run `ledger.py gate fast` again")
    indexed = file_blobs(lg, files, "")
    stage = [p for p in files if record.get(p) != "-" or indexed[p] != "-"]  # `git rm` staged the deleted files
    if stage:
        run(["git", "add", "-A", "--"] + stage, lg.root)
    if any(blob != record.get(p) for p, blob in file_blobs(lg, files, "").items()):
        die("this wave's files changed while they were staged: `ledger.py check` first")
    staged = [p for p in run(["git", "diff", "--cached", "--no-renames", "--name-only", "-z"], lg.root).stdout
              .decode("utf-8", "replace").split("\0") if p]
    stray = sorted(set(staged) - set(files))
    if stray:
        die(f"the index holds files outside this wave: {', '.join(clean(x) for x in stray[:5])}; unstage them first")
    # Only what the index holds becomes `removed`: a removal undone since ingest goes back to dead.
    drop_lost(lg, unremoved(lg, units, base))
    n = sum(1 for u in units for cid in u["candidates"] if lg.cands[cid]["status"] == "applied")
    if not n:  # nothing of the wave survived: never a "remove 0" commit; its leftover edits go back
        leftovers = sorted(set(staged) | {p for p in changed_paths(lg, untracked=False) if p in files})
        if leftovers:
            run(["git", "restore", "--staged", "--"] + leftovers, lg.root, check=False)
            queue_restore(lg, leftovers, "edits of a wave none of whose removals survived")
        print("nothing to commit: no removal of this wave is in the tree")
        settle(lg, units, None)
        return
    msg = (f"refactor(dead-code): remove {n} unused declaration{'s' if n != 1 else ''} "
           f"(round {lg.state['round']}, wave {lg.state['current_wave']})")
    tree = run(["git", "write-tree"], lg.root).stdout.decode().strip()  # what the gate passed, as staged
    proc = run(["git", "commit", "-q", "-m", msg], lg.root, check=False)
    if proc.returncode != 0:
        print("git commit failed (a commit hook may have rejected the wave):")
        print("\n".join("  " + clean(line) for line in (proc.stdout + proc.stderr).decode(errors="replace").splitlines()[-15:]))
        lg.state["gates"].append({"kind": "fast", "round": lg.state["round"], "wave": lg.state["current_wave"],
                                  "outcome": "rejected", "head": head, "at": now()})
        lg.save()
        say_next("never bypass the hook with --no-verify and never edit code for it: treat this as a red gate, "
                 "`ledger.py settle --fail <unit>` for the units it names, or stop and ask the user")
        return
    sha = run(["git", "rev-parse", "HEAD"], lg.root).stdout.decode().strip()
    lg.state["branch"] = lg.state.get("branch") or branch
    if run(["git", "rev-parse", "-q", "--verify", f"{sha}^"], lg.root, check=False).stdout.decode().strip() != head:
        die(f"HEAD is {sha[:12]}, which is not a commit on top of {head[:12]} (a hook committed again after the "
            "wave's commit?): the wave stays open; stop and ask the user")
    committed = run(["git", "rev-parse", f"{sha}^{{tree}}"], lg.root).stdout.decode().strip()
    if committed != tree:
        changed = changed_between(lg, tree, sha)
        outside = [p for p in changed if p not in files]
        if outside:
            die(f"a commit hook put {', '.join(clean(p) for p in outside[:5])} into {sha[:12]} with the wave: the wave "
                "stays open, since bisect could revert someone's work with it; stop and ask the user")
        held = file_blobs(lg, files, sha)
        dropped = [p for p in changed if record.get(p) not in (None, "-") and held[p] == "-"]
        if dropped:  # the full gate runs on the working tree, where they still are: it would never see this
            die(f"a commit hook took {', '.join(clean(p) for p in dropped[:5])} out of {sha[:12]}, although this wave "
                "only edits them: the wave stays open; stop and ask the user")
        print(f"warning: a commit hook changed this wave's files in {sha[:12]} beyond what the gate passed: "
              f"{', '.join(clean(p) for p in changed[:5])}" + ("; the full gate tests the result" if
                                                               lg.state["gate"].get("full") else ""))
        drop_lost(lg, unremoved(lg, units, base, sha), "in the commit")
        # What the hook left out of the commit is the run's own removal: back to the commit, with a copy.
        now_, staged_now = file_blobs(lg, files), file_blobs(lg, files, "")
        left = [p for p in files if now_[p] != held[p] or staged_now[p] != held[p]]
        if left:
            queue_restore(lg, left, "the run's own removal, which a commit hook left out of the commit")
        if committed == run(["git", "rev-parse", f"{head}^{{tree}}"], lg.root, check=False).stdout.decode().strip():
            print(f"a commit hook emptied {sha[:12]}: none of this wave's removals is in it")
            settle(lg, units, None)
            return
    print(f"committed {sha[:12]}: {msg}")
    settle(lg, units, sha)


def settle(lg: Ledger, units: list, sha, first: str = "") -> None:
    """Close the current wave: applied candidates become removed in commit `sha`. Without a commit
    nothing was removed, so they go back to dead for a later wave."""
    removed = 0
    for u in units:
        for cid in u["candidates"]:
            c = lg.cands[cid]
            if c["status"] == "applied" and sha:
                set_status(c, "removed")
                c["commit"] = sha
                removed += 1
            elif c["status"] == "removed" and sha and c.get("commit") == sha:
                removed += 1  # recorded by a settle that was cut short before the state was saved
            elif c["status"] == "applied":
                set_status(c, "dead", "its wave closed without a commit")
                c["unit"] = None
        u["status"] = "settled"
    lg.state["history"].append({"round": lg.state["round"], "wave": lg.state["current_wave"], "removed": removed,
                                "commit": sha, "at": now()})
    lg.state["current_wave"] = None
    lg.save()
    print(f"wave settled: {removed} removal(s)" + (f" in {sha[:12]}" if sha else ""))
    say_next(first + next_step(lg))


def cmd_settle(args) -> None:
    lg = Ledger(git_root()).load()
    wave = lg.state.get("current_wave")
    moved = moved_head(lg)
    if moved:
        die(moved_step(lg, moved))
    if any(u["wave"] == wave for u in lg.units("remove", "dispatched")):
        die("this wave's removers have not been ingested yet: `ledger.py ingest remove` first")
    units = open_removal_units(lg)
    if not units:
        if wave is not None and args.ok:
            settle(lg, [], None)  # every unit failed: close the wave with nothing removed
            return
        die("no removal wave is waiting for its gate")
    if args.find:
        # A search cut short resumes whatever its own gate runs queued for restore: `restore` waits for it.
        if lg.state.get("restore") and lg.state.get("finding") != wave:
            die("files are waiting to be restored first: `ledger.py restore`, then `ledger.py gate fast`")
        find_culprits(lg, units, args.timeout)
        return
    if lg.state.get("finding"):
        die("a `settle --find` was cut short: run `ledger.py settle --find` again first")
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
        die("after a green fast gate, `ledger.py commit`; after a red one, `--fail <unit>` or `--find`")
    if any(lg.cands[cid]["status"] == "applied" for u in units for cid in u["candidates"]):
        die("this wave has removals applied: after a green fast gate, `ledger.py commit` checks and commits them")
    leftovers = [p for p in changed_paths(lg, untracked=False) if p in wave_files(lg)]
    if leftovers:  # nothing of the wave survived its ingest: what its removers left goes back
        queue_restore(lg, leftovers, "edits of a wave none of whose removals survived")
    settle(lg, units, None)


def fail_open_unit(lg: Ledger, u: dict, note: str) -> None:
    """The gate proved this unit's removals wrong: they are alive, and its files go back to HEAD."""
    for cid in u["candidates"]:
        c = lg.cands[cid]
        if c["status"] == "applied":
            set_status(c, "reverted", note)
            c["pinned"] = True
    u["status"] = "failed"
    queue_restore(lg, set(u["allowed"]) | set(u["deletes"]), f"unit {u['id']}'s removals, which broke the gate: "
                                                             "the run's own wrong removal")
    print(f"{u['id']} reverted: " + ", ".join(f"{cid} {lg.cands[cid]['symbol']}" for cid in u["candidates"]))


class ReapplyError(Exception):
    """A unit's saved patch would not apply again."""


def find_culprits(lg: Ledger, units: list, timeout: int) -> None:
    """Bisect the open wave: find the units whose removals break the fast gate, keep the others applied.
    Each unit's patch is saved in .dead-code/find/ before the tree is touched, and every way out but a
    verdict puts the whole wave back, with the ledger as it was: a search cut short by a kill starts over
    from those patches, as their digests in the state vouch. A wave whose patches will not apply again, or are
    missing or changed, is given up: its removals are kept under .dead-code/restored/, and its candidates wait
    for a later wave."""
    files = sorted({p for u in units for p in u["allowed"] + u["deletes"]})
    in_head = [p for p in files if lg.in_head(p)]
    saved = lg.dir / "find"
    wave = lg.state["current_wave"]
    resumed = lg.state.get("finding") == wave
    if resumed:
        # A patch is applied again only as it was saved: one missing or altered since (an agent can write there)
        # could delete what no unit removed. Then the search cannot resume, and the wave is given up with a copy.
        sums, patches, lost = lg.state.get("finding_patches") or {}, {}, ""
        for u in units:
            path = saved / f"{u['id']}.patch"
            try:
                if saved.is_symlink() or path.is_symlink() or not path.is_file():
                    raise OSError(f"no file {LEDGER}/find/{u['id']}.patch")
                patches[u["id"]] = path.read_bytes()
            except OSError as err:
                lost = f"are missing ({clean(err, 200)})"
                break
            if digest(patches[u["id"]]) != sums.get(u["id"]):
                lost = f"no longer match what it saved ({u['id']}.patch)"
                break
        if lost:
            lose_wave(lg, units, files, lost)
            return
        print("the last `settle --find` was cut short: the whole wave goes back first")
    else:
        patches = {u["id"]: worktree_patch(lg, sorted(set(u["allowed"]) | set(u["deletes"]))) for u in units}
        problem = patches_apply(lg, patches)
        if problem:
            die(f"cannot narrow this wave: {problem}; nothing was changed")
        try:
            if saved.is_symlink() or (saved.exists() and not saved.is_dir()):
                saved.unlink()  # planted there: the folder is the ledger's own
            shutil.rmtree(saved, ignore_errors=True)
            saved.mkdir()
        except OSError as err:
            die(f"cannot narrow this wave: {saved} cannot be made a folder ({err}); nothing was changed")
        for unit, data in patches.items():
            (saved / f"{unit}.patch").write_bytes(data)
        lg.state["finding"] = wave
        lg.state["finding_patches"] = {unit: digest(data) for unit, data in patches.items()}
        lg.save()
    before = copy.deepcopy((lg.state, lg.cands))  # what the ledger goes back to without a verdict
    runs, outcome, culprits, keep, failure, problem, stuck, given_up = 0, "", [], [], "", "", False, False
    indexed = resumed  # whether the wave's files were last written by `git apply --index`

    def keep_edits():
        """Save what was typed into the wave's files since the last apply, before they are put back: apply
        keeps the index equal to the tree, so a difference between them is an edit made since. A file the wave
        deletes has no index entry for git to compare, so a file at its path was written after the deletion."""
        if not in_head:
            return
        edited = []
        if indexed:
            out = run(["git", "diff-files", "--name-only", "-z", "--"] + in_head, lg.root, check=False).stdout
            edited = [p for p in out.decode("utf-8", "replace").split("\0") if p]
        listed = set(run(["git", "ls-files", "-z", "--"] + in_head, lg.root, check=False).stdout
                     .decode("utf-8", "replace").split("\0"))
        edited += [p for p in in_head if p not in listed and p not in edited and (lg.root / p).is_file()
                   and not (lg.root / p).is_symlink() and differs_from_head(lg, p)]
        folder = save_copy(lg, edited, {p: "edited while `settle --find` ran: maybe someone's own change"
                                        for p in edited}) if edited else ""
        if folder:
            lg.save()  # recorded at once: a kill before the search ends must not leave the copy unexplained
            print(f"{', '.join(clean(p) for p in edited[:5])} changed while the search ran: what they held is saved "
                  f"in {folder}")

    def apply(subset):
        """Put the wave's files back to HEAD, then apply these units' patches: what git says when it cannot."""
        nonlocal indexed
        keep_edits()
        keep_folders(lg, in_head, "written where the wave has a file while `settle --find` ran: maybe someone's own "
                                  "change")
        indexed = True
        if in_head:
            proc = run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"] + in_head, lg.root,
                       check=False)
            if proc.returncode != 0:
                return clean(proc.stderr.decode(errors="replace").strip(), 200)
        for u in subset:
            if patches[u["id"]].strip():
                proc = subprocess.run(["git", "apply", "--index", "--whitespace=nowarn", "-"], cwd=str(lg.root),
                                      input=patches[u["id"]], capture_output=True, env=GIT_ENV)
                if proc.returncode != 0:
                    return f"{u['id']}: " + clean(proc.stderr.decode(errors="replace").strip(), 200)
        return ""

    def red(subset):
        nonlocal runs
        checkpoint()
        trouble = apply(subset)
        if trouble:
            raise ReapplyError(trouble)
        runs += 1
        gate, _, _, _, touched = run_gate(lg, "fast", timeout)
        if touched:  # a formatter or a lockfile: back after the search, never left behind
            queue_restore(lg, touched, "the gate command changed it")
        if gate == "timeout":
            die("the fast gate timed out while narrowing the wave; re-run with a larger --timeout")
        if gate == "rewritten":
            die("the fast gate rewrites the wave's own files (a formatter, `--fix`, or a code generator), so no "
                "removal in them can be committed: stop and tell the user")
        checkpoint()
        return gate == "red"

    def search(subset, base):
        """The units of `subset` whose removals break the gate once applied on top of `base`."""
        if len(subset) == 1:
            return subset
        half = len(subset) // 2
        left, right = subset[:half], subset[half:]
        found = (search(left, base) if red(base + left) else []) + (search(right, base) if red(base + right) else [])
        if found:
            return found
        # Each half passes alone: the break needs units of both. Add them one at a time and blame the one
        # that turns the gate red; the ones before it stay applied, so only one unit of the set is reverted.
        applied = list(base)
        for u in subset:
            if red(applied + [u]):
                return [u]
            applied.append(u)
        return []

    print(f"narrowing wave {wave}: {len(units)} unit(s)")
    with signals_raise():
        try:
            if not red(units):
                outcome = "green"
            else:
                if red([]):
                    die("the fast gate fails even without any of this wave's removals (a flaky gate, the "
                        "environment, or a red baseline): every unit stays open; stop and tell the user")
                keep = list(units)
                while True:  # a second culprit can hide behind the first: search again until what is kept passes
                    found = search(keep, [])
                    if not found:
                        die("the fast gate gives different results for the same removals (a flaky gate): every "
                            "unit stays open; stop and tell the user")
                    culprits += found
                    keep = [u for u in keep if u not in found]
                    if not keep or not red(keep):
                        break
                trouble = apply(keep)
                if trouble:
                    raise ReapplyError(trouble)
                head = head_sha(lg)
                # The verdict is recorded whole: a signal from here on waits until it is saved.
                for u in culprits:
                    fail_open_unit(lg, u, "the fast gate failed with this unit's removals, and passed without them")
                    # Its files went back to HEAD with apply(): what they held is kept, as a restore would.
                    save_copy(lg, sorted(set(u["allowed"]) | set(u["deletes"])),
                              {p: f"unit {u['id']}'s removals, which broke the gate: the run's own wrong removal"
                               for p in set(u["allowed"]) | set(u["deletes"])}, patch=patches[u["id"]])
                # The tree already holds exactly the kept units: the failed units' files need no restore.
                lg.state["restore"] = sorted(set(lg.state.get("restore", [])) - set(files))
                for p in files:
                    lg.state.get("restore_causes", {}).pop(p, None)
                lg.state.setdefault("gates", []).append({"kind": "fast", "round": lg.state["round"], "wave": wave,
                                                         "outcome": "stale", "head": head, "at": now()})
                outcome = "verdict"
        except ReapplyError as err:
            failure = str(err)
        finally:
            if outcome not in ("verdict", "green"):  # cut short: the ledger and the whole wave go back
                lg.state, lg.cands = kept_progress(lg, before, files)
                problem = apply(units)
                if problem:
                    given_up = give_up_wave(lg, units, patches, files)
                    stuck = not given_up
            if not stuck:
                lg.state["finding"] = None
                lg.state.pop("finding_patches", None)
            lg.save()
            if not stuck:  # only once the saved state no longer asks to resume from them
                shutil.rmtree(saved, ignore_errors=True)
    checkpoint()
    if stuck:
        die(f"git could not put wave {wave} back ({problem}); if no git command is running, delete "
            ".git/index.lock, then `ledger.py settle --find` again")
    if given_up:
        print(f"wave {wave}'s patches would not apply again ({problem}): its removals are kept under "
              f"{lg.dir / 'restored'}, and its candidates wait for a later wave")
        settle(lg, [], None)
        return
    if failure:
        die(f"`settle --find` could not apply a unit's patch ({failure}); the whole wave is back as it was: "
            "`ledger.py settle --fail <unit>` for the unit the gate's error names, or stop and tell the user")
    if outcome == "green":
        print("the fast gate is green with every unit applied")
        say_next("ledger.py gate fast")
        return
    print(f"{len(culprits)} unit(s) failed after {runs} gate run(s); {len(keep)} kept")
    if not open_removal_units(lg):
        settle(lg, [], None)
        return
    say_next(next_step(lg))


def lose_wave(lg: Ledger, units: list, files: list, lost: str) -> None:
    """A `settle --find` cut short whose saved patches are gone or altered cannot resume: its wave is given up, as
    one whose patches no longer apply is. What the wave's files hold now is kept, they go back to HEAD, and the
    wave's candidates wait for a later wave."""
    wave = lg.state["current_wave"]
    with signals_raise():  # a stop waits: never inside git, and the state is saved whole
        kept = save_copy(lg, files, {p: f"wave {wave}'s files as a `settle --find` cut short left them, its saved "
                                        "patches lost: the run's own removals, and maybe someone's own change"
                                     for p in files})
        given_up = give_up_wave(lg, units, {u["id"]: b"" for u in units}, files)
        if given_up:
            lg.state["finding"] = None
            lg.state.pop("finding_patches", None)
        lg.save()
    checkpoint()
    if not given_up:
        die(f"git could not put wave {wave} back; if no git command is running, delete .git/index.lock, then "
            "`ledger.py settle --find` again")
    shutil.rmtree(lg.dir / "find", ignore_errors=True)
    print(f"the saved patches of the interrupted `settle --find` {lost}, so it cannot resume: wave {wave}'s files are "
          "back at HEAD" + (f", what they held is kept in {kept}" if kept else "") + ", and its candidates wait for a "
          "later wave")
    settle(lg, [], None)


def kept_progress(lg: Ledger, before: tuple, files: list) -> tuple:
    """The ledger as it was before a search that ends without a verdict, with only what the search learned about
    the tree: the gate's untracked artifacts, the copies it saved, and files outside the wave to put back."""
    state, cands = copy.deepcopy(before)
    state["untracked"] = lg.state.get("untracked", [])
    state["restored"] = lg.state.get("restored", [])
    for key in ("hidden", "preexisting", "touched_by_tools"):  # what the gate runs did to files git cannot show
        if key in lg.state:
            state[key] = lg.state[key]
    for p in lg.state.get("restore", []):
        if p not in files:
            state.setdefault("restore_causes", {}).setdefault(p, lg.state.get("restore_causes", {}).get(p, ""))
            state["restore"] = sorted(set(state.get("restore", [])) | {p})
    return state, cands


def keep_folders(lg: Ledger, paths: list, cause: str) -> str:
    """Keep a copy of the files in any folder that stands where `paths` have a file in the last commit, before
    `git restore` puts the file back: git deletes such a folder with everything in it, untracked files
    included, and says nothing. Returns the copy's folder, or ""."""
    inside = sorted(q.relative_to(lg.root).as_posix() for p in paths
                    if (lg.root / p).is_dir() and not (lg.root / p).is_symlink()
                    for q in (lg.root / p).rglob("*") if q.is_file() and not q.is_symlink())
    folder = save_copy(lg, inside, {q: cause for q in inside}) if inside else ""
    if folder:
        lg.save()  # on record before git deletes anything
        print(f"{', '.join(clean(q) for q in inside[:5])} stood in a folder where the last commit has a file: what it "
              f"held is saved in {folder}")
    return folder


def give_up_wave(lg: Ledger, units: list, patches: dict, files: list) -> bool:
    """Give up on a wave whose patches will not apply again: put its files back to HEAD, keep its patches under
    .dead-code/restored/, and send its candidates back to dead for a later wave. False when git cannot even put
    the files back (a stale .git/index.lock): then nothing changes, and the patches stay in .dead-code/find/."""
    in_head = [p for p in files if lg.in_head(p)]
    keep_folders(lg, in_head, "written where the wave has a file while `settle --find` ran: maybe someone's own change")
    if in_head and run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"] + in_head, lg.root,
                       check=False).returncode != 0:
        return False
    save_copy(lg, files, {p: f"wave {lg.state['current_wave']}'s removals, which `settle --find` could not apply again: "
                             "the run's own removals, planned again later" for p in files},
              patch=b"".join(patches[u["id"]] for u in units))
    for u in units:
        for cid in u["candidates"]:
            c = lg.cands[cid]
            if c["status"] == "applied":
                c["unit"] = None
                set_status(c, "dead", "its wave could not be put back after `settle --find`")
        u["status"] = "failed"
    return True


def patches_apply(lg: Ledger, patches: dict) -> str:
    """An empty string when the patches apply to HEAD one after the other, else what git says. The check runs
    against a scratch index, so neither the working tree nor the real index is touched."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(GIT_ENV, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        subprocess.run(["git", "read-tree", "HEAD"], cwd=str(lg.root), env=env, capture_output=True)
        for unit, data in sorted(patches.items()):
            if not data.strip():
                continue
            proc = subprocess.run(["git", "apply", "--cached", "--whitespace=nowarn", "-"], cwd=str(lg.root),
                                  env=env, input=data, capture_output=True)
            if proc.returncode != 0:
                return (f"the patch of {unit} would not apply again on top of the others "
                        f"({clean(proc.stderr.decode(errors='replace').strip(), 200)})")
    return ""


def worktree_patch(lg: Ledger, paths: list) -> bytes:
    """The working tree's changes to these paths against HEAD, as a patch `git apply` takes back. Plumbing
    ignores the user's diff settings (external drivers, prefixes, colors, context size, textconv)."""
    return run(["git", "diff-index", "-p", "--binary", "HEAD", "--"] + paths, lg.root).stdout


def differs_from_head(lg: Ledger, path: str) -> bool:
    blob = run(["git", "cat-file", "blob", f"HEAD:{path}"], lg.root, check=False)
    try:
        return blob.returncode != 0 or (lg.root / path).read_bytes() != blob.stdout
    except OSError:
        return False


def save_copy(lg: Ledger, paths: list, causes: dict, patch=None) -> str:
    """Keep what a restore is about to discard, in a new numbered folder under .dead-code/restored/: the
    files as they are (any that differ from HEAD, even where git shows no diff), a patch of them against HEAD
    (`git apply -3` takes it back) and of what the index held. Recorded in the state with HEAD, each file's
    cause and the digest of everything written, so that the report can tell the user's own change from an
    agent's, and a copy altered since from one to trust. Returns the folder, or "" when nothing differs."""
    earlier = patch is not None
    patch = patch if earlier else (worktree_patch(lg, paths) if paths else b"")
    staged = b"" if earlier or not paths else \
        run(["git", "diff-index", "--cached", "-p", "--binary", "HEAD", "--"] + paths, lg.root).stdout
    files = [] if earlier else [p for p in paths if (lg.root / p).is_file() and not (lg.root / p).is_symlink()
                                and differs_from_head(lg, p)]
    if not patch.strip() and not staged.strip() and not files:
        return ""
    folder = new_copy_folder(lg)
    written = {"changes.patch": patch}
    if staged.strip():
        written["staged.patch"] = staged
    for p in files:
        try:
            written["files/" + p] = (lg.root / p).read_bytes()
        except OSError:
            pass
    for name, data in written.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    name = folder.relative_to(lg.root).as_posix()
    lg.state.setdefault("restored", []).append({"folder": name, "head": lg.head(), "at": now(),
                                                "files": {p: causes.get(p, "") for p in paths},
                                                "hashes": {k: digest(v) for k, v in written.items()}})
    return name


def new_copy_folder(lg: Ledger) -> Path:
    """A new numbered folder for a copy under .dead-code/restored, or under the first name after it (restored.d,
    restored.2, ...) when a file or a link took that name: a copy is never written through it."""
    for k in range(100):
        top = lg.dir / ("restored" if k == 0 else "restored.d" if k == 1 else f"restored.{k}")
        if top.is_symlink() or (top.exists() and not top.is_dir()):
            continue
        first = 1 + max([int(p.name) for p in top.glob("[0-9][0-9][0-9]") if p.is_dir()] + [0])
        for n in range(first, first + 1000):
            try:
                (top / f"{n:03d}").mkdir(parents=True)
                if k:
                    print(f"note: {LEDGER}/restored is taken by something the ledger did not make (a file or a link): "
                          f"this copy goes to {top.relative_to(lg.root).as_posix()}")
                return top / f"{n:03d}"
            except FileExistsError:
                continue
            except OSError:  # the name was taken meanwhile
                break
    die(f"no folder for a copy can be made under {lg.dir / 'restored'} or the names after it: stop and ask the user")


def copy_intact(root: Path, entry: dict) -> bool:
    """Whether the files the ledger saved in a copy still hold exactly what it wrote: an agent can write under
    .dead-code/, and a copy it altered is never one to apply. A file added since (a Finder .DS_Store, or an
    agent's) leaves the copy intact: copy_extras names it, and the report says never to apply it."""
    folder, hashes = root / str(entry.get("folder", "")), entry.get("hashes")
    if not isinstance(hashes, dict) or not hashes or not folder.is_dir() or folder.is_symlink():
        return False
    try:
        return all(not (folder / k).is_symlink() and digest((folder / k).read_bytes()) == v for k, v in hashes.items())
    except OSError:
        return False


def copy_extras(root: Path, entry: dict) -> list:
    """The files of a saved copy the ledger did not write there."""
    folder, hashes = root / str(entry.get("folder", "")), entry.get("hashes")
    hashes = hashes if isinstance(hashes, dict) else {}
    try:
        return sorted(k for k in (p.relative_to(folder).as_posix() for p in folder.rglob("*")
                                  if p.is_symlink() or not p.is_dir()) if k not in hashes)
    except OSError:
        return []


def gitlinks(lg: Ledger, paths: list) -> set:
    """The paths among these that are submodules, in the index or in HEAD: their work lives in another
    repository, and the run never restores them."""
    if not paths:
        return set()
    links = set()
    for cmd in (["git", "ls-files", "-s", "-z", "--"], ["git", "ls-tree", "-z", "HEAD", "--"]):
        out = os.fsdecode(run(cmd + list(paths), lg.root, check=False).stdout)
        links |= {e.partition("\t")[2] for e in out.split("\0") if e.startswith("160000 ")}
    return links


def layout_changed(lg: Ledger, path: str) -> bool:
    """Whether a folder now stands where HEAD has the file `path`, or a file where HEAD has one of its folders:
    `git restore` would delete what is in the way, with nothing kept. A path HEAD does not hold as a file (a
    folder someone committed since, a file only the index added) is never written back by a restore."""
    if not lg.in_head(path):
        return False
    full = lg.root / path
    if full.is_dir() and not full.is_symlink():
        return True
    parent = full.parent
    while parent != lg.root and lg.root in parent.parents:
        if parent.exists() and (not parent.is_dir() or parent.is_symlink()):
            return True
        parent = parent.parent
    return False


def at_head(lg: Ledger, paths: list) -> list:
    """The paths whose working tree and index hold what the last commit has (a file, or a folder), with nothing
    untracked under them: the change that queued them was committed or undone since."""
    if not paths:
        return []
    differ = set()
    for cmd in (["git", "diff", "--no-renames", "--name-only", "-z", "HEAD", "--"],
                ["git", "diff", "--no-renames", "--cached", "--name-only", "-z", "HEAD", "--"],
                ["git", "ls-files", "-o", "--exclude-standard", "-z", "--"]):
        proc = run(cmd + list(paths), lg.root, check=False)
        if proc.returncode != 0:
            return []
        differ |= set(os.fsdecode(proc.stdout).split("\0")) - {""}
    return [p for p in paths if not any(d == p or d.startswith(p + "/") for d in differ)]


def uncopyable(lg: Ledger, path: str) -> bool:
    """Whether a queued path is something no copy can be kept of: a FIFO, a socket or a device where the last
    commit has a file, or a file the ledger may not read."""
    full = lg.root / path
    try:
        if full.is_symlink() or full.is_dir() or not full.exists():
            return False
        return not full.is_file() or not os.access(full, os.R_OK)
    except OSError:
        return True


def cmd_restore(args) -> None:
    """Put the queued files back to their committed state, keeping a copy of what goes."""
    lg = Ledger(git_root()).load()
    paths = lg.state.get("restore", [])
    moved = moved_head(lg)
    if moved and set(paths) & wave_files(lg):
        die(moved_step(lg, moved))
    links = gitlinks(lg, paths)
    hidden = (set(tracked_files(lg.root, list(paths))) if paths else set()) - lg.tracked()
    # A path back at HEAD needs nothing, whoever put it there: a folder that replaced a file and was committed as it
    # stands would block the queue for good otherwise.
    done = at_head(lg, [p for p in paths if p not in links and p not in hidden])
    if done:
        paths = [p for p in paths if p not in done]
        lg.state["restore"] = paths
        for p in done:
            lg.state.get("restore_causes", {}).pop(p, None)
        lg.save()
        print(f"{len(done)} queued path(s) already match the last commit (committed or put back since), so they leave "
              "the queue: " + ", ".join(clean(p) for p in done[:8]))
    blocked = sorted(hidden | {p for p in paths if p not in links and layout_changed(lg, p)})
    if blocked:
        die(f"restore would destroy {', '.join(clean(p) for p in blocked[:5])}: a folder stands where the last commit "
            "has a file (or the reverse), or git hides the file (assume-unchanged, skip-worktree); nothing was "
            "restored: stop and ask the user. A path leaves the queue once it matches the last commit again (the user "
            "commits it as it stands, or puts it back) and git no longer hides it (`git update-index "
            "--no-assume-unchanged -- <path>`, then `git update-index --no-skip-worktree -- <path>`); then "
            "`ledger.py restore` again")
    odd = sorted(p for p in paths if p not in links and lg.in_head(p) and uncopyable(lg, p))
    if odd:
        die(f"restore cannot keep a copy of {', '.join(clean(p) for p in odd[:5])}: not a regular file (a FIFO, a "
            "device), or one the ledger may not read; nothing was restored: stop and ask the user to make it a "
            "readable file again, or to put it back as the last commit has it; then `ledger.py restore` again")
    paths = [p for p in paths if p not in links]
    in_head = [p for p in paths if lg.in_head(p)]
    added = [p for p in paths if not lg.in_head(p)]  # only in the index: unstaged, and the file is kept
    saved = save_copy(lg, in_head, lg.state.get("restore_causes", {}))
    if saved:
        lg.save()  # the copy is on record before git discards anything: a restore cut short never orphans it
    if in_head:
        run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"] + in_head, lg.root)
    if added:
        run(["git", "restore", "--staged", "--"] + added, lg.root, check=False)
    lg.state["restore"], lg.state["restore_causes"] = [], {}
    lg.save()
    print(f"restored {len(in_head)} file(s) to HEAD" + (": " + ", ".join(clean(p) for p in in_head[:8]) if in_head else ""))
    if added:
        print(f"unstaged {len(added)} file(s) the index had added, keeping them: " + ", ".join(clean(p) for p in added[:8]))
    if saved:
        print(f"what they held is saved in {saved} (`git apply -3 {saved}/changes.patch` takes it back; the files "
              f"as they were are in {saved}/files)")
    if links:
        print(f"submodule(s) {', '.join(clean(p) for p in sorted(links)[:5])} point at another commit: the run never "
              "restores a submodule; stop and ask the user")
        return
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
    if lg.state.get("finished"):
        die("the run is finished (a second wrong spot-check, a decline, or its last round): `ledger.py report`")
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
    where = clean(f"{c['file']}:{c['line']}" if c.get("line") else c["file"])
    print(f"  {c['id']} [{c['status']}] {c['kind']} `{clean(c['symbol'], 120)}` at {where}"
          f" (refs: code {refs.get('other', 0)}, same file {refs.get('same_file', 0)}, tests {refs.get('tests', 0)},"
          f" docs {refs.get('docs', 0)})")
    for s in refs.get("sample", [])[:4]:
        print(f"      mention: {clean(s)}")
    for lens in LENSES:
        v = c["votes"].get(lens)
        if v:
            print(f"      {lens}: {v['verdict']} {v['confidence']} - {clean(v['evidence'], 220)}")
    if c.get("note"):
        print(f"      note: {clean(c['note'], 220)}")


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
        # The script tallies the votes: `dead` is for candidates the three lenses already voted dead
        # (bisect's innocent waves), never a way past them, past --protect, or into a dependency.
        if args.status in ("pending", "dead") and c["kind"] == "dependency":
            die(f"{cid} is a dependency: the report lists it for the package manager; no lens or agent handles it")
        if args.status == "dead" and (c["status"] == "reverted" or c["status"] == "alive" and c.get("pinned")):
            die(f"{cid} was proven alive (by the gate, or by a human): `--status pending` sends it back to the lenses")
        if args.status == "dead" and tally(c) != "dead":
            die(f"{cid} lacks three dead votes: only the lenses decide that code is dead; `--status pending` "
                "sends it back to them")
        if args.status == "dead" and (lg.is_protected(c["file"]) or matches(c["file"], NEVER_SCAN)):
            die(f"{cid} is under a protected, vendored, generated or migration path, which is never deleted")
        u = lg.state["units"].get(c.get("unit") or "")
        if c["status"] in ("planned", "applied") and u and u["status"] != "ready":
            die(f"{cid} is in removal unit {u['id']}, already {u['status']}: finish that wave, "
                f"or `ledger.py settle --fail {u['id']}`")
        if c["status"] == "planned" and u and cid in u.get("covered", {}):
            if args.status == "dead":
                continue  # it goes with its file already
            # Something inside the file is not dead after all: the file stays, its other declarations go back
            # to dead to be planned one by one, and this one takes the status asked for.
            fid = u["covered"][cid]
            drop_from_unit(lg, u, fid)
            lg.cands[fid]["unit"] = None
            set_status(lg.cands[fid], "unsure", f"{cid} `{clean(c['symbol'], 80)}` in it was marked {args.status}: "
                                                "the file stays")
            print(f"{fid} (its file, {clean(c['file'], 120)}) stays: {cid} was marked {args.status}")
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
    keep = [lg.cands[x] for x in u["candidates"]]
    dying = {c["file"] for c in lg.cands.values() if c["kind"] == "file" and c["status"] in ("planned", "applied")
             and c["id"] != cid}
    u["deletes"] = sorted(c["file"] for c in keep if c["kind"] == "file")
    u["allowed"] = sorted(({c["file"] for c in keep} | {e["file"] for c in keep for e in c["also_edit"]})
                          - set(u["deletes"]) - dying)
    u["agent"] = bool(remove_edits(lg, u))
    if not u["candidates"]:
        u["status"] = "settled"


def cmd_ignore(args) -> None:
    """Let check ignore the untracked files that match now: build or test artifacts. A file that appears
    later, maybe planted by an agent, is judged again even when it matches. Of the changes `git status`
    cannot show, those at the paths the globs name are accepted as they are now, and only those."""
    lg = Ledger(git_root()).load()
    hits = sorted({p for code, p in status_entries(lg) if code == "??" and matches(p, args.globs)})
    lg.state["untracked"] = sorted(set(lg.state.get("untracked", [])) | set(hits))
    lg.state.setdefault("ignore", []).extend(args.globs)
    for p in [p for p in lg.state.get("preexisting") or {} if matches(p, args.globs)]:
        try:  # the user said this change of theirs is fine
            st = (lg.root / p).stat()
            lg.state["preexisting"][p] = [st.st_size, st.st_mtime_ns]
        except OSError:
            del lg.state["preexisting"][p]
    # Of the changes `git status` cannot show, only those of the paths the globs name are accepted: any other one
    # (an agent's plant next to the user's own change) stays reported.
    accepted = accept_hidden(lg, args.globs)
    lg.save()
    print(f"{len(hits)} untracked file(s) matching {', '.join(args.globs)} are ignored by check from now on; one "
          "that appears later is judged again, and a change to a tracked file always counts")
    if accepted:
        print(f"{len(accepted)} change(s) `git status` cannot show are accepted as they are now: "
              + ", ".join(clean(p) for p in accepted[:8]))
    left = hidden_changes(lg)
    if left:
        print(f"{len(left)} other change(s) `git status` cannot show are still pending, e.g. {left[0]}: no glob given "
              "names them")
        say_next("ledger.py check (it lists them again: ask the user about each before ignoring it)")
        return
    say_next(next_step(lg))


def accept_hidden(lg: Ledger, globs: list) -> list:
    """Take what is now at the ignored paths and skipped files the globs name (a folder as listed, `dist/`, or by
    its name, `dist`) into the reference of hidden_changes, and .git/info/exclude when a glob names it. Returns the
    paths whose change was accepted."""
    before = lg.state.get("hidden")
    if not isinstance(before, dict):
        return []
    now_, accepted = hidden_snapshot(lg), []
    for key in ("ignored", "skipped"):
        old = dict(before.get(key) or {})
        for p in sorted(set(old) | set(now_[key])):
            if (matches(p, globs) or matches(p.rstrip("/"), globs)) and old.get(p) != now_[key].get(p):
                accepted.append(p)
                if p in now_[key]:
                    old[p] = now_[key][p]
                else:
                    del old[p]
        before[key] = old
    if matches(".git/info/exclude", globs) and before.get("exclude") != now_["exclude"]:
        before["exclude"] = now_["exclude"]
        accepted.append(".git/info/exclude")
    return accepted


def cmd_round(args) -> None:
    lg = Ledger(git_root()).load()
    busy = Counter(c["status"] for c in lg.cands.values() if c["status"] in IN_FLIGHT)
    if busy and not args.force:
        die("the round is not finished: " + ", ".join(f"{k} {v}" for k, v in busy.items()))
    step = next_step(lg)
    if step != "ledger.py round" and not args.force:
        die(f"the round is not over yet: {step}")
    if changed_paths(lg, untracked=False) and not args.force:
        die("tracked files have uncommitted changes: `ledger.py check` lists them; if no agent of this run made "
            "them, ask the user before `ledger.py restore` puts them back")
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
        print(f"{len(proposed)} file(s) left without declarations are now candidates: "
              f"{', '.join(clean(p) for p in proposed[:8])}")
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
                rest = line.split(block, 1)[1].strip()
                block = None
                if re.sub(r"""^(from\s*(["'`]).*?\2)?\s*;?$""", "", rest):
                    return False  # `} from "./a"; a.init();`: a statement after the import
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
        if re.match(r"^(await\s+)?using\s+[\w$]+\s*=", line) or (line.startswith("import") and
                                                                 re.match(r"^import\s*\(", line) and line != "import ("):
            return False  # `using x = open()` runs code, and so does a dynamic `import("./x")`
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
    """This round committed waves (removals still in place or reverted since), and the full gate has not
    passed on the current commit."""
    committed = any(h["round"] == lg.state["round"] and h.get("commit") for h in lg.state["history"])
    return bool(committed and lg.state["gate"].get("full") and lg.state.get("full_gate_head") != head_sha(lg))


def round_waves(lg: Ledger) -> list:
    """This round's wave commits whose removals are still in place, oldest first."""
    return [h["commit"] for h in lg.state["history"] if h["round"] == lg.state["round"] and h.get("commit")
            and any(c.get("commit") == h["commit"] and c["status"] == "removed" for c in lg.cands.values())]


def clear_bisect(lg: Ledger) -> None:
    """Undo bisect's reverts: forget the revert in progress, and put back only the files the reverted
    commits touched, after keeping any edit made to them while the suite ran. Nothing else in the tree
    is touched, so a change made elsewhere meanwhile stays."""
    files = (lg.state.get("bisecting") or {}).get("files", [])
    run(["git", "revert", "--quit"], lg.root, check=False)
    if files:
        # The reverts staged their own changes, so an edit made during the search differs from the index.
        edited = [p for p in run(["git", "diff-files", "--name-only", "-z", "--"] + files, lg.root).stdout
                  .decode("utf-8", "replace").split("\0") if p and p in files]
        if edited:
            save_copy(lg, edited, {p: "edited while bisect ran the suite: maybe someone's own change" for p in edited})
        indexed = set(run(["git", "ls-files", "-z", "--"] + files, lg.root).stdout.decode("utf-8", "replace").split("\0"))
        known = [p for p in files if lg.in_head(p) or p in indexed]
        keep_folders(lg, known, "written where a reverted commit has a file while bisect ran the suite: maybe "
                                "someone's own change")
        if known:
            run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"] + known, lg.root, check=False)
    lg.state["bisecting"] = None


def cmd_bisect(args) -> None:
    """Find the wave commit of this round that breaks the full gate."""
    lg = Ledger(git_root()).load()
    if lg.state.get("bisecting"):
        print("the last bisect was cut short: its reverts are undone first")
        clear_bisect(lg)
        lg.save()
    if wrong_branch(lg):
        die(wrong_branch(lg))
    applied = round_waves(lg)
    gate = gate_command(lg, "full")
    if not applied or not gate:
        die("this round has no wave commit still in place (or no gate) to search")
    if changed_paths(lg, untracked=False):
        die("tracked files have changes: `ledger.py check` lists them; if no agent of this run made them, ask the "
            "user before `ledger.py restore` puts them back")
    if user_files_changed(lg) or hidden_changes(lg):
        die("files changed where `git status` cannot show them: `ledger.py check` first")
    head = head_sha(lg)
    # Every file a revert can touch: putting back only these leaves the rest of the tree alone.
    files = sorted({p for sha in applied for p in changed_between(lg, f"{sha}^", sha)})
    lg.state["bisecting"] = {"head": head, "files": files}
    lg.save()
    before = status_entries(lg)
    # Revert the waves newest first, keeping each revert, until the suite passes: the last wave
    # reverted is the culprit. Reverting in the reverse order of the commits always applies, even
    # when consecutive waves edited the same file. Waves already reverted are not in `applied`.
    culprit, reverted, timed_out, finished = None, [], False, False
    with signals_raise():
        try:
            for sha in reversed(applied):
                checkpoint()
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
            else:
                finished = True  # every wave reverted and still red: no wave of this round explains it
            finished = finished or culprit is not None
        finally:
            clear_bisect(lg)
            tool_leftovers(lg, before, "the full gate changed it while bisect ran it")
            if finished:  # only a search that ran to its end is a verdict; a stopped one says nothing
                lg.state.setdefault("bisects", {})[head] = culprit or ""
            lg.save()
    checkpoint()
    if not finished and not timed_out:
        say_next("the search stopped before a verdict (a revert that did not apply): run `ledger.py gate full` "
                 "again; if it stays red, `ledger.py bisect` again, or stop and tell the user")
        return
    if timed_out:
        say_next(f"the suite timed out: `ledger.py bisect --timeout {2 * args.timeout}`")
        return
    if culprit is None:
        say_next("no wave commit of this round explains the failure (flaky, or broken before the round): run "
                 "`ledger.py gate full` again; if it stays red, stop and tell the user")
        return
    alone = run(["git", "revert", "--no-commit", culprit], lg.root, check=False).returncode == 0
    lg.state["bisecting"] = {"head": head, "files": files}
    clear_bisect(lg)
    lg.save()
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
    holder = lock_holder(lg.dir / "lock")
    if holder and holder != os.getpid():
        return (f"wait: another ledger command (pid {holder}) is still running; when it has finished, `ledger.py "
                "status` (if no ledger command runs any more, delete .dead-code/lock)")
    if st.get("finding"):
        return "ledger.py settle --find (the last one was cut short: it puts the whole wave back first)"
    if st.get("bisecting"):
        return "ledger.py bisect (the last one was cut short: it undoes its reverts first)"
    statuses = Counter(c["status"] for c in lg.cands.values())
    dispatched = lg.units(status="dispatched")
    if dispatched:
        stage = dispatched[0]["stage"]
        return (f"wait for the {stage} workflow's completion notice, then `ledger.py ingest {stage}` (if no "
                f"workflow is running any more, ingest anyway: units without output are dispatched again)")
    if st.get("restore"):
        return "ledger.py restore"
    if open_removal_units(lg):
        moved = moved_head(lg)
        if moved:
            return moved_step(lg, moved)
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
        if outcome == "rewritten":
            rewritten = set(st.get("rewritten") or [])
            owners = " ".join(f"--fail {u['id']}" for u in open_removal_units(lg)
                              if rewritten & set(u["allowed"] + u["deletes"]))
            return ("the fast gate rewrites this wave's own files (a formatter, `--fix`, or a code generator), so no "
                    "removal in them can be committed: stop and tell the user (protect generated files, or record a "
                    "gate that only checks)" + (f"; to go on without them, `ledger.py settle {owners} --note \"the gate "
                                                "rewrites its files\"`, then `ledger.py restore` and `ledger.py gate fast`"
                                                if owners else ""))
        if outcome == "rejected":
            return ("a commit hook rejected this wave: `ledger.py settle --fail <unit>` for the units it names, or "
                    "stop and ask the user; never bypass the hook")
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
        culprit = st.get("bisects", {}).get(head_sha(lg))
        if culprit and culprit in round_waves(lg):
            return (f"`git revert --no-edit {culprit[:12]}`, then mark its candidates as `ledger.py bisect` said "
                    "(run it again to see that), then `ledger.py gate full`")
        if culprit == "" or not round_waves(lg):
            return ("the full gate fails at HEAD and no wave commit of this round explains it: stop, `ledger.py "
                    "report`, and tell the user")
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
            last = next((g for g in reversed(st.get("gates") or []) if g.get("kind") == kind), {})
            return f"ledger.py gate {kind} --timeout {2 * (last.get('timeout') or 1800)}"
        if outcome != "green":
            return f"ledger.py gate {kind}"
    return None


def cmd_status(args) -> None:
    lg = Ledger(git_root()).load()
    st = lg.state
    holder = lock_holder(lg.dir / "lock")
    if holder:
        print(f"a ledger command (pid {holder}) is still running: wait for it before anything else")
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
            names = ", ".join(f"{cid} {clean(lg.cands[cid]['symbol'], 80)} ({lg.cands[cid]['status']})"
                              for cid in u["candidates"])
            print(f"  {u['id']}: {names}")
            print(f"      edits {clean(' '.join(u['allowed'])) or '-'}"
                  + (f" | deletes {clean(' '.join(u['deletes']))}" if u["deletes"] else ""))
    working = {p for u in lg.units("remove", "dispatched") if u["wave"] == st.get("current_wave")
               for p in u["allowed"] + u["deletes"]}
    known = wave_files(lg) | working | set(st.get("restore", []))
    outside = [p for p in changed_paths(lg, untracked=False) if p not in known]
    if outside and not lg.units(status="dispatched"):
        print(f"warning: {len(outside)} tracked file(s) changed outside the open wave, e.g. {clean(outside[0])}: "
              "if no agent of this run made them, ask the user before `check` and `restore` put them back")
    for p in user_files_changed(lg):
        print(f"warning: the untracked file {clean(p)}, there before the run, changed or vanished: tell the user")
    branch = run(["git", "branch", "--show-current"], lg.root, check=False).stdout.decode().strip()
    if st.get("branch") and branch != st["branch"]:
        print(f"warning: the run works on branch {st['branch']}, but {branch or 'a detached HEAD'} is checked out: "
              f"`git switch {st['branch']}` first")
    say_next(next_step(lg))


def votes_line(c: dict) -> str:
    parts = [f"{lens}: {v['verdict']} {v['confidence']} ({clean(v['evidence'], 300)})"
             for lens, v in ((lens, c["votes"].get(lens)) for lens in LENSES) if v]
    return "; ".join(parts) or clean(c.get("note", ""))


# The languages a SARIF log covers depend on the tool that wrote it.
SARIF_EXTS = {"pmd": {".java"}, "gradle": {".java"}, "gradlew": {".java"}, "mvn": {".java"}, "mvnw": {".java"},
              "detekt": {".kt", ".kts"}, "detekt-cli": {".kt", ".kts"}, "dotnet": {".cs"}, "jb": {".cs"}}


def job_roots(lg: Ledger, job: dict) -> list:
    """The folders and files an analyzer command named, root-relative; [] when it named none."""
    cwd = lg.root / job["base"] if job["base"] else lg.root
    roots = []
    for a in job["argv"][1:]:
        if a in ("./...", "...", "."):
            a = "."
        elif a.startswith("-"):
            continue
        p = cwd / a
        if p.exists() and inside(p, lg.root) and not inside(p, lg.dir):
            roots.append(p.resolve().relative_to(lg.root.resolve()).as_posix())
    return roots


def analyzer_reach(lg: Ledger) -> list:
    """(name, extensions, root folders or None) for each analyzer the run used. None: the paths it read
    cannot be told (a report loaded with `import`, a command that named no path)."""
    out, seen = [], set()
    for job in lg.state.get("analyzer_cmds", []):
        name = job["source"] or job["tool"]
        exts = SARIF_EXTS.get(Path(job["argv"][0]).name, set()) if job["tool"] == "sarif" else \
            ANALYZER_EXTS.get(job["tool"], set())
        out.append((name, exts, job_roots(lg, job) or None))
        seen.add(name)
    for name in lg.state["analyzers"]:
        if name not in seen and name != "scan":
            out.append((name, ANALYZER_EXTS.get(name, set()), None))
    return out


def coverage_lines(lg: Ledger) -> list:
    """What the run examined and what it did not, computed from the tree, the analyzers and the scan units."""
    st = lg.state
    reach = analyzer_reach(lg)
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
        else:
            by = sorted(n for n, exts, roots in reach if suffix in exts and roots and
                        any(r == "." or path == r or path.startswith(r.rstrip("/") + "/") for r in roots))
            maybe = sorted(n for n, exts, roots in reach if suffix in exts and roots is None)
            if by:
                groups["examined by " + "/".join(by)].append(path)
            elif maybe:
                groups["extension covered by " + "/".join(maybe) + " (which paths it read is not known)"].append(path)
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
        return clean(f"{c['id']} `{c['file']}:{c['line']}`" if c.get("line") else f"{c['id']} `{c['file']}`")

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
    restored = [r for r in st.get("restored", []) if isinstance(r, dict) and (lg.root / str(r.get("folder"))).is_dir()]
    recorded = {r["folder"] for r in restored}
    planted = sorted(p.relative_to(lg.root).as_posix() for top in copy_tops(lg.dir)
                     for p in (top.iterdir() if top.is_dir() and not top.is_symlink() else [top])
                     if p.relative_to(lg.root).as_posix() not in recorded and holds_files(p))
    if restored or planted:
        lines += ["", "## Changes the run put back", "",
                  "Each folder holds the files as they were, `changes.patch` against the commit named and, when the "
                  "index held something else, `staged.patch`. Most are the run's own wrong removals, never to apply "
                  "again; a change marked as maybe someone's own is for the user to review, then `git apply -3` "
                  "its patches. A folder marked UNVERIFIED (altered since it was saved, carried from a run the ledger "
                  "could not vouch for, or never recorded) may hold someone's work, or an agent's plant: the user "
                  "checks it by hand, and it is never applied as it is.", ""]
        for r in restored:
            why = sorted(set(str(x) for x in (r.get("files") or {}).values()))
            intact, extra = copy_intact(lg.root, r), copy_extras(lg.root, r)
            if r.get("unverified"):
                label = (f"UNVERIFIED ({clean(r['unverified'], 200)}"
                         + ("" if intact or not r.get("hashes") else ", and changed since it was carried")
                         + "): it may hold someone's work, or an agent's plant; ")
            elif intact:
                label = ""
            elif r.get("hashes"):
                label = "ALTERED since it was saved, so UNVERIFIED: it may still hold someone's work, never apply it as it is; "
            else:
                label = "saved without digests, so UNVERIFIED: check it before applying; "
            lines.append((f"- `{clean(r['folder'])}` ({len(r.get('files') or r.get('hashes') or {})} file(s)"
                          + (f", against `{clean(r['head'][:12])}`" if r.get("head") else "") + "): " + label
                          + (f"also holds {len(extra)} file(s) the ledger did not write, e.g. `{clean(extra[0])}`: "
                             "never apply those; " if extra else "")
                          + clean("; ".join(why), 400)).rstrip("; :"))
        lines += [f"- `{clean(p)}`: UNVERIFIED, not recorded by the ledger (an agent's plant, or a copy a command saved "
                  "before it was killed): it may hold someone's work; never apply it as it is" for p in planted]
    mine = sorted(set(user_files_changed(lg)) | set(st.get("touched_by_tools") or []))
    if mine:
        lines += ["", "## Untracked files of the user's that changed during the run", ""] + [f"- `{clean(p)}`" for p in mine]
    last_full = next((g for g in reversed(st.get("gates") or []) if g.get("kind") == "full"), {})
    if st["gate"].get("full"):
        at_head = last_full.get("head") == head_sha(lg)
        lines += ["", "## Full gate", "", f"- At HEAD `{head_sha(lg)[:12]}`: "
                  + (last_full["outcome"] if at_head else "not run since the last commit")]
    lines += ["", "## Coverage", ""] + coverage_lines(lg)
    if st["notes"]:
        lines += ["", "## Facts given to the verifiers", ""] + [f"- {n}" for n in st["notes"]]
    out = Path(args.out) if args.out else lg.dir / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", errors="replace")
    print(f"report: {out}")
    print("summary: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(by.items())))
    for c in by.get("dead", [])[:args.examples]:
        print(f"  dead: {c['id']} {clean(c['file'])}:{c.get('line') or '-'} {c['kind']} {clean(c['symbol'], 80)}")
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
    s.add_argument("--ok", action="store_true", help="close a wave none of whose removals survived (else: commit)")
    s.add_argument("--fail", action="append", default=[], help="unit whose removals broke the gate (repeatable)")
    s.add_argument("--note", default="", help="the error that proved it alive")
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
    for stream in (sys.stdout, sys.stderr):  # text from agents can hold what no terminal encoding takes
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if args.cmd in ("status", "show"):
        args.func(args)
        return
    with ledger_lock(git_root()):
        end_orphans(Ledger(git_root()))  # a gate a killed command left running must not write into the wave
        if args.cmd == "init":  # locked too: it never starts over under a running command, nor ends its gate
            args.func(args)
            return
        # A `settle --find` or a bisect cut short leaves the tree half changed: only running it again, which
        # first puts the tree back, and the read-only commands may run until then.
        state = git_root() / LEDGER / "state.json"
        try:
            st = json.loads(state.read_bytes()) if state.exists() else {}
        except (ValueError, RecursionError, OSError):
            st = {}
        if isinstance(st, dict) and st.get("finding") and args.cmd not in ("settle", "report", "note"):
            die("a `settle --find` was cut short and left the wave half applied: run `ledger.py settle --find`, "
                "which puts the whole wave back first")
        if isinstance(st, dict) and st.get("bisecting") and args.cmd not in ("bisect", "report", "note"):
            die("a bisect was cut short and left its reverts in the tree: run `ledger.py bisect`, which undoes them "
                "first")
        args.func(args)


@contextlib.contextmanager
def ledger_lock(root: Path):
    """One ledger command at a time: two that load and save the run together lose each other's work."""
    path = root / LEDGER / "lock"
    if not path.parent.is_dir():
        yield
        return
    stale = "if no ledger command runs any more, delete .dead-code/lock"
    for _ in range(2):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            die(f"{path} is not a lock this script wrote: {stale}")
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            holder = lock_holder(path)
            if holder:
                die(f"another ledger command (pid {holder}) is still running: wait for it to finish, and never run "
                    f"two at once ({stale})")
            try:
                path.unlink()  # left by a command that was killed
            except FileNotFoundError:
                pass
            except OSError as err:
                die(f"cannot remove the stale {path} ({err}): {stale}")
    else:
        die(f"cannot take {path}: {stale}")
    os.write(fd, f"{os.getpid()} {process_stamp(os.getpid())}".encode())
    os.close(fd)
    try:
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def lock_holder(path: Path) -> int:
    """The pid of the live ledger command holding the lock, or 0. The lock names its process with the time it
    started, so a pid reused since, or a lock this script did not write, holds nothing."""
    try:
        pid_text, _, stamp = path.read_text().strip().partition(" ")
        pid = int(pid_text or 0)
    except (OSError, ValueError):
        return 0
    if pid <= 0:
        return 0
    now_stamp = process_stamp(pid)
    if now_stamp or stamp:
        return pid if now_stamp and now_stamp == stamp else 0
    try:  # the system cannot tell when a process started: whether it lives is all there is
        os.kill(pid, 0)
    except PermissionError:
        return pid
    except OSError:
        return 0
    return pid


if __name__ == "__main__":
    main()
