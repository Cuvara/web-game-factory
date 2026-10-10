"""The baseline comparison (scripts/wgf_playability/baseline.py): a candidate build held to the
build a person accepted, quantity by quantity, unit by unit - first on synthetic profiles and
records (every check fails what it must, passes what it must, says unmeasured where a build does
not report, honours a person's recorded change and nothing else), then REPLAYED on real
measurements of the two 2026-10 validation games (scripts/tests/fixtures/real/baseline-compare/
README.md): the regressed loop heads must FAIL against the accepted r1 builds, each accepted
build must PASS against its own repeat measurement, and the current candidates' results are
asserted as they were measured.

    python -m unittest scripts.tests.test_baseline_compare
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgf_playability import baseline, realism  # noqa: E402
from wgf_playability.step import PlayabilityStep  # noqa: E402
from wgflib import genre_models  # noqa: E402

RULES = baseline.load_rules()
REALISM = realism.load_rules()
TOL = genre_models.implementation().get("difficulty_tolerance")
REAL = os.path.join(HERE, "fixtures", "real", "baseline-compare")
# Release as a run holds it: an unmeasured comparison is not passed.
HELD = baseline.strength_for(RULES, "release", held=lambda cid: "not passed at release")
MVP = baseline.strength_for(RULES, "mvp")


def path_layout(*lengths, width=8):
    return {"width": width, "segments": [{"t": "line", "len": n} for n in lengths]}


def content(units, tuning=None):
    data = {"schema": "wgf-content/1", "units": units}
    if tuning is not None:
        data["tuning"] = tuning
    return data


def unit(uid, index, layout=None, elements=None, difficulty=None, par=None):
    entry = {"id": uid, "index": index}
    if layout is not None:
        entry["layout"] = layout
    if elements is not None:
        entry["elements"] = elements
    if difficulty is not None:
        entry["difficulty"] = difficulty
    if par is not None:
        entry.setdefault("layout", {})["par_s"] = par
    return entry


def naive_run(policy, asked, unit_id, won, ms, played=None):
    return {"policy": policy, "asked": asked, "unit_id": unit_id, "entered": True, "won": won,
            "clear_ms": ms if won else None, "played_ms": played or ms, "losses": 0}


def records(naive=(), survey=(), start=500, fps_frames=1200, elapsed=20000, sizes=None):
    win = {"health": {"frames": {"count": fps_frames, "gap_max_ms": 40},
                      "worker": {"elapsed_ms": elapsed}},
           "sampled": {"frames": [[["paddle", "player", 1, 0, 0] + list(sizes or (80, 20))]]}}
    return {"first-session": {"playingMs": start, "observerMs": 0},
            "win": win,
            "naive": {"applies": True, "runs": list(naive)},
            "survey": {"applies": True, "unit_ms": 12000, "visits": list(survey)}}


def visit(uid, kinds, won_ms=None, difficulty=None):
    return {"asked": uid, "entered": True, "kinds_by_role": {"threat": kinds},
            "difficulty": difficulty or {}, "won": won_ms is not None, "lost": False,
            "duration_ms": won_ms}


ACCEPTED_UNITS = [unit("a", 1, path_layout(100, 120), ["ramp"], {"speed": 0.2}, 30),
                  unit("b", 2, path_layout(200, 40), ["ramp", "rail"], {"speed": 0.4}, 40),
                  unit("c", 3, path_layout(300), ["rail"], {"speed": 0.6}, 50)]
TUNING = {"ball": {"speed": 320, "radius": 11}, "paddle": {"width": 96}}


def profile(units=None, tuning=TUNING, recs=None, data=True):
    return baseline.profile(recs or records(), content(copy.deepcopy(
        ACCEPTED_UNITS if units is None else units), tuning) if data else None, None, None,
        RULES)


def checks(accepted, candidate, changes=None, strength=HELD):
    found = baseline.compare(accepted, candidate, RULES, REALISM, changes, strength,
                             difficulty_tolerance=TOL)
    return {c["id"]: c for c in found}


class TheChecks(unittest.TestCase):
    def test_every_check_is_reported_once_in_order(self):
        found = baseline.compare(profile(), profile(), RULES, REALISM, None, HELD,
                                 difficulty_tolerance=TOL)
        self.assertEqual([c["id"] for c in found], list(baseline.IDS))

    def test_the_same_content_passes_the_content_checks(self):
        got = checks(profile(), profile())
        for cid in ("baseline.units_kept", "baseline.unit_content", "baseline.unit_extent",
                    "baseline.tuning", "baseline.difficulty_order"):
            self.assertEqual(got[cid]["status"], "PASS", got[cid]["summary"])

    def test_a_unit_removed_or_renamed_fails(self):
        units = copy.deepcopy(ACCEPTED_UNITS)
        units[1]["id"] = "b-renamed"
        got = checks(profile(), profile(units))["baseline.units_kept"]
        self.assertEqual(got["status"], "FAIL")
        self.assertTrue(got["required"])
        self.assertIn("QUALITY REGRESSION", got["summary"])
        self.assertIn("b: gone", got["summary"])

    def test_a_changed_layout_or_element_set_fails(self):
        units = copy.deepcopy(ACCEPTED_UNITS)
        units[0]["layout"]["segments"][0]["len"] = 101
        units[2]["elements"] = ["rail", "bumper"]
        got = checks(profile(), profile(units))["baseline.unit_content"]
        self.assertEqual(got["status"], "FAIL")
        bad = {(i["unit"], i["quantity"]) for i in got["measured"]["items"]
               if i["verdict"] == "regressed"}
        self.assertEqual(bad, {("a", "layout"), ("c", "elements")})

    def test_a_unit_s_own_tuning_changed_fails(self):
        # Real (K7, 2D 0db72b6 against 96f5cea): w3-l2's rows were re-laid AND its
        # `descend.interval_s` moved 4.2 -> 4.6; a scalar inside an accepted unit's layout is
        # that unit's tuning, outside every geometry sequence, and is compared too.
        rows = ["##.###.##", "#.#.#.#.#"]
        a = profile([unit("w3-l2", 1, {"rows": rows, "descend": {"interval_s": 4.2}})])
        c = profile([unit("w3-l2", 1, {"rows": rows, "descend": {"interval_s": 4.6}})])
        got = checks(a, c)["baseline.unit_content"]
        self.assertEqual(got["status"], "FAIL")
        bad = [i for i in got["measured"]["items"] if i["verdict"] == "regressed"]
        self.assertEqual([(i["unit"], i["quantity"]) for i in bad],
                         [("w3-l2", "layout.descend.interval_s")])
        same = profile([unit("w3-l2", 1, {"rows": rows, "descend": {"interval_s": 4.2}})])
        self.assertEqual(checks(a, same)["baseline.unit_content"]["status"], "PASS")

    def test_a_layout_written_another_way_is_the_same_layout(self):
        units = copy.deepcopy(ACCEPTED_UNITS)
        units[0]["layout"] = {"pieces": [{"t": "line", "len": 100.0}, {"t": "line", "len": 120}],
                              "width": 8, "par_s": 30}
        self.assertEqual(checks(profile(), profile(units))["baseline.unit_content"]["status"],
                         "PASS")

    def test_a_cut_course_fails_extent_and_par(self):
        units = copy.deepcopy(ACCEPTED_UNITS)
        units[2]["layout"] = path_layout(60, width=8)
        units[2]["layout"]["par_s"] = 20
        got = checks(profile(), profile(units))["baseline.unit_extent"]
        self.assertEqual(got["status"], "FAIL")
        regressed = {(i["unit"], i["quantity"]): i for i in got["measured"]["items"]
                     if i["verdict"] == "regressed"}
        # The unit, and the whole game it is part of.
        self.assertEqual(set(regressed), {("c", "extent"), ("c", "par_s"), ("*", "total.extent"),
                                          ("*", "total.par_s")})
        self.assertEqual(regressed[("c", "extent")]["ratio"], 0.2)

    def test_every_unit_renamed_and_cut_still_fails_on_the_whole_game(self):
        units = [unit(f"new-{u['id']}", u["index"], path_layout(30), u.get("elements"),
                      u.get("difficulty"), 20) for u in copy.deepcopy(ACCEPTED_UNITS)]
        got = checks(profile(), profile(units))
        self.assertEqual(got["baseline.units_kept"]["status"], "FAIL")
        extent = got["baseline.unit_extent"]
        self.assertEqual(extent["status"], "FAIL")
        totals = {i["quantity"]: i for i in extent["measured"]["items"]}
        self.assertEqual(totals["total.extent"]["ratio"], round(90 / 760, 3))
        self.assertEqual(totals["total.par_s"]["verdict"], "regressed")

    def test_a_grid_unit_counts_its_solid_cells(self):
        grid = [unit("g", 1, {"rows": [".#######.", "####M####"], "par_time_s": 22})]
        fewer = [unit("g", 1, {"rows": ["##########"], "par_time_s": 22})]
        a, c = profile(grid), profile(fewer)
        self.assertEqual(a["units"]["g"]["extent"], {"value": 16, "unit": "cells", "kind": "grid"})
        self.assertEqual(c["units"]["g"]["extent"]["value"], 10)
        self.assertEqual(a["units"]["g"]["par_s"], 22)
        self.assertEqual(checks(a, c)["baseline.unit_extent"]["status"], "FAIL")

    def test_a_tuning_value_changed_or_gone_fails(self):
        moved = copy.deepcopy(TUNING)
        moved["ball"]["speed"] = 425
        del moved["paddle"]
        got = checks(profile(), profile(tuning=moved))["baseline.tuning"]
        self.assertEqual(got["status"], "FAIL")
        keys = {i["quantity"] for i in got["measured"]["items"] if i["verdict"] == "regressed"}
        self.assertEqual(keys, {"ball.speed", "paddle.width"})

    def test_difficulty_values_moved_or_inverted_fail(self):
        units = copy.deepcopy(ACCEPTED_UNITS)
        units[0]["difficulty"] = {"speed": 0.7}
        got = checks(profile(), profile(units))["baseline.difficulty_order"]
        self.assertEqual(got["status"], "FAIL")
        quantities = {i["quantity"] for i in got["measured"]["items"] if i["verdict"] == "regressed"}
        self.assertEqual(quantities, {"speed", "speed.order"})
        within = copy.deepcopy(ACCEPTED_UNITS)
        within[0]["difficulty"] = {"speed": 0.2 + TOL / 2}
        self.assertEqual(checks(profile(), profile(within))["baseline.difficulty_order"]["status"],
                         "PASS")

    def test_drawn_kinds_changed_fail(self):
        a = profile(recs=records(survey=[visit("a", ["spike"]), visit("b", ["spike", "gem"])]))
        c = profile(recs=records(survey=[visit("a", ["spike"]), visit("b", ["spike"])]))
        got = checks(a, c)["baseline.unit_kinds"]
        self.assertEqual(got["status"], "FAIL")
        self.assertIn("gone ['gem']", got["summary"])

    def test_a_probe_that_names_no_kind_is_unmeasured_not_an_empty_set(self):
        # Observed (2D 96f5cea, 2026-10-10): 120 content entities drawn in w1-l1, none with a
        # kind - the accepted build predates entities[].kind.
        bare = visit("a", [])
        bare.update(content_entities=120, unkinded=120)
        a = profile(recs=records(survey=[bare]))
        self.assertNotIn("kinds", a["units"]["a"])
        c = profile(recs=records(survey=[visit("a", ["ball", "brick"])]))
        got = checks(a, c)["baseline.unit_kinds"]
        self.assertEqual((got["status"], got["required"]), ("WARNING", False))
        self.assertEqual(got["measured"]["unmeasured"], baseline.ACCEPTED_UNMEASURED)
        self.assertEqual(got["measured"]["regressed"], 0)

    def test_a_person_s_recorded_change_is_listed_never_hidden(self):
        units = copy.deepcopy(ACCEPTED_UNITS)
        units[2]["layout"] = dict(path_layout(60), par_s=20)
        changes, invalid = baseline.accepted_changes({"init": {"accepted_changes": [
            {"check": "baseline.unit_extent", "unit": "c", "quantity": "extent",
             "reason": "cut on purpose after the playtest", "decided_by": "a person"},
            {"check": "baseline.unit_extent", "unit": "c", "quantity": "par_s",
             "reason": ""},
            "not an entry"]}})
        self.assertEqual(len(changes), 1)
        self.assertEqual(len(invalid), 2)
        got = checks(profile(), profile(units), changes)["baseline.unit_extent"]
        # Par was cut too, and its entry names no reason: still a regression.
        self.assertEqual(got["status"], "FAIL")
        verdicts = {(i["unit"], i["quantity"]): i["verdict"] for i in got["measured"]["items"]}
        self.assertEqual(verdicts[("c", "extent")], "accepted-change")
        self.assertEqual(verdicts[("c", "par_s")], "regressed")
        self.assertEqual(got["measured"]["accepted_changes"][0]["reason"],
                         "cut on purpose after the playtest")
        both = changes + [{"check": "baseline.unit_extent", "unit": "c", "quantity": "par_s",
                           "reason": "par follows the cut", "decided_by": "a person"}]
        got = checks(profile(), profile(units), both)["baseline.unit_extent"]
        self.assertEqual(got["status"], "PASS")
        self.assertIn("2 changed with a person's recorded reason", got["summary"])

    def test_a_course_cleared_in_a_fraction_of_its_time_fails(self):
        a = profile(recs=records(naive=[naive_run("steady", None, "a", False, 25000)]))
        c = profile(recs=records(naive=[naive_run("steady", None, "a", True, 6800)]))
        got = checks(a, c)["baseline.clear_time"]
        self.assertEqual(got["status"], "FAIL")
        self.assertIn("ratio at most 0.272", got["summary"])

    def test_lower_bounds_never_decide_more_than_they_show(self):
        # The accepted build not cleared in 25 s, the candidate cleared at 19 s: the true ratio
        # is at most 0.76, which the bar cannot fail - undetermined, so unmeasured overall.
        a = profile(recs=records(naive=[naive_run("steady", None, "a", False, 25000)]))
        c = profile(recs=records(naive=[naive_run("steady", None, "a", True, 19000)]))
        got = checks(a, c)["baseline.clear_time"]
        self.assertEqual((got["status"], got["required"]), ("WARNING", False))
        self.assertEqual(got["measured"]["unmeasured"], baseline.UNDETERMINED)
        self.assertIn("ratio at most 0.76", got["summary"])
        # Both cleared, within the bar: a pass.
        a = profile(recs=records(naive=[naive_run("steady", None, "a", True, 20000)]))
        c = profile(recs=records(naive=[naive_run("steady", None, "a", True, 14000)]))
        self.assertEqual(checks(a, c)["baseline.clear_time"]["status"], "PASS")

    def test_a_unit_made_easier_beyond_the_band_fails_clear_rate(self):
        runs = REALISM["clear_rate"]["runs"]
        a = profile(recs=records(naive=[naive_run("jitter", "b", "b", i < 1, 20000, 25000)
                                        for i in range(runs)]))
        c = profile(recs=records(naive=[naive_run("jitter", "b", "b", True, 9000)
                                        for _ in range(runs)]))
        got = checks(a, c)["baseline.clear_rate"]
        self.assertEqual(got["status"], "FAIL")
        same = profile(recs=records(naive=[naive_run("jitter", "b", "b", i < 1, 20000, 25000)
                                           for i in range(runs)]))
        self.assertEqual(checks(a, same)["baseline.clear_rate"]["status"], "PASS")

    def test_a_role_drawn_another_size_fails(self):
        a = profile(recs=records(sizes=(80, 20)))
        c = profile(recs=records(sizes=(130, 20)))
        got = checks(a, c)["baseline.entity_size"]
        self.assertEqual(got["status"], "FAIL")
        self.assertEqual(checks(a, profile(recs=records(sizes=(84, 20))))[
            "baseline.entity_size"]["status"], "PASS")

    def test_a_slower_start_or_frame_rate_fails(self):
        a = profile(recs=records(start=600, fps_frames=1200))
        slow = profile(recs=records(start=4000, fps_frames=1200))
        choppy = profile(recs=records(start=600, fps_frames=700))
        self.assertEqual(checks(a, slow)["baseline.responsiveness"]["status"], "FAIL")
        self.assertEqual(checks(a, choppy)["baseline.responsiveness"]["status"], "FAIL")
        self.assertEqual(checks(a, profile(recs=records(start=900, fps_frames=1100)))[
            "baseline.responsiveness"]["status"], "PASS")

    def test_the_start_is_timed_from_the_page_s_first_byte(self):
        # Real (K7, 2026-10-10, 3D 43c08e2 against 64ff4c6): the preview answered the
        # candidate's navigation after 2301 ms (time to first byte) and play began 500 ms
        # later; the accepted build's first byte came at 11 ms and play at 719 ms. The wait
        # for the first byte is the local server's, never the game's boot.
        def nav(playing, ttfb):
            recs = records(start=playing)
            recs["first-session"]["health"] = {"nav": {"ttfb_ms": ttfb, "playing_ms": playing}}
            return recs
        a, c = profile(recs=nav(719, 11)), profile(recs=nav(2801, 2301))
        self.assertEqual(a["responsiveness"]["start_ms"], 708)
        self.assertEqual(c["responsiveness"]["start_ms"], 500)
        self.assertEqual(checks(a, c)["baseline.responsiveness"]["status"], "PASS")
        # A game whose own boot is that much slower still fails.
        self.assertEqual(checks(a, profile(recs=nav(4801, 2301)))[
            "baseline.responsiveness"]["status"], "FAIL")

    def test_a_degraded_host_never_passes_or_fails_a_timing(self):
        a = profile(recs=records(start=600))
        a["degraded"]["first-session"] = a["degraded"]["win"] = True
        a["degraded"]["act"] = True
        got = checks(a, profile(recs=records(start=6000)))["baseline.responsiveness"]
        self.assertEqual(got["status"], "BLOCKED")
        self.assertEqual(got["measured"]["unmeasured"], baseline.DEGRADED)
        # An accepted naive play the host slowed makes the candidate look fast: not a
        # regression, and not a pass either. Observed on this machine (2026-10-10): the
        # accepted 3D build's naive recording degraded on every attempt while another build
        # was played beside it.
        a = profile(recs=records(naive=[naive_run("steady", None, "a", False, 25000)]))
        a["degraded"]["naive"] = True
        c = profile(recs=records(naive=[naive_run("steady", None, "a", True, 6800)]))
        for cid in ("baseline.clear_time", "baseline.clear_rate"):
            got = checks(a, c)[cid]
            self.assertEqual((got["status"], got["required"]), ("BLOCKED", True), cid)

    def test_what_the_accepted_build_cannot_report_is_reported_never_passed_or_held(self):
        # Observed (3D 64ff4c6, the accepted r1 build): no content data file, a probe with no
        # content unit. Nothing the candidate can do measures the accepted build: reported as
        # unmeasured on the accepted build - a WARNING, never a pass - and not held.
        a = profile(data=False)
        got = checks(a, profile())
        for cid in ("baseline.units_kept", "baseline.unit_content", "baseline.unit_extent",
                    "baseline.tuning", "baseline.difficulty_order", "baseline.unit_kinds"):
            self.assertEqual((got[cid]["status"], got[cid]["required"]), ("WARNING", False), cid)
            self.assertTrue(got[cid]["summary"].startswith("unmeasured on the accepted build"))
            self.assertEqual(got[cid]["measured"]["unmeasured"], baseline.ACCEPTED_UNMEASURED)

    def test_what_the_candidate_does_not_report_is_held_at_release(self):
        # The accepted build declares its layouts; the candidate ships no content data file
        # (its units reached through the probe): unmeasured on the candidate, held.
        reach = records(survey=[visit(u["id"], ["x"]) for u in ACCEPTED_UNITS])
        c = profile(data=False, recs=reach)
        got = checks(profile(recs=reach), c)
        self.assertEqual(got["baseline.units_kept"]["status"], "PASS")
        for cid in ("baseline.unit_content", "baseline.unit_extent", "baseline.tuning"):
            self.assertEqual((got[cid]["status"], got[cid]["required"]), ("FAIL", True), cid)
            self.assertEqual(got[cid]["measured"]["unmeasured"], baseline.UNREPORTED)
        # Below release an unmeasured comparison is a warning, never a pass.
        below = checks(profile(recs=reach), c, strength=MVP)["baseline.unit_content"]
        self.assertEqual((below["status"], below["required"]), ("WARNING", False))

    def test_a_quantity_the_accepted_build_declares_none_of_is_not_held(self):
        got = checks(profile(tuning=None), profile())["baseline.tuning"]
        self.assertEqual(got["status"], "WARNING")
        self.assertFalse(got["required"])
        self.assertEqual(got["measured"]["unmeasured"], baseline.ACCEPTED_NONE)

    def test_units_reached_through_the_probe_count_when_no_data_file_declares_them(self):
        a = profile(data=False, recs=records(survey=[visit("a", ["x"]), visit("b", ["x"])]))
        c = profile(data=False, recs=records(survey=[visit("a", ["x"])]))
        got = checks(a, c)["baseline.units_kept"]
        self.assertEqual(got["status"], "FAIL")
        self.assertIn("b: gone", got["summary"])

    def test_a_measured_regression_holds_the_build_at_every_tier(self):
        units = copy.deepcopy(ACCEPTED_UNITS)[:2]
        for strength in (MVP, HELD, baseline.strength_for(RULES, None)):
            got = checks(profile(), profile(units), strength=strength)["baseline.units_kept"]
            self.assertEqual((got["status"], got["required"]), ("FAIL", True))


class ThePlaySettings(unittest.TestCase):
    def test_both_builds_survey_and_sample_the_accepted_units(self):
        settings = {"survey_units": ["a"], "survey_projects": [], "survey_ms": 0,
                    "survey_unit_ms": 0, "naive_units": [], "naive_repeats": 1}
        sufficiency = {"survey": {"projects": ["desktop"], "unit_s": 12, "total_s": 480}}
        out = baseline.play_settings(settings, ["u1", "u2", "u3", "u4", "u5"], REALISM,
                                     sufficiency)
        self.assertEqual(out["survey_units"], ["a", "u1", "u2", "u3", "u4", "u5"])
        self.assertEqual(out["survey_projects"], ["desktop"])
        self.assertEqual(out["survey_ms"], 480000)
        self.assertEqual(out["naive_units"], ["u3", "u5"])
        self.assertEqual(out["naive_repeats"], REALISM["clear_rate"]["runs"])
        self.assertEqual(settings["survey_units"], ["a"])  # a copy

    def test_the_accepted_build_is_the_design_s_floor_commit(self):
        self.assertIsNone(baseline.accepted_of({}))
        found = baseline.accepted_of({"existing_content": {
            "source": {"commit": "f" * 40, "baseline": "factory.init.accepted_baseline r1"},
            "unit_ids": ["a", "b"]}})
        self.assertEqual(found["commit"], "f" * 40)
        self.assertEqual(found["unit_ids"], ["a", "b"])
        self.assertIn("accepted_baseline", found["by"])


class TheStep(unittest.TestCase):
    """The step plays the accepted commit once per bot and settings, and compares."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-baseline-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def test_the_accepted_play_is_made_once_and_reused(self):
        step = PlayabilityStep(types.SimpleNamespace(params={}, id="playability"))
        calls = []

        def prepare(located, commit, repo, logs, context):
            calls.append(commit)
            os.makedirs(repo, exist_ok=True)
            return None

        def play(repo, out, logs, settings, context, *a, **k):
            os.makedirs(os.path.join(out, "desktop"), exist_ok=True)
            with open(os.path.join(out, "desktop", "naive.json"), "w") as handle:
                json.dump({"applies": True, "runs": []}, handle)
            return None

        step._prepare, step._play = prepare, play
        context = types.SimpleNamespace(run_dir=self.base)
        settings = {"survey_ms": 0, "ramp_extend_ms": 0, "start_timeout_ms": 1000,
                    "naive_run_ms": 0}
        first = step._play_accepted("x", "a" * 40, settings, RULES, context, 600)
        again = step._play_accepted("x", "a" * 40, settings, RULES, context, 600)
        self.assertEqual(calls, ["a" * 40])
        self.assertFalse(first["cached"])
        self.assertTrue(again["cached"])
        self.assertIn("naive", again["records"]["desktop"])
        other = dict(settings, naive_run_ms=1)
        step._play_accepted("x", "a" * 40, other, RULES, context, 600)
        self.assertEqual(len(calls), 2, "other settings are another play")

    def test_an_accepted_build_that_cannot_be_played_blocks_every_comparison(self):
        step = PlayabilityStep(types.SimpleNamespace(params={}, id="playability"))
        context = types.SimpleNamespace(run_dir=self.base, config={}, environment=None,
                                        current_step="playability")
        found, info = step._baseline_checks(
            {"commit": "a" * 40, "by": "test", "unit_ids": []},
            {"blocked": "pnpm build failed", "records": {}}, "b" * 40, self.base, {}, {}, {},
            REALISM, RULES, "release", context)
        self.assertEqual([c["id"] for c in found], list(baseline.IDS))
        self.assertTrue(all(c["status"] == "BLOCKED" and c["required"] for c in found))
        self.assertEqual(info["blocked_reason"], "pnpm build failed")

    def test_the_accepted_play_feeds_naive_clear_rate_only_when_it_names_its_units(self):
        named = {"records": {"desktop": {"naive": {"applies": True, "runs": [
            naive_run("jitter", None, "w1-l1", False, 25000)]}}}}
        self.assertIsNotNone(PlayabilityStep._accepted_naive(named, RULES))
        # Real (3D 64ff4c6): its probe reports no content unit, so its naive runs carry no
        # unit id - no per-unit clear rate exists to fall from.
        unnamed = {"records": {"desktop": {"naive": {"applies": True, "runs": [
            naive_run("jitter", None, None, False, 25000)]}}}}
        self.assertIsNone(PlayabilityStep._accepted_naive(unnamed, RULES))
        self.assertIsNone(PlayabilityStep._accepted_naive(None, RULES))

    def test_the_accepted_build_itself_is_not_compared(self):
        step = PlayabilityStep(types.SimpleNamespace(params={}, id="playability"))
        context = types.SimpleNamespace(run_dir=self.base, config={}, environment=None)
        found, info = step._baseline_checks(
            {"commit": "a" * 40, "by": "test", "unit_ids": []}, None, "a" * 40, self.base,
            {}, {}, {}, REALISM, RULES, "release", context)
        self.assertEqual(found, [])
        self.assertTrue(info["same_build"])


