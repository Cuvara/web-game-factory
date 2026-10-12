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
        self.at, self.after = canvas(), canvas()
        self.others = []
        self.after_others = []

    def turned_at(self):
        return ball(self.cx, self.cy, self.drawn, self.collider)

    def capture(self, kind="reversal"):
        cy = self.cy
        frames = [
            {"t": 0.0, "e": [ball(self.cx - 4, cy + 6, self.drawn, self.collider)] + self.others, "pf": None},
            {"t": 16.7, "e": [self.turned_at()] + self.others, "pf": None},
            {"t": 33.3, "e": [ball(self.cx + 4, cy + 6, self.drawn, self.collider)] + self.others, "pf": None},
        ]
        after = [{"t": 333.3, "e": [ball(self.cx + 60, cy + 90, self.drawn, self.collider)]
                  + (self.after_others if self.after_others is not None else []), "pf": None}]
        for name, image in ((f"contact-{self.n}-at", self.at), (f"contact-{self.n}-after", self.after)):
            with open(os.path.join(self.directory, name + ".png"), "wb") as handle:
                handle.write(encode_png(image))
        return {"n": self.n, "unit_id": "u1",
                "at": {"frame": f"contact-{self.n}-at", "still": True, "clip": dict(CLIP),
                       "event": {"kind": kind, "id": "ball",
                                 "turns": [{"axis": 1, "sign": -1, "speed": 6.0}]},
                       "frames": frames},
                "after": {"frame": f"contact-{self.n}-after", "still": True, "clip": dict(CLIP),
                          "frames": after}}


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

    def test_a_composite_row_is_left_to_the_probe(self):
        s = self.scene()
        row = entity("bricks", 300, 186, 200, 14, role="target", render="composite")
        s.others, s.after_others = [row], [row]
        result = judged(record(s.capture()), self.dir, MVP)["physics.contact_drawn"]
        self.assertEqual(result["status"], "WARNING")
        self.assertEqual(result["measured"]["unverified"], {"composite surface": 1})

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

    def test_frames_too_far_apart_are_not_read(self):
        s = self.scene()
        capture = s.capture()
        for i, f in enumerate(capture["at"]["frames"]):
            f["t"] = 200.0 * i
        result = judged(record(capture), self.dir, MVP)["physics.contact_drawn"]
        self.assertEqual(result["measured"]["unverified"], {"frames too far apart": 1})

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
            self.assertTrue(all(v > RULES["contact"]["max_collider_to_contact"] for v in reach.values()), reach)
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
        still["win"] = {"sampled": {"frames": [[entity("ball", 394, 200, 12, 12)]] * 5, "viewport": [1280, 720]}}
        self.assertEqual(judged(still, self.dir, HELD)["physics.contact_drawn"]["status"], "PASS")

    def test_a_faint_wall_is_not_a_drawn_wall(self):
        # Not a bypass: a wall drawn at 8 % opacity reads as the background it is blended into.
        s = Scene(self.dir)
        for image in (s.at, s.after):
            paint(image, rect(300, 190, 500, 200), (220, 220, 230), alpha=0.08)
        self.assertEqual(judged(record(s.capture()), self.dir)["physics.contact_drawn"]["status"], "FAIL")


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
