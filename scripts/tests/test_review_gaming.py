"""The review's gate-gaming pre-check (scripts/wgf_review/gaming.py,
core/reference/gate-gaming.yaml): a specialist commit that met a gate by changing what the
gate measures instead of the game is flagged, a legitimate change is not, and a flag becomes a
review blocker routed back to the specialist that made it.

Every case is a synthetic commit in a scratch git repository: a develop brief naming the
specialist and its routed findings, and the change. The three real commits the vocabulary was
calibrated on are replayed by `RealCommits` when WGF_GAMING_REPLAY_2D / WGF_GAMING_REPLAY_3D
name the two validation game repositories; otherwise it is skipped and says so.

Standard library only. Run from the repository root:

    python -m unittest scripts/tests/test_review_gaming.py
"""

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

from wgf_review import gaming, report  # noqa: E402
from wgf_review.step import ReviewStep  # noqa: E402
from wgflib import isolation  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402

BRIEF = "docs/development/brief.json"


def finding(check, dimension="content", summary="", producer="playability-report"):
    return {"id": f"{producer}:{check}", "dimension": dimension, "severity": "blocker",
            "source": {"producer": producer, "check": check}, "summary": summary or check,
            "task": {"change": f"Make `{check}` pass", "acceptance": ["the gate passes"]}}


REACH = finding("content.units_reachable@desktop",
                summary="units reached: [1, 2]; the design's first 3 are [1, 2, 3]")
SIMILAR = finding("content.structure", dimension="level-design",
                  producer="content-sufficiency-report",
                  summary="2 of 12 units are near-identical to another")
VISIBLE = finding("assets.runtime", dimension="art-2d", producer="production-quality-report",
                  summary="ball: fails at visible")
PROBE = finding("probe.contract", dimension="gameplay",
                summary="the probe reports no unit")

PARSER = """\
export function parseUnit(raw: Record<string, unknown>) {
  const parameters = raw["parameters"] as Record<string, number>;
  return {
    speed: numberOf(parameters, "speed"),
    gems: numberOf(parameters, "gems"),
  };
}
export function placeLevel(layout: { top?: number }) {
  return layout.top ?? 0;
}
"""
COURSE = """\
export interface Course {
  readonly ramps: readonly number[];
}
export function build(): Course {
  const ramps: number[] = [];
  return { ramps };
}
"""
TUNING = """\
export const BALL = {
  radius: 12,
};
export function rest(ball: { y: number }, paddleY: number) {
  return paddleY - BALL.radius - ball.y;
}
"""
BOARD = """\
/** Drawn sizes. */
const BALL_DRAW = 44;
const SPARK_SIZE = 20;
const TINT = 0x335577;
export function draw() {
  return [BALL_DRAW, SPARK_SIZE, TINT];
}
"""
SIM = """\
export class Sim {
  step(dt: number): void {
    this.t += dt;
  }

  /** The probe showcase only: stage one capsule in the open. */
  stageCapsule(): void {
    this.capsules.push({ x: 100, y: 200 });
  }
}
"""
UNITS = {"units": [
    {"id": "u1", "parameters": {"speed": 1, "gems": 3}, "layout": {"top": 100}},
    {"id": "u2", "parameters": {"speed": 2, "gems": 4}, "layout": {"top": 120}},
]}


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class Repo:
    """A scratch game repository with one base commit."""

    def __init__(self, test):
        self.root = tempfile.mkdtemp(prefix="wgf-gaming-")
        test.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.invalid")
        git(self.root, "config", "user.name", "t")
        git(self.root, "config", "commit.gpgsign", "false")
        self.write({"src/game/content.ts": PARSER, "src/game/course.ts": COURSE,
                    "src/game/tuning.ts": TUNING, "src/rendering/board.ts": BOARD,
                    "src/game/sim.ts": SIM, "public/content/units.json": UNITS,
                    BRIEF: {"iteration": 1}})
        self.base = self.commit("base")

    def write(self, files):
        for path, content in files.items():
            full = os.path.join(self.root, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content if isinstance(content, str)
                             else json.dumps(content, indent=2) + "\n")

    def read(self, path):
        with open(os.path.join(self.root, *path.split("/")), encoding="utf-8") as handle:
            return handle.read()

    def edit(self, path, old, new):
        text = self.read(path)
        assert old in text, (path, old)
        self.write({path: text.replace(old, new)})

    def commit(self, message):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)
        return git(self.root, "rev-parse", "HEAD")

    def visit(self, findings, files=None, edits=(), report=None, role="level-designer",
              specialist=True, iteration=2):
        """One develop visit's commit: its brief (a specialist's, by default), the change."""
        brief = {"iteration": iteration, "baseline_commit": git(self.root, "rev-parse", "HEAD")}
        if specialist:
            brief["specialist"] = {"role": role, "label": role, "findings": findings}
        self.write({BRIEF: brief})
        self.write(files or {})
        for path, old, new in edits:
            self.edit(path, old, new)
        if report is not None:
            self.write({"docs/development/report.json": report})
        return self.commit(f"visit {iteration}")

    def precheck(self, base=None, head=None):
        reader = gaming.GitReader(isolation.Git(self.root))
        return gaming.precheck_range(reader, base or self.base,
                                     head or git(self.root, "rev-parse", "HEAD"))


