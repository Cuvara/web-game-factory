"""Ad coverage per target platform (wgflib.ad_coverage) - lesson L30.

The incident (2026-10-21): Y8 returned a game the Factory built with "the game is missing
ads". Its integration plan listed its placements for the platforms of the original design
(crazygames, yandex, poki); the title was retargeted to yandex, crazygames and y8 with
game.config.yaml monetization.ad_kinds [interstitial, rewarded], nothing regenerated the
plan, and the y8 build made no ad call. The sdk step reported y8's interstitial
`not-required` ("the design places none"); verify, the quality gate and platform-validate had
nothing that asked. Each reader of the rule is tested here on that exact shape:

  * the sdk step (wgf_sdk.integration): _cover_targets gives the retargeted target the
    placements; _ad_gaps never reports a committed, offered, unreached kind as not-required
    where the portal requires ads; the plan records the targets it was generated for;
  * verify: platform.ads-integrated:<id> (wgf_verification.checks.platform._ads_integrated),
    on the checkout's plan and the platform's bundle;
  * platform-validate: guard ads_integrated (wgflib.portal_sdks.ads_guard);
  * the store listing: a Y8 rendition leaves title/loading screens out, and validation warns
    for one that remains.

The bundle text below is REAL esbuild 0.21.5 --minify output (the template's own bundler) of
a plan rendered by wgf_sdk.integrate.render_plan, and the Y8 ad call is the line of a real
template v1.2.2 y8 build (assets/index-*.js) - both captured 2026-10-21.
"""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from wgflib import ad_coverage, paths, portal_sdks  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402
from wgf_sdk import integrate  # noqa: E402
from wgf_sdk.design import design_placements  # noqa: E402
from wgf_sdk.integration import IntegrationPhase  # noqa: E402
from wgf_sdk.step import _overlay  # noqa: E402
from wgf_verification.checks import platform as platform_checks  # noqa: E402
from wgf_verification.model import BLOCKED, FAIL, PASS, WARNING  # noqa: E402

INCIDENT_PLACEMENT_PLATFORMS = ["crazygames", "yandex", "poki"]
INCIDENT_TARGETS = ["yandex", "crazygames", "y8"]
INCIDENT_AD_KINDS = ["interstitial", "rewarded"]

# Real: the Y8 adapter's ad call in a template v1.2.2 y8 build (minified).
REAL_Y8_AD_CALL = ('"error"),i(this,G,"f").adStartTimeoutMs??15e3);try{const P=s.showAd({type:o,'
                   'name:f,...qe,...Ve});P&&typeof P')
# Real: esbuild --minify of render_plan's output, placements listing crazygames/yandex/poki.
REAL_MINIFIED_PLAN = (
    'var t={titleId:"demo",placements:[{id:"interstitial-game-over",kind:"interstitial",'
    'moment:"game-over",trigger:"After a lost run: {retry} // not a comment",platforms:'
    '["crazygames","yandex","poki"]},{id:"rewarded-game-over",kind:"rewarded",moment:'
    '"game-over",trigger:"Revive",platforms:["crazygames","yandex","poki"]}],'
    'adapterSubstitutes:{},breakOnContinue:[]};')


def profile(pid):
    return load_file(os.path.join(paths.PLATFORMS, f"{pid}.yaml"))


def pin(pid):
    return f"{pid}@{profile(pid)['version']}"


def game_config(targets=INCIDENT_TARGETS, ad_kinds=INCIDENT_AD_KINDS):
    return {"game": {"id": "demo"},
            "platforms": [{"id": t, "profile": pin(t), "role": "required"} for t in targets],
            "monetization": {"ad_kinds": list(ad_kinds)}}


def plan(platforms=INCIDENT_PLACEMENT_PLATFORMS, kinds=INCIDENT_AD_KINDS, **extra):
    out = {"titleId": "demo", "placements": [
        {"id": f"{k}-game-over", "kind": k, "moment": "game-over",
         "trigger": "After a lost run: {retry}", "platforms": platforms} for k in kinds],
        "adapterSubstitutes": {}, "breakOnContinue": []}
    out.update(extra)
    return out


