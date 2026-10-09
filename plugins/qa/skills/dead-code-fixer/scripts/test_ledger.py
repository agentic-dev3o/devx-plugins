#!/usr/bin/env python3
"""End-to-end tests for ledger.py: a scratch git repository, fake agent outputs, no network.

Run: python3 test_ledger.py
"""

from __future__ import annotations

import codecs
import json
import os
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

    def ledger(self, *args: str, ok: bool = True, env=None) -> str:
        proc = subprocess.run([sys.executable, str(LEDGER), *args], cwd=self.root, capture_output=True, text=True,
                              env=env)
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


def delete_stale(repo):
    util = repo.root / "src/util.ts"
    util.write_text(util.read_text().replace("export function stale() { return helper(); }\n", ""))


class LedgerFlow(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(APP)
        self.repo.ledger("init", "--gate-fast", "true", "--note", "Private app.")
        self.repo.ledger("gate", "fast")  # the baseline
        (self.repo.root / ".dead-code/findings.tsv").write_text(FINDINGS)
        self.repo.ledger("import", "--tool", "tsv", ".dead-code/findings.tsv", "--source", "analyzer")
        (self.repo.root / ".dead-code/scan.tsv").write_text("src/util.ts\t3\thelper\tfunction\tscanner\n")
        self.repo.ledger("import", "--tool", "tsv", ".dead-code/scan.tsv", "--source", "scan")
        self.repo.ledger("refs")

    def tearDown(self):
        self.repo.tmp.cleanup()

    def approve(self) -> None:
        if "re-check these" in self.repo.ledger("spotcheck"):
            self.repo.ledger("spotcheck", "--ok")
        self.repo.ledger("confirm")

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
        self.assertEqual(c["helper"]["status"], "referenced", "stale still calls it")
        self.assertIn("ledger.py spotcheck", self.repo.ledger("status"))
        self.assertIn("spot-check", self.repo.ledger("dispatch", "remove"))
        self.assertIn("spot-check", self.repo.ledger("confirm", ok=False))

        self.approve()

        self.remove_wave(delete_stale)
        self.assertFalse((self.repo.root / "src/barrel.ts").exists(), "whole file deleted by ingest")
        self.assertIn("ledger.py commit", self.repo.ledger("gate", "fast"))
        self.repo.ledger("commit")
        c = self.repo.cands()
        self.assertEqual(c["barrel"]["status"], "removed")
        self.assertEqual(c["stale"]["status"], "removed")
        log = self.repo.git("log", "--format=%s", "-1")
        self.assertIn("refactor(dead-code): remove", log)

        self.repo.ledger("round")
        self.assertIn("re-run this run's analyzers", self.repo.ledger("status"))
        (self.repo.root / ".dead-code/round2.tsv").write_text("src/old-pricing.ts\t0\told-pricing\tfile\tx\n")
        self.repo.ledger("import", "--tool", "tsv", ".dead-code/round2.tsv")
        self.repo.ledger("refs")
        c = self.repo.cands()
        self.assertEqual(c["old-pricing"]["status"], "pending", "its only importer is gone: vote again")
        self.assertEqual(c["helper"]["status"], "pending", "orphaned by the removal of stale")

    def test_file_left_empty_becomes_a_candidate_next_round(self):
        self.repo.write({"src/legacy.ts": '// Legacy helpers.\nimport { used } from "./util";\n\n'
                                          'export function legacy() { return used(); }\n'})
        self.repo.commit("legacy")
        (self.repo.root / ".dead-code/legacy.tsv").write_text("src/legacy.ts\t4\tlegacy\tfunction\tanalyzer\n")
        self.repo.ledger("import", "--tool", "tsv", ".dead-code/legacy.tsv")
        self.repo.ledger("refs")
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85), "barrel": ("alive", 95),
                         "stale": ("alive", 95), "onlyTested": ("alive", 95)})
        self.approve()

        def empty_legacy(repo):
            (repo.root / "src/legacy.ts").write_text('// Legacy helpers.\n')
        self.remove_wave(empty_legacy)
        self.repo.ledger("gate", "fast")
        self.repo.ledger("commit")
        out = self.repo.ledger("round")
        self.assertIn("src/legacy.ts", out)
        legacy = [c for c in self.repo.cands().values() if c["file"] == "src/legacy.ts" and c["kind"] == "file"]
        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy[0]["sources"], ["emptied"])

    def test_red_gate_reverts_one_unit(self):
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
        self.approve()
        self.remove_wave(delete_stale)
        unit = next(u for u in json.loads((self.repo.root / ".dead-code/state.json").read_text())["units"].values()
                    if u["stage"] == "remove" and "src/util.ts" in u["allowed"])
        out = self.repo.ledger("settle", "--fail", unit["id"], "--note", "TS2304")
        self.assertIn("ledger.py restore", out)
        self.assertIn("src/util.ts", self.repo.ledger("restore"))
        self.assertEqual(self.repo.git("status", "--porcelain", "--", "src/util.ts"), "")
        self.repo.ledger("check")
        self.repo.ledger("settle", "--ok")
        c = self.repo.cands()
        self.assertEqual(c["stale"]["status"], "reverted")
        self.assertEqual(c["barrel"]["status"], "removed")

    def test_over_deletion_is_rejected(self):
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
        self.approve()
        self.repo.ledger("dispatch", "remove")
        unit = self.repo.unit("remove")
        (self.repo.root / "src/util.ts").write_text("export function used() { return 1; }\n")  # stale AND helper
        Path(unit["output"]).write_text(json.dumps({"unit": unit["unit"], "applied": [e["id"] for e in unit["edits"]]}))
        out = self.repo.ledger("ingest", "remove")
        self.assertIn("rejected", out)
        self.assertIn("helper", out)
        self.assertEqual(self.repo.cands()["stale"]["status"], "dead", "back to dead for another wave")
        self.assertIn("src/util.ts", self.repo.ledger("check", ok=False), "unrestored files are strays")

    def test_skipped_whole_file_is_kept(self):
        (self.repo.root / ".dead-code/more.tsv").write_text("src/extra.ts\t0\textra\tfile\tanalyzer\n")
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85), "onlyTested": ("alive", 90)})
        c = self.repo.cands()
        self.assertEqual(c["barrel"]["status"], "dead")
        self.approve()
        self.repo.ledger("dispatch", "remove")
        state = json.loads((self.repo.root / ".dead-code/state.json").read_text())
        barrel_unit = next(u for u in state["units"].values() if u["stage"] == "remove" and "src/barrel.ts" in u["deletes"])
        spec = json.loads((self.repo.root / f".dead-code/units/{barrel_unit['id']}.json").read_text())
        Path(spec["output"]).write_text(json.dumps({"unit": spec["unit"], "applied": [],
                                                    "skipped": [{"id": c["barrel"]["id"], "reason": "cannot"}]}))
        barrel_unit["agent"] = True
        (self.repo.root / ".dead-code/state.json").write_text(json.dumps(state))
        for other in state["units"].values():
            if other["stage"] == "remove" and other["id"] != barrel_unit["id"] and other["status"] == "dispatched":
                o = json.loads((self.repo.root / f".dead-code/units/{other['id']}.json").read_text())
                Path(o["output"]).write_text(json.dumps({"unit": o["unit"], "applied": []}))
        self.repo.ledger("ingest", "remove")
        self.assertTrue((self.repo.root / "src/barrel.ts").exists())
        self.assertEqual(self.repo.cands()["barrel"]["status"], "skipped")

    def test_mark_guards_planned_candidates(self):
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
        self.approve()
        self.repo.ledger("dispatch", "remove")
        stale = self.repo.cands()["stale"]
        out = self.repo.ledger("mark", "--ids", stale["id"], "--status", "alive", ok=False)
        self.assertIn("already dispatched", out)

    def test_mark_drops_from_ready_unit(self):
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
        self.approve()
        self.repo.ledger("dispatch", "remove")  # plans every wave, dispatches the first
        state = json.loads((self.repo.root / ".dead-code/state.json").read_text())
        ready = [u for u in state["units"].values() if u["stage"] == "remove" and u["status"] == "ready"]
        if not ready:
            self.skipTest("everything fits in one wave")
        cid = ready[0]["candidates"][0]
        self.repo.ledger("mark", "--ids", cid, "--status", "alive", "--note", "spot-check")
        state = json.loads((self.repo.root / ".dead-code/state.json").read_text())
        self.assertNotIn(cid, state["units"][ready[0]["id"]]["candidates"])

    def test_dirty_tree_blocks_removal(self):
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
        self.approve()
        (self.repo.root / "src/index.ts").write_text("// edited\n")
        self.assertIn("ledger.py check", self.repo.ledger("dispatch", "remove"))

    def test_also_edit_outside_repo_or_protected_is_dropped(self):
        self.repo.ledger("dispatch", "verify")
        unit = self.repo.unit("verify")
        rows = [json.dumps({"id": c["id"], "verdict": "dead", "confidence": 90, "evidence": "x",
                            "also_edit": [{"file": "../../etc/passwd", "line": 1, "action": "x"},
                                          {"file": ".git/config", "line": 1, "action": "x"},
                                          {"file": ".dead-code/state.json", "line": 1, "action": "x"},
                                          {"file": "src/index.ts", "line": 1, "action": "drop import"}]})
                for c in unit["candidates"]]
        Path(unit["output"]).write_text("\n".join(rows) + "\n")
        self.repo.ledger("ingest", "verify")
        for c in self.repo.cands().values():
            for e in c["also_edit"]:
                self.assertEqual(e["file"], "src/index.ts")

    def test_unapplied_removal_is_caught(self):
        self.verify_all({"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
        self.approve()
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
        self.assertIn("spotcheck", out)
        self.assertIn("## For a human: undecided", report)
        self.assertIn("left-pad", report)


class Gates(unittest.TestCase):
    """Baseline, wave and round gates, commits, bisect, artifacts, declines and spot-checks."""

    def setUp(self):
        self.repo = Repo(APP)

    def tearDown(self):
        self.repo.tmp.cleanup()

    def start(self, *extra):
        self.repo.ledger("init", *extra)
        if "--gate-fast" in extra:
            self.repo.ledger("gate", "fast", ok=False)
        if "--gate-full" in extra:
            self.repo.ledger("gate", "full", ok=False)
        (self.repo.root / ".dead-code/findings.tsv").write_text(FINDINGS)
        self.repo.ledger("import", "--tool", "tsv", ".dead-code/findings.tsv", "--source", "analyzer")
        self.repo.ledger("refs")
        for _ in range(3):
            if "nothing to dispatch" in self.repo.ledger("dispatch", "verify"):
                break
            self.repo.answer("verify", {"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
            self.repo.ledger("ingest", "verify")

    def wave(self):
        out = self.repo.ledger("dispatch", "remove")
        if "workflow-args" in out:
            unit = self.repo.unit("remove")
            delete_stale(self.repo)
            Path(unit["output"]).write_text(json.dumps({"unit": unit["unit"], "applied": [
                e["id"] for e in unit["edits"] if e["remove"] == "the declaration"]}))
        self.repo.ledger("ingest", "remove")
        self.repo.ledger("check")

    def approve(self):
        self.repo.ledger("spotcheck")
        self.repo.ledger("spotcheck", "--ok")
        self.repo.ledger("confirm")

    def test_full_gate_red_bisects_and_reverts(self):
        self.start("--gate-fast", "true", "--gate-full", "test -f src/barrel.ts")
        self.approve()
        self.wave()
        self.repo.ledger("gate", "fast")
        self.repo.ledger("commit")
        self.assertIn("ledger.py gate full", self.repo.ledger("status"))
        out = self.repo.ledger("gate", "full", ok=False)
        self.assertIn("RED", out)
        self.assertIn("ledger.py bisect", self.repo.ledger("status"))
        out = self.repo.ledger("bisect")
        sha = self.repo.git("rev-parse", "HEAD").strip()
        self.assertIn(f"the suite passes once {sha[:12]} is reverted", out)
        self.assertEqual(self.repo.git("rev-parse", "HEAD").strip(), sha, "bisect leaves HEAD where it was")
        self.repo.git("revert", "--no-edit", sha)
        self.repo.ledger("mark", "--commit", sha[:12], "--status", "reverted", "--note", "test -f failed")
        self.assertIn("GREEN", self.repo.ledger("gate", "full"))
        self.assertIn("fixed point", self.repo.ledger("round"))
        self.assertTrue(self.repo.cands()["barrel"]["pinned"])

    def test_bisect_finds_a_middle_wave_that_cannot_be_reverted_alone(self):
        repo = Repo({"a.txt": "one\ntwo\nthree\nfour\n"})
        try:
            repo.ledger("init", "--gate-fast", "true", "--gate-full", "grep -q two a.txt")
            shas = []
            for gone in ("four\n", "two\n", "three\n"):  # wave 2 breaks the suite; wave 3 edits next to it
                path = repo.root / "a.txt"
                path.write_text(path.read_text().replace(gone, "", 1))
                repo.commit(f"wave without {gone.strip()}")
                shas.append(repo.git("rev-parse", "HEAD").strip())
            L = load_ledger_module()
            lg = L.Ledger(repo.root).load()
            for wave, sha in enumerate(shas, 1):
                cid = L.add_candidate(lg, file="a.txt", symbol=f"s{wave}", kind="function", source="t", line=wave)
                lg.cands[cid].update(status="removed", commit=sha)
                lg.state["history"].append({"round": 1, "wave": wave, "removed": 1, "commit": sha})
            lg.save()
            out = repo.ledger("bisect")
            self.assertIn(f"passes once {shas[1][:12]} is reverted", out)
            self.assertIn(f"git revert --no-edit {shas[2][:12]} {shas[1][:12]}", out)
            self.assertIn(f"mark --commit {shas[2][:12]} --status dead", out)
            self.assertEqual(repo.git("rev-parse", "HEAD").strip(), shas[2])
            self.assertEqual(repo.git("status", "--porcelain", "--untracked-files=no"), "")
        finally:
            repo.tmp.cleanup()

    def test_gate_artifacts_are_ignored_and_commit_takes_wave_files_only(self):
        self.start("--gate-fast", "touch build-cache.txt && echo log > gate.log")
        state = json.loads((self.repo.root / ".dead-code/state.json").read_text())
        self.assertEqual(sorted(state["ignore"]), ["build-cache.txt", "gate.log"], "the baseline left them")
        self.approve()
        self.wave()
        self.assertIn("GREEN", self.repo.ledger("gate", "fast"))
        self.repo.ledger("commit")
        files = self.repo.git("show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(sorted(files), ["src/barrel.ts", "src/util.ts"])
        self.repo.ledger("check")  # the artifacts are not strays

    def test_red_baseline_blocks_removal_and_resume_asks_for_it(self):
        self.repo.ledger("init", "--gate-fast", "true", "--gate-full", "false")
        self.assertIn("ledger.py gate fast", self.repo.ledger("status"), "a resumed run runs the baseline first")
        self.repo.ledger("gate", "fast")
        self.assertIn("ledger.py gate full", self.repo.ledger("status"))
        self.repo.ledger("gate", "full", ok=False)
        self.assertIn("the baseline is red", self.repo.ledger("status"))
        self.assertIn("baseline is red", self.repo.ledger("dispatch", "remove", ok=False))

    def test_gate_that_edits_a_tracked_file_gets_it_restored(self):
        self.start("--gate-fast", "echo formatted >> src/index.ts")
        self.assertIn("ledger.py restore", self.repo.ledger("status"))
        self.repo.ledger("restore")
        self.assertEqual(self.repo.git("status", "--porcelain", "--untracked-files=no"), "")

    def test_commit_needs_a_green_gate(self):
        self.start("--gate-fast", "test -f src/barrel.ts")
        self.approve()
        self.wave()
        self.assertIn("RED", self.repo.ledger("gate", "fast", ok=False))
        self.assertIn("has not passed", self.repo.ledger("commit", ok=False))

    def test_failing_every_unit_closes_the_wave(self):
        self.start("--gate-fast", "true")
        self.approve()
        self.wave()
        state = json.loads((self.repo.root / ".dead-code/state.json").read_text())
        units = [u["id"] for u in state["units"].values() if u["stage"] == "remove" and u["status"] == "ingested"]
        args = [a for u in units for a in ("--fail", u)]
        out = self.repo.ledger("settle", *args, "--note", "boom")
        self.assertIn("wave settled: 0", out)
        self.assertIsNone(json.loads((self.repo.root / ".dead-code/state.json").read_text())["current_wave"])

    def test_decline_finishes_as_a_report(self):
        self.start("--gate-fast", "true")
        self.repo.ledger("spotcheck")
        self.repo.ledger("spotcheck", "--ok")
        self.repo.ledger("confirm", "--no")
        self.assertIn("next: ledger.py report", self.repo.ledger("status"))
        self.assertIn("go-ahead", self.repo.ledger("dispatch", "remove"))

    def test_two_failed_spotchecks_stop_the_run(self):
        self.start("--gate-fast", "true")
        out = self.repo.ledger("spotcheck")
        ids = [line.split()[0] for line in out.splitlines() if line.startswith("  c")]
        self.repo.ledger("spotcheck", "--wrong", ids[0], "--note", "used via registry")
        self.assertTrue(self.repo.cands()[[k for k, c in self.repo.cands().items() if c["id"] == ids[0]][0]]["pinned"])
        out = self.repo.ledger("spotcheck")
        ids = [line.split()[0] for line in out.splitlines() if line.startswith("  c")]
        out = self.repo.ledger("spotcheck", "--wrong", ids[0])
        self.assertIn("miscalibrated", out)
        self.assertIn("ledger.py report", self.repo.ledger("status"))

    def test_analyze_runs_imports_and_reruns(self):
        self.repo.ledger("init", "--gate-fast", "true")
        self.assertIn("does not start", self.repo.ledger("analyze", "--tool", "tsv", "--", "sh", "-c", "id", ok=False))
        bin_dir = self.repo.root / ".dead-code" / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "vulture"
        fake.write_text("#!/bin/sh\necho \"src/util.ts:2: unused function 'stale' (60% confidence)\"\nexit 3\n")
        fake.chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
        out = self.repo.ledger("analyze", "--tool", "vulture", "--", "vulture", "src", env=env)
        self.assertIn("vulture: 1 new candidate", out)
        state = json.loads((self.repo.root / ".dead-code/state.json").read_text())
        self.assertEqual(state["analyzer_cmds"][0]["argv"], ["vulture", "src"])
        self.assertIn("0 new candidate", self.repo.ledger("analyze", "--again", env=env))
        fake.write_text("#!/bin/sh\necho boom >&2\nexit 2\n")
        self.assertIn("failed", self.repo.ledger("analyze", "--again", env=env))

    def test_sarif_exit_codes_follow_the_tool(self):
        self.repo.ledger("init", "--gate-fast", "true")
        bin_dir = self.repo.root / ".dead-code" / "bin"
        bin_dir.mkdir()
        sarif = {"runs": [{"results": [{"ruleId": "UnusedPrivateMember", "message": {"text": "Private function `stale` is unused."},
                 "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/util.ts"}, "region": {"startLine": 2}}}]}]}]}
        (bin_dir / "report.sarif").write_text(json.dumps(sarif))
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
        for program, code, imported in (("detekt", 2, True), ("pmd", 4, True), ("dotnet", 1, False)):
            fake = bin_dir / program
            fake.write_text(f"#!/bin/sh\ncp {bin_dir}/report.sarif .dead-code/out.sarif\nexit {code}\n")
            fake.chmod(0o755)
            out = self.repo.ledger("analyze", "--tool", "sarif", "--output", ".dead-code/out.sarif", "--source", program,
                                   "--", program, "build", env=env)
            self.assertEqual("failed" not in out, imported, out)

    def test_analyze_checks_the_command_shape_and_survives_a_bad_report(self):
        self.repo.ledger("init", "--gate-fast", "true")
        self.assertIn("does not start", self.repo.ledger("analyze", "--tool", "knip", "--", "npx", "-y", "evil", ok=False))
        self.assertIn("does not start", self.repo.ledger("analyze", "--tool", "vulture", "--", "python3", "-c", "1",
                                                         ok=False))
        bin_dir = self.repo.root / ".dead-code" / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "vulture"
        fake.write_text("#!/bin/sh\nexit 0\n")  # nothing found: vulture prints nothing
        fake.chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
        out = self.repo.ledger("analyze", "--tool", "vulture", "--", "vulture", "src", env=env)
        self.assertNotIn("failed", out)
        state = json.loads((self.repo.root / ".dead-code/state.json").read_text())
        self.assertEqual(len(state["analyzer_cmds"]), 1, "an empty report still records the command")
        knip = bin_dir / "knip"
        knip.write_text("#!/bin/sh\necho not json\nexit 0\n")
        knip.chmod(0o755)
        out = self.repo.ledger("analyze", "--tool", "knip", "--", "knip", "--reporter", "json", env=env)
        self.assertIn("not JSON", out)

    def test_missing_analyzer_is_reported(self):
        self.repo.ledger("init", "--gate-fast", "true")
        self.assertIn("not installed", self.repo.ledger("analyze", "--tool", "sarif", "--output", "x.sarif", "--",
                                                       "detekt", "-r", "sarif:x.sarif"))


class Flow2(unittest.TestCase):
    """next: lines around the baseline, the full gate after removals, narrowing a red wave, timeouts."""

    def setUp(self):
        self.repo = Repo(APP)

    def tearDown(self):
        self.repo.tmp.cleanup()

    def test_baseline_then_detection_then_full_gate_after_removals(self):
        self.repo.ledger("init", "--gate-fast", "true", "--gate-full", "true")
        self.repo.ledger("gate", "fast")
        out = self.repo.ledger("gate", "full")
        self.assertIn("detect:", out, "the baseline must lead to detection, not to `round`")
        (self.repo.root / ".dead-code/f.tsv").write_text(FINDINGS)
        self.repo.ledger("import", "--tool", "tsv", ".dead-code/f.tsv")
        self.repo.ledger("refs")
        for _ in range(3):
            if "nothing to dispatch" in self.repo.ledger("dispatch", "verify"):
                break
            self.repo.answer("verify", {"handle_refund": ("alive", 95), "old-pricing": ("alive", 85)})
            self.repo.ledger("ingest", "verify")
        self.repo.ledger("spotcheck")
        self.repo.ledger("spotcheck", "--ok")
        self.repo.ledger("confirm")
        self.repo.ledger("dispatch", "remove")
        unit = self.repo.unit("remove")
        delete_stale(self.repo)
        Path(unit["output"]).write_text(json.dumps({"unit": unit["unit"], "applied": [
            e["id"] for e in unit["edits"] if e["remove"] == "the declaration"]}))
        self.repo.ledger("ingest", "remove")
        self.repo.ledger("check")
        self.repo.ledger("gate", "fast")
        self.assertIn("ledger.py gate full", self.repo.ledger("commit"), "the baseline full gate does not cover removals")
        self.assertIn("full gate", self.repo.ledger("round", ok=False))
        self.repo.ledger("gate", "full")
        self.assertIn("ledger.py round", self.repo.ledger("status"))

    def removal_wave(self, gate: str) -> Repo:
        """A repo with four one-declaration units applied and waiting for the fast gate."""
        files = {f"src/m{i}.ts": f"export function keep{i}() {{}}\nexport function dead{i}() {{}}\n" for i in range(4)}
        repo = Repo(files)
        repo.ledger("init", "--gate-fast", gate)
        repo.ledger("gate", "fast")
        rows = "".join(f"src/m{i}.ts\t2\tdead{i}\tfunction\tx\n" for i in range(4))
        (repo.root / ".dead-code/f.tsv").write_text(rows)
        repo.ledger("import", "--tool", "tsv", ".dead-code/f.tsv")
        repo.ledger("refs")
        for _ in range(3):
            if "nothing to dispatch" in repo.ledger("dispatch", "verify"):
                break
            repo.answer("verify", {})
            repo.ledger("ingest", "verify")
        repo.ledger("spotcheck")
        repo.ledger("spotcheck", "--ok")
        repo.ledger("confirm")
        repo.ledger("dispatch", "remove")
        state = json.loads((repo.root / ".dead-code/state.json").read_text())
        for u in state["units"].values():
            if u["status"] != "dispatched":
                continue
            spec = json.loads((repo.root / f".dead-code/units/{u['id']}.json").read_text())
            for e in spec["edits"]:
                path = repo.root / e["file"]
                path.write_text(path.read_text().replace(f"export function {e['symbol']}() {{}}\n", ""))
            Path(spec["output"]).write_text(json.dumps({"unit": spec["unit"], "applied": [e["id"] for e in spec["edits"]]}))
        repo.ledger("ingest", "remove")
        repo.ledger("check")
        return repo

    def test_settle_find_fails_only_the_breaking_unit(self):
        repo = self.removal_wave("grep -q dead2 src/m2.ts")
        try:
            self.assertIn("RED", repo.ledger("gate", "fast", ok=False))
            out = repo.ledger("settle", "--find")
            self.assertIn("1 unit(s) failed", out)
            c = repo.cands()
            self.assertEqual(c["dead2"]["status"], "reverted")
            self.assertEqual(c["dead0"]["status"], "applied")
            self.assertIn("GREEN", repo.ledger("gate", "fast"))
            repo.ledger("commit")
            self.assertIn("dead2", (repo.root / "src/m2.ts").read_text())
            self.assertNotIn("dead0", (repo.root / "src/m0.ts").read_text())
        finally:
            repo.tmp.cleanup()

    def test_settle_find_blames_no_unit_for_a_gate_red_without_the_wave(self):
        repo = self.removal_wave("test ! -f flaky.flag")
        try:
            (repo.root / "flaky.flag").write_text("the environment changed\n")
            repo.ledger("gate", "fast", ok=False)
            out = repo.ledger("settle", "--find", ok=False)
            self.assertIn("even without any of this wave's removals", out)
            c = repo.cands()
            self.assertTrue(all(c[f"dead{i}"]["status"] == "applied" for i in range(4)))
            self.assertNotIn("dead0", (repo.root / "src/m0.ts").read_text(), "the wave is applied again")
        finally:
            repo.tmp.cleanup()

    def test_settle_find_waits_for_a_pending_restore(self):
        repo = self.removal_wave("grep -q dead2 src/m2.ts")
        try:
            repo.ledger("gate", "fast", ok=False)
            unit = next(u for u in json.loads((repo.root / ".dead-code/state.json").read_text())["units"].values()
                        if u["stage"] == "remove" and "src/m2.ts" in u["allowed"])
            repo.ledger("settle", "--fail", unit["id"])
            self.assertIn("restored first", repo.ledger("settle", "--find", ok=False))
            repo.ledger("restore")
            self.assertIn("GREEN", repo.ledger("gate", "fast"))
        finally:
            repo.tmp.cleanup()

    def test_gate_timeout_is_not_red(self):
        self.repo.ledger("init", "--gate-fast", "sleep 5")
        out = self.repo.ledger("gate", "fast", "--timeout", "1")
        self.assertIn("TIMEOUT", out)


class Precision(unittest.TestCase):
    """Reference counting and import adapters on awkward inputs."""

    def make(self, files):
        self.repo = Repo(files)
        self.repo.ledger("init", "--report-only")

    def tearDown(self):
        self.repo.tmp.cleanup()

    def tsv(self, text, source="analyzer"):
        (self.repo.root / ".dead-code/in.tsv").write_text(text)
        self.repo.ledger("import", "--tool", "tsv", ".dead-code/in.tsv", "--source", source)
        self.repo.ledger("refs")
        return self.repo.cands()

    def test_dollar_names_count(self):
        self.make({"src/Cart.php": "<?php\nclass Cart {\n  private $items = [];\n  function n() { return count($this->items); }\n}\n"})
        c = self.tsv("src/Cart.php\t3\titems\tmember\tx\n")
        self.assertEqual(c["items"]["refs"]["same_file"], 1)

    def test_same_name_twice_in_a_file_stays_two_candidates(self):
        self.make({"app/m.py": "class A:\n    def save(self):\n        pass\n\nclass B:\n    def save(self, force):\n        pass\n"})
        self.tsv("app/m.py\t2\tsave\tmethod\tx\napp/m.py\t6\tsave\tmethod\tx\n")
        items = json.loads((self.repo.root / ".dead-code/candidates.json").read_text())["items"]
        self.assertEqual(len(items), 2)
        for c in items.values():
            self.assertEqual(c["refs"]["same_file"], 0, "a twin declaration is not a use")

    def test_utf16_file_mentions_count(self):
        self.make({"src/a.ts": "export function legacyHook() {}\n"})
        (self.repo.root / "scripts").mkdir()
        (self.repo.root / "scripts/run.ps1").write_bytes(codecs.BOM_UTF16_LE + "legacyHook\r\n".encode("utf-16-le"))
        self.repo.commit("ps1")
        c = self.tsv("src/a.ts\t1\tlegacyHook\tfunction\tx\n")
        self.assertEqual(c["legacyHook"]["refs"]["other"], 1)

    def test_symlinks_are_not_read(self):
        self.make({"src/a.py": "def dead():\n    pass\n"})
        (self.repo.root / "src/b.py").symlink_to("a.py")
        self.repo.commit("link")
        c = self.tsv("src/a.py\t1\tdead\tfunction\tx\n")
        self.assertEqual(c["dead"]["refs"]["total"], 0)

    def test_docs_mentions_do_not_keep_scanner_candidates(self):
        self.make({"src/a.rb": "def stale_helper\nend\n", "README.md": "We used to call stale_helper.\n"})
        c = self.tsv("src/a.rb\t1\tstale_helper\tfunction\tscan\n", source="scan")
        self.assertEqual(c["stale_helper"]["status"], "pending")
        self.assertEqual(c["stale_helper"]["refs"]["docs"], 1)

    def test_convention_aliases_count(self):
        self.make({"app/models/line_item.rb": "class LineItem\nend\n",
                   "app/models/order.rb": "class Order\n  has_many :line_items\nend\n"})
        c = self.tsv("app/models/line_item.rb\t1\tLineItem\tclass\tscan\n", source="scan")
        self.assertEqual(c["LineItem"]["status"], "referenced")
        self.assertGreaterEqual(c["LineItem"]["refs"]["convention"], 1)

    def test_cargo_group_without_names(self):
        self.make({"src/lib.rs": "struct S;\nimpl S {\n    fn a(&self) {}\n    fn b(&self) {}\n}\n"})
        msg = {"reason": "compiler-message", "message": {"code": {"code": "dead_code"},
               "message": "multiple methods are never used", "spans": [
                   {"is_primary": True, "file_name": "src/lib.rs", "line_start": 3,
                    "text": [{"text": "    fn a(&self) {}", "highlight_start": 8, "highlight_end": 9}]},
                   {"is_primary": True, "file_name": "src/lib.rs", "line_start": 4,
                    "text": [{"text": "    fn b(&self) {}", "highlight_start": 8, "highlight_end": 9}]}]}}
        (self.repo.root / ".dead-code/c.json").write_text(json.dumps(msg) + "\n")
        self.repo.ledger("import", "--tool", "cargo", ".dead-code/c.json")
        self.assertEqual(set(self.repo.cands()), {"a", "b"})

    def test_sarif_escaped_uri_base_and_names(self):
        self.make({"my app/App.java": "class App {\n  private void importLegacy() {}\n}\n"})
        log = {"runs": [{"tool": {"driver": {"name": "PMD"}},
                         "originalUriBaseIds": {"SRC": {"uri": "file://" + str(self.repo.root).replace(" ", "%20") + "/"}},
                         "results": [{"ruleId": "UnusedPrivateMethod",
                                      "message": {"text": "Avoid unused private methods such as 'importLegacy()'."},
                                      "locations": [{"physicalLocation": {
                                          "artifactLocation": {"uri": "my%20app/App.java", "uriBaseId": "SRC"},
                                          "region": {"startLine": 2}}}]}]}]}
        (self.repo.root / ".dead-code/p.sarif").write_text(json.dumps(log))
        self.repo.ledger("import", "--tool", "sarif", ".dead-code/p.sarif")
        c = self.repo.cands()
        self.assertEqual(c["importLegacy"]["file"], "my app/App.java")

    def test_null_fields_in_agent_outputs_do_not_crash(self):
        self.make({"lib/a.rb": "class A\n  def x\n  end\nend\n"})
        self.repo.ledger("shard", "--ext", "rb")
        self.repo.ledger("dispatch", "scan")
        unit = self.repo.unit("scan")
        Path(unit["output"]).write_text(json.dumps({"file": "lib/a.rb", "line": 2, "symbol": "x", "kind": "method",
                                                    "markers": None}) + "\n")
        self.assertIn("1 new declaration", self.repo.ledger("ingest", "scan"))


def load_ledger_module():
    import importlib.util
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("ledger_under_test", LEDGER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stray(unittest.TestCase):
    """The diff check accepts exactly the deletion of the planned declarations and what served them."""

    L = load_ledger_module()

    def check(self, path, before, after, symbol, line):
        """`symbol` and `line` may be lists, for a unit that removes several declarations."""
        repo = Repo({path: before})
        try:
            (repo.root / path).write_text(after)
            lg = self.L.Ledger(repo.root)
            pairs = zip(symbol, line) if isinstance(symbol, list) else [(symbol, line)]
            cs = [{"id": f"c{i}", "file": path, "line": ln, "symbol": sym, "kind": "function", "also_edit": []}
                  for i, (sym, ln) in enumerate(pairs)]
            return self.L.stray_deletions(lg, {"allowed": [path], "deletes": []}, cs)
        finally:
            repo.tmp.cleanup()

    def ok(self, *args):
        self.assertEqual(self.check(*args), [])

    def rejected(self, *args):
        self.assertNotEqual(self.check(*args), [])

    def test_declares_nothing(self):
        nothing = self.L.declares_nothing
        self.assertTrue(nothing([]))
        self.assertTrue(nothing(['"""Old helpers."""', "", "import os", "from x import (", "    a,", ")", "# end"]))
        self.assertTrue(nothing(["// x", "/*", " * y", " */", 'import { a } from "./a";', 'export * from "./b";']))
        self.assertTrue(nothing(["package util", "", "import (", '\t"fmt"', ")"]))
        self.assertFalse(nothing(['export { a } from "./a";', "export const b = 1;"]))
        self.assertFalse(nothing(["const { a, b } = obj;"]))
        self.assertFalse(nothing(["module Helpers", "end"]))
        self.assertFalse(nothing(["#[derive(Debug)]", "struct A;"]))
        self.assertFalse(nothing(["#define X 1"]))
        self.assertFalse(nothing(["require('./server').start();"]))
        self.assertFalse(nothing(["import('./app').then(run);"]))
        self.assertFalse(nothing(["/* boot */ initTelemetry();"]))
        self.assertFalse(nothing(["<?php require 'x'; App\\Kernel::boot();"]))
        self.assertFalse(nothing(["import app.cli; app.cli.main()"], python=True))
        self.assertFalse(nothing(["import app.signals"], python=True))
        self.assertFalse(nothing(["package db", "", "import (", '\t_ "github.com/lib/pq"', ")"]))
        self.assertFalse(nothing(["package db", "//go:generate stringer -type=Kind"]))
        self.assertFalse(nothing(['import "./polyfills";']))
        self.assertTrue(nothing(["<?php", "namespace App;", "use App\\Models\\User;"]))
        self.assertTrue(nothing(["import java.util.List;", "package a.b;"]))

    def test_multi_line_signatures_and_decorators(self):
        keep = "\n\ndef keep():\n    return 0\n"
        self.ok("m.py", "import os\n\n\ndef compute(\n    amount,\n    rate,\n) -> int:\n    total = amount * rate\n"
                "    return total" + keep, "import os\n" + keep, "compute", 4)
        self.ok("k.py", "class Base:\n    pass\n\n\nclass Foo(\n    Base,\n):\n    x = 1\n\n    def m(self):\n"
                "        return 2" + keep, "class Base:\n    pass\n" + keep, "Foo", 5)
        self.ok("d.py", "import functools\n\n\n@functools.lru_cache(\n    maxsize=128,\n)\ndef f():\n    return 1" + keep,
                "import functools\n" + keep, "f", 7)
        self.ok("q.py", 'def query():\n    sql = """\nSELECT 1\nFROM t\n"""\n    return sql\n# a note\n    pass' + keep,
                keep.lstrip("\n"), "query", 1)
        self.ok("a.rb", "class A\n  def keep\n    1\n  end\n\n  def dead(a,\n           b)\n    a + b\n  end\nend\n",
                "class A\n  def keep\n    1\n  end\nend\n", "dead", 6)
        self.ok("A.java", "class A {\n    int keep() { return 1; }\n\n    int dead(int a,\n             int b)\n    {\n"
                "        return a + b;\n    }\n}\n", "class A {\n    int keep() { return 1; }\n}\n", "dead", 4)
        self.ok("w.rs", "fn keep() {}\n\nfn dead<T>(x: T) -> T\nwhere\n    T: Clone,\n{\n    x.clone()\n}\n",
                "fn keep() {}\n", "dead", 3)
        self.ok("e.kt", "fun keep() = 1\n\nfun dead(\n    a: Int,\n) =\n    a + 1\n", "fun keep() = 1\n", "dead", 3)

    def test_wrappers_go_with_their_declarations(self):
        self.ok("lib.rs", "use std::fmt;\n\npub fn keep() {}\n\nstruct Legacy {\n    v: u8,\n}\n\nimpl Legacy {\n"
                "    fn new() -> Self {\n        Legacy { v: 0 }\n    }\n}\n\nimpl fmt::Display for Legacy {\n"
                "    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {\n        write!(f, \"x\")\n    }\n}\n",
                "pub fn keep() {}\n", "Legacy", 5)
        self.ok("c.go", "package main\n\nconst (\n\tDeadA = 1\n\tDeadB = 2\n)\n\nfunc main() {}\n",
                "package main\n\nfunc main() {}\n", ["DeadA", "DeadB"], [4, 5])
        self.rejected("c.go", "package main\n\nconst (\n\tDeadA = 1\n\tLive = 2\n)\n\nfunc main() { _ = Live }\n",
                      "package main\n\nfunc main() { _ = Live }\n", "DeadA", 4)

    def test_separator_left_by_the_last_item(self):
        self.ok("Color.java", "enum Color {\n    RED,\n    OLD;\n\n    int x() { return 1; }\n}\n",
                "enum Color {\n    RED;\n\n    int x() { return 1; }\n}\n", "OLD", 3)
        self.ok("cfg.ts", "export const cfg = {\n  a: 1,\n  stale: 2,\n};\n", "export const cfg = {\n  a: 1\n};\n",
                "stale", 3)

    def test_side_effects_and_live_lines_are_not_served(self):
        self.rejected("app.ts", 'import "./polyfills";\nimport { a } from "./a";\n\nexport function stale() {}\n\nexport const b = a;\n',
                      'import { a } from "./a";\n\nexport const b = a;\n', "stale", 4)
        self.rejected("app.py", "import app.signals  # registers handlers\nimport json\n\n\ndef stale():\n    return 1\n\n\nx = json.dumps(1)\n",
                      "import json\n\n\nx = json.dumps(1)\n", "stale", 5)
        self.rejected("index.ts", 'export * from "./server";\nexport function stale() {}\n', "", "stale", 2)
        self.rejected("u.ts", "export function id() {}\nexport function run(x) {\n  if (!x.id) throw new Error();\n  return x;\n}\n",
                      "export function run(x) {\n  return x;\n}\n", "id", 1)
        self.rejected("t.ts", "class A {\n  get() { return 1; }\n}\nclass B {\n  get() { return 2; }\n}\n",
                      "class A {\n}\nclass B {\n}\n", "get", 2)
        self.ok("v.py", "import json\nimport os\n\n\ndef stale():\n    return json.dumps(1)\n\n\nprint(os.sep)\n",
                "import os\n\n\nprint(os.sep)\n", "stale", 5)
        self.ok("x.ts", 'import { a, b } from "./m";\n\nexport function stale() { return b; }\n\nexport const y = a;\n',
                'import { a } from "./m";\n\nexport const y = a;\n', "stale", 3)
        self.ok("__init__.py", '__all__ = [\n    "keep",\n    "stale",\n]\n\n\ndef keep():\n    pass\n\n\ndef stale():\n    pass\n',
                '__all__ = [\n    "keep",\n]\n\n\ndef keep():\n    pass\n', "stale", 11)

    def test_go_grouped_import(self):
        before = 'package main\n\nimport (\n\t"fmt"\n\t"strings"\n)\n\nfunc main() { fmt.Println(1) }\n\nfunc dead() string {\n\treturn strings.ToUpper("x")\n}\n'
        after = 'package main\n\nimport (\n\t"fmt"\n)\n\nfunc main() { fmt.Println(1) }\n'
        self.ok("main.go", before, after, "dead", 10)

    def test_python_parenthesized_import(self):
        before = "from os.path import (\n    join,\n    basename,\n)\n\n\ndef used():\n    return join('a', 'b')\n\n\ndef dead():\n    return basename('x')\n"
        after = "from os.path import (\n    join,\n)\n\n\ndef used():\n    return join('a', 'b')\n"
        self.ok("m.py", before, after, "dead", 11)

    def test_ruby_class_method_and_rust_const_fn_and_ts_const_enum(self):
        self.ok("a.rb", "class A\n  def self.dead\n    1\n  end\n\n  def live\n    2\n  end\nend\n",
                "class A\n  def live\n    2\n  end\nend\n", "dead", 2)
        self.ok("lib.rs", "pub fn live() {}\n\nconst fn dead() -> u8 {\n    1\n}\n", "pub fn live() {}\n", "dead", 3)
        self.ok("e.ts", "export const live = 1;\n\nconst enum Dead {\n  A,\n  B,\n}\n", "export const live = 1;\n", "Dead", 3)

    def test_ts_neighbour_method_is_rejected(self):
        before = "class Cart {\n  stale() {\n    return 1;\n  }\n\n  total() {\n    return 2;\n  }\n}\n"
        self.rejected("c.ts", before, "class Cart {\n}\n", "stale", 2)

    def test_java_neighbour_and_python_statement_and_constant_edit_are_rejected(self):
        self.rejected("A.java", "class A {\n  private void stale() {}\n  int total() { return 1; }\n}\n", "class A {\n}\n", "stale", 2)
        self.rejected("m.py", "LIMIT = 100\n\n\ndef stale():\n    pass\n\n\napp_start()\n",
                      "LIMIT = 1\n", "stale", 4)

    def test_mixin_call_argument_and_reindent_are_rejected(self):
        self.rejected("a.rb", "class A\n  include Comparable\n\n  def stale\n  end\nend\n", "class A\nend\n", "stale", 4)
        self.rejected("b.py", "import os\n\n\ndef stale():\n    pass\n\n\nif os.environ.get('X'):\n    os.remove('/tmp/x')\n",
                      "import os\n\n\nif os.environ.get('X'):\n    pass\nos.remove('/tmp/x')\n", "stale", 4)

    def test_decorated_python_function_and_export_specifier(self):
        self.ok("v.py", "import x\n\n\n@x.route('/a')\ndef dead():\n    return 1\n\n\ndef live():\n    return 2\n",
                "import x\n\n\ndef live():\n    return 2\n", "dead", 5)
        self.ok("index.ts", 'export { live, dead } from "./m";\nexport const x = 1;\n',
                'export { live } from "./m";\nexport const x = 1;\n', "dead", 1)


class Paths(unittest.TestCase):
    def test_protect_directory_and_scope_from_subdir(self):
        repo = Repo(APP)
        try:
            proc = subprocess.run([sys.executable, str(LEDGER), "init", "--report-only", "--scope", ".",
                                   "--protect", "../src/routes.ts", "--protect", "."], cwd=repo.root / "tests",
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            state = json.loads((repo.root / ".dead-code/state.json").read_text())
            self.assertEqual(state["scope"], ["tests"])
            self.assertIn("src/routes.ts", state["protect"])
            self.assertIn("tests/*", state["protect"])
        finally:
            repo.tmp.cleanup()

    def test_never_scan_paths_are_not_candidates(self):
        repo = Repo({"src/a.ts": "export const a = 1;\n", "db/migrations/001.py": "def up():\n    pass\n"})
        try:
            repo.ledger("init", "--report-only")
            (repo.root / ".dead-code/f.tsv").write_text("db/migrations/001.py\t1\tup\tfunction\tx\n"
                                                         "src/a.ts\t1\ta\tvariable\tx\n")
            repo.ledger("import", "--tool", "tsv", ".dead-code/f.tsv")
            self.assertEqual(set(repo.cands()), {"a"})
        finally:
            repo.tmp.cleanup()


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
