"""AGENTS category: the live developer -> reviewer loop on a game built from the brief.

    WGF_LIVE_AGENT=1 python -m unittest test_live_loop -v      (from scripts/tests; costs money)

The live test runs golden.live: the golden 2D pipeline with the developer and the reviewer
workspace/config/factory.yaml documents, verbatim, from develop visit 1 - the developer
builds the game from scratch from the Factory's brief, the reviewer judges it against the
design. It asserts what convergence means: the run completes; the last development commit is
approved by review and the commit that ships by sdk-review; every develop check passed on it;
the build stays inside the developer's files; every verdict is trusted and nothing is left
running. It does NOT assert that review requests changes first - a build may be approved on
its first review; the evidence records every review either way. WGF_LIVE_KEEP=<dir> keeps the
run's work directory under <dir>/<test id>.

The other tests are offline and always run: the live run's argvs are the documented ones,
verbatim, and the configuration file `live.py config` writes reads back as the same thing.
"""

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

import pinned_template  # noqa: E402
from golden import games, live  # noqa: E402
from test_core_agents import evidence_dir  # noqa: E402
from wgf_develop import brief as briefs  # noqa: E402
from wgf_develop import scope, seam  # noqa: E402
from wgf_develop.settings import Settings as DevelopSettings  # noqa: E402
from wgf_review.settings import Settings as ReviewSettings  # noqa: E402
from wgflib import template  # noqa: E402
from wgflib.workflow.config import load_config  # noqa: E402
from wgflib.workflow.contracts import ArtifactContracts  # noqa: E402
from wgflib.workflow.model import RunStatus  # noqa: E402
from wgflib.yamllite import load  # noqa: E402

LIVE = os.environ.get("WGF_LIVE_AGENT") == "1"


def _ports():
    try:
        return template.golden_ports_checkout(), None
    except template.TemplateError as exc:
        return None, f"pinned golden ports unavailable: {exc}"


PORTS, PORTS_UNAVAILABLE = _ports()
TEMPLATE, TEMPLATE_UNAVAILABLE = pinned_template.checkout()


def owned_by_someone_else(path):
    """A path inside the writable ones that is still not the developer's."""
    return path in seam.SEAM_FILES or any(
        path == p or (p.endswith("/") and path.startswith(p)) for p, _ in briefs.TEMPLATE_SOURCE)


class ShippedArgvs(unittest.TestCase):
    def test_the_examples_are_the_documented_claude_hosts(self):
        developer, reviewer = live.shipped_agent_examples()
        for block in (developer, reviewer):
            self.assertEqual(block["kind"], "command")
            self.assertEqual(block["argv"][:3], ["claude", "-p", "{prompt}"])
        self.assertEqual(reviewer["verdict_from"], "stdout")
        self.assertIn("--safe-mode", reviewer["argv"])

    def test_a_missing_example_is_refused_not_guessed(self):
        path = os.path.join(tempfile.mkdtemp(prefix="wgf-live-"), "factory.yaml")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
        with open(path, "w") as handle:
            handle.write("factory:\n  develop: {}\n")
        with self.assertRaises(live.LiveSetupError):
            live.shipped_agent_examples(path)


class Yaml(unittest.TestCase):
    def test_it_reads_back_as_the_same_value(self):
        developer, reviewer = live.shipped_agent_examples()
        value = {"factory": {"develop": {"developer": developer},
                             "review": {"reviewer": reviewer},
                             "empty": {}, "none": [], "n": 1.5, "flag": True, "nothing": None,
                             "tricky": "It's \"q\" # not a comment: {prompt}"}}
        self.assertEqual(load(live.to_yaml(value)), value)


