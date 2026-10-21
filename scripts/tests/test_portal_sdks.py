"""Portal SDKs in a platform's bundle: the Factory's own scan (wgflib.portal_sdks), the verify
step's `platform.foreign-sdk:<id>` / `platform.sdk-loaded:<id>`, the echoed
`package.platform_sdk` fact no longer counted on template contract 1, and platform-validate's
guards `portal_sdk_isolated` / `portal_sdk_loaded`.

The regression input is REAL: fixtures/portal-sdks/sky-marble-43c08e2.json, minimised from
per-platform builds of the 3D validation game sky-marble at 43c08e2 on the pinned template
v1.2.0 (every bundle carries every portal adapter; the template's own crazygames-audit FAILs
the crazygames bundle on unexpected_dependencies), and of the same commit with the template
backport patches 0001-0003 applied (one adapter per bundle; the audit PASSes). Each bundle is
rebuilt here from the fixture: every file it had (empty unless it matched), index.html with
its real <script> tags, and the real text around every match.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from test_verification import (FIXTURES, FakeRunner, VerificationCase,  # noqa: E402
                               failing, fixture, honoring_build, ok, read_json)
from wgflib import portal_sdks  # noqa: E402
from wgflib.workflow import StepOutcome  # noqa: E402

REAL = os.path.join(HERE, "fixtures", "portal-sdks", "sky-marble-43c08e2.json")
# What the template's own crazygames-audit reported on the real as-is crazygames bundle
# (unexpected_dependencies FAIL; scratch log, 2026-10-10).
TEMPLATE_AUDIT_FOREIGN = {"poki", "yandex", "gamedistribution", "gamemonetize"}


def real_bundles():
    with open(REAL, encoding="utf-8") as handle:
        return {b["label"]: b for b in json.load(handle)["bundles"]}


BUNDLES = real_bundles()


def materialise(bundle, directory, keep_index=None):
    """Write the fixture's bundle into `directory`. `keep_index`: an existing index.html whose
    head gets the real non-module <script> tags (so a fixture game's own entry still loads)."""
    os.makedirs(directory, exist_ok=True)
    texts = {}
    for excerpt in bundle["excerpts"]:
        texts.setdefault(excerpt["file"], []).append(excerpt["text"])
    head = "".join(tag + "</script>" for tag in bundle["index_html_scripts"]
                   if 'type="module"' not in tag)
    for entry in bundle["files"]:
        path = os.path.join(directory, *entry["path"].split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if entry["path"] == "index.html":
            if keep_index is not None:
                html = keep_index.replace("<head>", "<head>" + head, 1)
            else:
                html = ("<!doctype html><html><head>" + "".join(
                    t + "</script>" for t in bundle["index_html_scripts"])
                        + "</head><body></body></html>")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(html)
        elif entry["path"] in texts:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(texts[entry["path"]]) + "\n")
        elif not os.path.exists(path):
            open(path, "wb").close()


class RealFixture(unittest.TestCase):
    def test_the_fixture_is_labelled_real_and_pins_every_original_file(self):
        with open(REAL, encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertIn("REAL DATA", document["_fixture"])
        self.assertEqual(document["game_commit"], "43c08e2f6b92e0d20e74d9376e72b7f474365596")
        self.assertEqual(document["template"]["commit"],
                         "b1062619457f427bac91b45f6a96762f256a945a")
        self.assertEqual(len(document["backport_patches"]), 3)
        for bundle in document["bundles"]:
            self.assertIn("index.html", [f["path"] for f in bundle["files"]])
            for entry in bundle["files"]:
                self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")


class Scanner(unittest.TestCase):
    def setUp(self):
        self.reference = portal_sdks.load()
        self.scratch = tempfile.mkdtemp(prefix="wgf-portal-sdks-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def scan(self, label):
        directory = os.path.join(self.scratch, label)
        materialise(BUNDLES[label], directory)
        return portal_sdks.scan_directory(self.reference, directory, label)

    def test_the_v1_2_0_crazygames_bundle_carries_four_other_portals_and_y8(self):
        found = portal_sdks.foreign(self.scan("43c08e2-crazygames"), "crazygames")
        # Every portal the template's own audit named, and Y8 (which the audit does not list).
        self.assertTrue(TEMPLATE_AUDIT_FOREIGN <= set(found), found)
        self.assertEqual(set(found), TEMPLATE_AUDIT_FOREIGN | {"y8"})

    def test_the_backported_crazygames_bundle_carries_only_its_own(self):
        scan = self.scan("43c08e2+backport-crazygames")
        self.assertEqual(portal_sdks.foreign(scan, "crazygames"), {})
        self.assertEqual(scan.portals(), ["crazygames"])
        self.assertEqual(portal_sdks.loader_status(scan, "crazygames")[1], True)

    def test_every_backported_bundle_is_clean_and_every_v1_2_0_bundle_is_not(self):
        for pid in ("yandex", "crazygames", "y8"):
            dirty = portal_sdks.foreign(self.scan(f"43c08e2-{pid}"), pid)
            clean = self.scan(f"43c08e2+backport-{pid}")
            self.assertEqual(len(dirty), 5, (pid, dirty))
            self.assertEqual(portal_sdks.foreign(clean, pid), {}, pid)
            self.assertEqual(clean.portals(), [pid])

    def test_a_y8_bundle_built_without_its_ids_does_not_load_the_y8_sdk(self):
        for label in ("43c08e2-y8", "43c08e2+backport-y8"):
            script, loaded, needs = portal_sdks.loader_status(self.scan(label), "y8")
            self.assertEqual((script, loaded, needs),
                             ("https://cdn.y8.com/minimal-sdk/2-0/y8.min.js", False,
                              ["WGF_Y8_APP_ID"]), label)
        self.assertTrue(portal_sdks.loader_status(
            self.scan("43c08e2+backport-y8-with-ids"), "y8")[1])

    def test_a_package_archive_scans_as_its_directory(self):
        directory = os.path.join(self.scratch, "dir")
        materialise(BUNDLES["43c08e2-crazygames"], directory)
        for prefix in ("", "game/"):
            archive = os.path.join(self.scratch, f"pkg{len(prefix)}.zip")
            with zipfile.ZipFile(archive, "w") as handle:
                for root, _, names in os.walk(directory):
                    for name in names:
                        full = os.path.join(root, name)
                        handle.write(full, prefix + os.path.relpath(full, directory)
                                     .replace(os.sep, "/"))
            zipped = portal_sdks.scan_zip(self.reference, archive)
            plain = portal_sdks.scan_directory(self.reference, directory)
            self.assertEqual(zipped.found, plain.found)
            self.assertEqual(portal_sdks.loader_status(zipped, "crazygames")[1], True)

    def test_generic_web_finds_every_portal_foreign(self):
        scan = self.scan("43c08e2+backport-yandex")
        self.assertEqual(sorted(portal_sdks.foreign(scan, "generic-web")), ["yandex"])

    def test_every_reference_key_is_a_platform_profile(self):
        profiles = {name[:-5] for name in os.listdir(os.path.join(
            SCRIPTS, "..", "core", "reference", "platforms")) if name.endswith(".yaml")}
        self.assertEqual(set(self.reference.portals), profiles)


class AtThePin(unittest.TestCase):
    """What the reference says of the pinned template is true of it: every audit CLI exists,
    takes --dir and --out, writes its report and reports its result id; every loader script
    is the URL the template's adapters and build plugin name."""

    def setUp(self):
        import pinned_template
        self.root, why = pinned_template.checkout()
        if self.root is None:
            self.skipTest(why)
        self.reference = portal_sdks.load()

    def read(self, relative):
        with open(os.path.join(self.root, *relative.split("/")), encoding="utf-8") as handle:
            return handle.read()

    def test_every_named_audit_is_the_pins(self):
        audits = {pid: entry["audit"] for pid, entry in self.reference.portals.items()
                  if entry.get("audit")}
        self.assertTrue(audits)
        for pid, audit in audits.items():
            text = self.read(audit["cli"])
            for needle in ("--dir", "--out", audit["report"], f'"{audit["check"]}"'):
                self.assertIn(needle, text, (pid, needle))

    def test_every_loader_script_is_the_pins(self):
        plugin = self.read("scripts/build/game-config-plugin.ts")
        for pid, entry in self.reference.portals.items():
            if entry.get("loader"):
                self.assertIn(f'"{entry["loader"]["script"]}"', plugin, pid)


class Guards(Scanner):
    def zip_of(self, label):
        directory = os.path.join(self.scratch, label)
        materialise(BUNDLES[label], directory)
        archive = os.path.join(self.scratch, label + ".zip")
        with zipfile.ZipFile(archive, "w") as handle:
            for root, _, names in os.walk(directory):
                for name in names:
                    full = os.path.join(root, name)
                    handle.write(full, os.path.relpath(full, directory).replace(os.sep, "/"))
        return portal_sdks.scan_zip(self.reference, archive)

    def test_the_v1_2_0_crazygames_package_is_red_and_the_backport_green(self):
        red = portal_sdks.isolated_guard("crazygames", self.zip_of("43c08e2-crazygames"))
        self.assertIs(red.value, False)
        self.assertIn("poki", red.reason)
        green = portal_sdks.isolated_guard("crazygames",
                                           self.zip_of("43c08e2+backport-crazygames"))
        self.assertIs(green.value, True, green.reason)

    def test_verifys_failing_check_is_red_even_when_the_scan_is_clean(self):
        verified = {"id": "platform.foreign-sdk:crazygames", "status": "FAIL",
                    "message": "template audit unexpected_dependencies: gamepix"}
        result = portal_sdks.isolated_guard(
            "crazygames", self.zip_of("43c08e2+backport-crazygames"), verified)
        self.assertIs(result.value, False)
        self.assertIn("template audit", result.reason)

    def test_verifys_blocked_check_is_unknown_never_green(self):
        # Final review round 2, N-1: the template audit decided nothing, so verify's check is
        # BLOCKED; the package carries an ad network only the audit's list names
        # (googlesyndication.com), which the Factory scan does not recognise.
        directory = os.path.join(self.scratch, "ads")
        materialise(BUNDLES["43c08e2+backport-crazygames"], directory)
        with open(os.path.join(directory, "assets", "ads.js"), "w") as handle:
            handle.write('load("https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js");\n')
        archive = os.path.join(self.scratch, "ads.zip")
        with zipfile.ZipFile(archive, "w") as handle:
            for root, _, names in os.walk(directory):
                for name in names:
                    full = os.path.join(root, name)
                    handle.write(full, os.path.relpath(full, directory).replace(os.sep, "/"))
        scan = portal_sdks.scan_zip(self.reference, archive)
        self.assertEqual(portal_sdks.foreign(scan, "crazygames"), {})  # the scan alone is clean
        verified = {"id": "platform.foreign-sdk:crazygames", "status": "BLOCKED",
                    "message": "the template's scripts/crazygames-audit.mjs ... reported no "
                               "unexpected_dependencies"}
        result = portal_sdks.isolated_guard("crazygames", scan, verified)
        self.assertIsNone(result.value, result.reason)
        self.assertIn("BLOCKED", result.reason)
        # A Factory finding still makes it RED whatever verify said.
        self.assertIs(portal_sdks.isolated_guard(
            "crazygames", self.zip_of("43c08e2-crazygames"), verified).value, False)

    def test_an_unread_package_is_unknown(self):
        self.assertIsNone(portal_sdks.isolated_guard("y8", None).value)
        self.assertIsNone(portal_sdks.loaded_guard("y8", None).value)

    def test_an_sdk_less_y8_package_is_red_once_its_ids_are_issued(self):
        scan = self.zip_of("43c08e2+backport-y8")
        refused = portal_sdks.loaded_guard("y8", scan, ids_pending=False)
        self.assertIs(refused.value, False)
        self.assertIn("WGF_Y8_APP_ID", refused.reason)
        # Before the game exists the submit visit only creates it and uploads nothing.
        pending = portal_sdks.loaded_guard("y8", scan, ids_pending=True)
        self.assertIs(pending.value, True)
        self.assertIn("uploads nothing", pending.reason)
        loaded = portal_sdks.loaded_guard("y8", self.zip_of("43c08e2+backport-y8-with-ids"))
        self.assertIs(loaded.value, True)

    def test_a_platform_the_reference_does_not_describe_is_unknown_never_green(self):
        # A profile added without a portal-sdks.yaml entry is undescribed, not SDK-less:
        # generic-web and gamevui declare `signatures: []` on purpose (final review MAJOR-1).
        scan = self.zip_of("43c08e2+backport-yandex")
        undescribed = portal_sdks.loaded_guard("new-portal", scan)
        self.assertIsNone(undescribed.value, undescribed.reason)
        self.assertIn("no entry", undescribed.reason)
        self.assertIs(portal_sdks.loaded_guard("gamevui", scan).value, True)
        self.assertIs(portal_sdks.loaded_guard("generic-web", scan).value, True)

    def test_a_commented_out_loader_is_not_loaded(self):
        scan = portal_sdks.Scan(self.reference, "fixture")
        scan.add("index.html", '<html><head><!-- <script src="https://sdk.crazygames.com/'
                               'crazygames-sdk-v3.js"></script> --></head></html>')
        self.assertIs(portal_sdks.loader_status(scan, "crazygames")[1], False)
        self.assertIs(portal_sdks.loaded_guard("crazygames", scan).value, False)

    def test_a_package_without_its_own_portals_code_is_red(self):
        # The backported yandex bundle, presented as a crazygames package: no CrazyGames SDK.
        result = portal_sdks.loaded_guard("yandex", self.zip_of("43c08e2+backport-crazygames"))
        self.assertIs(result.value, False)
        self.assertIs(portal_sdks.loaded_guard(
            "yandex", self.zip_of("43c08e2+backport-yandex")).value, True)


class WhatShips(unittest.TestCase):
    """Every file a package ships is read, and nothing read is never a pass (K7 preflight
    review, 2026-10-12). The bundles are the real backported ones, with one file added."""

    setUp = Scanner.setUp

    POKI = "window.PokiSDK.init();\n"  # the real poki identifier the v1.2.0 bundles carry

    def zip_dir(self, directory, archive, prefix="", extra=()):
        with zipfile.ZipFile(archive, "w") as handle:
            for root, _, names in os.walk(directory):
                for name in names:
                    full = os.path.join(root, name)
                    handle.write(full, prefix + os.path.relpath(full, directory)
                                 .replace(os.sep, "/"))
            for name, text in extra:
                handle.writestr(name, text)
        return archive

    def test_a_root_file_beside_a_single_folder_is_scanned(self):
        # A zip of one folder holding index.html, plus a file at the archive's root: the
        # portal receives that file too.
        directory = os.path.join(self.scratch, "clean")
        materialise(BUNDLES["43c08e2+backport-crazygames"], directory)
        archive = self.zip_dir(directory, os.path.join(self.scratch, "pkg.zip"), "game/",
                               extra=[("loader.js", self.POKI)])
        scan = portal_sdks.scan_zip(self.reference, archive)
        self.assertEqual(sorted(portal_sdks.foreign(scan, "crazygames")), ["poki"])
        self.assertIn("loader.js", scan.found["poki"]["poki-sdk"])
        # The folder is still the bundle root: its index.html is the entry page.
        self.assertIs(portal_sdks.loader_status(scan, "crazygames")[1], True)
        self.assertIs(portal_sdks.isolated_guard("crazygames", scan).value, False)

    def test_a_bundle_s_node_modules_is_scanned_as_its_package_ships_it(self):
        # The template's release:package zips the whole bundle directory, node_modules too.
        directory = os.path.join(self.scratch, "clean")
        materialise(BUNDLES["43c08e2+backport-crazygames"], directory)
        os.makedirs(os.path.join(directory, "node_modules", "x"))
        with open(os.path.join(directory, "node_modules", "x", "index.js"), "w") as handle:
            handle.write(self.POKI)
        plain = portal_sdks.scan_directory(self.reference, directory)
        zipped = portal_sdks.scan_zip(self.reference, self.zip_dir(
            directory, os.path.join(self.scratch, "pkg.zip")))
        self.assertEqual(sorted(portal_sdks.foreign(plain, "crazygames")), ["poki"])
        self.assertEqual(plain.found, zipped.found)

    def test_a_missing_or_empty_bundle_is_never_isolated(self):
        missing = portal_sdks.scan_directory(self.reference,
                                             os.path.join(self.scratch, "never-built"))
        self.assertEqual(missing.files, 0)
        self.assertIs(portal_sdks.isolated_guard("yandex", missing).value, False)
        archive = os.path.join(self.scratch, "images.zip")
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("cover.png", b"\x89PNG")
        empty = portal_sdks.scan_zip(self.reference, archive)
        result = portal_sdks.isolated_guard("yandex", empty)
        self.assertIs(result.value, False)
        self.assertIn("no text file", result.reason)
        # verify's check on a bundle it cannot read a file of
        from wgf_verification.checks import platform as checks
        common = {"category": "platform", "required": False, "platform_id": "yandex"}
        check = checks._foreign_sdk(None, "yandex", "build/platforms/yandex/dist",
                                    self.reference, missing, common)
        self.assertEqual(check.status, "FAIL", check.message)

    def test_another_portal_named_in_a_shipped_source_map_fails_as_the_template_audit_does(self):
        # Deliberate, not a false positive: the map ships in the package, and the template's
        # own crazygames-audit reads .map files for FORBIDDEN_DEPENDENCIES too (v1.2.0).
        directory = os.path.join(self.scratch, "clean")
        materialise(BUNDLES["43c08e2+backport-crazygames"], directory)
        with open(os.path.join(directory, "assets", "game.js.map"), "w") as handle:
            handle.write('{"version":3,"sourcesContent":["// unlike PokiSDK, we ..."]}')
        scan = portal_sdks.scan_directory(self.reference, directory)
        self.assertEqual(sorted(portal_sdks.foreign(scan, "crazygames")), ["poki"])


# -- the verify step -------------------------------------------------------------------------

Y8_RESULTS = [
    # What evaluate-assertions.mjs reports for the real SDK-less y8 bundle on contract 1: the
    # echoed platform_sdk fact makes y8_sdk_present hold.
    {"criterion_id": "y8_sdk_present", "measured": "y8", "breached": False,
     "evaluated_at": "2026-10-10T00:00:00Z", "severity": "blocking"},
    {"criterion_id": "y8_no_external_links", "measured": 0, "breached": False,
     "evaluated_at": "2026-10-10T00:00:00Z", "severity": "blocking"},
]


class Verify(VerificationCase):
    def add_platform(self, entry):
        with open(os.path.join(self.repo, "game.config.yaml")) as handle:
            text = handle.read()
        anchor = "  - { id: generic-web, profile: generic-web@1.1.0, role: required }"
        self.write("game.config.yaml", text.replace(anchor, anchor + "\n  " + entry))

    def run_verify(self, pid, variant, audit=None, label=None, fail_own=False):
        """Verify a [generic-web, <pid>] game whose <pid> bundle is the real one (variant
        `43c08e2` or `43c08e2+backport`); generic-web's is the backported yandex bundle with
        the yandex code left out, i.e. no portal SDK at all."""
        profile = {"crazygames": "crazygames@1.3.0", "y8": "y8@1.4.0"}[pid]
        self.add_platform(f"- {{ id: {pid}, profile: {profile}, role: optional }}")
        sdk = fixture("inputs/sdk-report.json")
        sdk["platforms"].append(dict(sdk["platforms"][0], platform_id=pid,
                                     profile_version=profile.split("@")[1]))
        label = label or f"{variant}-{pid}"

        def build(command, cwd, env):
            # vite empties its output directory first; the fake copies over what is there.
            shutil.rmtree(os.path.join(cwd, "dist"), ignore_errors=True)
            result = honoring_build(command, cwd, env)
            with open(os.path.join(cwd, *env["WGF_GAME_CONFIG"].split("/")),
                      encoding="utf-8") as handle:
                chosen = json.load(handle)["platforms"][0]["id"]
            if fail_own and chosen == pid:
                return failing("vite: build failed")
            if chosen == pid:
                with open(os.path.join(cwd, "dist", "index.html"), encoding="utf-8") as handle:
                    index = handle.read()
                # The template's own head script for crazygames, as honoring_build adds it,
                # is replaced by the real bundle's tags.
                index = index.replace('<script src="https://sdk.crazygames.com/'
                                      'crazygames-sdk-v3.js"></script>', "")
                materialise(BUNDLES[label], os.path.join(cwd, "dist"), keep_index=index)
            return result

        def evaluate(command, cwd, env):
            platform = command[command.index("--platform") + 1]
            results = Y8_RESULTS if platform == "y8" else fixture(
                "assertions-generic-web.json") if platform == "generic-web" else []
            return FakeRunner.evaluate(command, cwd, env, results=results)

        handlers = {"pnpm build": build, "evaluate-assertions": evaluate}
        if audit is not None:
            self.write("scripts/crazygames-audit.mjs", "// fixture: the template audit\n")
            handlers["crazygames-audit"] = audit
        runner = FakeRunner(handlers)
        result, report, _ = self.verify(runner=runner, inputs=self.inputs(**{"sdk-report": sdk}))
        return result, report, runner

    def test_the_real_v1_2_0_crazygames_bundle_fails_the_foreign_sdk_check(self):
        result, report, runner = self.run_verify("crazygames", "43c08e2")
        check = self.check(report, "platform.foreign-sdk:crazygames")
        self.assertEqual(check["status"], "FAIL", check["message"])
        self.assertFalse(check["required"])
        for portal in TEMPLATE_AUDIT_FOREIGN:
            self.assertIn(portal, check["message"])
        self.assertIn("Factory scan", check["message"])
        self.assertNotIn("crazygames-audit", check["message"])  # the checkout has none
        # Reported on its platform, not blocking verify: a golden run on the pinned template
        # still passes verify, and platform-validate is where it blocks.
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        readiness = {r["platform_id"]: r["readiness"] for r in report["platform_readiness"]}
        self.assertEqual(readiness["crazygames"], "not-ready")
        self.assertIn("platform.foreign-sdk:crazygames",
                      next(r for r in report["platform_readiness"]
                           if r["platform_id"] == "crazygames")["blocking_checks"])
        self.assertEqual(self.check(report, "platform.sdk-loaded:crazygames")["status"], "PASS")

    def test_the_backported_crazygames_bundle_passes(self):
        result, report, _ = self.run_verify("crazygames", "43c08e2+backport")
        check = self.check(report, "platform.foreign-sdk:crazygames")
        self.assertEqual(check["status"], "PASS", check["message"])
        readiness = {r["platform_id"]: r["readiness"] for r in report["platform_readiness"]}
        self.assertEqual(readiness, {"generic-web": "ready", "crazygames": "ready"})

    def test_the_template_audit_is_reused_when_the_checkout_ships_it(self):
        calls = []

        def audit(command, cwd, env):
            calls.append(command)
            out = os.path.join(cwd, command[command.index("--out") + 1])
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "crazygames-audit.json"), "w") as handle:
                json.dump({"audits": [{"dir": command[command.index("--dir") + 1], "results": [
                    {"id": "unexpected_dependencies", "status": "FAIL",
                     "detail": "gamepix (assets/x.js)"}]}]}, handle)
            return ok()

        # The Factory's scan is clean on the backported bundle; the template audit is not.
        _, report, _ = self.run_verify("crazygames", "43c08e2+backport", audit=audit)
        self.assertEqual(len(calls), 1)
        self.assertIn("build/platforms/crazygames/dist", calls[0])
        check = self.check(report, "platform.foreign-sdk:crazygames")
        self.assertEqual(check["status"], "FAIL", check["message"])
        self.assertIn("scripts/crazygames-audit.mjs", check["message"])
        self.assertIn("gamepix", check["message"])

    def test_a_present_template_audit_that_decides_nothing_never_passes(self):
        # The checkout ships the audit the reference names and it writes no report: the
        # Factory scan alone lacks the audit's own list, so the check is no PASS (MINOR-2).
        def silent(command, cwd, env):
            return ok()
        _, report, _ = self.run_verify("crazygames", "43c08e2+backport", audit=silent)
        check = self.check(report, "platform.foreign-sdk:crazygames")
        self.assertEqual(check["status"], "BLOCKED", check["message"])
        self.assertIn("scripts/crazygames-audit.mjs", check["message"])
        # A Factory scan that already finds other portals still FAILs.
        _, report, _ = self.run_verify("crazygames", "43c08e2", audit=silent)
        self.assertEqual(self.check(report, "platform.foreign-sdk:crazygames")["status"],
                         "FAIL")

    def test_a_failed_platform_build_blocks_both_checks(self):
        # Contract 1: a platform build that fails fails build.build, so nothing is scanned.
        _, report, _ = self.run_verify("crazygames", "43c08e2", fail_own=True)
        for cid in ("platform.foreign-sdk:crazygames", "platform.sdk-loaded:crazygames"):
            check = self.check(report, cid)
            self.assertEqual(check["status"], "BLOCKED", (cid, check["message"]))

    def test_a_platform_whose_own_build_is_missing_never_scans_the_shared_dist(self):
        # Contract 2: the repository builds its platforms itself; crazygames' own bundle is
        # missing while the ordinary build passed. Its checks are BLOCKED on
        # build.platform:crazygames - never a verdict on dist/, which is another bundle
        # (here the real v1.2.0 crazygames one, carrying five other portals) (MINOR-1).
        package = read_json(self.repo, "package.json")
        package["wgf"] = {"template": {"version": "1.3.0", "contract": 2}}
        package.setdefault("scripts", {})["build:platforms"] = "node scripts/build/x.mjs"
        self.write("package.json", json.dumps(package))
        self.add_platform("- { id: crazygames, profile: crazygames@1.3.0, role: optional }")
        sdk = fixture("inputs/sdk-report.json")
        sdk["platforms"].append(dict(sdk["platforms"][0], platform_id="crazygames",
                                     profile_version="1.3.0"))

        def build(command, cwd, env):
            result = FakeRunner.build(command, cwd, env)
            materialise(BUNDLES["43c08e2-crazygames"], os.path.join(cwd, "dist"),
                        keep_index=open(os.path.join(cwd, "dist", "index.html"),
                                        encoding="utf-8").read())
            return result

        def build_platforms(command, cwd, env):
            from wgf_verification.platform_builds import digest_tree
            rel = "build/platforms/generic-web/dist"
            shutil.copytree(os.path.join(FIXTURES, "bundle"), os.path.join(cwd, *rel.split("/")),
                            dirs_exist_ok=True)
            with open(os.path.join(cwd, "build", "platforms", "index.json"), "w") as handle:
                json.dump({"platforms": [{"id": "generic-web", "dir": rel,
                                          "dist_digest": digest_tree(cwd, rel)[0]}]}, handle)
            return ok()
        runner = FakeRunner({"pnpm build": build, "run build:platforms": build_platforms,
                             "evaluate-assertions": lambda c, cwd, env: FakeRunner.evaluate(
                                 c, cwd, env, results=fixture("assertions-generic-web.json"))})
        _, report, _ = self.verify(runner=runner, inputs=self.inputs(**{"sdk-report": sdk}))
        self.assertEqual(self.check(report, "build.bundle")["status"], "PASS")
        self.assertNotEqual(self.check(report, "build.platform:crazygames")["status"], "PASS")
        for cid in ("platform.foreign-sdk:crazygames", "platform.sdk-loaded:crazygames"):
            check = self.check(report, cid)
            self.assertEqual(check["status"], "BLOCKED", (cid, check["message"]))
            self.assertIn("build.platform:crazygames", check["message"])

    def test_the_real_sdk_less_y8_bundle_is_blocked_for_a_person(self):
        result, report, _ = self.run_verify("y8", "43c08e2+backport")
        loaded = self.check(report, "platform.sdk-loaded:y8")
        self.assertEqual(loaded["status"], "BLOCKED", loaded["message"])
        self.assertFalse(loaded["required"])
        self.assertIn("WGF_Y8_APP_ID", loaded["message"])
        self.assertIn("create-before-build", loaded["message"])
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.message)
        # The echoed fact is no longer evidence: y8_sdk_present is not counted.
        policy = self.check(report, "policy.assertions:y8")
        recorded = next(e["data"] for e in policy["evidence"]
                        if (e.get("data") or {}).get("results") is not None)
        self.assertEqual([r["criterion_id"] for r in recorded["results"]],
                         ["y8_no_external_links"])
        self.assertEqual([r["criterion_id"] for r in recorded["not_counted"]],
                         ["y8_sdk_present"])
        readiness = {r["platform_id"]: r["readiness"] for r in report["platform_readiness"]}
        self.assertEqual(readiness["y8"], "unverified")

    def test_a_y8_bundle_built_with_its_ids_loads_the_sdk(self):
        _, report, _ = self.run_verify("y8", None, label="43c08e2+backport-y8-with-ids")
        loaded = self.check(report, "platform.sdk-loaded:y8")
        self.assertEqual(loaded["status"], "PASS", loaded["message"])
        self.assertEqual(self.check(report, "platform.foreign-sdk:y8")["status"], "PASS")

    def test_generic_web_with_no_portal_sdk_passes(self):
        _, report, _ = self.run_verify("crazygames", "43c08e2+backport")
        self.assertEqual(self.check(report, "platform.foreign-sdk:generic-web")["status"],
                         "PASS")
        with self.assertRaises(AssertionError):
            self.check(report, "platform.sdk-loaded:generic-web")  # no loader declared


