"""Play realism (scripts/wgf_playability/realism.py): the build's physics against what it draws,
naive play, the level geometry it declares, the clearance its moving body needs, per-unit
clear rates against the accepted build, and the console - each check on synthetic passing and
failing records, then REPLAYED on the real evidence of the two 2026-10 validation games
(scripts/tests/fixtures/real/play-realism/README.md): the regressed builds must FAIL, the
accepted and r1-forward builds must PASS where the evidence exists.

    python -m unittest scripts.tests.test_play_realism
"""

import copy
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_playability import analysis, realism  # noqa: E402
from wgf_playability.step import CONTENT_COPY, RECORDS, PlayabilityStep  # noqa: E402
from wgflib import jsonschema_lite, paths  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

RULES = realism.load_rules()
D2 = {"engine": {"dimension": "2d"}}
D3 = {"engine": {"dimension": "3d"}}
REAL = os.path.join(HERE, "fixtures", "real", "play-realism")
MVP = realism.strength_for(RULES, "mvp")
RELEASE = realism.strength_for(RULES, "release")
# Release as a run holds it: an unmeasured check is not passed (quality-policy.yaml rule 5).
HELD = realism.strength_for(RULES, "release", held=lambda cid: "not passed at release")


def real(name):
    path = os.path.join(REAL, name)
    if name.endswith(".gz"):
        with gzip.open(path, "rb") as handle:
            return json.loads(handle.read().decode("utf-8"))
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# A board of 400 x 600 at (440, 0); a paddle at the bottom, a brick row at y 100-120, a HUD
# bar at y 20-34 (a goal-role entity) above everything.
PADDLE = ["paddle", "player", 1, 600, 560, 80, 20, "paddle", "asset", None]
BRICKS = ["bricks", "target", 1, 440, 100, 400, 20, "brick", "asset", None]
HUD = ["bar", "goal", 1, 560, 20, 160, 14, None, "primitive", None]
PLAYFIELD = {"x": 440, "y": 0, "w": 400, "h": 600}


def ball(x, y, size=20, collider=None):
    return ["ball", "projectile", 1, x - size / 2, y - size / 2, size, size, "ball", "asset", collider]


def win(frames, playfields=None):
    sampled = {"frames": frames, "viewport": [1280, 720]}
    if playfields is not None:
        sampled["playfields"] = playfields
    return {"win": {"sampled": sampled}}


def path(points, extra=(PADDLE, BRICKS, HUD), **kw):
    """Frames of a ball through `points` (centre x, y), one per frame, beside `extra`."""
    return [[ball(x, y, **kw)] + [list(e) for e in extra] for x, y in points]


def line(a, b, steps):
    return [(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
            for i in range(steps + 1)]


def check(checks, cid):
    found = [c for c in checks if c["id"] == cid]
    return found[0] if found else None


class UndrawnCollision(unittest.TestCase):
    def judge(self, records, design=D2, strength=MVP):
        return check(realism.judge(records, design, RULES, "desktop", strength),
                     "physics.undrawn_collision")

    def test_a_ball_turning_at_the_paddle_and_the_bricks_passes(self):
        points = line((640, 550), (660, 130), 20)[:-1] + line((660, 130), (680, 550), 20)
        result = self.judge(win(path(points)))
        self.assertEqual(result["status"], "PASS", result)
        self.assertGreaterEqual(result["measured"]["turns"], 1)

    def test_a_ball_turning_short_of_anything_drawn_fails_and_blocks_at_release(self):
        # The shape of 68a12b7: up from the paddle, turned at y 377 with the drawn brick row
        # behind it and the HUD bar 248 px above - an undrawn ceiling.
        bricks_low = ["bricks", "target", 1, 440, 403, 400, 17, "brick", "composite", None]
        points = line((700, 550), (707, 377), 12)[:-1] + line((707, 377), (720, 550), 12)
        hud = ["bar", "goal", 1, 553, 103, 173, 14, None, "composite", None]
        records = win(path(points, extra=(PADDLE, bricks_low, hud)))
        result = self.judge(records, strength=RELEASE)
        self.assertEqual(result["status"], "FAIL", result)
        self.assertTrue(result["required"])
        first = result["measured"]["unexplained"][0]
        self.assertEqual(first["moving"], "-y")
        self.assertGreater(first["gap_ahead_px"], 200)
        # Below the release tier a measured failure is a warning the report lists.
        self.assertEqual(self.judge(records, strength=MVP)["status"], "WARNING")

    def test_with_a_playfield_a_wall_bounce_passes_and_a_mid_board_turn_fails(self):
        to_wall = line((600, 300), (450, 250), 10)[:-1] + line((450, 250), (600, 200), 10)
        frames = path(to_wall, extra=(PADDLE,))
        self.assertEqual(self.judge(win(frames, [PLAYFIELD] * len(frames)))["status"], "PASS")
        short = line((600, 300), (520, 250), 10)[:-1] + line((520, 250), (600, 200), 10)
        frames = path(short, extra=(PADDLE,))
        result = self.judge(win(frames, [PLAYFIELD] * len(frames)), strength=RELEASE)
        self.assertEqual(result["status"], "FAIL", result)
        self.assertTrue(result["measured"]["unexplained"][0]["playfield"])

    def test_without_a_playfield_a_wall_bounce_is_unmeasured_never_passed(self):
        to_wall = line((600, 300), (450, 250), 10)[:-1] + line((450, 250), (600, 200), 10)
        result = self.judge(win(path(to_wall, extra=(PADDLE,))))
        self.assertEqual(result["status"], "WARNING")
        self.assertFalse(result["required"])
        self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)
        self.assertIn("no playfield", result["summary"])
        # Where quality-policy.yaml holds a skipped check as not passed, it fails the build.
        held = self.judge(win(path(to_wall, extra=(PADDLE,))), strength=HELD)
        self.assertEqual(held["status"], "FAIL")
        self.assertTrue(held["required"])

    def test_a_brick_the_hit_breaks_still_explains_the_turn(self):
        points = line((640, 550), (660, 130), 20)[:-1] + line((660, 130), (680, 550), 20)
        frames = path(points)
        for f in frames[20:]:
            f[:] = [e for e in f if e[0] != "bricks"]
        self.assertEqual(self.judge(win(frames))["status"], "PASS")

    def test_a_ball_carried_by_the_paddle_turns_with_it(self):
        frames = []
        for x in [600, 610, 620, 630, 620, 610, 600]:
            paddle = list(PADDLE)
            paddle[3] = x - 40
            frames.append([ball(x, 550), paddle])
        self.assertEqual(self.judge(win(frames))["status"], "PASS")

    def test_a_turn_on_both_axes_at_the_paddle_is_one_contact(self):
        points = [(600, 500), (610, 520), (620, 540), (610, 520), (600, 500)]
        self.assertEqual(self.judge(win(path(points, extra=(PADDLE,))))["status"], "PASS")

    def test_a_3d_build_is_not_judged_on_screen_turns(self):
        points = line((640, 550), (660, 300), 10)[:-1] + line((660, 300), (680, 550), 10)
        self.assertIsNone(self.judge(win(path(points)), design=D3))

    def test_no_sampled_frame_is_unmeasured(self):
        self.assertEqual(self.judge({"win": {}})["status"], "WARNING")

    def test_nothing_moving_of_a_judged_role_is_not_judged(self):
        frames = [[list(PADDLE), list(BRICKS)] for _ in range(10)]
        self.assertIsNone(self.judge(win(frames)))

    def test_a_composite_mover_is_no_bodys_path(self):
        bolts = [["bolts", "projectile", 1, 600, y, 60, h, None, "composite", None]
                 for y, h in ((400, 30), (350, 30), (300, 300), (420, 30))]
        self.assertIsNone(self.judge(win([[b, list(PADDLE)] for b in bolts])))

    def test_turns_are_found_on_each_axis_and_stops(self):
        events = realism.turns(path([(500, 300), (510, 300), (520, 300), (510, 300)], extra=()),
                               {"projectile"}, RULES["physics"])
        self.assertEqual([(e["axis"], e["kind"]) for e in events], [(0, "reversal")])
        stopped = path([(500, 300), (510, 300), (520, 300)] + [(520, 300)] * 4, extra=())
        self.assertEqual([e["kind"] for e in realism.turns(stopped, {"projectile"},
                                                           RULES["physics"])], ["stop"])
        jumped = path([(500, 300), (510, 300), (900, 600), (890, 590)], extra=())
        self.assertEqual(realism.turns(jumped, {"projectile"}, RULES["physics"]), [])

    def test_a_reported_collider_is_what_must_reach_the_surface(self):
        # Drawn 40 px, colliding 12 px: the drawn edge reaches the bricks, the body does not.
        points = line((640, 550), (660, 160), 20)[:-1] + line((660, 160), (680, 550), 20)
        frames = [[ball(x, y, 40, ["circle", x - 6, y - 6, 12, 12])] + [list(PADDLE), list(BRICKS)]
                  for x, y in points]
        result = self.judge(win(frames, [PLAYFIELD] * len(frames)), strength=RELEASE)
        self.assertEqual(result["status"], "FAIL", result)
        self.assertTrue(result["measured"]["collider_reported"])


