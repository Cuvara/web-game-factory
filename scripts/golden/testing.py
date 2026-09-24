"""The test cases behind scripts/tests/test_golden_2d.py and test_golden_3d.py.

Two kinds, per golden game:

    Fast (always on, no node, no browser, ~seconds)
        the harness configuration, the frozen fixtures, the research -> G3 slice of the real
        workflow (the steering: the design must declare the game's engine), the replay
        developer's file mapping against the template's examples, the port's static
        conformance, and the golden reviewer on a throwaway repository.

    EndToEnd (only with WGF_GOLDEN=1; minutes)
        the whole golden run through the harness, then the summary asserted: every step at
        its expected outcome, the engine everywhere, a drafted release manifest whose zip
        sha256s reproduce, evidence statuses never upgraded, the independent browser
        evidence passed, and no process left behind. Without WGF_GOLDEN=1 it is SKIPPED,
        and a skip is never a pass: `wgf test-core` reports the category as SKIP.

A test module binds a game key: `Fast = fast_case("2d")`, `EndToEnd = end_to_end_case("2d")`.
"""

import json
import os
import re
import shutil
import tempfile
import unittest

from wgflib import paths, procs
from wgflib.workflow.api import RunRequest

from golden import games, harness, replay_developer, reviewer, summary

RUN_GOLDEN = os.environ.get("WGF_GOLDEN") == "1"
SKIP_REASON = ("the golden runs are real pipelines (pnpm, vite, Playwright, Chromium; minutes "
               "each): set WGF_GOLDEN=1 to run them. A skip is not a pass.")
PLACEHOLDER_ARGS = ("{brief}", "{repo}", "{key}", "{verdict}", "{commit}")


def _template_has_examples():
    return all(os.path.isdir(os.path.join(harness.TEMPLATE_DIR, "examples", g.example))
               for g in games.GAMES.values())


