"""K6.4: what a fresh session may learn depends on how far its evidence was repeated.

Three sessions, each in a SEPARATE process with its own project directory (WGF_PROJECT_DIR)
and an environment scrubbed of the others' (scripts/tests/fixtures/transfer/
learning_session.py writes the session's runs; the REAL `wgf knowledge ingest` and
`wgf knowledge promote` then run against that project, each a process of its own):

  Single     one measured FAIL->PASS pair on one scenario of one run: ingest records it
             single-run; promote drafts only an experimental candidate lesson
             (OBSERVATION/HEURISTIC) and refuses a RECOMMENDATION or VALIDATED_PRINCIPLE.
  Validated  the repair reproduced on desktop and on mobile: ingest records it validated;
             promote may draft a VALIDATED_PRINCIPLE - an enforced, validated lesson with
             its three test stubs and the evidence's verified leg - whose patch applies.
  Circular   the single pair, then only circular "validation": the same reports re-ingested
             under another run, a pass replaying the failing commit, a judge re-reading the
             build it passed. Each is refused with its reason; the strength stays
             single-run, and promote refuses the stronger classifications.

The ledgers are made by the REAL triage step; the playability reports by the playability
step's own path over FIXTURE bot records, the visual-qa reports in the step's shape with a
FIXTURE judge's scores (learning_ledgers.py). The lesson proposed is held by an advisory
check, the band below REQUIRED that strength caps; a hard or quality check would still
derive BLOCKING or REQUIRED from its tier (K4, test_knowledge_strength).

    python -m unittest scripts.tests.test_knowledge_learning_transfer
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
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from wgf_knowledge import model, promote  # noqa: E402
from wgf_quality import registry  # noqa: E402
from wgflib.yamllite import load as load_yaml  # noqa: E402

SESSION = os.path.join(HERE, "fixtures", "transfer", "learning_session.py")
WGF = os.path.join(SCRIPTS, "wgf.py")


def scrubbed_env(project, foreign=()):
    """This process's environment without any WGF_ variable and without anything naming
    another session's directory, plus the session's own project."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("WGF_")
           and not any(f and f in v for f in foreign)}
    env["WGF_PROJECT_DIR"] = project
    return env


class Session:
    """One session: its project, its runs (made in a process of its own), and the knowledge
    CLI run against it, each command in a process of its own."""

    def __init__(self, tmp, name, foreign=()):
        self.project = os.path.join(tmp, name)
        os.makedirs(self.project)
        self.env = scrubbed_env(self.project, foreign)
        out = os.path.join(self.project, "summary.json")
        done = subprocess.run([sys.executable, SESSION, "make", "--session", name,
                               "--out", out], cwd=ROOT, env=self.env, capture_output=True,
                              text=True, timeout=600)
        if done.returncode != 0:
            raise AssertionError(f"session {name} failed:\n{done.stdout}\n{done.stderr}")
        with open(out, encoding="utf-8") as handle:
            self.summary = json.load(handle)
        self.ingested = [self.cli("ingest", run, "--json") for run in self.summary["runs"]]

    def cli(self, *args):
        done = subprocess.run([sys.executable, WGF, "knowledge", *args], cwd=ROOT,
                              env=self.env, capture_output=True, text=True, timeout=600)
        return done.returncode, done.stdout, done.stderr

    def candidates(self):
        with open(os.path.join(self.project, "workspace", "lessons", "candidates.yaml"),
                  encoding="utf-8") as handle:
            return load_yaml(handle.read())["candidates"]

    def promote(self, *args):
        code, out, err = self.cli("promote", "C-1", "--json", *args)
        return code, (json.loads(out) if out.strip().startswith("{") else {}), out + err