def units_with(**changes):
    data = json.loads(json.dumps(UNITS))
    for unit in data["units"]:
        for section, values in changes.items():
            unit[section].update(values)
    return data


def flags(result, status="flagged"):
    return sorted((f["pattern"], f["file"]) for v in result["commits"] for f in v["flags"]
                  if f["status"] == status)


class Patterns(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)

    # -- (a) content data fields no game source reads ----------------------------------------

    def test_an_unread_field_added_to_content_data_is_flagged(self):
        # The parser takes `speed` and `gems` by name; `ramps` is added to every unit and
        # `.ramps` exists in game source only on another object (a course's ramps).
        self.repo.visit([SIMILAR], files={
            "public/content/units.json": units_with(parameters={"ramps": 2, "bumpers": 1})})
        result = self.repo.precheck()
        found = [f for f in result["commits"][0]["flags"]
                 if f["pattern"] == "unread-content-field"]
        self.assertEqual(sorted(f["key"] for f in found), ["bumpers", "ramps"])
        self.assertTrue(all(f["line"] for f in found))

    def test_a_field_the_game_reads_is_not_flagged(self):
        # By a quoted key (a parser), and by `<parent>.key` on the object it was added to.
        self.repo.edit("src/game/content.ts", '    gems: numberOf(parameters, "gems"),\n',
                       '    gems: numberOf(parameters, "gems"),\n'
                       '    ramps: numberOf(parameters, "ramps"),\n')
        self.repo.edit("src/game/content.ts", "return layout.top ?? 0;",
                       "return (layout.top ?? 0) + (layout.lift ?? 0);")
        self.repo.visit([SIMILAR], files={
            "public/content/units.json": units_with(parameters={"ramps": 2},
                                                    layout={"lift": 10})})
        self.assertEqual(flags(self.repo.precheck()), [])

    def test_a_field_named_only_in_a_comment_or_a_test_is_unread(self):
        self.repo.edit("src/game/content.ts", "export function placeLevel",
                       '// "ramps" will be read here later\nexport function placeLevel')
        self.repo.write({"tests/unit/ramps.test.ts": 'expect(unit.parameters["ramps"]);\n'})
        self.repo.visit([SIMILAR], files={
            "public/content/units.json": units_with(parameters={"ramps": 2})})
        self.assertEqual(flags(self.repo.precheck()),
                         [("unread-content-field", "public/content/units.json")])

    # -- (b) play area, bounds, colliders in a reach/time/visibility visit -------------------

    def test_a_lowered_ceiling_in_a_reachability_visit_is_flagged(self):
        self.repo.edit("src/game/content.ts", "return layout.top ?? 0;",
                       "return layout.top ?? 0;\n}\nexport function ceiling(layout: "
                       "{ ceiling_y?: number }) {\n  return layout.ceiling_y ?? 0;")
        self.repo.commit("the ceiling is data")
        base = git(self.repo.root, "rev-parse", "HEAD")
        self.repo.visit([REACH], files={
            "public/content/units.json": units_with(layout={"ceiling_y": 640})})
        result = self.repo.precheck(base=base)
        self.assertEqual(flags(result), [("play-area-change", "public/content/units.json")])
        self.assertIn("ceiling_y", result["commits"][0]["flags"][0]["detail"])

    def test_a_bounds_change_in_source_in_a_visibility_visit_is_flagged(self):
        self.repo.edit("src/game/sim.ts", "this.t += dt;",
                       "this.t += dt;\n    this.bounds = { w: 600, h: 900 };")
        self.repo.visit([VISIBLE], role="artist-2d", files={})
        self.assertIn(("play-area-change", "src/game/sim.ts"), flags(self.repo.precheck()))

    def test_the_same_change_in_a_visit_not_routed_for_reach_time_or_visibility_is_not(self):
        self.repo.edit("src/game/content.ts", "return layout.top ?? 0;",
                       "return layout.top ?? 0;\n}\nexport function ceiling(layout: "
                       "{ ceiling_y?: number }) {\n  return layout.ceiling_y ?? 0;")
        self.repo.visit([SIMILAR], files={
            "public/content/units.json": units_with(layout={"ceiling_y": 640})})
        result = self.repo.precheck()
        self.assertEqual(flags(result), [])
        self.assertIn("play-area-change", result["commits"][0]["skipped"])

    def test_a_reachability_fix_in_the_rules_is_player_facing(self):
        # Faster pacing: the time follows from what the player does.
        self.repo.visit([REACH], files={
            "public/content/units.json": units_with(parameters={"speed": 3})})
        result = self.repo.precheck()
        self.assertEqual(flags(result), [])
        classes = {(h["file"], h["class"]) for h in result["commits"][0]["hunks"]}
        self.assertIn(("public/content/units.json", "player-facing"), classes)
        self.assertIn((BRIEF, "bookkeeping"), classes)

    # -- (c) probe-, showcase- or bot-only code for gameplay findings ------------------------

    def test_a_probe_only_path_changed_for_a_gameplay_finding_is_flagged(self):
        self.repo.visit([VISIBLE], role="artist-2d", edits=[
            ("src/game/sim.ts", "this.capsules.push({ x: 100, y: 200 });",
             "this.capsules.push({ x: 100, y: 80, hover: true });")])
        result = self.repo.precheck()
        self.assertEqual(flags(result), [("probe-path-change", "src/game/sim.ts")])
        hunks = [h for h in result["commits"][0]["hunks"] if h["file"] == "src/game/sim.ts"]
        self.assertEqual({h["class"] for h in hunks}, {"measurement-facing"})

    def test_probe_code_changed_for_a_probe_finding_is_not(self):
        self.repo.visit([PROBE], role="gameplay", edits=[
            ("src/game/sim.ts", "this.capsules.push({ x: 100, y: 200 });",
             "this.capsules.push({ x: 120, y: 200 });")])
        result = self.repo.precheck()
        self.assertEqual(flags(result), [])
        self.assertIn("probe-path-change", result["commits"][0]["skipped"])

    def test_gameplay_code_beside_no_probe_is_not(self):
        self.repo.visit([REACH], edits=[("src/game/sim.ts", "this.t += dt;",
                                         "this.t += dt * 1.25;")])
        self.assertEqual(flags(self.repo.precheck()), [])

    # -- (d) a drawn size without the physical size ----------------------------------------

    def test_a_sprite_drawn_larger_with_its_collider_unchanged_is_flagged(self):
        self.repo.visit([VISIBLE], role="artist-2d", edits=[
            ("src/rendering/board.ts", "const BALL_DRAW = 44;", "const BALL_DRAW = 60;")])
        result = self.repo.precheck()
        self.assertEqual(flags(result),
                         [("sprite-size-without-collider", "src/rendering/board.ts")])
        self.assertIn("ball", result["commits"][0]["flags"][0]["detail"])

    def test_a_sprite_and_its_collider_changed_together_is_not(self):
        self.repo.visit([VISIBLE], role="artist-2d", edits=[
            ("src/rendering/board.ts", "const BALL_DRAW = 44;", "const BALL_DRAW = 60;"),
            ("src/game/tuning.ts", "export const BALL = {\n  radius: 12,",
             "export const BALL = {\n  radius: 16,")])
        self.assertEqual(flags(self.repo.precheck()), [])

    def test_an_effect_with_no_body_and_a_colour_are_not(self):
        self.repo.visit([VISIBLE], role="artist-2d", edits=[
            ("src/rendering/board.ts", "const SPARK_SIZE = 20;", "const SPARK_SIZE = 32;"),
            ("src/rendering/board.ts", "const TINT = 0x335577;", "const TINT = 0x446688;")])
        self.assertEqual(flags(self.repo.precheck()), [])

    # -- which commits are read ------------------------------------------------------------

    def test_a_commit_that_is_no_specialists_is_not_read(self):
        self.repo.visit([], specialist=False, files={
            "public/content/units.json": units_with(parameters={"ramps": 2})})
        self.assertEqual(self.repo.precheck()["commits"], [])

    def test_every_specialist_commit_of_a_chain_is_read(self):
        self.repo.visit([SIMILAR], files={
            "public/content/units.json": units_with(parameters={"ramps": 2})}, iteration=2)
        self.repo.visit([VISIBLE], role="artist-2d", iteration=3, edits=[
            ("src/rendering/board.ts", "const BALL_DRAW = 44;", "const BALL_DRAW = 60;")])
        result = self.repo.precheck()
        self.assertEqual([v["owner"] for v in result["commits"]],
                         ["level-designer", "artist-2d"])
        made = gaming.blockers(result)
        self.assertEqual([(b["id"], b["dimension"]) for b in made],
                         [("gate-gaming-unread-content-field-1", "level-design"),
                          ("gate-gaming-sprite-size-without-collider-1", "art-2d")])


