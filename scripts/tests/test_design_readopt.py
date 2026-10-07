"""A re-entered design on an adopted repository measures what the checkout ships now.

Found live (2026-10-07, the 3D run new-game-20261005-002923-597b5e): a person moved the
adopted checkout to a human-accepted content set (12 courses first-roll..the-summit) and
resumed the run from strategy. The re-entered design kept the floor its earlier visit had
counted at f7434a0 - an intermediate commit of the run's own build - with that build's units
meadow-roll..storm-crown, answered the old design's gaps on those units, and greybox started a
developer to make the game conform: a rewrite of the accepted courses. These tests hold:

  * wgf_design/existing.py: the floor is counted at HEAD less the run's own commits (their
    `Wgf-<Step>-Key` trailers name the run); a person's commit moves it, the run's own build
    never does; a moved floor records the one it replaces in `supersedes`; the replayed run
    store's floor now starts from c340631's twelve courses;
  * wgf_design/step.py + agent.py: a visit whose checkout ships units the last design does
    not plan is an adoption - the shipped units are the starting units, the request and the
    prompt say extend, the last design's gaps are not repaired - and a design that keeps the
    old ids breaches existing_content_floor_kept;
  * wgf_develop: the brief names the shipped units to extend, and a design that drops shipped
    ids while listing others is BLOCKED before any developer starts.

Offline (local git repositories in a temporary directory). Run from the repository root:

    python -m unittest scripts.tests.test_design_readopt
"""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import test_design_agent as agent_tests  # noqa: E402
import test_design_module as design_tests  # noqa: E402
import test_develop_module as develop_tests  # noqa: E402
from wgf_design import existing  # noqa: E402
from wgf_develop import brief as develop_briefs  # noqa: E402
from wgf_develop import floor as develop_floor  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

RUN = "new-game-20261005-002923-597b5e"
STORE = os.path.join(HERE, "fixtures", "design", "readopt-3d", "run-store.json")
CONTENT = "public/content/units.json"


def load_store():
    with open(STORE, encoding="utf-8") as handle:
        return json.load(handle)


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                           "-c", "core.autocrlf=false", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit_content(checkout, units, message):
    path = os.path.join(checkout, *CONTENT.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"schema": "wgf-content/1", "units": units}, handle)
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", message)
    return git(checkout, "rev-parse", "HEAD")


def run_commit(checkout, step="Develop", key=None):
    """A commit a step of RUN makes on top: a file outside the content data."""
    with open(os.path.join(checkout, "game.config.yaml"), "a", encoding="utf-8",
              newline="\n") as handle:
        handle.write(f"# {step}\n")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m",
        f"chore: {step.lower()}\n\nWgf-{step}-Key: {key or RUN + ':' + step.lower() + ':1'}")
    return git(checkout, "rev-parse", "HEAD")


def units_named(ids, base=None):
    return [dict(copy.deepcopy(base or {}), id=uid, index=n + 1, tier="mvp",
                 objective=f"Clear {uid}", mechanics=["steer"])
            for n, uid in enumerate(ids)]


