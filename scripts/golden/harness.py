"""The golden-run harness: one real `new-game` run, isolated, with its evidence summarized.

    python3 scripts/golden/run.py --game 2d|3d [--workdir DIR] [--keep] [--json]

What it does, in order:

1. Makes an isolated work directory (default: a fresh temp dir under $WGF_GOLDEN_DIR or
   /tmp - a fast local file system, never the Windows mount) holding the run store, the
   game repository and the evidence.
2. Builds an isolated factory configuration: workspace/config/factory.yaml, read and never
   written, with the overrides below. Nothing in workspace/ is written by a golden run.
3. Runs the ONE shared `new-game` workflow through the real WorkflowAPI - the same
   assembly `wgf new-game` uses, without --mock, so every step is its real module:
   research -> strategy -> G2 -> design -> tech-plan -> G3 -> init -> assets -> develop ->
   review -> sdk -> verify -> G4 -> release. The run stops WAITING at G4, which only a
   person decides; the harness answers it `pass` (below) and resumes.
4. Browser-tests the resulting game on its own (browser.py), independently of the
   pipeline's own checks.
5. Writes a summary: every step's outcome and duration, every artifact id@version with its
   content hash, the game repository's commits, the engine, the release manifest and its
   zip digests, the evidence statuses exactly as the modules wrote them, and the browser
   evidence. The run passes only if every step reached its expected outcome
   (games.EXPECTED_STEPS) and release drafted a manifest.

The overrides, and why each is legitimate:

    init.source: local           no GitHub: the repository is `git archive` of the template
                                 checkout, committed locally (docs/init-module.md)
    *.checkouts / games_dir      every module finds the repository under <workdir>/games
    assets.root                  assets are written into that repository's public/assets
    discovery.*                  the frozen evidence and a one-archetype catalog under
                                 fixtures/, and a fixed as_of - deterministic steering
                                 through the step's documented settings
    develop.developer            kind `command`: the REPLAY developer (replay_developer.py),
                                 which ports a known-good example game. It is not an agent.
    review.reviewer              kind `command`: the golden reviewer (reviewer.py), a
                                 deterministic rule check. It is not an agent either.
    checkpoints.auto_approve     [G2, G3]: both are reversible gates, which the engine lets
                                 an installation auto-approve. G4/G6/G7 never are.

And one decision, not an override: G4 (prototype-review) is irreversible, so nothing in the
configuration can approve it. The harness resumes the waiting run with `pass` through the
same API `wgf decide` uses, with `decided_by` from default_decider() - `human`, because the
person who started the golden run is outside every step's process tree; were the harness
itself inside one, the decision would be `automation` and G4 would refuse it and keep
waiting, failing the run. A golden run is a regression run of a known-good port, so the
pass is that person's, stated in the decision's note (G4_NOTE).
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from wgflib import paths  # noqa: E402
from wgflib.yamllite import load_file  # noqa: E402

from golden import games  # noqa: E402

__all__ = ["template_dir", "make_workdir", "build_config", "GoldenRun", "Summary"]

from wgflib import template  # noqa: E402

# The template a golden run creates its game from: the commit pinned in
# workspace/config/template.lock.json, as a checkout of exactly that commit
# (wgflib.template.checkout) - never the sibling working copy as it happens to be.
# WGF_TEMPLATE_COMMIT=<sha> runs against another revision on purpose (adopting a new pin);
# WGF_GOLDEN_TEMPLATE_REF is its older spelling.
if os.environ.get("WGF_GOLDEN_TEMPLATE_REF") and not os.environ.get("WGF_TEMPLATE_COMMIT"):
    os.environ["WGF_TEMPLATE_COMMIT"] = os.environ["WGF_GOLDEN_TEMPLATE_REF"]


def template_dir():
    """The pinned checkout; raises wgflib.template.TemplateError if it cannot be obtained."""
    return template.checkout()


def __getattr__(name):
    # `harness.TEMPLATE_DIR`: the pinned checkout, resolved on first use; "" when it cannot
    # be obtained, so the fast tests skip instead of reading another revision.
    if name == "TEMPLATE_DIR":
        try:
            return template_dir()
        except template.TemplateError:
            return ""
    # `harness.PORTS_DIR`: a checkout of the lock's golden_ports commit, the replay's
    # fixtures; "" when it cannot be obtained.
    if name == "PORTS_DIR":
        try:
            return template.golden_ports_checkout()
        except template.TemplateError:
            return ""
    raise AttributeError(name)


# Who the golden run's local commits are by (develop's and sdk's): the machine may have no
# git identity. Init has its own default (wgf-init). Nothing is ever pushed.
GOLDEN_AUTHOR = {"name": "wgf-golden", "email": "wgf-golden@users.noreply.invalid"}

AUTO_APPROVE = ["G2", "G3"]  # reversible gates only; the engine refuses G4/G6/G7 anyway

# The gate the harness answers as the person running it, and what it answers. At most this
# many answers per run: a pass does not loop, so a second wait means something is wrong.
G4_GATE, G4_DECISION = "G4", "pass"
G4_NOTE = ("golden run: a regression run of a known-good example port; pass given by the "
           "person running the golden harness")
MAX_GATE_ANSWERS = 2

# Environment variables that would point a module somewhere other than this run's checkout.
FOREIGN_ENV = ("WGF_GAME_REPO", "WGF_RESEARCH_LIVE", "WGF_GAME_CONFIG")


# The golden run must never contact a portal - yet a build for a portal loads that portal's
# SDK from its CDN, and every browser test the pipeline runs would fetch it (on a machine
# with network, the template's own "makes no insecure requests" smoke then fails on the
# portal SDK's http:// sub-requests). For the whole run, HTTP(S) goes through a local proxy
# that refuses everything and records it (netguard.py); localhost is reached directly.
# pnpm needs no network either: the store is warm and installs are --offline /
# --prefer-offline. A guard, not a sandbox: a child that ignores proxy variables is not
# stopped by it.
from wgflib.netguard import NO_PROXY, PROXY_VARS, sandbox_env  # noqa: E402,F401


class network_sandbox:
    """Start the refusing proxy and point this process's environment at it (children
    inherit it); restore the environment and stop the proxy afterwards."""

    def __enter__(self):
        from golden.netguard import RefusingProxy
        self.proxy = RefusingProxy().start()
        env = sandbox_env(self.proxy.url)
        self.saved = {name: os.environ.get(name) for name in env}
        os.environ.update(env)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.proxy.stop()
        return False


def make_workdir(base=None):
    """A fresh work directory on a local file system."""
    base = base or os.environ.get("WGF_GOLDEN_DIR") or "/tmp"
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix="wgf-golden-", dir=base)


def _merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def base_config():
    """workspace/config/factory.yaml's `factory:` section, read-only."""
    document = load_file(os.path.join(paths.CONFIG, "factory.yaml")) or {}
    return copy.deepcopy(document.get("factory") or {})