class TheReader(unittest.TestCase):
    """check-tiers.yaml baseline-compare: absent checks are NOT_APPLICABLE only for a run that
    adopted nothing or a visit that played the accepted build; otherwise UNMEASURED."""

    def status(self, report, design):
        from wgf_quality import registry
        tiers = registry.load()["tiers"]
        facts = {"reports": {"game-design": design, "playability-report": report}}
        return registry.check_status(tiers, "baseline-compare:baseline.units_kept", report,
                                     facts)[0]["status"]

    def test_absence_reads_as_the_run_was(self):
        report = {"verdict": "PASS", "checks": [{"id": "probe.present", "status": "PASS"}]}
        self.assertEqual(self.status(report, {}), "NOT_APPLICABLE")
        adopted = {"existing_content": {"source": {"commit": "a" * 40}}}
        self.assertEqual(self.status(report, adopted), "UNMEASURED")
        same = dict(report, baseline_comparison={"accepted_commit": "a", "commit": "a",
                                                 "same_build": True})
        self.assertEqual(self.status(same, adopted), "NOT_APPLICABLE")

    def test_a_quantity_the_accepted_build_declares_none_of_reads_not_applicable(self):
        from wgf_quality import registry
        tiers = registry.load()["tiers"]
        report = {"verdict": "PASS", "checks": [
            {"id": "baseline.tuning", "status": "WARNING", "required": False,
             "measured": {"unmeasured": baseline.ACCEPTED_NONE}}]}
        found = registry.check_status(tiers, "baseline-compare:baseline.tuning", report, {})
        self.assertEqual(found[0]["status"], "NOT_APPLICABLE")


