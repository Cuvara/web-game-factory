"""The installed Claude plugin is the Factory runtime; the working directory is the project.

Claude Code installs a plugin by copying its directory, and nothing outside it, into the
plugin cache, and runs its commands from whatever project the user is in. So:

  * the plugin carries the runtime closure (claude-web-game-plugin/runtime/, built by
    scripts/build-plugin-runtime.py) - core/, the engine, its step modules, the shipped
    config - and nothing a development checkout alone has (tests, goldens, instance data);
  * run from that bundle, the engine reads core/ and the workflow from the bundle, whatever
    the working directory holds, and keeps runs and instance data in the working directory
    (or WGF_PROJECT_DIR) - never in the plugin;
  * run from this repository, nothing changed: the project is the repository.

Every run here is `new-game --mock`, which stops at G4 (exit 3) and touches no network.
"Installing" is what Claude Code does: a copy of the plugin directory alone, somewhere else.

    python -m unittest scripts.tests.test_plugin_runtime
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
PLUGIN = os.path.join(ROOT, "claude-web-game-plugin")
EXIT_WAITING = 3
sys.path.insert(0, SCRIPTS)


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_plugin_runtime_under_test", os.path.join(SCRIPTS, "build-plugin-runtime.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = load_builder()


def environment(**extra):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("WGF_") and k not in ("PYTHONPATH", "PYTHONSTARTUP")}
    env.update(extra)
    return env


def wgf(engine, *argv, cwd, env=None):
    return subprocess.run([sys.executable, engine, *argv], cwd=cwd, env=env or environment(),
                          capture_output=True, text=True, timeout=300)


def where(engine, cwd, env=None):
    result = wgf(engine, "where", "--json", cwd=cwd, env=env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def real(path):
    return os.path.realpath(path)


def inside(path, root):
    return os.path.commonpath([real(path), real(root)]) == real(root)


def tree(root):
    """{relative path: bytes} of every file under root."""
    found = {}
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(directory, name)
            with open(path, "rb") as handle:
                found[os.path.relpath(path, root)] = handle.read()
    return found


def install(source_plugin, destination):
    """What Claude Code does on install: copy the plugin directory, and only it."""
    shutil.copytree(source_plugin, destination,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return os.path.join(destination, "runtime", "scripts", "wgf.py")


class InstalledPluginCase(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-plugin-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.installed = os.path.join(self.base, "installed-plugin")
        self.engine = install(PLUGIN, self.installed)
        self.runtime = os.path.join(self.installed, "runtime")

    def project(self, name):
        path = os.path.join(self.base, name)
        os.makedirs(path)
        return path

    def run_new_game(self, cwd, *extra, env=None):
        result = wgf(self.engine, "new-game", "--mock", "--json", *extra, cwd=cwd, env=env)
        self.assertEqual(result.returncode, EXIT_WAITING, result.stderr[-2000:])
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(events[0]["event"], "WORKFLOW_STARTED")
        return events[0]["run_id"]

    def state(self, store, run_id):
        with open(os.path.join(store, "workflows", run_id, "state.json"), encoding="utf-8") as h:
            return json.load(h)

    def assert_factory_from_plugin(self, resolved):
        self.assertTrue(resolved["installed"])
        self.assertEqual(real(resolved["factory_root"]), real(self.runtime))
        self.assertTrue(inside(resolved["workflow"], self.runtime), resolved["workflow"])
        self.assertTrue(os.path.isfile(resolved["workflow"]))


class ExternalProject(InstalledPluginCase):
    """1. Factory source here, plugin installed elsewhere, cwd a game project."""

    def test_new_game_reads_the_workflow_from_the_plugin_and_keeps_the_run_in_the_project(self):
        target = self.project("source-game")
        resolved = where(self.engine, target)
        self.assert_factory_from_plugin(resolved)
        self.assertEqual(real(resolved["project_root"]), real(target))
        self.assertEqual(real(resolved["store"]), real(os.path.join(target, ".factory")))
        # No instance config in the project: the plugin's shipped default applies.
        self.assertTrue(inside(resolved["config"], self.runtime), resolved["config"])

        before = tree(self.installed)
        run_id = self.run_new_game(target, "--project", "source-game")
        state = self.state(os.path.join(target, ".factory"), run_id)
        self.assertEqual(state["workflow_id"], "new-game")
        self.assertEqual(state["project_id"], "source-game")  # --project: the title id, as ever
        self.assertEqual(state["status"], "WAITING")
        self.assertEqual(state["cursor"], "prototype-review")
        self.assertEqual(tree(self.installed), before, "a run wrote into the installed plugin")

        status = wgf(self.engine, "status", run_id, "--json", cwd=target)
        self.assertEqual(status.returncode, EXIT_WAITING, status.stderr)
        self.assertEqual(json.loads(status.stdout)["run_id"], run_id)

    def test_a_project_workflow_file_is_never_read(self):
        """A project that happens to hold a core/ - broken here - does not change the Factory."""
        target = self.project("has-a-core")
        broken = os.path.join(target, "core", "workflows")
        os.makedirs(broken)
        with open(os.path.join(broken, "new-game.workflow.yaml"), "w") as handle:
            handle.write("this: is [not a workflow\n")
        self.assert_factory_from_plugin(where(self.engine, target))
        self.run_new_game(target)


class FactoryRepositoryAsProject(InstalledPluginCase):
    """2. The same installed plugin, run with the Factory repository as the working directory."""

    def test_the_factory_checkout_is_the_project_and_the_plugin_the_factory(self):
        resolved = where(self.engine, ROOT)
        self.assert_factory_from_plugin(resolved)
        self.assertEqual(real(resolved["project_root"]), real(ROOT))
        # The checkout's own workspace/config/factory.yaml is the instance's configuration.
        self.assertEqual(real(resolved["config"]),
                         real(os.path.join(ROOT, "workspace", "config", "factory.yaml")))

    def test_new_game_runs_with_a_factory_checkout_as_the_project(self):
        # A copy of the checkout's instance layout: running in the real one would leave a run
        # in the developer's .factory/.
        checkout = self.project("web-game-factory")
        shutil.copytree(os.path.join(ROOT, "workspace", "config"),
                        os.path.join(checkout, "workspace", "config"))
        shutil.copytree(os.path.join(ROOT, "core"), os.path.join(checkout, "core"))
        resolved = where(self.engine, checkout)
        self.assert_factory_from_plugin(resolved)
        self.assertTrue(inside(resolved["config"], checkout))
        run_id = self.run_new_game(checkout, "--hold-gates")
        state = self.state(os.path.join(checkout, ".factory"), run_id)
        self.assertEqual(state["cursor"], "strategy-review")  # --hold-gates: stops at G2

    def test_the_source_engine_is_unchanged(self):
        """Run from this repository (no bundle), the project is the repository, whatever
        the working directory - as before the plugin carried a runtime."""
        elsewhere = self.project("anywhere")
        resolved = where(os.path.join(SCRIPTS, "wgf.py"), elsewhere)
        self.assertFalse(resolved["installed"])
        self.assertEqual(real(resolved["factory_root"]), real(ROOT))
        self.assertEqual(real(resolved["project_root"]), real(ROOT))
        self.assertEqual(real(resolved["store"]), real(os.path.join(ROOT, ".factory")))


class ArbitraryProject(InstalledPluginCase):
    """3. Other projects: each its own instance, the Factory always the plugin's."""

    def test_two_projects_do_not_share_runs(self):
        first, second = self.project("game-a"), self.project("game-b")
        run_a = self.run_new_game(first)
        self.assert_factory_from_plugin(where(self.engine, second))
        runs = wgf(self.engine, "runs", "--json", cwd=second)
        self.assertEqual(runs.returncode, 0, runs.stderr)
        self.assertNotIn(run_a, runs.stdout)
        self.assertFalse(os.path.exists(os.path.join(second, ".factory", "workflows", run_a)))

    def test_project_dir_override_and_instance_config(self):
        project, cwd = self.project("game-c"), self.project("somewhere-else")
        config = os.path.join(project, "workspace", "config")
        os.makedirs(config)
        with open(os.path.join(config, "factory.yaml"), "w") as handle:
            handle.write("factory:\n  storage:\n    directory: runs\n")
        env = environment(WGF_PROJECT_DIR=project)
        resolved = where(self.engine, cwd, env=env)
        self.assert_factory_from_plugin(resolved)
        self.assertEqual(real(resolved["project_root"]), real(project))
        self.assertEqual(real(resolved["config"]), real(os.path.join(config, "factory.yaml")))
        run_id = self.run_new_game(cwd, env=env)
        self.assertEqual(self.state(os.path.join(project, "runs"), run_id)["status"], "WAITING")
        self.assertEqual(os.listdir(cwd), [])

    def test_a_subdirectory_of_the_project_is_its_own_project_unless_told(self):
        project = self.project("game-d")
        nested = os.path.join(project, "src")
        os.makedirs(nested)
        self.assertEqual(real(where(self.engine, nested)["project_root"]), real(nested))
        env = environment(WGF_PROJECT_DIR=project)
        self.assertEqual(real(where(self.engine, nested, env=env)["project_root"]),
                         real(project))

    def test_test_core_is_refused_by_an_installed_runtime(self):
        result = wgf(self.engine, "test-core", cwd=self.project("game-e"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("installed runtime does not ship", result.stderr)


class FreshPackage(unittest.TestCase):
    """4. Build the package from a clean copy of the source, install it, delete the source,
    and run it. Proves the plugin needs nothing but itself."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-package-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def clean_copy(self):
        """The files a fresh clone would have: tracked plus not-ignored. Every file on disk
        when this is not a git work tree."""
        checkout = os.path.join(self.base, "checkout")
        # exists, not isdir: in a git worktree .git is a file.
        if shutil.which("git") and os.path.exists(os.path.join(ROOT, ".git")):
            listed = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others",
                                     "--exclude-standard"], capture_output=True, check=True)
            files = [f for f in listed.stdout.decode("utf-8").split("\0") if f
                     and not f.startswith("claude-web-game-plugin/runtime/")]
        else:
            files = [os.path.relpath(os.path.join(d, f), ROOT)
                     for d, dirs, names in os.walk(ROOT) for f in names
                     if ".git" not in d.split(os.sep) and "__pycache__" not in d]
        for relative in files:
            source = os.path.join(ROOT, relative)
            if not os.path.isfile(source):  # deleted in the work tree
                continue
            target = os.path.join(checkout, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
        return checkout

    def test_a_package_built_from_a_clean_copy_runs_without_the_source(self):
        checkout = self.clean_copy()
        self.assertFalse(os.path.exists(os.path.join(checkout, "claude-web-game-plugin",
                                                     "runtime")))
        builder = subprocess.run(
            [sys.executable, os.path.join(checkout, "scripts", "build-plugin-runtime.py")],
            cwd=self.base, env=environment(), capture_output=True, text=True, timeout=300)
        self.assertEqual(builder.returncode, 0, builder.stderr)
        package = os.path.join(self.base, "package")
        shutil.copytree(os.path.join(checkout, "claude-web-game-plugin"), package)

        # The package is what the repository ships: identical to the committed bundle.
        self.assertEqual(BUILDER.check(os.path.join(PLUGIN, "runtime")), [])
        with open(os.path.join(package, "runtime", BUILDER.MANIFEST), "rb") as fresh, \
                open(os.path.join(PLUGIN, "runtime", BUILDER.MANIFEST), "rb") as committed:
            self.assertEqual(fresh.read(), committed.read())

        shutil.rmtree(checkout)  # no source left to fall back on
        installed = os.path.join(self.base, "cache", "web-game-factory", "2.x")
        engine = install(package, installed)
        shutil.rmtree(package)
        target = os.path.join(self.base, "source-game")
        os.makedirs(target)

        resolved = where(engine, target)
        self.assertTrue(resolved["installed"])
        self.assertTrue(inside(resolved["workflow"], installed))
        result = wgf(engine, "new-game", "--mock", "--json", cwd=target)
        self.assertEqual(result.returncode, EXIT_WAITING, result.stderr[-2000:])
        self.assertTrue(os.path.isdir(os.path.join(target, ".factory", "workflows")))

    def test_the_package_carries_the_runtime_closure_and_nothing_else(self):
        files = set(BUILDER.runtime_files(ROOT))
        for required in ("core/workflows/new-game.workflow.yaml", "core/lifecycle/gates.yaml",
                         "core/artifacts/game-design.schema.json", "scripts/wgf.py",
                         "scripts/wgflib/paths.py", "scripts/wgflib/workflow/engine.py",
                         "scripts/wgflib/workflow/fixtures/game-design.json",
                         "scripts/wgf_discovery/archetypes.yaml",
                         # The 2D asset pipeline: its module, CLI, schema and craft playbook.
                         "scripts/wgf_assets/atlas.py", "scripts/wgf_assets/runtime.py",
                         "scripts/wgf-assets.py",
                         # The 3D asset pipeline: Blender backend and its build script, GLB
                         # validation, model specs, CLI, schema and craft playbook.
                         "scripts/wgf_assets/blender.py",
                         "scripts/wgf_assets/blender_scripts/build_model.py",
                         "scripts/wgf_assets/gltf.py", "scripts/wgf_assets/modelspec.py",
                         "scripts/wgf-model.py",
                         "core/artifacts/shared/model-spec.schema.json",
                         "core/craft/3d-assets-and-animation.md",
                         "core/artifacts/shared/runtime-assets.schema.json",
                         "core/craft/2d-assets.md",
                         "workspace/config/factory.yaml", "workspace/config/template.lock.json",
                         "docs/workflow-engine.md", "VERSION"):
            self.assertIn(required, files)
        for path in files:
            with self.subTest(path=path):
                self.assertFalse(path.startswith(("scripts/tests/", "scripts/golden/",
                                                  "scripts/mv4/", "docs/evidence/",
                                                  "workspace/titles/", "workspace/claims/",
                                                  "workspace/opportunities/",
                                                  "workspace/research/", ".github/")))
                self.assertNotIn("__pycache__", path)
        for dev_only in ("scripts/check-integrity.py", "scripts/gen-adapters.sh",
                         "scripts/build-plugin-runtime.py", "scripts/wgf-org-setup.sh"):
            self.assertNotIn(dev_only, files)
        # Every step module the shipped config installs is in the package.
        from wgflib.yamllite import load_file
        modules = load_file(os.path.join(ROOT, "workspace", "config", "factory.yaml"))[
            "factory"]["steps"]["modules"]
        for module in modules:
            self.assertIn(f"scripts/{module}/__init__.py", files)


class SourceModePaths(unittest.TestCase):
    """paths.PROJECT is paths.ROOT in a development checkout - every existing reader of
    workspace/ and the store is unchanged - and WGF_PROJECT_DIR alone moves it."""

    def probe(self, env, cwd):
        code = ("import json, sys; sys.path.insert(0, sys.argv[1]); from wgflib import paths; "
                "print(json.dumps([paths.ROOT, paths.PROJECT, paths.INSTALLED, "
                "paths.config_file('factory.yaml'), paths.both_roots('workspace/config')]))")
        result = subprocess.run([sys.executable, "-c", code, SCRIPTS], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_source_checkout(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            root, project, installed, config, guarded = self.probe(environment(), elsewhere)
        self.assertEqual(project, root)
        self.assertFalse(installed)
        self.assertEqual(config, os.path.join(root, "workspace", "config", "factory.yaml"))
        self.assertEqual(guarded, [os.path.join(root, "workspace", "config")])

    def test_project_dir_override(self):
        with tempfile.TemporaryDirectory() as project:
            root, found, _installed, config, guarded = self.probe(
                environment(WGF_PROJECT_DIR=project), ROOT)
            self.assertEqual(real(found), real(project))
            # No factory.yaml of its own: the Factory's shipped one.
            self.assertEqual(config, os.path.join(root, "workspace", "config", "factory.yaml"))
            self.assertEqual(guarded, [os.path.join(root, "workspace", "config"),
                                       os.path.join(found, "workspace", "config")])


if __name__ == "__main__":
    unittest.main()