class Checkout(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-readopt-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.title = "demo-title"
        self.checkout = os.path.join(self.base, self.title)
        os.makedirs(self.checkout)
        git(self.checkout, "init", "-q")
        self.config = {"checkouts": self.base, "init": {"adopt_existing": True}}

    def floor(self, run_id=RUN, config=None):
        return existing.read_adoption(config or self.config, self.title, run_id=run_id)


class TheShippedCommit(Checkout):
    def test_a_step_key_of_the_run_marks_its_own_commit(self):
        self.assertTrue(existing.run_commit(f"x\n\nWgf-Develop-Key: {RUN}:develop:3", RUN))
        self.assertTrue(existing.run_commit(f"x\n\nWgf-Init-Key: wgf-init:{RUN}:init", RUN))
        self.assertFalse(existing.run_commit("x\n\nWgf-Develop-Key: other-run:develop:3", RUN))
        self.assertFalse(existing.run_commit(f"mentions {RUN} in prose", RUN))
        self.assertFalse(existing.run_commit(f"Wgf-Develop-Key: {RUN}:develop:3", None))

    def test_the_runs_own_commits_on_top_never_move_the_floor(self):
        shipped = commit_content(self.checkout, units_named(["a", "b"]), "the shipped game")
        run_commit(self.checkout, "Init", f"wgf-init:{RUN}:init")
        # The run's own build grows the content: still not what the checkout shipped.
        path = os.path.join(self.checkout, *CONTENT.split("/"))
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"units": units_named(["a", "b", "c"])}, handle)
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "-q", "-m", f"dev\n\nWgf-Develop-Key: {RUN}:develop:1")
        floor, note, units = self.floor()
        self.assertEqual(floor["source"]["commit"], shipped)
        self.assertEqual(floor["unit_ids"], ["a", "b"])
        self.assertEqual(floor["source"]["head"], git(self.checkout, "rev-parse", "HEAD"))
        self.assertIn("2 commit(s) this run made", floor["source"]["baseline"])
        self.assertEqual([u["id"] for u in units], ["a", "b"])

    def test_without_a_run_id_the_floor_is_head(self):
        commit_content(self.checkout, units_named(["a"]), "shipped")
        head = run_commit(self.checkout)
        floor, _note, _units = self.floor(run_id=None)
        self.assertEqual(floor["source"]["commit"], head)
        self.assertNotIn("head", floor["source"])

    def test_a_persons_commit_on_top_of_the_run_is_what_ships(self):
        commit_content(self.checkout, units_named(["a", "b"]), "shipped")
        run_commit(self.checkout)
        moved = commit_content(self.checkout, units_named(["x", "y", "z"]), "a person")
        floor, _note, _units = self.floor()
        self.assertEqual(floor["source"]["commit"], moved)
        self.assertEqual(floor["unit_ids"], ["x", "y", "z"])

    def test_an_accepted_baseline_names_the_floor(self):
        accepted = commit_content(self.checkout, units_named(["a", "b"]), "accepted")
        git(self.checkout, "tag", "baseline-r1")
        commit_content(self.checkout, units_named(["a"]), "a person cut one")
        config = dict(self.config, init=dict(self.config["init"],
                                             accepted_baseline="baseline-r1"))
        floor, _note, _units = self.floor(config=config)
        self.assertEqual(floor["source"]["commit"], accepted)
        self.assertEqual(floor["unit_ids"], ["a", "b"])
        config["init"]["accepted_baseline"] = "no-such-ref"
        with self.assertRaises(ValueError):
            self.floor(config=config)


class Reconcile(unittest.TestCase):
    def floor(self, commit, ids):
        return {"source": {"method": "content-data", "path": CONTENT, "commit": commit},
                "units": len(ids), "unit_ids": list(ids)}

    def test_the_same_commit_keeps_the_recorded_floor(self):
        kept = dict(self.floor("a" * 40, ["x"]), reason="kept")
        self.assertIs(existing.reconcile(kept, self.floor("a" * 40, ["y"])), kept)

    def test_nothing_read_now_keeps_the_recorded_floor(self):
        kept = self.floor("a" * 40, ["x"])
        self.assertIs(existing.reconcile(kept, None), kept)
        self.assertIsNone(existing.reconcile(None, None))

    def test_the_same_content_at_another_commit_records_the_new_commit(self):
        digest = existing.units_digest([{"id": "x"}])
        now = dict(self.floor("b" * 40, ["x"]), units_digest=digest)
        chosen = existing.reconcile(dict(self.floor("a" * 40, ["x"]), units_digest=digest), now)
        self.assertIs(chosen, now)
        self.assertNotIn("supersedes", chosen)

    def test_other_content_under_the_same_ids_supersedes(self):
        was = dict(self.floor("a" * 40, ["x"]), units_digest=existing.units_digest([{"id": "x"}]))
        now = dict(self.floor("b" * 40, ["x"]),
                   units_digest=existing.units_digest([{"id": "x", "objective": "other"}]))
        chosen = existing.reconcile(was, now)
        self.assertEqual(chosen["supersedes"]["units_digest"], was["units_digest"])

    def test_other_content_supersedes_the_recorded_floor(self):
        chosen = existing.reconcile(self.floor("a" * 40, ["x", "y"]),
                                    self.floor("b" * 40, ["p", "q", "r"]))
        self.assertEqual(chosen["unit_ids"], ["p", "q", "r"])
        self.assertEqual(chosen["supersedes"], {"status": "measured", "unit_ids": ["x", "y"],
                                                "commit": "a" * 40, "units": 2})