class ColliderSize(unittest.TestCase):
    def judge(self, frames, strength=RELEASE):
        return check(realism.judge(win(frames), D2, RULES, "desktop", strength),
                     "physics.collider_size")

    def test_a_ball_drawn_twice_its_body_fails(self):
        frames = [[ball(600, 300 - i, 24, ["circle", 594, 294 - i, 12, 12])] for i in range(5)]
        result = self.judge(frames)
        self.assertEqual(result["status"], "FAIL", result)
        self.assertEqual(result["measured"]["out_of_bounds"], ["ball"])

    def test_a_sprite_with_a_soft_edge_passes(self):
        frames = [[ball(600, 300 - i, 22, ["circle", 590, 290 - i, 20, 20])] for i in range(5)]
        self.assertEqual(self.judge(frames)["status"], "PASS")

    def test_a_body_larger_than_its_drawing_fails(self):
        frames = [[ball(600, 300 - i, 10, ["rect", 590, 290 - i, 20, 20])] for i in range(5)]
        self.assertEqual(self.judge(frames)["status"], "FAIL")

    def test_no_collider_reported_is_unmeasured(self):
        result = self.judge([[ball(600, 300 - 3 * i)] for i in range(5)], strength=MVP)
        self.assertEqual(result["status"], "WARNING")
        self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)

    def body_ball(self, drawn, body, collider, halo=None):
        """A ball drawn `drawn` px across (a glow) around an opaque `body` px across (None: no
        body reported), colliding `collider` px across, all centred at (600, y)."""
        frames = []
        for i in range(5):
            y = 300 - i
            sample = ball(600, y, drawn, ["circle", 600 - collider / 2, y - collider / 2,
                                          collider, collider])
            sample += [[600 - body / 2, y - body / 2, body, body] if body is not None else None,
                       halo]
            frames.append([sample])
        return frames

    def test_r1_forward_passes_on_its_body_inside_r1s_glow(self):
        # 2D r1-forward: a solid disc exactly the collider (40 board units) inside r1's glow
        # (56.8), at a board scale of 0.542 - 21.7 px inside 30.8 px. On the whole sprite it
        # would be 1.42 x; on its body it is 1.0.
        scale = 0.542
        frames = self.body_ball(56.8 * scale, 40 * scale, 40 * scale, halo=True)
        result = self.judge(frames)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["measured"]["judged_on"], {"ball": ["body"]})
        self.assertEqual(result["measured"]["ratios"]["ball"], [1.0, 1.0])
        # The same sprite reporting no body is judged on its whole drawn box, and fails.
        self.assertEqual(self.judge(self.body_ball(56.8 * scale, None, 40 * scale))["status"], "FAIL")

    def test_a_sprite_enlarged_with_the_collider_unchanged_still_fails(self):
        scale = 0.542
        # The body grew with the sprite (a 60-unit disc in a 85-unit glow), the collider did not.
        result = self.judge(self.body_ball(85 * scale, 60 * scale, 40 * scale, halo=True))
        self.assertEqual(result["status"], "FAIL", result)
        self.assertEqual(result["measured"]["out_of_bounds"], ["ball"])

    def test_a_collider_is_never_passed_without_a_drawn_body(self):
        # A halo declared without a body leaves nothing to hold the collider to.
        result = self.judge(self.body_ball(30, None, 21, halo=True))
        self.assertEqual(result["status"], "FAIL", result)
        self.assertIn("ball", result["measured"]["no_drawn_body"])
        # An empty body, or a body outside the drawn box, is no drawn body either.
        self.assertEqual(self.judge(self.body_ball(30, 0, 21, halo=True))["status"], "FAIL")
        self.assertEqual(self.judge(self.body_ball(16, 21, 21, halo=True))["status"], "FAIL")

    def test_the_two_builds_would_fail_once_they_report_colliders(self):
        # From their own tuning (play-realism.yaml): r1 draws 32.5 px over 11.9 px, 894b4b8
        # over 21.7 px. The bar is the ledger's; neither build reports a collider yet.
        for body in (11.9, 21.7):
            frames = [[ball(600, 300 - i, 32.5, ["circle", 600 - body / 2, 300 - i - body / 2,
                                                  body, body])] for i in range(5)]
            self.assertEqual(self.judge(frames)["status"], "FAIL", body)


def naive_run(policy="jitter", unit="u1", **kw):
    run = {"policy": policy, "asked": None, "unit_id": unit, "entered": True,
           "played_ms": 25000, "won": False, "clear_ms": None, "losses": 0, "inputs": 30,
           "setbacks_first": None, "setbacks_last": None, "par_s": None, "samples": []}
    run.update(kw)
    return run


def naive(*runs):
    return {"naive": {"applies": True, "input_kind": "held", "runs": list(runs)}}


