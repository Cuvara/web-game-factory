"""Browser QA (core/reference/browser-qa.yaml, scripts/wgf_verification/browser_qa.py): the
contract as data, the tiers, and the judging of the spec's records - one defect at a time on
a healthy fixture, the host-health rule for timing checks, and the replay of the records the
spec made of the two validation games (fixtures/browser-qa/).

    python -m unittest discover scripts/tests -p test_browser_qa.py
"""

import copy
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from browser_qa_fixture import DEGRADED, ORIGIN, healthy_records  # noqa: E402
from wgf_verification import browser_qa  # noqa: E402
from wgf_verification.model import BLOCKED, CATEGORIES, FAIL, PASS, WARNING  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
FIXTURES = os.path.join(HERE, "fixtures", "browser-qa")
CHECK_ID = re.compile(r"^[a-z]+\.[a-z0-9-]+(:[a-z0-9-]+)?$")   # verification-report checkId
CONTRACT = browser_qa.load_contract()


def judged(records, klass="release", hard=(), bundle=None, action_audio=("pause", "launch")):
    checks = browser_qa.judge(records, CONTRACT, klass=klass, hard_profiles=hard, bundle=bundle,
                              action_audio=list(action_audio))
    return {c.id: c for c in checks}


class Contract(unittest.TestCase):
    def test_versioned_and_every_check_is_tiered(self):
        self.assertRegex(str(CONTRACT["version"]), r"^\d+\.\d+\.\d+$")
        scopes = {"viewport", "once", "outcome", "offline"}
        for check in CONTRACT["checks"]:
            self.assertIn(check["tier"], ("hard", "quality", "advisory"), check["id"])
            self.assertIn(check["scope"], scopes, check["id"])
            self.assertIn(check["category"], CATEGORIES, check["id"])
            self.assertTrue(check.get("owner") and check.get("what"), check["id"])
        ids = [c["id"] for c in CONTRACT["checks"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_check_is_routed_to_its_owner(self):
        from wgf_triage import Routing
        routing = Routing.load()
        table = routing.producer("qa-report").get("verification_checks") or {}
        self.assertEqual(table.get("browser.run"), "browser")
        for check in CONTRACT["checks"]:
            self.assertIn(check["owner"], routing.dimensions, check["id"])
            self.assertEqual(table.get(f"browser.{check['id']}"), check["owner"], check["id"])

    def test_every_check_is_tiered_in_the_registry_as_it_states(self):
        from wgf_quality import registry
        checks, problems = registry.classify(registry.load(ROOT)["tiers"], ROOT)
        self.assertEqual(problems, [])
        for check in CONTRACT["checks"]:
            entry = checks[f"browser-qa:browser.{check['id']}"]
            self.assertEqual(entry["tier"], check["tier"], check["id"])
        self.assertEqual(checks["browser-qa-run:browser.run"]["tier"], "hard")

    def test_the_viewport_set(self):
        sizes = {(v["width"], v["height"]) for v in CONTRACT["viewports"]}
        for size in ((1920, 1080), (1280, 720), (1024, 768), (768, 1024), (390, 844)):
            self.assertIn(size, sizes)
        ids = {v["id"] for v in CONTRACT["viewports"]}
        self.assertIn(CONTRACT["audio_viewport"], ids)
        self.assertIn(CONTRACT["perf_viewport"], ids)
        self.assertTrue(set(CONTRACT["outcomes"]["viewports"]) <= ids)

    def test_the_request_is_covered(self):
        """Every browser-QA item of the 2026-10-07 quality request is a check of the contract."""
        ids = {c["id"] for c in CONTRACT["checks"]}
        for wanted in ("loads", "canvas", "ready", "first-interaction", "menus", "win", "lose",
                       "restart", "pause-resume", "hidden-pause", "console-errors", "page-errors",
                       "webgl-context", "overflow", "clipping", "ui-overlap", "ui-covers-play",
                       "safe-margins", "button-states", "context-menu", "audio-events",
                       "audio-loops", "audio-loudness", "audio-mute", "audio-hidden",
                       "load-time", "frame-stability", "memory-growth", "oversized-textures"):
            self.assertIn(wanted, ids)

    def test_shared_bars_are_read_not_copied(self):
        env = browser_qa.environment_bars(CONTRACT)
        for key in ("tick_ms", "stall_ms", "max_stall_ms", "max_stalled_share",
                    "max_server_wait_ms", "max_attempts"):
            self.assertIn(key, env)
        self.assertAlmostEqual(browser_qa.muted_level(CONTRACT), 0.001)

    def test_tiers_decide_what_is_required(self):
        defs = {c["id"]: c for c in CONTRACT["checks"]}
        self.assertTrue(browser_qa.required_for(defs["page-errors"], "development", CONTRACT))
        self.assertTrue(browser_qa.required_for(defs["console-errors"], "release", CONTRACT))
        self.assertFalse(browser_qa.required_for(defs["console-errors"], "development", CONTRACT))
        self.assertFalse(browser_qa.required_for(defs["safe-margins"], "release", CONTRACT))
        # A targeted profile that requires the context menu suppressed makes it a Hard Gate.
        self.assertFalse(browser_qa.required_for(defs["context-menu"], "development", CONTRACT))
        self.assertTrue(browser_qa.required_for(defs["context-menu"], "development", CONTRACT,
                                                {"context_menu_suppressed"}))


class Healthy(unittest.TestCase):
    def test_a_healthy_game_passes_every_check(self):
        checks = judged(healthy_records(CONTRACT))
        bad = {i: (c.status, c.message) for i, c in checks.items() if c.status != PASS}
        # Nothing in the bundle to read here: the offline asset checks are unmeasured.
        self.assertEqual(set(bad), {"browser.oversized-textures", "browser.asset-weight"}, bad)
        for check in checks.values():
            self.assertRegex(check.id, CHECK_ID)
            self.assertTrue(check.evidence)

    def test_one_check_per_viewport_and_once_per_build(self):
        checks = judged(healthy_records(CONTRACT))
        for v in CONTRACT["viewports"]:
            for cid in ("loads", "canvas", "context-menu", "ui-covers-play", "win", "restart"):
                self.assertIn(f"browser.{cid}:{v['id']}", checks)
        for cid in ("audio-events", "audio-loops", "frame-stability", "memory-growth"):
            self.assertIn(f"browser.{cid}", checks)

    def test_unmeasured_is_never_a_pass(self):
        checks = judged({})
        self.assertFalse(any(c.status == PASS for c in checks.values()
                             if c.id not in ("browser.oversized-textures",)))
        self.assertEqual(checks["browser.loads:mobile"].status, BLOCKED)
        self.assertEqual(checks["browser.frame-stability"].status, BLOCKED)


class Defects(unittest.TestCase):
    def setUp(self):
        self.records = healthy_records(CONTRACT)

    def vp(self, vid="desktop-standard"):
        return self.records[vid]["viewport"]

    def test_context_menu_left_open_fails_at_release(self):
        self.vp()["context_menu"]["events"] = [{"t": 1, "prevented": False, "target": "canvas"}]
        checks = judged(self.records)
        self.assertEqual(checks["browser.context-menu:desktop-standard"].status, FAIL)
        self.assertTrue(checks["browser.context-menu:desktop-standard"].required)
        # Quality tier: a WARNING in a development run, unless a profile makes it hard.
        self.assertEqual(judged(self.records, "development")
                         ["browser.context-menu:desktop-standard"].status, WARNING)
        hard = judged(self.records, "development", hard={"context_menu_suppressed"})
        self.assertEqual(hard["browser.context-menu:desktop-standard"].status, FAIL)
        self.assertIn("[hard]", hard["browser.context-menu:desktop-standard"].message)

    def test_page_errors_are_a_hard_gate(self):
        self.records["mobile"]["outcomes"]["watch"]["page_errors"] = ["TypeError: x is undefined"]
        check = judged(self.records, "development")["browser.page-errors:mobile"]
        self.assertEqual((check.status, check.required), (FAIL, True))

    def test_console_errors_of_the_game_not_of_the_environment(self):
        console = self.vp()["watch"]["console"]
        console.append({"type": "error", "text": "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT",
                        "url": "https://portal.example/sdk.js"})
        console.append({"type": "error", "text": "the portal said no", "url": "https://portal.example/sdk.js"})
        self.assertEqual(judged(self.records)["browser.console-errors:desktop-standard"].status, PASS)
        console.append({"type": "error", "text": "level 3 has no exit", "url": ORIGIN + "/assets/index.js"})
        self.assertEqual(judged(self.records)["browser.console-errors:desktop-standard"].status, FAIL)

    def test_webgl_context_loss(self):
        self.vp("tablet")["watch"]["runs"]["main"]["context_lost"] = [12000]
        self.assertEqual(judged(self.records, "development")["browser.webgl-context:tablet"].status, FAIL)

    def test_a_failed_request_of_the_game(self):
        self.vp()["watch"]["failed_requests"] = [{"url": ORIGIN + "/assets/sprites/boss.png",
                                                  "status": 404, "error": None}]
        self.assertEqual(judged(self.records)["browser.loads:desktop-standard"].status, FAIL)

    def test_menus_that_never_reach_play(self):
        self.vp("mobile")["started"].update(playing_ms=None, states=["title"], began=["play"])
        self.assertEqual(judged(self.records)["browser.menus:mobile"].status, FAIL)

    def test_overflow_clipping_overlap(self):
        layout = self.vp("mobile")["layouts"][1]
        layout["scroll"] = [390, 900]
        layout["controls"].append({"tag": "button", "text": "MENU", "box": [370, 12, 44, 44], "disabled": False})
        layout["controls"].append({"tag": "button", "text": "SOUND", "box": [340, 20, 44, 44], "disabled": False})
        checks = judged(self.records)
        self.assertEqual(checks["browser.overflow:mobile"].status, FAIL)
        self.assertEqual(checks["browser.clipping:mobile"].status, FAIL)
        self.assertEqual(checks["browser.ui-overlap:mobile"].status, FAIL)
        self.assertEqual(checks["browser.safe-margins:mobile"].status, WARNING)
        self.assertFalse(checks["browser.safe-margins:mobile"].required)

    def test_ui_over_a_critical_entity(self):
        covered = [{"id": "paddle", "role": "player", "kind": "paddle", "box": [600, 680, 80, 16],
                    "share": 0.6, "by": "div#pause-hint"}]
        clear = [dict(covered[0], share=0, by=None)]
        # A banner for one sample as play starts is not UI over play ...
        self.vp()["cover"] = [covered, clear, clear]
        self.assertEqual(judged(self.records)["browser.ui-covers-play:desktop-standard"].status, PASS)
        # ... a hint that stays over the paddle is (the 3D pause-hint lesson).
        self.vp()["cover"] = [clear, covered, covered, clear]
        check = judged(self.records)["browser.ui-covers-play:desktop-standard"]
        self.assertEqual(check.status, FAIL)
        self.assertIn("div#pause-hint", check.message)

    def test_pause_and_hidden(self):
        self.vp()["pause"].update(paused=True, resumed=False)
        self.vp("tablet")["hidden"].update(state_hidden=["playing", "playing"], still=False)
        checks = judged(self.records)
        self.assertEqual(checks["browser.pause-resume:desktop-standard"].status, FAIL)
        self.assertEqual(checks["browser.hidden-pause:tablet"].status, FAIL)

    def test_no_pause_control_is_reported_not_failed(self):
        self.vp()["pause"].update(declared=False, how="key:Escape", paused=False)
        check = judged(self.records)["browser.pause-resume:desktop-standard"]
        self.assertEqual((check.status, check.required), (WARNING, False))

    def test_flat_button_states(self):
        control = self.vp()["control_states"]["controls"][0]
        control["hover"] = dict(control["rest"])
        check = judged(self.records)["browser.button-states:desktop-standard"]
        self.assertEqual((check.status, check.required), (WARNING, False))

    def test_restart_that_does_not_return(self):
        self.records["desktop-wide"]["outcomes"]["restart"].update(reached=None)
        self.assertEqual(judged(self.records)["browser.restart:desktop-wide"].status, FAIL)

    def test_win_not_reached_in_the_window_is_unmeasured(self):
        self.records["tablet"]["outcomes"]["win"]["reached"] = None
        check = judged(self.records)["browser.win:tablet"]
        self.assertEqual((check.status, check.required), (WARNING, False))
        self.records["tablet"]["outcomes"]["win"]["reached"] = "lost"
        self.assertEqual(judged(self.records)["browser.win:tablet"].status, FAIL)


class Omissions(unittest.TestCase):
    """What the build OMITS (the probe reports no critical entity, no audio level; no runtime
    manifest) is held like a skipped check (quality-policy.yaml skipped_checks): at the
    release class BLOCKED and required, so the quality floor cannot pass over it; below it a
    WARNING. A game that genuinely has none of a thing (no pause or mute control) stays a
    WARNING at every class."""

    def setUp(self):
        self.records = healthy_records(CONTRACT)
        self.vp = self.records["desktop-standard"]["viewport"]

    def test_no_critical_entity_reported_is_blocked_at_release(self):
        self.vp["cover"] = [[], []]
        check = judged(self.records)["browser.ui-covers-play:desktop-standard"]
        self.assertEqual((check.status, check.required), (BLOCKED, True))
        check = judged(self.records, klass="development")["browser.ui-covers-play:desktop-standard"]
        self.assertEqual((check.status, check.required), (WARNING, False))

    def test_no_audio_reported_by_the_probe_is_blocked_at_release(self):
        self.vp["hidden"]["audio_hidden"] = None
        check = judged(self.records)["browser.audio-hidden"]
        self.assertEqual((check.status, check.required), (BLOCKED, True))
        check = judged(self.records, klass="development")["browser.audio-hidden"]
        self.assertEqual((check.status, check.required), (WARNING, False))

    def test_no_runtime_manifest_is_blocked_at_release(self):
        self.records["desktop-standard"]["clips"]["clips"]["manifest"] = 404
        checks = judged(self.records)
        for cid in ("browser.audio-clips", "browser.audio-loudness"):
            self.assertEqual((checks[cid].status, checks[cid].required), (BLOCKED, True), cid)

    def test_a_game_with_no_pause_or_mute_control_is_a_warning_at_release(self):
        self.vp["pause"] = {"tried": True, "paused": False, "declared": False, "how": "escape"}
        self.vp["mute"] = {"tried": False, "reason": "no mute control"}
        checks = judged(self.records)
        for cid in ("browser.pause-resume:desktop-standard", "browser.audio-mute"):
            self.assertEqual((checks[cid].status, checks[cid].required), (WARNING, False), cid)

    def test_a_golden_run_at_mvp_holds_an_omission_as_a_warning(self):
        # The golden runs are tier mvp (scripts/golden/harness.py), class development: an
        # omission there is the producer's WARNING, never what blocks verify.
        self.vp["hidden"]["audio_hidden"] = None
        checks = browser_qa.judge(self.records, CONTRACT, klass="development", tier="mvp",
                                  action_audio=["pause", "launch"])
        check = {c.id: c for c in checks}["browser.audio-hidden"]
        self.assertEqual((check.status, check.required), (WARNING, False))

    def test_a_page_never_hidden_during_play_is_blocked_at_every_class_and_says_why(self):
        # PR #56 CI, golden 3D: audio-hidden BLOCKED at class development. Not an omission:
        # the hidden probe found the game out of play (a dodge game left unsteered by the
        # context-menu and pause probes ends within seconds). A hard check the bot could not
        # make is BLOCKED wherever play started - unchanged - and the reason is now named.
        self.vp["hidden"] = {"tried": False, "reason": "not playing (lost)",
                             "reentered": "failed: lost"}
        for klass in ("development", "release"):
            check = judged(self.records, klass=klass)["browser.audio-hidden"]
            self.assertEqual((check.status, check.required), (BLOCKED, True), klass)
            self.assertIn("not playing (lost)", check.message)
            self.assertIn("failed: lost", check.message)

    def test_the_spec_brings_the_game_back_into_play_before_hiding_the_page(self):
        with open(browser_qa.SPEC, encoding="utf-8") as handle:
            spec = handle.read()
        body = spec[spec.index("async function hiddenProbe("):]
        body = body[:body.index("\n}\n")]
        self.assertLess(body.index("backToPlay("), body.index("setHidden(true)"))
        helper = spec[spec.index("async function backToPlay("):]
        helper = helper[:helper.index("\n}\n")]
        for step in ("resume(", "retryFrom(", "beginOf("):
            self.assertIn(step, helper)

    def test_the_rule_is_the_quality_policys(self):
        self.assertTrue(browser_qa.omission_policy(None, "release").strict)
        self.assertFalse(browser_qa.omission_policy(None, "development").strict)
        self.assertTrue(browser_qa.omission_policy("release", None).strict)
        self.assertFalse(browser_qa.omission_policy("mvp", None).strict)


class Audio(unittest.TestCase):
    def setUp(self):
        self.records = healthy_records(CONTRACT)
        self.vp = self.records["desktop-standard"]["viewport"]
        self.oc = self.records["desktop-standard"]["outcomes"]

    def test_a_declared_action_without_a_sound(self):
        self.vp["watch"]["runs"]["main"]["sounds"] = [
            s for s in self.vp["watch"]["runs"]["main"]["sounds"] if s["t"] != 5230]
        check = judged(self.records)["browser.audio-events"]
        self.assertEqual(check.status, FAIL)
        self.assertIn("pause (0 of 1)", check.message)

    def test_an_end_state_without_a_sound(self):
        self.oc["watch"]["runs"]["lose"]["sounds"] = []
        self.assertIn("lost (0 of 1)", judged(self.records)["browser.audio-events"].message)

    def test_a_silence_on_a_degraded_host_is_re_measured(self):
        self.oc["watch"]["runs"]["lose"]["sounds"] = []
        self.oc["attempts"] = [{"attempt": 1, "health": DEGRADED}]
        check = judged(self.records)["browser.audio-events"]
        self.assertEqual(check.status, BLOCKED)
        self.assertIn("degraded host", check.message)
        # A sound that followed in its window stands, whatever the host.
        self.oc["watch"]["runs"]["lose"]["sounds"] = [{"t": 20100, "kind": "buffer", "url": None,
                                                      "loop": False, "duration": 0.5, "loop_now": False}]
        self.assertEqual(judged(self.records)["browser.audio-events"].status, PASS)

    def test_the_end_sound_may_lead_the_reported_state(self):
        """Brick Breaker Worlds: the game-over sting starts 350 ms before the card says lost."""
        self.oc["watch"]["runs"]["lose"]["sounds"] = [{"t": 19650, "kind": "buffer", "url": None,
                                                      "loop": False, "duration": 2.2, "loop_now": False}]
        self.assertEqual(judged(self.records)["browser.audio-events"].status, PASS)

    def test_an_action_never_taken_is_named_not_failed(self):
        check = judged(self.records, action_audio=("pause", "shoot"))["browser.audio-events"]
        self.assertEqual(check.status, PASS)
        self.assertIn("not taken here: shoot", check.message)

    def test_a_one_shot_started_looping(self):
        self.vp["watch"]["runs"]["main"]["sounds"].append(
            {"t": 6000, "kind": "buffer", "url": ORIGIN + "/assets/audio/sfx-hit.wav", "loop": True,
             "duration": 0.3, "context": "running", "loop_now": True})
        check = judged(self.records, "development")["browser.audio-loops"]
        self.assertEqual((check.status, check.required), (FAIL, True))
        self.assertIn("sfx-hit", check.message)

    def test_a_loop_set_after_start_is_seen(self):
        self.oc["watch"]["runs"]["win"]["sounds"].append(
            {"t": 6000, "kind": "buffer", "url": ORIGIN + "/assets/audio/sfx-tap.wav", "loop": False,
             "duration": 0.2, "context": "running", "loop_now": True})
        self.assertEqual(judged(self.records)["browser.audio-loops"].status, FAIL)

    def test_a_declared_loop_is_matched_by_its_manifest_url(self):
        """Sky Marble's sfx-roll: 2 s, `audio.loop: true` in the manifest - a loop, not a one-shot."""
        clips = self.records["desktop-standard"]["clips"]["clips"]["clips"]
        clips.append(dict(clips[1], id="sfx-roll", url="audio/sfx-roll.wav", loop=True, duration_s=2.0))
        self.vp["watch"]["runs"]["main"]["sounds"].append(
            {"t": 6000, "kind": "buffer", "url": ORIGIN + "/assets/audio/sfx-roll.wav", "loop": True,
             "duration": 2.0, "context": "running", "loop_now": True})
        self.assertEqual(judged(self.records)["browser.audio-loops"].status, PASS)

    def test_music_and_declared_loops_may_loop(self):
        self.assertEqual(judged(self.records)["browser.audio-loops"].status, PASS)

    def test_mute_that_does_not_silence(self):
        self.vp["mute"]["muted"]["level"] = 0.03
        self.assertEqual(judged(self.records)["browser.audio-mute"].status, FAIL)

    def test_no_mute_control_is_reported(self):
        self.vp["mute"] = {"tried": False, "reason": "no mute control on the play screen"}
        check = judged(self.records)["browser.audio-mute"]
        self.assertEqual((check.status, check.required), (WARNING, False))

    def test_sound_while_hidden_is_a_hard_gate(self):
        self.vp["hidden"]["audio_hidden"]["level"] = 0.02
        check = judged(self.records, "development")["browser.audio-hidden"]
        self.assertEqual((check.status, check.required), (FAIL, True))

    def test_silence_proves_nothing_when_nothing_played(self):
        self.vp["hidden"]["audio_before"]["level"] = 0.0
        self.assertEqual(judged(self.records)["browser.audio-hidden"].status, WARNING)

    def test_loudness_spread_music_balance_and_clipping(self):
        clips = self.records["desktop-standard"]["clips"]["clips"]["clips"]
        clips[1]["blocks_db"] = [-40.0] * 6          # an effect 26 dB under the loudest
        check = judged(self.records)["browser.audio-loudness"]
        self.assertEqual(check.status, FAIL)
        self.assertIn("effects spread", check.message)
        clips = healthy_records(CONTRACT)
        clips["desktop-standard"]["clips"]["clips"]["clips"][0]["blocks_db"] = [-5.0] * 6
        self.assertIn("music sits", judged(clips)["browser.audio-loudness"].message)
        clips = healthy_records(CONTRACT)
        clips["desktop-standard"]["clips"]["clips"]["clips"][2]["peak_dbfs"] = 0.0
        self.assertIn("clipping: sfx-hit", judged(clips)["browser.audio-loudness"].message)

    def test_gated_loudness_ignores_silence(self):
        self.assertEqual(browser_qa.gated_loudness([-20.0, -20.0, -90.0, -90.0], -50), -20.0)
        self.assertIsNone(browser_qa.gated_loudness([-90.0], -50))

    def test_a_clip_that_does_not_decode(self):
        clip = self.records["desktop-standard"]["clips"]["clips"]["clips"][1]
        clip.update(error="EncodingError: Unable to decode audio data", duration_s=None)
        check = judged(self.records, "development")["browser.audio-clips"]
        self.assertEqual((check.status, check.required), (FAIL, True))


class Performance(unittest.TestCase):
    def setUp(self):
        self.records = healthy_records(CONTRACT)
        self.perf = self.records["desktop-standard"]["perf"]

    def test_frames_and_memory_over_the_bars(self):
        self.perf["frames"]["deltas"] = [16.7] * 300 + [50.0] * 40
        self.perf["memory"]["series"][-1]["mb"] = 60.0
        checks = judged(self.records)
        self.assertEqual(checks["browser.frame-stability"].status, FAIL)
        self.assertEqual(checks["browser.memory-growth"].status, FAIL)

    def test_a_software_rasterizer_blocks_a_failure_and_keeps_a_pass(self):
        self.perf["renderer"] = "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)"
        self.assertEqual(judged(self.records)["browser.frame-stability"].status, PASS)
        self.perf["frames"]["deltas"] = [100.0] * 100
        check = judged(self.records)["browser.frame-stability"]
        self.assertEqual(check.status, BLOCKED)
        self.assertIn("software rasterizer", check.message)

    def test_a_degraded_host_never_passes_or_fails_a_timing_check(self):
        """The zz-perf lesson (M3): a load artefact is BLOCKED, never FAIL - and never PASS."""
        for record in (self.perf, self.records["desktop-standard"]["viewport"]):
            record["health"] = DEGRADED
            record["attempts"] = [{"attempt": 1, "health": DEGRADED}, {"attempt": 2, "health": DEGRADED}]
        self.records["desktop-standard"]["viewport"]["started"]["ready_ms"] = 19000
        checks = judged(self.records)
        for cid in ("browser.frame-stability", "browser.memory-growth",
                    "browser.load-time:desktop-standard", "browser.first-interaction:desktop-standard"):
            self.assertEqual(checks[cid].status, BLOCKED, cid)
            self.assertIn("degraded", checks[cid].message)
        # A development run does not hold up on it, and still does not pass it.
        dev = judged(self.records, "development")
        self.assertEqual(dev["browser.load-time:desktop-standard"].status, WARNING)

    def test_the_zz_perf_load_artefact_is_blocked_never_failed(self):
        """Brick Breaker Worlds' zz-perf (wgf-inv/out, 2026-10-06): 5.33 fps against a floor
        of 6, on software WebGL beside other workers - r1 failed identically, 8 of 8 runs. The
        same reading - SwiftShader, ~187 ms frames, a stalling host - is BLOCKED here."""
        self.perf["renderer"] = ("ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) "
                                 "(0x0000C0DE)), SwiftShader driver)")
        self.perf["frames"]["deltas"] = [187.5] * 60
        check = judged(self.records)["browser.frame-stability"]
        self.assertEqual(check.status, BLOCKED)
        self.perf["attempts"] = [{"attempt": 1, "health": DEGRADED}, {"attempt": 2, "health": DEGRADED}]
        check = judged(self.records)["browser.frame-stability"]
        self.assertEqual(check.status, BLOCKED)
        self.assertIn("degraded", check.message)

    def test_a_healthy_retry_is_judged(self):
        self.perf["attempts"] = [{"attempt": 1, "health": DEGRADED}, {"attempt": 2, "health": self.perf["health"]}]
        check = judged(self.records)["browser.frame-stability"]
        self.assertEqual(check.status, PASS)
        self.assertEqual([a["degraded"] for a in check.evidence[0].data["environment"]], [True, False])

    def test_slow_load_on_a_quiet_host_fails(self):
        self.records["mobile"]["viewport"]["started"]["ready_ms"] = 9000
        self.assertEqual(judged(self.records)["browser.load-time:mobile"].status, FAIL)


class Bundle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wgf-bqa-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def png(self, name, w, h, pad=0):
        import struct
        import zlib
        header = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        chunk = b"IHDR" + header
        filler = b"tEXt" + b"x" * pad
        data = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(header)) + chunk
                + struct.pack(">I", zlib.crc32(chunk))
                + (struct.pack(">I", pad) + filler + struct.pack(">I", zlib.crc32(filler))
                   if pad else b"")
                + struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND")))
        os.makedirs(os.path.dirname(os.path.join(self.dir, name)), exist_ok=True)
        with open(os.path.join(self.dir, name), "wb") as handle:
            handle.write(data)

    def test_oversized_and_heavy_textures(self):
        self.png("assets/a.png", 512, 512)
        self.png("assets/huge.png", 8192, 1024)
        self.png("assets/wide.png", 3000, 1000, pad=1100000)
        bundle = browser_qa.scan_bundle(self.dir)
        checks = judged(healthy_records(CONTRACT), bundle=bundle)
        self.assertEqual(checks["browser.oversized-textures"].status, FAIL)
        self.assertIn("huge.png 8192x1024", checks["browser.oversized-textures"].message)
        weight = checks["browser.asset-weight"]
        self.assertEqual((weight.status, weight.required), (WARNING, False))
        self.assertIn("wide.png", weight.message)


class Runner(unittest.TestCase):
    def test_the_runner_is_written_inside_the_ignored_build_dir(self):
        root = tempfile.mkdtemp(prefix="wgf-bqa-root-")
        try:
            cfg = browser_qa.settings(CONTRACT, {"build_spec": {"experience": {
                "win": {"condition": "x", "metric": "m"},
                "actions": [{"action": "launch", "audio": "thwack"}, {"action": "steer"}]}}})
            self.assertEqual(cfg["action_audio"], ["launch"])
            self.assertTrue(cfg["has_win"])
            work, config, out = browser_qa.write_runner(root, cfg, port=4999)
            self.assertTrue(work.replace("\\", "/").endswith("build/wgf-browser-qa"))
            self.assertTrue(os.path.isfile(os.path.join(work, "browser_qa.spec.ts")))
            with open(config, encoding="utf-8") as handle:
                text = handle.read()
            for v in CONTRACT["viewports"]:
                self.assertIn(f'"name": "{v["id"]}"', text)
            self.assertIn("WGF_BROWSER_PROXY", text)
            self.assertIn("--strictPort", text)
            self.assertGreater(browser_qa.timeout_s(cfg), 600)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class Replay(unittest.TestCase):
    """The records the spec made of the two validation games at their accepted commits
    (2026-10-07), trimmed to what the judge reads. The defects they show are the games'."""

    def load(self, name):
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
            return json.load(handle)

    def test_replays(self):
        for name in sorted(os.listdir(FIXTURES)) if os.path.isdir(FIXTURES) else []:
            if not name.endswith(".json"):
                continue
            with self.subTest(name):
                fixture = self.load(name)
                checks = judged(fixture["records"], fixture.get("klass", "release"),
                                action_audio=fixture.get("action_audio", []),
                                bundle=fixture.get("bundle"))
                for cid, status in fixture["expect"].items():
                    self.assertIn(cid, checks)
                    self.assertEqual(checks[cid].status, status, f"{cid}: {checks[cid].message}")

    def judge(self, name):
        fixture = self.load(name)
        return judged(fixture["records"], fixture["klass"], action_audio=fixture["action_audio"],
                      bundle=fixture["bundle"])

    def test_both_games_open_the_context_menu_at_every_viewport(self):
        """M6, Yandex 1.6.1.8: neither validation game prevents it - a right click on desktop,
        the contextmenu a device's long press raises on tablet and mobile."""
        for name in ("brick-breaker-worlds-894b4b8.json", "sky-marble-c340631.json"):
            checks = self.judge(name)
            for v in CONTRACT["viewports"]:
                self.assertEqual(checks[f"browser.context-menu:{v['id']}"].status, FAIL, (name, v["id"]))

    def test_the_2d_objective_card_covers_the_ball_on_touch_layouts(self):
        checks = self.judge("brick-breaker-worlds-894b4b8.json")
        for vid in ("tablet", "mobile"):
            check = checks[f"browser.ui-covers-play:{vid}"]
            self.assertEqual(check.status, FAIL)
            self.assertIn("div#objective-line", check.message)
        for vid in ("desktop-wide", "desktop-standard", "desktop-narrow"):
            self.assertEqual(checks[f"browser.ui-covers-play:{vid}"].status, PASS)

    def test_the_3d_time_out_is_silent(self):
        """Sky Marble loses on its clock with no sound at all (its last sound, the fall, is
        3.8 s earlier); its declared actions with sounds are heard."""
        check = self.judge("sky-marble-c340631.json")["browser.audio-events"]
        self.assertEqual(check.status, FAIL)
        self.assertIn("lost (0 of 1)", check.message)
        self.assertNotIn("pause", check.message)

    def test_both_games_pass_runtime_audio_and_performance(self):
        for name in ("brick-breaker-worlds-894b4b8.json", "sky-marble-c340631.json"):
            checks = self.judge(name)
            for cid in ("browser.frame-stability", "browser.memory-growth", "browser.audio-loops",
                        "browser.audio-hidden", "browser.audio-mute", "browser.audio-loudness",
                        "browser.audio-clips", "browser.page-errors:mobile",
                        "browser.webgl-context:desktop-wide", "browser.load-time:tablet"):
                self.assertEqual(checks[cid].status, PASS, (name, cid, checks[cid].message))


if __name__ == "__main__":
    unittest.main()
