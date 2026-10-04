"""The autonomous profile, and the config layering that makes a profile a small file.

A project's own workspace/config/factory.yaml is layered over the Factory's shipped one key
by key (wgflib/workflow/config.py load_config) - in 2.4.1 it replaced it, so a project
that set only `auto_approve` silently lost the step modules. The autonomous profile
(workspace/config/profiles/autonomous.yaml) is such an overlay: the shipped, verified agent
argvs, G2/G3 auto-approval, a local init and a spend budget. The shipped default stays
supervised (test_core_agents.ShippedConfig).

The dry runs use an installed copy of the plugin and `--mock`: no agent session, no network,
no repository. The real-step run stops at the end of `plan`, before init.

    python -m unittest scripts.tests.test_autonomous_profile
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

from wgflib import paths  # noqa: E402
from wgflib.workflow import config as config_module  # noqa: E402
from wgflib.workflow.config import load_config  # noqa: E402

PROFILE = os.path.join(ROOT, "workspace", "config", "profiles", "autonomous.yaml")
SHIPPED = os.path.join(ROOT, "workspace", "config", "factory.yaml")
EXIT_OK, EXIT_WAITING = 0, 3


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


class Layering(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-layers-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.shipped = os.path.join(self.base, "factory", "factory.yaml")
        self.project_config = os.path.join(self.base, "project", "workspace", "config")
        write(self.shipped, "factory:\n  steps:\n    modules: [a, b]\n"
                            "  checkpoints:\n    auto_approve: []\n"
                            "  init:\n    source: github\n    owner: Someone\n")
        for patcher in (mock.patch.object(config_module, "SHIPPED_CONFIG_PATH", self.shipped),
                        mock.patch.object(paths, "CONFIG", self.project_config)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def own(self, text):
        path = os.path.join(self.project_config, "factory.yaml")
        write(path, text)
        return path

    def test_no_project_file_is_the_shipped_file(self):
        config = load_config()
        self.assertEqual(config.layers, [self.shipped])
        self.assertEqual(config.step_modules, ["a", "b"])

    def test_a_project_file_changes_only_what_it_sets(self):
        own = self.own("factory:\n  checkpoints:\n    auto_approve: [G2]\n"
                       "  init:\n    source: local\n")
        config = load_config()
        self.assertEqual(config.layers, [self.shipped, own])
        self.assertEqual(config.source, own)
        self.assertEqual(config.step_modules, ["a", "b"])       # kept from the shipped file
        self.assertEqual(config.auto_approve, ["G2"])           # the project's
        self.assertEqual(config.section("init"), {"source": "local", "owner": "Someone"})

    def test_a_list_replaces_it_is_never_appended(self):
        self.own("factory:\n  steps:\n    modules: [c]\n")
        self.assertEqual(load_config().step_modules, ["c"])

    def test_the_same_file_is_one_layer(self):
        """A development checkout: the project's config is the shipped file."""
        with mock.patch.object(paths, "CONFIG", os.path.dirname(self.shipped)):
            self.assertEqual(load_config().layers, [self.shipped])

    def test_an_explicit_config_is_that_file_alone(self):
        self.own("factory:\n  checkpoints:\n    auto_approve: [G2]\n")
        other = os.path.join(self.base, "other.yaml")
        write(other, "factory:\n  checkpoints:\n    auto_approve: [G3]\n")
        config = load_config(other)
        self.assertEqual(config.layers, [other])
        self.assertEqual(config.step_modules, [])  # not merged over anything but DEFAULTS
        self.assertEqual(config.auto_approve, ["G3"])


