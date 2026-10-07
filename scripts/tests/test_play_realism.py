"""Play realism (scripts/wgf_playability/realism.py): the build's physics against what it draws,
naive play, and the level geometry it declares - each check on a passing and a failing fixture.

The fixtures are the shapes the 2026-10 validation builds had (factory-learning-ledger L11, L13,
L14): a ball that turned 248 px short of anything drawn (an undrawn ceiling), a ball drawn twice
the size of its body, an opening course cleared by holding forward in a fifth of its par, an
off-axis camera, and 180-degree bends of 0.84 x the width railed outside only - beside the
accepted builds' shapes, which pass.

    python -m unittest scripts.tests.test_play_realism
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_playability import realism  # noqa: E402
from wgf_playability.step import LAYOUTS_COPY, PlayabilityStep  # noqa: E402
from wgflib import jsonschema_lite, paths  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

RULES = realism.load_rules()
D2 = {"engine": {"dimension": "2d"}}
D3 = {"engine": {"dimension": "3d"}}

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
    def judge(self, records, design=D2, tier="mvp", rules=RULES):
        return check(realism.judge(records, design, rules, "desktop", tier), "physics.undrawn_collision")

    def test_a_ball_turning_at_the_paddle_and_the_bricks_passes(self):
        # Up from the paddle to the brick row's underside (y 120, ball radius 10), and back.
        points = line((640, 550), (660, 130), 20)[:-1] + line((660, 130), (680, 550), 20)
        result = self.judge(win(path(points)))
        self.assertEqual(result["status"], "PASS", result)
        self.assertGreaterEqual(result["measured"]["turns"], 1)

    def test_a_ball_turning_short_of_anything_drawn_fails(self):
        # The 2D validation build (68a12b7): up from the paddle, turned at y 377 with the drawn
        # brick row already behind it and the HUD bar 248 px above - an undrawn ceiling.
        bricks_low = ["bricks", "target", 1, 440, 403, 400, 17, "brick", "composite", None]
        points = line((700, 550), (707, 377), 12)[:-1] + line((707, 377), (720, 550), 12)
        hud = ["bar", "goal", 1, 553, 103, 173, 14, None, "composite", None]
        result = self.judge(win(path(points, extra=(PADDLE, bricks_low, hud))))
        self.assertEqual(result["status"], "FAIL", result)
        self.assertTrue(result["required"])
        first = result["measured"]["unexplained"][0]
        self.assertEqual(first["moving"], "-y")
        self.assertGreater(first["gap_ahead_px"], 200)

    def test_with_a_playfield_a_wall_bounce_passes_and_a_mid_board_turn_fails(self):
        to_wall = line((600, 300), (450, 250), 10)[:-1] + line((450, 250), (600, 200), 10)
        frames = path(to_wall, extra=(PADDLE,))
        self.assertEqual(self.judge(win(frames, [PLAYFIELD] * len(frames)))["status"], "PASS")
        short = line((600, 300), (520, 250), 10)[:-1] + line((520, 250), (600, 200), 10)
        frames = path(short, extra=(PADDLE,))
        result = self.judge(win(frames, [PLAYFIELD] * len(frames)))
        self.assertEqual(result["status"], "FAIL", result)
        self.assertTrue(result["measured"]["unexplained"][0]["playfield"])

    def test_without_a_playfield_a_wall_bounce_is_unmeasured_never_passed(self):
        to_wall = line((600, 300), (450, 250), 10)[:-1] + line((450, 250), (600, 200), 10)
        result = self.judge(win(path(to_wall, extra=(PADDLE,))))
        self.assertEqual(result["status"], "WARNING")
        self.assertFalse(result["required"])
        self.assertTrue(result["measured"]["unmeasured"])
        self.assertIn("no playfield", result["summary"])

    def test_the_tier_decides_what_unmeasured_is(self):
        rules = copy.deepcopy(RULES)
        rules["unmeasured"]["release"] = "fail"
        to_wall = line((600, 300), (450, 250), 10)[:-1] + line((450, 250), (600, 200), 10)
        result = self.judge(win(path(to_wall, extra=(PADDLE,))), tier="release", rules=rules)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(self.judge(win(path(to_wall, extra=(PADDLE,))), tier="mvp",
                                    rules=rules)["status"], "WARNING")

    def test_a_brick_the_hit_breaks_still_explains_the_turn(self):
        points = line((640, 550), (660, 130), 20)[:-1] + line((660, 130), (680, 550), 20)
        frames = path(points)
        turn = 20
        for f in frames[turn:]:
            f[:] = [e for e in f if e[0] != "bricks"]
        self.assertEqual(self.judge(win(frames))["status"], "PASS")

    def test_a_ball_carried_by_the_paddle_turns_with_it(self):
        frames = []
        for i, x in enumerate([600, 610, 620, 630, 620, 610, 600]):
            paddle = list(PADDLE)
            paddle[3] = x - 40
            frames.append([ball(x, 550), paddle])
        self.assertEqual(self.judge(win(frames))["status"], "PASS")

    def test_a_turn_on_both_axes_at_the_paddle_is_one_contact(self):
        points = [(600, 500), (610, 520), (620, 540), (610, 520), (600, 500)]
        frames = path(points, extra=(PADDLE,))
        self.assertEqual(self.judge(win(frames))["status"], "PASS")

    def test_a_3d_build_is_unmeasured_with_its_reason(self):
        points = line((640, 550), (660, 300), 10)[:-1] + line((660, 300), (680, 550), 10)
        result = self.judge(win(path(points)), design=D3)
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("projections", result["summary"])

    def test_no_sampled_frame_is_unmeasured(self):
        self.assertEqual(self.judge({"win": {}})["status"], "WARNING")

    def test_nothing_moving_of_a_judged_role_is_not_judged(self):
        frames = [[list(PADDLE), list(BRICKS)] for _ in range(10)]
        self.assertIsNone(self.judge(win(frames)))

    def test_a_composite_mover_is_no_bodys_path(self):
        bolts = [["bolts", "projectile", 1, 600, y, 60, h, None, "composite", None]
                 for y, h in ((400, 30), (350, 30), (300, 300), (420, 30))]
        frames = [[b, list(PADDLE)] for b in bolts]
        self.assertIsNone(self.judge(win(frames)))

    def test_turns_are_found_on_each_axis_and_stops(self):
        events = realism.turns(path([(500, 300), (510, 300), (520, 300), (510, 300)], extra=()),
                               {"projectile"}, RULES["physics"])
        self.assertEqual([(e["axis"], e["kind"]) for e in events], [(0, "reversal")])
        stopped = path([(500, 300), (510, 300), (520, 300)] + [(520, 300)] * 4, extra=())
        events = realism.turns(stopped, {"projectile"}, RULES["physics"])
        self.assertEqual([e["kind"] for e in events], ["stop"])
        # A respawn is a jump, not a turn.
        jumped = path([(500, 300), (510, 300), (900, 600), (890, 590)], extra=())
        self.assertEqual(realism.turns(jumped, {"projectile"}, RULES["physics"]), [])


class ColliderSize(unittest.TestCase):
    def judge(self, frames):
        return check(realism.judge(win(frames), D2, RULES, "desktop", "mvp"),
                     "physics.collider_size")

    def test_a_ball_drawn_twice_its_body_fails(self):
        # Drawn 24 px across, colliding 12 px across (the 2D validation build's 2.0x).
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
        frames = [[ball(600, 300 - 3 * i)] for i in range(5)]
        result = self.judge(frames)
        self.assertEqual(result["status"], "WARNING")
        self.assertTrue(result["measured"]["unmeasured"])


def naive_run(policy="jitter", unit="u1", **kw):
    run = {"policy": policy, "asked": None, "unit_id": unit, "entered": True,
           "played_ms": 25000, "won": False, "clear_ms": None, "losses": 0, "inputs": 30,
           "setbacks_first": None, "setbacks_last": None, "par_s": None, "samples": []}
    run.update(kw)
    return run


def naive(*runs):
    return {"naive": {"applies": True, "input_kind": "held", "runs": list(runs)}}


class NaivePlay(unittest.TestCase):
    def judge(self, records, cid, units=()):
        return check(realism.judge(records, D3, RULES, "desktop", "mvp", units), cid)

    # -- pace -----------------------------------------------------------------------------
    def test_a_course_held_forward_through_in_a_fifth_of_its_par_fails(self):
        # The 3D validation build (1c6b099): meadow-roll, par 24 s, cleared holding forward in
        # 9.1 s (the bot's steady policy), and its last course, par 50 s, in 19 s.
        records = naive(naive_run("steady", "meadow-roll", won=True, clear_ms=9099, played_ms=9099, par_s=24),
                        naive_run("steady", "storm-crown", won=True, clear_ms=19012, played_ms=19012, par_s=50))
        result = self.judge(records, "naive.pace")
        self.assertEqual(result["status"], "FAIL", result)
        self.assertEqual(result["measured"]["too_fast"], ["meadow-roll", "storm-crown"])

    def test_a_course_naive_play_has_not_crossed_after_half_its_par_passes_as_a_lower_bound(self):
        # The accepted 3D build (64ff4c6): course 1, par 18 s, still short of the end after 25 s.
        records = naive(naive_run("steady", "1", par_s=18), naive_run("jitter", "1", par_s=18))
        result = self.judge(records, "naive.pace")
        self.assertEqual(result["status"], "PASS", result)
        self.assertTrue(all(c["lower_bound"] for c in result["measured"]["cleared"]))

    def test_the_par_comes_from_the_design_when_the_probe_has_none(self):
        units = [{"id": "u1", "parameters": {"time_target": 30}}]
        records = naive(naive_run(won=True, clear_ms=6000, played_ms=6000))
        result = self.judge(records, "naive.pace", units)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["measured"]["cleared"][0]["par_from"], "design parameters.time_target")

    def test_no_par_anywhere_is_unmeasured(self):
        result = self.judge(naive(naive_run(won=True, clear_ms=6000, played_ms=6000)), "naive.pace")
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("par", result["summary"])

    # -- setbacks -------------------------------------------------------------------------
    def test_falling_every_few_seconds_fails(self):
        records = naive(naive_run(setbacks_first=0, setbacks_last=4, played_ms=30000))
        result = self.judge(records, "naive.setbacks")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["measured"]["per_min"], 8.0)

    def test_one_fall_in_a_short_sample_is_not_a_rate(self):
        records = naive(naive_run(setbacks_first=0, setbacks_last=1, played_ms=20000))
        result = self.judge(records, "naive.setbacks")
        self.assertEqual(result["status"], "PASS")
        self.assertIn("too few", result["summary"])

    def test_rare_falls_pass(self):
        records = naive(naive_run(setbacks_first=2, setbacks_last=3, played_ms=60000))
        self.assertEqual(self.judge(records, "naive.setbacks")["status"], "PASS")

    def test_without_setbacks_losses_are_a_lower_bound(self):
        few = self.judge(naive(naive_run(losses=1, played_ms=60000)), "naive.setbacks")
        self.assertEqual(few["status"], "WARNING")
        self.assertIn("no `setbacks`", few["summary"])
        many = self.judge(naive(naive_run(losses=5, played_ms=60000)), "naive.setbacks")
        self.assertEqual(many["status"], "FAIL")
        self.assertEqual(many["measured"]["source"], "losses")

    # -- drift and alignment --------------------------------------------------------------
    def samples(self, track=None, view=None, n=20):
        return [{"ms": i * 250, "state": "playing", "setbacks": 0,
                 "track": track(i) if track else None, "view": view(i) if view else None,
                 "progress": None} for i in range(n)]

    def test_drift_to_the_edge_fails_and_a_centred_run_passes(self):
        wide = self.samples(track=lambda i: {"offset": 3.8 if i % 2 else -3.9, "half_width": 4})
        self.assertEqual(self.judge(naive(naive_run(samples=wide)), "naive.drift")["status"], "FAIL")
        centred = self.samples(track=lambda i: {"offset": (i % 5 - 2) * 0.5, "half_width": 4})
        self.assertEqual(self.judge(naive(naive_run(samples=centred)), "naive.drift")["status"], "PASS")

    def test_drift_without_track_is_unmeasured(self):
        result = self.judge(naive(naive_run(samples=self.samples())), "naive.drift")
        self.assertEqual(result["status"], "WARNING")
        self.assertIn("track", result["summary"])

    def test_an_off_axis_camera_fails_alignment(self):
        # Course-relative steering under a camera turned 50 degrees off the course.
        skew = self.samples(view=lambda i: {"camera_forward": [0, -1],
                                            "control_forward": [0.766, -0.643]})
        result = self.judge(naive(naive_run(samples=skew)), "naive.alignment")
        self.assertEqual(result["status"], "FAIL")
        self.assertAlmostEqual(result["measured"]["p90_deg"], 50.0, delta=0.2)
        chase = self.samples(view=lambda i: {"camera_forward": [0, -1], "control_forward": [0.1, -1]})
        self.assertEqual(self.judge(naive(naive_run(samples=chase)), "naive.alignment")["status"], "PASS")

    def test_alignment_without_view_is_unmeasured(self):
        self.assertEqual(self.judge(naive(naive_run()), "naive.alignment")["status"], "WARNING")

    # -- the record -----------------------------------------------------------------------
    def test_no_record_on_a_naive_viewport_is_unmeasured_and_other_viewports_are_not_judged(self):
        checks = realism.judge({}, D3, RULES, "desktop", "mvp")
        self.assertEqual(sorted(c["id"] for c in checks if c["id"].startswith("naive.")),
                         ["naive.alignment", "naive.drift", "naive.pace", "naive.setbacks"])
        self.assertTrue(all(c["status"] == "WARNING" for c in checks))
        mobile = realism.judge({"naive": {"applies": False}}, D3, RULES, "mobile", "mvp")
        self.assertEqual([c for c in mobile if c["id"].startswith("naive.")], [])

    def test_units_the_naive_play_samples_beside_the_opening(self):
        units = [{"id": f"u{i}", "index": i} for i in range(1, 13)]
        self.assertEqual(realism.naive_units(units, 3), ["u7", "u12"])
        self.assertEqual(realism.naive_units(units[:1], 3), [])
        self.assertEqual(realism.naive_units(units, 1), [])


# -- level geometry ---------------------------------------------------------------------------

def layouts(**units):
    return {"schema": "wgf-layouts/1", "layouts": units}


HEAD_CIRCUIT = {"width": 8, "segments": [
    {"t": "line", "len": 14}, {"t": "turn", "deg": 180, "r": 6.684, "rails": "outside"},
    {"t": "line", "len": 14}, {"t": "turn", "deg": 180, "r": 6.684, "rails": "outside"}]}
R1_HAIRPINS = {"width": 5.5, "top_speed": 16, "par_s": 31, "segments": [
    {"t": "line", "len": 120}, {"t": "turn", "deg": 170, "r": 11},
    {"t": "turn", "deg": -170, "r": 11}, {"t": "line", "len": 120}]}


class LevelGeometry(unittest.TestCase):
    def judge(self, data, tier="release", content=None, units=()):
        return {c["id"]: c for c in realism.judge_layouts(data, RULES, tier, content, units)}

    def test_hairpins_tighter_than_the_width_fail(self):
        result = self.judge(layouts(**{"meadow-circuit": HEAD_CIRCUIT}))["level.geometry"]
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["measured"]["failing"][0]["radius_to_width"], 0.84)
        self.assertEqual(result["measured"]["failing"][0]["inner_edge"], "open")

    def test_the_accepted_builds_open_hairpins_pass(self):
        checks = self.judge(layouts(**{"9": R1_HAIRPINS}))
        self.assertEqual(checks["level.geometry"]["status"], "PASS")
        self.assertEqual(checks["level.unit_length"]["status"], "PASS", checks["level.unit_length"])

    def test_a_tight_bend_needs_a_railed_inner_edge(self):
        bend = {"width": 9, "segments": [{"t": "line", "len": 200},
                                         {"t": "turn", "deg": 130, "r": 11}]}
        self.assertEqual(self.judge(layouts(g=bend))["level.geometry"]["status"], "FAIL")
        railed = copy.deepcopy(bend)
        railed["segments"][1]["rails"] = True
        self.assertEqual(self.judge(layouts(g=railed))["level.geometry"]["status"], "PASS")

    def test_a_short_course_fails_its_length_and_its_time(self):
        # meadow-roll (1c6b099): 38 m at 14 m wide, 4.75 s at 8 m/s against a 24 s par.
        course = {"width": 14, "top_speed": 8, "segments": [
            {"t": "line", "len": 7}, {"t": "turn", "deg": 35, "r": 22, "rails": True},
            {"t": "turn", "deg": -35, "r": 22, "rails": True}, {"t": "line", "len": 4.122}]}
        content = {"units": [{"id": "meadow-roll", "parameters": {"time_target": 24}}]}
        result = self.judge(layouts(**{"meadow-roll": course}), content=content)["level.unit_length"]
        self.assertEqual(result["status"], "FAIL")
        problems = " ".join(result["measured"]["units"][0].keys())
        self.assertIn("traverse_to_par", problems)
        self.assertEqual(result["measured"]["units"][0]["traverse_to_par"], 0.2)

    def test_the_tier_sets_the_minimum_crossing_time(self):
        course = {"width": 5, "top_speed": 10, "segments": [{"t": "line", "len": 100}]}
        self.assertEqual(self.judge(layouts(c=course), tier="mvp")["level.unit_length"]["status"], "PASS")
        self.assertEqual(self.judge(layouts(c=course), tier="release")["level.unit_length"]["status"], "FAIL")

    def test_no_layout_file_is_not_judged_and_a_foreign_one_is_unmeasured(self):
        self.assertEqual(realism.judge_layouts(None, RULES, "release"), [])
        checks = self.judge({"layouts": {}})
        self.assertEqual({c["status"] for c in checks.values()}, {"WARNING"})

    def test_length_counts_lines_arcs_and_jumps(self):
        layout = {"segments": [{"t": "line", "len": 10}, {"t": "turn", "deg": 180, "r": 1},
                               {"t": "jump", "gap": 2}]}
        self.assertAlmostEqual(realism.layout_length(layout), 12 + 3.14159, places=3)


class TheContract(unittest.TestCase):
    def test_the_bars_are_versioned_data(self):
        data = load_file(os.path.join(paths.REFERENCE, "play-realism.yaml"))
        self.assertTrue(data["version"])
        for section in ("unmeasured", "physics", "naive", "geometry"):
            self.assertIn(section, data)
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
        from wgf_triage import routing
        table = routing.Routing.load()
        checks = table.data["producers"]["playability-report"]["checks"]
        self.assertEqual(checks["physics."], "gameplay")
        self.assertEqual(checks["naive."], "gameplay")
        self.assertEqual(checks["level."], "level-design")

    def test_the_bot_records_colliders_playfields_and_naive_play(self):
        with open(os.path.join(SCRIPTS, "wgf_playability", "bot.spec.ts"), encoding="utf-8") as h:
            bot = h.read()
        self.assertIn('test("naive: the build played by someone who is not perfect"', bot)
        self.assertIn("e.collider ?", bot)
        self.assertIn("playfields", bot)
        self.assertIn('write(project, "naive"', bot)


class TheStep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_layout_file_is_kept_beside_the_records(self):
        repo, out = os.path.join(self.tmp, "repo"), os.path.join(self.tmp, "out")
        os.makedirs(os.path.join(repo, "public", "content"))
        with open(os.path.join(repo, "public", "content", "layouts.json"), "w", encoding="utf-8") as h:
            json.dump(layouts(a=HEAD_CIRCUIT), h)
        PlayabilityStep._keep_content_data(repo, out)
        self.assertTrue(os.path.isfile(os.path.join(out, LAYOUTS_COPY)))
        self.assertEqual(PlayabilityStep._json(os.path.join(out, LAYOUTS_COPY))["schema"], "wgf-layouts/1")
        self.assertIsNone(PlayabilityStep._json(os.path.join(out, "absent.json")))

    def test_the_naive_settings_and_their_window(self):
        design = {"build_spec": {"content": {"unit_kind": "level", "generation": {"mode": "authored"},
                                             "units": [{"id": f"u{i}", "index": i, "tier": "mvp"}
                                                       for i in range(1, 7)]}}}
        settings = PlayabilityStep._naive_settings(design, RULES, ["mvp"])
        self.assertEqual(settings["naive_projects"], ["desktop"])
        self.assertEqual(settings["naive_run_ms"], RULES["naive"]["run_s"] * 1000)
        self.assertEqual(len(settings["naive_units"]), RULES["naive"]["units"] - 1)
        settings["start_timeout_ms"] = 30000
        window = PlayabilityStep._naive_window_s(settings)
        self.assertEqual(window, 1 * RULES["naive"]["units"] * 2 * (RULES["naive"]["run_s"] + 30 + 5))


if __name__ == "__main__":
    unittest.main()
