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


def unit(index, uid, objective, difficulty, duration=40, mechanics=("shoot",), failure=True):
    return {"id": uid, "index": index, "tier": "mvp", "purpose": "test", "objective": objective,
            "mechanics": list(mechanics), "difficulty": difficulty,
            "expected_duration_s": duration,
            "success": "Every enemy of the wave is down.",
            "failure": "The player's health reaches zero." if failure else "n/a",
            "acceptance": ["The wave is entered from the previous one by playing.",
                           f"The objective of {uid} is on screen before it starts."]}


# An authored design of a genre family (shooter): three mvp waves, one declared difficulty axis
# that the family says escalates, and a depth contract with a persisted best.
CONTENT_DESIGN = copy.deepcopy(DESIGN)
CONTENT_DESIGN["genre"] = {"family": "shooter", "ending": "finite", "session_profile": "standard"}
CONTENT_DESIGN["session"] = {"target_seconds": 180, "first_session_seconds": 180,
                             "time_to_first_play_s": 5, "time_to_first_reward_s": 10,
                             "structure": "waves"}
CONTENT_DESIGN["build_spec"].update({
    "content": {
        "unit_kind": "wave", "generation": {"mode": "authored"},
        "units": [unit(1, "w-01", "Clear every rusher before the gate falls.", {"enemy-count": 0.3}),
                  unit(2, "w-02", "Hold the breach while the shielded pair advances.",
                       {"enemy-count": 0.25}),
                  unit(3, "w-03", "Survive the elite wave with one magazine.",
                       {"enemy-count": 0.6})]},
    "difficulty": {"model": "level-authored", "curve": [{"at": "wave 1", "description": "calm"}],
                   "axes": [{"id": "enemy-count", "range": [0, 1]}]},
    "depth": {
        "meta_loop": {"statement": "Clear waves, bank the best, come back for the next one.",
                      "tier": "mvp",
                      "persists": [{"kind": "best-score", "what": "the best wave reached",
                                    "tier": "mvp"}]},
        "goal_ladder": [{"id": "g-1", "horizon": "short", "goal": "Clear the next rusher.",
                         "tier": "mvp"}],
        "content_schedule": [{"id": "shielded", "kind": "enemy", "name": "Shielded rusher",
                              "introduced": "wave 2", "at_s": 20,
                              "rule": "Shields must be broken first.", "tier": "mvp"}],
        "first_session": {"target_s": 180, "ends_on": "beating the best wave", "tier": "mvp"},
        "return_hooks": [{"id": "best", "kind": "best-score",
                          "statement": "I want the next wave.", "tier": "mvp"}]},
})


def traverse(units=((1, "w-01", 0.3, ("rusher",)), (2, "w-02", 0.25, ("rusher", "shield")),
                    (3, "w-03", 0.6, ("elite",))), grace_ms=400, objectives=None):
    """A traverse record: the units played in order, each entered just after the last ended."""
    design_units = {u["id"]: u for u in CONTENT_DESIGN["build_spec"]["content"]["units"]}
    per_unit, transitions, snapshots = [], [], []
    at = 0
    previous = None
    for index, uid, value, kinds in units:
        texts = (objectives or {}).get(uid, design_units[uid]["objective"])
        per_unit.append({"unit_id": uid, "index": index,
                         "objective_texts": [texts] if texts else [],
                         "kinds": list(kinds), "difficulty": {"enemy-count": value},
                         "metrics": {"saves": index, "lives": 3}, "won": True, "lost": False,
                         "entered_ms": at, "duration_ms": 5000})
        snapshots.append({"ms": at, "unit_id": uid, "unit_index": index, "state": "playing",
                          "progress": {"metric": "cleared", "value": 0, "target": 5},
                          "difficulty": {"enemy-count": value}, "kinds": list(kinds)})
        if previous is not None:
            transitions.append({"from": previous, "to": index, "at_ms": at, "how": "won",
                                "since_end_ms": grace_ms})
        previous = index
        at += 5000
    return {"applies": True, "snapshots": snapshots, "transitions": transitions,
            "per_unit": per_unit, "losses": 0, "stopped": "max units", "errors": []}