class TheReplayedRunStore(Checkout):
    """The real 3D run's artifacts: the checkout a person moved to c340631's courses, the
    run's init commit on top, and the floor design v4 recorded at f7434a0."""

    def setUp(self):
        super().setUp()
        self.store = load_store()
        self.shipped = commit_content(self.checkout, self.store["shipped_content"]["units"],
                                      "style: prettier on course.ts and the content test")
        with open(os.path.join(self.checkout, "game.config.yaml"), "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write("engine: {type: threejs}\n")
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "-q", "-m", self.store["init_message"])
        self.accepted = [u["id"] for u in self.store["shipped_content"]["units"]]

    def test_the_floor_is_the_accepted_courses_and_supersedes_v4s(self):
        current, _note, units = self.floor(run_id=self.store["run_id"])
        self.assertEqual(current["source"]["commit"], self.shipped)
        floor = existing.reconcile(self.store["design_v4_floor"], current)
        self.assertEqual(floor["unit_ids"], self.accepted)
        self.assertEqual(floor["unit_ids"][0], "first-roll")
        self.assertEqual(floor["unit_ids"][-1], "the-summit")
        self.assertEqual(floor["supersedes"]["commit"], self.store["commits"]["floor_v4"])
        self.assertEqual(floor["supersedes"]["unit_ids"], self.store["design_v4_unit_ids"])
        self.assertEqual(len(existing.adoption_units(units)), 12)
        # Recorded, it is a valid game-design floor.
        design = {"existing_content": floor}
        self.assertEqual([p for p in ArtifactContracts()("game-design", design)
                          if "existing_content" in p], [])

    def test_v4s_units_breach_the_floor_the_checkout_ships(self):
        current, _note, _units = self.floor(run_id=self.store["run_id"])
        floor = existing.reconcile(self.store["design_v4_floor"], current)
        design = {"existing_content": floor, "build_spec": {"content": {
            "units": units_named(self.store["design_v4_unit_ids"])}}}
        short = existing.floor_view(design)["short"]
        self.assertTrue(any(s.startswith("unit ids: the design drops 12 unit(s)") and
                            "first-roll" in s for s in short), short)

    def test_greybox_refuses_v4_before_any_developer(self):
        current, _note, _units = self.floor(run_id=self.store["run_id"])
        design = {"existing_content": dict(self.store["design_v4_floor"]),
                  "build_spec": {"content": {
                      "units": units_named(self.store["design_v4_unit_ids"])}}}

        class Git:
            def head(_self):
                return git(self.checkout, "rev-parse", "HEAD")

            def file_at(_self, commit, path):
                return git(self.checkout, "show", f"{commit}:{path}")

        reason = develop_floor.replacement(design, Git(), "greybox")
        self.assertIn("replaces the adopted game's content", reason)
        self.assertIn("first-roll", reason)
        self.assertIn("meadow-roll", reason)
        # On the re-measured floor and a design that keeps every course: nothing refused.
        kept = existing.adoption_units(self.store["shipped_content"]["units"])
        design = {"existing_content": current, "build_spec": {"content": {
            "units": kept + units_named(["bonus-isle"])}}}
        self.assertIsNone(develop_floor.replacement(design, Git(), "greybox"))


