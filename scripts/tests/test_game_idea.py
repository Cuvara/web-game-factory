"""A game idea given to a new run: `wgf new-game [--project ID] "IDEA"`.

The idea is the run's brief. It is canonicalised once (wgflib.workflow.api.canonical_idea),
recorded in the run's params - and so in WORKFLOW_STARTED, which every resume corroborates -
handed to steps as `context.environment["idea"]`, and carried by the artifacts that have a
place for it: research-report `scope.brief`, opportunity, title-strategy and game-design
`brief`. `--project` stays the run's identity; without an idea the run is the blank market
scan it always was.

Covered: the CLI (positional idea, with and without --project, with --mock --hold-gates,
quoting, refusals), the run state, resume, the real research / strategy / design modules
against the discovery fixture corpus, research's idea_fallback and the project concepts
file, and the generated command surfaces.

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
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
WGF = os.path.join(SCRIPTS, "wgf.py")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgf_discovery import analysis  # noqa: E402
from wgf_discovery.step import CATALOG, ResearchStep  # noqa: E402
from wgflib.workflow import integrity  # noqa: E402
from wgflib.workflow.api import (  # noqa: E402
    IDEA_MAX_LENGTH, RunRequest, WorkflowAPI, canonical_idea)
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.model import RunStatus, StepOutcome  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

# A brief the catalog cannot answer: no catalog entry, genre family or genre-node alias holds
# any of its words, which is what makes it the fixture for "nothing matches the brief".
# "saves penalty kicks", not "blocks penalty shots": "blocks" is a genre node of the
# block-puzzle family, and a goalkeeper is not a block puzzle.
GOALKEEPER = "3D goalkeeper game where the player saves penalty kicks"
# The live brief that once selected the endless runner on one incidental verb ("collect").
MARBLE = ("A 3D low-poly marble-roll game (Three.js): tilt/steer a marble across floating "
          "sky-island courses, ramps, moving platforms, gaps and bumpers; collect gems, beat "
          "the par time for stars; 3 themed worlds of hand-designed courses, unlocks and saved "
          "progress, a time-trial mode with personal bests. Chase camera, desktop keys and "
          "mobile touch.")
DISCOVERY = os.path.join(HERE, "fixtures", "discovery")
CONCEPTS = os.path.join(DISCOVERY, "concepts", "concepts.yaml")
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

    def real_api(self, design=None, **discovery):
        return WorkflowAPI(config=FactoryConfig({
            "steps": {"modules": ["wgf_discovery", "wgf_strategy", "wgf_design"]},
            "storage": {"fsync": False},
            "design": design or {},
            # The built-in design author writes MVP-sized content: at tier release the
            # design is held to the quality benchmark (content.tier_*).
            "strategy": {"quality_tier": "mvp"},
            "discovery": dict({"corpus": os.path.join(DISCOVERY, "corpus"),
                               "backlog": os.path.join(DISCOVERY, "backlog"), "as_of": AS_OF},
                              **discovery),
        }), store_dir=self.store)

    def run_plan(self, idea, project="goalkeeper-3d", design=RunStatus.COMPLETED, **discovery):
        api = self.real_api(**discovery)
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
        # The catalog has no goalkeeper. With idea_fallback: nearest, research carries the
        # brief to the nearest buildable concept of the dimension it names, and says so. The
        # built-in design author fits the archetype that concept declares (never one the
        # brief's words would pick, which design consistency would refuse), records the
        # brief, and states as an open question that it is not the brief's dimension. The
        # agent author designs the brief.
        api, state = self.run_plan(GOALKEEPER, idea_fallback="nearest")
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
        self.assertTrue(any(GOALKEEPER in a["statement"] for a in strategy["assumptions"]))
        self.assertNotIn(GOALKEEPER, strategy["one_liner"])
        self.assertEqual(strategy["title_id"], "goalkeeper-3d")
        design = bodies["game-design"]
        self.assertEqual(design["consistency"]["status"], "pass")
        self.assertEqual(design["engine"]["dimension"], "2d")
        self.assertTrue(any(q.startswith("The brief names 3d; this design is 2d")
                            for q in design["open_questions"]), design["open_questions"])

    def test_research_prefers_the_shape_the_idea_names(self):
        state = self.real_api().run(RunRequest(scope="research", project_id="swapper",
                                               idea="A match-3 puzzle with candy tiles"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        report = self.artifact(state, "research-report")
        self.assertEqual(report["selection"]["candidate_id"], "match-3")
        self.assertEqual([g for g in report["gaps"] if g["kind"] == "idea-unmatched"], [])

    def test_an_unbuildable_match_is_never_selected_for_the_idea(self):
        # physics-puzzle matches the most words, but the catalog declares neither a design
        # archetype nor a genre model for it: research keeps it excluded and carries the brief
        # to a buildable concept.
        state = self.real_api().run(RunRequest(
            scope="research", project_id="dropper",
            idea="A calm physics puzzle with falling blocks"))
        report = self.artifact(state, "research-report")
        physics = next(c for c in report["candidates"] if c["id"] == "physics-puzzle")
        self.assertEqual(physics["status"], "excluded")
        self.assertEqual(physics["idea_match"]["terms"], ["physics", "puzzle"])
        self.assertNotEqual(report["selection"]["candidate_id"], "physics-puzzle")

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

        api = self.real_api(idea_fallback="nearest")
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

    def test_an_idea_no_concept_carries_waits_for_input_by_default(self):
        state = self.real_api().run(RunRequest(scope="research", idea=GOALKEEPER,
                                               project_id="goalkeeper-3d"))
        self.assertEqual((state.status, state.cursor), (RunStatus.WAITING, "research"),
                         state.message)
        self.assertIn("concepts.yaml", state.message)
        self.assertIn("idea_fallback: nearest", state.message)
        self.assertIsNone(state.latest_artifact("opportunity"))
        report = self.artifact(state, "research-report")
        self.assertEqual(report["selection"]["candidate_id"], "none")

    def assert_only_the_agent_designs_it(self, strategy):
        """F09 at design: the archetype author refuses an agent-only concept with the fix,
        never swapping in a catalog archetype; as the agent's starting point it picks
        within the strategy's dimension."""
        from wgf_design import archetypes
        from wgf_design.authors import ArchetypeAuthor, AuthorError
        from wgf_design.platforms import load_platforms
        self.assertEqual(strategy["research"]["capability"]["design_archetype"], "agent")
        brief = {"title_id": "goalkeeper-3d", "strategy": strategy,
                 "platforms": load_platforms(strategy, None), "params": {}}
        with self.assertRaises(AuthorError) as raised:
            ArchetypeAuthor().draft(brief)
        self.assertIn("design: {author: agent}", str(raised.exception))
        dimension = archetypes.dimension_of(strategy)
        self.assertIn(dimension, ("2d", "3d"))
        chosen, _why = archetypes.select(strategy)
        self.assertEqual(archetypes.ARCHETYPES[chosen]["dimension"], dimension)
        starting = ArchetypeAuthor(starting_point=True).draft(brief)
        self.assertIn(f"Archetype {chosen!r} was chosen", " ".join(starting["open_questions"]))

    def test_a_concept_for_the_idea_is_carried_through_strategy(self):
        # The fixture concept is `design_archetype: agent`: only the agent author designs it.
        api = self.real_api(design={"author": "agent"}, concepts=CONCEPTS)
        state = api.run(RunRequest(scope="research", idea=GOALKEEPER,
                                   project_id="goalkeeper-3d"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        state = api.run(RunRequest(scope="strategy", run_id=state.run_id))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.message)
        entry = load_file(CONCEPTS)["archetypes"][0]
        strategy = self.artifact(state, "title-strategy")
        self.assert_only_the_agent_designs_it(strategy)
        self.assertEqual(strategy["concept"]["core_mechanic"], entry["core_mechanic"])
        self.assertEqual(strategy["concept"]["core_loop"], entry["core_loop"])
        self.assertEqual(strategy["brief"], GOALKEEPER)


def research(idea=GOALKEEPER, config=None, **params):
    """The research step alone on the fixture corpus, as the engine would hand it the idea.
    `config` is the factory section (default: the agent design author, which the fixture
    concepts - `design_archetype: agent` - need)."""
    base = {"corpus": os.path.join(DISCOVERY, "corpus"),
            "backlog": os.path.join(DISCOVERY, "backlog"), "as_of": AS_OF}
    base.update(params)
    step = ResearchStep(types.SimpleNamespace(
        id="research", type="research", params=base, inputs=[],
        outputs=["research-report", "opportunity"]),
        clock=lambda: datetime(2026, 9, 23, tzinfo=timezone.utc))
    logger = types.SimpleNamespace(**{level: (lambda *a, **k: None)
                                      for level in ("debug", "info", "warning", "error")})
    context = types.SimpleNamespace(
        config=AGENT_AUTHOR if config is None else config, execution=1, attempt=1,
        visit=1, project_id=None, run_id="run-test",
        current_step="research", idempotency_key="run-test:research:1", logger=logger,
        mock=False, environment={"idea": idea} if idea else {}, previous_outputs=[],
        decision=None)
    return step.execute(types.SimpleNamespace(refs={}, missing=[]), context)


AGENT_AUTHOR = {"design": {"author": "agent"}}


def outputs(result):
    return {a.type: a.content for a in result.artifacts}


class IdeaFallback(unittest.TestCase):
    """What research does with a brief no eligible catalog concept matches."""

    def test_wait_is_the_default_and_selects_nothing(self):
        result = research()
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)
        self.assertIn("the brief matches no concept research can carry", result.message)
        self.assertIn("concepts.yaml", result.message)
        self.assertIn("discovery.idea_fallback: nearest", result.message)
        out = outputs(result)
        self.assertEqual(list(out), ["research-report"])
        report = out["research-report"]
        self.assertEqual(ArtifactContracts().problems("research-report", report), [])
        self.assertEqual(report["selection"]["candidate_id"], "none")
        self.assertIn("idea_fallback is wait", report["selection"]["rationale"])
        # Every candidate is kept, none selected; the nearest shape is information only.
        self.assertNotIn("selected", {c["status"] for c in report["candidates"]})
        self.assertTrue(any(c["status"] == "considered" for c in report["candidates"]))
        gaps = [g for g in report["gaps"] if g["kind"] == "idea-unmatched"]
        self.assertEqual(len(gaps), 1, report["gaps"])
        self.assertIn("goalkeeper", gaps[0]["description"])
        self.assertIn("nothing was selected", gaps[0]["description"])
        self.assertIn("endless-runner", gaps[0]["description"])
        self.assertNotIn("concepts", {c["id"] for c in report["method"]["collectors"]})

    def test_a_brief_sharing_one_incidental_word_waits(self):
        # The live defect: the marble brief selected endless-runner on "collect" alone.
        result = research(idea=MARBLE)
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT, result.message)
        out = outputs(result)
        self.assertEqual(list(out), ["research-report"])
        report = out["research-report"]
        self.assertEqual(report["selection"]["candidate_id"], "none")
        self.assertEqual([c["id"] for c in report["candidates"] if c["idea_match"]["terms"]],
                         [])

    def test_missing_external_evidence_still_waits_first(self):
        empty = tempfile.mkdtemp(prefix="wgf-idea-corpus-")
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        os.makedirs(os.path.join(empty, "snapshots"))
        result = research(corpus=empty)
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)
        self.assertIn("no external evidence", result.message)

    def test_nearest_selects_the_nearest_shape(self):
        result = research(idea_fallback="nearest")
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        report = outputs(result)["research-report"]
        self.assertEqual(report["selection"]["candidate_id"], "endless-runner")

    def test_a_matched_idea_is_selected_either_way(self):
        for fallback in ("wait", "nearest"):
            with self.subTest(fallback=fallback):
                result = research(idea="A match-3 puzzle with candy tiles",
                                  idea_fallback=fallback)
                self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
                self.assertEqual(outputs(result)["research-report"]["selection"]
                                 ["candidate_id"], "match-3")

    def test_any_other_value_is_refused(self):
        for bad in ("substitute", None, ""):
            with self.subTest(bad=bad):
                result = research(idea_fallback=bad)
                self.assertEqual(result.outcome, StepOutcome.FAILED)
                self.assertFalse(result.retryable)
                self.assertIn("idea_fallback", result.error)

    def test_without_an_idea_neither_setting_changes_a_byte(self):
        blank = outputs(research(idea=None))
        for params in ({"idea_fallback": "nearest"}, {"concepts": CONCEPTS}):
            with self.subTest(params=params):
                self.assertEqual(outputs(research(idea=None, **params)), blank)