class Content(Judge):
    """The content, difficulty and depth checks: a build held to the units it claims."""

    IN_UNIT = {"unit_id": "w-01", "unit_index": 1, "unit_count": 3, "unit_kind": "wave",
               "objective": "Clear every rusher before the gate falls.",
               "progress": {"metric": "cleared", "value": 1, "target": 5}}

    def setUp(self):
        super().setUp()
        # A build that authors its content says, in every playing snapshot, which unit it is in.
        for sample in self.records["first-session"]["samples"]:
            if sample["state"] == "playing":
                sample["content"] = dict(self.IN_UNIT)
        for entry in self.records["act"]["acted"]:
            for side in ("before", "after"):
                entry[side]["content"] = dict(self.IN_UNIT)
        self.records["traverse"] = traverse()
        self.records["lose"].update({
            "endedAtMs": 8000, "initialContent": {"unit_id": "w-01", "unit_index": 1,
                                                  "unit_count": 3, "unit_kind": "wave"},
            "contentAtEnd": {"unit_id": "w-01", "unit_index": 1, "unit_count": 3,
                             "unit_kind": "wave",
                             "progress": {"metric": "cleared", "value": 2, "target": 5}},
            "series": [{"ms": 0, "state": "playing", "metrics": {"lives": 3}, "content": None}]})
        self.records["persist"] = {
            "applies": True, "changed": "best",
            "before": {"state": "playing", "metrics": {"saves": 3, "best": 7},
                       "content": {"unit_id": "w-02", "unit_index": 2, "unit_count": 3,
                                   "unit_kind": "wave"}},
            "after": {"state": "title", "metrics": {"saves": 0, "best": 7}, "content": None},
            "after_resumed": {"state": "playing", "metrics": {"saves": 0, "best": 7},
                              "content": {"unit_id": "w-02", "unit_index": 2, "unit_count": 3,
                                          "unit_kind": "wave"}}}
        self.records["session"] = {
            "applies": True, "length_ms": 150000, "beat_at_ms": 60000, "ended_on": "beat reached",
            "target_ms": 180000, "window_ms": 30000,
            "runs": [{"duration_ms": 60000, "inputs": 10, "oracle_inputs_per_third": [3, 3, 4]}],
            "windows": [{"at_ms": 30000, "difficulty": {"enemy-count": 0.3}},
                        {"at_ms": 60000, "difficulty": {"enemy-count": 0.6}}]}

    def judge(self, design=None):
        return super().judge(design if design is not None else CONTENT_DESIGN)

    def test_units_traversed_in_design_order_pass(self):
        checks = self.judge()
        self.assertEqual(checks["content.units_reachable"]["status"], "PASS",
                         checks["content.units_reachable"]["summary"])
        self.assertEqual(checks["content.units_reachable"]["measured"]["units_reached"], [1, 2, 3])
        self.assertEqual(self.failed(), [], {k: v["summary"] for k, v in checks.items()
                                            if v["status"] == "FAIL"})

    def test_a_skipped_unit_fails_units_reachable(self):
        self.records["traverse"] = traverse(units=((1, "w-01", 0.3, ("rusher",)),
                                                   (3, "w-03", 0.6, ("elite",))))
        check = self.judge()["content.units_reachable"]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("[1, 2, 3]", check["summary"])

    def test_objective_shown_per_unit(self):
        checks = self.judge()
        self.assertEqual(checks["content.objective_shown"]["status"], "PASS")
        self.records["traverse"] = traverse(objectives={"w-02": "0  3  HP"})
        check = self.judge()["content.objective_shown"]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("w-02", check["summary"])

    def test_difficulty_rises_with_a_relief_dip(self):
        # 0.3 -> 0.25 is relief (inside relief_dip_max), 0.25 -> 0.6 climbs, and 0.6 > 0.3.
        check = self.judge()["difficulty.axes_progress"]
        self.assertEqual(check["status"], "PASS", check["summary"])
        self.assertEqual(check["measured"]["enemy-count"], [0.3, 0.25, 0.6])

    def test_flat_difficulty_fails(self):
        self.records["traverse"] = traverse(units=((1, "w-01", 0.3, ("rusher",)),
                                                   (2, "w-02", 0.3, ("rusher", "shield")),
                                                   (3, "w-03", 0.3, ("elite",))))
        check = self.judge()["difficulty.axes_progress"]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("ended at 0.3, started at 0.3", check["summary"])

    def test_required_axis_absent_from_probe_fails(self):
        # The family says enemy-variety is reported by the build (`probe: required`).
        design = copy.deepcopy(CONTENT_DESIGN)
        design["build_spec"]["difficulty"]["axes"].append({"id": "enemy-variety", "range": [0, 1]})
        check = self.judge(design)["difficulty.axes_progress"]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("metrics.difficulty.enemy-variety", check["summary"])

    def test_variety_between_consecutive_units(self):
        self.assertEqual(self.judge()["content.variety"]["status"], "PASS")
        # Every unit drawing the same one kind: no variety, and no new kind per unit either.
        self.records["traverse"] = traverse(units=((1, "w-01", 0.3, ("rusher",)),
                                                   (2, "w-02", 0.4, ("rusher",)),
                                                   (3, "w-03", 0.6, ("rusher",))))
        design = copy.deepcopy(CONTENT_DESIGN)
        for entry in design["build_spec"]["content"]["units"]:
            entry["mechanics"] = ["shoot"]
        check = self.judge(design)["content.variety"]
        self.assertEqual(check["status"], "FAIL")
        self.assertEqual(check["measured"]["changed_pairs_share"], 0.0)

    def test_persisted_progress_survives_reload(self):
        check = self.judge()["progression.persists"]
        self.assertEqual(check["status"], "PASS", check["summary"])
        self.assertEqual(check["measured"]["best"], {"before": 7, "after": 7})
        self.assertEqual(check["measured"]["content.unit_index"], {"before": 2, "after": 2})
        self.records["persist"]["after"]["metrics"]["best"] = 0
        self.records["persist"]["after_resumed"]["metrics"]["best"] = 0
        failed = self.judge()["progression.persists"]
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("best", failed["summary"])

    def test_parametric_designs_skip_content_checks_and_skipped_is_never_pass(self):
        design = copy.deepcopy(CONTENT_DESIGN)
        design["build_spec"]["content"]["generation"] = {"mode": "parametric",
                                                         "expected_units": 3}
        checks = self.judge(design)
        for cid in ("content.units_reachable", "content.objective_shown",
                    "content.win_lose_per_unit"):
            self.assertEqual(checks[cid]["status"], "SKIPPED", cid)
            self.assertNotEqual(checks[cid]["status"], "PASS")
            self.assertIn("parametric", checks[cid]["summary"])
        # Nothing skipped is counted as a failure either: a skip measures nothing.
        self.assertNotIn("content.units_reachable", self.failed())

    def test_claimed_content_with_no_probe_content_fails_probe_valid(self):
        # The design authors units; the build never says which one the player is in.
        for sample in self.records["first-session"]["samples"]:
            sample.pop("content", None)
        for entry in self.records["act"]["acted"]:
            for side in ("before", "after"):
                entry[side].pop("content", None)
        self.records["traverse"] = {"applies": True, "snapshots": [], "transitions": [],
                                    "per_unit": [], "losses": 0, "stopped": "window"}
        check = self.judge()["probe.valid"]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("reports no `content` while playing", check["summary"])

    def test_session_length_bar(self):
        check = self.judge()["depth.session_length"]
        self.assertEqual(check["status"], "PASS", check["summary"])
        self.records["session"]["length_ms"] = 30000       # under 0.5 x 180 s
        short = self.judge()["depth.session_length"]
        self.assertEqual(short["status"], "FAIL")
        self.assertEqual(short["measured"]["length_ms"], 30000)

    def test_a_truncated_session_is_not_a_failure_of_the_build(self):
        self.records["session"]["length_ms"] = 30000
        self.rules["_truncated"] = {"session": True}
        check = self.judge()["depth.session_length"]
        self.assertEqual(check["status"], "WARNING")
        self.assertTrue(check["measured"]["truncated"])

    def test_finite_design_without_win_fails(self):
        design = copy.deepcopy(CONTENT_DESIGN)
        del design["build_spec"]["experience"]["win"]
        self.records["win"]["reached"] = None
        self.records["win"]["series"] = [{"ms": 0, "value": 0, "state": "playing"},
                                         {"ms": 900, "value": 9, "state": "playing"}]
        check = self.judge(design)["win.reachable"]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("encounter-cleared", check["summary"])

    def test_cfg_respects_the_time_budget(self):
        from wgflib import genre_models

        qa = genre_models.qa_of(CONTENT_DESIGN)
        base = {"idle_ms": 10000, "win_ms": 180000, "lose_ms": 90000, "start_timeout_ms": 30000}
        cfg, truncated, total_s = PlayabilityStep._content_settings(CONTENT_DESIGN, qa, base)
        self.assertEqual(total_s, qa["time_budget"]["bot_total_s"])
        spent = base["idle_ms"] + base["win_ms"] + base["lose_ms"] + 2 * base["start_timeout_ms"]
        asked = cfg["traverse_ms"] + cfg["persist_ms"] + cfg["session_max_ms"]
        self.assertLessEqual(spent + asked, total_s * 1000)
        self.assertEqual(truncated, {"traverse": True, "persist": True, "session": True})
        self.assertTrue(cfg["content_applies"] and cfg["depth_applies"])
        self.assertEqual(cfg["unit_count"], 3)
        self.assertEqual(cfg["axes"], ["enemy-count"])
        # The family states no endless window, so the depth bar stands.
        self.assertEqual(cfg["window_ms"], qa["difficulty"]["endless_window_s"] * 1000)
        self.assertIn("next", cfg["advance_actions"])

    def test_a_design_with_no_content_or_depth_asks_for_none_of_it(self):
        from wgflib import genre_models

        cfg, truncated, _ = PlayabilityStep._content_settings(
            DESIGN, genre_models.qa_of(DESIGN),
            {"idle_ms": 10000, "win_ms": 180000, "lose_ms": 90000, "start_timeout_ms": 30000})
        self.assertFalse(cfg["content_applies"] or cfg["depth_applies"])
        self.assertEqual((cfg["traverse_ms"], cfg["persist_ms"], cfg["session_max_ms"]), (0, 0, 0))
        self.assertEqual(truncated, {"traverse": False, "persist": False, "session": False})