def rendered(plan_data, targets=INCIDENT_PLACEMENT_PLATFORMS):
    return integrate.render_plan(plan_data, "wgf:game-design:demo:20261001-01", targets)


def incident_design(name_y8=True):
    """The retargeted title's design: placements for the original platforms; its constraints
    name the new targets (the shape b07cd0b's `considered` rule left out on purpose)."""
    constraints = [{"platform_id": p} for p in
                   (INCIDENT_TARGETS if name_y8 else INCIDENT_PLACEMENT_PLATFORMS)]
    return {"platform_constraints_applied": constraints, "monetization": {"placements": [
        {"kind": "interstitial", "trigger": "After a lost run, before retry",
         "platforms": INCIDENT_PLACEMENT_PLATFORMS},
        {"kind": "rewarded", "trigger": "Revive after a crash",
         "platforms": INCIDENT_PLACEMENT_PLATFORMS}]}}


# -- the rule -------------------------------------------------------------------------------

class Rule(unittest.TestCase):
    def requirements(self, config):
        return ad_coverage.requirements(config, profile)

    def test_y8_requires_ads_and_its_profile_says_where(self):
        y8 = profile("y8")
        self.assertTrue(ad_coverage.required_by_portal(y8))
        source = y8["ads"]["required_by_portal_source"]
        self.assertIn("https://docs.y8.com/sdk/advertising/", source["urls"])
        self.assertIn("https://docs.y8.com/sdk/ad-placement-guidelines/", source["urls"])
        self.assertEqual(source["read"], "2026-10-21")
        # Only Y8: no other portal's documentation was read to say it requires ads.
        for pid in ("yandex", "crazygames", "poki", "gamepix", "gamedistribution",
                    "gamemonetize", "gamevui", "generic-web"):
            self.assertFalse(ad_coverage.required_by_portal(profile(pid)), pid)

    def test_every_target_offering_a_committed_kind_is_required(self):
        required = self.requirements(game_config())
        self.assertEqual({(r.platform, r.kind) for r in required},
                         {(t, k) for t in INCIDENT_TARGETS for k in INCIDENT_AD_KINDS})
        self.assertEqual({r.platform for r in required if r.portal_required}, {"y8"})

    def test_a_platform_without_ads_and_a_kind_not_committed_require_nothing(self):
        self.assertEqual(self.requirements(game_config(["generic-web"])), [])
        self.assertEqual(self.requirements(game_config(["y8"], [])), [])
        only = self.requirements(game_config(["y8"], ["interstitial"]))
        self.assertEqual([(r.platform, r.kind) for r in only], [("y8", "interstitial")])
        # GameMonetize offers no rewarded: a committed rewarded is not required of it.
        self.assertEqual([r.kind for r in self.requirements(
            game_config(["gamemonetize"]))], ["interstitial"])

    def test_the_incident_plan_reaches_every_target_but_y8(self):
        data = ad_coverage.parse_plan(rendered(plan()))
        gaps = ad_coverage.gaps(data, self.requirements(game_config()))
        self.assertEqual([(g.platform, g.kind) for g in gaps],
                         [("y8", "interstitial"), ("y8", "rewarded")])

    def test_a_plan_listing_y8_or_every_platform_reaches_it(self):
        for platforms in (INCIDENT_PLACEMENT_PLATFORMS + ["y8"], None):
            data = ad_coverage.parse_plan(rendered(plan(platforms)))
            self.assertEqual(ad_coverage.gaps(data, self.requirements(game_config())), [])

    def test_placements_match_the_target_not_its_substitute(self):
        data = plan(["generic-web"], ["interstitial"], adapterSubstitutes={"gamevui": "generic-web"})
        self.assertFalse(ad_coverage.covers(data, "interstitial", "gamevui"))

    def test_break_on_continue_reaches_an_interstitial_never_a_rewarded(self):
        data = plan([], INCIDENT_AD_KINDS, breakOnContinue=["poki"])
        self.assertTrue(ad_coverage.covers(data, "interstitial", "poki"))
        self.assertFalse(ad_coverage.covers(data, "rewarded", "poki"))

    def test_the_generated_plan_parses_and_records_its_targets(self):
        text = rendered(plan(), ["crazygames", "yandex", "poki"])
        self.assertIn("// Targets: crazygames, yandex, poki", text)
        self.assertEqual(ad_coverage.plan_targets(text), ["crazygames", "yandex", "poki"])
        data = ad_coverage.parse_plan(text)
        self.assertEqual(data["placements"][0]["trigger"], "After a lost run: {retry}")

    def test_a_retarget_makes_the_plan_stale(self):
        text = rendered(plan(), ["crazygames", "yandex", "poki"])
        reason = ad_coverage.stale(text, game_config())
        self.assertIn("targets added since: y8", reason)
        self.assertIn("targets dropped since: poki", reason)
        self.assertIsNone(ad_coverage.stale(rendered(plan(), INCIDENT_TARGETS), game_config()))
        # A plan written before the header existed is never taken as current.
        self.assertIn("records no targets", ad_coverage.stale(
            integrate.render_plan(plan(), "x"), game_config()))

    def test_an_unreadable_plan_is_never_coverage(self):
        with self.assertRaises(ad_coverage.PlanUnreadable):
            ad_coverage.parse_plan("export const OTHER = {};\n")
        with self.assertRaises(ad_coverage.PlanUnreadable):
            ad_coverage.parse_plan("export const INTEGRATION_PLAN = build();\n")

    def test_the_compiled_plan_is_read_from_real_minified_output(self):
        found = ad_coverage.bundle_placements([REAL_MINIFIED_PLAN])
        self.assertEqual(found, [("interstitial", INCIDENT_PLACEMENT_PLATFORMS),
                                 ("rewarded", INCIDENT_PLACEMENT_PLATFORMS)])
        self.assertFalse(ad_coverage.bundle_covers(found, "interstitial", "y8"))
        self.assertTrue(ad_coverage.bundle_covers(found, "rewarded", "yandex"))

    def test_each_portals_ad_call_is_recognised_in_its_own_bundle_only(self):
        reference = portal_sdks.load()
        scan = portal_sdks.scan_files(reference, [("assets/index.js",
                                                   REAL_Y8_AD_CALL.encode())])
        self.assertEqual(sorted(scan.ad_calls), ["y8"])
        for pid in ("y8", "yandex", "crazygames", "poki", "gamepix"):
            self.assertTrue(reference.ad_calls(pid), pid)


