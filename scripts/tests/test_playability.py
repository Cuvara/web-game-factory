"""The playability step's judgement (scripts/wgf_playability): what a bot saw, held to the bars.

The bot (bot.spec.ts) records; analysis.judge decides. These tests feed it records and frames
made here - a well-behaved game, and one with each defect a real run's game had: no
objective on screen, a loss with no input 2.7 s into play, a dive that changed nothing on
screen, an attacker too small to read, a ball never seen in flight, a near-black frame. The
real run's game (Goalkeeper Royale 810925b, with a probe added) failed each of these when
the step played it.

The step's own orchestration (clone, install, build, play) is exercised against a real game
outside this suite; here, its refusals and the report it writes.

    python -m unittest scripts.tests.test_playability
"""

import copy
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_design.experience import load_rules as experience_rules  # noqa: E402
from wgf_playability import analysis  # noqa: E402
from wgf_playability.step import PlayabilityStep, load_rules  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import StepOutcome  # noqa: E402

W, H = 320, 180

DESIGN = {"build_spec": {"experience": {
    "goal": {"statement": "Save eight shots before your lives run out.", "metric": "saves",
             "shown_on": "play"},
    "win": {"condition": "Eight saves.", "metric": "saves"},
    "lose": {"condition": "No lives left.", "metric": "lives"},
    "actions": [{"action": "dive", "visual": "The keeper dives.", "max_ack_ms": 100}],
    "onboarding": {"teaches": ["dive"], "grace": {"until": "first-success"}, "reveals_answer": False},
    "first_30s": {"first_frame_s": 2, "playable_s": 5, "first_success_s": 10, "retry_s": 1},
}}}


def frame(path, luminance, spot=None):
    """A flat grey frame, with an optional bright square: (x, y, size)."""
    image = Image(W, H, bytes([luminance, luminance, luminance, 255]) * (W * H))
    if spot:
        x0, y0, size = spot
        for y in range(y0, y0 + size):
            for x in range(x0, x0 + size):
                i = (y * W + x) * 4
                image.pixels[i:i + 3] = bytes([250, 250, 250])
    with open(path, "wb") as handle:
        handle.write(encode_png(image))


def snapshot(state="playing", saves=0, lives=3):
    return {"state": state, "metrics": {"saves": saves, "lives": lives},
            "entities": [{"id": "keeper", "role": "player", "x": 100, "y": 100, "w": 40, "h": 50,
                          "visible": True}],
            "inputs": [{"action": "dive", "input": {"type": "pointer", "x": 50, "y": 90}}]}


def entity_frames(ball_moves=True, attacker_size=30):
    frames = []
    for i in range(30):
        ball_x = 150 + (i * 4 if ball_moves else 0)
        frames.append([["keeper", "player", 1, 100, 100, 40, 50],
                       ["attacker", "threat", 1, 150, 40, attacker_size, attacker_size],
                       ["ball", "projectile", 1, ball_x, 60, 8, 8]])
    return {"frames": frames, "viewport": [W, H]}