class AReEnteredDesignAdopts(agent_tests.AgentCase):
    """Visit 2 of a run whose checkout a person moved: the agent starts from the shipped
    units, not from the last design's, and its gaps are not repaired."""

    def setUp(self):
        super().setUp()
        self.run_dir = os.path.join(self.scratch, "run")
        self.strategy = design_tests.load_strategy()
        first = design_tests.run_step(self.strategy)
        self.assertEqual(first.outcome, StepOutcome.SUCCESS, first.error)
        previous = first.artifacts[0].content
        units = previous["build_spec"]["content"]["units"]
        self.old_ids = [u["id"] for u in units]
        # The person's content: the same units under other ids (so the game still checks).
        shipped = self.shipped_from(units)
        self.new_ids = [u["id"] for u in shipped]
        self.checkouts = os.path.join(self.scratch, "games")
        self.checkout = os.path.join(self.checkouts, self.strategy["title_id"])
        os.makedirs(self.checkout)
        git(self.checkout, "init", "-q")
        self.old_commit = commit_content(self.checkout, units, "the run's earlier build")
        self.moved = commit_content(self.checkout, shipped, "a person: the accepted content")
        run_commit(self.checkout, "Init", f"wgf-init:{RUN}:init")
        # The previous design recorded a floor of its own units at the earlier commit.
        previous = copy.deepcopy(previous)
        previous["existing_content"] = dict(
            existing.measure(units), source={"method": "content-data", "path": CONTENT,
                                             "commit": self.old_commit})
        location = "artifacts/game-design/v1.json"
        path = os.path.join(self.run_dir, *location.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = json.dumps(previous, indent=2).encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(payload)
        self.ref = agent_tests.ArtifactRef(
            id="game-design", type="game-design", version=1, location=location,
            checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            content_hash=previous["provenance"]["content_hash"], seq=1)

    def shipped_from(self, units):
        """The person's content: the same units under other ids (so the game still checks)."""
        return [dict(copy.deepcopy(unit), id=f"accepted-{n + 1}", layout={"rows": ["#..#"]})
                for n, unit in enumerate(units)]

    def visit(self, config):
        config = dict(config, checkouts=self.checkouts, init={"adopt_existing": True})
        report = {"design_gaps": [{"field": "build_spec.content.units[0].difficulty",
                                   "question": "Is the first unit too easy?",
                                   "severity": "minor"}],
                  "provenance": {"artifact_id": "wgf:prototype-report:mock-title:20261007-01",
                                 "content_hash": "sha256:" + "cd" * 32}}
        context = design_tests.FakeContext(config, run_dir=self.run_dir,
                                           previous_outputs=[self.ref], visit=2)
        context.run_id = RUN
        step = design_tests.FixedClockStep(design_tests.FakeDefinition())
        return step.execute(design_tests.FakeInputs(self.strategy,
                                                    extra={"prototype-report": report}),
                            context), context

    def test_the_agent_starts_from_the_shipped_units_and_repairs_no_gap(self):
        config = self.config("revise", argv=[sys.executable, self.host, "revise", "{request}",
                                             "{draft}", "{prompt}"])
        result, context = self.visit(config)
        # A fresh adoption, not a gap repair: no `-gaps` request.
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "design",
                                                     "2-1-gaps.request.json")))
        request = self.request_of("2-1")
        self.assertEqual(request["adoption"]["unit_ids"], self.new_ids)
        self.assertEqual(request["adoption"]["commit"], self.moved)
        self.assertEqual(request["adoption"]["supersedes"]["unit_ids"], self.old_ids)
        self.assertNotIn("gaps", request)
        with open(request["adoption"]["units_file"], encoding="utf-8") as handle:
            self.assertIn("layout", json.load(handle)["units"][0])
        with open(os.path.join(self.run_dir, "design", "seen-2-1.json"),
                  encoding="utf-8") as handle:
            seen = json.load(handle)
        self.assertEqual([u["id"] for u in seen["starting_draft"]["build_spec"]["content"]
                          ["units"]], self.new_ids)
        self.assertNotIn("layout", seen["starting_draft"]["build_spec"]["content"]["units"][0])
        self.assertIn("ADOPTS", seen["rest"][0])
        self.assertIn("Never replace a shipped unit", seen["rest"][0])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        design = result.artifacts[0].content
        self.assertEqual(design["existing_content"]["source"]["commit"], self.moved)
        self.assertEqual(design["existing_content"]["supersedes"]["commit"], self.old_commit)
        self.assertEqual([u["id"] for u in design["build_spec"]["content"]["units"]],
                         self.new_ids)
        self.assertTrue(any("not repaired" in r[1] for r in context.logger.records))

    def test_a_design_that_keeps_the_old_ids_breaches_the_floor(self):
        # The built-in author plans its own units, never the checkout's.
        result, _context = self.visit({})
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertIn("existing_content_floor_kept", result.error)
        design = result.artifacts[0].content
        self.assertEqual(design["existing_content"]["unit_ids"], self.new_ids)
        self.assertEqual(design["existing_content"]["supersedes"]["unit_ids"], self.old_ids)
        breach = next(r for r in design["consistency"]["rule_results"]
                      if r["criterion_id"] == "existing_content_floor_kept")
        self.assertTrue(any("unit ids: the design drops" in m for m in breach["measured"]))