# -- the sdk step ---------------------------------------------------------------------------

class SdkStep(unittest.TestCase):
    def cover(self, design, targets=INCIDENT_TARGETS, declared=INCIDENT_AD_KINDS):
        placements = design_placements(design)
        notes = []
        IntegrationPhase._cover_targets(placements, design, targets, notes, declared)
        return placements, notes

    def test_L30_the_sdk_step_covers_a_retargeted_portal_required_target(self):
        # The design's constraints name y8, so the 2026-10-04 rule (cover only a target the
        # design never considered) left it out: the incident.
        placements, notes = self.cover(incident_design(name_y8=True))
        for placement in placements:
            self.assertIn("y8", placement.platforms, placement.id)
        self.assertTrue(any(n.startswith("y8 is a target") and "predate the retarget" in n
                            for n in notes), notes)

    def test_a_target_the_design_never_considered_is_covered_as_before(self):
        placements, notes = self.cover(incident_design(name_y8=False))
        self.assertTrue(all("y8" in p.platforms for p in placements))
        self.assertTrue(any("the design predates it" in n for n in notes), notes)

    def test_the_portal_requirement_covers_a_considered_target_with_current_lists(self):
        design = {"platform_constraints_applied": [{"platform_id": "yandex"},
                                                   {"platform_id": "y8"}],
                  "monetization": {"placements": [
                      {"kind": "interstitial", "trigger": "After a lost run",
                       "platforms": ["yandex"]}]}}
        placements, notes = self.cover(design, ["yandex", "y8"], ["interstitial"])
        self.assertEqual(placements[0].platforms, ["yandex", "y8"])
        self.assertTrue(any("requires ads" in n for n in notes), notes)

    def test_a_deliberate_exclusion_stays_where_the_portal_does_not_require_ads(self):
        design = {"platform_constraints_applied": [{"platform_id": "yandex"},
                                                   {"platform_id": "crazygames"}],
                  "monetization": {"placements": [
                      {"kind": "interstitial", "trigger": "After a lost run",
                       "platforms": ["yandex"]}]}}
        placements, _ = self.cover(design, ["yandex", "crazygames"], ["interstitial"])
        self.assertEqual(placements[0].platforms, ["yandex"])

    def features(self):
        return [{"feature": "init", "status": "working"},
                {"feature": "interstitial", "status": "not-required",
                 "note": "offered by the adapter; the design places none"},
                {"feature": "rewarded", "status": "not-required",
                 "note": "offered by the adapter; the design places none"}]

    def test_a_gap_on_a_portal_requiring_ads_is_not_started_and_the_platform_not_working(self):
        out = IntegrationPhase._ad_gaps(self.features(), "y8", plan(), INCIDENT_AD_KINDS)
        by = {f["feature"]: f for f in out}
        for kind in INCIDENT_AD_KINDS:
            self.assertEqual(by[kind]["status"], "not-started")
            self.assertIn("no " + kind + " placement in src/platform/integration-plan.ts "
                          "reaches y8", by[kind]["note"])
            self.assertIn("crazygames, yandex, poki", by[kind]["note"])
        entry = {"platform_id": "y8", "status": "working",
                 "features": [{"feature": "init", "status": "working"}]}
        _overlay(entry, {"features": out, "adapter": {"status": "implemented"}})
        self.assertNotEqual(entry["status"], "working")

    def test_a_gap_elsewhere_is_said_not_hidden(self):
        out = IntegrationPhase._ad_gaps(self.features(), "crazygames",
                                        plan(["yandex"]), INCIDENT_AD_KINDS)
        by = {f["feature"]: f for f in out}
        self.assertEqual(by["interstitial"]["status"], "not-required")
        self.assertIn("platform.ads-integrated:crazygames", by["interstitial"]["note"])

    def test_a_reached_target_is_left_alone(self):
        features = self.features()
        self.assertEqual(IntegrationPhase._ad_gaps(features, "yandex", plan(),
                                                   INCIDENT_AD_KINDS), features)


