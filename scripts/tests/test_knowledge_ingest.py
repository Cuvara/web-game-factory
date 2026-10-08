"""K4: lesson candidates collected from runs, de-duplicated, and drafted as lessons by a person.

scripts/wgf_knowledge/ingest.py (`wgf knowledge ingest`, `candidates`, `reject`) and
promote.py (`wgf knowledge promote`). These tests hold:

  * INGEST. A run's candidates - quality-report, triage-report, prototype-report
    specialist, review-report - reach workspace/lessons/candidates.yaml schema-valid, with
    the run, the report by id, version and digest, the build commit and the reporter.
  * REFUSED. A candidate without a summary or a root cause, or outside its schema, is
    refused and nothing is written (exit 1); a malformed run store is unusable (exit 2).
  * DEDUPE. A candidate whose check an active lesson holds is that lesson's regression
    observation; the same summary and check from another run is another source of one
    candidate; the same report ingested twice changes nothing.
  * PROMOTE. A candidate is drafted as a PR-ready patch - the lessons.yaml entry, the
    evidence.yaml entry, the test stubs - that applies and passes the model's rules; nothing
    is written to core/. Subjective evidence (a review's comment) is never drafted blocking
    or required.

    python -m unittest scripts.tests.test_knowledge_ingest
"""

