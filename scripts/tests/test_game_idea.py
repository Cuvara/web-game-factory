"""A game idea given to a new run: `wgf new-game [--project ID] "IDEA"`.

The idea is the run's brief. It is canonicalised once (wgflib.workflow.api.canonical_idea),
recorded in the run's params - and so in WORKFLOW_STARTED, which every resume corroborates -
handed to steps as `context.environment["idea"]`, and carried by the artifacts that have a
place for it: research-report `scope.brief`, opportunity, title-strategy and game-design
`brief`. `--project` stays the run's identity; without an idea the run is the blank market
scan it always was.

Covered: the CLI (positional idea, with and without --project, with --mock --hold-gates,
quoting, refusals), the run state, resume, the real research / strategy / design modules
against the discovery fixture corpus, and the generated command surfaces.

Deterministic and offline: mock steps or the fixture corpus, temporary stores, no network,
no repository created, no game project touched.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
WGF = os.path.join(SCRIPTS, "wgf.py")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgf_discovery import analysis  # noqa: E402
from wgflib.workflow import integrity  # noqa: E402
from wgflib.workflow.api import (  # noqa: E402
    IDEA_MAX_LENGTH, RunRequest, WorkflowAPI, canonical_idea)
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402

GOALKEEPER = "3D goalkeeper game where the player blocks penalty shots"
DISCOVERY = os.path.join(HERE, "fixtures", "discovery")
AS_OF = "2026-09-23T00:00:00Z"
BRIEF_BEARING = {"research-report": ("scope", "brief"), "opportunity": ("brief",),
                 "title-strategy": ("brief",), "game-design": ("brief",)}


def brief_of(artifact_type, body):
    for key in BRIEF_BEARING[artifact_type]:
        body = (body or {}).get(key)
    return body


class Scratch(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-idea-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.store = os.path.join(self.scratch, "store")
        self.config = os.path.join(self.scratch, "factory.yaml")
        with open(self.config, "w", encoding="utf-8") as handle:
            handle.write("factory:\n  storage:\n    fsync: false\n")

    def wgf(self, *args, idea=None, dashdash=False, expect=0):
        """Run wgf as a person types it: the options, then the idea as one argv element."""
        command = [sys.executable, WGF, *args, "--store", self.store, "--config", self.config]
        if dashdash:
            command.append("--")
        if idea is not None:
            command.append(idea)
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if expect is not None:
            self.assertEqual(done.returncode, expect,
                             f"wgf {' '.join(args)} {idea!r}\n{done.stdout}\n{done.stderr}")
        return done

    def api(self):
        return WorkflowAPI(config=FactoryConfig({"storage": {"fsync": False}}),
                           store_dir=self.store)

    def only_run(self):
        runs = self.api().store.list_runs()
        self.assertEqual(len(runs), 1, runs)
        return runs[0]

    def started_params(self, run_id):
        events = self.api().store.read_events(run_id)
        started = [e for e in events if e.get("event") == "WORKFLOW_STARTED"]
        return started[0]["data"]["params"]

    def artifact(self, state, artifact_type):
        ref = state.latest_artifact(artifact_type)
        self.assertIsNotNone(ref, f"no {artifact_type} in {state.run_id}")
        return self.api().store.read_artifact(state.run_id, ref)


# -- canonical form ---------------------------------------------------------------------------


class CanonicalIdea(unittest.TestCase):
    def test_whitespace_runs_become_one_space_and_nothing_else_changes(self):
        self.assertEqual(canonical_idea("  3D  goalkeeper\tgame\n where  \"Keeper's\" day "),
                         "3D goalkeeper game where \"Keeper's\" day")

    def test_case_punctuation_and_unicode_are_kept(self):
        self.assertEqual(canonical_idea("Gardien de but 3D — arrête les tirs!"),
                         "Gardien de but 3D — arrête les tirs!")

    def test_it_is_nfc(self):
        self.assertEqual(canonical_idea("arrête"), "arrête")

    def test_empty_control_characters_and_overlong_ideas_are_refused(self):
        for bad in ("", "   ", "\n\t", "goal\x07keeper", "x" * (IDEA_MAX_LENGTH + 1), None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                canonical_idea(bad)
        self.assertEqual(len(canonical_idea("x" * IDEA_MAX_LENGTH)), IDEA_MAX_LENGTH)


# -- the CLI ----------------------------------------------------------------------------------


class Cli(Scratch):
    def test_positional_idea_only(self):
        self.wgf("new-game", "--mock", "--json", idea=GOALKEEPER, expect=3)
        state = self.only_run()
        self.assertEqual(state.params["idea"], GOALKEEPER)
        self.assertIsNone(state.project_id)
        self.assertEqual(self.started_params(state.run_id)["idea"], GOALKEEPER)

    def test_project_only_is_identity_and_records_no_idea(self):
        self.wgf("new-game", "--mock", "--project", "goalkeeper-3d", "--quiet", expect=3)
        state = self.only_run()
        self.assertEqual(state.project_id, "goalkeeper-3d")
        self.assertNotIn("idea", state.params)
        self.assertNotIn("idea", self.started_params(state.run_id))

    def test_project_and_idea_are_kept_apart(self):
        self.wgf("new-game", "--mock", "--project", "goalkeeper-3d", "--quiet",
                 idea=GOALKEEPER, expect=3)
        state = self.only_run()
        self.assertEqual(state.project_id, "goalkeeper-3d")
        self.assertEqual(state.params["idea"], GOALKEEPER)

    def test_the_idea_may_come_before_the_options(self):
        command = [sys.executable, WGF, "new-game", GOALKEEPER, "--mock", "--project",
                   "goalkeeper-3d", "--quiet", "--store", self.store, "--config", self.config]
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 3, done.stderr)
        state = self.only_run()
        self.assertEqual((state.project_id, state.params["idea"]), ("goalkeeper-3d", GOALKEEPER))

    def test_mock_hold_gates_with_an_idea(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", idea=GOALKEEPER, expect=3)
        state = self.only_run()
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "strategy-review"))
        self.assertEqual(state.params, {"mock": True, "idea": GOALKEEPER})
        for artifact_type in ("research-report", "opportunity", "title-strategy"):
            self.assertEqual(brief_of(artifact_type, self.artifact(state, artifact_type)),
                             GOALKEEPER)

    def test_a_quoted_idea_with_spaces_and_quotes_is_one_argument_kept_exactly(self):
        idea = "A  \"keeper's\" game:   dive,  block & $HOME `echo no`"
        self.wgf("new-game", "--mock", "--quiet", idea=idea, expect=3)
        self.assertEqual(self.only_run().params["idea"],
                         "A \"keeper's\" game: dive, block & $HOME `echo no`")

    def test_an_idea_starting_with_a_dash_follows_double_dash(self):
        self.wgf("new-game", "--mock", "--quiet", idea="-3D keeper", dashdash=True, expect=3)
        self.assertEqual(self.only_run().params["idea"], "-3D keeper")

    def test_status_shows_the_idea(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", idea=GOALKEEPER, expect=3)
        run_id = self.only_run().run_id
        shown = self.wgf("status", run_id, expect=3).stdout
        self.assertIn(f"Idea:     {GOALKEEPER}", shown)
        as_json = json.loads(self.wgf("status", run_id, "--json", expect=3).stdout)
        self.assertEqual(as_json["params"]["idea"], GOALKEEPER)

    def test_refusals_run_nothing(self):
        cases = [
            (("new-game", "--mock"), "   "),                        # empty after trimming
            (("new-game", "--mock"), "x" * (IDEA_MAX_LENGTH + 1)),  # too long
            (("verify", "--mock"), GOALKEEPER),                     # no research step
            (("plan", "--mock"), GOALKEEPER),                       # no research step
            (("new-game", "--mock", "--from", "design"), GOALKEEPER),  # research skipped
        ]
        for args, idea in cases:
            with self.subTest(args=args):
                done = self.wgf(*args, idea=idea, expect=2)
                self.assertIn("idea", done.stderr)
        self.assertEqual(self.api().store.list_runs(), [])

    def test_resume_and_run_refuse_a_new_idea(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", idea=GOALKEEPER, expect=3)
        run_id = self.only_run().run_id
        for flag in ("--resume", "--run"):
            with self.subTest(flag=flag):
                done = self.wgf("new-game", flag, run_id, idea="another game", expect=2)
                self.assertIn("IDEA only applies to a new run", done.stderr)
        # `wgf resume` takes no idea at all: argparse refuses the extra argument.
        self.wgf("resume", run_id, idea="another game", expect=2)
        self.assertEqual(self.only_run().params["idea"], GOALKEEPER)

    def test_no_argument_is_the_blank_scan_it_always_was(self):
        self.wgf("new-game", "--mock", "--quiet", expect=3)
        state = self.only_run()
        # A mock run without --hold-gates records exactly these, and nothing about an idea.
        self.assertEqual(sorted(state.params), ["auto_approve", "mock"])
        self.assertEqual(sorted(self.started_params(state.run_id)), ["auto_approve", "mock"])
        report = self.artifact(state, "research-report")
        self.assertNotIn("brief", report["scope"])
        for artifact_type in ("opportunity", "title-strategy", "game-design"):
            self.assertNotIn("brief", self.artifact(state, artifact_type))
        self.assertNotIn("Idea:", self.wgf("status", state.run_id, expect=3).stdout)


# -- resume -----------------------------------------------------------------------------------


class Resume(Scratch):
    def test_resume_keeps_the_idea_and_every_later_artifact_carries_it(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", idea=GOALKEEPER, expect=3)
        run_id = self.only_run().run_id
        self.wgf("decide", run_id, "approve", "--quiet", expect=3)       # G2
        state = self.only_run()
        self.assertEqual(state.cursor, "tech-plan-review")
        self.assertEqual(state.params["idea"], GOALKEEPER)
        self.assertEqual(brief_of("game-design", self.artifact(state, "game-design")),
                         GOALKEEPER)
        self.wgf("resume", run_id, "--quiet", expect=3)                  # still waiting at G3
        self.assertEqual(self.only_run().params["idea"], GOALKEEPER)

    def test_an_idea_edited_into_state_json_is_refused(self):
        self.wgf("new-game", "--mock", "--hold-gates", "--quiet", idea=GOALKEEPER, expect=3)
        run_id = self.only_run().run_id
        path = os.path.join(self.store, "workflows", run_id, "state.json")
        for edit in ("a different game", None):
            with self.subTest(edit=edit):
                with open(path, encoding="utf-8") as handle:
                    original = handle.read()
                data = json.loads(original)
                if edit is None:
                    del data["params"]["idea"]
                else:
                    data["params"]["idea"] = edit
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
                done = self.wgf("resume", run_id, "--quiet", expect=None)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("params.idea", done.stderr + done.stdout)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(original)

    def test_an_idea_is_a_guarded_param(self):
        self.assertIn("idea", integrity.GUARDED_PARAMS)
        state = types.SimpleNamespace(params={"idea": GOALKEEPER})
        self.assertTrue(integrity.params_problems(state, []))   # no WORKFLOW_STARTED record
        self.assertEqual(integrity.params_problems(
            state, [{"event": "WORKFLOW_STARTED", "data": {"params": {"idea": GOALKEEPER}}}]),
            [])


# -- the real modules -------------------------------------------------------------------------


class RealModules(Scratch):
    """research, strategy, G2 and design, with the real modules on the fixture corpus."""

    def real_api(self):
        return WorkflowAPI(config=FactoryConfig({
            "steps": {"modules": ["wgf_discovery", "wgf_strategy", "wgf_design"]},
            "storage": {"fsync": False},
            "discovery": {"corpus": os.path.join(DISCOVERY, "corpus"),
                          "backlog": os.path.join(DISCOVERY, "backlog"), "as_of": AS_OF},
        }), store_dir=self.store)

    def run_plan(self, idea, project="goalkeeper-3d", design=RunStatus.COMPLETED):
        api = self.real_api()
        state = api.run(RunRequest(scope="research", idea=idea, project_id=project))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        run_id = state.run_id
        state = api.run(RunRequest(scope="strategy", run_id=run_id))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        state = api.run(RunRequest(scope="strategy-review", run_id=run_id))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "strategy-review"),
                         state.message)
        state = api.run(RunRequest(resume=run_id, decision="approve", decided_by="human"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        state = api.run(RunRequest(scope="design", run_id=run_id))
        self.assertEqual(state.status, design, state.message)
        return api, state

    def test_research_strategy_and_design_all_derive_from_the_exact_idea(self):
        # The built-in design author has no goalkeeper either. The brief's "3D" makes it fit
        # a 3D shape (arena-dodge) to a strategy whose catalog concept is lanes, and the
        # consistency guard refuses that design - persisted as evidence, route `descope` -
        # rather than build a game nobody approved. Nothing is relaxed to let it through:
        # an agent author (factory.design.author: agent) is what designs the brief itself.
        api, state = self.run_plan(GOALKEEPER, design=RunStatus.FAILED)
        self.assertEqual(state.steps["design"].last_route, "descope")
        contracts = ArtifactContracts()
        bodies = {}
        for artifact_type in BRIEF_BEARING:
            body = self.artifact(state, artifact_type)
            bodies[artifact_type] = body
            self.assertEqual(brief_of(artifact_type, body), GOALKEEPER, artifact_type)
            self.assertEqual(contracts.problems(artifact_type, body), [], artifact_type)
        report = bodies["research-report"]
        self.assertIn(GOALKEEPER, report["scope"]["question"])
        # The catalog has no goalkeeper: research says so instead of pretending, and carries
        # the brief to a shape of the dimension it names.
        gaps = [g for g in report["gaps"] if g["kind"] == "idea-unmatched"]
        self.assertEqual(len(gaps), 1, report["gaps"])
        self.assertIn("goalkeeper", gaps[0]["description"])
        chosen = next(c for c in report["candidates"] if c["status"] == "selected")
        self.assertEqual(chosen["idea_match"], {"terms": [], "dimension": True})
        self.assertEqual(chosen["profile"]["rendering"], "3d")
        self.assertTrue(report["selection"]["rationale"].startswith("Closest to the brief"))
        strategy = bodies["title-strategy"]
        self.assertEqual(strategy["one_liner"], GOALKEEPER)
        self.assertTrue(strategy["why_this_opportunity"].startswith(f'Brief: "{GOALKEEPER}"'))
        self.assertEqual(strategy["title_id"], "goalkeeper-3d")
        design = bodies["game-design"]
        self.assertEqual(design["engine"]["dimension"], "3d")
        breached = {r["criterion_id"] for r in design["consistency"]["rule_results"]
                    if r.get("breached")}
        self.assertEqual(breached, {"concept_mechanics_carried",
                                    "design_adds_no_foreign_mechanic"})

    def test_research_prefers_the_shape_the_idea_names(self):
        state = self.real_api().run(RunRequest(scope="research", project_id="sorter",
                                               idea="A calm sort puzzle with colored balls"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        report = self.artifact(state, "research-report")
        self.assertEqual(report["selection"]["candidate_id"], "sort-puzzle")
        self.assertEqual([g for g in report["gaps"] if g["kind"] == "idea-unmatched"], [])

    def test_without_an_idea_research_is_unchanged(self):
        api = self.real_api()
        state = api.run(RunRequest(scope="research"))
        report = self.artifact(state, "research-report")
        self.assertNotIn("brief", report["scope"])
        self.assertNotIn("brief", self.artifact(state, "opportunity"))
        self.assertTrue(all("idea_match" not in c for c in report["candidates"]))
        self.assertTrue(report["scope"]["question"].startswith("Which kind of web game"))

    def test_the_research_step_reads_exactly_the_runs_idea(self):
        from wgf_discovery.step import ResearchStep
        seen = []

        class Recording(ResearchStep):
            def execute(self, inputs, context):
                seen.append(self.idea(context))
                return super().execute(inputs, context)

        api = self.real_api()
        original = api.registry

        def registry(mock, load_modules=True):
            reg = original(mock, load_modules=load_modules)
            reg.register("research", Recording)
            return reg

        api.registry = registry
        idea = "  3D   goalkeeper\tgame  "
        state = api.run(RunRequest(scope="research", idea=idea))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        self.assertEqual(seen, [canonical_idea(idea)])
        self.assertEqual(seen, ["3D goalkeeper game"])

    def test_the_api_refuses_an_idea_no_step_reads(self):
        with self.assertRaises(EngineError):
            self.real_api().run(RunRequest(scope="plan", idea=GOALKEEPER))


class IdeaMatching(unittest.TestCase):
    def test_whole_words_only(self):
        block = {"genre": "puzzle", "subgenre": "block-puzzle", "title": "Block Puzzle",
                 "core_mechanic": "place blocks", "market_tags": ["puzzle"]}
        self.assertEqual(analysis.idea_match(block, "the keeper blocks shots")["terms"],
                         ["blocks"])
        self.assertEqual(analysis.idea_match(block, "a block game")["terms"], ["block"])
        self.assertEqual(analysis.idea_match(block, "3D keeper"),
                         {"terms": [], "dimension": False})

    def test_dimension(self):
        self.assertEqual(analysis.idea_dimension("3D goalkeeper"), "3d")
        self.assertEqual(analysis.idea_dimension("a 2d runner"), "2d")
        self.assertIsNone(analysis.idea_dimension("2D or 3D"))
        self.assertIsNone(analysis.idea_dimension("goalkeeper"))


# -- the surfaces -----------------------------------------------------------------------------


class Surfaces(unittest.TestCase):
    def test_both_new_game_surfaces_take_the_idea_as_one_verbatim_argument(self):
        for plugin in ("claude-web-game-plugin", "codex-web-game-plugin"):
            with self.subTest(plugin=plugin):
                with open(os.path.join(ROOT, plugin, "commands", "new-game.md"),
                          encoding="utf-8") as handle:
                    text = handle.read()
                for phrase in ("game idea", "--json -- '<idea>'", "blank market scan",
                               "only the run's identity"):
                    self.assertTrue(phrase in text, f"{plugin} new-game.md lacks {phrase!r}")
        with open(os.path.join(ROOT, "claude-web-game-plugin", "commands", "new-game.md"),
                  encoding="utf-8") as handle:
            self.assertTrue('[\\"<game idea>\\"]' in handle.read(), "argument-hint lacks the idea")


if __name__ == "__main__":
    unittest.main()