class Declarations(unittest.TestCase):
    """The documented false-positive path: report.json `measurement_changes` with evidence."""

    def setUp(self):
        self.repo = Repo(self)

    def declare(self, entry):
        return {"known_issues": [], "measurement_changes": [entry]}

    def test_evidence_of_a_read_clears_an_unread_field(self):
        # Read through an alias the pre-check cannot see: the evidence line shows it.
        self.repo.edit("src/game/content.ts", "export function placeLevel",
                       "export function extras(p: Record<string, number>) {\n"
                       "  const q = p;\n  return q.ramps;\n}\nexport function placeLevel")
        line = self.repo.read("src/game/content.ts").splitlines().index(
            "  return q.ramps;") + 1
        self.repo.visit([SIMILAR], files={
            "public/content/units.json": units_with(parameters={"ramps": 2})},
            report=self.declare({"flag": "unread-content-field",
                                 "where": "public/content/units.json#ramps",
                                 "evidence": [{"file": "src/game/content.ts", "line": line}],
                                 "player_effect": "each ramp is built from it"}))
        result = self.repo.precheck()
        self.assertEqual(flags(result), [])
        self.assertEqual(flags(result, "cleared"),
                         [("unread-content-field", "public/content/units.json")])
        self.assertEqual(gaming.blockers(result), [])

    def test_evidence_that_does_not_read_the_field_clears_nothing(self):
        self.repo.visit([SIMILAR], files={
            "public/content/units.json": units_with(parameters={"ramps": 2})},
            report=self.declare({"flag": "unread-content-field", "where": "",
                                 "evidence": [{"file": "src/game/content.ts", "line": 2}],
                                 "player_effect": "trust me"}))
        self.assertEqual(flags(self.repo.precheck()),
                         [("unread-content-field", "public/content/units.json")])

    def test_a_declared_change_with_evidence_goes_to_the_reviewer_not_a_blocker(self):
        self.repo.visit([VISIBLE], role="artist-2d", edits=[
            ("src/rendering/board.ts", "const BALL_DRAW = 44;", "const BALL_DRAW = 60;")],
            report=self.declare({"flag": "sprite-size-without-collider",
                                 "where": "src/rendering/board.ts",
                                 "evidence": [{"file": "src/rendering/board.ts", "line": 2}],
                                 "player_effect": "the halo is drawn outside the ball"}))
        result = self.repo.precheck()
        self.assertEqual(flags(result), [])
        self.assertEqual(flags(result, "declared"),
                         [("sprite-size-without-collider", "src/rendering/board.ts")])
        self.assertEqual(gaming.blockers(result), [])
        brief = "\n".join(report._gaming_lines(result))
        self.assertIn("the halo is drawn outside the ball", brief)
        self.assertIn("src/rendering/board.ts:2", brief)

    def test_a_declaration_without_evidence_or_effect_changes_nothing(self):
        for entry in ({"flag": "sprite-size-without-collider", "where": "",
                       "evidence": [], "player_effect": "bigger"},
                      {"flag": "sprite-size-without-collider", "where": "",
                       "evidence": [{"file": "src/rendering/board.ts", "line": 999}],
                       "player_effect": "bigger"},
                      {"flag": "sprite-size-without-collider", "where": "",
                       "evidence": [{"file": "src/rendering/board.ts", "line": 2}],
                       "player_effect": " "}):
            with self.subTest(entry=entry):
                repo = Repo(self)
                repo.visit([VISIBLE], role="artist-2d", edits=[
                    ("src/rendering/board.ts", "const BALL_DRAW = 44;",
                     "const BALL_DRAW = 60;")], report=self.declare(entry))
                self.assertEqual(flags(repo.precheck()),
                                 [("sprite-size-without-collider", "src/rendering/board.ts")])