class TheProfile(unittest.TestCase):
    """The profile layered over the real shipped config, as a project would have it."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-profile-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        project_config = os.path.join(self.base, "workspace", "config")
        os.makedirs(project_config)
        shutil.copyfile(PROFILE, os.path.join(project_config, "factory.yaml"))
        patcher = mock.patch.object(paths, "CONFIG", project_config)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = load_config()

    def test_it_is_an_overlay_of_the_shipped_config(self):
        self.assertEqual(len(self.config.layers), 2)
        shipped = load_config(SHIPPED)
        self.assertEqual(self.config.step_modules, shipped.step_modules)
        self.assertEqual(self.config.section("review")["guarded_paths"],
                         shipped.section("review")["guarded_paths"])

    def test_developer_reviewer_and_gates(self):
        from wgf_develop.settings import Settings as DevelopSettings
        from wgf_review.settings import Settings as ReviewSettings
        from wgflib.workflow import checkpoint
        from wgflib.workflow.api import timeout_windows

        data = self.config.data
        self.assertEqual(DevelopSettings.resolve(data).developer["kind"], "command")
        review = ReviewSettings.resolve(data)
        self.assertEqual((review.kind, review.verdict_from), ("command", "stdout"))
        self.assertEqual(self.config.auto_approve, ["G2", "G3"])
        self.assertFalse(set(self.config.auto_approve) & checkpoint.irreversible_gates())
        self.assertEqual(timeout_windows(self.config), {})
        self.assertEqual(self.config.section("init")["source"], "local")
        self.assertEqual(self.config.section("release").get("allow_unreviewed"), False)

    def test_spend_is_bounded(self):
        snapshot = self.config.develop_budget
        self.assertIsNotNone(snapshot)
        self.assertEqual(json.dumps(snapshot, sort_keys=True).count("12"), 1)

    def test_the_agent_argvs_are_the_shipped_verified_examples(self):
        """No second, drifting copy: the profile's argvs are the commented examples in the
        shipped factory.yaml that docs/claude-capabilities.md verified."""
        from golden.live import shipped_agent_examples

        developer, reviewer = shipped_agent_examples(SHIPPED)
        self.assertEqual(self.config.section("develop")["developer"]["argv"], developer["argv"])
        self.assertEqual(self.config.section("review")["reviewer"]["argv"], reviewer["argv"])
        for key in ("timeout_seconds", "idle_timeout_seconds"):
            self.assertEqual(self.config.section("develop")["developer"].get(key),
                             developer.get(key))
            self.assertEqual(self.config.section("review")["reviewer"].get(key),
                             reviewer.get(key))


class TheDesignAgent(unittest.TestCase):
    """The profile's design author is the shipped commented `design.agent` example, verbatim:
    a brief no design archetype carries can only be designed by an agent author."""

    @staticmethod
    def commented_design_agent():
        from wgflib.yamllite import load
        with open(SHIPPED, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        start = lines.index("    # agent:", lines.index("  design:"))
        block = []
        for line in lines[start:]:
            if not line.startswith("    # "):
                break
            block.append(line[len("    # "):])
        return load("\n".join(block))["agent"]

    def test_the_profile_uses_the_shipped_design_agent(self):
        base = tempfile.mkdtemp(prefix="wgf-profile-design-")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        project_config = os.path.join(base, "workspace", "config")
        os.makedirs(project_config)
        shutil.copyfile(PROFILE, os.path.join(project_config, "factory.yaml"))
        with mock.patch.object(paths, "CONFIG", project_config):
            design = load_config().section("design")
        self.assertEqual(design["author"], "agent")
        self.assertEqual(design["agent"], self.commented_design_agent())
        self.assertEqual(load_config(SHIPPED).section("design")["author"], "archetype")

    def test_the_agent_is_told_what_the_module_checks(self):
        from wgf_design import agent
        self.assertIn("concept", agent.PROMPT_CONCEPT)
        self.assertIn("no mechanic the strategy's concept, content_model or MVP does not state",
                      agent.PROMPT_CONCEPT)


def commented_example(section, key):
    """The shipped factory.yaml's commented `    # <key>:` block under `  <section>:`,
    uncommented: the verified example docs/claude-capabilities.md records."""
    from wgflib.yamllite import load
    with open(SHIPPED, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    start = lines.index(f"    # {key}:", lines.index(f"  {section}:"))
    block = [f"{key}:"]
    for line in lines[start + 1:]:
        if not line.startswith("    #   "):
            break
        block.append(line[len("    # "):])
    return load("\n".join(block))[key]


class TheWorkflow5Agents(unittest.TestCase):
    """Workflow 5 refuses placeholder art and blocks without a visual-QA judge, so the
    profile configures the 2D asset author, the 3D model author and the judge - each the
    shipped commented example, verbatim. The model author and the judge are read-only (the
    host has only Read); the 2D set author writes only under the Factory's {out} and runs
    only the Factory's {preview}."""

    def setUp(self):
        base = tempfile.mkdtemp(prefix="wgf-profile-w5-")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        project_config = os.path.join(base, "workspace", "config")
        os.makedirs(project_config)
        shutil.copyfile(PROFILE, os.path.join(project_config, "factory.yaml"))
        patcher = mock.patch.object(paths, "CONFIG", project_config)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = load_config()

    def agents(self):
        assets, visualqa = self.config.section("assets"), self.config.section("visualqa")
        return {("assets", "author"): assets["author"],
                ("assets", "model_author"): assets["model_author"],
                ("visualqa", "judge"): visualqa["judge"]}

    def test_each_is_the_shipped_verified_example(self):
        for (section, key), agent in self.agents().items():
            with self.subTest(agent=key):
                self.assertEqual(agent, commented_example(section, key))
        shipped = load_config(SHIPPED)
        self.assertEqual(shipped.section("assets")["author"]["kind"], "none")
        self.assertEqual(shipped.section("assets")["model_author"]["kind"], "none")
        self.assertEqual(shipped.section("visualqa")["judge"]["kind"], "none")

    def test_each_is_read_only_or_write_scoped_and_bounded(self):
        for (_, key), agent in self.agents().items():
            with self.subTest(agent=key):
                argv = agent["argv"]
                self.assertIn("--safe-mode", argv)
                self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
                self.assertIsNone(agent["idle_timeout_seconds"])  # text prints at exit
                self.assertGreater(agent["timeout_seconds"], 0)
                if key == "author":
                    # One session for the whole set: writes scoped to {out}, the shell to
                    # exactly {preview}; nothing else is allowed, nothing is prompted.
                    allowed = argv[argv.index("--allowedTools") + 1:
                                   argv.index("--disallowedTools")]
                    self.assertEqual(allowed, ["Read", "Edit({out_rule}/**)", "Bash({preview})"])
                    self.assertEqual(agent["mode"], "set")
                    self.assertLessEqual(float(argv[argv.index("--max-budget-usd") + 1]), 8)
                    continue
                if key == "model_author":
                    # The 3D set author writes its spec files, and only under its session
                    # directory: an Edit rule governs every file-editing tool.
                    self.assertEqual(argv[argv.index("--allowedTools") + 1],
                                     "Read,Edit({dir_rule}/**)")
                    denied = argv[argv.index("--disallowedTools") + 1].split(",")
                    self.assertIn("Bash", denied)
                    self.assertLessEqual(float(argv[argv.index("--max-budget-usd") + 1]), 3)
                    continue
                self.assertEqual(argv[argv.index("--allowedTools") + 1], "Read")
                self.assertEqual(argv[argv.index("--tools") + 1], "Read")
                self.assertLessEqual(float(argv[argv.index("--max-budget-usd") + 1]), 2)

    def test_the_modules_accept_them(self):
        from wgf_assets.author import build_author
        from wgf_visualqa.settings import Settings as VisualQASettings

        author = build_author(self.agents()[("assets", "author")], self.config.data)
        self.assertEqual((author.kind, author.mode, author.label, author.repair_rounds),
                         ("command", "set", "author:set", 1))
        from wgf_assets.model_author import MODES
        model = self.agents()[("assets", "model_author")]
        self.assertEqual((model["mode"], model["spec_from"]), ("set", "file"))
        self.assertIn(model["mode"], MODES)
        judge = VisualQASettings.resolve(self.config.data)
        self.assertEqual((judge.kind, judge.verdict_from), ("command", "stdout"))