class NaivePlay(unittest.TestCase):
    def judge(self, records, cid, units=(), strength=RELEASE, design=D3, accepted=None):
        return check(realism.judge(records, design, RULES, "desktop", strength, units, accepted),
                     cid)

    def samples(self, track=None, view=None, n=20):
        return [{"ms": i * 250, "state": "playing", "setbacks": 0,
                 "track": track(i) if track else None, "view": view(i) if view else None,
                 "progress": None} for i in range(n)]

    def test_a_course_held_forward_through_in_a_third_of_its_par_fails(self):
        records = naive(naive_run("steady", "meadow-roll", won=True, clear_ms=9099, played_ms=9099, par_s=24),
                        naive_run("steady", "storm-crown", asked="storm-crown", won=True,
                                  clear_ms=19012, played_ms=19012, par_s=50))
        result = self.judge(records, "naive.pace")
        self.assertEqual(result["status"], "FAIL", result)
        self.assertTrue(result["required"])
        self.assertEqual(result["measured"]["too_fast"], ["meadow-roll", "storm-crown"])

    def test_a_unit_not_crossed_after_half_its_par_passes_as_a_lower_bound(self):
        records = naive(naive_run("steady", "1", par_s=18), naive_run("jitter", "1", par_s=18))
        result = self.judge(records, "naive.pace")
        self.assertEqual(result["status"], "PASS", result)
        self.assertTrue(all(c["lower_bound"] for c in result["measured"]["timed"]))

    def test_the_par_comes_from_the_design_when_the_probe_has_none(self):
        for key in ("par_s", "time_target"):
            units = [{"id": "u1", "parameters": {key: 30}}]
            result = self.judge(naive(naive_run(won=True, clear_ms=6000, played_ms=6000)),
                                "naive.pace", units)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["measured"]["timed"][0]["par_from"], f"design parameters.{key}")

    def test_no_par_anywhere_is_unmeasured(self):
        result = self.judge(naive(naive_run(won=True, clear_ms=6000, played_ms=6000)), "naive.pace",
                            strength=MVP)
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("par", result["summary"])

    def test_a_unit_cleared_in_a_few_seconds_is_too_short_at_the_tier(self):
        records = naive(naive_run(won=True, clear_ms=9000, played_ms=9000))
        self.assertEqual(self.judge(records, "naive.unit_duration")["status"], "FAIL")
        self.assertEqual(self.judge(records, "naive.unit_duration", strength=MVP)["status"], "PASS")
        lasted = naive(naive_run(played_ms=25000))
        result = self.judge(lasted, "naive.unit_duration")
        self.assertEqual(result["status"], "PASS")
        self.assertIn("lower bound", result["summary"])

    def test_falling_every_few_seconds_in_the_opening_fails(self):
        records = naive(naive_run(setbacks_first=0, setbacks_last=4, played_ms=30000))
        result = self.judge(records, "naive.setbacks")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["measured"]["per_min"], 8.0)

    def test_falls_in_a_later_unit_are_reported_not_judged(self):
        records = naive(naive_run(setbacks_first=0, setbacks_last=0, played_ms=30000),
                        naive_run(unit="u9", asked="u9", setbacks_first=0, setbacks_last=9,
                                  played_ms=30000))
        result = self.judge(records, "naive.setbacks")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["measured"]["units"]["u9"]["per_min"], 18.0)

    def test_one_fall_in_a_short_sample_is_not_a_rate(self):
        result = self.judge(naive(naive_run(setbacks_first=0, setbacks_last=1, played_ms=5000)),
                            "naive.setbacks")
        self.assertEqual(result["status"], "PASS")
        self.assertIn("too few", result["summary"])

    def test_without_setbacks_losses_are_a_lower_bound(self):
        few = self.judge(naive(naive_run(losses=1, played_ms=60000)), "naive.setbacks", strength=MVP)
        self.assertEqual(few["status"], "WARNING")
        self.assertIn("no `setbacks`", few["summary"])
        many = self.judge(naive(naive_run(losses=8, played_ms=60000)), "naive.setbacks")
        self.assertEqual(many["status"], "FAIL")
        self.assertEqual(many["measured"]["losses"], 8)

    def test_drift_to_the_edge_fails_and_a_centred_run_passes(self):
        wide = self.samples(track=lambda i: {"offset": 3.8 if i % 2 else -3.9, "half_width": 4})
        self.assertEqual(self.judge(naive(naive_run(samples=wide)), "naive.drift")["status"], "FAIL")
        centred = self.samples(track=lambda i: {"offset": (i % 5 - 2) * 0.5, "half_width": 4})
        self.assertEqual(self.judge(naive(naive_run(samples=centred)), "naive.drift")["status"], "PASS")

    def test_drift_without_track_is_unmeasured_on_3d_and_not_asked_of_2d(self):
        result = self.judge(naive(naive_run(samples=self.samples())), "naive.drift", strength=MVP)
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("track", result["summary"])
        self.assertIsNone(self.judge(naive(naive_run()), "naive.drift", design=D2))
        self.assertIsNone(self.judge(naive(naive_run()), "naive.alignment", design=D2))

    def test_an_off_axis_camera_fails_alignment(self):
        skew = self.samples(view=lambda i: {"camera_forward": [0, -1],
                                            "control_forward": [0.766, -0.643]})
        result = self.judge(naive(naive_run(samples=skew)), "naive.alignment")
        self.assertEqual(result["status"], "FAIL")
        self.assertAlmostEqual(result["measured"]["p90_deg"], 50.0, delta=0.2)
        chase = self.samples(view=lambda i: {"camera_forward": [0, -1], "control_forward": [0.1, -1]})
        self.assertEqual(self.judge(naive(naive_run(samples=chase)), "naive.alignment")["status"], "PASS")

    def test_no_record_on_a_naive_viewport_is_unmeasured_and_other_viewports_are_not_judged(self):
        checks = realism.judge({}, D3, RULES, "desktop", MVP)
        self.assertEqual(sorted(c["id"] for c in checks if c["id"].startswith("naive.")),
                         ["naive.alignment", "naive.drift", "naive.pace", "naive.setbacks",
                          "naive.unit_duration"])
        self.assertTrue(all(c["status"] == "WARNING" for c in checks))
        mobile = realism.judge({"naive": {"applies": False}}, D3, RULES, "mobile", MVP)
        self.assertEqual([c for c in mobile if c["id"].startswith("naive.")], [])

    def test_units_the_naive_play_samples_beside_the_opening(self):
        units = [{"id": f"u{i}", "index": i} for i in range(1, 13)]
        self.assertEqual(realism.naive_units(units, 3), ["u7", "u12"])
        self.assertEqual(realism.naive_units(units[:1], 3), [])
        self.assertEqual(realism.naive_units(units, 1), [])


