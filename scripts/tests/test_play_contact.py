"""Contact frames (scripts/wgf_playability/realism.py judge_contacts): whether a mover turned at
something DRAWN, and whether what is drawn of it is the size of what collides - read off the
pixels of the bot's frozen contact frames, not off what the probe says is drawn.

Synthetic scenes first (each built here, pixel by pixel, and labelled synthetic), then the REAL
recordings of the 2D validation game (scripts/tests/fixtures/real/play-contact/README.md): the
regressed builds must FAIL, the accepted build must not.

    python -m unittest scripts.tests.test_play_contact
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

from wgf_assets.raster import Image, encode_png  # noqa: E402
from wgf_playability import realism, scenario  # noqa: E402
from wgf_playability.step import CONTACT_FRAME_PREFIX, RECORDS, PlayabilityStep  # noqa: E402

RULES = realism.load_rules()
D2 = {"engine": {"dimension": "2d"}}
D3 = {"engine": {"dimension": "3d"}}
MVP = realism.strength_for(RULES, "mvp")
RELEASE = realism.strength_for(RULES, "release")
HELD = realism.strength_for(RULES, "release", held=lambda cid: "not passed at release")
REAL = os.path.join(HERE, "fixtures", "real", "play-contact")

# A synthetic clip of the screen: 200 x 200 CSS px at (300, 100), a dark blue board with a
# gentle gradient (a backdrop is never one flat colour).
CLIP = {"x": 300, "y": 100, "width": 200, "height": 200}
BACKGROUND = (30, 40, 70)


def canvas():
    image = Image(CLIP["width"], CLIP["height"])
    for y in range(image.height):
        for x in range(image.width):
            i = (y * image.width + x) * 4
            shade = (x + y) // 40
            image.pixels[i:i + 4] = bytes((BACKGROUND[0] + shade, BACKGROUND[1] + shade,
                                           BACKGROUND[2] + shade, 255))
    return image


def paint(image, inside, colour, alpha=1.0):
    """Blend `colour` over every pixel whose screen (CSS) position satisfies `inside(x, y)`."""
    for y in range(image.height):
        for x in range(image.width):
            if inside(x + CLIP["x"] + 0.5, y + CLIP["y"] + 0.5):
                i = (y * image.width + x) * 4
                for c in range(3):
                    image.pixels[i + c] = int(round(image.pixels[i + c] * (1 - alpha)
                                                    + colour[c] * alpha))


def disc(cx, cy, d):
    return lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= (d / 2) ** 2


def rect(x0, y0, x1, y1):
    return lambda x, y: x0 <= x <= x1 and y0 <= y <= y1


def entity(eid, x, y, w, h, role="projectile", render="asset", collider=None):
    return [eid, role, 1, x, y, w, h, eid, render, collider, None, None]


def ball(cx, cy, drawn, collider=12):
    return entity("ball", cx - drawn / 2, cy - drawn / 2, drawn, drawn,
                  collider=["circle", cx - collider / 2, cy - collider / 2, collider, collider]
                  if collider else None)


class Scene:
    """One frozen contact: a ball moving up (-y) turned with its leading edge at `top`, the
    frame of it and the frame after it left, written into a frames directory."""

    def __init__(self, directory, n=1, top=200.0, drawn=20, collider=12, cx=400.0):
        self.directory, self.n = directory, n
        self.cx, self.drawn, self.collider = cx, drawn, collider
        size = collider or drawn
        self.cy = top + size / 2
        self.at, self.after, self.later = canvas(), canvas(), canvas()
        self.others = []
        self.after_others = []
        self.later_others = None  # as in the frame after

    # A bot from play-realism 1.2.0 keeps a third frame: where the ball is in it, and in the
    # frame after (the extent is read on those two, inside the clip).
    AFTER = (-40.0, 40.0)
    LATER = (-100.0, 100.0)

    def after_at(self):
        return self.cx + self.AFTER[0], self.cy + self.AFTER[1]

    def turned_at(self):
        return ball(self.cx, self.cy, self.drawn, self.collider)

    def capture(self, kind="reversal", third=False):
        cy = self.cy
        frames = [
            {"t": 0.0, "e": [ball(self.cx - 4, cy + 6, self.drawn, self.collider)] + self.others, "pf": None},
            {"t": 16.7, "e": [self.turned_at()] + self.others, "pf": None},
            {"t": 33.3, "e": [ball(self.cx + 4, cy + 6, self.drawn, self.collider)] + self.others, "pf": None},
        ]
        after = [{"t": 333.3, "e": [ball(self.cx + 60, cy + 90, self.drawn, self.collider)]
                  + (self.after_others if self.after_others is not None else []), "pf": None}]
        images = [(f"contact-{self.n}-at", self.at), (f"contact-{self.n}-after", self.after)]
        if third:
            # Moving down-left at 3 px a frame away from the turn, at 1 px a frame per axis.
            (ax, ay), (lx, ly) = self.after_at(), (self.cx + self.LATER[0], cy + self.LATER[1])
            others = self.after_others if self.after_others is not None else []
            later_others = self.later_others if self.later_others is not None else others
            after = [{"t": 316.6, "e": [ball(ax + 2, ay - 2, self.drawn, self.collider)] + others, "pf": None},
                     {"t": 333.3, "e": [ball(ax, ay, self.drawn, self.collider)] + others, "pf": None}]
            later = [{"t": 650.0, "e": [ball(lx + 2, ly - 2, self.drawn, self.collider)] + later_others, "pf": None},
                     {"t": 666.6, "e": [ball(lx, ly, self.drawn, self.collider)] + later_others, "pf": None}]
            images.append((f"contact-{self.n}-later", self.later))
        for name, image in images:
            with open(os.path.join(self.directory, name + ".png"), "wb") as handle:
                handle.write(encode_png(image))
        out = {"n": self.n, "unit_id": "u1",
                "at": {"frame": f"contact-{self.n}-at", "still": True, "clip": dict(CLIP),
                       "event": {"kind": kind, "id": "ball",
                                 "turns": [{"axis": 1, "sign": -1, "speed": 6.0}]},
                       "frames": frames},
                "after": {"frame": f"contact-{self.n}-after", "still": True, "clip": dict(CLIP),
                          "frames": after}}
        if third:
            out["later"] = {"frame": f"contact-{self.n}-later", "still": True, "clip": dict(CLIP),
                            "frames": later}
        return out


def record(*captures, **kw):
    out = {"applies": True, "clock": "frame-stepped", "ended": "window", "captures": list(captures)}
    out.update(kw)
    return {"contact": out}


def judged(records, directory, strength=RELEASE, design=D2):
    return {c["id"]: c for c in realism.judge_contacts(records, directory, design, RULES,
                                                       "desktop", strength)}


class ContactDrawn(unittest.TestCase):
    """physics.contact_drawn on synthetic scenes (SYNTHETIC: built here, not recorded)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wgf-contact-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def scene(self, **kw):
        return Scene(self.dir, **kw)

    def test_a_turn_where_nothing_is_drawn_fails_and_blocks_at_release(self):
        s = self.scene()
        paint(s.at, disc(s.cx, s.cy, s.drawn), (240, 200, 40))
        result = judged(record(s.capture()), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result)
        self.assertTrue(result["required"])
        undrawn = result["measured"]["undrawn"][0]
        self.assertEqual(undrawn["surface"], "nothing reported")
        self.assertLess(undrawn["edge"], RULES["contact"]["min_edge"])
        # The frame read is pinned by its hash.
        self.assertTrue(result["measured"]["frames"]["contact-1-after"].startswith("sha256:"))
        # Below the enforced tiers it is a warning, never a pass.
        self.assertEqual(judged(record(s.capture()), self.dir, MVP)["physics.contact_drawn"]["status"],
                         "WARNING")

    def test_a_turn_at_a_drawn_wall_passes(self):
        s = self.scene()
        for image in (s.at, s.after):
            paint(image, rect(300, 190, 500, 200), (220, 220, 230))
        result = judged(record(s.capture()), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "PASS", result)
        self.assertGreater(result["measured"]["edges"][0], RULES["contact"]["min_edge"])

    def test_a_thin_line_is_a_drawn_wall(self):
        s = self.scene()
        for image in (s.at, s.after):
            paint(image, rect(300, 199, 500, 200), (120, 180, 220))
        self.assertEqual(judged(record(s.capture()), self.dir)["physics.contact_drawn"]["status"], "PASS")

    def test_a_surface_the_probe_reports_but_the_screen_does_not_draw_fails(self):
        # The gaming route around physics.undrawn_collision: report a box where the invisible
        # wall is. The probe's box explains the turn; the pixels do not.
        s = self.scene()
        ceiling = entity("ceiling", 300, 190, 200, 10, role="target", render="primitive")
        s.others, s.after_others = [ceiling], [ceiling]
        result = judged(record(s.capture()), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result)
        self.assertEqual(result["measured"]["undrawn"][0]["surface"], "reported entity")
        self.assertIn("the probe reports but the screen does not draw", result["summary"])
        # The probe-only check is satisfied by the same records: that is the gap this closes.
        win = {"win": {"sampled": {"frames": [f["e"] for f in s.capture()["at"]["frames"]],
                                   "viewport": [1280, 720]}}}
        probe_only = [c for c in realism.judge(win, D2, RULES, "desktop", RELEASE)
                      if c["id"] == "physics.undrawn_collision"]
        self.assertEqual(probe_only[0]["status"], "PASS", probe_only)

    def test_a_brick_the_hit_broke_is_left_to_the_probe(self):
        s = self.scene()
        brick = entity("brick-7", 380, 186, 40, 14, role="target")
        paint(s.at, rect(380, 186, 420, 200), (200, 80, 60))
        s.others, s.after_others = [brick], []
        result = judged(record(s.capture()), self.dir, HELD)["physics.contact_drawn"]
        self.assertNotEqual(result["status"], "PASS")
        self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)
        self.assertEqual(result["measured"]["unverified"], {"surface gone by the frame after": 1})
        self.assertEqual(result["status"], "FAIL")  # held: not passed at release

    def test_a_paddle_that_moved_under_the_ball_inside_the_step_is_left_to_the_probe(self):
        # As recorded on 894b4b8 (mobile, capture 9): in the frame the ball turned the paddle was
        # 40 px aside; in the next it was under the ball - it met the ball inside the step.
        s = self.scene()
        capture = s.capture()
        top = s.cy - 6
        aside = entity("paddle", 460, top - 12, 80, 12, role="player")
        under = entity("paddle", 360, top - 12, 80, 12, role="player")
        for f, paddle in zip(capture["at"]["frames"], (aside, aside, under)):
            f["e"].append(list(paddle))
        result = judged(record(capture), self.dir, MVP)["physics.contact_drawn"]
        self.assertEqual(result["measured"]["unverified"], {"moving surface": 1}, result)
        self.assertEqual(result["status"], "WARNING")

    def test_something_passing_through_in_the_frame_after_is_not_read(self):
        s = self.scene()
        capsule = entity("capsule", 380, 185, 19, 20, role="collectible")
        paint(s.after, rect(380, 185, 399, 205), (250, 250, 250))
        s.after_others = [capsule]
        result = judged(record(s.capture()), self.dir)["physics.contact_drawn"]
        # The capsule's pixels are masked, the rest of the band is read: still nothing drawn.
        self.assertEqual(result["status"], "FAIL", result)
        # Covering the whole contact, nothing is left to read: unmeasured, never a pass.
        s.after_others = [entity("capsule", 380, 175, 40, 45, role="collectible")]
        paint(s.after, rect(380, 175, 420, 220), (250, 250, 250))
        covered = judged(record(s.capture()), self.dir, MVP)["physics.contact_drawn"]
        self.assertEqual(covered["measured"]["unverified"], {"masked": 1})
        self.assertEqual(covered["status"], "WARNING")

    def test_a_frame_taken_while_the_page_moved_is_never_read(self):
        s = self.scene()
        capture = s.capture()
        capture["after"]["still"] = False
        result = judged(record(capture), self.dir, MVP)["physics.contact_drawn"]
        self.assertEqual(result["status"], "WARNING")
        self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)

    def test_a_bounce_off_the_screen_edge_is_at_a_drawn_edge(self):
        # K7 review MINOR-1: the canvas fills the viewport, the board's top IS the screen's top
        # (the clip is clamped to it): nothing past it is in any frame. The player sees the ball
        # turn at the edge of the screen - verified, not a turn at nothing drawn.
        s = self.scene(top=100.0)
        capture = s.capture()
        capture["at"]["clip"]["y"] = capture["after"]["clip"]["y"] = 0
        for part in ("at", "after"):
            for f in capture[part]["frames"]:
                for e in f["e"]:
                    e[4] -= 100
                    if e[9]:
                        e[9][2] -= 100
                f["pf"] = {"x": 0, "y": 0, "w": 1280, "h": 720}
        capture["viewport"] = [1280, 720]
        result = judged(record(capture), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "PASS", result["summary"])
        self.assertEqual(result["measured"]["verified"], 1)
        # The same board 40 px below the screen's top (letterboxed): its edge is not the
        # screen's, nothing is drawn there, and it FAILs - as it does with no viewport recorded.
        for part in ("at", "after"):
            for f in capture[part]["frames"]:
                for e in f["e"]:
                    e[4] += 40
                    if e[9]:
                        e[9][2] += 40
                f["pf"] = {"x": 0, "y": 40, "w": 1280, "h": 680}
        self.assertEqual(judged(record(capture), self.dir)["physics.contact_drawn"]["status"], "FAIL")
        for part in ("at", "after"):
            for f in capture[part]["frames"]:
                for e in f["e"]:
                    e[4] -= 40
                    if e[9]:
                        e[9][2] -= 40
                f["pf"] = {"x": 0, "y": 0, "w": 1280, "h": 720}
        del capture["viewport"]
        self.assertEqual(judged(record(capture), self.dir)["physics.contact_drawn"]["status"], "FAIL")

    def test_a_turn_that_travelled_too_far_in_its_frame_is_not_read(self):
        # A loop on its own clock on a slow host: 30 px a frame. The band past its leading edge
        # would reach whatever is drawn that far beyond an undrawn wall.
        s = self.scene()
        paint(s.after, rect(300, 170, 500, 176), (220, 220, 230))  # drawn 24-30 px beyond
        capture = s.capture()
        capture["at"]["event"]["turns"][0]["speed"] = 30.0
        result = judged(record(capture), self.dir, MVP)["physics.contact_drawn"]
        self.assertEqual(result["measured"]["unverified"], {"travelled too far in a frame": 1})
        self.assertEqual(result["status"], "WARNING")
        # At the bar's travel it is read, and the wall that far beyond is not reached.
        capture["at"]["event"]["turns"][0]["speed"] = RULES["contact"]["max_travel_px"]
        self.assertEqual(judged(record(capture), self.dir)["physics.contact_drawn"]["status"], "FAIL")

    def test_frame_timestamps_of_a_bot_record_are_stepped_and_cannot_show_the_pace(self):
        # REAL: the bot keeps the STEPPED timestamps (frame_ms apart by construction) while the
        # page's real pacing was often slower than 40 ms - which is why the reading is guarded
        # on the mover's travel, not on the frames' timestamps (K7 review, MAJOR-1).
        for build in ("96f5cea", "68a12b7", "cbac64e"):
            rec = real(os.path.join(build, "desktop", "contact.json.gz"))
            for c in rec["captures"]:
                ts = [f["t"] for f in c["at"]["frames"]]
                self.assertTrue(all(abs((b - a) - rec["frame_ms"]) < 0.01 for a, b in zip(ts, ts[1:])), ts)
            self.assertGreater(sum(rec["frame_gaps"][2:]), 100, build)

    def test_no_turn_frozen_is_unmeasured_never_passed(self):
        result = judged(record(ended="window"), self.dir, HELD)
        self.assertEqual(result["physics.contact_drawn"]["status"], "FAIL")
        self.assertEqual(result["physics.contact_drawn"]["measured"]["unmeasured"], realism.UNREPORTED)
        self.assertEqual(result["physics.drawn_extent"]["status"], "FAIL")
        mvp = judged(record(ended="window"), self.dir, MVP)
        self.assertEqual({c["status"] for c in mvp.values()}, {"WARNING"})

    def test_movers_that_never_turned_have_no_contact_to_verify(self):
        # As physics.undrawn_collision passes a window in which nothing turned (a shot that
        # flies off the board); the drawn extent is still owed.
        result = judged(record(ended="window", turns=0, passed=0, movers_seen=240), self.dir, HELD)
        self.assertEqual(result["physics.contact_drawn"]["status"], "PASS")
        self.assertEqual(result["physics.drawn_extent"]["status"], "FAIL")
        self.assertEqual(result["physics.drawn_extent"]["measured"]["unmeasured"], realism.UNREPORTED)
        # Turns seen but none frozen on (all at moving or composite surfaces): unmeasured.
        held = judged(record(ended="window", turns=4, passed=4, movers_seen=240), self.dir, HELD)
        self.assertEqual(held["physics.contact_drawn"]["measured"]["unmeasured"], realism.UNREPORTED)

    def test_a_pair_asked_for_without_a_turn_measures_the_extent_only(self):
        s = self.scene()
        paint(s.at, disc(s.cx + 4, s.cy + 6, 14), (240, 200, 40))
        capture = s.capture(kind="asked")
        capture["at"]["event"] = {"kind": "asked"}
        result = judged(record(capture, turns=0, passed=0, movers_seen=240), self.dir)
        self.assertEqual(result["physics.contact_drawn"]["status"], "PASS", result)
        self.assertEqual(result["physics.drawn_extent"]["status"], "PASS", result)

    def test_nothing_of_the_judged_roles_in_play_is_not_judged(self):
        self.assertEqual(judged(record(ended="no projectile in play"), self.dir), {})
        # ... unless the design declares one: the bot not seeing it is not "none to judge"
        # (K7 review MAJOR-3: a ball that appears late, or one the probe does not report).
        ball_design = {"engine": {"dimension": "2d"},
                       "build_spec": {"assets": [{"id": "ball", "role": "projectile"}]}}
        declared = judged(record(ended="no projectile in play"), self.dir, HELD, design=ball_design)
        self.assertEqual({c["status"] for c in declared.values()}, {"FAIL"})
        self.assertEqual({c["measured"]["unmeasured"] for c in declared.values()}, {realism.UNREPORTED})
        self.assertEqual(set(declared), {"physics.contact_drawn", "physics.drawn_extent"})
        # A page the contact hook never reached is not "nothing in play": unmeasured.
        lost = judged(record(ended="no contact hook"), self.dir, MVP)
        self.assertEqual({c["status"] for c in lost.values()}, {"WARNING"})

    def test_a_3d_build_an_older_bot_and_a_record_not_asked_are_not_judged(self):
        s = self.scene()
        self.assertEqual(judged(record(s.capture()), self.dir, design=D3), {})
        self.assertEqual(judged({}, self.dir), {})
        self.assertEqual(judged({"contact": {"applies": False, "reason": "3d"}}, self.dir), {})


