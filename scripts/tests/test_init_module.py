"""The init module (scripts/wgf_init): game-design -> repository from the template -> local
project -> scaffold-record.

GitHub is faked behind the module's own `GitHub` and `Git` interfaces; nothing here touches
the network, creates a repository or runs `gh`. The fake's clone copies a template tree
built from TEMPLATE_INFRASTRUCTURE, and `RealTemplate` checks that list against the actual
web-game-template checkout when one is beside this repository.

Run from the repository root:

    python -m unittest discover scripts/tests

Set WGF_AJV=1 to also validate an emitted scaffold-record with ajv (needs npx).
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import pinned_template  # noqa: E402

import wgf_init  # noqa: E402
from test_workflow_contracts import tree_digest  # noqa: E402
from wgf_init import (  # noqa: E402
    TEMPLATE_INFRASTRUCTURE,
    DesignError,
    GhCli,
    Git,
    GitHub,
    InitSettings,
    InitStep,
    ProjectMetadata,
    Repository,
    SettingsError,
    ToolError,
    missing_infrastructure,
)
from wgf_init.tooling import parse_remote  # noqa: E402
from wgflib import paths  # noqa: E402
from wgflib.hashing import content_hash  # noqa: E402
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep  # noqa: E402
from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import FactoryConfig  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.definition import load_definition  # noqa: E402
from wgflib.workflow.model import ArtifactRef, RunStatus, StepOutcome  # noqa: E402
from wgflib.workflow.step import StepInputs  # noqa: E402

DESIGN_PATH = os.path.join(paths.TITLES, "neon-drift", "game-design.json")
TEMPLATE = "acme/web-game-template"
OWNER = "acme"
REPO = "acme/neon-drift"
NOW = "2026-09-23T10:00:00Z"

GAME_CONFIG = textwrap.dedent("""\
    # Written by the Factory at scaffolding from tech_plan.repo_params.game_config.
    game:
      id: example-game
      name: Example Game
      version: 0.1.0
    engine:
      type: pixijs
    platforms:
      - { id: generic-web, profile: generic-web@1.0.0, role: required }
    monetization:
      ad_kinds: []
      iap: false
    build:
      command: pnpm build
      output: dist
    """)


def load_design():
    with open(DESIGN_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def build_template_tree(root):
    """A stand-in for web-game-template: exactly the infrastructure init expects."""
    for path, _purpose in TEMPLATE_INFRASTRUCTURE:
        full = os.path.join(root, *path.rstrip("/").split("/"))
        if path.endswith("/"):
            os.makedirs(full, exist_ok=True)
            with open(os.path.join(full, ".gitkeep"), "w"):
                pass
        else:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as handle:
                handle.write(GAME_CONFIG if path == "game.config.yaml" else "{}\n")
    return root


# -- fakes ---------------------------------------------------------------------------------


class FakeGit(Git):
    def __init__(self):
        self.origins = {}
        self.pulls = []
        self.template_tree = None

    def origin(self, directory):
        return self.origins.get(os.path.normpath(directory))

    def has_commits(self, directory):
        return os.path.exists(os.path.join(directory, "game.config.yaml"))

    def pull(self, directory, branch):
        self.pulls.append((directory, branch))
        shutil.copytree(self.template_tree, directory, dirs_exist_ok=True)


class FakeGitHub(GitHub):
    def __init__(self, template_tree, git):
        self.template_tree = template_tree
        self.git = git
        git.template_tree = template_tree
        self.repos = {}
        self.calls = []
        self.errors = {}          # method -> ToolError raised once
        self.unpopulated_checks = 0  # has_file answers False this many times first

    def _call(self, name, *args):
        self.calls.append((name,) + args)
        error = self.errors.pop(name, None)
        if error:
            raise error

    def calls_to(self, name):
        return [c for c in self.calls if c[0] == name]

    def add(self, full_name, description="", template=TEMPLATE):
        owner, name = full_name.split("/")
        self.repos[full_name] = Repository(owner, name, url=f"https://github.com/{full_name}",
                                           description=description, visibility="private",
                                           default_branch="main", template=template)

    def view(self, full_name):
        self._call("view", full_name)
        return copy.copy(self.repos.get(full_name))

    def head_sha(self, full_name):
        self._call("head_sha", full_name)
        return "d4f6569bd21284bdf1d5708d42a4a0da8557916c"

    def create_from_template(self, full_name, template, visibility, description):
        self._call("create", full_name, template, visibility, description)
        self.add(full_name, description, template)
        self.repos[full_name].visibility = visibility
        return copy.copy(self.repos[full_name])

    def has_file(self, full_name, path):
        self._call("has_file", full_name, path)
        if self.unpopulated_checks:
            self.unpopulated_checks -= 1
            return False
        return full_name in self.repos

    def clone(self, full_name, destination):
        self._call("clone", full_name, destination)
        shutil.copytree(self.template_tree, destination, dirs_exist_ok=True)
        self.git.origins[os.path.normpath(destination)] = full_name


class Logger:
    def __init__(self):
        self.lines = []

    def _log(self, level, message, **fields):
        self.lines.append((level, message, fields))

    def debug(self, message, **fields):
        self._log("debug", message, **fields)

    info = warning = error = debug


class Context:
    def __init__(self, config, run_id="run-1", project_id="neon-drift", execution=1,
                 previous_outputs=None):
        self.run_id = run_id
        self.project_id = project_id
        self.config = config
        self.execution = execution
        self.previous_outputs = previous_outputs or []
        self.logger = Logger()


def inputs_for(design):
    if design is None:
        return StepInputs({}, lambda ref: None, ["game-design"])
    ref = ArtifactRef(id="game-design", type="game-design", version=1,
                      location="artifacts/game-design/v1.json", checksum="sha256:x",
                      content_hash=design["provenance"]["content_hash"])
    return StepInputs({"game-design": ref}, lambda _ref: design, [])


class InitCase(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="wgf-init-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.projects = os.path.join(self.scratch, "games")
        self.template_tree = build_template_tree(os.path.join(self.scratch, "template"))
        self.git = FakeGit()
        self.github = FakeGitHub(self.template_tree, self.git)
        self.settings = {"owner": OWNER, "template": TEMPLATE, "projects_dir": self.projects,
                         "populate_timeout_seconds": 4}
        self.definition = load_definition("new-game").step("init")
        self.design = load_design()

    @property
    def config(self):
        return {"init": dict(self.settings)}

    def step(self):
        return InitStep(self.definition, github=self.github, git=self.git,
                        clock=lambda: NOW, sleep=lambda _s: None)

    def execute(self, context=None, design="default"):
        design = self.design if design == "default" else design
        return self.step().execute(inputs_for(design), context or Context(self.config))

    @property
    def local(self):
        return os.path.join(self.projects, "neon-drift")


# -- unit ----------------------------------------------------------------------------------


class ProjectMetadataTest(unittest.TestCase):
    def test_metadata_from_the_worked_example(self):
        project = ProjectMetadata.from_design(load_design(), project_id="neon-drift")
        self.assertEqual(project.repo_name, "neon-drift")
        self.assertEqual(project.design_platforms, ["crazygames", "yandex"])
        self.assertTrue(project.summary.endswith("."))

    def test_description_keeps_the_marker_under_the_github_limit(self):
        design = load_design()
        design["fantasy"] = "x" * 1000
        text = ProjectMetadata.from_design(design).description("wgf-init:run:init")
        self.assertLessEqual(len(text), 350)
        self.assertTrue(text.endswith("[wgf-init:run:init]"))

    def test_designs_that_cannot_be_scaffolded(self):
        cases = {
            "title_id": lambda d: d.update(title_id="Neon Drift"),
            "consistency": lambda d: d["consistency"].update(status="fail"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                design = load_design()
                mutate(design)
                with self.assertRaises(DesignError):
                    ProjectMetadata.from_design(design)
        with self.assertRaises(DesignError):
            ProjectMetadata.from_design(load_design(), project_id="another-title")


class SettingsTest(unittest.TestCase):
    def test_defaults_and_refusals(self):
        settings = InitSettings.from_config({"init": {"owner": "acme", "template": TEMPLATE}})
        self.assertEqual((settings.visibility, settings.adopt_existing),
                         ("private", False))
        self.assertEqual(settings.local_path("x"),
                         os.path.normpath(os.path.join(paths.ROOT, "..", "x")))
        for bad in ({}, {"owner": "acme"}, {"owner": "acme", "template": "no-slash"},
                    {"owner": "acme", "template": TEMPLATE, "visibility": "secret"},
                    {"owner": "acme", "template": TEMPLATE, "adopt_existing": "yes"}):
            with self.subTest(bad):
                with self.assertRaises(SettingsError):
                    InitSettings.from_config({"init": bad})


class InitStepTest(InitCase):
    def test_creates_the_repository_and_the_local_project(self):
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)

        create = self.github.calls_to("create")
        self.assertEqual(len(create), 1)
        _, full_name, template, visibility, description = create[0]
        self.assertEqual((full_name, template, visibility), (REPO, TEMPLATE, "private"))
        self.assertIn("[wgf-init:run-1:init]", description)
        self.assertEqual(self.github.calls_to("clone"), [("clone", REPO, self.local)])

        record = result.artifacts[0].content
        self.assertEqual(result.artifacts[0].type, "scaffold-record")
        self.assertEqual(record["outcome"], "created")
        self.assertEqual(record["repository"],
                         {"owner": "acme", "name": "neon-drift", "default_branch": "main",
                          "url": "https://github.com/acme/neon-drift",
                          "visibility": "private"})
        self.assertEqual(record["template"]["repository"], TEMPLATE)
        self.assertEqual(len(record["template"]["commit_sha"]), 40)
        self.assertEqual(record["idempotency_key"], "wgf-init:run-1:init")
        self.assertEqual(result.artifacts[0].metadata["local_path"], self.local)

    def test_the_scaffold_record_meets_its_contract(self):
        record = self.execute().artifacts[0].content
        self.assertEqual(ArtifactContracts()("scaffold-record", record), [])
        provenance = record["provenance"]
        self.assertEqual(provenance["artifact_id"], "wgf:scaffold-record:neon-drift:20260923-01")
        self.assertEqual(provenance["produced_by"], {"role": "release", "actor": "automation"})
        self.assertEqual(provenance["inputs"], [{
            "artifact_id": self.design["provenance"]["artifact_id"],
            "artifact_type": "game-design",
            "content_hash": self.design["provenance"]["content_hash"],
        }])
        self.assertEqual(provenance["content_hash"], content_hash(record))
        game_config = record["game_config"]
        self.assertEqual(game_config["path"], "game.config.yaml")
        self.assertEqual(game_config["platforms"],
                         [{"id": "generic-web", "profile": "generic-web@1.0.0",
                           "role": "required"}])
        self.assertRegex(game_config["checksum"], r"^sha256:[0-9a-f]{64}$")

    def test_the_generated_project_has_the_template_infrastructure(self):
        self.execute()
        self.assertEqual(missing_infrastructure(self.local), [])
        for path in ("packages/platform-sdk", ".github/workflows/ci.yml",
                     ".github/workflows/publish.yml", "tests/unit", "config/platforms"):
            self.assertTrue(os.path.exists(os.path.join(self.local, path)), path)

    def test_init_writes_nothing_into_the_generated_project(self):
        self.execute()
        self.assertEqual(tree_digest(self.local), tree_digest(self.template_tree))

    def test_missing_game_design_waits(self):
        result = self.execute(design=None)
        self.assertEqual(result.outcome, StepOutcome.WAITING_FOR_INPUT)
        self.assertEqual(self.github.calls, [])

    def test_unconfigured_installation_blocks_before_touching_github(self):
        result = self.step().execute(inputs_for(self.design), Context({}))
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("factory.init.owner", result.error or result.message)
        self.assertEqual(self.github.calls, [])

    def test_a_design_that_cannot_be_scaffolded_fails_without_retry(self):
        self.design["consistency"]["status"] = "fail"
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertEqual(self.github.calls, [])


# -- idempotency ---------------------------------------------------------------------------


class Idempotency(InitCase):
    def test_same_key_twice_creates_one_repository(self):
        first = self.execute()
        second = self.execute()
        self.assertEqual(len(self.github.calls_to("create")), 1)
        self.assertEqual(len(self.github.calls_to("clone")), 1)
        self.assertEqual(first.artifacts[0].content["outcome"], "created")
        self.assertEqual(second.artifacts[0].content["outcome"], "reused")
        self.assertNotIn("commit_sha", second.artifacts[0].content["template"])

    def test_a_crash_after_create_is_recovered_by_the_marker(self):
        # gh created the repository, then the process died before anything was persisted:
        # the retry has no previous_outputs, only the marker on the repository itself.
        self.github.errors["clone"] = ToolError("connection reset")
        failed = self.execute()
        self.assertEqual((failed.outcome, failed.retryable), (StepOutcome.FAILED, True))
        retried = self.execute()
        self.assertEqual(retried.outcome, StepOutcome.SUCCESS, retried.error)
        self.assertEqual(len(self.github.calls_to("create")), 1)
        self.assertEqual(retried.artifacts[0].content["outcome"], "reused")

    def test_previous_outputs_also_identify_the_repository(self):
        self.github.add(REPO, description="edited by a person since")
        ref = ArtifactRef(id="scaffold-record", type="scaffold-record", version=1,
                          location="x", checksum="x", metadata={"repository": REPO})
        result = self.execute(Context(self.config, previous_outputs=[ref]))
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(self.github.calls_to("create"), [])

    def test_an_empty_clone_from_an_early_attempt_is_filled_not_replaced(self):
        os.makedirs(os.path.join(self.local, ".git"))
        self.github.add(REPO, description="[wgf-init:run-1:init]")
        self.git.origins[self.local] = REPO
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(self.git.pulls, [(self.local, "main")])
        self.assertEqual(self.github.calls_to("clone"), [])


# -- refusals and failure paths ------------------------------------------------------------


class Refusals(InitCase):
    def test_a_repository_this_run_did_not_create_is_not_taken_over(self):
        self.github.add(REPO, description="someone else's game")
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("adopt_existing", result.error or result.message)
        self.assertEqual(self.github.calls_to("create"), [])
        self.assertEqual(self.github.calls_to("clone"), [])

    def test_adopting_is_possible_when_authorized(self):
        self.github.add(REPO, description="made by hand from the template")
        self.settings["adopt_existing"] = True
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(result.artifacts[0].content["outcome"], "reused")

    def test_a_repository_not_from_the_template_is_refused_even_when_authorized(self):
        self.github.add(REPO, description="[wgf-init:run-1:init]", template=None)
        self.settings["adopt_existing"] = True
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("originate from the template", result.error)

    def test_an_existing_directory_is_never_overwritten(self):
        os.makedirs(self.local)
        with open(os.path.join(self.local, "precious.txt"), "w") as handle:
            handle.write("do not touch")
        before = tree_digest(self.local)
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertIn("never overwrites", result.error or result.message)
        self.assertEqual(tree_digest(self.local), before)
        self.assertEqual(self.github.calls_to("clone"), [])

    def test_a_clone_of_another_repository_is_not_reused(self):
        os.makedirs(os.path.join(self.local, ".git"))
        self.git.origins[self.local] = "acme/other-game"
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)

    def test_missing_template_infrastructure_fails_without_retry(self):
        os.remove(os.path.join(self.template_tree, ".github", "workflows", "ci.yml"))
        shutil.rmtree(os.path.join(self.template_tree, "packages", "platform-sdk"))
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("packages/platform-sdk/", result.error)
        self.assertIn(".github/workflows/ci.yml", result.error)

    def test_an_unpinned_platform_fails(self):
        with open(os.path.join(self.template_tree, "game.config.yaml"), "w") as handle:
            handle.write(GAME_CONFIG.replace(
                "  - { id: generic-web, profile: generic-web@1.0.0, role: required }",
                "  - generic-web"))
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertIn("unpinned", result.error)

    def test_a_transient_github_error_is_retryable(self):
        self.github.errors["view"] = ToolError("HTTP 502")
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, True))

    def test_a_non_retryable_github_error_is_not_retried(self):
        self.github.errors["create"] = ToolError("Name already exists", retryable=False)
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_waits_for_github_to_generate_the_contents(self):
        self.github.unpopulated_checks = 2
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(len(self.github.calls_to("has_file")), 3)

    def test_contents_that_never_arrive_are_a_retryable_failure(self):
        self.github.unpopulated_checks = 100
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, True))
        self.assertEqual(self.github.calls_to("clone"), [])


# -- the real CLI wrappers, with the process runner faked ----------------------------------


class CliWrappers(unittest.TestCase):
    def runner(self, responses):
        calls = []

        def run(argv, cwd=None, timeout=300):
            calls.append(argv)
            answer = responses.get(tuple(argv[:3]))
            if isinstance(answer, Exception):
                raise answer
            return answer or ""
        return run, calls

    def test_create_uses_the_template_and_never_a_blank_repository(self):
        view = json.dumps({"name": "neon-drift", "owner": {"login": "acme"},
                           "url": "https://github.com/acme/neon-drift", "description": "d",
                           "visibility": "PRIVATE", "defaultBranchRef": {"name": "main"},
                           "templateRepository": {"name": "web-game-template",
                                                  "owner": {"login": "acme"}}})
        run, calls = self.runner({("gh", "repo", "view"): view})
        repo = GhCli(run).create_from_template(REPO, TEMPLATE, "private", "d [m]")
        self.assertEqual(calls[0], ["gh", "repo", "create", REPO, "--template", TEMPLATE,
                                    "--private", "--description", "d [m]"])
        self.assertEqual((repo.template, repo.visibility, repo.default_branch),
                         (TEMPLATE, "private", "main"))

    def test_view_of_a_missing_repository_is_none(self):
        missing = ToolError("gh repo view failed: GraphQL: Could not resolve to a Repository")
        run, _ = self.runner({("gh", "repo", "view"): missing})
        self.assertIsNone(GhCli(run).view(REPO))
        run, _ = self.runner({("gh", "repo", "view"): ToolError("HTTP 502")})
        with self.assertRaises(ToolError):
            GhCli(run).view(REPO)

    def test_a_name_taken_by_an_invisible_repository_is_not_retryable(self):
        run, _ = self.runner({("gh", "repo", "create"): ToolError("Name already exists")})
        with self.assertRaises(ToolError) as caught:
            GhCli(run).create_from_template(REPO, TEMPLATE, "private", "d")
        self.assertFalse(caught.exception.retryable)

    def test_remote_urls(self):
        for url in ("git@github.com:acme/neon-drift.git", "https://github.com/acme/neon-drift",
                    "ssh://git@github.com/acme/neon-drift.git\n"):
            self.assertEqual(parse_remote(url), REPO)
        self.assertIsNone(parse_remote("https://gitlab.com/acme/neon-drift"))


# -- through the real engine ---------------------------------------------------------------

CONTRACT_WORKFLOW = """
workflow:
  id: init-contract
  version: 1
  steps:
    - id: design
      type: test.seed-design
      outputs: [game-design]
    - id: init
      type: init
      inputs: [game-design]
      outputs: [scaffold-record]