class ClearRate(unittest.TestCase):
    def runs(self, unit, won, n, policy="jitter"):
        return [naive_run(policy, unit, asked=unit, won=i < won, clear_ms=30000 if i < won else None)
                for i in range(n)]

    def judge(self, runs, accepted, strength=RELEASE):
        return check(realism.judge(naive(*runs), D2, RULES, "desktop", strength, (), accepted),
                     "naive.clear_rate")

    def test_without_an_accepted_build_the_rates_are_reported_never_passed_never_held(self):
        result = self.judge(self.runs("a", 3, 6), None, strength=HELD)
        self.assertEqual(result["status"], "WARNING")
        self.assertFalse(result["required"])
        self.assertEqual(result["measured"]["rates"], {"a": {"jitter": {"won": 3, "n": 6}}})

    def test_a_significant_drop_fails_and_a_small_one_passes(self):
        accepted = {"units": {"a": {"jitter": {"won": 6, "n": 6}}, "b": {"jitter": {"won": 5, "n": 6}}}}
        result = self.judge(self.runs("a", 0, 6) + self.runs("b", 4, 6), accepted)
        self.assertEqual(result["status"], "FAIL", result)
        self.assertEqual([c["unit"] for c in result["measured"]["compared"] if c["regressed"]], ["a"])
        self.assertEqual(self.judge(self.runs("a", 5, 6), accepted)["status"], "PASS")

    def test_too_few_runs_on_either_side_is_unmeasured(self):
        accepted = {"units": {"a": {"jitter": {"won": 6, "n": 6}}}}
        result = self.judge(self.runs("a", 0, 2), accepted, strength=HELD)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)

    def test_an_accepted_naive_record_is_read_like_a_table(self):
        accepted = naive(*self.runs("a", 6, 6))["naive"]
        self.assertEqual(self.judge(self.runs("a", 0, 6), accepted)["status"], "FAIL")


def content(units, **top):
    data = {"schema": "wgf-content/1", "units": units}
    data.update(top)
    return data


HEAD_CIRCUIT = {"width": 8, "segments": [
    {"t": "line", "len": 14}, {"t": "turn", "deg": 180, "r": 6.684, "rails": "outside"},
    {"t": "line", "len": 14}, {"t": "turn", "deg": 180, "r": 6.684, "rails": "outside"}]}
R1_HAIRPINS = {"width": 5.5, "top_speed": 16, "par_s": 31, "segments": [
    {"t": "line", "len": 120}, {"t": "turn", "deg": 170, "r": 11},
    {"t": "turn", "deg": -170, "r": 11}, {"t": "line", "len": 120}]}


class LevelGeometry(unittest.TestCase):
    def judge(self, data, strength=RELEASE, source=None, units=()):
        return {c["id"]: c for c in realism.judge_layouts(data, RULES, strength, source, units)}

    def test_hairpins_tighter_than_the_width_fail(self):
        result = self.judge(content([{"id": "c", "layout": HEAD_CIRCUIT}]))["level.geometry"]
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["measured"]["failing"][0]["radius_to_width"], 0.84)

    def test_open_hairpins_twice_the_width_pass(self):
        checks = self.judge(content([{"id": "9", "layout": R1_HAIRPINS}]))
        self.assertEqual(checks["level.geometry"]["status"], "PASS")
        self.assertEqual(checks["level.unit_length"]["status"], "PASS", checks["level.unit_length"])

    def test_a_tight_bend_needs_a_railed_inner_edge(self):
        bend = {"width": 9, "segments": [{"t": "line", "len": 200}, {"t": "turn", "deg": 130, "r": 11}]}
        self.assertEqual(self.judge(content([{"id": "g", "layout": bend}]))["level.geometry"]["status"], "FAIL")
        railed = copy.deepcopy(bend)
        railed["segments"][1]["rails"] = True
        self.assertEqual(self.judge(content([{"id": "g", "layout": railed}]))["level.geometry"]["status"], "PASS")

    def test_the_layout_source_is_read_like_a_units_own_layout(self):
        result = self.judge(content([{"id": "c"}]), source={"c": HEAD_CIRCUIT})["level.geometry"]
        self.assertEqual(result["status"], "FAIL")

    def test_the_top_speed_may_be_a_path_into_the_data_file(self):
        course = {"width": 5, "segments": [{"t": "line", "len": 100}]}
        none = self.judge(content([{"id": "c", "layout": course}]), strength=HELD)["level.unit_length"]
        self.assertEqual(none["status"], "FAIL")
        self.assertEqual(none["measured"]["unmeasured"], realism.UNREPORTED)
        declared = content([{"id": "c", "layout": course}], tuning={"move": {"max": 10}},
                           play_geometry={"top_speed": "tuning.move.max"})
        self.assertEqual(self.judge(declared)["level.unit_length"]["status"], "FAIL")  # 10 s < 12
        self.assertEqual(self.judge(declared, strength=MVP)["level.unit_length"]["status"], "PASS")

    def test_no_content_file_or_no_path_layout_is_not_judged(self):
        self.assertEqual(realism.judge_layouts(None, RULES, RELEASE), [])
        self.assertEqual(self.judge(content([{"id": "a", "layout": {"waves": [1, 2]}}])), {})

    def test_length_counts_lines_arcs_and_jumps(self):
        layout = {"segments": [{"t": "line", "len": 10}, {"t": "turn", "deg": 180, "r": 1},
                               {"t": "jump", "gap": 2}]}
        self.assertAlmostEqual(realism.layout_length(layout), 12 + 3.14159, places=3)


GRID = {"grid": {"key": "rows", "cell": [72, 32], "solid": "S"}, "body": {"radius": 11}}


class Clearance(unittest.TestCase):
    def judge(self, data, strength=RELEASE):
        return check(realism.judge_layouts(data, RULES, strength), "level.clearance")

    def test_a_one_cell_gap_threads_a_small_body_and_not_a_large_one(self):
        units = [{"id": "w", "layout": {"rows": ["#########", "SS.S.S.SS", "#########"]}}]
        self.assertEqual(self.judge(content(units, play_geometry=GRID))["status"], "PASS")
        large = copy.deepcopy(GRID)
        large["body"] = {"radius": 20}
        result = self.judge(content(units, play_geometry=large))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["measured"]["failing"][0]["widest_to_body"], 1.8)

    def test_a_wide_lane_anywhere_in_the_row_is_enough(self):
        large = copy.deepcopy(GRID)
        large["body"] = {"diameter": 40}
        units = [{"id": "w", "layout": {"rows": ["SS.....SS", "#########"]}}]
        self.assertEqual(self.judge(content(units, play_geometry=large))["status"], "PASS")

    def test_a_passage_narrower_than_the_body_is_closed(self):
        tiny = {"grid": {"key": "rows", "cell": [10, 10], "solid": "S"}, "body": {"diameter": 15}}
        units = [{"id": "w", "layout": {"rows": ["S.SS..S", "#######"]}}]
        result = self.judge(content(units, play_geometry=tiny))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["measured"]["closed"][0]["closed_passages"], 1)

    def test_a_grid_without_a_declaration_is_unmeasured_and_not_held(self):
        # Undeclared, a grid is a guess from the data's shape: never a pass, never a blocker.
        units = [{"id": "w", "layout": {"rows": ["S.S.S", "#####"]}}]
        result = self.judge(content(units), strength=HELD)
        self.assertEqual(result["status"], "WARNING")
        self.assertFalse(result["required"])
        self.assertIn("play_geometry.grid", result["summary"])
        # A declared grid missing its body is the build's own contract: held.
        partial = {"grid": {"key": "rows", "cell": [10, 10], "solid": "S"}}
        held = self.judge(content(units, play_geometry=partial), strength=HELD)
        self.assertEqual(held["status"], "FAIL")
        self.assertIn("body", held["summary"])

    def test_values_may_be_paths_into_the_data_file(self):
        units = [{"id": "w", "layout": {"rows": ["SS.S.S.SS", "#########"]}}]
        declared = {"grid": {"key": "rows", "cell": ["tuning.b.w", 32], "solid": "S"},
                    "body": {"radius": "tuning.ball.r"}}
        data = content(units, play_geometry=declared, tuning={"b": {"w": 72}, "ball": {"r": 20}})
        self.assertEqual(self.judge(data)["status"], "FAIL")