# -- an authored puzzle, mirroring the first live greybox run ---------------------------------
# A six-level level-authored puzzle of the `puzzle` family (Ice Slide, greybox 2-1). The family
# asks for 4 units traversed, so the bot is given 5 and the fifth is still in play when it
# stops at `max units`; variety there is the layout, which entity kinds cannot show
# (qa.min_new_kinds_per_unit 0); and the family states no `endless_window_s`, so one level has
# no time ramp inside it. The difficulty values are the ones that run's design authored and its
# build reported.
LEVELS = [
    ("l-01", {"depth": 0.08, "move-limit": 0.06, "board-complexity": 0.1, "piece-variety": 0.15},
     ("goal-tile", "penguin")),
    ("l-02", {"depth": 0.08, "move-limit": 0.14, "board-complexity": 0.1, "piece-variety": 0.15},
     ("goal-tile", "penguin")),
    ("l-03", {"depth": 0.08, "move-limit": 0.14, "board-complexity": 0.1, "piece-variety": 0.27},
     ("door", "goal-tile", "key", "penguin")),
    ("l-04", {"depth": 0.08, "move-limit": 0.14, "board-complexity": 0.17, "piece-variety": 0.27},
     ("door", "goal-tile", "key", "penguin")),
    ("l-05", {"depth": 0.08, "move-limit": 0.14, "board-complexity": 0.11, "piece-variety": 0.27},
     ("door", "goal-tile", "key", "penguin")),
    ("l-06", {"depth": 0.16, "move-limit": 0.14, "board-complexity": 0.11, "piece-variety": 0.41},
     ("door", "goal-tile", "key", "penguin")),
]
PUZZLE_AXES = ["depth", "move-limit", "board-complexity", "piece-variety"]


