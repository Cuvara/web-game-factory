"""wgflib.checkout: one checkout resolver for every step, and the per-checkout lock.

    python -m unittest scripts/tests/test_checkout.py

The resolver matrix (precedence, WGF_GAME_REPO for every step, local_path, the deprecated
keys, hostile names, relative paths), the lock (another run is refused, the same run is not,
a dead holder is taken over), assets landing in the checkout and listed in the develop
brief, the develop module's template literals coming from the template contract, and old
1.1.0 scaffold-records still validating and resolving.
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgflib import checkout, paths, provenance  # noqa: E402
from wgflib import template_contract as contract  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402

STEPS = ("init", "assets", "develop", "review", "sdk", "verification", "release")


class Logger:
    def __init__(self):
        self.records = []

    def warning(self, message, **fields):
        self.records.append(("warning", message, fields))

    def info(self, message, **fields):
        self.records.append(("info", message, fields))

    debug = error = info

    def warnings(self):
        return [" ".join(str(v) for v in f.values()) for level, _m, f in self.records
                if level == "warning"]


def scaffold(name="demo", local_path=None):
    repository = {"owner": "acme", "name": name}
    if local_path is not None:
        repository["local_path"] = local_path
    return {"title_id": name, "repository": repository}


class Case(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-checkout-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def mkdir(self, *parts):
        path = os.path.join(self.scratch, *parts)
        os.makedirs(path, exist_ok=True)
        return path


class Precedence(Case):
    def test_the_order_is_with_then_env_then_local_path_then_checkouts(self):
        recorded = self.mkdir("recorded")
        config = {"checkouts": os.path.join(self.scratch, "games")}
        record = scaffold(local_path=recorded)
        env = {"WGF_GAME_REPO": os.path.join(self.scratch, "from-env")}
        with_ = {"repo_dir": os.path.join(self.scratch, "from-with")}
        for section in STEPS:
            with self.subTest(section=section):
                self.assertEqual(checkout.locate(config, record, section, with_, env),
                                 (with_["repo_dir"], "step with: repo_dir"))
                self.assertEqual(checkout.locate(config, record, section, {}, env),
                                 (env["WGF_GAME_REPO"], "WGF_GAME_REPO"))
                self.assertEqual(checkout.locate(config, record, section, {}, {}),
                                 (recorded, "scaffold-record repository.local_path"))
                path, source = checkout.locate(config, scaffold(), section, {}, {})
                self.assertEqual(path, os.path.join(self.scratch, "games", "demo"))
                self.assertTrue(source.startswith("factory.checkouts"), source)

    def test_game_repo_is_an_alias_of_repo_dir(self):
        target = os.path.join(self.scratch, "x")
        self.assertEqual(checkout.locate({}, None, "sdk", {"game_repo": target}, {})[0], target)
        self.assertEqual(checkout.locate({}, None, "verification", {"game_repo": target},
                                         {})[0], target)
        self.assertEqual(checkout.locate({}, None, "sdk", {"game_repo": target,
                                                           "repo_dir": target}, {})[0], target)
        with self.assertRaises(checkout.CheckoutError):
            checkout.locate({}, None, "sdk", {"game_repo": target, "repo_dir": "/elsewhere"},
                            {})

    def test_a_recorded_local_path_that_is_gone_falls_back_with_a_warning(self):
        logger = Logger()
        config = {"checkouts": os.path.join(self.scratch, "games")}
        path, source = checkout.locate(config, scaffold(local_path="/no/such/dir"), "develop",
                                       {}, {}, logger=logger)
        self.assertEqual(path, os.path.join(self.scratch, "games", "demo"))
        self.assertIn("factory.checkouts", source)
        self.assertTrue(any("/no/such/dir" in w for w in logger.warnings()), logger.records)

    def test_relative_paths_resolve_against_the_factory_root_not_the_cwd(self):
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.scratch)
        expected = os.path.normpath(os.path.join(paths.ROOT, "..", "games", "demo"))
        self.assertEqual(checkout.locate({"checkouts": "../games"}, scaffold(), "sdk", {},
                                         {})[0], expected)
        self.assertEqual(checkout.locate({}, None, "sdk", {"repo_dir": "../games/demo"},
                                         {})[0], expected)
        self.assertEqual(checkout.locate({}, None, "sdk", {},
                                         {"WGF_GAME_REPO": "../games/demo"})[0], expected)
        self.assertEqual(checkout.locate({}, scaffold(local_path="../games/demo"), "sdk", {},
                                         {})[0] if os.path.isdir(expected) else expected,
                         expected)

    def test_the_default_is_the_factorys_parent_directory(self):
        self.assertEqual(checkout.locate({}, scaffold(), "release", {}, {})[0],
                         os.path.normpath(os.path.join(paths.ROOT, "..", "demo")))

    def test_without_a_name_there_is_no_checkout(self):
        with self.assertRaises(checkout.CheckoutError):
            checkout.locate({}, None, "develop", {}, {})
        self.assertEqual(checkout.locate({}, None, "develop", {}, {}, name="t")[0],
                         os.path.normpath(os.path.join(paths.ROOT, "..", "t")))

    def test_a_hostile_repository_name_is_refused_whichever_rule_decides(self):
        env = {"WGF_GAME_REPO": self.scratch}
        for bad in ("..", ".", "a/b", "../factory", "a\\b", "", " demo", "x\0y", "x\n"):
            with self.subTest(name=bad):
                with self.assertRaises(checkout.CheckoutError):
                    checkout.locate({}, scaffold(bad), "develop", {}, {})
                with self.assertRaises(checkout.CheckoutError):
                    checkout.locate({}, scaffold(bad), "develop", {}, env)
                with self.assertRaises(checkout.CheckoutError):
                    checkout.locate({}, None, "init", {}, {}, name=bad)


    def test_the_factory_itself_is_never_a_checkout(self):
        for where in (paths.ROOT, os.path.dirname(paths.ROOT), "."):
            with self.subTest(where=where):
                with self.assertRaises(checkout.CheckoutError):
                    checkout.locate({}, None, "develop", {"repo_dir": where}, {})
                with self.assertRaises(checkout.CheckoutError):
                    checkout.locate({}, None, "develop", {}, {"WGF_GAME_REPO": where})
        with self.assertRaises(checkout.CheckoutError):
            checkout.locate({}, scaffold(local_path="."), "release", {}, {})


class LegacyKeys(Case):
    def test_each_deprecated_key_alone_still_works(self):
        for section, key in checkout.LEGACY_KEYS:
            with self.subTest(key=f"{section}.{key}"):
                config = {section: {key: os.path.join(self.scratch, section)}}
                for step in STEPS:
                    path, source = checkout.locate(config, scaffold(), step, {}, {})
                    self.assertEqual(path, os.path.join(self.scratch, section, "demo"))
                    self.assertIn("deprecated", source)

    def test_every_step_reads_one_directory_and_disagreement_is_warned(self):
        config = {"verification": {"checkouts": "/srv/verify"},
                  "develop": {"checkouts": "/srv/develop"},
                  "sdk": {"games_dir": "/srv/develop"}}
        for step in STEPS:
            logger = Logger()
            with self.subTest(step=step):
                path, _ = checkout.locate(config, scaffold(), step, {}, {}, logger=logger)
                self.assertEqual(path, os.path.normpath("/srv/develop/demo"))
                self.assertTrue(any("verification.checkouts" in w
                                    for w in logger.warnings()), logger.records)

    def test_factory_checkouts_wins_over_every_deprecated_key(self):
        config = {"checkouts": "/srv/games", "develop": {"checkouts": "/srv/develop"},
                  "init": {"projects_dir": "/srv/games"}}
        logger = Logger()
        self.assertEqual(checkout.locate(config, scaffold(), "review", {}, {}, logger=logger)[0],
                         os.path.normpath("/srv/games/demo"))
        warned = " ".join(logger.warnings())
        self.assertIn("develop.checkouts", warned)
        self.assertNotIn("init.projects_dir", warned)  # agrees: nothing to say

    def test_sdk_game_repo_is_deprecated_and_sdk_only(self):
        config = {"sdk": {"game_repo": "/srv/one-game"}, "checkouts": "/srv/games"}
        logger = Logger()
        self.assertEqual(checkout.locate(config, scaffold(), "sdk", {}, {}, logger=logger),
                         ("/srv/one-game", "factory.sdk.game_repo (deprecated)"))
        self.assertTrue(logger.warnings())
        self.assertEqual(checkout.locate(config, scaffold(), "verification", {}, {})[0],
                         os.path.normpath("/srv/games/demo"))
        # WGF_GAME_REPO still comes first.
        self.assertEqual(checkout.locate(config, scaffold(), "sdk", {},
                                         {"WGF_GAME_REPO": "/srv/env"})[0], "/srv/env")

    def test_a_steps_own_with_checkouts_overrides_the_directory_for_that_step(self):
        self.assertEqual(checkout.locate({"checkouts": "/a"}, scaffold(), "develop",
                                         {"checkouts": "/b"}, {})[0],
                         os.path.normpath("/b/demo"))


class RecordedPath(Case):
    def test_beside_the_factory_is_relative_elsewhere_absolute(self):
        beside = os.path.join(os.path.dirname(paths.ROOT), "some-game")
        self.assertEqual(checkout.record_path(beside), "../some-game")
        self.assertEqual(checkout.resolve(checkout.record_path(beside)), beside)
        elsewhere = os.path.join(self.scratch, "g")
        if os.path.commonpath([os.path.dirname(paths.ROOT), elsewhere]) != \
                os.path.dirname(paths.ROOT):
            self.assertEqual(checkout.record_path(elsewhere), elsewhere)


class StepResolvers(Case):
    """WGF_GAME_REPO, and the scaffold's local_path, reach every step's own resolver."""

    def test_every_steps_resolver_honours_wgf_game_repo(self):
        from unittest import mock

        from wgf_develop.settings import Settings as DevelopSettings
        from wgf_init.step import InitSettings
        from wgf_review.settings import Settings as ReviewSettings
        from wgf_verification.session import locate_checkout

        repo = self.mkdir("env-repo")
        with open(os.path.join(repo, "package.json"), "w") as handle:
            handle.write("{}")
        env = {"WGF_GAME_REPO": repo}
        config = {"checkouts": os.path.join(self.scratch, "games")}
        self.assertEqual(DevelopSettings.resolve(config).checkout_for("demo", environ=env),
                         repo)
        self.assertEqual(ReviewSettings.resolve(config).checkout_for("demo", environ=env),
                         repo)
        init = InitSettings.from_config({"init": {"source": "local"}, **config}, environ=env)
        self.assertEqual(init.local_path("demo"), repo)
        for section in ("verification", "release"):
            self.assertEqual(locate_checkout({}, config, scaffold(), env, section=section)[0],
                             repo)
        with mock.patch.dict(os.environ, env):
            from wgf_sdk.step import SdkStep

            class Context:
                logger = Logger()

            Context.config = config
            import test_verification as tv
            step = SdkStep(tv.StepDefinition({"id": "sdk", "type": "sdk", "inputs": [],
                                              "outputs": ["sdk-report"]},
                                             retry=None, max_visits=None))
            self.assertEqual(step._game_repo(Context, scaffold())[0], repo)

    def test_verify_and_release_do_not_fall_through_past_the_rule_that_decided(self):
        from wgf_verification.session import locate_checkout
        games = self.mkdir("games", "demo")
        with open(os.path.join(games, "package.json"), "w") as handle:
            handle.write("{}")
        config = {"checkouts": os.path.join(self.scratch, "games")}
        path, evidence = locate_checkout({"repo_dir": os.path.join(self.scratch, "absent")},
                                         config, scaffold(), {})
        self.assertIsNone(path)
        self.assertIn("step with: repo_dir", evidence.summary)
        self.assertEqual(locate_checkout({}, config, scaffold(), {})[0], games)


class OldScaffoldRecords(Case):
    def record(self, version, **repository):
        body = {"title_id": "demo",
                "repository": dict({"owner": "acme", "name": "demo"}, **repository),
                "template": {"repository": "acme/web-game-template"},
                "game_config": {"path": "game.config.yaml"}, "outcome": "created"}
        body["provenance"] = provenance.build(
            "scaffold-record", artifact_id="wgf:scaffold-record:demo:20260901-01",
            produced_by=provenance.producer("release"), produced_at="2026-09-01T00:00:00Z",
            schema_version=version, title_id="demo")
        return provenance.seal(body)

    def test_the_schema_is_1_2_with_local_path_optional(self):
        self.assertEqual(provenance.version_of("scaffold-record"), "1.2.0")
        contracts = ArtifactContracts()
        self.assertEqual(contracts.problems("scaffold-record", self.record("1.1.0")), [])
        self.assertEqual(contracts.problems("scaffold-record",
                                            self.record("1.2.0", local_path="../demo")), [])
        self.assertTrue(contracts.problems("scaffold-record",
                                           self.record("1.2.0", local_path="")))

    def test_an_old_record_resolves_by_the_checkouts_directory(self):
        path, source = checkout.locate({"checkouts": self.scratch}, self.record("1.1.0"),
                                       "release", {}, {})
        self.assertEqual(path, os.path.join(self.scratch, "demo"))
        self.assertIn("repository name demo", source)


class Lock(Case):
    def setUp(self):
        super().setUp()
        self.storage = self.mkdir("store")
        self.repo = self.mkdir("games", "demo")

    def hold_in_child(self, run_id):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from wgflib import checkout; "
                "checkout.acquire(sys.argv[2], sys.argv[3], sys.argv[4]); "
                "print('held', flush=True); sys.stdin.read()")
        child = subprocess.Popen([sys.executable, "-c", code, SCRIPTS, self.repo, run_id,
                                  self.storage], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 text=True)
        self.addCleanup(lambda: (child.poll() is None) and (child.kill(), child.wait()))
        self.assertEqual(child.stdout.readline().strip(), "held")
        return child

    def test_another_live_run_is_refused_and_named(self):
        child = self.hold_in_child("run-other")
        with self.assertRaises(checkout.CheckoutLocked) as refused:
            checkout.acquire(self.repo, "run-mine", self.storage)
        self.assertIn("run-other", str(refused.exception))
        self.assertIn(str(child.pid), str(refused.exception))

    def test_the_same_run_is_never_refused(self):
        self.hold_in_child("run-1")
        lease = checkout.acquire(self.repo, "run-1", self.storage)
        lease.release()
        # ... and releasing it did not remove the other process's lock.
        with self.assertRaises(checkout.CheckoutLocked):
            checkout.acquire(self.repo, "run-2", self.storage)

    def test_a_dead_holder_is_taken_over(self):
        child = self.hold_in_child("run-dead")
        child.stdin.close()
        child.wait()
        lease = checkout.acquire(self.repo, "run-mine", self.storage)
        with open(lease.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["run_id"], "run-mine")
        lease.release()
        self.assertFalse(os.path.exists(lease.path))

    @unittest.skipUnless(os.path.exists("/proc/self/stat"), "no /proc start times")
    def test_a_recycled_pid_is_not_a_holder(self):
        path = checkout.lock_path(self.storage, self.repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getppid(), "started": 1, "run_id": "run-old"}, handle)
        checkout.acquire(self.repo, "run-mine", self.storage).release()

    def test_in_one_process_two_runs_exclude_and_one_run_nests(self):
        outer = checkout.acquire(self.repo, "run-1", self.storage)
        inner = checkout.acquire(self.repo, "run-1", self.storage)
        with self.assertRaises(checkout.CheckoutLocked):
            checkout.acquire(self.repo, "run-2", self.storage)
        inner.release()
        self.assertTrue(os.path.exists(outer.path))  # the outer hold still stands
        outer.release()
        checkout.acquire(self.repo, "run-2", self.storage).release()

    def test_the_lock_is_keyed_by_the_real_path(self):
        link = os.path.join(self.scratch, "link")
        try:
            os.symlink(self.repo, link)
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        lease = checkout.acquire(self.repo, "run-1", self.storage)
        self.addCleanup(lease.release)
        with self.assertRaises(checkout.CheckoutLocked):
            checkout.acquire(link, "run-2", self.storage)

    def test_a_step_lease_without_a_run_directory_holds_nothing(self):
        class Bare:
            run_id = "run-1"
        with checkout.StepLease(Bare()) as lease:
            self.assertIsNone(lease.take(self.repo))

    def test_a_step_lease_releases_whatever_it_took(self):
        class Context:
            run_id = "run-1"
            current_step = "develop"
            run_dir = os.path.join(self.storage, "workflows", "run-1")
        with checkout.StepLease(Context()) as lease:
            taken = lease.take(self.repo)
            self.assertEqual(os.path.dirname(os.path.dirname(taken.path)), self.storage)
            self.assertTrue(os.path.exists(taken.path))
        self.assertFalse(os.path.exists(taken.path))


class LockedSteps(Case):
    """Every step that works in the checkout is BLOCKED while another run holds it."""

    def test_verify_is_blocked_by_another_run_and_passes_for_its_own(self):
        import test_verification as tv
        from wgflib.workflow import StepOutcome

        case = tv.VerificationCase("run")
        case.setUp()
        self.addCleanup(case.doCleanups)
        storage = self.mkdir("store")
        context = tv.FakeContext()
        context.run_dir = os.path.join(storage, "workflows", context.run_id)
        other = checkout.acquire(case.repo, "run-other", storage)
        try:
            result = case.step().execute(case.inputs(), context)
        finally:
            other.release()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("run-other", result.message or result.error)
        # The same run holding it (a continued run) is not in the way.
        own = checkout.acquire(case.repo, context.run_id, storage)
        try:
            result = case.step().execute(case.inputs(), context)
        finally:
            own.release()
        self.assertNotEqual(result.outcome, StepOutcome.BLOCKED, result.message)

    def test_sdk_blocks_on_another_run(self):
        from wgf_develop.step import DevelopStep
        from wgf_review.step import ReviewStep
        from wgf_sdk.step import SdkStep
        from wgflib.workflow import StepOutcome
        import test_verification as tv

        storage = self.mkdir("store")
        repo = self.mkdir("games", "demo")
        subprocess.run(["git", "init", "-q", repo], check=True)
        with open(os.path.join(repo, "package.json"), "w") as handle:
            handle.write("{}")
        other = checkout.acquire(repo, "run-other", storage)
        self.addCleanup(other.release)
        # Release: test_release_module (its evidence refusals come before the checkout).
        for cls, output in ((SdkStep, "sdk-report"),):
            with self.subTest(step=cls.__name__):
                step = cls(tv.StepDefinition({
                    "id": cls.type, "type": cls.type, "inputs": [], "outputs": [output],
                    "with": {"repo_dir": repo, "required_gates": []}},
                    retry=None, max_visits=None))
                context = tv.FakeContext()
                context.run_dir = os.path.join(storage, "workflows", "run-mine")
                context.run_id = "run-mine"
                context.process_hooks = lambda: {}
                result = step.execute(tv.FakeInputs({}), context)
                text = json.dumps([result.message, result.error,
                                   getattr(result, "data", None)], default=str)
                self.assertEqual(result.outcome, StepOutcome.BLOCKED, text)
                self.assertIn("run-other", text)
        # develop and review read the checkout from the scaffold-record before anything else.
        for cls in (DevelopStep, ReviewStep):
            self.assertTrue(hasattr(cls, "_execute"), cls)


class AssetsReachTheGame(Case):
    def test_assets_default_into_the_checkout_and_the_brief_lists_their_paths(self):
        import test_assets as ta
        from wgf_assets.step import AssetsStep
        from wgf_develop import brief as briefs

        body = ta.fixture("design-2d.json")
        design = ta.with_provenance(body, "game-design", body["title_id"])
        title = body["title_id"]
        repo = self.mkdir("games", title)
        record = ta.with_provenance({
            "title_id": title,
            "repository": {"owner": "acme", "name": title},
            "template": {"repository": "acme/web-game-template"},
            "game_config": {"path": "game.config.yaml"},
            "outcome": "created"}, "scaffold-record", title)
        context = ta.FakeContext({"placeholders": {"backends": ["procedural"]}},
                                 config={"checkouts": os.path.join(self.scratch, "games")})
        storage = self.mkdir("store")
        context.run_id = "run-1"
        context.run_dir = os.path.join(storage, "workflows", "run-1")
        result = AssetsStep(ta.Definition()).execute(ta.inputs_for(design, record), context)
        self.assertEqual(result.outcome, "SUCCESS", result.error)
        manifest = result.artifacts[0].content
        files = [f["path"] for item in manifest["items"] for f in item.get("files") or []]
        self.assertTrue(files, manifest["items"][:2])
        for path in files:
            self.assertTrue(path.startswith("public/assets/"), path)
            self.assertTrue(os.path.isfile(os.path.join(repo, *path.split("/"))), path)
        self.assertFalse(os.path.exists(os.path.join(paths.ROOT, ".factory", "assets", title)))
        brief = briefs.build_brief(
            title_id=title, engine="pixijs", iteration=1, key="k", baseline=None,
            design=design, assets=manifest, scaffold=record)
        listed = [p for a in brief["assets"] for p in a.get("files") or []]
        self.assertTrue(listed)
        self.assertTrue(set(listed) <= set(files))
        text = briefs.render_markdown(brief)
        for path in listed:
            self.assertIn(f"`{path}`", text)

    def test_another_run_holding_the_checkout_blocks_assets(self):
        import test_assets as ta
        from wgf_assets.step import AssetsStep

        body = ta.fixture("design-2d.json")
        design = ta.with_provenance(body, "game-design", body["title_id"])
        repo = self.mkdir("games", body["title_id"])
        record = ta.with_provenance({
            "title_id": body["title_id"],
            "repository": {"owner": "acme", "name": body["title_id"]},
            "template": {"repository": "acme/web-game-template"},
            "game_config": {"path": "game.config.yaml"},
            "outcome": "created"}, "scaffold-record", body["title_id"])
        context = ta.FakeContext({"placeholders": {"backends": ["procedural"]}},
                                 config={"checkouts": os.path.join(self.scratch, "games")})
        storage = self.mkdir("store")
        context.run_id = "run-1"
        context.run_dir = os.path.join(storage, "workflows", "run-1")
        other = checkout.acquire(repo, "run-other", storage)
        self.addCleanup(other.release)
        result = AssetsStep(ta.Definition()).execute(ta.inputs_for(design, record), context)
        self.assertEqual(result.outcome, "BLOCKED", result.error)
        self.assertIn("run-other", result.message or result.error)
        self.assertEqual(os.listdir(repo), [])

    def test_without_a_scaffold_the_scratch_root_is_under_the_factory_root(self):
        from wgf_assets.step import AssetsStep
        step = AssetsStep.__new__(AssetsStep)
        root, in_checkout = step._asset_root({}, None, "demo", None)
        self.assertEqual(root, os.path.join(paths.ROOT, ".factory", "assets", "demo"))
        self.assertFalse(in_checkout)


class DevelopLiterals(unittest.TestCase):
    """The develop module's template literals are the template contract's (M10)."""

    def test_engines_paths_scripts_and_files_come_from_the_contract(self):
        from wgf_develop import brief, checks, repository, scope

        self.assertIs(repository.ENGINES, contract.ENGINES)
        self.assertEqual(set(brief.ENGINE_DIRS), set(contract.ENGINES))
        for engine, directory in brief.ENGINE_DIRS.items():
            self.assertEqual(directory + "/", contract.rendering_dir(engine))
            self.assertTrue(contract.renderer_package(engine).endswith(
                brief.framework_package(engine).split("/", 1)[1] + "/"))
            self.assertTrue(checks.ENGINE_MODULES[engine].match(brief.framework_package(engine)))
        self.assertIn(checks.ENGINE_SELECTOR, [p for p, _ in contract.SOURCE_PATHS])
        for command, script in checks.TOOLCHAIN.values():
            self.assertEqual(command[0], contract.PACKAGE_MANAGER)
            if script is not None:
                self.assertIn(script, contract.NPM_SCRIPTS)
                self.assertEqual(command[-1], script)
        self.assertEqual(scope.PACKAGE_FILES, (contract.PACKAGE_JSON, contract.PNPM_LOCK))
        self.assertEqual(brief.STRUCTURAL_PATHS, (contract.PACKAGE_JSON, contract.PNPM_LOCK))
        for path in (contract.GAME_CONFIG, contract.PLATFORM_PROFILES_DIR,
                     contract.PLAYWRIGHT_CONFIG, contract.VITEST_WORKSPACE,
                     contract.PACKAGE_JSON, contract.PNPM_LOCK):
            self.assertIn(path, brief.PROTECTED_PATHS)

    def test_the_behaviour_is_unchanged(self):
        from wgf_develop import brief, checks
        self.assertEqual(brief.ENGINE_DIRS, {"pixijs": "src/rendering/pixijs",
                                             "threejs": "src/rendering/threejs"})
        self.assertEqual(checks.ENGINE_SELECTOR, "src/rendering/create-renderer.ts")
        self.assertEqual(checks.TOOLCHAIN["smoke"], (["pnpm", "run", "test:e2e"], "test:e2e"))
        self.assertEqual(checks.TOOLCHAIN["unit"], (["pnpm", "run", "test"], "test"))
        for module in ("pixi.js", "@pixi/sprite", "@wgf/pixi-framework"):
            self.assertTrue(checks.ENGINE_MODULES["pixijs"].match(module), module)
        for module in ("three", "three/addons/x", "@wgf/three-framework"):
            self.assertTrue(checks.ENGINE_MODULES["threejs"].match(module), module)
        self.assertFalse(checks.ENGINE_MODULES["pixijs"].match("@wgf/pixiXframework"))


if __name__ == "__main__":
    unittest.main()