class AReEnteredDesignAdoptsARewriteUnderTheSameIds(AReEnteredDesignAdopts):
    """The 2D case: a person restored other content under the very ids the last design
    plans. The floor moved, the units differ: the visit adopts the shipped units."""

    def shipped_from(self, units):
        out = []
        for n, unit in enumerate(units):
            unit = copy.deepcopy(unit)
            unit["objective"] = f"Survive {n + 40} waves of falling stones without a miss"
            unit["mechanics"] = list(unit.get("mechanics") or [])[:1]
            unit["difficulty"] = {k: (0.95 if v < 0.5 else 0.05)
                                  for k, v in (unit.get("difficulty") or {}).items()}
            out.append(unit)
        return out

    def test_the_agent_starts_from_the_shipped_units_and_repairs_no_gap(self):
        config = self.config("revise", argv=[sys.executable, self.host, "revise", "{request}",
                                             "{draft}", "{prompt}"])
        self.visit(config)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "design",
                                                     "2-1-gaps.request.json")))
        request = self.request_of("2-1")
        self.assertEqual(request["adoption"]["unit_ids"], self.old_ids)
        self.assertEqual(request["adoption"]["commit"], self.moved)
        self.assertEqual(sorted(request["adoption"]["rewritten"]), sorted(self.old_ids))
        # Same ids, other content: the floor moved and records the one it replaces.
        self.assertEqual(request["adoption"]["supersedes"]["commit"], self.old_commit)
        with open(os.path.join(self.run_dir, "design", "seen-2-1.json"),
                  encoding="utf-8") as handle:
            seen = json.load(handle)
        units = seen["starting_draft"]["build_spec"]["content"]["units"]
        self.assertTrue(units[0]["objective"].startswith("Survive 40 waves"))

    def test_a_design_that_keeps_the_old_ids_breaches_the_floor(self):
        # The built-in author plans the run's old units under the shipped ids: the count
        # holds, the content does not - develop refuses it before any developer.
        result, _context = self.visit({})
        design = result.artifacts[0].content
        self.assertEqual(design["existing_content"]["supersedes"]["commit"], self.old_commit)
        reason = develop_floor.replacement(design, existing._Git(self.checkout), "greybox",
                                           run_id=RUN)
        self.assertIn("rewrites the adopted game's content under its own ids", reason)

    def test_without_a_move_a_design_that_changed_its_units_is_not_re_adopted(self):
        step = design_tests.FixedClockStep(design_tests.FakeDefinition())
        context = design_tests.FakeContext({}, run_dir=self.run_dir,
                                           previous_outputs=[self.ref], visit=2)
        floor = {"source": {"commit": self.moved}, "units": len(self.old_ids),
                 "unit_ids": self.old_ids}
        step._floor_moved = False
        self.assertIsNone(step._adoption(context, floor, self.shipped_from([
            {"id": i, "objective": "x", "difficulty": {}} for i in self.old_ids])))
        step._floor_moved = True
        found = step._adoption(context, floor, self.shipped_from(
            json.load(open(os.path.join(self.run_dir, "artifacts", "game-design", "v1.json"),
                           encoding="utf-8"))["build_spec"]["content"]["units"]))
        self.assertEqual(sorted(found["rewritten"]), sorted(self.old_ids))


class TheReplayed2DRunStore(Checkout):
    """The real 2D run: a person restored the accepted r1 levels (HEAD 894b4b8, no run key);
    game-design v1 holds the same 32 ids, every level another one."""

    def setUp(self):
        super().setUp()
        with open(STORE.replace("readopt-3d", "readopt-2d"), encoding="utf-8") as handle:
            self.store = json.load(handle)
        self.units = self.store["shipped_content"]["units"]
        self.shipped = commit_content(self.checkout, self.units, "feat(game): r1 content")

    def design(self, units, floor=None):
        return {"existing_content": floor or self.store["design_v1_floor"],
                "build_spec": {"content": {"units": units}}}

    def test_the_floor_moves_and_v1s_units_are_rewrites(self):
        current, _note, units = self.floor(run_id=self.store["run_id"])
        self.assertEqual(current["source"]["commit"], self.shipped)
        floor = existing.reconcile(self.store["design_v1_floor"], current)
        self.assertTrue(existing.moved(self.store["design_v1_floor"], floor))
        self.assertEqual(floor["unit_ids"], self.store["design_v1_floor"]["unit_ids"])
        rewrite, changed, kept = existing.is_rewrite(units, self.store["design_v1_units"])
        self.assertTrue(rewrite)
        self.assertEqual((len(changed), len(kept)), (32, 32))
        self.assertEqual(existing.unit_changes(units[0], self.store["design_v1_units"][0]),
                         ["objective", "mechanics", "difficulty"])

    def test_develop_refuses_v1(self):
        reason = develop_floor.replacement(self.design(self.store["design_v1_units"]),
                                           existing._Git(self.checkout), "greybox",
                                           run_id=self.store["run_id"])
        self.assertIn("rewrites the adopted game's content under its own ids", reason)
        self.assertIn("32 of the 32", reason)

    def test_an_honest_extension_passes(self):
        extended = existing.adoption_units(self.units)
        for unit in extended:
            unit.update(purpose="test", acceptance=["The clear card shows."],
                        structure="static-field", elements=["standard-brick"])
            unit["mechanics"] = list(unit["mechanics"]) + ["combo"]
            unit["difficulty"] = {k: round(v + 0.05, 3) for k, v in unit["difficulty"].items()}
            unit["objective"] = unit["objective"].replace("Break", "Clear")
        extended.append(dict(copy.deepcopy(extended[-1]), id="w5-l1", index=33))
        self.assertIsNone(develop_floor.replacement(
            self.design(extended), existing._Git(self.checkout), "greybox",
            run_id=self.store["run_id"]))
        self.assertFalse(existing.is_rewrite(self.units, extended)[0])