class ClearanceGate(unittest.TestCase):
    """level.clearance is a proxy: it blocks a unit only where its clear rate against the
    accepted build was not measured."""

    def checks(self, compared, strength=RELEASE):
        units = [{"id": "a", "layout": {"rows": ["SS.S.S.SS", "#########"]}},
                 {"id": "b", "layout": {"rows": ["S.S.S.S.S", "#########"]}}]
        large = {"grid": {"key": "rows", "cell": [72, 32], "solid": "S"}, "body": {"radius": 20}}
        out = realism.judge_layouts(content(units, play_geometry=large), RULES, strength)
        out.append({"id": "naive.clear_rate", "project": "desktop", "status": "PASS",
                    "required": True, "summary": "", "measured": {"compared": compared}})
        return realism.gate_clearance(out, strength)

    def test_unmeasured_clear_rate_leaves_the_clearance_blocking(self):
        result = check(self.checks([]), "level.clearance")
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["required"])
        self.assertEqual(result["measured"]["gate"], {"a": "quality-gate", "b": "quality-gate"})

    def test_a_passing_clear_rate_makes_the_clearance_advisory_unit_by_unit(self):
        result = check(self.checks([{"unit": "a", "regressed": False}]), "level.clearance")
        self.assertEqual(result["measured"]["gate"], {"a": "advisory", "b": "quality-gate"})
        self.assertTrue(result["required"])
        both = check(self.checks([{"unit": "a", "regressed": False},
                                  {"unit": "b", "regressed": False}]), "level.clearance")
        self.assertEqual(both["status"], "WARNING")
        self.assertFalse(both["required"])

    def test_a_failing_clear_rate_is_what_blocks_and_both_are_reported(self):
        result = check(self.checks([{"unit": "a", "regressed": True},
                                    {"unit": "b", "regressed": False}]), "level.clearance")
        self.assertEqual(result["status"], "WARNING")
        self.assertEqual(result["measured"]["gate"]["a"], "clear-rate-failed")
        self.assertIn("also fail naive.clear_rate", result["summary"])

    def test_below_the_release_tier_nothing_blocks(self):
        result = check(self.checks([], strength=MVP), "level.clearance")
        self.assertEqual(result["status"], "WARNING")
        self.assertFalse(result["required"])


class Runtime(unittest.TestCase):
    def judge(self, records, strength=RELEASE):
        return {c["id"]: c for c in realism.judge_runtime(records, RULES, "desktop", strength)}

    def test_an_error_from_the_games_origin_fails_and_network_refusals_are_not_counted(self):
        records = {"win": {"console": {"errors": [
            {"text": "Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED", "url": "", "same_origin": True},
            {"text": "ad sdk script", "url": "https://sdk.example/x.js", "same_origin": False}],
            "webgl_lost": 0}}}
        checks = self.judge(records)
        self.assertEqual(checks["runtime.console_errors"]["status"], "PASS")
        self.assertEqual(checks["runtime.console_errors"]["measured"]["ignored_network"], 1)
        records["act"] = {"console": {"errors": [{"text": "TypeError: x is undefined", "url": "/assets/index.js",
                                                  "same_origin": True}], "webgl_lost": 0}}
        failed = self.judge(records)["runtime.console_errors"]
        self.assertEqual(failed["status"], "FAIL")
        self.assertTrue(failed["required"])
        self.assertEqual(self.judge(records, strength=MVP)["runtime.console_errors"]["status"], "WARNING")

    def test_a_lost_webgl_context_fails(self):
        checks = self.judge({"win": {"console": {"errors": [], "webgl_lost": 1}}})
        self.assertEqual(checks["runtime.webgl_context"]["status"], "FAIL")

    def test_records_without_a_console_are_unmeasured(self):
        checks = self.judge({"win": {"errors": []}}, strength=HELD)
        self.assertEqual(checks["runtime.console_errors"]["status"], "FAIL")
        self.assertEqual(checks["runtime.console_errors"]["measured"]["unmeasured"], realism.UNREPORTED)


# -- the real evidence --------------------------------------------------------------------------