def level(index, uid, difficulty):
    entry = unit(index, uid, f"Reach the goal tile of {uid} inside its move cap.", difficulty,
                 duration=40, mechanics=("slide-move", "obstacle-wall", "goal-tile"))
    entry["success"] = "The penguin reaches the goal tile inside the move cap."
    entry["failure"] = "The move cap passes with the goal unreached, and the layout resets."
    return entry


PUZZLE_DESIGN = copy.deepcopy(DESIGN)
PUZZLE_DESIGN["genre"] = {"family": "puzzle", "node": "logic-puzzle", "ending": "finite",
                          "session_profile": "casual"}
PUZZLE_DESIGN["session"] = {"target_seconds": 90, "first_session_seconds": 180,
                            "time_to_first_play_s": 5, "time_to_first_reward_s": 10,
                            "structure": "levels"}
PUZZLE_DESIGN["build_spec"].update({
    "content": {"unit_kind": "level", "generation": {"mode": "authored"},
                "units": [level(i + 1, uid, dict(difficulty))
                          for i, (uid, difficulty, _kinds) in enumerate(LEVELS)]},
    "progression": {"model": "linear-levels"},
    "difficulty": {"model": "level-authored",
                   "curve": [{"at": "levels 1-3", "description": "forgiving"}],
                   "axes": [{"id": a, "range": [0, 1], "relief_allowed": True}
                            for a in PUZZLE_AXES]},
    "depth": {
        "meta_loop": {"statement": "Clear a level, earn its stars, open the next.", "tier": "mvp",
                      "persists": [{"kind": "collection", "what": "stars per level",
                                    "tier": "post-mvp"}]},
        "goal_ladder": [{"id": "g-1", "horizon": "short", "goal": "Find the next slide.",
                         "tier": "mvp"}],
        "first_session": {"target_s": 180, "ends_on": "a cleared level with its stars stamped",
                          "tier": "mvp"},
        "return_hooks": [{"id": "next-level", "kind": "stage-map",
                          "statement": "There is a next level.", "tier": "mvp"}]},
})