class TheRunsOwnBuildIsNotTheCheckoutsContent(Checkout):
    def test_greybox_after_a_design_gap_repair_reads_the_shipped_commit(self):
        commit_content(self.checkout, units_named(["a", "b"]), "the shipped game")
        # The run's own greybox build added `c`; the repaired design plans `d` instead.
        path = os.path.join(self.checkout, *CONTENT.split("/"))
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"units": units_named(["a", "b", "c"])}, handle)
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "-q", "-m", f"grey\n\nWgf-Develop-Key: {RUN}:greybox:1")
        floor, _note, _units = self.floor()
        design = {"existing_content": floor,
                  "build_spec": {"content": {"units": units_named(["a", "b", "d"])}}}
        reader = existing._Git(self.checkout)
        self.assertIsNone(develop_floor.replacement(design, reader, "greybox", run_id=RUN))
        # Read at raw HEAD (no run id), the run's own `c` looked shipped and was "dropped".
        self.assertIsNotNone(develop_floor.replacement(design, reader, "greybox"))

    def test_a_history_of_only_the_runs_commits_ships_nothing(self):
        run_commit(self.checkout, "Init", f"wgf-init:{RUN}:init")
        floor, note, _units = self.floor()
        self.assertIsNone(floor)
        self.assertIn("nothing was shipped before it", note)

    def test_a_run_deeper_than_the_listing_never_takes_head(self):
        commit_content(self.checkout, units_named(["a"]), "shipped")
        for n in range(3):
            run_commit(self.checkout, "Develop", f"{RUN}:develop:{n}")
        reader = existing._Git(self.checkout)
        with self.assertRaises(ValueError) as caught:
            existing.shipped_commit(reader, reader.head(), RUN, depth=2)
        self.assertIn("accepted_baseline", str(caught.exception))