# -- verify ---------------------------------------------------------------------------------

class FakeSession:
    """The part of wgf_verification.session.Session that platform.ads-integrated reads."""

    def __init__(self, root, config, bundle_text=None, bundle_built=True):
        self.root = root
        self.game_config = config
        self.platforms = config["platforms"]
        self.platform_build_mode = None
        self.results = {}
        self._built = bundle_built
        os.makedirs(os.path.join(root, "dist"), exist_ok=True)
        if bundle_text is not None:
            with open(os.path.join(root, "dist", "app.js"), "w", encoding="utf-8") as handle:
                handle.write(bundle_text)

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def exists(self, *parts):
        return os.path.exists(self.path(*parts))

    def file_hash(self, _relative):
        return None

    def profile(self, pid):
        return profile(pid), f"core/reference/platforms/{pid}.yaml"

    def passed(self, check_id):
        return check_id == "build.bundle" and self._built

    def platform_bundle(self, _pid):
        return "dist", {}

    def portal_sdk_reference(self):
        return portal_sdks.load()

    def blocked_by(self, check_id, *, id, category, title, required=True, platform_id=None):
        from wgf_verification.model import Check, Evidence
        return Check(id, category, title, BLOCKED, required=required, platform_id=platform_id,
                     message=f"depends on {check_id}",
                     evidence=[Evidence("reference", check_id, check_ref=check_id)])