def puzzle_traverse(count=5, stopped="max units", reported=None, finished=None):
    """A traverse of the first `count` levels, the last of them still in play.

    `reported` overrides what the build said the difficulty of a level was (uid -> axis ->
    value); `finished` is the number of levels the bot saw to their end (every one but the last
    by default - the bot stops while the next level is still being played).
    """
    per_unit, transitions, snapshots = [], [], []
    at = 0
    done = count - 1 if finished is None else finished
    for index, (uid, difficulty, kinds) in enumerate(LEVELS[:count], start=1):
        values = dict(difficulty)
        values.update((reported or {}).get(uid) or {})
        won = index <= done
        per_unit.append({"unit_id": uid, "index": index,
                         "objective_texts": [f"Reach the goal tile of {uid} inside its move cap."],
                         "kinds": list(kinds), "difficulty": values,
                         "metrics": {"saves": index, "lives": 3,
                                     **{f"difficulty.{a}": v for a, v in values.items()}},
                         "won": won, "lost": False, "entered_ms": at,
                         "duration_ms": 800 if won else 0})
        snapshots.append({"ms": at, "unit_id": uid, "unit_index": index, "state": "playing",
                          "progress": {"metric": "moves-left", "value": 12, "target": 0},
                          "difficulty": values, "kinds": list(kinds)})
        if index > 1:
            transitions.append({"from": index - 1, "to": index, "at_ms": at, "how": "won",
                                "since_end_ms": 265})
        at += 900
    return {"applies": True, "snapshots": snapshots, "transitions": transitions,
            "per_unit": per_unit, "losses": 0, "stopped": stopped, "errors": []}