# -- replayed on real measurements (fixtures/real/baseline-compare/README.md) ------------------

def real(name):
    with open(os.path.join(REAL, name + ".json"), encoding="utf-8") as handle:
        return json.load(handle)


def real_checks(accepted, candidate):
    return checks(real(accepted)["profile"], real(candidate)["profile"])


def regressed(check):
    return [(i.get("unit"), i.get("quantity")) for i in check["measured"]["items"]
            if i["verdict"] == "regressed"]


class TheRealGames(unittest.TestCase):
    """The two 2026-10 validation games, as measured on 2026-10-10 (K7)."""

    def test_the_fixtures_are_labelled_real_measurements(self):
        for name in sorted(os.listdir(REAL)):
            if not name.endswith(".json"):
                continue
            source = real(name[:-5])["_source"]
            self.assertRegex(source["commit"], r"^[0-9a-f]{40}$", name)
            self.assertIn("Real, not edited", source["capture"], name)
            files = source.get("records") or source.get("files")
            self.assertTrue(files and all(str(v).startswith("sha256:") for v in files.values()),
                            name)

    def test_K7_the_regressed_2d_head_fails_against_r1(self):
        got = real_checks("2d-96f5cea-accepted", "2d-68a12b7-regressed")
        # Every accepted level is still there, under its id - and nearly every one is another.
        self.assertEqual(got["baseline.units_kept"]["status"], "PASS")
        content = got["baseline.unit_content"]
        self.assertEqual(content["status"], "FAIL")
        self.assertEqual(sum(1 for u, q in regressed(content) if q == "layout"), 32)
        self.assertIn(("w3-l2", "layout.descend.interval_s"), regressed(content))
        # The opener cut from 16 bricks to 10 (H4), and 14 more levels smaller.
        extent = got["baseline.unit_extent"]
        self.assertEqual(extent["status"], "FAIL")
        w1 = next(i for i in extent["measured"]["items"]
                  if i.get("unit") == "w1-l1" and i["quantity"] == "extent")
        self.assertEqual((w1["accepted"], w1["candidate"], w1["verdict"]), (16, 10, "regressed"))
        self.assertEqual(extent["measured"]["regressed"], 15)
        # The speed curve and the tuning (H4).
        self.assertEqual(got["baseline.tuning"]["status"], "FAIL")
        self.assertEqual(got["baseline.difficulty_order"]["status"], "FAIL")
        self.assertIn(("w1-l1", "speed"), regressed(got["baseline.difficulty_order"]))
        # The paddle drawn 0.71 x as wide (H4).
        size = got["baseline.entity_size"]
        self.assertEqual(size["status"], "FAIL")
        player = next(i for i in size["measured"]["items"] if i["quantity"] == "player")
        self.assertEqual(player["ratio"][0], 0.714)
        # Its naive play was recorded on a degraded host: decided neither way, never passed.
        for cid in ("baseline.clear_time", "baseline.clear_rate"):
            self.assertEqual(got[cid]["status"], "BLOCKED", cid)

    def test_K7_the_regressed_3d_head_fails_against_r1(self):
        got = real_checks("3d-64ff4c6-accepted", "3d-1c6b099-regressed")
        # H7: the opening course held forward cleared in 6.18 s against 22.86 s on r1.
        clear = got["baseline.clear_time"]
        self.assertEqual(clear["status"], "FAIL")
        steady = next(i for i in clear["measured"]["items"] if i["quantity"] == "naive.steady")
        self.assertEqual((steady["accepted"]["fastest_s"], steady["candidate"]["fastest_s"],
                          steady["ratio"]), (22.86, 6.18, 0.27))
        # Never cleared under jittered input on r1 in 6 runs; cleared every time on the head.
        rate = got["baseline.clear_rate"]
        self.assertEqual(rate["status"], "FAIL")
        jitter = next(i for i in rate["measured"]["items"] if i["quantity"] == "naive.jitter")
        self.assertEqual((jitter["accepted"], jitter["candidate"]), ([0, 6], [6, 6]))
        # r1 ships no content data file and its probe reports no unit: its courses cannot be
        # read off it - reported, not held, never passed.
        for cid in ("baseline.units_kept", "baseline.unit_extent", "baseline.tuning"):
            self.assertEqual(got[cid]["measured"]["unmeasured"], baseline.ACCEPTED_UNMEASURED)

    def test_K7_the_regressed_3d_courses_are_cut_against_the_accepted_courses(self):
        # H6: the accepted courses as data (234-440 m) against the head's (38-124 m).
        accepted = real("3d-c340631-accepted-courses-data")["profile"]
        lengths = sorted(e["extent"]["value"] for e in accepted["units"].values())
        self.assertEqual((lengths[0], lengths[-1]), (234.02, 440.15))
        got = real_checks("3d-c340631-accepted-courses-data", "3d-1c6b099-data")
        self.assertEqual(got["baseline.units_kept"]["status"], "FAIL")
        self.assertEqual(got["baseline.units_kept"]["measured"]["regressed"], 12)
        extent = got["baseline.unit_extent"]
        self.assertEqual(extent["status"], "FAIL")
        total = next(i for i in extent["measured"]["items"] if i["quantity"] == "total.extent")
        self.assertEqual(total["ratio"], 0.21)
        self.assertEqual(got["baseline.tuning"]["status"], "FAIL")

    def test_K7_each_accepted_build_passes_against_its_own_repeat(self):
        for game, first, again in (("2d", "2d-96f5cea-accepted", "2d-96f5cea-repeat"),
                                   ("3d", "3d-64ff4c6-accepted", "3d-64ff4c6-repeat")):
            for a, c in ((first, again), (again, first)):
                got = real_checks(a, c)
                for cid, check in got.items():
                    self.assertNotIn(check["status"], ("FAIL", "BLOCKED"),
                                     f"{a} -> {c}: {cid}: {check['summary']}")
                    self.assertEqual(check["measured"]["regressed"], 0)
                decided = [cid for cid, check in got.items() if check["status"] == "PASS"]
                self.assertGreaterEqual(len(decided), 4, (game, decided))

    def test_K7_the_2d_candidate_as_measured(self):
        # Not tuned to pass: the current 2D candidate (main 0db72b6) keeps every accepted
        # level, its extents, pars, difficulty, drawn sizes and timings - and changes five
        # levels' layouts and the ball's collision radius, which no person recorded.
        got = real_checks("2d-96f5cea-accepted", "2d-0db72b6-candidate")
        self.assertEqual(got["baseline.unit_content"]["status"], "FAIL")
        self.assertEqual(sorted({u for u, _q in regressed(got["baseline.unit_content"])}),
                         ["w1-l7", "w2-l6", "w3-l1", "w3-l2", "w3-l7", "w4-l6", "w4-l7"])
        self.assertEqual(got["baseline.tuning"]["status"], "FAIL")
        self.assertEqual(sorted(q for _u, q in regressed(got["baseline.tuning"])),
                         ["ball-rebound.ball_radius_px", "descending-field.min_interval_s"])
        for cid in ("baseline.units_kept", "baseline.unit_extent", "baseline.difficulty_order",
                    "baseline.clear_rate", "baseline.entity_size", "baseline.responsiveness"):
            self.assertEqual(got[cid]["status"], "PASS", cid)

    def test_K7_the_3d_candidate_as_measured(self):
        # Played: the opening course held forward clears in 19.0 s against 22.86 s (0.83 x),
        # as often, drawn the same size, as responsive.
        got = real_checks("3d-64ff4c6-accepted", "3d-43c08e2-candidate")
        for cid in ("baseline.clear_time", "baseline.clear_rate", "baseline.entity_size",
                    "baseline.responsiveness"):
            self.assertEqual(got[cid]["status"], "PASS", cid)
        # Declared: the twelve accepted courses kept verbatim, their extents, pars and tuning -
        # and hairpin-rise's declared difficulty moved, out of order with switchbacks.
        got = real_checks("3d-c340631-accepted-courses-data", "3d-43c08e2-data")
        for cid in ("baseline.units_kept", "baseline.unit_content", "baseline.unit_extent",
                    "baseline.tuning"):
            self.assertEqual(got[cid]["status"], "PASS", cid)
        order = got["baseline.difficulty_order"]
        self.assertEqual(order["status"], "FAIL")
        self.assertIn(("hairpin-rise", "precision"), regressed(order))


if __name__ == "__main__":
    unittest.main()