class Judge(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-play-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.frames = os.path.join(self.base, "frames")
        os.makedirs(self.frames)
        frame(os.path.join(self.frames, "first-session-1s.png"), 110, (20, 20, 40))
        frame(os.path.join(self.frames, "play-2s.png"), 120, (60, 60, 40))
        frame(os.path.join(self.frames, "act-dive-before.png"), 110)
        frame(os.path.join(self.frames, "act-dive-after.png"), 110, (100, 100, 30))
        self.records = {
            "first-session": {"firstSnapshotMs": 100, "playingMs": 900,
                              "samples": [snapshot("loading"), snapshot()],
                              "texts": ["Save eight shots before your lives run out"],
                              "lostAtMs": None, "errors": [], "frames": ["first-session-1s"]},
            "act": {"acted": [{"action": "dive", "before": snapshot(), "after": snapshot()}]},
            "win": {"reached": "won", "inputs": 8, "series": [], "sampled": entity_frames()},
            "lose": {"reached": "lost", "initial": {"saves": 0, "lives": 3},
                     "restart": {"clicked": "button", "playingMs": 300,
                                 "metrics": {"saves": 0, "lives": 3}}},
        }
        self.rules = load_rules()
        self.rules["_idle_ms"] = 10000

    def judge(self, design=DESIGN):
        checks = analysis.judge(self.records, self.frames, design, self.rules, experience_rules(),
                                "desktop")
        return {c["id"]: c for c in checks}

    def failed(self):
        return sorted(cid for cid, c in self.judge().items() if c["status"] == "FAIL")

    def test_a_well_behaved_game_passes_every_check(self):
        checks = self.judge()
        self.assertEqual(self.failed(), [], {k: v["summary"] for k, v in checks.items()})
        for cid in ("probe.present", "probe.valid", "start.playable", "start.objective",
                    "idle.grace", "act.acknowledged", "win.reachable", "lose.reachable",
                    "restart.works", "entities.visible", "entities.projectile",
                    "frames.readable", "page.errors"):
            self.assertIn(cid, checks)

    def test_no_probe_is_a_failure_and_nothing_else_is_judged(self):
        self.records["first-session"]["samples"] = []
        checks = self.judge()
        self.assertEqual(list(checks), ["probe.present"])
        self.assertEqual(checks["probe.present"]["status"], "FAIL")

    def test_a_probe_missing_the_contracts_metric(self):
        for s in self.records["first-session"]["samples"]:
            del s["metrics"]["lives"]
        self.assertIn("probe.valid", self.failed())

    def test_the_objective_not_on_screen(self):
        self.records["first-session"]["texts"] = ["0", "Tap the glowing zone to dive"]
        self.assertIn("start.objective", self.failed())

    def test_a_loss_with_no_input_inside_the_grace(self):
        self.records["first-session"]["lostAtMs"] = 2727
        checks = self.judge()
        self.assertEqual(checks["idle.grace"]["status"], "FAIL")
        self.assertIn("2727 ms", checks["idle.grace"]["summary"])

    def test_an_action_that_changes_nothing_on_screen(self):
        frame(os.path.join(self.frames, "act-dive-after.png"), 110)
        self.assertIn("act.acknowledged", self.failed())

    def test_no_win_under_good_play(self):
        self.records["win"]["reached"] = None
        self.assertIn("win.reachable", self.failed())

    def test_an_endless_game_needs_its_objective_to_rise(self):
        design = copy.deepcopy(DESIGN)
        del design["build_spec"]["experience"]["win"]
        self.records["win"]["series"] = [{"ms": 0, "value": 0, "state": "playing"},
                                         {"ms": 900, "value": 0, "state": "playing"}]
        checks = self.judge(design)
        self.assertEqual(checks["win.reachable"]["status"], "FAIL")
        self.records["win"]["series"][-1]["value"] = 5
        self.assertEqual(self.judge(design)["win.reachable"]["status"], "PASS")

    def test_a_retry_that_does_not_reset(self):
        self.records["lose"]["restart"]["metrics"]["saves"] = 5
        self.assertIn("restart.works", self.failed())

    def test_a_threat_too_small_to_read(self):
        self.records["win"]["sampled"] = entity_frames(attacker_size=3)
        checks = self.judge()
        self.assertEqual(checks["entities.visible"]["status"], "FAIL")
        self.assertIn("threat", checks["entities.visible"]["summary"])

    def test_a_ball_never_seen_in_flight(self):
        """The real game drew the ball at the attacker and snapped it back before it moved."""
        self.records["win"]["sampled"] = entity_frames(ball_moves=False)
        checks = self.judge()
        self.assertEqual(checks["entities.projectile"]["status"], "FAIL")
        self.assertIn("0 consecutive frames", checks["entities.projectile"]["summary"])

    def test_a_frame_with_almost_nothing_lit(self):
        """Goalkeeper Royale 810925b: 0.2 % of the frame lit, an unlit scene."""
        frame(os.path.join(self.frames, "play-2s.png"), 8, (60, 60, 10))
        checks = self.judge()
        self.assertEqual(checks["frames.readable"]["status"], "FAIL")
        self.assertIn("% of pixels lit", checks["frames.readable"]["summary"])

    def test_a_dark_theme_with_bright_pieces_is_readable(self):
        """Tower Merge Rush: dark navy, bright tiles - a mean luminance near 25, and fine."""
        frame(os.path.join(self.frames, "play-2s.png"), 14, (40, 40, 50))
        frame(os.path.join(self.frames, "first-session-1s.png"), 14, (40, 40, 50))
        checks = self.judge()
        self.assertEqual(checks["frames.readable"]["status"], "PASS", checks["frames.readable"])
        self.assertLess(checks["frames.readable"]["measured"]["play-2s"]["mean_luminance"], 40)

    def test_a_washed_out_frame(self):
        frame(os.path.join(self.frames, "play-2s.png"), 240, (60, 60, 40))
        self.assertIn("mean luminance", self.judge()["frames.readable"]["summary"])

    def test_entity_samples_with_asset_and_render_are_judged_the_same(self):
        # The bot appends each entity's asset and render for the production gate.
        before = self.judge()["entities.visible"]
        self.records["win"]["sampled"]["frames"] = [
            [sample + ["keeper-sprite", "asset"] for sample in frame]
            for frame in self.records["win"]["sampled"]["frames"]]
        self.assertEqual(self.judge()["entities.visible"], before)

    def test_a_wall_is_judged_at_its_closest(self):
        """A threat that spawns as a speck on the horizon and rushes at the player is read
        up close; one that is always a speck is not."""
        frames = []
        for i in range(30):
            size = 2 + i * 3  # 2 px far away, 89 px up close
            frames.append([["keeper", "player", 1, 100, 100, 40, 50],
                           ["wall", "threat", 1, 150, 40, size, size]])
        self.records["win"]["sampled"] = {"frames": frames, "viewport": [W, H]}
        self.assertEqual(self.judge()["entities.visible"]["status"], "PASS")

    def test_a_wall_still_on_the_horizon_when_sampling_ends_is_not_judged(self):
        """Neon Drift Arena: the run ended with walls far away that never had their
        close-up; the walls that reached the player and left are the ones judged."""
        frames = []
        for i in range(30):
            entities = [["craft", "player", 1, 100, 100, 40, 50]]
            if i < 20:  # passed the player and despawned
                entities.append(["near", "threat", 1, 150, 40, 2 + i * 4, 2 + i * 4])
            entities += [[f"far-{n}", "threat", 1, 150 + n * 5, 40, 3, 3] for n in range(3)]
            frames.append(entities)
        self.records["win"]["sampled"] = {"frames": frames, "viewport": [W, H]}
        self.assertEqual(self.judge()["entities.visible"]["status"], "PASS")

    def test_page_errors(self):
        self.records["act"]["errors"] = ["TypeError: x is undefined"]
        self.assertIn("page.errors", self.failed())

    def test_measured_numbers_never_need_exponent_notation(self):
        """The artifact is hashed canonically, and a number like 5e-05 is refused there."""
        frame(os.path.join(self.frames, "act-dive-after.png"), 110, (0, 0, 1))
        fraction = self.judge()["act.acknowledged"]["measured"]["dive"]
        self.assertNotIn("e", repr(fraction))


class TheStep(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-play-step-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def run_step(self, docs, step="playability"):
        class Inputs:
            refs = {k: types.SimpleNamespace(content_hash=None) for k in docs}

            def __contains__(self, k):
                return k in docs

            def load(self, k):
                return docs[k]

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        context = types.SimpleNamespace(config={"checkouts": self.base}, run_dir=self.base,
                                        logger=Log(), visit=1, attempt=1, execution=1,
                                        current_step=step)
        return PlayabilityStep(types.SimpleNamespace(params={}, id=step)).execute(
            Inputs(), context)

    def test_each_step_plays_in_its_own_scratch_directory(self):
        # greybox-playability and playability both start at visit 1; the scratch directory
        # is emptied first, so a shared one erased the frames the greybox's report cites.
        os.makedirs(os.path.join(self.base, "demo"))
        subprocess.run(["git", "init", "-q", os.path.join(self.base, "demo")], check=True)
        keep = os.path.join(self.base, "greybox-playability", "1-1", "kept.txt")
        docs = {"game-design": DESIGN,
                "scaffold-record": {"title_id": "demo", "repository": {"name": "demo"}},
                "prototype-report": {"build_ref": {"commit_sha": "a" * 40}}}
        self.run_step(docs, step="greybox-playability")
        self.assertTrue(os.path.isdir(os.path.dirname(keep)))
        with open(keep, "w") as handle:
            handle.write("the greybox's evidence")
        self.run_step(docs, step="playability")
        self.assertTrue(os.path.isdir(os.path.join(self.base, "playability", "1-1")))
        self.assertTrue(os.path.exists(keep))

    def test_nothing_to_play_waits_for_input(self):
        self.assertEqual(self.run_step({}).outcome, StepOutcome.WAITING_FOR_INPUT)

    def test_a_design_without_an_experience_contract_is_blocked(self):
        result = self.run_step({"game-design": {"build_spec": {}}, "scaffold-record": {},
                                "prototype-report": {}})
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("experience contract", result.message)

    def test_no_checkout_is_blocked_with_a_valid_report(self):
        result = self.run_step({"game-design": DESIGN,
                                "scaffold-record": {"title_id": "demo", "repository": {"name": "demo"}},
                                "prototype-report": {"build_ref": {"commit_sha": "a" * 40}}})
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)


class TheReport(unittest.TestCase):
    def test_a_report_validates_against_its_schema(self):
        from wgf_playability.step import PlayabilityStep as Step

        captured = {}

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        context = types.SimpleNamespace(logger=Log(), execution=1)
        inputs = types.SimpleNamespace(refs={})
        checks = [{"id": "frames.readable", "project": "desktop", "status": "FAIL",
                   "required": True, "summary": "play-2s: mean luminance 6.84",
                   "measured": {"play-2s": {"mean_luminance": 6.84, "contrast": 9.79}}}]
        result = Step(types.SimpleNamespace(params={}))._finish(
            context, inputs, "demo", "b" * 40, checks, [], {}, None,
            [{"id": "desktop", "viewport": {"width": 1280, "height": 720}, "ran": True}])
        captured = result.artifacts[0].content
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.route, "fail")
        self.assertEqual(captured["verdict"], "FAIL")
        self.assertEqual(captured["failed_checks"], ["desktop:frames.readable"])
        self.assertEqual(ArtifactContracts()("playability-report", captured), [])


if __name__ == "__main__":
    unittest.main()
