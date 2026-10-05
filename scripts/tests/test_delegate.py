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
from unittest import mock

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


def states_of(ledger, task_id):
    return [e.get("state") for e in wgf_delegate.read_ledger(ledger)
            if e.get("task_id") == task_id]


class FakeOrca:
    """Records argv; answers worker-start/worker-show/worker-list like Orca does."""

    def __init__(self, repo, receipt_overrides=None, shown_path=None, create=True,
                 dispatch="ctx_x", terminal="term_x"):
        self.repo = repo
        self.calls = []
        self.overrides = receipt_overrides or {}
        self.shown_path = shown_path
        self.create = create
        self.worktree = None
        self.dispatch = dispatch
        self.terminal = terminal
        # What worker-show / worker-list report about the dispatch.
        self.liveness = "live"
        self.outcome = "in_progress"
        self.stage = "turn_started"
        self.known = True

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
                "runId": "run_x", "taskId": "task_x", "dispatchId": self.dispatch,
                "launch": {"effective": {"agent": "claude"}}, "turnStart": "observed",
                "effects": [
                    {"kind": "worktree", "action": "created",
                     "id": f"repo-id::{self.worktree}"},
                    {"kind": "terminal", "role": "agent", "action": "created",
                     "id": self.terminal},
                    {"kind": "dispatch_input", "role": "agent", "id": self.terminal,
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
            if not self.known:
                return 1, json.dumps({"ok": False, "error": {"message": "dispatch not found"}})
            path = self.shown_path or self.worktree
            return 0, json.dumps({"ok": True, "result": {
                "worker": {"stage": self.stage},
                "projection": {
                    "dispatchId": self.dispatch, "workspace": {"id": f"repo-id::{path}"},
                    "outcome": self.outcome, "liveness": {"verdict": self.liveness}}}})
        if args[:2] == ["orchestration", "worker-list"]:
            rows = [] if not self.known else [{"projection": {
                "dispatchId": self.dispatch, "outcome": self.outcome,
                "liveness": {"verdict": self.liveness},
                "workspace": {"id": f"repo-id::{self.worktree}"}}}]
            return 0, json.dumps({"ok": True, "result": {"workers": rows}})
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
        self.assertEqual({e["task_id"] for e in recorded}, {"T1"})
        self.assertEqual([e["state"] for e in recorded],
                         ["AGENT_REQUESTED", "WORKTREE_CREATED", "AGENT_SPAWNED",
                          "AGENT_STARTED"])

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
        # The dispatch exists, so it is recorded - as unverified, never as spawned.
        states = states_of(self.ledger, "T3")
        self.assertEqual(states, ["AGENT_REQUESTED", "AGENT_UNVERIFIED"])

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
        self.assertEqual(states_of(self.ledger, "T6")[-1], "AGENT_UNVERIFIED")
        self.assertNotIn("AGENT_STARTED", states_of(self.ledger, "T6"))

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
                "launch": {"effective": {"agent": None}}, "turnStart": "observed",
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
        folded = wgf_delegate.delegations(wgf_delegate.read_ledger(self.ledger))["T20"]
        self.assertEqual(folded["state"], "AGENT_UNVERIFIED")
        self.assertEqual(folded["dispatch"], "ctx_x")

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


class TurnStart(Base):
    def test_a_task_typed_but_never_started_is_refused_and_recorded_unverified(self):
        # Observed live: input accepted, turn unobserved, agent idle at an empty prompt.
        orca = FakeOrca(self.repo, receipt_overrides={"turnStart": "unobserved"})
        orca.stage = "turn_start_unobserved"
        with self.assertRaisesRegex(DelegationError, "never started a turn"):
            wgf_delegate.spawn("T30", "t", "do it", "silent-task", self.repo, runner=orca,
                               ledger=self.ledger, sleep=lambda s: None)
        self.assertEqual(states_of(self.ledger, "T30")[-1], "AGENT_UNVERIFIED")
        self.assertNotIn("AGENT_STARTED", states_of(self.ledger, "T30"))

    def test_a_turn_seen_later_on_the_worker_stage_is_accepted(self):
        orca = FakeOrca(self.repo, receipt_overrides={"turnStart": "unobserved"})
        orca.stage = "turn_start_unobserved"
        real = orca.__call__

        def later(argv):
            code, out = real(argv)
            if argv[1:3] == ["orchestration", "worker-show"]:
                data = json.loads(out)
                data["result"]["worker"] = {"stage": "turn_started"}
                return code, json.dumps(data)
            return code, out
        entry = wgf_delegate.spawn("T31", "t", "do it", "late-turn", self.repo, runner=later,
                                   ledger=self.ledger, sleep=lambda s: None)
        self.assertEqual(entry["dispatch"], "ctx_x")


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


def commit_in(path, name="w.txt"):
    (pathlib.Path(path) / name).write_text("w\n")
    git(path, "add", name)
    git(path, "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-q", "-m", name)
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def load_cli():
    import importlib.util
    path = os.path.join(os.path.dirname(HERE), "wgf-delegate.py")
    loaded = importlib.util.spec_from_file_location("wgf_delegate_cli", path)
    cli = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(cli)
    return cli


class Lifecycle(Base):
    """The lifecycle recorded per task id (2026-10-05: a real agent and worktree existed with
    no ledger record, and an unreadable worktree was reported as an empty orphan)."""

    def folded(self, task_id):
        return wgf_delegate.delegations(wgf_delegate.read_ledger(self.ledger))[task_id]

    def test_a_a_worktree_alone_never_yields_an_agent_working_or_completed(self):
        # A receipt with a created worktree but no agent terminal.
        orca = FakeOrca(self.repo, receipt_overrides={"effects": [
            {"kind": "worktree", "action": "created", "id": "repo-id::" + str(
                pathlib.Path(self.repo).parent / "wt" / "lonely-tree").replace("\\", "/")},
            {"kind": "dispatch_input", "state": "accepted"}]})
        with self.assertRaises(DelegationError):
            wgf_delegate.spawn("TA", "t", "do it", "lonely-tree", self.repo, runner=orca,
                               ledger=self.ledger)
        folded = self.folded("TA")
        self.assertEqual(folded["worktree_state"], "WORKTREE_CREATED")
        self.assertEqual(folded["state"], "AGENT_UNVERIFIED")
        # Commits appear in the worktree; Orca knows no such dispatch: not completion.
        commit_in(orca.worktree)
        orca.known = False
        report = wgf_delegate.status("TA", runner=orca, ledger=self.ledger)
        self.assertEqual(report["state"], "AGENT_ORPHANED")
        self.assertEqual(len(report["git"]["commits"]), 1)
        # A ledger holding only a worktree event carries no agent state at all.
        only = wgf_delegate.delegations([{"task_id": "X", "state": "WORKTREE_CREATED",
                                          "worktree": "/w"}])["X"]
        self.assertIsNone(only["state"])

    def test_b_an_orca_refusal_is_recorded_as_spawn_failed_and_exits_nonzero(self):
        def refusing(argv):
            return 1, json.dumps({"ok": False, "error": {"message": "nested depth exceeded"}})
        with self.assertRaisesRegex(DelegationError, "nested depth exceeded"):
            wgf_delegate.spawn("TB", "t", "do it", "refused-task", self.repo,
                               runner=lambda argv: (FakeOrca(self.repo)(argv)
                                                    if argv[1] == "repo" else refusing(argv)),
                               ledger=self.ledger)
        self.assertEqual(states_of(self.ledger, "TB"),
                         ["AGENT_REQUESTED", "AGENT_SPAWN_FAILED"])
        self.assertIn("nested depth exceeded", self.folded("TB")["last_error"])
        self.assertNotIn("dispatch", self.folded("TB"))
        # The CLI exits non-zero, and a refused task may be delegated again.
        spec = pathlib.Path(self.tmp.name) / "task.md"
        spec.write_text("do it")
        fake = FakeOrca(self.repo)
        with mock.patch.dict(os.environ, {"WGF_DELEGATION_LEDGER": str(self.ledger)}), \
                mock.patch.object(wgf_delegate, "_invoke",
                                  lambda args, runner: refusing(["orca"] + list(args))
                                  if args[1] == "worker-start" else fake(["orca"] + list(args))):
            code = load_cli().main(["spawn", "--task-id", "TB", "--name", "refused-task",
                                    "--title", "t", "--spec-file", str(spec),
                                    "--repo", str(self.repo)])
        self.assertEqual(code, 1)
        self.assertEqual(states_of(self.ledger, "TB")[-1], "AGENT_SPAWN_FAILED")

    def test_c_a_spawned_agent_is_recorded_with_task_role_worktree_dispatch_and_state(self):
        orca = FakeOrca(self.repo)
        entry = wgf_delegate.spawn("TC", "Level pass", "Add levels.", "level-pass", self.repo,
                                   runner=orca, ledger=self.ledger, role="level-designer")
        for key, value in (("task_id", "TC"), ("title", "Level pass"),
                           ("role", "level-designer"), ("dispatch", "ctx_x"),
                           ("terminal", "term_x"), ("worktree", orca.worktree),
                           ("branch", "user/level-pass"), ("state", "AGENT_STARTED")):
            self.assertEqual(entry[key], value, key)
        self.assertEqual(entry, self.folded("TC"))
        # A task with an agent on it is not delegated a second time.
        with self.assertRaisesRegex(DelegationError, "already delegated"):
            wgf_delegate.spawn("TC", "again", "Add levels.", "level-pass-2", self.repo,
                               runner=FakeOrca(self.repo), ledger=self.ledger)

    def test_d_completion_needs_orca_outcome_succeeded_commits_alone_are_not(self):
        orca = FakeOrca(self.repo)
        wgf_delegate.spawn("TD", "t", "do it", "done-task", self.repo, runner=orca,
                           ledger=self.ledger)
        sha = commit_in(orca.worktree)
        report = wgf_delegate.status("TD", runner=orca, ledger=self.ledger)
        self.assertEqual(report["state"], "AGENT_WORKING")
        self.assertEqual(report["git"]["commits"], [sha])
        # A live dispatch running outside its recorded worktree is not "working" there.
        orca.shown_path = "/elsewhere/checkout"
        self.assertEqual(wgf_delegate.status("TD", runner=orca, ledger=self.ledger)["state"],
                         "AGENT_UNVERIFIED")
        orca.shown_path = None
        orca.liveness, orca.outcome = "dead", None
        self.assertEqual(wgf_delegate.status("ctx_x", runner=orca, ledger=self.ledger)["state"],
                         "AGENT_ORPHANED")
        orca.outcome = "succeeded"
        report = wgf_delegate.status("TD", runner=orca, ledger=self.ledger)
        self.assertEqual(report["state"], "AGENT_COMPLETED")
        folded = self.folded("TD")
        self.assertEqual(folded["state"], "AGENT_COMPLETED")
        self.assertEqual(folded["commits"], [sha])
        # Nothing changed: nothing appended.
        before = len(wgf_delegate.read_ledger(self.ledger))
        self.assertFalse(wgf_delegate.status("TD", runner=orca, ledger=self.ledger)["recorded"])
        self.assertEqual(len(wgf_delegate.read_ledger(self.ledger)), before)

    def test_e_parallel_spawns_never_share_worktree_branch_dispatch_or_state(self):
        a = FakeOrca(self.repo, dispatch="ctx_a", terminal="term_a")
        b = FakeOrca(self.repo, dispatch="ctx_b", terminal="term_b")
        ea = wgf_delegate.spawn("TE1", "a", "do a", "task-a", self.repo, runner=a,
                                ledger=self.ledger)
        eb = wgf_delegate.spawn("TE2", "b", "do b", "task-b", self.repo, runner=b,
                                ledger=self.ledger)
        for key in ("worktree", "branch", "dispatch", "terminal", "task_id"):
            self.assertNotEqual(ea[key], eb[key], key)
        b_events = states_of(self.ledger, "TE2")
        a.outcome = "succeeded"
        wgf_delegate.status("TE1", runner=a, ledger=self.ledger)
        self.assertEqual(self.folded("TE1")["state"], "AGENT_COMPLETED")
        self.assertEqual(self.folded("TE2")["state"], "AGENT_STARTED")
        self.assertEqual(states_of(self.ledger, "TE2"), b_events)

    def test_f_dead_dispatch_is_agent_orphaned_and_an_unreadable_worktree_unknown(self):
        orca = FakeOrca(self.repo)
        wgf_delegate.spawn("TF", "t", "do it", "dead-task", self.repo, runner=orca,
                           ledger=self.ledger)
        (pathlib.Path(orca.worktree) / "half.txt").write_text("uncommitted\n")
        orca.liveness = "dead"
        root = pathlib.Path(self.tmp.name)
        git(self.repo, "worktree", "add", "-q", "-b", "gone", str(root / "gone"))
        import shutil
        shutil.rmtree(root / "gone")
        rows = wgf_delegate.audit(self.repo, runner=orca, ledger=self.ledger)
        by_path = {wgf_delegate._norm(r["path"]): r for r in rows}
        dead = by_path[wgf_delegate._norm(orca.worktree)]
        self.assertEqual(dead["class"], wgf_delegate.AGENT_ORPHANED_WORKTREE)
        self.assertIn("uncommitted", dead["reason"])
        self.assertEqual(dead["task"], "TF")
        self.assertEqual(dead["state"], "AGENT_STARTED")
        gone = by_path[wgf_delegate._norm(root / "gone")]
        self.assertEqual(gone["class"], wgf_delegate.UNKNOWN)
        self.assertIn("unreadable", gone["reason"])
        # A worktree git cannot read from this host (a WSL path seen from Windows) is
        # UNKNOWN, never an empty orphan.
        tree = {"path": "/home/u/wgf-wt/x", "branch": "x", "head": "abc"}
        unreadable = lambda path, *args: (127, "git could not run")  # noqa: E731
        kind, reason = wgf_delegate.classify(tree, {}, {}, "main", unreadable)
        self.assertEqual(kind, wgf_delegate.UNKNOWN)
        # status records the orphaned agent.
        self.assertEqual(wgf_delegate.status("TF", runner=orca, ledger=self.ledger)["state"],
                         "AGENT_ORPHANED")
        # Orca unreachable: a delegated worktree's agent state is UNKNOWN, not orphaned.
        tree = {"path": orca.worktree, "branch": "user/dead-task", "head": "abc"}
        kind, _ = wgf_delegate.classify(tree, {"TG": {"task_id": "TG", "dispatch": "ctx_q",
                                                      "worktree": orca.worktree,
                                                      "state": "AGENT_STARTED"}},
                                        None, "main")
        self.assertEqual(kind, wgf_delegate.UNKNOWN)

    def test_g_a_git_failure_after_the_start_records_agent_unverified(self):
        # 2026-10-05: Orca created the worktree, started the agent and delivered the task;
        # the git check then failed from a Windows host and NOTHING was recorded.
        spec = pathlib.Path(self.tmp.name) / "task.md"
        spec.write_text("do it")
        orca = FakeOrca(self.repo, create=False)
        with mock.patch.dict(os.environ, {"WGF_DELEGATION_LEDGER": str(self.ledger)}), \
                mock.patch.object(wgf_delegate, "_invoke",
                                  lambda args, runner: orca(["orca"] + list(args))):
            code = load_cli().main(["spawn", "--task-id", "TG", "--name", "proof-task",
                                    "--title", "proof", "--spec-file", str(spec),
                                    "--repo", str(self.repo)])
        self.assertEqual(code, 1)
        folded = self.folded("TG")
        self.assertEqual(folded["state"], "AGENT_UNVERIFIED")
        self.assertEqual(folded["dispatch"], "ctx_x")
        self.assertEqual(folded["terminal"], "term_x")
        self.assertTrue(folded["worktree_id"].endswith("proof-task"))
        self.assertIn("not a readable git worktree", folded["last_error"])
        self.assertTrue(folded["worktree"].endswith("proof-task"))
        unverified = [e for e in wgf_delegate.read_ledger(self.ledger)
                      if e.get("state") == "AGENT_UNVERIFIED"][0]
        self.assertIn("adopt --dispatch ctx_x", unverified["remedy"])
        self.assertIn("worker-stop --dispatch ctx_x", unverified["remedy"])
        with self.assertRaisesRegex(DelegationError, "AGENT_UNVERIFIED recorded"):
            wgf_delegate.spawn("TG2", "t", "do it", "proof-two", self.repo,
                               runner=FakeOrca(self.repo, create=False), ledger=self.ledger)

    def test_the_status_and_ledger_commands_show_the_lifecycle(self):
        orca = FakeOrca(self.repo)
        wgf_delegate.spawn("TS", "t", "do it", "shown-task", self.repo, runner=orca,
                           ledger=self.ledger)
        orca.outcome = "succeeded"
        import contextlib
        import io
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"WGF_DELEGATION_LEDGER": str(self.ledger)}), \
                mock.patch.object(wgf_delegate, "_invoke",
                                  lambda args, runner: orca(["orca"] + list(args))), \
                contextlib.redirect_stdout(out):
            cli = load_cli()
            self.assertEqual(cli.main(["status", "TS"]), 0)
            self.assertEqual(cli.main(["ledger"]), 0)
        self.assertIn("AGENT_STARTED -> AGENT_COMPLETED", out.getvalue())
        self.assertRegex(out.getvalue(), r"TS\s+AGENT_COMPLETED")

    def test_adopt_reads_a_worktree_orca_reports_as_a_wsl_path(self):
        orca = FakeOrca(self.repo)
        orca(["orca", "orchestration", "worker-start", "--name", "wsl-task"])
        orca.shown_path = "\\\\wsl.localhost\\Ubuntu" + orca.worktree.replace("/", "\\")
        entry = wgf_delegate.adopt("ctx_x", "TW", "t", runner=orca, ledger=self.ledger)
        self.assertEqual(entry["branch"], "user/wsl-task")
        self.assertEqual(states_of(self.ledger, "TW"), ["AGENT_SPAWNED", "AGENT_WORKING"])