# -- platform-validate -----------------------------------------------------------------------

from test_publish_module import PublishCase  # noqa: E402


class ValidateCase(PublishCase):
    """platform-validate scans the package it would hand to the portal. generic-web has no SDK,
    so any portal's SDK in its package is foreign: here, the real poki/yandex/... text of the
    v1.2.0 crazygames bundle, written into the fixture game's bundle before it is verified and
    released."""

    carry = None

    def prepare_bundle(self, game):
        if self.carry is None:
            return
        excerpts = [e["text"] for e in BUNDLES[self.carry]["excerpts"]
                    if e["file"].endswith(".js")]
        with open(game.path("dist", "assets", "app.js"), "a", encoding="utf-8") as handle:
            handle.write("\n".join(excerpts) + "\n")
        game.touch_bundle(1_700_000_000)

    def guards(self, result):
        return {g["guard"]: (g["verdict"], g["reason"])
                for g in result.artifacts[0].content["guards"]}


class Validate(ValidateCase):
    def test_a_clean_package_is_green_on_both_guards(self):
        self.write_metadata()
        result = self.validate()
        guards = self.guards(result)
        self.assertEqual(guards["portal_sdk_isolated"][0], "GREEN", guards)
        self.assertEqual(guards["portal_sdk_loaded"][0], "GREEN", guards)


class ValidateForeign(ValidateCase):
    carry = "43c08e2-crazygames"

    def test_a_package_carrying_other_portals_sdks_is_refused(self):
        self.write_metadata()
        result = self.validate()
        self.assertEqual((result.outcome, result.route), (StepOutcome.FAILED, "fail"))
        record = result.artifacts[0].content
        self.assertEqual(record["readiness"], "BLOCKED")
        verdict, reason = self.guards(result)["portal_sdk_isolated"]
        self.assertEqual(verdict, "RED")
        for portal in ("poki", "yandex", "crazygames", "y8", "gamedistribution",
                       "gamemonetize"):
            self.assertIn(portal, reason)
        self.assertIn("portal_sdk_isolated RED", result.error)


if __name__ == "__main__":
    unittest.main()