class RealEvidence(unittest.TestCase):
    """The two 2026-10 games. Regressed builds FAIL, accepted / r1-forward builds PASS."""

    def physics(self, record, project, strength=RELEASE):
        return check(realism.judge({"win": record}, D2, RULES, project, strength), "physics.undrawn_collision")

    def test_L11_the_regressed_2d_head_turns_at_an_undrawn_ceiling(self):
        visits = real("physics-2d-head-run.json.gz")["visits"]
        head = visits["10-1"]
        self.assertEqual(head["commit"], "68a12b7")
        statuses = {p: self.physics(r, p)["status"] for p, r in head["projects"].items()}
        self.assertIn("FAIL", statuses.values(), statuses)
        failed = self.physics(head["projects"]["mobile"], "mobile")
        self.assertTrue(failed["required"])
        self.assertEqual(failed["measured"]["unexplained"][0]["moving"], "-y")
        self.assertGreater(failed["measured"]["unexplained"][0]["gap_ahead_px"], 200)
        # Across the regressed run: 8 failing viewports of 20.
        fails = sum(1 for v in visits.values() for p, r in v["projects"].items()
                    if self.physics(r, p)["status"] == "FAIL")
        self.assertEqual(fails, 8)

    def test_L11_the_accepted_2d_build_never_turns_at_nothing(self):
        visits = real("physics-2d-r1-run.json.gz")["visits"]
        self.assertEqual(visits["17-1"]["commit"], "96f5cea")
        for name, visit in visits.items():
            for project, record in visit["projects"].items():
                result = self.physics(record, project)
                self.assertNotEqual(result["status"], "FAIL", (name, project, result["summary"]))
        self.assertEqual({p: self.physics(r, p)["status"]
                          for p, r in visits["17-1"]["projects"].items()},
                         {"desktop": "PASS", "mobile": "PASS"})

    def naive_record(self, key):
        entry = real("naive-bot-2026-10-05.json")["records"][key]
        return {"naive": {"applies": True, "input_kind": entry["input_kind"], "runs": entry["runs"]}}

    def test_L13_the_regressed_3d_head_is_cleared_by_holding_forward(self):
        for key in ("3d head 1c6b099, default sample", "3d head 1c6b099, the tight-bend units"):
            checks = {c["id"]: c for c in realism.judge(self.naive_record(key), D3, RULES, "desktop", RELEASE)}
            self.assertEqual(checks["naive.pace"]["status"], "FAIL", key)
            self.assertTrue(checks["naive.pace"]["required"])
            self.assertIn("meadow-roll", checks["naive.pace"]["measured"]["too_fast"])
            self.assertEqual(checks["naive.unit_duration"]["status"], "FAIL", key)

    def test_L13_the_accepted_builds_pass_naive_play(self):
        for key, design in (("3d r1 64ff4c6", D3), ("2d r1 96f5cea", D2)):
            checks = {c["id"]: c for c in realism.judge(self.naive_record(key), design, RULES, "desktop", RELEASE)}
            for cid in ("naive.pace", "naive.unit_duration"):
                self.assertEqual(checks[cid]["status"], "PASS", (key, cid, checks[cid]["summary"]))
            self.assertNotIn("FAIL", {c["status"] for c in checks.values()}, key)

    def test_L13_the_3d_r1_forward_build_passes_under_the_r1_harness(self):
        record = real("naive-harness-3d-c340631.json")
        checks = {c["id"]: c for c in realism.judge({"naive": record}, D3, RULES, "desktop", RELEASE)}
        self.assertEqual(checks["naive.setbacks"]["status"], "PASS")
        self.assertEqual(checks["naive.setbacks"]["measured"]["per_min"], 4.55)
        self.assertEqual(checks["naive.drift"]["status"], "PASS")
        self.assertAlmostEqual(checks["naive.drift"]["measured"]["mean_share"], 0.633, places=3)
        self.assertEqual(checks["naive.pace"]["status"], "PASS")
        self.assertEqual(checks["naive.unit_duration"]["status"], "PASS")
        # Later courses are hard for naive play by design; their falls are reported, not judged.
        self.assertGreater(checks["naive.setbacks"]["measured"]["units"]["the-summit"]["per_min"], 6)
        # Against itself (r1-forward plays r1's courses unchanged) no unit regresses.
        rates = realism.clear_rates(record["runs"])
        self.assertFalse(any(c["regressed"] for c in realism.compare_clear_rates(
            rates, rates, {"min_runs": 1, "min_drop": 0.15, "min_z": 2.33})))

    def bot_record(self, commit):
        return real(f"naive-bot-3d-{commit}.json")["record"]

    def judged(self, commit, strength):
        record = self.bot_record(commit)
        rules = load_file(os.path.join(paths.REFERENCE, "visual-quality.yaml"))
        units = [{"id": u["id"], "parameters": u.get("parameters") or {}}
                 for u in real(f"content-3d-{commit}.json")["units"]]
        checks = realism.judge({"naive": record}, D3, RULES, "desktop", strength, units)
        return {c["id"]: c for c in analysis._environment(checks, {"naive": record},
                                                          rules.get("environment") or {}, {})}

    def test_L13_this_bot_fails_the_regressed_3d_head_and_passes_r1_forward(self):
        # This branch's bot, run on each build's dist/ on a healthy host (2026-10-07).
        head = self.judged("1c6b099", RELEASE)
        self.assertEqual(head["naive.pace"]["status"], "FAIL")
        self.assertEqual(head["naive.pace"]["measured"]["too_fast"][0], "meadow-roll")
        self.assertEqual(head["naive.unit_duration"]["status"], "FAIL")
        forward = self.judged("c340631", RELEASE)
        self.assertEqual(forward["naive.pace"]["status"], "PASS")
        self.assertEqual(forward["naive.unit_duration"]["status"], "PASS")
        for checks in (head, forward):
            self.assertEqual(checks["runtime.console_errors"]["status"], "PASS")
            self.assertEqual(checks["runtime.webgl_context"]["status"], "PASS")
            # The refused portal SDK is a foreign request, recorded and never counted.
            self.assertGreater(checks["runtime.console_errors"]["measured"]["foreign"], 0)
        # Neither probe reports setbacks, track or view: unmeasured, never passed.
        held = self.judged("c340631", HELD)
        for cid in ("naive.setbacks", "naive.drift", "naive.alignment"):
            self.assertEqual(held[cid]["status"], "FAIL", cid)
            self.assertEqual(held[cid]["measured"]["unmeasured"], realism.UNREPORTED)

    def test_L14_the_regressed_3d_courses_are_too_tight_and_too_short(self):
        data, source = real("content-3d-1c6b099.json"), real("layouts-3d-1c6b099.json")["layouts"]
        checks = {c["id"]: c for c in realism.judge_layouts(data, RULES, RELEASE, source)}
        self.assertEqual(checks["level.geometry"]["status"], "FAIL")
        ratios = sorted(b["radius_to_width"] for b in checks["level.geometry"]["measured"]["failing"])
        self.assertEqual(ratios[0], 0.84)
        self.assertEqual(checks["level.unit_length"]["status"], "FAIL")
        self.assertEqual(len(checks["level.unit_length"]["measured"]["short"]), 12)

    def test_L14_the_3d_r1_forward_courses_pass(self):
        data = real("content-3d-c340631.json")
        checks = {c["id"]: c for c in realism.judge_layouts(data, RULES, RELEASE)}
        self.assertEqual(checks["level.geometry"]["status"], "PASS")
        self.assertEqual(checks["level.geometry"]["measured"]["bends"], 45)
        # As shipped it states no top speed: its crossing time is unmeasured, never passed.
        self.assertEqual(checks["level.unit_length"]["measured"]["unmeasured"], realism.UNREPORTED)
        declared = dict(data, play_geometry={"top_speed": "tuning.steering.max_speed"})
        checks = {c["id"]: c for c in realism.judge_layouts(declared, RULES, RELEASE)}
        self.assertEqual(checks["level.unit_length"]["status"], "PASS", checks["level.unit_length"])
        units = checks["level.unit_length"]["measured"]["units"]
        self.assertEqual(min(u["traverse_to_par"] for u in units), 0.66)
        self.assertEqual(min(u["length_to_width"] for u in units), 29.3)

    def grid(self, commit):
        # The declaration the build's own tuning makes (its units.json declares none yet).
        data = real(f"content-2d-{commit}.json")
        return dict(data, play_geometry={
            "grid": {"key": "rows", "solid": "S",
                     "cell": ["tuning.bricks.brick_width_px", "tuning.bricks.brick_height_px"]},
            "body": {"radius": "tuning.ball-rebound.ball_radius_px"}})

    def test_M1_the_r20_collider_cannot_thread_the_steel_gaps(self):
        result = check(realism.judge_layouts(self.grid("894b4b8"), RULES, RELEASE), "level.clearance")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(sorted({f["unit"] for f in result["measured"]["failing"]}), ["w3-l7", "w4-l7"])
        accepted = check(realism.judge_layouts(self.grid("96f5cea"), RULES, RELEASE), "level.clearance")
        self.assertEqual(accepted["status"], "PASS")
        self.assertEqual(accepted["measured"]["passage_share_min"], 0.231)
        # As shipped, neither declares its grid: unmeasured, never passed (not held: the
        # grid is only read from the data's shape until the build declares it).
        shipped = check(realism.judge_layouts(real("content-2d-894b4b8.json"), RULES, HELD), "level.clearance")
        self.assertEqual(shipped["status"], "WARNING")
        self.assertEqual(shipped["measured"]["unmeasured"], realism.UNREPORTED)

    def table(self, entry):
        return {u: {"nudge": c} for u, c in entry["levels"].items()}

    def test_M1_the_steel_levels_clear_less_often_than_on_the_accepted_build(self):
        rates = real("clear-rates-2d.json")
        bars = RULES["clear_rate"]
        compared = realism.compare_clear_rates(self.table(rates["focus-nudge-new"]),
                                               self.table(rates["focus-nudge-r1"]), bars)
        self.assertEqual(sorted(c["unit"] for c in compared if c["regressed"]),
                         ["w3-l2", "w3-l7", "w4-l6", "w4-l7"])
        full = realism.compare_clear_rates(self.table(rates["full-nudge-new"]),
                                           self.table(rates["full-nudge-r1"]), bars)
        self.assertEqual(sorted(c["unit"] for c in full if c["regressed"]), ["w3-l2", "w4-l6", "w4-l7"])
        # The same code at the accepted collider: nothing regresses - the collider is the cause.
        control = realism.compare_clear_rates(self.table(rates["full-nudge-new11"]),
                                              self.table(rates["full-nudge-r1"]), bars)
        self.assertEqual([c for c in control if c["regressed"]], [])
        self.assertEqual(len(control), 32)

    def steel(self, variant, units=("w3-l7", "w4-l7")):
        """naive.clear_rate of one steel-gaps variant against the r1 reference, every model."""
        levels = real("clear-rates-2d-steel-gaps.json")["levels"]
        current = {u: levels[u][variant] for u in units}
        accepted = {u: levels[u]["r1_ref11"] for u in units}
        runs = [naive_run(model, u, asked=u, won=i < cell["won"])
                for u, cells in current.items() for model, cell in cells.items()
                for i in range(cell["n"])]
        return check(realism.judge(naive(*runs), D2, RULES, "desktop", RELEASE, (),
                                   {"units": accepted}), "naive.clear_rate")

    def gated(self, commit, variant):
        layout = realism.judge_layouts(self.grid(commit), RULES, RELEASE)
        return {c["id"]: c for c in realism.gate_clearance(layout + [self.steel(variant)], RELEASE)}

    def test_M1_the_steel_gaps_fix_is_advisory_on_clearance_at_r1_clear_rate(self):
        # fix/steel-gaps (03f88ad) keeps w3-l7's one-cell steel lanes (1.8 x a 40 px ball) and
        # brought its clear rate back to r1's: the proxy is advisory, nothing blocks.
        checks = self.gated("03f88ad", "fixed")
        self.assertEqual(checks["naive.clear_rate"]["status"], "PASS", checks["naive.clear_rate"]["summary"])
        clearance = checks["level.clearance"]
        self.assertEqual(clearance["measured"]["gate"]["w3-l7"], "advisory")
        self.assertIn(1.8, [f["widest_to_body"] for f in clearance["measured"]["failing"]
                            if f["unit"] == "w3-l7"])
        self.assertEqual(clearance["status"], "WARNING")
        self.assertFalse(clearance["required"])

    def test_M1_894b4b8_is_blocked_by_its_clear_rate(self):
        checks = self.gated("894b4b8", "main_894b4b8")
        self.assertEqual(checks["naive.clear_rate"]["status"], "FAIL")
        self.assertTrue(checks["naive.clear_rate"]["required"])
        regressed = {c["unit"] for c in checks["naive.clear_rate"]["measured"]["compared"] if c["regressed"]}
        self.assertIn("w4-l7", regressed)
        self.assertEqual(checks["level.clearance"]["measured"]["gate"]["w4-l7"], "clear-rate-failed")
        # Without the clear rate, the same clearance finding blocks on its own.
        alone = check(realism.gate_clearance(realism.judge_layouts(self.grid("894b4b8"), RULES, RELEASE),
                                             RELEASE), "level.clearance")
        self.assertEqual(alone["status"], "FAIL")
        self.assertTrue(alone["required"])

    def test_M1_a_steel_gap_variant_that_restores_the_clear_rate_passes(self):
        rates = real("clear-rates-2d.json")
        accepted = self.table(rates["focus-nudge-r1"])
        outcome = {}
        for name, clears in rates["variants2"].items():
            unit = name.split()[0]
            current = {unit: {"nudge": {"won": clears["won"], "n": clears["n"]}}}
            outcome[name] = realism.compare_clear_rates(current, accepted, RULES["clear_rate"])[0]["regressed"]
        self.assertFalse(outcome["w4-l7 E r20 row1 XS..S..SX only"])
        self.assertTrue(outcome["w4-l7 F r20 row1 XSS...SSX only"])
        self.assertFalse(outcome["w4-l6 r11 as is"])
        self.assertTrue(outcome["w4-l6 r20 as is"])