@unittest.skipUnless(PORTS and TEMPLATE, PORTS_UNAVAILABLE or TEMPLATE_UNAVAILABLE)
class LiveConfig(unittest.TestCase):
    """The configuration a live build executes: the documented agents, verbatim."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="wgf-live-config-")
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)
        self.developer, self.reviewer = live.shipped_agent_examples()

    def build(self, **kwargs):
        return live.build_live_config(games.game(live.GAME), self.workdir, TEMPLATE, **kwargs)

    def test_both_agents_are_the_documented_ones_verbatim(self):
        config, record = self.build()
        self.assertEqual(config["develop"]["developer"], self.developer)
        self.assertEqual(config["review"]["reviewer"], self.reviewer)
        self.assertEqual((record["developer"], record["reviewer"]),
                         (self.developer, self.reviewer))
        self.assertEqual(record["source"], "workspace/config/factory.yaml")
        self.assertIn("host_version", record)

    def test_human_gates_auto_approve_nothing(self):
        config, record = self.build(human_gates=True)
        self.assertEqual(config["checkpoints"]["auto_approve"], [])
        self.assertEqual(record["auto_approved_gates"], [])
        config, _ = self.build()
        self.assertEqual(config["checkpoints"]["auto_approve"], ["G2", "G3"])  # as golden

    def test_the_written_config_is_what_the_cli_loads(self):
        done = subprocess.run([sys.executable, os.path.join(SCRIPTS, "golden", "live.py"),
                               "config", "--workdir", self.workdir, "--human-gates"],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        data = load_config(os.path.join(self.workdir, "factory.yaml")).data
        self.assertEqual(DevelopSettings.resolve(data).developer["argv"], self.developer["argv"])
        review = ReviewSettings.resolve(data)
        self.assertEqual((review.argv, review.verdict_from),
                         (self.reviewer["argv"], self.reviewer["verdict_from"]))
        self.assertEqual(data["checkpoints"]["auto_approve"], [])
        with open(os.path.join(self.workdir, "evidence", "live-agents.json")) as handle:
            self.assertEqual(json.load(handle)["developer"], self.developer)

    def test_the_live_run_says_it_is_not_sandboxed(self):
        with live.LiveGoldenRun.sandbox(None) as guard:
            self.assertFalse(guard.proxy.summary()["sandboxed"])


@unittest.skipUnless(LIVE, "live: set WGF_LIVE_AGENT=1 (builds the golden 2D game from the "
                           "brief with the developer and reviewer factory.yaml documents; "
                           "costs money)")
@unittest.skipUnless(PORTS and TEMPLATE, PORTS_UNAVAILABLE or TEMPLATE_UNAVAILABLE)
class LiveBuildConverges(unittest.TestCase):
    """A real developer -> reviewer loop, on a game built from the brief, to a release."""

    def setUp(self):
        keep = os.environ.get("WGF_LIVE_KEEP")
        workdir = evidence_dir(keep, self.id()) if keep else None
        self.run_ = live.LiveGoldenRun(workdir=workdir, keep=bool(keep))
        self.addCleanup(self.run_.cleanup)
        self.summary = self.run_.execute()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.run_.repo, check=True,
                              capture_output=True, text=True).stdout

    def test_the_loop_converges_to_a_release(self):
        run, summary, state = self.run_, self.summary, self.run_.state
        explain = json.dumps({k: summary.get(k) for k in ("run_status", "run_message",
                                                          "steps")}, indent=1, default=str)
        reviews = run.reports("review-report")
        prototypes = run.reports("prototype-report")
        self.assertTrue(reviews, explain)
        contracts = ArtifactContracts()
        for report in reviews:  # every verdict trusted, every reviewer gone
            self.assertEqual(contracts("review-report", report), [])
            self.assertTrue(report["isolation"]["intact"], report["isolation"])
            self.assertIn(report["verdict"], ("approve", "request-changes"),
                          report.get("failure"))
            self.assertEqual(report["reviewer"]["killed_pids"], [], report["reviewer"])
        self.assertEqual(state.status, RunStatus.COMPLETED, explain)

        # The last development commit: every check green, approved by review, and - from the
        # commit develop first started on - only the developer's own files changed.
        first, last = (p["build_ref"]["commit_sha"] for p in (prototypes[0], prototypes[-1]))
        started = json.loads(self.git("show", f"{first}:docs/development/brief.json"))
        for path in [p for p in self.git("diff", "--name-only", started["baseline_commit"],
                                         last).split("\n") if p]:
            self.assertIsNone(scope.refusal(path, started["writable_paths"]), path)
            self.assertFalse(owned_by_someone_else(path), path)
        for check in prototypes[-1].get("checks") or []:
            self.assertEqual(check.get("status"), "passed", check)
        approved = [r["reviewed_commit"] for r in reviews if r["verdict"] == "approve"]
        self.assertIn(last, approved, [r["verdict"] for r in reviews])

        # The commit that ships: sdk-review approved it, verify and G4 passed, a release draft.
        sdk = run.reports("sdk-report")[-1]["build_ref"]["commit_sha"]
        self.assertEqual((reviews[-1]["reviewed_commit"], reviews[-1]["baseline_commit"],
                          reviews[-1]["verdict"]), (sdk, last, "approve"))
        self.assertTrue(summary["passed"], explain)
        self.assertTrue(summary["release"], explain)
        self.assertEqual(summary["leftover_processes"], [], summary["leftover_processes"])
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), sdk)
        self.assertEqual(self.git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
