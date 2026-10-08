#!/usr/bin/env python3
"""End-to-end tests for ledger.py: a scratch git repository, fake agent outputs, no network.

Run: python3 test_ledger.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parent / "ledger.py"


class Repo:
    def __init__(self, files: dict):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.write(files)
        self.commit("init")

    def write(self, files: dict) -> None:
        for path, text in files.items():
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def git(self, *args: str) -> str:
        cmd = ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args]
        return subprocess.run(cmd, cwd=self.root, check=True, capture_output=True, text=True).stdout

    def commit(self, msg: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", msg)

    def ledger(self, *args: str, ok: bool = True) -> str:
        proc = subprocess.run([sys.executable, str(LEDGER), *args], cwd=self.root, capture_output=True, text=True)
        if ok and proc.returncode != 0:
            raise AssertionError(f"ledger {' '.join(args)} failed:\n{proc.stdout}{proc.stderr}")
        return proc.stdout + proc.stderr

    def cands(self) -> dict:
        items = json.loads((self.root / ".dead-code/candidates.json").read_text())["items"]
        return {c["symbol"]: c for c in items.values()}

    def unit(self, stage: str) -> dict:
        state = json.loads((self.root / ".dead-code/state.json").read_text())
        unit_id = max(u["id"] for u in state["units"].values() if u["stage"] == stage and u["status"] == "dispatched")
        return json.loads((self.root / f".dead-code/units/{unit_id}.json").read_text())

    def answer(self, stage: str, verdicts: dict) -> dict:
        """Write a fake verifier output: {symbol: (verdict, confidence)} for the open verify unit."""
        unit = self.unit(stage)
        by_id = {c["id"]: c for c in unit["candidates"]}
        lines = []
        for cid, c in by_id.items():
            verdict, conf = verdicts.get(c["symbol"], ("dead", 90))
            lines.append(json.dumps({"id": cid, "verdict": verdict, "confidence": conf, "evidence": "test"}))
        Path(unit["output"]).write_text("\n".join(lines) + "\n")
        return unit


APP = {
    ".gitignore": "node_modules/\n",
    "src/index.ts": 'import { used } from "./util";\nconsole.log(used());\n',
    "src/util.ts": "export function used() { return 1; }\nexport function stale() { return helper(); }\n"
                   "function helper() { return 2; }\n",
    "src/barrel.ts": 'export * from "./old-pricing";\n',
    "src/old-pricing.ts": "export const rate = 3;\n",
    "src/routes.ts": "const handlers = { refund: handle_refund };\nexport function handle_refund() {}\n",
    "tests/util.test.ts": 'import { onlyTested } from "../src/extra";\nonlyTested();\n',
    "src/extra.ts": "export function onlyTested() {}\n",
}

FINDINGS = "\n".join([
    "src/barrel.ts\t0\tbarrel\tfile\tanalyzer: unused file",
    "src/old-pricing.ts\t0\told-pricing\tfile\tanalyzer: unused file",
    "src/util.ts\t2\tstale\tfunction\tanalyzer: unused export",
    "src/routes.ts\t2\thandle_refund\tfunction\tanalyzer: unused export",
    "src/extra.ts\t1\tonlyTested\tfunction\tanalyzer: unused export",
    "package.json\t1\tleft-pad\tdependency\tanalyzer: unused dependency",
]) + "\n"


class LedgerFlow(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(APP)
        self.repo.ledger("init", "--gate-fast", "true", "--note", "Private app.")
        (self.repo.root / ".dead-code/findings.tsv").write_text(FINDINGS)
        self.repo.ledger("import", "--tool", "tsv", ".dead-code/findings.tsv", "--source", "analyzer")
        self.repo.ledger("refs")

    def tearDown(self):
        self.repo.tmp.cleanup()

    def verify_all(self, verdicts: dict) -> None:
        for _ in range(3):
            out = self.repo.ledger("dispatch", "verify")
            if "nothing to dispatch" in out:
                return
            self.repo.answer("verify", verdicts)
            self.repo.ledger("ingest", "verify")

    def remove_wave(self, edit) -> str:
        out = self.repo.ledger("dispatch", "remove")
        if "workflow-args" in out:
            unit = self.repo.unit("remove")
            applied = [e["id"] for e in unit["edits"] if e["remove"] == "the declaration"]
            edit(self.repo)
            Path(unit["output"]).write_text(json.dumps({"unit": unit["unit"], "applied": applied, "skipped": []}))
        self.repo.ledger("ingest", "remove")
        self.repo.ledger("check")
        return out

    def test_classification_after_refs(self):
        c = self.repo.cands()
        self.assertEqual(c["onlyTested"]["status"], "test-only")
        self.assertEqual(c["left-pad"]["status"], "dependency")
        self.assertEqual(c["old-pricing"]["refs"]["other"], 1, "hyphenated module counted as one token")
        self.assertEqual(c["barrel"]["refs"]["total"], 0)
        self.assertEqual(c["handle_refund"]["refs"]["same_file"], 1)

    def test_full_round_trip_and_transitive_round(self):
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
        c = self.repo.cands()
        self.assertEqual(c["barrel"]["status"], "dead")
        self.assertEqual(c["stale"]["status"], "dead")
        self.assertEqual(c["handle_refund"]["status"], "alive")
        self.assertIn("ask before deleting", self.repo.ledger("status"))
        self.assertIn("go-ahead", self.repo.ledger("dispatch", "remove"))

        self.repo.ledger("confirm")

        def delete_stale(repo):
            util = repo.root / "src/util.ts"
            util.write_text(util.read_text().replace("export function stale() { return helper(); }\n", ""))

        self.remove_wave(delete_stale)
        self.assertFalse((self.repo.root / "src/barrel.ts").exists(), "whole file deleted by ingest")
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "wave 1")
        self.repo.ledger("settle", "--ok", "--commit", "abc123")
        c = self.repo.cands()
        self.assertEqual(c["barrel"]["status"], "removed")
        self.assertEqual(c["stale"]["status"], "removed")

        self.repo.ledger("round")
        self.assertIn("ledger.py refs", self.repo.ledger("status"))
        self.repo.ledger("refs")
        c = self.repo.cands()
        self.assertEqual(c["old-pricing"]["status"], "pending", "its only importer is gone: vote again")

        (self.repo.root / ".dead-code/round2.tsv").write_text("src/util.ts\t2\thelper\tfunction\tanalyzer\n")
        self.repo.ledger("import", "--tool", "tsv", ".dead-code/round2.tsv")
        self.repo.ledger("refs")
        self.assertEqual(self.repo.cands()["helper"]["status"], "pending", "orphaned by the removal of stale")

    def test_red_gate_reverts_one_unit(self):
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
        self.repo.ledger("confirm")
        self.remove_wave(lambda repo: (repo.root / "src/util.ts").write_text("export function used() {}\n"))
        unit = next(u for u in json.loads((self.repo.root / ".dead-code/state.json").read_text())["units"].values()
                    if u["stage"] == "remove" and "src/util.ts" in u["allowed"])
        out = self.repo.ledger("settle", "--fail", unit["id"], "--note", "TS2304")
        self.assertIn("git restore --source=HEAD --staged --worktree -- src/util.ts", out)
        self.repo.git("restore", "--source=HEAD", "--staged", "--worktree", "--", "src/util.ts")
        self.repo.ledger("check")
        self.repo.ledger("settle", "--ok")
        c = self.repo.cands()
        self.assertEqual(c["stale"]["status"], "reverted")
        self.assertEqual(c["barrel"]["status"], "removed")

    def test_unapplied_removal_is_caught(self):
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
        self.repo.ledger("confirm")
        self.remove_wave(lambda repo: None)  # the remover claims success but edits nothing
        self.assertEqual(self.repo.cands()["stale"]["status"], "skipped")

    def test_low_confidence_and_bad_output(self):
        self.repo.ledger("dispatch", "verify")
        unit = self.repo.unit("verify")
        rows = [json.dumps({"id": c["id"], "verdict": "dead", "confidence": 60, "evidence": "x"})
                for c in unit["candidates"][1:]]
        Path(unit["output"]).write_text("not json\n" + "\n".join(rows) + "\n")
        out = self.repo.ledger("ingest", "verify")
        self.assertIn("invalid line", out)
        states = {c["id"]: c["status"] for c in self.repo.cands().values()}
        self.assertEqual(states[unit["candidates"][0]["id"]], "pending", "unanswered goes back to pending")
        self.assertEqual(states[unit["candidates"][1]["id"]], "likely-dead")

    def test_scope_guard(self):
        (self.repo.root / "stray.txt").write_text("x")
        out = self.repo.ledger("check", ok=False)
        self.assertIn("stray.txt", out)
        self.repo.ledger("dispatch", "verify")
        self.repo.answer("verify", {})
        self.assertIn("next: ledger.py check", self.repo.ledger("ingest", "verify"))

    def test_report(self):
        self.verify_all({"handle_refund": ("unsure", 40)})
        out = self.repo.ledger("report")
        report = (self.repo.root / ".dead-code/report.md").read_text()
        self.assertIn("ask before deleting", out)
        self.assertIn("## For a human: undecided", report)
        self.assertIn("left-pad", report)


class Scan(unittest.TestCase):
    def test_shard_dispatch_ingest(self):
        repo = Repo({"lib/cart.rb": "class Cart\n  def total; end\n  def stale; end\nend\nCart.new.total\n",
                     "app/foo.php": "<?php\nfunction unused_php() {}\n"})
        try:
            repo.ledger("init", "--report-only")
            self.assertIn("1 shard", repo.ledger("shard", "--ext", "rb", "--ext", "php"))
            repo.ledger("dispatch", "scan")
            unit = repo.unit("scan")
            rows = [{"file": "lib/cart.rb", "line": 1, "symbol": "Cart", "kind": "class"},
                    {"file": "lib/cart.rb", "line": 2, "symbol": "total", "kind": "method"},
                    {"file": "lib/cart.rb", "line": 3, "symbol": "stale", "kind": "method"},
                    {"file": "app/foo.php", "line": 2, "symbol": "unused_php", "kind": "function"},
                    {"file": "elsewhere.rb", "line": 1, "symbol": "Ghost", "kind": "class"}]
            Path(unit["output"]).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            self.assertIn("dropped 1 invalid", repo.ledger("ingest", "scan"))
            repo.ledger("refs")
            c = repo.cands()
            self.assertEqual(c["Cart"]["status"], "referenced")
            self.assertEqual(c["stale"]["status"], "pending")
            self.assertEqual(c["unused_php"]["status"], "pending")
            self.assertNotIn("Ghost", c)
        finally:
            repo.tmp.cleanup()


class Importers(unittest.TestCase):
    def setUp(self):
        self.repo = Repo({"pkg/core.py": "def dead():\n    pass\n", "src/lib.rs": "fn private_dead() {}\n",
                          "src/util.ts": "export const x = 1;\n", "src/App.java": "class App {\n  private void helper() {}\n}\n"})
        self.repo.ledger("init", "--report-only")

    def tearDown(self):
        self.repo.tmp.cleanup()

    def load(self, tool: str, text: str, *extra: str) -> str:
        path = self.repo.root / ".dead-code" / f"in.{tool}"
        path.write_text(text)
        return self.repo.ledger("import", "--tool", tool, str(path), *extra)

    def test_formats(self):
        self.load("vulture", "pkg/core.py:1: unused function 'dead' (60% confidence)\n"
                             "pkg/core.py:1: unused import 'os' (90% confidence)\n")
        self.load("cargo", json.dumps({"reason": "compiler-message", "message": {
            "code": {"code": "dead_code"}, "message": "function `private_dead` is never used",
            "spans": [{"is_primary": True, "file_name": "src/lib.rs", "line_start": 1}]}}) + "\n")
        self.load("knip", json.dumps({"issues": [{"file": "src/util.ts", "exports": [{"name": "x", "line": 1}],
                                                  "files": [], "dependencies": [{"name": "left-pad"}]}]}))
        self.load("sarif", json.dumps({"runs": [{"tool": {"driver": {"name": "PMD"}}, "results": [
            {"ruleId": "UnusedPrivateMethod", "message": {"text": "Avoid unused private methods such as 'helper()'."},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/App.java"},
                                                 "region": {"startLine": 2, "startColumn": 16}}}]},
            {"ruleId": "UnusedFormalParameter", "message": {"text": "Avoid unused parameters such as 's'."},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/App.java"},
                                                 "region": {"startLine": 2}}}]}]}]}))
        c = self.repo.cands()
        self.assertEqual(set(c), {"dead", "private_dead", "x", "left-pad", "helper"})
        self.assertEqual(c["helper"]["kind"], "method")
        self.assertEqual(c["left-pad"]["kind"], "dependency")


if __name__ == "__main__":
    unittest.main(verbosity=1)