def install(destination):
    shutil.copytree(os.path.join(ROOT, "claude-web-game-plugin"), destination,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return os.path.join(destination, "runtime", "scripts", "wgf.py")


def environment(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("WGF_")}
    env.update(extra)
    return env


class DryRunFromTheInstalledPlugin(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="wgf-autonomous-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.engine = install(os.path.join(self.base, "installed-plugin"))

    def project(self, name, profile=True):
        path = os.path.join(self.base, name)
        os.makedirs(path)
        if profile:
            where = self.wgf(path, "where", "--json")
            self.assertEqual(where.returncode, 0, where.stderr)
            source = json.loads(where.stdout)["profiles"]["autonomous"]
            self.assertTrue(source.startswith(os.path.join(self.base, "installed-plugin")))
            os.makedirs(os.path.join(path, "workspace", "config"))
            shutil.copyfile(source, os.path.join(path, "workspace", "config", "factory.yaml"))
        return path

    def wgf(self, cwd, *argv):
        return subprocess.run([sys.executable, self.engine, *argv], cwd=cwd,
                              env=environment(), capture_output=True, text=True, timeout=600)

    def state(self, project, run_id):
        with open(os.path.join(project, ".factory", "workflows", run_id, "state.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def test_where_reports_the_autonomy_the_profile_sets(self):
        autonomy = json.loads(self.wgf(self.project("with-profile"), "where", "--json")
                              .stdout)["autonomy"]
        self.assertEqual((autonomy["developer"], autonomy["reviewer"], autonomy["init_source"]),
                         ("command", "command", "local"))
        self.assertEqual(autonomy["auto_approve"], ["G2", "G3"])
        self.assertEqual(autonomy["develop_budget"]["max_sessions"], 12)
        self.assertEqual((autonomy["asset_author"], autonomy["model_author"],
                          autonomy["visualqa_judge"]), ("command", "command", "command"))
        default = json.loads(self.wgf(self.project("without", profile=False), "where", "--json")
                             .stdout)["autonomy"]
        self.assertEqual((default["developer"], default["reviewer"], default["auto_approve"],
                          default["init_source"]), ("handoff", "none", [], "github"))
        self.assertEqual((default["asset_author"], default["model_author"],
                          default["visualqa_judge"]), ("none", "none", "none"))

    def test_mock_hold_gates_still_stops_at_every_gate_without_the_profile(self):
        project = self.project("supervised", profile=False)
        result = self.wgf(project, "new-game", "--mock", "--hold-gates", "--json")
        self.assertEqual(result.returncode, EXIT_WAITING, result.stderr[-1500:])
        run_id = json.loads(result.stdout.splitlines()[0])["run_id"]
        self.assertEqual(self.state(project, run_id)["cursor"], "strategy-review")  # G2

    def test_with_the_profile_only_g4_waits_for_a_person(self):
        project = self.project("autonomous")
        result = self.wgf(project, "new-game", "--mock", "--hold-gates", "--json")
        self.assertEqual(result.returncode, EXIT_WAITING, result.stderr[-1500:])
        run_id = json.loads(result.stdout.splitlines()[0])["run_id"]
        state = self.state(project, run_id)
        self.assertEqual((state["status"], state["cursor"]), ("WAITING", "prototype-review"))
        self.assertEqual(state["params"]["auto_approve"], ["G2", "G3"])
        # G4 is refused automation: a decision attempted by the engine alone never happens.
        self.assertNotIn("G4", state["params"]["auto_approve"])

    def test_real_research_and_plan_run_unattended_up_to_init(self):
        """The real discovery, strategy, design and tech-plan modules, with the profile and
        the Factory's own evidence snapshots copied in as the project's evidence: no step
        waits for a person before init. Nothing past plan runs. The design author is pinned
        to the built-in one on top of the profile - the way a project overrides one key - so
        the test starts no agent session; the profile's agent author is held by
        TheDesignAgent. The built-in author writes MVP-sized content, so the run is at tier
        mvp: at release the design is held to the quality benchmark (content.tier_*)."""
        project = self.project("real-plan")
        with open(os.path.join(project, "workspace", "config", "factory.yaml"), "a",
                  encoding="utf-8") as handle:
            handle.write("\n  design:\n    author: archetype\n"
                         "  strategy:\n    quality_tier: mvp\n")
        shutil.copytree(os.path.join(ROOT, "workspace", "research", "snapshots"),
                        os.path.join(project, "workspace", "research", "snapshots"))
        research = self.wgf(project, "research", "--json")
        self.assertEqual(research.returncode, EXIT_OK, research.stderr[-1500:])
        run_id = json.loads(research.stdout.splitlines()[0])["run_id"]
        plan = self.wgf(project, "plan", "--run", run_id, "--json")
        self.assertEqual(plan.returncode, EXIT_OK, plan.stderr[-1500:])
        steps = self.state(project, run_id)["steps"]
        for step in ("research", "strategy", "strategy-review", "design", "tech-plan",
                     "tech-plan-review"):
            self.assertEqual(steps[step]["status"], "SUCCESS", step)
        self.assertNotIn("init", {k for k, v in steps.items() if v.get("status") == "SUCCESS"})

    def test_research_without_evidence_waits_for_input_even_with_the_profile(self):
        """Autonomy does not waive the evidence rule."""
        result = self.wgf(self.project("no-evidence"), "research", "--json")
        self.assertEqual(result.returncode, EXIT_WAITING, result.stderr[-1500:])
        self.assertIn("no external evidence", result.stdout)


if __name__ == "__main__":
    unittest.main()