class Verify(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wgf-ads-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def check(self, pid, plan_text, bundle_text, config=None, built=True):
        if plan_text is not None:
            os.makedirs(os.path.join(self.root, "src", "platform"), exist_ok=True)
            with open(os.path.join(self.root, "src", "platform", "integration-plan.ts"), "w",
                      encoding="utf-8") as handle:
                handle.write(plan_text)
        session = FakeSession(self.root, config or game_config(), bundle_text, built)
        common = {"category": "platform", "required": True, "platform_id": pid}
        return platform_checks._ads_integrated(session, pid, common)

    def incident_bundle(self):
        return REAL_Y8_AD_CALL + "\n" + REAL_MINIFIED_PLAN

    def test_L30_verify_fails_the_incident(self):
        result = self.check("y8", rendered(plan()), self.incident_bundle())
        self.assertEqual(result.id, "platform.ads-integrated:y8")
        self.assertEqual(result.status, FAIL, result.message)
        self.assertTrue(result.required)  # a Hard Gate: Y8 requires ads
        self.assertIn("no interstitial placement in src/platform/integration-plan.ts lists y8",
                      result.message)
        self.assertIn("no rewarded placement", result.message)
        self.assertIn("the plan compiled into dist/ has no interstitial placement listing y8",
                      result.message)
        self.assertIn("targets added since: y8", result.message)
        self.assertIn("--from sdk", result.message)

    def test_L30_verify_passes_once_the_plan_lists_the_target(self):
        listed = INCIDENT_PLACEMENT_PLATFORMS + ["y8"]
        minified = REAL_MINIFIED_PLAN.replace('"poki"]', '"poki","y8"]')
        result = self.check("y8", rendered(plan(listed), INCIDENT_TARGETS),
                            REAL_Y8_AD_CALL + "\n" + minified)
        self.assertEqual(result.status, PASS, result.message)

    def test_the_other_incident_targets_pass(self):
        for pid, call in (("yandex", "s.adv.showFullscreenAdv({callbacks:c})"),
                          ("crazygames", 's.ad.requestAd("midgame",{})')):
            result = self.check(pid, rendered(plan()), call + "\n" + REAL_MINIFIED_PLAN)
            self.assertEqual(result.status, PASS, (pid, result.message))

    def test_a_y8_bundle_without_the_y8_ad_call_fails(self):
        listed = INCIDENT_PLACEMENT_PLATFORMS + ["y8"]
        result = self.check("y8", rendered(plan(listed), INCIDENT_TARGETS), "console.log(1)")
        self.assertEqual(result.status, FAIL)
        self.assertIn("carries no y8 ad call", result.message)

    def test_no_plan_is_a_failure_on_y8(self):
        result = self.check("y8", None, self.incident_bundle())
        self.assertEqual(result.status, FAIL)
        self.assertIn("has no src/platform/integration-plan.ts", result.message)

    def test_a_gap_where_the_portal_does_not_require_ads_is_a_warning(self):
        config = game_config(["yandex", "crazygames"])
        result = self.check("crazygames", rendered(plan(["yandex"])),
                            's.ad.requestAd("midgame",{})', config)
        self.assertEqual(result.status, WARNING, result.message)
        self.assertFalse(result.required)

    def test_nothing_required_passes(self):
        result = self.check("generic-web", None, "", game_config(["generic-web"]))
        self.assertEqual(result.status, PASS)
        self.assertIn("no ad placement is required", result.message)
        result = self.check("y8", None, "", game_config(["y8"], []))
        self.assertEqual(result.status, PASS)

    def test_an_unbuilt_bundle_still_reports_a_plan_gap(self):
        result = self.check("y8", rendered(plan()), None, built=False)
        self.assertEqual(result.status, FAIL)
        listed = INCIDENT_PLACEMENT_PLATFORMS + ["y8"]
        self.assertEqual(self.check("y8", rendered(plan(listed), INCIDENT_TARGETS), None,
                                    built=False).status, BLOCKED)

    def test_L30_generalizes_to_another_portal_and_kind(self):
        # A 2D title first planned for poki only (interstitial), retargeted to gamepix. Gamepix
        # does not require ads: the gap is a WARNING at verify, and the sdk step covers it
        # because the lists predate the retarget (they name poki, no longer a target).
        config = game_config(["gamepix"], ["interstitial"])
        text = rendered(plan(["poki"], ["interstitial"]), ["poki"])
        result = self.check("gamepix", text, "window.GamePix.interstitialAd()", config)
        self.assertEqual(result.status, WARNING, result.message)
        self.assertIn("no interstitial placement", result.message)
        design = {"platform_constraints_applied": [{"platform_id": "gamepix"}],
                  "monetization": {"placements": [{"kind": "interstitial",
                                                   "trigger": "Between levels",
                                                   "platforms": ["poki"]}]}}
        placements = design_placements(design)
        IntegrationPhase._cover_targets(placements, design, ["gamepix"], [], ["interstitial"])
        self.assertEqual(placements[0].platforms, ["poki", "gamepix"])


# -- platform-validate ----------------------------------------------------------------------

class Guard(unittest.TestCase):
    def scan(self, text):
        return portal_sdks.scan_files(portal_sdks.load(), [("assets/app.js", text.encode())])

    def test_L30_platform_validate_refuses_the_incident_package(self):
        verified = {"id": "platform.ads-integrated:y8", "status": "FAIL",
                    "message": "no interstitial placement lists y8"}
        result = portal_sdks.ads_guard("y8", profile("y8"), self.scan(REAL_Y8_AD_CALL),
                                       verified)
        self.assertIs(result.value, False)
        self.assertIn("no interstitial placement lists y8", result.reason)

    def test_a_pin_older_than_the_requirement_is_refused_on_its_warning(self):
        verified = {"status": "WARNING", "message": "no rewarded placement lists y8"}
        result = portal_sdks.ads_guard("y8", profile("y8"), self.scan(REAL_Y8_AD_CALL),
                                       verified)
        self.assertIs(result.value, False)
        self.assertIn("predates the requirement", result.reason)

    def test_a_package_without_the_ad_call_is_refused(self):
        result = portal_sdks.ads_guard("y8", profile("y8"), self.scan("console.log(1)"),
                                       {"status": "PASS"})
        self.assertIs(result.value, False)
        self.assertIn("no y8 ad call", result.reason)

    def test_a_verified_package_with_its_ad_call_is_green(self):
        result = portal_sdks.ads_guard("y8", profile("y8"), self.scan(REAL_Y8_AD_CALL),
                                       {"status": "PASS"})
        self.assertIs(result.value, True)

    def test_no_verdict_is_unknown_never_green_where_ads_are_required(self):
        self.assertIsNone(portal_sdks.ads_guard("y8", profile("y8"),
                                                self.scan(REAL_Y8_AD_CALL), None).value)
        self.assertIsNone(portal_sdks.ads_guard("y8", profile("y8"), None,
                                                {"status": "PASS"}).value)

    def test_a_portal_that_does_not_require_ads_is_green_with_the_warning_named(self):
        result = portal_sdks.ads_guard("crazygames", profile("crazygames"), None,
                                       {"status": "WARNING", "message": "gap"})
        self.assertIs(result.value, True)
        self.assertIn("gap", result.reason)
        self.assertIs(portal_sdks.ads_guard("crazygames", profile("crazygames"), None,
                                            {"status": "FAIL", "message": "x"}).value, False)


# -- the store listing ----------------------------------------------------------------------

class Listing(unittest.TestCase):
    def test_the_y8_block_excludes_title_and_loading_screens(self):
        from wgf_listing import platforms as listing_platforms
        block = profile("y8")["store_listing"]
        self.assertEqual(block["screenshots"]["excluded_states"],
                         ["loading", "title", "paused", "other"])
        self.assertIn("https://docs.y8.com/studio/media/", block["notes"])
        self.assertIn("logo alone on a plain background", block["notes"])
        reference = load_file(os.path.join(paths.REFERENCE, "store-listing.yaml"))
        reqs = listing_platforms.requirements(profile("y8"), reference)
        shots = next(r for r in reqs if r["kind"] == "screenshots")
        self.assertEqual(shots["excluded_states"], ["loading", "title", "paused", "other"])


if __name__ == "__main__":
    unittest.main()