class ReviewOutcome(unittest.TestCase):
    """A flag makes the review request changes, routed back to the visit's owner."""

    PRECHECK = {"vocabulary": "gate-gaming@1.0.0", "commits": [{
        "commit": "c" * 40, "owner": "level-designer", "dimension": "level-design",
        "findings": [SIMILAR["id"]], "hunks": [], "skipped": {},
        "flags": [{"pattern": "unread-content-field", "file": "public/content/units.json",
                   "key": "ramps", "line": 4, "where": "public/content/units.json#ramps",
                   "detail": "`ramps` is read nowhere", "status": "flagged"}]}]}

    def test_an_approval_with_a_flag_becomes_a_request_for_changes(self):
        verdict, notes = ReviewStep._with_precheck(
            {"verdict": "approve", "commit": "c" * 40, "blockers": []}, self.PRECHECK)
        self.assertEqual(verdict["verdict"], "request-changes")
        self.assertEqual([b["id"] for b in verdict["blockers"]],
                         ["gate-gaming-unread-content-field-1"])
        self.assertEqual(verdict["blockers"][0]["dimension"], "level-design")
        self.assertIn("pre-check flagged 1", notes)

    def test_reviewer_blockers_are_kept_and_its_gaming_ones_routed_to_the_owner(self):
        verdict, _ = ReviewStep._with_precheck(
            {"verdict": "request-changes", "commit": "c" * 40, "blockers": [
                {"id": "gate-gaming-alias", "file": None, "summary": "s", "severity": "major"},
                {"id": "restart", "file": None, "summary": "s", "severity": "blocker"}]},
            self.PRECHECK)
        by_id = {b["id"]: b for b in verdict["blockers"]}
        self.assertEqual(by_id["gate-gaming-alias"]["dimension"], "level-design")
        self.assertNotIn("dimension", by_id["restart"])
        self.assertIn("gate-gaming-unread-content-field-1", by_id)

    def test_no_specialist_commit_changes_nothing(self):
        given = {"verdict": "approve", "commit": "c" * 40, "blockers": [], "notes": "ok"}
        self.assertEqual(ReviewStep._with_precheck(given, None), (given, "ok"))
        self.assertEqual(ReviewStep._with_precheck(
            given, {"vocabulary": "v", "commits": []})[0]["verdict"], "approve")

    def test_the_report_with_gaming_blockers_is_schema_valid(self):
        verdict, notes = ReviewStep._with_precheck(
            {"verdict": "approve", "commit": "c" * 40, "blockers": []}, self.PRECHECK)
        artifact = report.build_report(
            title_id="demo-game", commit="c" * 40, baseline="b" * 40,
            verdict=verdict["verdict"], blockers=verdict["blockers"], notes=notes,
            failure=None, reviewer={"kind": "command", "argv0": "r", "exit_code": 0,
                                    "status": "exited", "killed_pids": []},
            isolation={"checked_paths": 1, "violations": [], "intact": True,
                       "restored": None},
            iteration=1, attempt=1, duration_s=1.0, timed_out=False, pinned_inputs=[],
            artifact_seq=1, produced_at="2026-10-05T10:00:00Z",
            gate_gaming=ReviewStep._gaming_summary(self.PRECHECK))
        self.assertEqual(ArtifactContracts()("review-report", artifact), [])
        self.assertEqual(artifact["gate_gaming"]["flagged"], 1)

    def test_triage_routes_the_blocker_to_the_visits_owner(self):
        from wgf_triage.findings import normalize
        from wgf_triage.routing import Routing
        verdict, _ = ReviewStep._with_precheck(
            {"verdict": "approve", "commit": "c" * 40, "blockers": []}, self.PRECHECK)
        found = normalize("review-report", {"verdict": "request-changes",
                                            "blockers": verdict["blockers"]}, Routing.load())
        self.assertEqual([(f["owner"], f["route"]) for f in found],
                         [("level-designer", "develop")])
        plain = normalize("review-report", {"blockers": [
            {"id": "b", "file": None, "summary": "s", "severity": "blocker"}]},
            Routing.load())
        self.assertEqual(plain[0]["owner"], "gameplay")

    def test_the_reviewer_brief_shows_the_classification_and_the_flags(self):
        precheck = json.loads(json.dumps(self.PRECHECK))
        precheck["commits"][0]["hunks"] = [
            {"file": "public/content/units.json", "hunk": 3, "class": "measurement-facing",
             "reasons": ["unread-content-field"]},
            {"file": "docs/development/brief.json", "hunk": 1, "class": "bookkeeping",
             "reasons": []}]
        text = report.render_brief(
            title_id="demo-game", commit="c" * 40, baseline="b" * 40, design=None,
            prototype=None, develop_brief=None, verdict_path="/tmp/v.json", repo="/g",
            gaming=precheck)
        section = text.split("## Gate gaming")[1].split("## Look for")[0]
        self.assertIn("measurement-facing", section)
        self.assertNotIn("docs/development/brief.json", section)
        self.assertIn("`ramps` is read nowhere", section)
        self.assertIn("`gate-gaming-`", section)
        self.assertNotIn("## Gate gaming", report.render_brief(
            title_id="demo-game", commit="c" * 40, baseline="b" * 40, design=None,
            prototype=None, develop_brief=None, verdict_path="/tmp/v.json", repo="/g"))