import contextlib
import io
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
for entry in (SCRIPTS, HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import knowledge_runs as kr  # noqa: E402
from wgf_knowledge import cli, ingest, model, promote  # noqa: E402
from wgf_quality import registry  # noqa: E402
from wgflib.yamllite import load as load_yaml  # noqa: E402

NEW_CHECK = "browser-qa:browser.pause-resume"      # quality tier, held by no lesson
HARD_CHECK = "browser-qa:browser.page-errors"      # hard tier, held by no lesson
HELD_CHECK = "browser-qa:browser.context-menu"     # held by L25 (active)


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-k4-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.store = kr.make_store(os.path.join(self.tmp, "store"))
        self.candidates = os.path.join(self.tmp, "candidates.yaml")

    def ingest(self, run_id, *extra):
        return run_cli("ingest", run_id, "--store", self.store.directory,
                       "--candidates", self.candidates, "--json", *extra)

    def stored(self):
        return ingest.load_store(self.candidates)


class Ingest(Base):
    def test_a_candidate_from_a_quality_report_is_stored_with_its_source(self):
        run = kr.add_run(self.store, "run-a")
        found = kr.candidate(proposed_check=NEW_CHECK, finding="f-1", role="ui",
                             symptom="The pause overlay stayed after resume on the tablet",
                             systemic={"value": True, "why": "no gate resumes after pausing"})
        ref = kr.add_report(self.store, run, "quality-report", kr.quality_report([found]))
        code, out, _ = self.ingest("run-a")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["added"], ["C-1"])
        doc = self.stored()
        self.assertEqual(ingest.store_problems(doc), [])
        record = doc["candidates"][0]
        self.assertEqual((record["id"], record["state"], record["basis"]), ("C-1", "open", "measured"))
        self.assertEqual(record["symptom"], found["symptom"])
        self.assertEqual(record["systemic"], found["systemic"])
        source = record["sources"][0]
        self.assertEqual((source["run"], source["artifact_id"], source["artifact_type"],
                          source["version"]), ("run-a", "quality-report", "quality-report", 1))
        self.assertEqual(source["report_hash"], ref.checksum)
        self.assertEqual(source["content_hash"], "sha256:" + "b" * 64)
        self.assertEqual(source["commit"], kr.COMMIT)
        self.assertEqual(source["role"], "ui")
        # The file is YAML the Factory reads, and says what it is.
        with open(self.candidates, encoding="utf-8") as handle:
            text = handle.read()
        self.assertTrue(text.startswith("# Lesson candidates"))
        self.assertEqual(load_yaml(text)["candidates"][0]["id"], "C-1")

    def test_every_producer_of_candidates_is_read(self):
        run = kr.add_run(self.store, "run-b")
        kr.add_report(self.store, run, "prototype-report",
                      kr.prototype_report([kr.candidate("A: the spec", finding="f-2")]))
        kr.add_report(self.store, run, "triage-report",
                      kr.triage_report([kr.candidate("B: the triage")]))
        kr.add_report(self.store, run, "review-report",
                      kr.review_report([kr.candidate("C: the review", finding="f-3")]))
        code, out, _ = self.ingest("run-b")
        self.assertEqual(code, 0, out)
        records = {r["summary"]: r for r in self.stored()["candidates"]}
        self.assertEqual(sorted(records), ["A: the spec", "B: the triage", "C: the review"])
        self.assertEqual(records["A: the spec"]["basis"], "measured")
        self.assertEqual(records["A: the spec"]["sources"][0]["commit"], kr.COMMIT)
        # Without a finding it measured, a candidate is a judgment ...
        self.assertEqual(records["B: the triage"]["basis"], "subjective")
        # ... and a reviewer's is always one, whatever it names.
        self.assertEqual(records["C: the review"]["basis"], "subjective")

    def test_a_candidate_without_summary_or_root_cause_is_refused(self):
        run = kr.add_run(self.store, "run-c")
        kr.add_report(self.store, run, "quality-report", kr.quality_report([
            kr.candidate("Fine"), {"summary": "No cause given"}]))
        code, out, _ = self.ingest("run-c")
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertFalse(result["written"])
        self.assertTrue(any("root_cause" in p for p in result["problems"]), result["problems"])
        self.assertFalse(os.path.exists(self.candidates))

    def test_a_candidate_outside_its_schema_is_refused(self):
        run = kr.add_run(self.store, "run-d")
        kr.add_report(self.store, run, "quality-report", kr.quality_report([
            kr.candidate(proposed_level="mandatory"), kr.candidate("x", invented=True)]))
        code, out, _ = self.ingest("run-d")
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(out)["problems"]), 2)
        self.assertFalse(os.path.exists(self.candidates))

    def test_a_malformed_run_store_is_unusable_exit_2(self):
        run = kr.add_run(self.store, "run-e")
        ref = kr.add_report(self.store, run, "quality-report", kr.quality_report([kr.candidate()]))
        path = os.path.join(self.store.run_dir("run-e"), *ref.location.split("/"))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"lesson_candidates": [')          # truncated JSON
        self.assertEqual(self.ingest("run-e")[0], 2)
        # Wrong types: candidates that are not a list.
        other = kr.add_run(self.store, "run-f")
        kr.add_report(self.store, other, "triage-report", {"lesson_candidates": {"a": 1}})
        self.assertEqual(self.ingest("run-f")[0], 2)
        # A report that is not an object.
        third = kr.add_run(self.store, "run-g")
        kr.add_report(self.store, third, "quality-report", ["not", "a", "report"])
        self.assertEqual(self.ingest("run-g")[0], 2)
        # A state.json that is not one, and a run that does not exist.
        with open(os.path.join(self.store.run_dir("run-g"), "state.json"), "w") as handle:
            handle.write("{")
        self.assertEqual(self.ingest("run-g")[0], 2)
        self.assertEqual(self.ingest("no-such-run")[0], 2)
        self.assertFalse(os.path.exists(self.candidates))


class Dedupe(Base):
    def test_a_candidate_whose_check_an_active_lesson_holds_is_a_regression_observation(self):
        run = kr.add_run(self.store, "run-r")
        kr.add_report(self.store, run, "quality-report", kr.quality_report([
            kr.candidate("Right click opens the menu again", proposed_check=HELD_CHECK)]))
        code, out, _ = self.ingest("run-r")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["regressions"], ["L25"])
        doc = self.stored()
        self.assertEqual(doc["candidates"], [])
        self.assertEqual(doc["regressions"][0]["lesson"], "L25")
        self.assertEqual(doc["regressions"][0]["source"]["run"], "run-r")
        self.assertEqual(ingest.store_problems(doc), [])
        # Ingested again: nothing new.
        self.assertEqual(json.loads(self.ingest("run-r")[1])["unchanged"], 1)
        self.assertEqual(len(self.stored()["regressions"]), 1)

    def test_the_same_summary_and_check_merge_sources(self):
        first = kr.add_run(self.store, "run-1")
        kr.add_report(self.store, first, "quality-report", kr.quality_report([
            kr.candidate("Pause leaves the overlay up.", proposed_check=NEW_CHECK)]))
        second = kr.add_run(self.store, "run-2")
        kr.add_report(self.store, second, "review-report", kr.review_report([
            kr.candidate("  pause LEAVES the overlay up ", proposed_check=NEW_CHECK)]))
        self.assertEqual(self.ingest("run-1")[0], 0)
        code, out, _ = self.ingest("run-2")
        self.assertEqual((code, json.loads(out)["merged"]), (0, ["C-1"]))
        doc = self.stored()
        self.assertEqual(len(doc["candidates"]), 1)
        self.assertEqual([s["run"] for s in doc["candidates"][0]["sources"]], ["run-1", "run-2"])
        # A measured source keeps the candidate measured.
        self.assertEqual(doc["candidates"][0]["basis"], "subjective")
        # The same report twice changes nothing, byte for byte.
        with open(self.candidates, "rb") as handle:
            before = handle.read()
        code, out, _ = self.ingest("run-2")
        self.assertEqual((code, json.loads(out)["unchanged"]), (0, 1))
        with open(self.candidates, "rb") as handle:
            self.assertEqual(handle.read(), before)
        # Another check is another candidate.
        third = kr.add_run(self.store, "run-3")
        kr.add_report(self.store, third, "quality-report", kr.quality_report([
            kr.candidate("Pause leaves the overlay up.", proposed_check=HARD_CHECK)]))
        self.assertEqual(json.loads(self.ingest("run-3")[1])["added"], ["C-2"])

    def test_a_check_a_candidate_lesson_names_marks_the_duplicate(self):
        lessons = {"lessons": [{"id": "L90", "lifecycle": "candidate", "checks": [NEW_CHECK]}]}
        observation = {"candidate": kr.candidate(proposed_check=NEW_CHECK),
                       "source": {"run": "r", "artifact_id": "q", "artifact_type": "quality-report",
                                  "version": 1, "report_hash": "sha256:" + "c" * 64,
                                  "basis": "measured"}}
        doc, summary = ingest.ingest(ingest.empty_store(), [observation], lessons)
        self.assertEqual(summary["added"], ["C-1"])
        self.assertEqual(doc["candidates"][0]["duplicate_of"], "L90")

    def test_a_person_rejects_a_candidate_and_it_is_kept(self):
        run = kr.add_run(self.store, "run-x")
        kr.add_report(self.store, run, "quality-report", kr.quality_report([kr.candidate()]))
        self.ingest("run-x")
        self.assertEqual(run_cli("reject", "C-1", "--reason", "too short",
                                 "--candidates", self.candidates)[0], 2)
        code, _, _ = run_cli("reject", "C-1", "--reason", "a build mistake, not the Factory's",
                             "--by", "Ada Lovelace", "--candidates", self.candidates)
        self.assertEqual(code, 0)
        record = self.stored()["candidates"][0]
        self.assertEqual(record["state"], "rejected")
        self.assertEqual(record["rejected"]["by"], "Ada Lovelace")
        self.assertEqual(ingest.store_problems(self.stored()), [])
        code, out, _ = run_cli("promote", "C-1", "--candidates", self.candidates)
        self.assertEqual(code, 1)
        self.assertIn("rejected", out)