class TheProbeFloorIsNeverLost(unittest.TestCase):
    X, Y = "a" * 40, "b" * 40

    def unmeasured(self, commit):
        return {"status": "unmeasured",
                "source": {"method": "probe", "path": CONTENT, "commit": commit}}

    def probed(self, commit):
        return {"status": "measured", "source": {"method": "probe", "path": CONTENT,
                                                  "commit": commit},
                "units": 12, "unit_ids": [f"c{n}" for n in range(12)]}

    def test_two_unmeasured_floors_keep_the_runs(self):
        kept = self.unmeasured(self.X)
        self.assertIs(existing.reconcile(kept, self.unmeasured(self.Y)), kept)

    def test_a_probe_count_is_carried_over_an_unmeasured_floor(self):
        kept = self.probed(self.X)
        self.assertIs(existing.reconcile(kept, self.unmeasured(self.Y)), kept)

    def test_a_measured_content_floor_is_never_lost(self):
        kept = {"source": {"method": "content-data", "path": CONTENT, "commit": self.X},
                "units": 3, "unit_ids": ["a", "b", "c"]}
        self.assertIs(existing.reconcile(kept, self.unmeasured(self.Y)), kept)

    def test_the_design_step_carries_the_runs_probe_floor(self):
        scratch = tempfile.mkdtemp(prefix="wgf-readopt-probe-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        checkouts = os.path.join(scratch, "games")
        checkout = os.path.join(checkouts, "demo")
        os.makedirs(checkout)
        git(checkout, "init", "-q")
        with open(os.path.join(checkout, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("shipped\n")
        git(checkout, "add", "-A")
        git(checkout, "commit", "-q", "-m", "shipped, content in source code")
        first = git(checkout, "rev-parse", "HEAD")
        with open(os.path.join(checkout, "README.md"), "a", encoding="utf-8") as handle:
            handle.write("a person\n")
        git(checkout, "commit", "-q", "-am", "a person moved it, still no content data")
        run_dir = os.path.join(scratch, "run")
        design = {"existing_content": self.unmeasured(first)}
        os.makedirs(os.path.join(run_dir, "artifacts", "game-design"))
        os.makedirs(os.path.join(run_dir, "artifacts", "playability-report"))
        with open(os.path.join(run_dir, "artifacts", "game-design", "v1.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(design, handle)
        with open(os.path.join(run_dir, "artifacts", "playability-report", "v1.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"existing_content": self.probed(first)}, handle)
        ref = agent_tests.ArtifactRef(id="game-design", type="game-design", version=1,
                                      location="artifacts/game-design/v1.json",
                                      checksum="-", content_hash="sha256:" + "0" * 64)
        context = design_tests.FakeContext(
            {"checkouts": checkouts, "init": {"adopt_existing": True}}, run_dir=run_dir,
            previous_outputs=[ref], visit=2)
        context.run_id = RUN
        step = design_tests.FixedClockStep(design_tests.FakeDefinition())
        floor, _units = step._existing_floor(context, "demo")
        self.assertTrue(existing.measured(floor))
        self.assertEqual(floor["units"], 12)
        self.assertEqual(floor["source"]["commit"], first)


class ADevelopVisitOnAReplacement(develop_tests.DevelopCase):
    """Greybox on a design that drops the shipped units while it lists others: BLOCKED with
    no developer started. The brief of a design that keeps them names them to extend."""

    def setUp(self):
        super().setUp()
        content = os.path.join(self.repo, "public", "content")
        os.makedirs(content)
        with open(os.path.join(content, "units.json"), "w", encoding="utf-8",
                  newline="\n") as handle:
            json.dump({"units": units_named(["first-roll", "twin-bends"])}, handle)
        self.git("add", "-A")
        self.git(*develop_tests.IDENTITY, "commit", "-q", "-m", "the accepted courses")
        self.shipped = self.git("rev-parse", "HEAD").strip()

    def design(self, floor_ids, planned):
        design = develop_tests.fixture("game-design")
        floor = dict(existing.measure(units_named(floor_ids)),
                     source={"path": CONTENT, "commit": self.shipped})
        floor.pop("measured_by")
        design["existing_content"] = floor
        design.setdefault("build_spec", {}).setdefault("content", {})["units"] = \
            units_named(planned)
        return design

    def execute(self, design):
        runner = develop_tests.FakeRunner(on_develop=develop_tests.write_game)
        step = develop_tests.step_with(runner)
        step.definition.params = {"phase": "greybox"}
        inputs = develop_tests.inputs_for(
            types=("game-design", "scaffold-record", "title-strategy"),
            overrides={"game-design": design})
        return step.execute(inputs, develop_tests.context(self.command_config())), runner

    def test_a_stale_floor_and_replacement_units_are_blocked(self):
        # The design's own floor is stale (the old ids): HEAD's content data still counts.
        result, runner = self.execute(self.design(["meadow-roll"], ["meadow-roll", "pad-hop"]))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED, result.error)
        self.assertIn("first-roll", result.message)
        self.assertIn("replaces the adopted game's content", result.message)
        self.assertEqual(runner.developer_calls(), [])
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.shipped)

    def test_a_design_that_extends_the_shipped_units_is_briefed_to_extend_them(self):
        design = self.design(["first-roll", "twin-bends"],
                             ["first-roll", "twin-bends", "new-isle"])
        self.assertIsNone(develop_floor.replacement(design, None, "production"))
        brief = develop_briefs.existing_floor(design)
        self.assertIn("EXTEND and improve the shipped units", brief["rule"])
        self.assertIn("`first-roll`", brief["rule"])
        self.assertIn("never replace one", brief["rule"])


if __name__ == "__main__":
    unittest.main()