class AuthoredPuzzle(Judge):
    """The rules the first live greybox run of an authored puzzle made necessary: the build is
    held to the design's own difficulty values, and nothing is failed on evidence the bot's
    budget or the family's vocabulary cannot carry."""

    IN_UNIT = {"unit_id": "l-01", "unit_index": 1, "unit_count": 6, "unit_kind": "level",
               "objective": "Reach the goal tile of l-01 inside its move cap.",
               "progress": {"metric": "moves-left", "value": 11, "target": 0}}

    def setUp(self):
        super().setUp()
        for sample in self.records["first-session"]["samples"]:
            if sample["state"] == "playing":
                sample["content"] = dict(self.IN_UNIT)
        for entry in self.records["act"]["acted"]:
            for side in ("before", "after"):
                entry[side]["content"] = dict(self.IN_UNIT)
        self.records["traverse"] = puzzle_traverse()
        self.records["lose"].update({
            "endedAtMs": 9000, "initialContent": dict(self.IN_UNIT),
            "contentAtEnd": dict(self.IN_UNIT),
            "resetInUnit": {"clicked": "input:retry", "playingMs": 400,
                            "before": {**self.IN_UNIT,
                                       "progress": {"metric": "moves-left", "value": 8,
                                                    "target": 0}},
                            "after": {**self.IN_UNIT,
                                      "progress": {"metric": "moves-left", "value": 0,
                                                   "target": 0}}},
            "series": [{"ms": 0, "state": "playing", "metrics": {"lives": 3}, "content": None}]})
        self.records["session"] = {
            "applies": True, "length_ms": 150000, "beat_at_ms": 60000, "ended_on": "beat reached",
            "target_ms": 220000, "window_ms": 30000,
            # A level puzzle asks the same of the player throughout one level: the rate across a
            # run's thirds falls as the level is solved.
            "runs": [{"duration_ms": 800, "inputs": 6, "oracle_inputs_per_third": [3, 2, 1]}],
            "windows": []}

    def judge(self, design=None):
        return super().judge(design if design is not None else PUZZLE_DESIGN)

    def test_the_live_greybox_shape_fails_nothing_it_could_not_measure(self):
        checks = self.judge()
        self.assertEqual(self.failed(), [], {k: v["summary"] for k, v in checks.items()
                                            if v["status"] == "FAIL"})
        self.assertEqual(checks["content.variety"]["status"], "WARNING")
        self.assertEqual(checks["depth.ramp"]["status"], "PASS")
        self.assertEqual(checks["difficulty.axes_progress"]["status"], "PASS")

    # 2. A unit the traverse never left
    def test_a_unit_still_in_play_when_the_traverse_stopped_is_not_never_completed(self):
        check = self.judge()["content.win_lose_per_unit"]
        self.assertEqual(check["status"], "PASS", check["summary"])
        self.assertEqual(check["measured"]["in_progress"], ["l-05"])
        self.assertEqual(check["measured"]["not_completed"], [])
        self.assertIn("still in play when the traverse stopped (max units)", check["summary"])

    def test_a_unit_the_traverse_left_unwon_is_still_a_failure(self):
        # The traverse ended because play was lost twice - not because the bot ran out of
        # units - so the level it was in was played to its end, and never completed.
        self.records["traverse"] = puzzle_traverse(stopped="lost twice")
        check = self.judge()["content.win_lose_per_unit"]
        self.assertEqual(check["status"], "FAIL")
        self.assertEqual(check["measured"]["not_completed"], ["l-05"])
        self.assertIn("played but never completed: l-05", check["summary"])

    def test_the_failure_side_still_holds(self):
        # The design states a failure for every level; bad play must reach one.
        self.records["lose"]["reached"] = None
        self.assertIn("content.win_lose_per_unit", self.failed())

    # 3. The build against the design
    def test_a_build_whose_unit_difficulty_is_not_the_designs_fails(self):
        from wgflib import genre_models

        tolerance = genre_models.implementation()["difficulty_tolerance"]
        self.records["traverse"] = puzzle_traverse(
            reported={"l-03": {"depth": 0.08 + tolerance + 0.01}})
        check = self.judge()["difficulty.axes_progress"]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("l-03 depth", check["summary"])
        self.assertIn("the design states 0.08", check["summary"])
        self.assertEqual(check["measured"]["difficulty_tolerance"], tolerance)

    def test_a_value_inside_the_tolerance_is_the_designs(self):
        from wgflib import genre_models

        tolerance = genre_models.implementation()["difficulty_tolerance"]
        self.records["traverse"] = puzzle_traverse(reported={"l-03": {"depth": 0.08 + tolerance}})
        self.assertEqual(self.judge()["difficulty.axes_progress"]["status"], "PASS")

    def test_a_capped_traversal_is_not_held_to_a_rise_it_never_saw(self):
        # depth is 0.08 across levels 1-5 and rises on level 6, which the bot never reached.
        check = self.judge()["difficulty.axes_progress"]
        self.assertEqual(check["status"], "PASS", check["summary"])
        self.assertEqual(check["measured"]["depth"], [0.08] * 5)
        self.assertTrue(check["measured"]["partial"])
        self.assertIn("stopped short of the design's units", check["summary"])

    def test_a_whole_traversal_is_held_to_the_rise(self):
        self.records["traverse"] = puzzle_traverse(count=6, finished=6)
        check = self.judge()["difficulty.axes_progress"]
        self.assertEqual(check["status"], "PASS", check["summary"])
        self.assertNotIn("partial", check["measured"])
        # Flat to the end, design and build agreeing on it: a curve that never rises.
        flat = {uid: {"depth": 0.08} for uid, _d, _k in LEVELS}
        design = copy.deepcopy(PUZZLE_DESIGN)
        for entry in design["build_spec"]["content"]["units"]:
            entry["difficulty"]["depth"] = 0.08
        self.records["traverse"] = puzzle_traverse(count=6, finished=6, reported=flat)
        check = self.judge(design)["difficulty.axes_progress"]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("depth: ended at 0.08, started at 0.08", check["summary"])

    # 4. Variety a family does not promise in entity kinds
    def test_variety_is_reported_not_failed_when_kinds_cannot_show_it(self):
        check = self.judge()["content.variety"]
        self.assertEqual(check["status"], "WARNING")
        self.assertFalse(check["required"])
        self.assertEqual(check["measured"]["changed_pairs_share"], 0.25)
        self.assertEqual(check["measured"]["reason"],
                         "variety is not visible in entity kinds for this family (layout, "
                         "rules, objectives)")

    def test_a_family_that_asks_for_a_new_kind_per_unit_still_fails(self):
        # The same records under a family whose qa states min_new_kinds_per_unit >= 1.
        design = copy.deepcopy(PUZZLE_DESIGN)
        design["genre"]["family"] = "shooter"
        check = self.judge(design)["content.variety"]
        self.assertEqual(check["status"], "FAIL")
        self.assertTrue(check["required"])
        self.assertNotIn("reason", check["measured"])

    # 5. A ramp a unit-authored family has no window for
    def test_the_input_rate_ramp_is_reported_not_failed_without_a_time_ramp(self):
        check = self.judge()["depth.ramp"]
        self.assertEqual(check["status"], "PASS", check["summary"])
        self.assertFalse(check["required"])
        self.assertEqual(check["measured"]["oracle_inputs_per_third"], [3, 2, 1])
        self.assertIn("no time ramp", check["measured"]["reason"])

    def test_a_time_ramp_family_is_still_held_to_its_rate(self):
        design = copy.deepcopy(PUZZLE_DESIGN)
        design["genre"]["family"] = "arcade"   # qa.endless_window_s: 30
        check = self.judge(design)["depth.ramp"]
        self.assertEqual(check["status"], "FAIL")
        self.assertTrue(check["required"])
        self.assertIn("asks for less as it goes", check["summary"])
        self.assertNotIn("reason", check["measured"])

    def test_bad_play_that_never_ends_is_still_measured(self):
        self.records["lose"]["endedAtMs"] = None
        check = self.judge()["depth.ramp"]
        self.assertEqual(check["status"], "WARNING")
        self.assertIn("bad play ended after None ms", check["summary"])

    # 6. A retry with no loss to retry from
    def test_restart_waits_on_a_loss(self):
        self.records["lose"].update({"reached": None, "restart": None})
        check = self.judge()["restart.works"]
        self.assertEqual(check["status"], "BLOCKED")
        self.assertEqual(check["measured"]["reason"], "no loss to retry from")
        self.assertIn("lose.reachable", check["summary"])

    # 7. The objective compared is the design's own, per unit
    def test_the_objective_measured_is_the_units_own(self):
        traverse = puzzle_traverse()
        for entry in traverse["per_unit"]:
            # Every level showing the same generic line: only the level whose objective it is
            # has its objective on screen.
            entry["objective_texts"] = ["Reach the goal tile before your moves run out."]
        self.records["traverse"] = traverse
        check = self.judge()["content.objective_shown"]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("l-02", check["summary"])
        self.assertLess(check["measured"]["l-02"], 0.6)