class Promote(Base):
    def setUp(self):
        super().setUp()
        self.data = registry.load(ROOT)
        self.checks, _ = registry.classify(self.data["tiers"], ROOT)
        self.vocab = model.vocabulary(ROOT)
        with open(os.path.join(ROOT, *promote.LESSONS_PATH.split("/")), encoding="utf-8") as h:
            self.lessons_text = h.read()
        with open(os.path.join(ROOT, *promote.EVIDENCE_PATH.split("/")), encoding="utf-8") as h:
            self.evidence_text = h.read()

    def record(self, basis="measured", **extra):
        source = {"run": "run-a", "artifact_id": "quality-report",
                  "artifact_type": "review-report" if basis == "subjective" else "quality-report",
                  "version": 1, "report_hash": "sha256:" + "d" * 64, "commit": kr.COMMIT,
                  "basis": basis, "date": "2026-10-08T10:00:00Z"}
        out = {"id": "C-7", "state": "open", "key": "k", "basis": basis, "duplicate_of": None,
               "summary": "A paused game was never resumed by any gate, so an overlay that "
                          "stays after resume passed",
               "symptom": "The pause overlay stayed up after resume.",
               "root_cause": "Gates pause the game but never resume it and look again.",
               "systemic": {"value": True}, "proposed_check": NEW_CHECK,
               "proposed_level": None, "proposed_scope": None, "rejected": None,
               "sources": [source]}
        out.update(extra)
        return out

    def draft(self, record, **kw):
        return promote.draft(record, self.data["lessons"], self.lessons_text, self.evidence_text,
                             self.checks, self.vocab, evidence=self.data["evidence"], **kw)

    def test_a_measured_candidate_is_drafted_as_a_patch_that_applies_and_holds(self):
        result = self.draft(self.record(), today="2026-10-08")
        lesson = result.lesson
        self.assertEqual((lesson["status"], lesson["lifecycle"], lesson["checks"]),
                         ("enforced", "active", [NEW_CHECK]))
        self.assertEqual(model.derive_level(lesson, self.checks), "required")
        self.assertNotIn("level", lesson)
        self.assertEqual(result.evidence["candidate"], "C-7")
        stub = f"scripts/tests/test_lesson_{lesson['id'].lower()}.py"
        self.assertIn(stub, result.files)
        self.assertIn(f"{stub}::test_{lesson['id']}_the_check_fails_the_defect",
                      lesson["tests"]["catches"])
        self.assertIn("diff --git a/core/reference/lessons.yaml", result.patch)
        self.assertIn("+version: 2.1.0", result.patch)
        # The patch applies to the files as they are, and the result holds the model's rules
        # - stub tests included, which exist and fail until a person writes them.
        work = os.path.join(self.tmp, "repo")
        for path in (promote.LESSONS_PATH, promote.EVIDENCE_PATH):
            os.makedirs(os.path.dirname(os.path.join(work, path)), exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, path), os.path.join(work, path))
        patch = os.path.join(self.tmp, "draft.patch")
        with open(patch, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(result.patch)
        applied = subprocess.run(["git", "apply", "--unsafe-paths", "--directory", ".", patch],
                                 cwd=work, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        for path, text in result.files.items():
            with open(os.path.join(work, path), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), text)
        with open(os.path.join(work, promote.LESSONS_PATH), encoding="utf-8") as handle:
            after = load_yaml(handle.read())
        with open(os.path.join(work, promote.EVIDENCE_PATH), encoding="utf-8") as handle:
            evidence = load_yaml(handle.read())
        self.assertEqual(after["lessons"][-1], lesson)
        self.assertEqual(evidence["lessons"][lesson["id"]]["candidate"], "C-7")
        found = [p for p in model.lesson_problems(after, self.checks, self.vocab, evidence)
                 + registry.lesson_problems(after, self.checks, work, evidence)
                 if lesson["id"] in p]
        self.assertEqual(found, [])
        # The stubs are tests that fail - a promoted lesson cannot ship them green.
        from wgf_knowledge import firewall
        report = firewall.run({"lessons": [lesson]}, work)
        self.assertEqual(report["lessons"][0]["verdict"], firewall.FAIL)
        # And once applied, the candidate reads as promoted.
        self.assertEqual(ingest.promoted(evidence), {"C-7": lesson["id"]})
        with self.assertRaises(promote.PromoteRefused):
            promote.draft(self.record(), after, "", "", self.checks, self.vocab,
                          promoted=ingest.promoted(evidence))

    def test_a_stronger_proposal_is_declared_and_a_weaker_one_refused(self):
        self.assertEqual(self.draft(self.record(proposed_level="blocking")).lesson["level"],
                         "blocking")
        with self.assertRaisesRegex(promote.PromoteRefused, "cannot declare it weaker"):
            self.draft(self.record(proposed_check=HARD_CHECK, proposed_level="required"))

    def test_subjective_evidence_is_never_drafted_blocking_or_required(self):
        for level in ("blocking", "required"):
            with self.subTest(level=level):
                with self.assertRaisesRegex(promote.PromoteRefused, "subjective"):
                    self.draft(self.record(basis="subjective", proposed_level=level))
                with self.assertRaisesRegex(promote.PromoteRefused, "subjective"):
                    self.draft(self.record(basis="subjective"), level=level)
        # Drafted at all, a review's comment is a candidate lesson: experimental, never blocks.
        lesson = self.draft(self.record(basis="subjective")).lesson
        self.assertEqual((lesson["status"], lesson["lifecycle"]), ("gap", "candidate"))
        self.assertNotIn("checks", lesson)
        self.assertIn(NEW_CHECK, lesson["gap"])
        self.assertEqual(model.derive_level(lesson, self.checks), "experimental")

    def test_the_cli_refuses_blocking_for_subjective_only_evidence(self):
        run = kr.add_run(self.store, "run-s")
        kr.add_report(self.store, run, "review-report", kr.review_report([
            kr.candidate("Reviewers think the HUD font is too thin for phones",
                         root_cause="No gate reads text legibility on phones",
                         proposed_check=NEW_CHECK, proposed_level="blocking", finding="f-9")]))
        self.assertEqual(self.ingest("run-s")[0], 0)
        code, out, _ = run_cli("promote", "C-1", "--candidates", self.candidates)
        self.assertEqual(code, 1)
        self.assertIn("subjective", out)
        code, out, err = run_cli("promote", "C-1", "--candidates", self.candidates,
                                 "--level", "experimental", "--category", "ui_ux")
        self.assertEqual(code, 0, out + err)
        self.assertIn("+    status: gap", out)
        self.assertIn("nothing was written to core/", err)

    def test_not_systemic_and_uncategorised_are_refused(self):
        with self.assertRaisesRegex(promote.PromoteRefused, "not systemic"):
            self.draft(self.record(systemic={"value": False, "why": "a typo in one level"}))
        with self.assertRaisesRegex(promote.PromoteRefused, "category"):
            self.draft(self.record(proposed_check="nothing:holds-it"))
        with self.assertRaisesRegex(promote.PromoteRefused, "not classified"):
            self.draft(self.record(proposed_check="nothing:holds-it", proposed_level="required"),
                       category="ui_ux")

    def test_promote_never_writes_core(self):
        before = {p: open(os.path.join(ROOT, p), "rb").read()
                  for p in (promote.LESSONS_PATH, promote.EVIDENCE_PATH)}
        run = kr.add_run(self.store, "run-w")
        kr.add_report(self.store, run, "quality-report", kr.quality_report([
            kr.candidate(proposed_check=NEW_CHECK, finding="f-1")]))
        self.ingest("run-w")
        out_file = os.path.join(self.tmp, "c1.patch")
        code, _, err = run_cli("promote", "C-1", "--candidates", self.candidates,
                               "--out", out_file)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.getsize(out_file) > 0)
        for path, data in before.items():
            with open(os.path.join(ROOT, path), "rb") as handle:
                self.assertEqual(handle.read(), data)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "scripts", "tests",
                                                     "test_lesson_l29.py")))


if __name__ == "__main__":
    unittest.main()