def build_config(game, workdir, template_dir=None, python=None):
    """The golden run's factory configuration, as the `factory:` mapping."""
    template_dir = os.path.abspath(template_dir or globals()["template_dir"]())
    python = python or sys.executable
    games_dir = os.path.join(workdir, "games")
    repo = os.path.join(games_dir, game.title_id)
    config = base_config()
    overrides = {
        "storage": {"directory": os.path.join(workdir, "factory-store"), "fsync": True},
        "init": {
            "source": "local",
            "template_path": template_dir,
            "template_ref": template.expected_commit(),
            "projects_dir": games_dir,
            "adopt_existing": False,
        },
        "discovery": {
            "corpus": games.RESEARCH_CORPUS,
            "catalog": game.catalog,
            # No backlog: the golden scan must not depend on workspace/opportunities.
            "backlog": os.path.join(games.FIXTURES, "no-backlog"),
            "as_of": games.AS_OF,
            "live": False,
        },
        "assets": {"root": repo},
        "develop": {
            "checkouts": games_dir,
            "author": dict(GOLDEN_AUTHOR),
            "developer": {
                "kind": "command",
                "argv": [python, os.path.join(HERE, "replay_developer.py"),
                         "--game", game.key, "--brief", "{brief}", "--repo", "{repo}",
                         "--ports", template.golden_ports_checkout(), "--key", "{key}"],
                "timeout_seconds": 1800,
            },
        },
        "review": {
            "checkouts": games_dir,
            "reviewer": {
                "kind": "command",
                "argv": [python, os.path.join(HERE, "reviewer.py"),
                         "--game", game.key, "--repo", "{repo}", "--verdict", "{verdict}",
                         "--commit", "{commit}", "--brief", "{brief}"],
                "timeout_seconds": 600,
                "idle_timeout_seconds": 300,
                "verdict_from": "file",
            },
        },
        "sdk": {"games_dir": games_dir, "commit_author": dict(GOLDEN_AUTHOR)},
        "verification": {"checkouts": games_dir},
        "release": {"checkouts": games_dir},
        "checkpoints": {"auto_approve": list(AUTO_APPROVE)},
    }
    return _merge(config, overrides)


