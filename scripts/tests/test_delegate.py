"""wgf_delegate: a delegated task is an agent working in its own worktree, or it is refused.

The contract pinned here is the orchestration one, not "git can create a worktree":
  * the only call that starts work is `worker-start --worktree new-top-level`, never
    `--worktree current` (the 2026-10-03 defect: agents opened in the coordinator's checkout
    and made worktrees Orca never knew about);
  * success needs Orca's receipt to prove a created worktree, an agent terminal and the task
    accepted, AND `worker-show` to place the dispatch in that worktree; otherwise nothing is
    recorded;
  * every agent is told to work in its cwd, commit, never push, never kill by image name;
  * `audit` tells an active agent's worktree from finished, unfinished and orphaned ones.

Orca is replaced by a recording runner; git runs for real in temporary repositories.

    python -m unittest scripts/tests/test_delegate.py
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import wgf_delegate  # noqa: E402
from wgf_delegate import DelegationError  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd)] + list(args), check=True, capture_output=True,
                   text=True)


def make_repo(root):
    repo = pathlib.Path(root) / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "init")
    return repo


class FakeOrca:
    """Records argv; answers worker-start/worker-show/worker-list like Orca does."""

    def __init__(self, repo, receipt_overrides=None, shown_path=None, create=True):
        self.repo = repo
        self.calls = []
        self.overrides = receipt_overrides or {}
        self.shown_path = shown_path
        self.create = create
        self.worktree = None

    def __call__(self, argv):
        self.calls.append(argv)
        args = argv[1:]
        if args[:2] == ["orchestration", "worker-start"]:
            name = args[args.index("--name") + 1]
            path = pathlib.Path(self.repo).parent / "wt" / name
            if self.create:
                git(self.repo, "worktree", "add", "-q", "-b", f"user/{name}", str(path))
            self.worktree = str(path).replace("\\", "/")
            result = {
                "runId": "run_x", "taskId": "task_x", "dispatchId": "ctx_x",
                "launch": {"effective": {"agent": "claude"}},
                "effects": [
                    {"kind": "worktree", "action": "created",
                     "id": f"repo-id::{self.worktree}"},
                    {"kind": "terminal", "role": "agent", "action": "created", "id": "term_x"},
                    {"kind": "dispatch_input", "role": "agent", "id": "term_x",
                     "state": "accepted"},
                ]}
            result.update(self.overrides)
            return 0, json.dumps({"ok": True, "result": result})
        if args[:2] == ["repo", "show"]:
            if getattr(self, "registered", True):
                return 0, json.dumps({"ok": True, "result": {"repo": {"path": str(self.repo)}}})
            return 1, json.dumps({"ok": False, "error": {"message": "repo not found"}})
        if args[:2] == ["repo", "add"]:
            self.registered = True
            return 0, json.dumps({"ok": True, "result": {"repo": {"path": args[3]}}})
        if args[:2] == ["orchestration", "worker-show"]:
            path = self.shown_path or self.worktree
            return 0, json.dumps({"ok": True, "result": {"projection": {
                "dispatchId": "ctx_x", "workspace": {"id": f"repo-id::{path}"}}}})
        if args[:2] == ["orchestration", "worker-list"]:
            return 0, json.dumps({"ok": True, "result": {"workers": [{"projection": {
                "dispatchId": "ctx_x", "outcome": "in_progress",
                "liveness": {"verdict": "live"},
                "workspace": {"id": f"repo-id::{self.worktree}"}}}]}})
        return 1, json.dumps({"ok": False, "error": {"message": "unexpected " + " ".join(args)}})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(self.tmp.name)
        self.ledger = pathlib.Path(self.tmp.name) / "ledger.jsonl"
        os.environ["WGF_ORCA"] = "orca"
        self.addCleanup(os.environ.pop, "WGF_ORCA", None)


class Spawn(Base):
    def test_a_delegation_starts_the_agent_in_a_new_worktree_and_is_recorded(self):
        orca = FakeOrca(self.repo)
        entry = wgf_delegate.spawn("T1", "3D environment", "Make the world authored.",
                                   "improve-3d-env", self.repo, run="run_x", runner=orca,
                                   ledger=self.ledger)
        start = next(c for c in orca.calls if c[1:3] == ["orchestration", "worker-start"])
        self.assertEqual(start[1:3], ["orchestration", "worker-start"])
        self.assertEqual(start[start.index("--worktree") + 1], "new-top-level")
        self.assertNotIn("current", start)
        self.assertEqual(start[start.index("--name") + 1], "improve-3d-env")
        self.assertEqual(start[start.index("--agent") + 1], "claude")
        self.assertEqual(entry["dispatch"], "ctx_x")
        self.assertEqual(entry["terminal"], "term_x")
        self.assertEqual(entry["branch"], "user/improve-3d-env")
        self.assertTrue(os.path.isdir(entry["worktree"]))
        recorded = wgf_delegate.read_ledger(self.ledger)
        self.assertEqual([e["task_id"] for e in recorded], ["T1"])

    def test_the_agent_is_told_the_worktree_rules_before_the_task(self):
        orca = FakeOrca(self.repo)
        wgf_delegate.spawn("T2", "levels", "Add 20 levels.", "improve-2d-levels", self.repo,
                           runner=orca, ledger=self.ledger)
        start = next(c for c in orca.calls if c[1:3] == ["orchestration", "worker-start"])
        spec = start[start.index("--spec") + 1]
        self.assertTrue(spec.endswith("Add 20 levels."))
        for rule in ("current working directory IS that", "commit your work",
                     "Do not push", "Never", "taskkill /IM", "worker_done"):
            self.assertIn(rule, spec)

    def test_a_receipt_without_a_created_worktree_is_refused_and_not_recorded(self):
        orca = FakeOrca(self.repo, receipt_overrides={"effects": [
            {"kind": "worktree", "action": "reused", "id": "repo-id::C:/elsewhere"},
            {"kind": "terminal", "role": "agent", "id": "term_x"},
            {"kind": "dispatch_input", "state": "accepted"}]})
        with self.assertRaisesRegex(DelegationError, "not created for this task"):
            wgf_delegate.spawn("T3", "t", "do it", "some-task", self.repo, runner=orca,
                               ledger=self.ledger)
        self.assertEqual(wgf_delegate.read_ledger(self.ledger), [])

    def test_orca_reports_a_top_level_worktree_as_created_top_level(self):
        # Observed live 2026-10-03: worker-start --worktree new-top-level answers
        # action "created_top_level"; it is a worktree created for this task.
        orca = FakeOrca(self.repo)
        real = orca.__call__

        def top_level(argv):
            code, out = real(argv)
            data = json.loads(out)
            for effect in (data.get("result") or {}).get("effects", []):
                if effect.get("kind") == "worktree":
                    effect["action"] = "created_top_level"
            return code, json.dumps(data)
        entry = wgf_delegate.spawn("T9", "t", "do it", "top-level", self.repo,
                                   runner=top_level, ledger=self.ledger)
        self.assertEqual(entry["dispatch"], "ctx_x")

    def test_a_refusal_names_a_dispatch_that_was_started_anyway(self):
        orca = FakeOrca(self.repo, receipt_overrides={"effects": [
            {"kind": "worktree", "action": "reused", "id": "repo-id::C:/x"},
            {"kind": "terminal", "role": "agent", "id": "term_x"},
            {"kind": "dispatch_input", "state": "accepted"}]})
        with self.assertRaisesRegex(DelegationError, "ctx_x WAS started"):
            wgf_delegate.spawn("T10", "t", "do it", "some-task", self.repo, runner=orca,
                               ledger=self.ledger)

    def test_adopt_records_a_dispatch_in_its_own_worktree_and_refuses_a_main_checkout(self):
        orca = FakeOrca(self.repo)
        orca(["orca", "orchestration", "worker-start", "--name", "adopted-task"])
        entry = wgf_delegate.adopt("ctx_x", "T11", "t", runner=orca, ledger=self.ledger)
        self.assertEqual(entry["branch"], "user/adopted-task")
        self.assertTrue(entry["adopted"])
        main = FakeOrca(self.repo, shown_path=str(self.repo).replace("\\", "/"))
        main.worktree = str(self.repo)
        with self.assertRaisesRegex(DelegationError, "main checkout"):
            wgf_delegate.adopt("ctx_x", "T12", "t", runner=main, ledger=self.ledger)

    def test_an_unregistered_game_repository_is_registered_before_the_start(self):
        orca = FakeOrca(self.repo)
        orca.registered = False
        wgf_delegate.spawn("T13", "t", "do it", "game-task", self.repo, runner=orca,
                           ledger=self.ledger)
        verbs = [c[1:3] for c in orca.calls]
        self.assertLess(verbs.index(["repo", "add"]),
                        verbs.index(["orchestration", "worker-start"]))

    def test_a_receipt_without_an_agent_terminal_is_refused(self):
        orca = FakeOrca(self.repo, receipt_overrides={"effects": [
            {"kind": "worktree", "action": "created", "id": "repo-id::C:/x"},
            {"kind": "dispatch_input", "state": "accepted"}]})
        with self.assertRaisesRegex(DelegationError, "no agent terminal"):
            wgf_delegate.spawn("T4", "t", "do it", "some-task", self.repo, runner=orca,
                               ledger=self.ledger)

    def test_a_task_the_agent_never_received_is_refused(self):
        orca = FakeOrca(self.repo, receipt_overrides={"effects": [
            {"kind": "worktree", "action": "created", "id": "repo-id::C:/x"},
            {"kind": "terminal", "role": "agent", "id": "term_x"},
            {"kind": "dispatch_input", "state": "rejected"}]})
        with self.assertRaisesRegex(DelegationError, "not accepted"):
            wgf_delegate.spawn("T5", "t", "do it", "some-task", self.repo, runner=orca,
                               ledger=self.ledger)

    def test_an_agent_placed_outside_its_worktree_is_refused(self):
        orca = FakeOrca(self.repo, shown_path="C:/Workspaces/coordinator-checkout")
        with self.assertRaisesRegex(DelegationError, "not in its worktree"):
            wgf_delegate.spawn("T6", "t", "do it", "some-task", self.repo, runner=orca,
                               ledger=self.ledger)
        self.assertEqual(wgf_delegate.read_ledger(self.ledger), [])

    def test_no_task_no_worktree(self):
        orca = FakeOrca(self.repo)
        with self.assertRaisesRegex(DelegationError, "concrete task"):
            wgf_delegate.spawn("T7", "t", "   ", "some-task", self.repo, runner=orca,
                               ledger=self.ledger)
        self.assertEqual(orca.calls, [])

    def test_an_orca_failure_is_reported(self):
        def failing(argv):
            return 1, json.dumps({"ok": False, "error": {"message": "nested depth exceeded"}})
        with self.assertRaisesRegex(DelegationError, "nested depth exceeded"):
            wgf_delegate.spawn("T8", "t", "do it", "some-task", self.repo, runner=failing,
                               ledger=self.ledger)


class TrustBlocked(FakeOrca):
    """Observed live 2026-10-03 on a repository Claude Code had never opened: worker-start
    answers state failed / agent_readiness, lastFailure 'agent-trust-workspace'; the agent
    terminal shows the trust dialog with 'No, exit' highlighted."""

    def __init__(self, repo):
        super().__init__(repo)
        self.dialog = True
        self.highlight = "no"
        self.sent = []

    def __call__(self, argv):
        args = argv[1:]
        if args[:2] == ["orchestration", "worker-start"] and "--retry-of" not in args:
            code, out = super().__call__(argv)
            data = json.loads(out)
            data["result"].update({"state": "failed", "failedStage": "agent_readiness",
                                   "lastError": "Agent startup blocked: agent-trust-workspace"})
            data["result"]["effects"] = [e for e in data["result"]["effects"]
                                         if e["kind"] != "dispatch_input"]
            return code, json.dumps(data)
        if args[:2] == ["orchestration", "worker-start"]:
            self.calls.append(argv)
            if self.dialog:
                return 1, json.dumps({"ok": False, "error": {"message": "agent not ready"}})
            return 0, json.dumps({"ok": True, "result": {
                "dispatchId": "ctx_retry", "taskId": "task_x", "runId": "run_x",
                "launch": {"effective": {"agent": None}},
                "effects": [{"kind": "worktree", "action": "reused",
                             "id": f"repo-id::{self.worktree}"},
                            {"kind": "terminal", "action": "reused", "id": "term_x"},
                            {"kind": "dispatch_input", "state": "accepted"}]}})
        if args[:2] == ["terminal", "read"]:
            self.calls.append(argv)
            mark = lambda which: " > " if self.highlight == which else "   "
            tail = ([" Quick safety check: Is this a project you created or one you trust?",
                     mark("no") + "No, exit", mark("yes") + "Yes, I trust this folder",
                     " Enter to confirm"] if self.dialog else ["Claude Code", "> "])
            return 0, json.dumps({"ok": True, "result": {"terminal": {"tail": tail}}})
        if args[:2] == ["terminal", "send"]:
            self.calls.append(argv)
            if "--enter" in args:
                self.sent.append("enter")
                if self.highlight == "yes":
                    self.dialog = False
                else:
                    raise AssertionError("Enter pressed on 'No, exit'")
            else:
                self.sent.append("down")
                self.highlight = "yes"
            return 0, json.dumps({"ok": True, "result": {}})
        if args[:2] == ["orchestration", "worker-show"] and args[3] == "ctx_retry":
            return super().__call__(argv[:4] + ["ctx_x"] + argv[5:])
        return super().__call__(argv)


class Trust(Base):
    def test_a_trust_block_is_refused_with_the_remedy_unless_opted_in(self):
        orca = TrustBlocked(self.repo)
        with self.assertRaisesRegex(DelegationError, "--trust-workspace"):
            wgf_delegate.spawn("T20", "t", "do it", "trust-task", self.repo, runner=orca,
                               ledger=self.ledger)
        self.assertEqual(orca.sent, [])
        self.assertEqual(wgf_delegate.read_ledger(self.ledger), [])

    def test_opted_in_it_answers_yes_never_no_and_retries_in_the_same_terminal(self):
        orca = TrustBlocked(self.repo)
        entry = wgf_delegate.spawn("T21", "t", "do it", "trust-task", self.repo, runner=orca,
                                   ledger=self.ledger, trust_workspace=True,
                                   sleep=lambda s: None)
        self.assertEqual(orca.sent, ["down", "enter"])
        retry = [c for c in orca.calls if "--retry-of" in c]
        self.assertEqual(len(retry), 1)
        self.assertEqual(retry[0][retry[0].index("--terminal") + 1], "term_x")
        self.assertEqual(retry[0][retry[0].index("--task") + 1], "task_x")
        self.assertEqual(entry["dispatch"], "ctx_retry")
        self.assertEqual(entry["worktree"], orca.worktree)


class Audit(Base):
    def test_worktrees_are_classified_by_agent_and_content(self):
        orca = FakeOrca(self.repo)
        wgf_delegate.spawn("T1", "t", "do it", "live-task", self.repo, runner=orca,
                           ledger=self.ledger)
        live = orca.worktree
        root = pathlib.Path(self.tmp.name)
        # a worktree nobody delegated, with nothing in it
        git(self.repo, "worktree", "add", "-q", "-b", "placeholder", str(root / "empty"))
        # a worktree with uncommitted work and no agent
        git(self.repo, "worktree", "add", "-q", "-b", "half", str(root / "half"))
        (root / "half" / "b.txt").write_text("b\n")
        # a worktree with a commit that exists nowhere else
        git(self.repo, "worktree", "add", "-q", "-b", "local-only", str(root / "local"))
        (root / "local" / "c.txt").write_text("c\n")
        git(root / "local", "add", "c.txt")
        git(root / "local", "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-q",
            "-m", "c")
        # The repository has no remote: origin/main falls back to main.
        rows = wgf_delegate.audit(self.repo, base_ref="origin/main", runner=orca,
                                  ledger=self.ledger)
        by_path = {wgf_delegate._norm(r["path"]): r for r in rows}
        self.assertEqual(rows[0]["class"], wgf_delegate.MAIN)
        self.assertEqual(by_path[wgf_delegate._norm(live)]["class"], wgf_delegate.ACTIVE)
        self.assertEqual(by_path[wgf_delegate._norm(live)]["task"], "T1")
        self.assertEqual(by_path[wgf_delegate._norm(root / "empty")]["class"],
                         wgf_delegate.ORPHANED)
        self.assertEqual(by_path[wgf_delegate._norm(root / "half")]["class"],
                         wgf_delegate.UNFINISHED)
        self.assertEqual(by_path[wgf_delegate._norm(root / "local")]["class"],
                         wgf_delegate.UNFINISHED)
        self.assertIn("exist only here", by_path[wgf_delegate._norm(root / "local")]["reason"])


class Cli(Base):
    def test_spawn_exits_nonzero_when_orca_is_missing(self):
        os.environ["WGF_ORCA"] = ""
        os.environ["PATH"], saved = "", os.environ.get("PATH", "")
        self.addCleanup(os.environ.__setitem__, "PATH", saved)
        spec = pathlib.Path(self.tmp.name) / "task.md"
        spec.write_text("do it")
        sys.path.insert(0, os.path.dirname(HERE))
        import importlib.util
        path = os.path.join(os.path.dirname(HERE), "wgf-delegate.py")
        loaded = importlib.util.spec_from_file_location("wgf_delegate_cli", path)
        cli = importlib.util.module_from_spec(loaded)
        loaded.loader.exec_module(cli)
        code = cli.main(["spawn", "--task-id", "T", "--name", "some-task", "--title", "t",
                         "--spec-file", str(spec), "--repo", str(self.repo)])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