class DrawnExtent(unittest.TestCase):
    """physics.drawn_extent on synthetic sprites (SYNTHETIC: built here, not recorded)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wgf-extent-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def ratio(self, draw, collider=12, strength=RELEASE, drawn_box=40):
        s = Scene(self.dir, drawn=drawn_box, collider=collider)
        frozen = s.capture()["at"]["frames"][-1]["e"][0]
        # The frozen frame is the last of the three: the ball one step past the turn.
        box = realism._box(*frozen[9][1:5]) if frozen[9] else realism._box(*frozen[3:7])
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        draw(s.at, cx, cy)
        return judged(record(s.capture()), self.dir, strength)["physics.drawn_extent"]

    def test_a_sprite_about_its_collider_passes(self):
        result = self.ratio(lambda image, cx, cy: paint(image, disc(cx, cy, 14), (240, 200, 40)))
        self.assertEqual(result["status"], "PASS", result)
        self.assertTrue(all(1.0 <= r <= 1.4 for r in result["measured"]["ratios"]["ball"]), result)

    def test_a_sprite_drawn_three_times_its_collider_fails(self):
        result = self.ratio(lambda image, cx, cy: paint(image, disc(cx, cy, 36), (240, 200, 40)))
        self.assertEqual(result["status"], "FAIL", result)
        self.assertEqual(result["measured"]["out_of_bounds"], ["ball"])

    def test_a_soft_glow_around_a_solid_body_is_not_the_body(self):
        def draw(image, cx, cy):
            paint(image, disc(cx, cy, 36), (90, 230, 255), alpha=0.25)
            paint(image, disc(cx, cy, 14), (255, 255, 255))
        result = self.ratio(draw)
        self.assertEqual(result["status"], "PASS", result)

    def test_nothing_drawn_where_it_collides_fails(self):
        result = self.ratio(lambda image, cx, cy: paint(image, disc(cx + 30, cy, 14), (240, 200, 40)))
        self.assertEqual(result["status"], "FAIL", result)
        self.assertIn("ball", result["measured"]["nothing_drawn"])

    def test_a_body_drawn_smaller_than_its_collider_fails(self):
        # Below physics.min_drawn_to_collider a hit lands on nothing drawn.
        result = self.ratio(lambda image, cx, cy: paint(image, disc(cx, cy, 8), (240, 200, 40)))
        self.assertEqual(result["status"], "FAIL", result)
        self.assertTrue(any(r < RULES["physics"]["min_drawn_to_collider"]
                            for r in result["measured"]["ratios"]["ball"]), result)

    def scene_with(self, draw, others_at=(), others_after=(), collider=12, drawn_box=40):
        """A ball frozen at a turn, drawn by `draw(image, cx, cy)`, with other entities reported
        in the frozen frame and the frame after (each [entity, colour or None])."""
        s = Scene(self.dir, drawn=drawn_box, collider=collider)
        capture = s.capture()
        frozen = capture["at"]["frames"][-1]["e"]
        box = realism._box(*frozen[0][9][1:5])
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        draw(s.at, cx, cy)
        for frame, image, others in ((frozen, s.at, others_at),
                                     (capture["after"]["frames"][-1]["e"], s.after, others_after)):
            for make, colour in others:
                e = make(cx, cy)
                frame.append(e)
                if colour:
                    paint(image, rect(e[3], e[4], e[3] + e[5], e[4] + e[6]), colour)
        for name, image in (("contact-1-at", s.at), ("contact-1-after", s.after)):
            with open(os.path.join(self.dir, name + ".png"), "wb") as handle:
                handle.write(encode_png(image))
        return judged(record(capture), self.dir)["physics.drawn_extent"]

    def test_a_body_cut_by_the_window_on_every_axis_is_held_by_its_lower_bound(self):
        # A ball drawn five times its collider reaches the window's edge on both axes: each axis
        # is only a lower bound - and a lower bound over the bar FAILs.
        result = self.scene_with(lambda image, cx, cy: paint(image, disc(cx, cy, 60), (240, 200, 40)))
        self.assertEqual(result["status"], "FAIL", result)
        self.assertEqual(result["measured"]["ratios"]["ball"], [None, None])
        self.assertTrue(all(v > RULES["physics"]["max_drawn_to_collider"]
                            for v in result["measured"]["lower_bounds"]["ball"]), result)

    def test_a_body_cut_by_a_mask_is_never_held_too_small_on_that_axis(self):
        # A brick reported over the right half of a ball drawn about its collider: across x the
        # ball reads half its width, but cut - a lower bound, which can show a body too large,
        # never one too small. Its height is read whole.
        brick = (lambda cx, cy: entity("brick", cx, cy - 20, 20, 40, role="target"), None)
        result = self.scene_with(lambda image, cx, cy: paint(image, disc(cx, cy, 14), (240, 200, 40)),
                                 others_at=[brick])
        self.assertEqual(result["status"], "PASS", result)
        x, y = result["measured"]["ratios"]["ball"]
        self.assertIsNone(x)
        self.assertTrue(1.0 <= y <= 1.3, result)

    def test_an_entity_that_did_not_move_away_is_not_read(self):
        # A paddle with a collider, drawn its size, still in place in the frame after: nothing
        # changed where it collides, which says nothing about what is drawn there.
        def paddle(cx, cy):
            return entity("paddle", cx - 40, cy + 30, 40, 10, role="player",
                          collider=["rect", cx - 40, cy + 30, 40, 10])
        result = self.scene_with(lambda image, cx, cy: paint(image, disc(cx, cy, 14), (240, 200, 40)),
                                 others_at=[(paddle, (90, 220, 120))],
                                 others_after=[(paddle, (90, 220, 120))])
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["measured"]["not_moved_away"], 1)
        self.assertNotIn("paddle", result["measured"]["nothing_drawn"])

    def test_no_collider_reported_is_unmeasured_never_passed(self):
        result = self.ratio(lambda image, cx, cy: paint(image, disc(cx, cy, 14), (240, 200, 40)),
                            collider=None, strength=HELD)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)
        self.assertIn("no entities[].collider", result["summary"])


class Wiring(unittest.TestCase):
    """The step asks for the contact test on 2D builds only, keeps its crops out of the report's
    frames (visual QA judges screens, not crops), and names its record in the scenario."""

    def test_settings_by_dimension(self):
        on = PlayabilityStep._contact_settings(D2, RULES)
        self.assertTrue(on["contact_applies"])
        self.assertEqual(on["contact_projects"], RULES["contact"]["projects"])
        self.assertGreater(on["contact_ms"], 0)
        off = PlayabilityStep._contact_settings(D3, RULES)
        self.assertFalse(off["contact_applies"])
        self.assertEqual(off["contact_ms"], 0)
        self.assertIn("3d", off["contact_reason"])

    def test_the_record_is_read_and_its_crops_are_not_report_frames(self):
        self.assertIn("contact", RECORDS)
        directory = tempfile.mkdtemp(prefix="wgf-frames-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        for name in ("play-2s.png", CONTACT_FRAME_PREFIX + "1-at.png"):
            with open(os.path.join(directory, name), "wb") as handle:
                handle.write(encode_png(canvas()))
        listed = [f["id"] for f in PlayabilityStep._frames(directory, "desktop", directory)]
        self.assertEqual(listed, ["play-2s"])

    def test_scenarios_name_the_contact_record(self):
        for cid in ("physics.contact_drawn", "physics.drawn_extent"):
            self.assertEqual(scenario.SOURCES[cid], ("contact",))
        self.assertIn("contact", scenario.POLICIES)

    def test_the_process_timeout_grows_by_the_contact_window(self):
        settings = {"start_timeout_ms": 30000, "naive_projects": [], "risk_projects": []}
        base = PlayabilityStep._realism_window_s(settings)
        settings.update(PlayabilityStep._contact_settings(D2, RULES))
        grown = PlayabilityStep._realism_window_s(settings)
        self.assertGreaterEqual(grown - base, len(RULES["contact"]["projects"]) * RULES["contact"]["window_s"])


def real(name):
    with gzip.open(os.path.join(REAL, name), "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


class RealRecordings(unittest.TestCase):
    """REAL: the contact test played on builds of the 2D validation game (README.md there)."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = real("manifest.json.gz") if os.path.isfile(
            os.path.join(REAL, "manifest.json.gz")) else None

    def replay(self, build, project, strength=RELEASE):
        directory = os.path.join(REAL, build, project)
        rec = real(os.path.join(build, project, "contact.json.gz"))
        return {c["id"]: c for c in realism.judge_contacts({"contact": rec}, directory, D2, RULES,
                                                           project, strength)}

    def test_fixtures_are_the_bytes_recorded(self):
        import hashlib
        self.assertIsNotNone(self.manifest)
        for entry in self.manifest["files"]:
            with open(os.path.join(REAL, entry["path"]), "rb") as handle:
                digest = "sha256:" + hashlib.sha256(handle.read()).hexdigest()
            self.assertEqual(digest, entry["sha256"], entry["path"])

    # H2 (retro report section 6): undrawn ceilings added so the bot reached units in time.
    def test_H2_the_ceiling_commit_turns_the_ball_where_nothing_is_drawn(self):
        for project in ("desktop", "mobile"):
            result = self.replay("cbac64e", project)["physics.contact_drawn"]
            self.assertEqual(result["status"], "FAIL", (project, result["summary"]))
            undrawn = result["measured"]["undrawn"]
            self.assertTrue(undrawn)
            # Every undrawn contact is a turn upward (the ceiling), at nothing the probe reports.
            self.assertTrue(all(u["moving"] == "-y" and u["surface"] == "nothing reported"
                                for u in undrawn), undrawn)
            self.assertTrue(all(u["edge"] < 20 for u in undrawn), undrawn)

    def test_H2_the_regressed_head_still_turns_at_the_undrawn_ceiling(self):
        for project in ("desktop", "mobile"):
            result = self.replay("68a12b7", project)["physics.contact_drawn"]
            self.assertEqual(result["status"], "FAIL", (project, result["summary"]))
            self.assertGreaterEqual(len(result["measured"]["undrawn"]), 5)

    def test_H2_the_accepted_build_turns_only_at_drawn_surfaces(self):
        for project in ("desktop", "mobile"):
            result = self.replay("96f5cea", project)["physics.contact_drawn"]
            self.assertEqual(result["status"], "PASS", (project, result["summary"]))
            self.assertEqual(len(result["measured"]["edges"]), 6)
            self.assertGreater(min(result["measured"]["edges"]), 3 * RULES["contact"]["min_edge"])

    def test_the_bar_separates_every_real_reading(self):
        drawn, undrawn = [], []
        for build in ("68a12b7", "cbac64e", "96f5cea"):
            for project in ("desktop", "mobile"):
                m = self.replay(build, project)["physics.contact_drawn"]["measured"]
                low = {u["capture"] for u in m["undrawn"]}
                undrawn += [u["edge"] for u in m["undrawn"]]
                drawn += [e for e in m["edges"] if e >= RULES["contact"]["min_edge"]]
                self.assertEqual(len(low), len(m["undrawn"]))
        self.assertLess(max(undrawn), RULES["contact"]["min_edge"] / 1.4)
        self.assertGreater(min(drawn), RULES["contact"]["min_edge"] * 3.5)

    def test_builds_that_report_no_collider_are_never_passed_on_drawn_extent(self):
        for build in ("68a12b7", "cbac64e", "96f5cea"):
            result = self.replay(build, "desktop", HELD)["physics.drawn_extent"]
            self.assertEqual(result["status"], "FAIL", build)
            self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)
            self.assertIn("no entities[].collider", result["summary"])

    # H3: the ball's drawing enlarged (44 -> 60 board px) with its collider r11 unchanged.
    def test_H3_the_enlarged_ball_is_drawn_far_larger_than_its_collider(self):
        result = self.replay("68a12b7-collider", "desktop")["physics.drawn_extent"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        x, y = result["measured"]["ratios"]["ball-1"]
        self.assertGreater(x, 2.5)
        self.assertGreater(y, RULES["physics"]["max_drawn_to_collider"])

    def test_H3_r1_itself_draws_its_solid_disc_twice_its_collider(self):
        # Not the person's PASS: r1's 42.3 px solid disc over its 22 px collider is 1.9 x on the
        # pixels, over the 1.3 bar physics.collider_size already holds - the reason 894b4b8
        # grew the collider to the disc (its own tuning says so). The glow is not counted.
        result = self.replay("96f5cea-collider", "desktop")["physics.drawn_extent"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        for ratios in result["measured"]["ratios"].values():
            self.assertTrue(all(1.8 <= r <= 2.1 for r in ratios if r is not None), ratios)

    def test_H3_the_collider_grown_to_the_disc_passes_on_its_pixels(self):
        for project in ("desktop", "mobile"):
            result = self.replay("894b4b8-collider", project)["physics.drawn_extent"]
            self.assertEqual(result["status"], "PASS", (project, result["summary"]))
            for ratios in result["measured"]["ratios"].values():
                self.assertTrue(all(1.0 <= r <= 1.25 for r in ratios if r is not None), ratios)
            self.assertEqual(self.replay("894b4b8-collider", project)["physics.contact_drawn"]["status"],
                             "PASS")

    def test_H3_a_body_reported_the_collider_size_passes_the_probe_check_and_fails_the_pixels(self):
        # The gaming route: report `body` = the collider (and `halo: true`) on the head's ball.
        rec = real(os.path.join("68a12b7-collider", "desktop", "contact.json.gz"))
        frames = []
        for capture in rec["captures"]:
            for f in capture["at"]["frames"]:
                for s in f["e"]:
                    if s[0].startswith("ball") and s[9]:
                        s[10], s[11] = list(s[9][1:5]), True
                frames.append(f["e"])
        probe = [c for c in realism.judge({"win": {"sampled": {"frames": frames}}}, D2, RULES,
                                          "desktop", RELEASE) if c["id"] == "physics.collider_size"]
        self.assertEqual(probe[0]["status"], "PASS", probe)
        pixels = realism.judge_contacts({"contact": rec}, os.path.join(REAL, "68a12b7-collider", "desktop"),
                                        D2, RULES, "desktop", RELEASE)
        self.assertEqual([c["status"] for c in pixels if c["id"] == "physics.drawn_extent"], ["FAIL"])


class Bypasses(unittest.TestCase):
    """Ways a build could pass physics.contact_drawn / physics.drawn_extent without drawing what
    it collides with (K7 bypass review, 2026-10-12). SYNTHETIC scenes are built here; the REAL
    ones edit a recorded record the way a gaming build would report it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wgf-bypass-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def drawn_wall(self, n):
        s = Scene(self.dir, n=n)
        for image in (s.at, s.after):
            paint(image, rect(300, 190, 500, 200), (220, 220, 230))
        return s.capture()

    def test_an_entity_reported_over_the_contact_in_the_frame_after_cannot_hide_an_undrawn_wall(self):
        # A "dust" entity reported over the turn from the frame after on, drawn nowhere: its box
        # masks every line of the contact. A mask hides what is drawn under it, never that
        # nothing is: read without it, nothing is drawn there either.
        s = Scene(self.dir, n=2)
        s.after_others = [entity("dust", 380, 175, 40, 45, role="vfx")]
        result = judged(record(self.drawn_wall(1), s.capture()), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        self.assertEqual([u["capture"] for u in result["measured"]["undrawn"]], [2])
        self.assertTrue(result["measured"]["undrawn"][0]["masked"])
        # Something drawn over it (a capsule passing) is still never read as the wall.
        drawn = Scene(self.dir, n=3)
        drawn.after_others = [entity("capsule", 380, 175, 40, 45, role="collectible")]
        paint(drawn.after, rect(380, 175, 420, 220), (250, 250, 250))
        covered = judged(record(self.drawn_wall(1), drawn.capture()), self.dir)["physics.contact_drawn"]
        self.assertEqual(covered["measured"]["unverified"], {"masked": 1}, covered)
        self.assertEqual(covered["measured"]["verified"], 1)

    def test_an_entity_masked_in_every_frame_is_not_dropped_from_the_drawn_extent(self):
        # The ball, drawn three times its collider, under a "trail" entity reported over it
        # (drawn nowhere) in the frozen frame; a paddle drawn its collider's size beside it. The
        # ball is never read - unmeasured, never passed on the paddle alone.
        s = Scene(self.dir, drawn=40, collider=12)
        capture = s.capture()
        frozen = capture["at"]["frames"][-1]["e"]
        box = realism._box(*frozen[0][9][1:5])
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        paint(s.at, disc(cx, cy, 36), (240, 200, 40))
        frozen.append(entity("trail", cx - 10, cy - 10, 20, 20, role="vfx"))
        frozen.append(entity("paddle", 330, 250, 20, 10, role="player", collider=["rect", 330, 250, 20, 10]))
        paint(s.at, rect(330, 250, 350, 260), (90, 220, 120))
        capture["after"]["frames"][-1]["e"].append(
            entity("paddle", 430, 250, 20, 10, role="player", collider=["rect", 430, 250, 20, 10]))
        paint(s.after, rect(430, 250, 450, 260), (90, 220, 120))
        for name, image in (("contact-1-at", s.at), ("contact-1-after", s.after)):
            with open(os.path.join(self.dir, name + ".png"), "wb") as handle:
                handle.write(encode_png(image))
        result = judged(record(capture), self.dir, HELD)["physics.drawn_extent"]
        self.assertEqual(result["status"], "FAIL", result)
        self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)
        self.assertEqual(result["measured"]["masked_out"], ["ball"])
        self.assertIn("ball", result["summary"])

    @staticmethod
    def scaled(build, project, k):
        """The REAL record with every ball's reported collider scaled by `k` about its centre -
        the probe edited, the simulation not."""
        rec = real(os.path.join(build, project, "contact.json.gz"))
        for capture in rec["captures"]:
            for part in ("at", "after"):
                for f in (capture.get(part) or {}).get("frames") or []:
                    for s in f["e"]:
                        if s[0].startswith("ball") and s[9]:
                            shape, x, y, w, h = s[9]
                            s[9] = [shape, x + w / 2 - k * w / 2, y + h / 2 - k * h / 2, k * w, k * h]
        return rec

    def test_a_collider_reported_to_match_the_drawing_is_held_to_where_it_touched(self):
        # REAL records, the collider scaled to where the drawn extent alone passes (or, x2.0 on
        # 96f5cea, reads 1.0 x).
        for build, k in (("68a12b7-collider", 2.3), ("96f5cea-collider", 2.6), ("96f5cea-collider", 2.0)):
            rec = self.scaled(build, "desktop", k)
            result = {c["id"]: c for c in realism.judge_contacts(
                {"contact": rec}, os.path.join(REAL, build, "desktop"), D2, RULES, "desktop", RELEASE)}
            extent = result["physics.drawn_extent"]
            self.assertEqual(extent["status"], "FAIL", (build, extent["summary"]))
            self.assertIn("where it touched", extent["summary"])
            reach = extent["measured"]["collider_to_contact"]
            bar = RULES["contact"]["max_collider_to_contact"]
            self.assertTrue(all(v > bar for v in reach.values()), reach)
        # The honest records stay under the bar (894b4b8 PASSes, test_H3_the_collider_grown_...).
        for build, project in (("894b4b8-collider", "desktop"), ("894b4b8-collider", "mobile"),
                               ("96f5cea-collider", "desktop"), ("68a12b7-collider", "desktop")):
            m = self.replay_measured(build, project)
            self.assertTrue(m["collider_to_contact"], (build, project))
            self.assertTrue(all(v < 0.9 for v in m["collider_to_contact"].values()), (build, project, m))

    def replay_measured(self, build, project):
        directory = os.path.join(REAL, build, project)
        rec = real(os.path.join(build, project, "contact.json.gz"))
        return {c["id"]: c for c in realism.judge_contacts({"contact": rec}, directory, D2, RULES, project,
                                                           RELEASE)}["physics.drawn_extent"]["measured"]

    @staticmethod
    def bouncing(stall):
        """Per-frame samples of a ball bouncing between a drawn floor and a turn at y 200, where
        nothing is drawn (the bricks lie ahead of it, at 100-120); `stall` still frames at each
        turn at the top (a hit-stop)."""
        frames, y, v = [], 260.0, -5.0
        bricks = entity("bricks", 300, 100, 200, 20, role="target")
        floor = entity("floor", 300, 266, 200, 10, role="environment")
        for _ in range(60):
            here = entity("ball", 394, y - 6, 12, 12, collider=["circle", 394, y - 6, 12, 12])
            frames.append([here, list(bricks), list(floor)])
            if y <= 200 and v < 0:
                v = -v
                frames += [[list(here), list(bricks), list(floor)] for _ in range(stall)]
            y += v
            if y >= 260 and v > 0:
                v = -v
        return frames

    def test_a_hit_stop_at_each_bounce_does_not_hide_the_turn(self):
        for stall in (0, 1, 2, 5):
            win = {"win": {"sampled": {"frames": self.bouncing(stall), "viewport": [1280, 720]}}}
            got = [c for c in realism.judge(win, D2, RULES, "desktop", RELEASE)
                   if c["id"] == "physics.undrawn_collision"][0]
            self.assertEqual(got["status"], "FAIL", (stall, got["summary"]))

    def test_no_turn_frozen_is_not_passed_when_the_probe_samples_show_turns(self):
        # The contact test saw no turn (a hit-stop the bot's three-frame track cannot see), the
        # win test's samples did: there was a contact to verify, so it is unmeasured.
        records = record(ended="window", turns=0, passed=0, movers_seen=240)
        records["win"] = {"sampled": {"frames": self.bouncing(1), "viewport": [1280, 720]}}
        result = judged(records, self.dir, HELD)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)
        self.assertIn("win test", result["summary"])
        # Samples with no turn either: still no contact to verify.
        still = record(ended="window", turns=0, passed=0, movers_seen=240)
        still["win"] = {"sampled": {"frames": [[entity("ball", 394, 200, 12, 12)]] * 5,
                                    "viewport": [1280, 720]}}
        self.assertEqual(judged(still, self.dir, HELD)["physics.contact_drawn"]["status"], "PASS")

    def test_a_reported_ui_box_over_the_contact_cannot_mask_an_undrawn_wall(self):
        # K7 review MINOR-3 (probe P4): a HUD strip reported over the band, drawn nowhere there.
        s = Scene(self.dir, n=2)
        s.after_others = [entity("hud", 300, 150, 200, 56, role="ui", render="primitive")]
        result = judged(record(self.drawn_wall(1), s.capture()), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        self.assertEqual(result["measured"]["unverified"], {})

    def test_a_low_contrast_wall_reads_undrawn_a_known_limitation(self):
        # K7 review MINOR-2, PINNED (not a bypass - a false positive the docs list): a wall
        # drawn at a 20-35 colour distance from the backdrop (26 here; visible on a monitor) is
        # under min_edge 48 and FAILs as a turn at nothing drawn. The bar was calibrated on one
        # game (undrawn 13-34, drawn 172-385); a second game's palette is what it lacks.
        s = Scene(self.dir)
        for image in (s.at, s.after):
            paint(image, rect(300, 186, 500, 200), (50, 60, 90))
        result = judged(record(s.capture()), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        self.assertTrue(20 < result["measured"]["undrawn"][0]["edge"] < RULES["contact"]["min_edge"], result)

    def test_a_faint_wall_is_not_a_drawn_wall(self):
        # Not a bypass: a wall drawn at 8 % opacity reads as the background it is blended into.
        s = Scene(self.dir)
        for image in (s.at, s.after):
            paint(image, rect(300, 190, 500, 200), (220, 220, 230), alpha=0.08)
        self.assertEqual(judged(record(s.capture()), self.dir)["physics.contact_drawn"]["status"], "FAIL")


class ReviewR1(unittest.TestCase):
    """K7 review of 3e8d25f: surfaces a later frame cannot show where the mover met them are read
    where they are (MAJOR-2), the third frame (`later`, a bot from play-realism 1.2.0) against
    sparks (MINOR-4) and for the drawn extent away from the impact, across the travel (MAJOR-4),
    a game whose turns are all at a moving paddle (MINOR-5). SYNTHETIC scenes, built here."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wgf-review-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def drawn_wall(self, n):
        s = Scene(self.dir, n=n)
        for image in (s.at, s.after):
            paint(image, rect(300, 190, 500, 200), (220, 220, 230))
        return s.capture()

    # -- MAJOR-2 ---------------------------------------------------------------------------

    def test_a_reported_ceiling_that_moves_is_read_where_it_went(self):
        # Probe P9: the box reported where the invisible ceiling is, jittering 1 px a frame. It
        # is a moving surface: the contact is carried with it to where it is in the frame after.
        s = Scene(self.dir, n=2)
        capture = s.capture()
        for i, f in enumerate(capture["at"]["frames"]):
            f["e"].append(entity("ceiling", 300 + i, 190, 200, 10, role="target", render="primitive"))
        capture["after"]["frames"][0]["e"].append(
            entity("ceiling", 303, 190, 200, 10, role="target", render="primitive"))
        result = judged(record(self.drawn_wall(1), capture), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        undrawn = result["measured"]["undrawn"][0]
        self.assertEqual((undrawn["surface"], undrawn["read"]), ("moving surface", "carried"))

    def test_a_paddle_is_read_where_it_went_and_a_paddle_only_game_passes(self):
        # MINOR-5: a keep-it-up game turns only at its paddle. The paddle moved 60 px by the
        # frame after; drawn there, the contact carried with it is at something drawn.
        s = Scene(self.dir, top=200.0)
        capture = s.capture()
        top = s.cy - 6
        for f, x in zip(capture["at"]["frames"], (360, 362, 364)):
            f["e"].append(entity("paddle", x, top - 12, 80, 12, role="player"))
        capture["after"]["frames"][0]["e"].append(entity("paddle", 424, top - 12, 80, 12, role="player"))
        paint(s.after, rect(424, top - 12, 504, top), (90, 220, 120))
        with open(os.path.join(self.dir, "contact-1-after.png"), "wb") as handle:
            handle.write(encode_png(s.after))
        result = judged(record(capture, turns=6, passed=6, movers_seen=500), self.dir, HELD)
        contact = result["physics.contact_drawn"]
        self.assertEqual(contact["status"], "PASS", contact["summary"])
        self.assertEqual(contact["measured"]["verified"], 1)
        # Not drawn where it went: a paddle the screen does not show.
        s.after = canvas()
        with open(os.path.join(self.dir, "contact-1-after.png"), "wb") as handle:
            handle.write(encode_png(s.after))
        self.assertEqual(judged(record(capture), self.dir)["physics.contact_drawn"]["status"], "FAIL")

    def composite_row(self, drawn):
        s = Scene(self.dir, n=2)
        row = entity("bricks", 300, 186, 200, 14, role="target", render="composite")
        s.others, s.after_others = [row], [row]
        if drawn:
            # The row drawn, but for the brick the hit broke (380-420).
            for x0 in (300, 340, 420, 460):
                paint(s.after, rect(x0 + 1, 186, x0 + 39, 200), (200, 80, 60))
        return s.capture()

    def test_a_composite_is_read_along_its_face(self):
        # A row of bricks, the one hit gone: drawn along its face - a verified contact.
        drawn = judged(record(self.drawn_wall(1), self.composite_row(True)), self.dir)
        self.assertEqual(drawn["physics.contact_drawn"]["status"], "PASS", drawn["physics.contact_drawn"])
        self.assertEqual(drawn["physics.contact_drawn"]["measured"]["verified"], 2)
        # `render: composite` on an invisible ceiling: nothing drawn along its face, and nothing
        # drawn in its box in any frame read - not passed (the bricks around a hit can all be
        # gone, so it is not a measured FAIL either).
        ghost = judged(record(self.drawn_wall(1), self.composite_row(False)), self.dir, HELD)
        contact = ghost["physics.contact_drawn"]
        self.assertEqual(contact["status"], "FAIL", contact["summary"])
        self.assertEqual(contact["measured"]["unmeasured"], realism.UNREPORTED)
        self.assertEqual(contact["measured"]["composites_drawn_nowhere"], {"bricks": [2]})
        # A sparse composite: nothing along its face near the hit, its other parts drawn in its
        # box - left to the probe, the other contact verified: PASS.
        sparse = self.composite_row(False)
        s = Scene(self.dir, n=2)
        paint(s.after, rect(301, 120, 339, 134), (200, 80, 60))
        row = entity("bricks", 300, 120, 200, 80, role="target", render="composite")
        s.others, s.after_others = [row], [row]
        sparse = s.capture()
        result = judged(record(self.drawn_wall(1), sparse), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "PASS", result["summary"])
        self.assertEqual(result["measured"]["unverified"], {"composite surface": 1})

    def test_a_ceiling_reported_anew_under_another_id_is_read(self):
        # Re-issuing the ceiling's id each frame made it "gone by the frame after": the box under
        # another id in the same place is the same surface.
        s = Scene(self.dir, n=2)
        s.others = [entity("ceiling-1", 300, 190, 200, 10, role="target")]
        s.after_others = [entity("ceiling-9", 300, 190, 200, 10, role="target")]
        result = judged(record(self.drawn_wall(1), s.capture()), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        self.assertEqual(result["measured"]["undrawn"][0]["explained_by"], "ceiling-9")

    def test_a_surface_gone_that_the_mover_meets_again_is_not_passed(self):
        # Reported only while the mover is near it: gone from every frame after, met again. A
        # brick the hit broke is never met again.
        captures = [self.drawn_wall(1)]
        for n in (2, 3):
            s = Scene(self.dir, n=n)
            s.others, s.after_others = [entity("ceiling", 300, 190, 200, 10, role="target")], []
            captures.append(s.capture())
        result = judged(record(*captures), self.dir, HELD)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        self.assertEqual(result["measured"]["unmeasured"], realism.UNREPORTED)
        self.assertEqual(result["measured"]["gone_and_met_again"], {"ceiling": [2, 3]})
        # Met once, gone: a brick the hit broke - still left to the probe.
        once = judged(record(*captures[:2]), self.dir)["physics.contact_drawn"]
        self.assertEqual(once["status"], "PASS", once["summary"])

    # -- MINOR-4 ---------------------------------------------------------------------------

    def test_sparks_at_the_contact_have_faded_by_the_third_frame(self):
        # Probe P3: a burst of sparks still on screen in the frame after, over an undrawn ceiling.
        s = Scene(self.dir)
        for dx in range(-8, 9, 2):
            paint(s.after, disc(s.cx + dx, 196, 3), (255, 240, 180))
        result = judged(record(s.capture(third=True)), self.dir)["physics.contact_drawn"]
        self.assertEqual(result["status"], "FAIL", result["summary"])
        # A drawn wall is still there in the third frame.
        w = Scene(self.dir, n=2)
        for image in (w.at, w.after, w.later):
            paint(image, rect(300, 190, 500, 200), (220, 220, 230))
        self.assertEqual(judged(record(w.capture(third=True)), self.dir)["physics.contact_drawn"]["status"],
                         "PASS")
        # PINNED: a record without the third frame (a bot before 1.2.0) reads the sparks as drawn.
        self.assertEqual(judged(record(s.capture()), self.dir)["physics.contact_drawn"]["status"], "PASS")

    # -- MAJOR-4 ---------------------------------------------------------------------------

    def extent(self, draw, collider=12, drawn_box=20):
        """The drawn extent of a ball drawn by `draw(image, cx, cy, s)` in the frame after the turn
        (third-frame records: read there, against the third frame)."""
        s = Scene(self.dir, drawn=drawn_box, collider=collider)
        ax, ay = s.after_at()
        draw(s.after, ax, ay, s)
        return judged(record(s.capture(third=True)), self.dir)["physics.drawn_extent"]

    def test_a_ball_its_collider_size_passes_away_from_the_impact(self):
        result = self.extent(lambda image, x, y, s: paint(image, disc(x, y, 12), (240, 200, 40)))
        self.assertEqual(result["status"], "PASS", result["summary"])
        self.assertTrue(0.9 <= result["measured"]["across"]["ball"] <= 1.15, result["measured"])

    def test_a_squash_on_the_hit_frame_is_not_the_body(self):
        # Probe P6: squashed 1.35 x 0.75 on the frame of the hit, its collider's size after.
        def draw(image, x, y, s):
            paint(s.at, lambda px, py: ((px - s.cx) / 8.1) ** 2 + ((py - s.cy) / 4.5) ** 2 <= 1,
                  (240, 200, 40))
            paint(image, disc(x, y, 12), (240, 200, 40))
        result = self.extent(draw)
        self.assertEqual(result["status"], "PASS", result["summary"])

    def test_a_trail_behind_the_ball_is_not_the_body(self):
        # Probe P5: three 60 % ghosts behind it, along its travel (it moves down-left).
        def draw(image, x, y, s):
            for k in range(1, 4):
                paint(image, disc(x + 3 * k, y - 3 * k, 12), (240, 200, 40), alpha=0.6)
            paint(image, disc(x, y, 12), (240, 200, 40))
        result = self.extent(draw)
        self.assertEqual(result["status"], "PASS", result["summary"])

    def test_a_ball_drawn_three_times_its_collider_still_fails_across_its_travel(self):
        result = self.extent(lambda image, x, y, s: paint(image, disc(x, y, 36), (240, 200, 40)),
                             drawn_box=40)
        self.assertEqual(result["status"], "FAIL", result["summary"])
        self.assertGreater(result["measured"]["across"]["ball"], RULES["physics"]["max_drawn_to_collider"])
        self.assertIn("across its travel", result["summary"])

    def test_a_ball_masked_in_one_capture_and_read_in_another_is_read(self):
        # Under something reported in one capture's frame after, read across its travel in
        # another: it was read - not "masked in every frame".
        captures = []
        for n, masked in ((1, True), (2, False)):
            s = Scene(self.dir, n=n)
            ax, ay = s.after_at()
            paint(s.after, disc(ax, ay, 12), (240, 200, 40))
            if masked:
                s.after_others = [entity("trail", ax - 10, ay - 10, 20, 20, role="vfx")]
                s.later_others = []
            captures.append(s.capture(third=True))
        result = judged(record(*captures), self.dir)["physics.drawn_extent"]
        self.assertEqual(result["status"], "PASS", result["summary"])
        self.assertNotIn("masked_out", result["measured"])

    def test_a_ball_drawn_smaller_than_its_collider_fails_across_its_travel(self):
        result = self.extent(lambda image, x, y, s: paint(image, disc(x, y, 8), (240, 200, 40)))
        self.assertEqual(result["status"], "FAIL", result["summary"])
        self.assertLess(result["measured"]["across"]["ball"], RULES["physics"]["min_drawn_to_collider"])


class RealRecordingsR2(unittest.TestCase):
    """REAL: the play-realism 1.2.0 bot's recordings of the same builds (`*-r2`, README.md there):
    turns at moving and composite surfaces frozen on and read where the surface is, a third
    frame, the drawn extent away from the impact and across the travel (K7 review)."""

    def replay(self, name, project, rules=RULES, strength=RELEASE):
        directory = os.path.join(REAL, name, project)
        rec = real(os.path.join(name, project, "contact.json.gz"))
        return {c["id"]: c for c in realism.judge_contacts({"contact": rec}, directory, D2, rules,
                                                           project, strength)}

    SETS = (("68a12b7-collider-r2", ("desktop", "mobile")), ("cbac64e-collider-r2", ("desktop",)),
            ("96f5cea-collider-r2", ("desktop", "mobile")), ("96f5cea-r2", ("desktop", "mobile")),
            ("894b4b8-collider-r2", ("desktop", "mobile")))

    def test_the_bot_froze_on_passing_turns_and_kept_a_third_frame(self):
        for name, projects in self.SETS:
            for project in projects:
                rec = real(os.path.join(name, project, "contact.json.gz"))
                self.assertTrue(any(c["at"]["event"].get("passing") for c in rec["captures"]), name)
                self.assertTrue(all(c.get("later") and c["later"]["still"] for c in rec["captures"]), name)
                self.assertGreater(rec["game_ms"], 6000, name)

    def test_the_regressed_builds_still_turn_at_the_undrawn_ceiling(self):
        for name, projects in self.SETS[:2]:
            for project in projects:
                result = self.replay(name, project)["physics.contact_drawn"]
                self.assertEqual(result["status"], "FAIL", (name, project, result["summary"]))
                self.assertTrue(all(u["surface"] == "nothing reported" and u["moving"] == "-y"
                                    for u in result["measured"]["undrawn"]), result["measured"]["undrawn"])

    def test_the_accepted_builds_turn_only_at_drawn_surfaces_read_where_they_are(self):
        reads = {}
        for name, projects in self.SETS[2:]:
            for project in projects:
                result = self.replay(name, project)["physics.contact_drawn"]
                self.assertEqual(result["status"], "PASS", (name, project, result["summary"]))
                self.assertGreaterEqual(result["measured"]["verified"], 9, (name, project))
                for how, n in result["measured"]["reads"].items():
                    reads[how] = reads.get(how, 0) + n
        # Paddles carried to where they went and brick rows read along their face are among the
        # drawn contacts - before 1.2.0 neither was frozen on.
        self.assertGreater(reads.get("carried", 0), 5, reads)
        self.assertGreater(reads.get("along its face", 0), 5, reads)

    def test_the_bar_separates_every_r2_reading(self):
        drawn, undrawn = [], []
        for name, projects in self.SETS:
            for project in projects:
                m = self.replay(name, project)["physics.contact_drawn"]["measured"]
                undrawn += [u["edge"] for u in m["undrawn"]]
                drawn += [e for e in m["edges"] if e >= RULES["contact"]["min_edge"]]
        self.assertLess(max(undrawn), RULES["contact"]["min_edge"] / 2.5)
        self.assertGreater(min(drawn), RULES["contact"]["min_edge"] * 2)

    def test_drawn_extent_away_from_the_impact(self):
        hi = RULES["physics"]["max_drawn_to_collider"]
        for project in ("desktop", "mobile"):
            # 894b4b8: the collider is the solid disc - PASS with a margin, whatever the share.
            for share in (0.3, 0.4, 0.5):
                rules = copy.deepcopy(RULES)
                rules["contact"]["solid_share"] = share
                result = self.replay("894b4b8-collider-r2", project, rules)["physics.drawn_extent"]
                self.assertEqual(result["status"], "PASS", (project, share, result["summary"]))
                self.assertTrue(all(0.95 <= v <= 1.23 for v in result["measured"]["across"].values()),
                                result["measured"]["across"])
            result = self.replay("894b4b8-collider-r2", project)["physics.drawn_extent"]
            self.assertTrue(all(v <= 1.1 for v in result["measured"]["across"].values()), result["measured"])
            # r1 96f5cea: its solid disc twice its collider, as the 1.1.0 recording read it.
            r1 = self.replay("96f5cea-collider-r2", project)["physics.drawn_extent"]
            self.assertEqual(r1["status"], "FAIL")
            self.assertTrue(all(1.9 <= v <= 2.1 for v in r1["measured"]["across"].values()), r1["measured"])
            # 68a12b7: the enlarged ball.
            head = self.replay("68a12b7-collider-r2", project)["physics.drawn_extent"]
            self.assertEqual(head["status"], "FAIL")
            self.assertTrue(all(v > hi for v in head["measured"]["across"].values()), head["measured"])

    def test_honest_colliders_stay_under_the_contact_bar(self):
        for name, projects in self.SETS:
            if "collider" not in name:
                continue
            for project in projects:
                m = self.replay(name, project)["physics.drawn_extent"]["measured"]
                self.assertTrue(m["collider_to_contact"], (name, project))
                self.assertTrue(all(v < 0.95 for v in m["collider_to_contact"].values()),
                                (name, project, m["collider_to_contact"]))


class Generalizes(unittest.TestCase):
    """SYNTHETIC (built here, not recorded): another shape and family - a block patrolling a
    ledge (a hazard with a rect collider, turning on x) - is read the same way. No second real
    2D game with moving bodies was recorded: the golden 2D port moves none (its contact test
    ends `no projectile in play` and reports nothing)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wgf-general-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def patrol(self, wall_drawn, drawn_w):
        at, after = canvas(), canvas()
        # The block (collider 16 x 16) moving +x turned with its right edge at x 420.
        cx, cy = 412.0, 200.0
        if wall_drawn:
            for image in (at, after):
                paint(image, rect(420, 150, 430, 250), (90, 60, 40))
        paint(at, rect(cx - drawn_w / 2, cy - drawn_w / 2, cx + drawn_w / 2, cy + drawn_w / 2),
              (230, 80, 80))

        def block(x):
            return entity("crawler", x - drawn_w / 2, cy - drawn_w / 2, drawn_w, drawn_w,
                          role="hazard", collider=["rect", x - 8, cy - 8, 16, 16])
        for name, image in (("contact-1-at", at), ("contact-1-after", after)):
            with open(os.path.join(self.dir, name + ".png"), "wb") as handle:
                handle.write(encode_png(image))
        frames = [{"t": 0.0, "e": [block(cx - 5)], "pf": None},
                  {"t": 16.7, "e": [block(cx)], "pf": None},
                  {"t": 33.3, "e": [block(cx - 5)], "pf": None}]
        return record({"n": 1, "unit_id": "u1",
                       "at": {"frame": "contact-1-at", "still": True, "clip": dict(CLIP),
                              "event": {"kind": "reversal", "id": "crawler",
                                        "turns": [{"axis": 0, "sign": 1, "speed": 5.0}]},
                              "frames": frames},
                       "after": {"frame": "contact-1-after", "still": True, "clip": dict(CLIP),
                                 "frames": [{"t": 333.0, "e": [block(cx - 80)], "pf": None}]}})

    def test_a_patrol_turning_at_a_drawn_pillar_passes_and_at_nothing_fails(self):
        bars = dict(RULES)
        bars["contact"] = dict(RULES["contact"], roles=["hazard"])
        drawn = realism.judge_contacts(self.patrol(True, 18), self.dir, D2, bars, "desktop", RELEASE)
        self.assertEqual({c["id"]: c["status"] for c in drawn},
                         {"physics.contact_drawn": "PASS", "physics.drawn_extent": "PASS"})
        bare = realism.judge_contacts(self.patrol(False, 40), self.dir, D2, bars, "desktop", RELEASE)
        self.assertEqual({c["id"]: c["status"] for c in bare},
                         {"physics.contact_drawn": "FAIL", "physics.drawn_extent": "FAIL"})