class TheAntiOracle(unittest.TestCase):
    """The bot's bad play (bot.spec.ts). The first live greybox run pressed one blocked
    direction for 85 s: it cost no move, nothing changed, and the game could not be lost."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(SCRIPTS, "wgf_playability", "bot.spec.ts")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        start = source.index('test("lose and restart')
        cls.source = source[start:source.index('write(project, "lose"', start)]

    def has(self, fragment):
        self.assertIn(fragment, self.source, f"the anti-oracle no longer contains {fragment!r}")

    def test_the_wrong_move_rotates(self):
        # The k-th move that is not the oracle's, not the first one every time.
        self.has("const picked = others.length ? k % others.length : null;")
        self.has("others[picked]")
        # k advances on every press.
        self.has("k += 1;")

    def test_a_press_that_changed_nothing_advances_the_rotation(self):
        self.has("const repeated = unchanged !== null && state === unchanged;")
        self.has("if (repeated) k += 1;")

    def test_bad_play_is_never_a_pause_or_a_settings_toggle(self):
        self.has("filter((m) => !UTILITY.test(m.action))")


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
    @staticmethod
    def finish(checks, blocked=None):
        from wgf_playability.step import PlayabilityStep as Step

        class Log:
            def __getattr__(self, name):
                return lambda *a, **k: None

        return Step(types.SimpleNamespace(params={}))._finish(
            types.SimpleNamespace(logger=Log(), execution=1), types.SimpleNamespace(refs={}),
            "demo", "b" * 40, checks, [], {}, blocked,
            [{"id": "desktop", "viewport": {"width": 1280, "height": 720}, "ran": True}])

    def test_a_report_with_skipped_checks_validates(self):
        """A skip is reported with its reason, counted as neither a pass nor a failure."""
        checks = [{"id": "content.units_reachable", "project": "desktop", "status": "SKIPPED",
                   "required": True,
                   "summary": "content is generated (parametric): the units listed are "
                              "representative"},
                  {"id": "content.units_reachable", "project": "mobile", "status": "SKIPPED",
                   "required": True,
                   "summary": "content is generated (parametric): the units listed are "
                              "representative"},
                  {"id": "difficulty.axes_progress", "project": "desktop", "status": "WARNING",
                   "required": False, "summary": "no escalating axis is reported",
                   "measured": {"reported": []}},
                  {"id": "idle.grace", "project": "desktop", "status": "PASS", "required": True,
                   "summary": "with no input for 10000 ms, play was not lost"}]
        result = self.finish(checks)
        report = result.artifacts[0].content
        self.assertEqual(result.outcome, StepOutcome.SUCCESS)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["failed_checks"], [])
        self.assertEqual(report["skipped_checks"],
                         [{"id": "content.units_reachable",
                           "reason": "content is generated (parametric): the units listed are "
                                     "representative"}])
        self.assertIn("content.units_reachable", result.message)
        self.assertIn("not passes", result.message)
        self.assertEqual(ArtifactContracts()("playability-report", report), [])

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