class Paths(unittest.TestCase):
    UNC = "\\\\wsl.localhost\\Ubuntu\\home\\u\\orca\\workspaces\\proof\\p1"

    def test_h_wsl_paths_translate_for_the_host_both_directions(self):
        for host in ("wsl", "linux"):
            self.assertEqual(wgf_delegate.to_local(self.UNC, host),
                             "/home/u/orca/workspaces/proof/p1")
            self.assertEqual(wgf_delegate.to_local("\\\\wsl$\\Ubuntu\\home\\u\\x", host),
                             "/home/u/x")
            self.assertEqual(wgf_delegate.to_local("//wsl.localhost/Ubuntu/home/u/x", host),
                             "/home/u/x")
        self.assertEqual(wgf_delegate.to_local("C:\\Users\\u\\repo", "wsl"), "/mnt/c/Users/u/repo")
        self.assertEqual(wgf_delegate.to_local("C:/Users/u/repo", "linux"), "C:/Users/u/repo")
        self.assertEqual(wgf_delegate.to_local("/mnt/c/Users/u/repo", "windows"),
                         "C:/Users/u/repo")
        self.assertEqual(wgf_delegate.to_local("/mnt/d", "windows"), "D:/")
        self.assertEqual(wgf_delegate.to_local("/mnt/c/x", "wsl"), "/mnt/c/x")

    def test_git_reads_a_wsl_worktree_from_windows_through_wsl_exe(self):
        with mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": ""}):
            argv = wgf_delegate.git_argv(self.UNC, ["status"], host="windows")
            self.assertTrue(os.path.basename(argv[0]).startswith("wsl"))
            self.assertEqual(argv[1:], ["-d", "Ubuntu", "git", "-C",
                                        "/home/u/orca/workspaces/proof/p1", "status"])
            bare = wgf_delegate.git_argv("/home/u/wgf-wt/x", ["status"], host="windows")
            self.assertEqual(bare[1:], ["git", "-C", "/home/u/wgf-wt/x", "status"])
        self.assertEqual(wgf_delegate.git_argv("/mnt/c/r", ["status"], host="windows"),
                         ["git", "-C", "C:/r", "status"])
        self.assertEqual(wgf_delegate.git_argv(self.UNC, ["status"], host="wsl"),
                         ["git", "-C", "/home/u/orca/workspaces/proof/p1", "status"])
        self.assertEqual(wgf_delegate._norm(self.UNC, "windows"),
                         wgf_delegate._norm("/home/u/orca/workspaces/proof/p1/", "windows"))
        self.assertEqual(wgf_delegate._norm(self.UNC, "wsl"),
                         wgf_delegate._norm("/home/u/orca/workspaces/proof/p1", "wsl"))

    def test_the_orca_launcher_comes_from_wgf_orca_then_orca_cli_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher = pathlib.Path(tmp) / "orca-ide"
            launcher.write_text("#!/bin/sh\n")
            launcher.chmod(0o755)
            env = {"WGF_ORCA": "", "ORCA_CLI_COMMAND": str(launcher), "PATH": ""}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(wgf_delegate.orca_executable(), str(launcher))
                os.environ["WGF_ORCA"] = "/opt/orca"
                self.assertEqual(wgf_delegate.orca_executable(), "/opt/orca")
                os.environ["WGF_ORCA"] = ""
                os.environ["ORCA_CLI_COMMAND"] = ""
                with self.assertRaises(wgf_delegate.OrcaUnavailable):
                    wgf_delegate.orca_executable()


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