class TheContract(unittest.TestCase):
    def test_the_bars_are_versioned_data(self):
        data = load_file(os.path.join(paths.REFERENCE, "play-realism.yaml"))
        self.assertTrue(data["version"])
        for section in ("enforce", "physics", "naive", "clear_rate", "geometry", "clearance",
                        "runtime", "risk"):
            self.assertIn(section, data)
        self.assertEqual(data["enforce"]["fail_required_at"], ["release", "premium"])
        self.assertEqual(data["naive"]["policies"]["held"], ["steady", "jitter"])

    def test_the_probe_takes_the_realism_fields_and_old_snapshots_still_validate(self):
        with open(os.path.join(paths.ARTIFACTS, "shared", "play-probe.schema.json"), encoding="utf-8") as h:
            validator = jsonschema_lite.Validator(json.load(h))
        old = {"state": "playing", "metrics": {}, "inputs": [],
               "entities": [{"id": "b", "role": "projectile", "x": 1, "y": 1, "w": 2, "h": 2, "visible": True}]}
        self.assertEqual(list(validator.iter_errors(old)), [])
        new = copy.deepcopy(old)
        new["entities"][0]["collider"] = {"shape": "circle", "x": 1.5, "y": 1.5, "w": 1, "h": 1}
        new.update(playfield={"x": 0, "y": 0, "w": 100, "h": 100}, setbacks=2,
                   track={"offset": -0.5, "half_width": 4},
                   view={"camera_forward": [0, -1], "control_forward": [0, -1]})
        self.assertEqual(list(validator.iter_errors(new)), [])
        bad = copy.deepcopy(new)
        bad["entities"][0]["collider"]["shape"] = "blob"
        self.assertTrue(list(validator.iter_errors(bad)))

    def test_the_checks_route_to_their_owners(self):
        table = load_file(os.path.join(paths.REFERENCE, "specialist-routing.yaml"))
        checks = table["producers"]["playability-report"]["checks"]
        self.assertEqual(checks["physics."], "gameplay")
        self.assertEqual(checks["naive."], "difficulty")
        self.assertEqual(checks["naive.alignment"], "gameplay")
        self.assertEqual(checks["level."], "level-design")
        self.assertEqual(checks["naive.pace"], "level-design")
        self.assertEqual(checks["naive.unit_duration"], "level-design")
        # A console error is browser QA's, as a page error is; a lost context performance's.
        self.assertEqual(checks["runtime."], "browser")
        self.assertEqual(checks["runtime.webgl_context"], "performance")

    def test_a_degraded_host_re_records_naive_play(self):
        self.assertIn("naive", analysis.RETRIED_RECORDS)
        for cid in ("physics.undrawn_collision", "naive.pace", "naive.clear_rate"):
            self.assertIn(cid, analysis.EVIDENCE)
        self.assertIn("naive", RECORDS)
        self.assertIn("risk", RECORDS)

    def test_the_bot_records_colliders_playfields_naive_play_risk_and_the_console(self):
        with open(os.path.join(SCRIPTS, "wgf_playability", "bot.spec.ts"), encoding="utf-8") as h:
            bot = h.read()
        self.assertIn('test("naive: the build played by someone who is not perfect"', bot)
        self.assertIn('"naive: the build played by someone who is not perfect": "naive"', bot)
        self.assertIn("e.collider ?", bot)
        self.assertIn("e.body ?", bot)
        self.assertIn("playfields", bot)
        self.assertIn('await finish(page, info, "naive"', bot)
        self.assertIn('test("risk: the oracle', bot)
        self.assertIn('page.on("console"', bot)
        self.assertIn("webglcontextlost", bot)
        self.assertIn("addInitScript(installContextWatch)", bot)