REVIEWER = """\
import json, sys
json.dump({"verdict": "approve", "commit": sys.argv[2], "blockers": []},
          open(sys.argv[1], "w"))
"""


class Step(unittest.TestCase):
    """The review step end to end: a specialist commit, a reviewer that approves it."""

    def run_review(self, repo, baseline):
        from test_verification import FakeContext, FakeInputs
        from wgflib.workflow.definition import StepDefinition
        # The visit's brief names its baseline: the change reviewed is baseline..HEAD.
        self.assertEqual(json.loads(repo.read(BRIEF))["baseline_commit"], baseline)
        head = git(repo.root, "rev-parse", "HEAD")
        script = os.path.join(repo.root, "..", os.path.basename(repo.root) + "-reviewer.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(REVIEWER)
        self.addCleanup(os.remove, script)
        step = ReviewStep(StepDefinition({
            "id": "review", "type": "review", "inputs": [], "outputs": ["review-report"],
            "with": {"repo_dir": repo.root}}, retry=None, max_visits=None))
        context = FakeContext(config={"review": {"reviewer": {
            "kind": "command", "argv": [sys.executable, script, "{verdict}", "{commit}"],
            "timeout_seconds": 60}}})
        context.current_step = "review"
        context.run_dir = tempfile.mkdtemp(prefix="wgf-gaming-run-")
        self.addCleanup(shutil.rmtree, context.run_dir, ignore_errors=True)
        inputs = FakeInputs({
            "prototype-report": {"title_id": "demo", "build_ref": {"commit_sha": head}},
            "scaffold-record": {"title_id": "demo", "repository": {"name": "demo"}}})
        return step.execute(inputs, context), context

    def test_an_approved_gamed_commit_is_sent_back_to_its_specialist(self):
        repo = Repo(self)
        repo.visit([SIMILAR], files={
            "public/content/units.json": units_with(parameters={"ramps": 2})})
        result, context = self.run_review(repo, repo.base)
        self.assertEqual((result.outcome, result.route), ("FAILED", "request-changes"),
                         result.error)
        content = result.artifacts[0].content
        self.assertEqual(content["verdict"], "request-changes")
        self.assertEqual([(b["id"], b.get("dimension")) for b in content["blockers"]],
                         [("gate-gaming-unread-content-field-1", "level-design")])
        self.assertEqual(content["gate_gaming"]["flagged"], 1)
        self.assertEqual(ArtifactContracts()("review-report", content), [])
        with open(os.path.join(context.run_dir, "review", "review-1-1.brief.md"),
                  encoding="utf-8") as handle:
            brief = handle.read()
        self.assertIn("## Gate gaming", brief)
        self.assertTrue(os.path.isfile(os.path.join(context.run_dir, "review",
                                                    "review-1-1.gaming.json")))

    def test_a_clean_specialist_commit_is_approved(self):
        repo = Repo(self)
        repo.visit([REACH], files={
            "public/content/units.json": units_with(parameters={"speed": 3})})
        result, _ = self.run_review(repo, repo.base)
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        self.assertEqual(result.artifacts[0].content["gate_gaming"]["flagged"], 0)


class DevelopBrief(unittest.TestCase):
    """The specialist's brief states the rules, tied to each routed finding."""

    def render(self, findings):
        from wgf_develop import specialist
        spec = {"role": "level-designer", "label": "Level designer", "focus": "Levels.",
                "playbooks": [], "writable_paths": ["public/content/"], "findings": findings,
                "context": {}}
        return "\n".join(specialist.render(spec))

    def test_each_finding_carries_the_rules_of_its_kind(self):
        text = self.render([REACH, VISIBLE, SIMILAR])
        owned = text.split("### Your findings")[1].split("### Change the game")[0]
        reach = owned.split(REACH["id"])[1].split(VISIBLE["id"])[0]
        self.assertIn("Never shrink the play space", reach)
        visible = owned.split(VISIBLE["id"])[1].split(SIMILAR["id"])[0]
        self.assertIn("keep visual and physical size consistent", visible)
        similar = owned.split(SIMILAR["id"])[1]
        self.assertIn("Never change only descriptive data", similar)
        self.assertNotIn("Never shrink the play space", similar)

    def test_every_specialist_brief_states_the_general_rules_and_the_declaration(self):
        text = self.render([SIMILAR])
        section = text.split("### Change the game, not its measurement")[1]
        for needle in ("Fix the player-facing cause", "hide, undraw or remove a collider",
                       "special-case the bot", "`measurement_changes`", "player_effect"):
            self.assertIn(needle, section)

    def test_the_report_contract_names_the_declaration(self):
        from wgf_develop import brief
        entry = brief.REPORT_CONTRACT["measurement_changes"][0]
        self.assertEqual(sorted(entry), ["evidence", "flag", "player_effect", "where"])
        for pattern in gaming.PATTERNS:
            self.assertIn(pattern, entry["flag"])


class Vocabulary(unittest.TestCase):
    def test_the_shipped_vocabulary_loads_and_names_every_pattern(self):
        vocab = gaming.Vocabulary.load()
        self.assertEqual(sorted(vocab.patterns), sorted(gaming.PATTERNS))
        self.assertTrue(vocab.rules)
        for cid, spec in vocab.categories.items():
            self.assertTrue(spec.get("words") and spec.get("rules"), cid)
        for spec in vocab.patterns.values():
            self.assertLessEqual(set(spec.get("watch") or []), set(vocab.categories))

    def test_identifier_words(self):
        self.assertEqual(gaming.words("BALL_DRAW gridTop wgf-probe ceiling_y HUDLayer"),
                         ["ball", "draw", "grid", "top", "wgf", "probe", "ceiling", "y",
                          "hud", "layer"])


# Calibration (docs/review-module.md): the three real specialist commits, each a gate passed
# by changing its input. Point the variables at the two validation game repositories.
REPLAY_2D = os.environ.get("WGF_GAMING_REPLAY_2D")
REPLAY_3D = os.environ.get("WGF_GAMING_REPLAY_3D")


class RealCommits(unittest.TestCase):
    def replay(self, repo, sha):
        g = isolation.Git(repo)
        full = g.run("rev-parse", sha).strip()
        reader = gaming.GitReader(g)
        return gaming.precheck_range(reader, reader.parent(full), full)

    @unittest.skipUnless(REPLAY_2D, "WGF_GAMING_REPLAY_2D names no 2D validation repository")
    def test_2d_lowered_ceiling_for_reachability(self):
        self.assertIn(("play-area-change", "public/content/units.json"),
                      flags(self.replay(REPLAY_2D, "cbac64e")))

    @unittest.skipUnless(REPLAY_2D, "WGF_GAMING_REPLAY_2D names no 2D validation repository")
    def test_2d_sprites_drawn_larger_than_their_colliders(self):
        found = flags(self.replay(REPLAY_2D, "68a12b7"))
        self.assertIn(("sprite-size-without-collider", "src/rendering/pixijs/board.ts"), found)

    @unittest.skipUnless(REPLAY_3D, "WGF_GAMING_REPLAY_3D names no 3D validation repository")
    def test_3d_unparsed_fields_for_similarity(self):
        result = self.replay(REPLAY_3D, "1c6b099")
        self.assertEqual(sorted(f["key"] for v in result["commits"] for f in v["flags"]
                                if f["pattern"] == "unread-content-field"),
                         ["bumpers", "gaps", "lifts", "ramps"])


if __name__ == "__main__":
    unittest.main()