def fast_case(key):
    game = games.game(key)

    class Fast(unittest.TestCase):
        def setUp(self):
            self.workdir = tempfile.mkdtemp(prefix=f"wgf-golden-fast-{key}-")
            self.addCleanup(shutil.rmtree, self.workdir, True)

        # -- configuration ---------------------------------------------------------------

        def test_config_is_isolated_and_offline(self):
            config = harness.build_config(game, self.workdir, harness.TEMPLATE_DIR)
            games_dir = os.path.join(self.workdir, "games")
            self.assertEqual(config["init"]["source"], "local")
            self.assertEqual(config["init"]["projects_dir"], games_dir)
            self.assertFalse(config["init"]["adopt_existing"])
            for section, key_name in (("develop", "checkouts"), ("review", "checkouts"),
                                      ("verification", "checkouts"), ("release", "checkouts"),
                                      ("sdk", "games_dir")):
                self.assertEqual(config[section][key_name], games_dir, section)
            self.assertEqual(config["assets"]["root"], os.path.join(games_dir, game.title_id))
            self.assertTrue(config["storage"]["directory"].startswith(self.workdir))
            self.assertFalse(config["discovery"]["live"])
            self.assertEqual(config["discovery"]["catalog"], game.catalog)
            self.assertEqual(config["discovery"]["as_of"], games.AS_OF)

        def test_only_reversible_gates_are_auto_approved(self):
            from wgflib.workflow.checkpoint import irreversible_gates
            config = harness.build_config(game, self.workdir, harness.TEMPLATE_DIR)
            approved = set(config["checkpoints"]["auto_approve"])
            self.assertEqual(approved, {"G2", "G3"})
            self.assertEqual(approved & set(irreversible_gates()), set())

        def test_developer_and_reviewer_are_the_labelled_stand_ins(self):
            config = harness.build_config(game, self.workdir, harness.TEMPLATE_DIR)
            developer = config["develop"]["developer"]
            self.assertEqual(developer["kind"], "command")
            self.assertTrue(developer["argv"][1].endswith("scripts/golden/replay_developer.py"))
            self.assertIn(key, developer["argv"])
            reviewer_cfg = config["review"]["reviewer"]
            self.assertEqual(reviewer_cfg["kind"], "command")
            self.assertTrue(reviewer_cfg["argv"][1].endswith("scripts/golden/reviewer.py"))
            self.assertEqual(reviewer_cfg["verdict_from"], "file")
            for argv in (developer["argv"], reviewer_cfg["argv"]):
                self.assertTrue(set(argv) & set(PLACEHOLDER_ARGS))
            self.assertIn("not an AI developer", replay_developer.REPLAY_LABEL)
            self.assertIn("not an AI reviewer", reviewer.REVIEWER)

        def test_the_installation_config_is_only_read(self):
            path = os.path.join(paths.CONFIG, "factory.yaml")
            with open(path, "rb") as handle:
                before = handle.read()
            config = harness.build_config(game, self.workdir, harness.TEMPLATE_DIR)
            config["init"]["owner"] = "mutated"
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), before)
            self.assertNotEqual(harness.base_config().get("init", {}).get("owner"), "mutated")

        # -- fixtures and steering --------------------------------------------------------

        def test_fixtures_are_valid_and_not_from_the_future(self):
            from wgflib.yamllite import load_file
            catalog = load_file(game.catalog)
            self.assertEqual(len(catalog["archetypes"]), 1)
            snapshots = os.path.join(games.RESEARCH_CORPUS, "snapshots")
            names = sorted(os.listdir(snapshots))
            self.assertTrue(names)
            for name in names:
                with open(os.path.join(snapshots, name), encoding="utf-8") as handle:
                    snapshot = json.load(handle)
                self.assertEqual(snapshot["id"] + ".json", name)
                self.assertLessEqual(snapshot["observed_at"], games.AS_OF, name)

        def test_research_to_g3_steers_to_the_engine(self):
            """The real research, strategy, design and tech-plan modules, gates G2/G3."""
            run = harness.GoldenRun(key, workdir=self.workdir, browser=False)
            api = run.api()
            state = api.run(RunRequest(scope="research", project_id=game.title_id))
            self.assertEqual(state.steps["research"].status, "SUCCESS", state.message)
            state = api.run(RunRequest(scope="plan", run_id=state.run_id))
            for step_id in ("strategy", "strategy-review", "design", "tech-plan",
                            "tech-plan-review"):
                self.assertEqual(state.steps[step_id].status, "SUCCESS",
                                 f"{step_id}: {state.steps[step_id].error}")
            design = api.store.read_artifact(state.run_id, state.latest_of_type("game-design"))
            plan = api.store.read_artifact(state.run_id, state.latest_of_type("tech-plan"))
            self.assertEqual(design["engine"]["type"], game.engine)
            self.assertEqual(design["title_id"], game.title_id)
            self.assertEqual(plan["engine"]["type"], game.engine)
            self.assertEqual(plan["repo_params"]["game_config"]["engine"]["type"], game.engine)

        # -- the replay developer ---------------------------------------------------------

        def test_port_manifest_maps_onto_the_template_example(self):
            if not _template_has_examples():
                self.skipTest(f"no template examples at {harness.TEMPLATE_DIR}")
            port = replay_developer.load_port(key)
            self.assertEqual(port["engine"], game.engine)
            self.assertEqual(port["example"], game.example)
            copies = replay_developer.plan_copies(port, harness.TEMPLATE_DIR)
            self.assertEqual(len(copies), len(port["copy"]))
            for target, text in copies:
                if target.endswith(".ts"):
                    self.assertTrue(text.startswith("// GOLDEN-RUN REPLAY: copied from"))
            deps = replay_developer.engine_dependencies(port, harness.TEMPLATE_DIR)
            self.assertEqual(set(deps), set(port["engine_dependencies"]))

        def test_port_satisfies_the_develop_static_rules(self):
            from wgf_develop import brief as briefs
            from wgf_develop import checks
            port = replay_developer.load_port(key)
            files = dict(replay_developer.port_files(key))
            engine_dir = briefs.ENGINE_DIRS[game.engine] + "/"
            for relative, source in files.items():
                for prefix in briefs.PROTECTED_PATHS:
                    self.assertFalse(relative == prefix or relative.startswith(prefix + "/"),
                                     f"{relative} is template-owned")
                if not relative.endswith((".ts", ".js")):
                    continue
                with open(source, encoding="utf-8") as handle:
                    text = handle.read()
                self.assertIn("GOLDEN-RUN REPLAY", text, relative)
                self.assertIsNone(checks.PORTAL_SDK.search(text), relative)
                if relative.startswith("src/") and not relative.startswith("src/platform/"):
                    self.assertIsNone(re.search(r"\.show(Rewarded|Interstitial)\s*\(", text),
                                      relative)
                for match in checks._IMPORT.finditer(text):
                    module = next(g for g in match.groups() if g)
                    for name, pattern in checks.ENGINE_MODULES.items():
                        if pattern.match(module):
                            self.assertEqual(name, game.engine, relative)
                            self.assertTrue(relative.startswith(engine_dir), relative)
            main = files["src/main.ts"]
            with open(main, encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotRegex(text, r"\bBootScene\b")
            # The template's own boot lines, which the sdk step patches, are kept verbatim.
            self.assertIn('import { createPlatform } from "@wgf/platform-sdk";\n', text)
            self.assertIn("  const platform = createPlatform(primaryPlatform().id, "
                          "{ namespace: config.game.id });\n  await platform.initialize();\n",
                          text)
            self.assertIn("  const game = new Game();\n", text)
            self.assertIn("new DefaultGameIntegration(", text)
            self.assertIn(game.scene_id, port["scene_id"])

        def test_replay_refuses_a_brief_for_the_other_engine(self):
            other = "threejs" if game.engine == "pixijs" else "pixijs"
            brief_dir = os.path.join(self.workdir, "docs", "development")
            os.makedirs(brief_dir)
            with open(os.path.join(brief_dir, "brief.json"), "w", encoding="utf-8") as handle:
                json.dump({"engine": other, "mvp": []}, handle)
            with open(os.path.join(brief_dir, "brief.md"), "w", encoding="utf-8") as handle:
                handle.write("# brief\n")
            with self.assertRaises(replay_developer.ReplayError) as caught:
                replay_developer.replay(key, os.path.join(brief_dir, "brief.md"), self.workdir)
            self.assertIn("will not pretend", str(caught.exception))

        def test_report_is_honest_about_what_the_replay_does_not_cover(self):
            port = replay_developer.load_port(key)
            brief = {"engine": game.engine,
                     "mvp": list(port["mvp"]) + ["Something the design invents later"],
                     "placements": [{"kind": "rewarded", "trigger": "On death"},
                                    {"kind": "interstitial", "trigger": "Between runs"}],
                     "assets": [{"id": "background-main"}],
                     "required_systems": [{"id": "boot"}, {"id": "hud"}]}
            report = replay_developer.build_report(brief, port, ["src/main.ts"])
            self.assertEqual([m["item"] for m in report["mvp"]], brief["mvp"])
            invented = report["mvp"][-1]
            self.assertEqual(invented["status"], "cut")
            self.assertIn(invented["item"], [d["item"] for d in report["scope_deltas"]])
            self.assertEqual({p["kind"] for p in report["placements"]},
                             {"rewarded", "interstitial"})
            self.assertEqual(report["assets"], [{"id": "background-main",
                                                 "status": "placeholder"}])
            self.assertIn("REPLAY", report["known_issues"][0])
            self.assertIn("not an AI developer", report["replay"]["developer"])

        # -- the golden reviewer -----------------------------------------------------------

        def test_reviewer_approves_a_clean_game_commit_and_blocks_a_template_edit(self):
            repo = os.path.join(self.workdir, "repo")
            os.makedirs(os.path.join(repo, "docs", "development"))
            git = lambda *a: procs.run(["git", "-C", repo, *a], timeout=30)  # noqa: E731
            self.assertTrue(git("init", "-q").ok)
            git("config", "user.email", "golden@example.invalid")
            git("config", "user.name", "golden")
            _write(repo, "package.json", json.dumps({"dependencies": {}}))
            _write(repo, "vite.config.ts", "export default {};\n")
            git("add", "-A")
            git("commit", "-q", "-m", "template")
            baseline = git("rev-parse", "HEAD").stdout.strip()

            _write(repo, "docs/development/brief.json",
                   json.dumps({"engine": game.engine, "baseline_commit": baseline}))
            _write(repo, "docs/development/report.json",
                   json.dumps({"engine": game.engine, "replay": {"developer": "replay"}}))
            _write(repo, "src/main.ts", "export {};\n")
            _write(repo, "tests/unit/rules.test.ts", "export {};\n")
            _write(repo, "tests/e2e/game.spec.ts", "// @boot @start @game-over @restart\n")
            dep = next(iter(summary_engine_packages(game.engine)))
            _write(repo, "package.json", json.dumps({"dependencies": {dep: "1"}}))
            git("add", "-A")
            git("commit", "-q", "-m", "game")
            head = git("rev-parse", "HEAD").stdout.strip()
            blockers, _ = reviewer.review(key, repo, head)
            self.assertEqual(blockers, [])

            _write(repo, "vite.config.ts", "export default { base: '/' };\n")
            _write(repo, "src/ads.ts", "window.PokiSDK.commercialBreak(); x.showRewarded();\n")
            git("add", "-A")
            git("commit", "-q", "-m", "bad")
            head = git("rev-parse", "HEAD").stdout.strip()
            blockers, _ = reviewer.review(key, repo, head)
            ids = {b["id"].rsplit("-", 1)[0] for b in blockers}
            self.assertEqual(ids, {"allowed-paths", "no-portal-sdk", "ad-calls-in-seam"})

    Fast.__name__ = Fast.__qualname__ = f"Golden{key.upper()}Fast"
    return Fast


def summary_engine_packages(engine):
    return reviewer.ENGINE_PACKAGES[engine]


def _write(repo, relative, text):
    path = os.path.join(repo, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def end_to_end_case(key):
    game = games.game(key)

    @unittest.skipUnless(RUN_GOLDEN, SKIP_REASON)
    class EndToEnd(unittest.TestCase):
        summary = None
        workdir = None

        @classmethod
        def setUpClass(cls):
            cls.workdir = harness.make_workdir()
            run = harness.GoldenRun(key, workdir=cls.workdir)
            try:
                cls.summary = run.execute()
            finally:
                procs.terminate_all()

        @classmethod
        def tearDownClass(cls):
            if cls.workdir and os.environ.get("WGF_GOLDEN_KEEP") != "1":
                shutil.rmtree(cls.workdir, ignore_errors=True)

        def _explain(self):
            return (f"golden {key} summary: {os.path.join(self.workdir, 'evidence', f'golden-{key}.json')}"
                    f" (set WGF_GOLDEN_KEEP=1 to keep it)")

        def test_every_step_reached_its_expected_outcome(self):
            failed = [f"{s['step']}: {s['status']} (expected {s['expected']}) {s['message']}"
                      for s in self.summary["steps"] if not s["reached"]]
            self.assertEqual(failed, [], self._explain())
            self.assertEqual(self.summary["run_status"], "COMPLETED", self._explain())

        def test_the_engine_is_the_games_everywhere(self):
            self.assertTrue(self.summary["engine"]["consistent"], self.summary["engine"])
            self.assertEqual(self.summary["engine"]["expected"], game.engine)

        def test_release_drafted_a_manifest_with_reproducing_zip_hashes(self):
            release = self.summary["release"]
            self.assertIsNotNone(release, self._explain())
            self.assertEqual(release["state"], "draft")
            self.assertTrue(release["manifest_path"])
            self.assertTrue(release["packages"])
            for package in release["packages"]:
                self.assertRegex(package["checksum"] or "", r"^sha256:[0-9a-f]{64}$")
                self.assertTrue(package["reproduces"], package)
                self.assertTrue(package["content_digest"])

        def test_evidence_statuses_are_never_upgraded(self):
            evidence = self.summary["evidence"]
            self.assertEqual(evidence["unknown_statuses"], [])
            manifest = evidence["release_manifest"]
            qa = evidence["qa_report"]
            # The draft carries the verification's status exactly (PASS_MOCK stays PASS_MOCK).
            self.assertEqual(manifest["evidence_status"], qa["evidence_status"])
            for platform in manifest["platforms"]:
                self.assertEqual(platform["external_approval"], "not-claimed")
                self.assertNotEqual(platform["portal_status"], "PASS",
                                    "no portal was contacted, so no portal status can be PASS")

        def test_artifacts_are_pinned_by_hash(self):
            for record in self.summary["artifacts"]:
                self.assertRegex(record["content_hash"] or "", r"^sha256:[0-9a-f]{64}$",
                                 record["ref"])
            types = {r["type"] for r in self.summary["artifacts"]}
            for expected in ("research-report", "opportunity", "title-strategy", "game-design",
                             "tech-plan", "scaffold-record", "asset-manifest",
                             "prototype-report", "review-report", "sdk-report",
                             "verification-report", "qa-report", "release-manifest"):
                self.assertIn(expected, types)

        def test_the_game_passed_the_browser_independently(self):
            browser = self.summary["browser"]
            self.assertIsNotNone(browser, self._explain())
            self.assertTrue(browser["suites"]["passed"], browser["suites"].get("failed"))
            self.assertEqual(set(browser["suites"]["projects"]), {"desktop", "mobile"})
            self.assertTrue(browser["probe"]["passed"], browser["probe"])
            self.assertEqual(browser["probe"]["engine_reported"], game.engine)
            for viewport in browser["probe"]["viewports"].values():
                self.assertEqual(viewport["page_errors"], [])
                self.assertEqual(set(viewport["screenshot_sha256"]),
                                 {"boot", "playing", "over"})
            self.assertEqual(browser["bundle"]["source"], "release-package")
            self.assertTrue(browser["bundle"]["matches_manifest"])
            self.assertTrue(self.summary["browser_passed"])

        def test_the_repository_is_clean_and_nothing_was_pushed(self):
            repo = self.summary["repository"]
            self.assertTrue(repo["clean"], repo["dirty_paths"])
            remotes = procs.run(["git", "-C", repo["path"], "remote"], timeout=30)
            self.assertEqual(remotes.stdout.strip(), "")

        def test_no_process_outlived_the_run(self):
            self.assertEqual(self.summary["leftover_processes"], [])
            self.assertEqual(summary.leftover_processes(self.workdir), [])
            self.assertEqual(procs.live_groups(), [])

        def test_the_run_passed(self):
            self.assertTrue(self.summary["passed"], self._explain())

    EndToEnd.__name__ = EndToEnd.__qualname__ = f"Golden{key.upper()}EndToEnd"
    return EndToEnd