class Viewports(unittest.TestCase):
    def test_the_viewports_are_data(self):
        from wgf_playability import step
        data = load_file(os.path.join(paths.REFERENCE, "visual-quality.yaml"))
        listed = [(v["id"], v["width"], v["height"]) for v in data["viewports"]]
        self.assertEqual(list(step.PROJECTS), listed)
        config = step.projects_config()
        for vid, width, height in listed:
            self.assertIn(f'name: "{vid}"', config)
            self.assertIn(f"width: {width}, height: {height}", config)
        self.assertIn('devices["Pixel 5"]', config)
        rendered = step.CONFIG.format(port=1, proxy_var="X", bypass="", retries=0).replace(
            "__WGF_PROJECTS__", config)
        self.assertIn('devices["Desktop Chrome"]', rendered)


class TheStep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    DESIGN = {"build_spec": {"content": {"unit_kind": "level", "generation": {"mode": "authored"},
                                         "units": [{"id": f"u{i}", "index": i, "tier": "mvp"}
                                                   for i in range(1, 7)]}}}

    def test_the_naive_settings_and_their_window(self):
        settings = PlayabilityStep._naive_settings(self.DESIGN, RULES, ["mvp"])
        self.assertEqual(settings["naive_projects"], ["desktop"])
        self.assertEqual(settings["naive_run_ms"], RULES["naive"]["run_s"] * 1000)
        self.assertEqual(len(settings["naive_units"]), RULES["naive"]["units"] - 1)
        self.assertEqual(settings["naive_repeats"], 1)
        settings.update(PlayabilityStep._risk_settings(self.DESIGN, RULES, {}, ["mvp"]))
        settings["start_timeout_ms"] = 30000
        window = PlayabilityStep._realism_window_s(settings)
        self.assertEqual(window, 1 * RULES["naive"]["units"] * 2 * (RULES["naive"]["run_s"] + 30 + 5))
        # Compared with an accepted build, every unit is played `clear_rate.runs` times.
        compared = PlayabilityStep._naive_settings(self.DESIGN, RULES, ["mvp"], compare=True)
        self.assertEqual(compared["naive_repeats"], RULES["clear_rate"]["runs"])

    def test_the_risk_test_is_asked_for_only_with_risk(self):
        self.assertEqual(PlayabilityStep._risk_settings(self.DESIGN, RULES, {}, ["mvp"])["risk_units"], [])
        asked = PlayabilityStep._risk_settings(self.DESIGN, RULES, {"risk": True}, ["mvp"])
        self.assertEqual(asked["risk_units"][0], "u1")
        self.assertEqual(len(asked["risk_units"]), RULES["risk"]["units"])
        self.assertEqual(asked["risk_policies"], ["safe", "greedy"])

    def test_the_layout_checks_read_the_kept_content_file_and_its_layout_source(self):
        repo, out = os.path.join(self.tmp, "repo"), os.path.join(self.tmp, "out")
        os.makedirs(os.path.join(repo, "public", "content"))
        with open(os.path.join(repo, "public", "content", "units.json"), "w", encoding="utf-8") as h:
            json.dump(real("content-3d-1c6b099.json"), h)
        with open(os.path.join(repo, "public", "content", "layouts.json"), "w", encoding="utf-8") as h:
            json.dump(real("layouts-3d-1c6b099.json"), h)
        PlayabilityStep._keep_content_data(repo, out)
        self.assertTrue(os.path.isfile(os.path.join(out, CONTENT_COPY)))
        checks = {c["id"]: c for c in PlayabilityStep._layout_checks(out, {}, RULES, RELEASE)}
        self.assertEqual(checks["level.geometry"]["status"], "FAIL")
        self.assertEqual(PlayabilityStep._layout_checks(os.path.join(self.tmp, "none"), {}, RULES, RELEASE), [])

    def test_an_accepted_play_file_is_read_or_the_step_says_why_not(self):
        path = os.path.join(self.tmp, "accepted.json")
        with open(path, "w", encoding="utf-8") as h:
            json.dump({"units": {"a": {"jitter": {"won": 6, "n": 6}}}}, h)
        data, error = PlayabilityStep._accepted_play({"accepted_play": path})
        self.assertIsNone(error)
        self.assertEqual(data["units"]["a"]["jitter"]["n"], 6)
        self.assertEqual(PlayabilityStep._accepted_play({}), (None, None))
        missing, why = PlayabilityStep._accepted_play({"accepted_play": os.path.join(self.tmp, "x.json")})
        self.assertIsNone(missing)
        self.assertIn("cannot be read", why)

    def test_a_degraded_naive_recording_blocks_a_failure_instead_of_softening_it(self):
        health = {"bot": {"max_lag_ms": 9000, "stalled_ms": 9000, "elapsed_ms": 20000}}
        rules = load_file(os.path.join(paths.REFERENCE, "visual-quality.yaml"))
        records = naive(naive_run("steady", "u1", won=True, clear_ms=3000, played_ms=3000, par_s=30))
        records["naive"]["health"] = health
        records["naive"]["attempts"] = [{"attempt": 1, "health": health}]
        checks = analysis._environment(realism.judge(records, D3, RULES, "desktop", RELEASE),
                                       records, rules.get("environment") or {}, {})
        pace = check(checks, "naive.pace")
        self.assertEqual(pace["status"], "BLOCKED")
        self.assertEqual(pace["measured"]["unmeasured"], analysis.ENVIRONMENT_DEGRADED)


if __name__ == "__main__":
    unittest.main()