"""


class SeedDesignStep(WorkflowStep):
    type = "test.seed-design"

    def execute(self, inputs, context):
        return StepResult.success([ArtifactOutput("game-design", load_design())])


class EngineContract(InitCase):
    """Registered from config, run by the real engine, re-run without a second repository."""

    def setUp(self):
        super().setUp()
        workflow = os.path.join(self.scratch, "init-contract.workflow.yaml")
        with open(workflow, "w", encoding="utf-8") as handle:
            handle.write(CONTRACT_WORKFLOW)
        fakes = self

        class Api(WorkflowAPI):
            def registry(self, use_mock):
                registry = super().registry(use_mock)
                assert registry.resolve("init") is InitStep  # from factory.steps.modules
                registry.register(SeedDesignStep.type, SeedDesignStep)
                registry.register("init", lambda d: InitStep(
                    d, github=fakes.github, git=fakes.git, clock=lambda: NOW,
                    sleep=lambda _s: None))
                return registry

        config = FactoryConfig({"steps": {"modules": ["wgf_init"]},
                                "storage": {"fsync": False}, "init": self.config["init"]})
        self.api = Api(config=config, store_dir=os.path.join(self.scratch, "store"),
                       workflow=workflow)

    def test_the_engine_persists_the_record_and_a_rerun_reuses_the_repository(self):
        workspace_before = tree_digest(paths.WORKSPACE)
        state = self.api.run(RunRequest(project_id="neon-drift"))
        self.assertEqual(state.status, RunStatus.COMPLETED, state.steps["init"].error)

        ref = self.api.store.load(state.run_id).latest_artifact("scaffold-record")
        record = self.api.store.read_artifact(state.run_id, ref)
        self.assertEqual(record["outcome"], "created")
        self.assertEqual(record["idempotency_key"], f"wgf-init:{state.run_id}:init")
        self.assertEqual(ref.metadata["repository"], REPO)
        self.assertEqual(state.steps["init"].consumed, ["game-design@v1"])

        # `wgf init --run <id> --force`: the step executes again in the same run.
        again = self.api.run(RunRequest(run_id=state.run_id, scope="init", force=True))
        self.assertEqual(again.status, RunStatus.COMPLETED)
        latest = self.api.store.load(again.run_id).latest_artifact("scaffold-record")
        self.assertEqual(latest.version, 2)
        self.assertEqual(self.api.store.read_artifact(again.run_id, latest)["outcome"],
                         "reused")
        self.assertEqual(len(self.github.calls_to("create")), 1)
        self.assertEqual(tree_digest(paths.WORKSPACE), workspace_before)

    def test_the_new_game_workflow_resolves_init_to_this_module(self):
        registry = WorkflowAPI(config=FactoryConfig({"steps": {"modules": ["wgf_init"]}}),
                               store_dir=os.path.join(self.scratch, "s2")).registry(False)
        self.assertIs(registry.resolve("init"), InitStep)
        self.assertEqual(wgf_init.register.__module__, "wgf_init")



# -- game.config.yaml from the tech plan, and the local source ----------------------------

from test_techplan_module import designed, plan as make_plan  # noqa: E402
from wgf_init import apply_game_config, bootstrap_identity  # noqa: E402
from wgf_init.gameconfig import GameConfigError  # noqa: E402
from wgf_init.tooling import KEY_TRAILER, GitCli, run_command  # noqa: E402
from wgflib.yamllite import load as yaml_load  # noqa: E402

GIT = shutil.which("git")
BOOTSTRAP_YML = "name: Bootstrap\non:\n  push:\n"
IDENTITY = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]


def read_text(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


def git(directory, *args):
    completed = subprocess.run(["git", *IDENTITY, "-C", directory, *args], capture_output=True,
                               text=True, check=True)
    return completed.stdout.strip()


_PLANS = {}


def tech_plan(engine="threejs"):
    if engine not in _PLANS:
        _PLANS[engine] = make_plan(designed(engine)).artifacts[0].content
    return copy.deepcopy(_PLANS[engine])


def inputs_with_plan(design, plan):
    refs = {"game-design": ArtifactRef(
        id="game-design", type="game-design", version=1, location="x", checksum="x",
        content_hash=design["provenance"]["content_hash"])}
    if plan is not None:
        refs["tech-plan"] = ArtifactRef(id="tech-plan", type="tech-plan", version=1,
                                        location="y", checksum="y",
                                        content_hash=plan["provenance"]["content_hash"])
    content = {"game-design": design, "tech-plan": plan}
    return StepInputs(refs, lambda ref: copy.deepcopy(content[ref.type]), [])


def make_git_template(root, bootstrap=True):
    build_template_tree(root)
    if bootstrap:
        with open(os.path.join(root, ".github", "workflows", "bootstrap.yml"), "w") as handle:
            handle.write(BOOTSTRAP_YML)
    subprocess.run(["git", "init", "-q", "-b", "main", root], check=True)
    git(root, "add", "--all")
    git(root, "commit", "-q", "-m", "template")
    return root


class GameConfigRewrite(unittest.TestCase):
    PLAN = {"engine": {"type": "threejs"},
            "platforms": [{"id": "yandex", "profile": "yandex@1.0.0", "role": "required"},
                          {"id": "poki", "profile": "poki@1.0.0", "role": "optional"}],
            "monetization": {"ad_kinds": ["rewarded"], "iap": True}}

    def test_writes_only_the_owned_fields_and_keeps_comments(self):
        text = apply_game_config(GAME_CONFIG, self.PLAN)
        document = yaml_load(text)
        self.assertEqual(document["engine"], {"type": "threejs"})
        self.assertEqual(document["platforms"], self.PLAN["platforms"])
        self.assertEqual(document["monetization"], {"ad_kinds": ["rewarded"], "iap": True})
        self.assertEqual(document["game"]["id"], "example-game")  # bootstrap's, on GitHub
        self.assertEqual(document["build"], yaml_load(GAME_CONFIG)["build"])
        self.assertTrue(text.startswith("# Written by the Factory"))
        self.assertEqual(apply_game_config(text, self.PLAN), text)  # a fixed point

    def test_identity_is_bootstraps_derivation(self):
        self.assertEqual(bootstrap_identity("neon-drift"), ("neon-drift", "Neon Drift"))
        self.assertEqual(bootstrap_identity("My_Game 2"), ("my-game-2", "My Game 2"))
        text = apply_game_config(GAME_CONFIG, self.PLAN, bootstrap_identity("neon-drift"))
        self.assertEqual(yaml_load(text)["game"],
                         {"id": "neon-drift", "name": "Neon Drift", "version": "0.1.0"})

    def test_block_style_and_missing_sections(self):
        text = ("game:\n  id: example-game\n  name: Example Game\n  version: 0.1.0\n"
                "platforms:\n  - id: generic-web\n    profile: generic-web@1.0.0\n"
                "    role: required\n# trailing comment\nbuild:\n  command: pnpm build\n")
        result = yaml_load(apply_game_config(text, self.PLAN))
        self.assertEqual(result["platforms"], self.PLAN["platforms"])
        self.assertEqual(result["engine"], {"type": "threejs"})
        self.assertEqual(result["build"], {"command": "pnpm build"})

    def test_refuses_what_it_cannot_write_safely(self):
        with self.assertRaises(GameConfigError):
            apply_game_config(GAME_CONFIG, dict(self.PLAN, engine={"type": "unity"}))
        with self.assertRaises(GameConfigError):
            apply_game_config("engine: pixijs\nplatforms: []\n", self.PLAN)


@unittest.skipUnless(GIT, "git is not installed")
class ProcessRunner(unittest.TestCase):
    def test_run_command_goes_through_the_owned_process_runner(self):
        self.assertEqual(run_command([sys.executable, "-c", "print('ok')"]).strip(), "ok")
        with self.assertRaises(ToolError) as failed:
            run_command([sys.executable, "-c", "import sys; sys.exit(3)"])
        self.assertTrue(failed.exception.retryable)
        with self.assertRaises(ToolError) as missing:
            run_command(["wgf-no-such-tool-xyz"])
        self.assertFalse(missing.exception.retryable)
        with self.assertRaises(ToolError) as slow:
            run_command([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.5)
        self.assertIn("timed out", str(slow.exception))


@unittest.skipUnless(GIT, "git is not installed")
class LocalCase(InitCase):
    def setUp(self):
        super().setUp()
        self.template = make_git_template(os.path.join(self.scratch, "local-template"))
        self.git = GitCli()
        self.settings = {"source": "local", "template_path": self.template,
                         "projects_dir": self.projects}
        self.plan = tech_plan("threejs")

    def step(self):
        return InitStep(self.definition, github=self.github, git=self.git,
                        clock=lambda: NOW, sleep=lambda _s: None)

    def execute(self, context=None, plan="default"):
        plan = self.plan if plan == "default" else plan
        return self.step().execute(inputs_with_plan(self.design, plan),
                                   context or Context(self.config))

    def commits(self):
        return git(self.local, "rev-list", "--count", "HEAD")


class LocalSource(LocalCase):
    def test_creates_an_independent_project_offline_and_configures_it(self):
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(self.github.calls, [])  # no network, no gh at all
        self.assertEqual(git(self.local, "remote"), "")
        self.assertEqual(missing_infrastructure(self.local), [])
        self.assertEqual(self.commits(), "2")  # template as one initial commit + config

        config = wgf_init.read_game_config(self.local)
        document = yaml_load(read_text(self.local, "game.config.yaml"))
        planned = self.plan["repo_params"]["game_config"]
        self.assertEqual(document["engine"], {"type": "threejs"})
        self.assertEqual(document["platforms"], planned["platforms"])
        self.assertEqual(document["monetization"], planned["monetization"])
        self.assertEqual(document["game"]["id"], "neon-drift")
        self.assertEqual(document["game"]["name"], "Neon Drift")
        self.assertFalse(os.path.exists(os.path.join(self.local, ".github", "workflows",
                                                     "bootstrap.yml")))
        for platform in planned["platforms"]:
            vendored = os.path.join(self.local, "config", "platforms", f"{platform['id']}.yaml")
            with open(vendored, "rb") as a, \
                    open(os.path.join(paths.PLATFORMS, f"{platform['id']}.yaml"), "rb") as b:
                self.assertEqual(a.read(), b.read())
        pinned = json.loads(read_text(self.local, "config", "platforms", "pinned.json"))
        self.assertTrue({p["id"] for p in planned["platforms"]}
                        <= {p["id"] for p in pinned["profiles"]})
        self.assertEqual(git(self.local, "status", "--porcelain"), "")

        record = result.artifacts[0].content
        self.assertEqual(ArtifactContracts()("scaffold-record", record), [])
        self.assertEqual(record["outcome"], "created")
        self.assertEqual(record["template"]["source"], "local")
        self.assertEqual(record["template"]["commit_sha"], git(self.template, "rev-parse", "HEAD"))
        self.assertEqual(record["game_config"]["engine"], {"type": "threejs"})
        self.assertEqual(record["game_config"]["platforms"], config["platforms"])
        self.assertEqual(record["game_config"]["commit_sha"], git(self.local, "rev-parse", "HEAD"))
        self.assertIs(record["game_config"]["pushed"], False)
        self.assertIn("tech-plan", {i["artifact_type"] for i in record["provenance"]["inputs"]})
        self.assertIn(f"{KEY_TRAILER}: wgf-init:run-1:init",
                      git(self.local, "log", "-1", "--format=%B"))
        self.assertEqual(git(self.local, "config", "--local", "wgf.init-marker"),
                         "wgf-init:run-1:init")
        self.assertEqual(result.artifacts[0].metadata["source"], "local")

    def test_a_2d_plan_gets_pixijs(self):
        self.plan = tech_plan("pixijs")
        record = self.execute().artifacts[0].content
        self.assertEqual(record["game_config"]["engine"], {"type": "pixijs"})

    def test_rerun_is_idempotent(self):
        first = self.execute()
        head = git(self.local, "rev-parse", "HEAD")
        second = self.execute()
        self.assertEqual(second.outcome, StepOutcome.SUCCESS, second.error)
        record = second.artifacts[0].content
        self.assertEqual(record["outcome"], "reused")
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), head)
        self.assertEqual(self.commits(), "2")
        self.assertEqual(record["game_config"]["commit_sha"],
                         first.artifacts[0].content["game_config"]["commit_sha"])
        self.assertEqual(record["template"]["commit_sha"],
                         first.artifacts[0].content["template"]["commit_sha"])

    def test_a_crash_before_the_commit_is_recovered_with_one_commit(self):
        class Crashing(GitCli):
            crashed = False

            def commit(self, *args, **kwargs):
                if not Crashing.crashed:
                    Crashing.crashed = True
                    raise ToolError("killed")
                return super().commit(*args, **kwargs)

        self.git = Crashing()
        failed = self.execute()
        self.assertEqual((failed.outcome, failed.retryable), (StepOutcome.FAILED, True))
        retried = self.execute()
        self.assertEqual(retried.outcome, StepOutcome.SUCCESS, retried.error)
        self.assertEqual(retried.artifacts[0].content["outcome"], "reused")
        self.assertEqual(self.commits(), "2")
        self.assertEqual(git(self.local, "status", "--porcelain"), "")

    def test_a_revised_plan_in_the_same_run_is_a_second_keyed_commit(self):
        self.execute()
        self.plan = tech_plan("pixijs")  # G3 rejected, design and plan revised
        result = self.execute()
        self.assertEqual(result.artifacts[0].content["game_config"]["engine"], {"type": "pixijs"})
        self.assertEqual(self.commits(), "3")
        self.assertEqual(self.execute().artifacts[0].content["game_config"]["commit_sha"],
                         git(self.local, "rev-parse", "HEAD"))

    def test_the_template_ref_is_pinned(self):
        first = git(self.template, "rev-parse", "HEAD")
        with open(os.path.join(self.template, "later.txt"), "w") as handle:
            handle.write("added after the pin")
        git(self.template, "add", "later.txt")
        git(self.template, "commit", "-q", "-m", "later")
        self.settings["template_ref"] = first
        record = self.execute().artifacts[0].content
        self.assertEqual(record["template"]["commit_sha"], first)
        self.assertFalse(os.path.exists(os.path.join(self.local, "later.txt")))

    def test_without_a_plan_the_config_is_left_alone(self):
        result = self.execute(plan=None)
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        record = result.artifacts[0].content
        self.assertNotIn("commit_sha", record["game_config"])
        self.assertEqual(self.commits(), "1")
        with open(os.path.join(self.local, "game.config.yaml")) as handle:
            self.assertEqual(handle.read(), GAME_CONFIG)


class LocalRefusals(LocalCase):
    def test_another_runs_project_is_not_taken_over(self):
        self.execute(Context(self.config, run_id="run-0"))
        head = git(self.local, "rev-parse", "HEAD")
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.BLOCKED)
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), head)

    def test_adopting_requires_the_same_template(self):
        self.execute(Context(self.config, run_id="run-0"))
        self.settings["adopt_existing"] = True
        self.assertEqual(self.execute().outcome, StepOutcome.SUCCESS)
        other = make_git_template(os.path.join(self.scratch, "other-template"))
        self.settings["template_path"] = other
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))

    def test_a_directory_init_did_not_make_is_never_overwritten(self):
        os.makedirs(self.local)
        with open(os.path.join(self.local, "precious.txt"), "w") as handle:
            handle.write("mine")
        before = tree_digest(self.local)
        self.assertEqual(self.execute().outcome, StepOutcome.BLOCKED)
        self.assertEqual(tree_digest(self.local), before)

    def test_a_template_path_that_is_not_a_repository_blocks(self):
        self.settings["template_path"] = self.template_tree  # plain files, no .git
        self.assertEqual(self.execute().outcome, StepOutcome.BLOCKED)

    def test_a_plan_for_another_title_fails(self):
        self.plan["title_id"] = "other-title"
        result = self.execute()
        self.assertEqual((result.outcome, result.retryable), (StepOutcome.FAILED, False))
        self.assertFalse(os.path.exists(self.local))

    def test_local_settings(self):
        with self.assertRaises(SettingsError):
            InitSettings.from_config({"init": {"source": "local"}})
        with self.assertRaises(SettingsError):
            InitSettings.from_config({"init": {"source": "ftp", "template_path": "x"}})
        settings = InitSettings.from_config({"init": {"source": "local",
                                                      "template_path": "../t"}})
        self.assertEqual((settings.owner, settings.template_ref), (None, "HEAD"))


@unittest.skipUnless(GIT, "git is not installed")
class GithubSourceWithAPlan(InitCase):
    """source github: the clone gets the plan's config as one local commit, never pushed,
    and the identity lines stay for bootstrap.yml to set."""

    def setUp(self):
        super().setUp()
        with open(os.path.join(self.template_tree, ".github", "workflows", "bootstrap.yml"),
                  "w") as handle:
            handle.write(BOOTSTRAP_YML)
        self.git = GitCli()
        github = self.github

        def clone(full_name, destination):
            github._call("clone", full_name, destination)
            shutil.copytree(github.template_tree, destination, dirs_exist_ok=True)
            subprocess.run(["git", "init", "-q", "-b", "main", destination], check=True)
            git(destination, "add", "--all")
            git(destination, "commit", "-q", "-m", "Initial commit")
            git(destination, "remote", "add", "origin", f"https://github.com/{full_name}.git")

        self.github.clone = clone
        self.plan = tech_plan("threejs")

    def execute(self, context=None):
        step = InitStep(self.definition, github=self.github, git=self.git, clock=lambda: NOW,
                        sleep=lambda _s: None)
        return step.execute(inputs_with_plan(self.design, self.plan),
                            context or Context(self.config))

    def test_config_committed_locally_and_identity_left_to_bootstrap(self):
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        document = yaml_load(read_text(self.local, "game.config.yaml"))
        self.assertEqual(document["engine"], {"type": "threejs"})
        self.assertEqual(document["game"]["id"], "example-game")
        self.assertTrue(os.path.exists(os.path.join(self.local, ".github", "workflows",
                                                    "bootstrap.yml")))
        record = result.artifacts[0].content
        self.assertEqual(record["template"]["source"], "github")
        self.assertIs(record["game_config"]["pushed"], False)
        self.assertEqual(record["game_config"]["commit_sha"], git(self.local, "rev-parse", "HEAD"))
        # Nothing was pushed: the remote-tracking ref does not even exist.
        self.assertEqual(git(self.local, "branch", "-r"), "")
        self.assertIn("pull --rebase", record["notes"])

        again = self.execute()
        self.assertEqual(again.artifacts[0].content["outcome"], "reused")
        self.assertEqual(git(self.local, "rev-list", "--count", "HEAD"), "2")
        self.assertEqual(len(self.github.calls_to("create")), 1)


# -- against the real template -------------------------------------------------------------


_PINNED, _PINNED_WHY = pinned_template.checkout()


@unittest.skipUnless(_PINNED, _PINNED_WHY)
class RealTemplate(unittest.TestCase):
    """TEMPLATE_INFRASTRUCTURE is a claim about web-game-template. Check it against the
    real thing, so the list cannot drift into describing a template that does not exist."""

    def test_the_template_has_every_expected_piece(self):
        self.assertEqual(missing_infrastructure(_PINNED), [])

    def test_the_template_game_config_is_pinned(self):
        game_config = wgf_init.read_game_config(_PINNED)
        self.assertTrue(game_config["platforms"])


REAL_TEMPLATE = _PINNED or ""


@unittest.skipUnless(GIT and _PINNED, _PINNED_WHY or "git is not on PATH")
class RealTemplateLocalSource(LocalCase):
    """source local against the real template: what a golden regression run does."""

    def setUp(self):
        super().setUp()
        self.settings["template_path"] = REAL_TEMPLATE

    def test_a_3d_title_from_the_real_template(self):
        result = self.execute()
        self.assertEqual(result.outcome, StepOutcome.SUCCESS, result.error)
        self.assertEqual(missing_infrastructure(self.local), [])
        document = yaml_load(read_text(self.local, "game.config.yaml"))
        self.assertEqual(document["engine"], {"type": "threejs"})
        self.assertEqual(document["platforms"],
                         self.plan["repo_params"]["game_config"]["platforms"])
        self.assertEqual(document["game"]["id"], "neon-drift")
        # The rest of the template's file survives untouched.
        with open(os.path.join(REAL_TEMPLATE, "game.config.yaml")) as handle:
            original = yaml_load(handle.read())
        for key in ("build", "verification", "publishing"):
            self.assertEqual(document.get(key), original.get(key), key)
        self.assertEqual(self.execute().artifacts[0].content["outcome"], "reused")
        self.assertEqual(self.commits(), "2")


@unittest.skipUnless(os.environ.get("WGF_AJV") and shutil.which("npx"),
                     "set WGF_AJV=1 to validate with ajv (needs npx)")
class AjvSchema(InitCase):
    def test_the_scaffold_record_validates_against_its_schema(self):
        path = os.path.join(self.scratch, "scaffold-record.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.execute().artifacts[0].content, handle)
        completed = subprocess.run(
            ["npx", "--yes", "-p", "ajv-cli@5", "-p", "ajv-formats@2", "ajv", "validate",
             "-s", "core/artifacts/scaffold-record.schema.json",
             "-r", "core/artifacts/shared/*.schema.json", "-c", "ajv-formats",
             "--spec=draft2020", "--strict=false", "-d", path],
            cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


@unittest.skipUnless(GIT and os.environ.get("WGF_AJV") and shutil.which("npx"),
                     "set WGF_AJV=1 to validate with ajv (needs npx)")
class AjvSchemaLocal(LocalCase):
    execute_record = AjvSchema.test_the_scaffold_record_validates_against_its_schema

    def test_the_local_record_with_engine_and_commit_validates(self):
        record = self.execute().artifacts[0].content
        self.assertIn("commit_sha", record["game_config"])
        self.execute_record()


if __name__ == "__main__":
    unittest.main()