def step_ids():
    return [step for step, _ in games.EXPECTED_STEPS]


class GoldenRun:
    """One golden run of one game. `execute()` returns a Summary."""

    def __init__(self, game_key, workdir=None, keep=False, template_dir=None, progress=None,
                 browser=True):
        self.game = games.game(game_key)
        self.created_workdir = workdir is None
        self.workdir = os.path.abspath(workdir or make_workdir())
        os.makedirs(self.workdir, exist_ok=True)
        self.keep = keep
        self.template_dir = os.path.abspath(template_dir or globals()["template_dir"]())
        self.progress = progress
        self.browser = browser
        self.config_data = build_config(self.game, self.workdir, self.template_dir)
        self.repo = os.path.join(self.workdir, "games", self.game.title_id)
        self.evidence_dir = os.path.join(self.workdir, "evidence")

    def api(self):
        from wgflib.workflow.api import WorkflowAPI
        from wgflib.workflow.config import FactoryConfig
        config = FactoryConfig(self.config_data, source="golden:" + self.game.key)
        subscribers = [self.progress] if self.progress else []
        return WorkflowAPI(config=config, store_dir=self.config_data["storage"]["directory"],
                           workflow="new-game", subscribers=subscribers)

    def write_config(self):
        """A copy of the configuration the run used, for whoever reads the evidence."""
        os.makedirs(self.evidence_dir, exist_ok=True)
        path = os.path.join(self.evidence_dir, f"factory-config-{self.game.key}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"factory": self.config_data}, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return path

    def run_workflow(self, resume=None, from_step=None):
        from wgflib.workflow.api import RunRequest
        for name in FOREIGN_ENV:
            os.environ.pop(name, None)
        api = self.api()
        if resume:
            request = RunRequest(resume=resume, from_step=from_step)
        else:
            request = RunRequest(project_id=self.game.title_id)
        started = time.monotonic()
        state = api.run(request)
        for _ in range(MAX_GATE_ANSWERS):
            pending = api.pending(state)
            if not pending or pending.get("gate") != G4_GATE:
                break
            # decided_by is left to default_decider(), as for `wgf decide`.
            state = api.run(RunRequest(resume=state.run_id, decision=G4_DECISION,
                                       note=G4_NOTE))
        return api, state, time.monotonic() - started

    def execute(self, resume=None, from_step=None):
        from golden import summary as summaries
        self.write_config()
        with network_sandbox() as guard:
            api, state, seconds = self.run_workflow(resume=resume, from_step=from_step)
            pipeline_network = guard.proxy.summary()
            browser = None
            developed = (state.steps.get("develop") and
                         state.steps["develop"].status == "SUCCESS")
            if self.browser and developed and os.path.isdir(self.repo):
                # Even when a later step stopped the run, the game develop committed can be
                # played; the evidence records whether it was the released bundle.
                from golden import browser as browsers
                _, contents = summaries._artifacts(api, state)
                release = summaries._release(self.repo, contents.get("release-manifest"))
                browser = browsers.capture(self.game, self.repo, self.evidence_dir,
                                           run_id=state.run_id, release=release)
            network = {"pipeline": pipeline_network, "whole_run": guard.proxy.summary()}
        result = summaries.build(self, api, state, seconds, browser)
        # What the run tried to reach outside localhost, every attempt refused.
        result["network_refused"] = network
        summaries.write(result, self.evidence_dir, self.game.key)
        return result

    def cleanup(self):
        if not self.keep and self.created_workdir:
            shutil.rmtree(self.workdir, ignore_errors=True)