class LearningTransfer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wgf-k64-transfer-")
        cls.single = Session(cls.tmp, "single")
        cls.validated = Session(cls.tmp, "validated", foreign=(cls.single.project,))
        cls.circular = Session(cls.tmp, "circular",
                               foreign=(cls.single.project, cls.validated.project))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def only(self, session):
        for code, out, err in session.ingested:
            self.assertEqual(code, 0, out + err)
        records = session.candidates()
        self.assertEqual([r["id"] for r in records], ["C-1"])
        return records[0]

    # -- isolation ----------------------------------------------------------------------

    def test_each_session_is_its_own_project(self):
        sessions = (self.single, self.validated, self.circular)
        for session in sessions:
            others = [s.project for s in sessions if s is not session]
            self.assertEqual(session.summary["project"], session.project)
            self.assertEqual(session.summary["env"], ["WGF_PROJECT_DIR"])
            self.assertTrue(session.summary["store"].startswith(session.project))
            for value in list(session.env.values()) + session.summary["argv"]:
                for other in others:
                    self.assertNotIn(other, value)
            runs = {s["run"] for c in session.candidates() for s in c["sources"]}
            self.assertEqual(runs, set(session.summary["runs"]))

    # -- single-run ---------------------------------------------------------------------

    def test_single_run_evidence_drafts_only_an_experimental_lesson(self):
        record = self.only(self.single)
        self.assertEqual((record["basis"], record["strength"]), ("measured", "single-run"))
        self.assertIn("FAILED on aaaaaaaaaaaa and PASSED on bbbbbbbbbbbb once",
                      record["strength_why"])
        code, result, text = self.single.promote()
        self.assertEqual(code, 0, text)
        lesson = result["lesson"]
        self.assertEqual((lesson["status"], lesson["lifecycle"], lesson["classification"]),
                         ("gap", "candidate", "OBSERVATION"))
        self.assertEqual(result["evidence"]["strength"]["level"], "single-run")
        for asked in ("RECOMMENDATION", "VALIDATED_PRINCIPLE"):
            code, result, text = self.single.promote("--classification", asked)
            self.assertEqual(code, 1, text)
            self.assertIn("single-run", result["refused"])

    # -- validated ----------------------------------------------------------------------

    def test_validated_evidence_may_draft_a_validated_principle(self):
        record = self.only(self.validated)
        self.assertEqual(record["strength"], "validated", record["strength_why"])
        self.assertEqual(record["refused_evidence"], [])
        patch_file = os.path.join(self.validated.project, "lesson.patch")
        code, result, text = self.validated.promote("--classification", "VALIDATED_PRINCIPLE",
                                                    "--out", patch_file)
        self.assertEqual(code, 0, text)
        lesson = result["lesson"]
        self.assertEqual((lesson["status"], lesson["lifecycle"], lesson["classification"]),
                         ("enforced", "validated", "VALIDATED_PRINCIPLE"))
        self.assertEqual(result["evidence"]["verified"]["commit"], "b" * 40)
        # The patch applies to the Factory's knowledge files and holds the model.
        work = os.path.join(self.tmp, "apply")
        for relative in (promote.LESSONS_PATH, promote.EVIDENCE_PATH):
            target = os.path.join(work, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, *relative.split("/")), target)
        done = subprocess.run(["git", "apply", "--unsafe-paths", "--directory=.", patch_file],
                              cwd=work, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(work, *promote.LESSONS_PATH.split("/")), encoding="utf-8") as h:
            lessons = load_yaml(h.read())
        with open(os.path.join(work, *promote.EVIDENCE_PATH.split("/")), encoding="utf-8") as h:
            evidence = load_yaml(h.read())
        checks, _ = registry.classify(registry.load(ROOT)["tiers"], ROOT)
        applied = {l["id"]: l for l in lessons["lessons"]}[lesson["id"]]
        self.assertEqual(applied, lesson)
        self.assertEqual([p for p in model.lesson_problems(lessons, checks,
                                                           model.vocabulary(ROOT), evidence)
                          if f" {lesson['id']}:" in p], [])

    # -- circular -----------------------------------------------------------------------

    def test_circular_validation_is_refused_and_the_strength_stays_single_run(self):
        record = self.only(self.circular)
        self.assertEqual(len(record["sources"]), 3)
        self.assertEqual(record["strength"], "single-run", record["strength_why"])
        refused = {r["rule"]: r for r in record["refused_evidence"]}
        self.assertEqual(sorted(refused), ["duplicate", "same-build", "self-agreement"])
        self.assertEqual(refused["duplicate"]["run"], "circular-copy")
        self.assertIn("counted once", refused["duplicate"]["reason"])
        self.assertEqual(refused["same-build"]["run"], "circular-1")
        self.assertIn("commit it failed on", refused["same-build"]["reason"])
        self.assertEqual(refused["self-agreement"]["run"], "circular-judge")
        self.assertIn("already judged", refused["self-agreement"]["reason"])
        for asked in ("RECOMMENDATION", "VALIDATED_PRINCIPLE"):
            code, result, text = self.circular.promote("--classification", asked)
            self.assertEqual(code, 1, text)
            self.assertIn("single-run", result["refused"])
        code, result, text = self.circular.promote()
        self.assertEqual(code, 0, text)
        self.assertEqual(result["lesson"]["lifecycle"], "candidate")


if __name__ == "__main__":
    unittest.main()