class ConceptsFile(unittest.TestCase):
    """A concept a project authored for the brief: <corpus>/concepts.yaml, or `concepts`."""

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-concepts-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.entry = load_file(CONCEPTS)["archetypes"][0]

    def write(self, text, name="concepts.yaml"):
        path = os.path.join(self.scratch, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def edited(self, old, new):
        with open(CONCEPTS, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(old, text)
        return self.write(text.replace(old, new, 1),
                          name=f"concepts-{len(os.listdir(self.scratch))}.yaml")

    def test_a_concept_only_the_agent_designs_waits_under_the_archetype_author(self):
        # F09: the shipped default author is archetype. Selecting an agent-only concept used
        # to reach design (after strategy and a person's G2), which swapped in a catalog
        # archetype by keyword - a 2D brief designed as a 3D arena-dodge - and failed.
        for config in ({}, {"design": {"author": "archetype"}}):
            with self.subTest(config=config):
                result = research(concepts=CONCEPTS, config=config)
                self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT,
                                 result.message)
                self.assertIn(self.entry["id"], result.message)
                self.assertIn("design: {author: agent}", result.message)
                self.assertIn("workspace/config/factory.yaml", result.message)
                types_out = [a.type for a in result.artifacts]
                self.assertEqual(types_out, ["research-report"])  # no opportunity carried

    def test_the_concept_is_selected_and_carried_verbatim(self):
        result = research(concepts=CONCEPTS)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        out = outputs(result)
        report, opportunity = out["research-report"], out["opportunity"]
        contracts = ArtifactContracts()
        self.assertEqual(contracts.problems("research-report", report), [])
        self.assertEqual(contracts.problems("opportunity", opportunity), [])
        self.assertEqual(report["selection"]["candidate_id"], "shot-stopper")
        self.assertEqual([g for g in report["gaps"] if g["kind"] == "idea-unmatched"], [])
        for key in ("genre", "subgenre", "core_mechanic", "fantasy", "core_loop"):
            self.assertEqual(opportunity["concept"][key], self.entry[key], key)
        self.assertEqual(opportunity["brief"], GOALKEEPER)
        collector = next(c for c in report["method"]["collectors"] if c["id"] == "concepts")
        self.assertEqual((collector["kind"], collector["status"]), ("reference", "used"))

    def test_its_figures_stay_hypotheses_and_it_says_it_is_authored(self):
        report = outputs(research(concepts=CONCEPTS))["research-report"]
        claims = {c["id"]: c for c in report["claims"]}
        chosen = next(c for c in report["candidates"] if c["id"] == "shot-stopper")
        for dimension in chosen["dimensions"]:
            if dimension["dimension"] in ("dev_speed_days", "asset_cost", "scope_complexity",
                                          "retention_potential"):
                self.assertEqual(dimension["tier"], "hypothesis")
                for ref in dimension["claim_refs"]:
                    self.assertEqual(claims[ref]["tier"], "hypothesis")
                    self.assertLessEqual(claims[ref]["confidence"], 0.6)
        authored = [claims[ref] for ref in chosen["claim_refs"]
                    if "concept" in claims[ref]["tags"]]
        self.assertEqual(len(authored), 1)
        self.assertEqual(authored[0]["tier"], "hypothesis")
        self.assertLessEqual(authored[0]["confidence"], 0.6)
        for phrase in (GOALKEEPER, "concepts.yaml", "not a catalog shape", "unmeasured"):
            self.assertIn(phrase, authored[0]["statement"])
        # Catalog candidates carry no such claim.
        runner = next(c for c in report["candidates"] if c["id"] == "endless-runner")
        self.assertFalse(any("concept" in claims[ref]["tags"] for ref in runner["claim_refs"]))

    def test_the_report_id_changes_with_the_file(self):
        waiting = outputs(research())["research-report"]["id"]
        first = outputs(research(concepts=CONCEPTS))["research-report"]["id"]
        second = outputs(research(concepts=self.edited("dev_speed_days: 14",
                                                       "dev_speed_days: 12")))
        self.assertNotEqual(first, waiting)
        self.assertNotEqual(second["research-report"]["id"], first)
        self.assertEqual(outputs(research(concepts=CONCEPTS))["research-report"]["id"], first)

    def test_the_default_file_is_in_the_corpus(self):
        corpus = os.path.join(self.scratch, "corpus")
        shutil.copytree(os.path.join(DISCOVERY, "corpus"), corpus)
        shutil.copy(CONCEPTS, os.path.join(corpus, "concepts.yaml"))
        result = research(corpus=corpus)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        self.assertEqual(outputs(result)["research-report"]["selection"]["candidate_id"],
                         "shot-stopper")

    def test_refusals_are_permanent(self):
        cases = {
            "another brief": (self.edited(f"brief: {GOALKEEPER}", "brief: a different game"),
                              "another brief"),
            "no design_archetype": (self.edited("    design_archetype: agent\n", ""),
                                    "design_archetype"),
            "null design_archetype": (self.edited("design_archetype: agent",
                                                  "design_archetype: null"),
                                      "design_archetype"),
            "not kebab-case": (self.edited("design_archetype: agent",
                                           "design_archetype: Lane Runner"),
                               "design_archetype"),
            "a catalog id": (self.edited("id: shot-stopper", "id: endless-runner"),
                             "catalog already has"),
            "a catalog key missing": (self.edited("    core_loop: read", "    loop: read"),
                                      "core_loop"),
            "not the catalog's shape": (self.write("archetypes: []\n", name="bare.yaml"),
                                        "version"),
            "a configured file that does not exist": (
                os.path.join(self.scratch, "absent.yaml"), "no concepts file"),
            # Found by the dogfood run: a note written where the priors go was read as a
            # prior, so every prior dimension went unscored and the note became claim text.
            "priors that are not priors": (
                self.edited("priors: {", "priors: {note: guessed, "), "priors"),
            "a prior outside [0, 1]": (
                self.edited("monetization_fit: 0.", "monetization_fit: 7."), "priors"),
        }
        for name, (path, words) in cases.items():
            with self.subTest(name):
                result = research(concepts=path)
                self.assertEqual(result.outcome, StepOutcome.FAILED, result.message)
                self.assertFalse(result.retryable)
                self.assertIn(words, result.error)


class IdeaMatching(unittest.TestCase):
    def test_whole_words_only(self):
        block = {"genre": "puzzle", "subgenre": "block-puzzle", "title": "Block Puzzle",
                 "core_mechanic": "place blocks", "market_tags": ["puzzle"]}
        self.assertEqual(analysis.idea_match(block, "a puzzle where the keeper blocks shots")
                         ["terms"], ["puzzle", "blocks"])
        self.assertEqual(analysis.idea_match(block, "a block game")["terms"], ["block"])
        self.assertEqual(analysis.idea_match(block, "3D keeper"),
                         {"terms": [], "dimension": False})

    def test_one_incidental_word_is_not_a_match(self):
        # The defect: the marble brief shares only "collect" with the endless runner's
        # mechanic sentence, and "three" (Three.js) with match-3's. Neither is the brief.
        catalog = {a["id"]: a for a in load_file(CATALOG)["archetypes"]}
        for archetype_id in ("endless-runner", "match-3", "one-touch-arcade", "io-arena",
                             "car-parking"):
            with self.subTest(archetype=archetype_id):
                self.assertEqual(analysis.idea_match(catalog[archetype_id], MARBLE)["terms"],
                                 [])
        # Generic gameplay and engine vocabulary is no word of any brief.
        for word in ("collect", "stars", "levels", "time", "touch", "three", "js"):
            self.assertNotIn(word, analysis.idea_terms(MARBLE + " levels"))

    def test_a_brief_naming_the_genre_still_matches(self):
        runner = {a["id"]: a for a in load_file(CATALOG)["archetypes"]}["endless-runner"]
        self.assertEqual(analysis.idea_match(runner, "an endless runner where you collect "
                                                     "coins")["terms"], ["endless", "runner"])
        # Its mechanic sentence alone matches on two of its words, never on one.
        self.assertEqual(analysis.idea_match(runner, "dodge obstacles across lanes")["terms"],
                         ["dodge", "obstacles", "lanes"])
        self.assertEqual(analysis.idea_match(runner, "dodge the goalkeeper")["terms"], [])

    def test_dimension(self):
        self.assertEqual(analysis.idea_dimension("3D goalkeeper"), "3d")
        self.assertEqual(analysis.idea_dimension("a 2d runner"), "2d")
        self.assertIsNone(analysis.idea_dimension("2D or 3D"))
        self.assertIsNone(analysis.idea_dimension("goalkeeper"))

    def test_idea_matches_a_family_label(self):
        """An entry built from a genre model is the shape of its whole family: the family's
        label and the genre nodes it covers are words for the same game."""
        survivor = {"genre": "action", "subgenre": "arena-survivor", "title": "Arena Survivor",
                    "core_mechanic": "weapons fire themselves", "genre_model": "survival",
                    "market_tags": ["action"]}
        # "survival" is in neither the genre, the subgenre, the title nor the tags: only the
        # family label (Survival (arena survivor)) holds it.
        self.assertEqual(analysis.idea_match(survivor, "a survival game")["terms"],
                         ["survival"])
        self.assertEqual(analysis.idea_match(dict(survivor, genre_model=None),
                                            "a survival game")["terms"], [])
        # A node id matches whole and is never split: the puzzle family covers bubble-shooter,
        # which does not make a block puzzle a shooter.
        block = {"genre": "puzzle", "subgenre": "block-puzzle", "title": "Block Grid Puzzle",
                 "core_mechanic": "drag given block shapes onto a grid",
                 "genre_model": "puzzle", "market_tags": ["puzzle"]}
        self.assertEqual(analysis.idea_match(block, "a shooter game")["terms"], [])
        self.assertEqual(analysis.idea_match(block, "a bubble-shooter game")["terms"],
                         ["bubble-shooter"])
        # End to end, on the fixture corpus: the brief selects the shape its family names.
        report = outputs(research(idea="a tower defense game"))["research-report"]
        self.assertEqual(report["selection"]["candidate_id"], "tower-defense")
        chosen = next(c for c in report["candidates"] if c["status"] == "selected")
        self.assertEqual(chosen["idea_match"]["terms"], ["tower", "defense"])
        self.assertEqual([g for g in report["gaps"] if g["kind"] == "idea-unmatched"], [])


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
