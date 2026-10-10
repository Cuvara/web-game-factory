"""K6.4: a lesson's evidence strength, derived from the finding ledger - never self-confirmed.

scripts/wgf_knowledge/strength.py (core/reference/evidence-strength.yaml), as `wgf knowledge
ingest` records it (ingest.py) and `wgf knowledge promote` caps a draft by it (promote.py).
These tests hold:

  * LEVELS. hypothesis (a claim; a measured failure never re-measured), single-run (one
    FAIL->PASS pair - also on REAL bot records: the 3D validation game's naive.pace, FAIL on
    1c6b099 and PASS on c340631), reproduced (the pass repeated in a later report),
    validated (reproduced in two runs, or on other builds - desktop and mobile of one run
    and build are one context).
  * CAPS. A check whose ledger alternates verdicts is `unstable` and capped at single-run; so
    is a pair measured only by the game's own probe (self-reported), one AI judgment, or a
    check of no known class.
  * CIRCULARITY. Each refused, with its rule and reason recorded: (a) the detecting report
    counted again, (b) the lesson's own proposed check on a build that motivated it, (c) a
    pass on the failing commit, (d) a judge re-reading a build or frames it judged, (e) a
    claim; hash-identical duplicates count once.
  * INGEST -> PROMOTE. The candidate records `strength`, `strength_why`, `refused_evidence`
    and `unstable`, refreshed when its run is ingested again; promote derives it again from
    the run store and never drafts a classification beyond it - while BLOCKING and REQUIRED
    stay the check tiers' (K4).

The ledgers are made by the REAL triage step from playability reports the playability step's
own path judges over FIXTURE bot records (scripts/tests/learning_ledgers.py), except the
naive.pace one (REAL records). A few cases a real ledger cannot reach (a ledger counting its
detecting report again, a nondeterministic same-commit pass) are a real ledger EDITED to show
it, and say so.

    python -m unittest scripts.tests.test_knowledge_strength
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import knowledge_runs as kr  # noqa: E402
import learning_ledgers as ll  # noqa: E402
from wgf_knowledge import ingest, model, promote, strength  # noqa: E402
from wgf_quality import registry  # noqa: E402
from wgflib.yamllite import load as load_yaml  # noqa: E402

A, B, C, D, E = ("a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40)
NO_LESSONS = {"lessons": []}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wgf-k64-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.store = kr.make_store(os.path.join(self.tmp, "store"))
        self.n = 0

    def rounds(self, builds, producer="playability-report", design=None):
        self.n += 1
        rounds = ll.Rounds(os.path.join(self.tmp, f"run-dir-{self.n}"), design)
        rounds.play(builds, producer)
        return rounds

    def put(self, run_id, rounds, candidates, **kw):
        return ll.store_run(self.store, run_id, rounds, candidates, **kw)

    def ingest(self, *run_ids, doc=None, lessons=NO_LESSONS):
        doc = doc or ingest.empty_store()
        summary = None
        for run_id in run_ids:
            state = self.store.load(run_id)
            observations, problems = ingest.extract(
                state, lambda ref, s=state: self.store.read_artifact(s.run_id, ref))
            self.assertEqual(problems, [])
            doc, summary = ingest.ingest(doc, observations, lessons)
        self.assertEqual(ingest.store_problems(doc), [])
        return doc, summary

    def one(self, *run_ids, **kw):
        doc, _ = self.ingest(*run_ids, **kw)
        self.assertEqual(len(doc["candidates"]), 1, [c["key"] for c in doc["candidates"]])
        return doc["candidates"][0]

    def rules(self, record):
        return sorted({r["rule"] for r in record.get("refused_evidence") or []})


# ------------------------------------------------------------------------------- levels


class Levels(Base):
    def test_the_vocabulary_in_core_is_the_one_the_code_derives(self):
        with open(os.path.join(ROOT, *strength.VOCABULARY_FILE.split("/")),
                  encoding="utf-8") as handle:
            vocabulary = load_yaml(handle.read())
        self.assertEqual(strength.problems(vocabulary), [])
        broken = copy.deepcopy(vocabulary)
        broken["levels"][1]["ceiling"] = "RECOMMENDATION"
        self.assertTrue(strength.problems(broken))
        broken = copy.deepcopy(vocabulary)
        del broken["refusals"]["own-check"]
        self.assertTrue(strength.problems(broken))

    def test_a_claim_is_a_hypothesis(self):
        """A reviewer's candidate (a judgment), and one naming no finding, measure nothing."""
        rounds = self.rounds([(A, ll.blind()), (B, ll.well())])
        run = kr.add_run(self.store, "run-claim")
        kr.add_report(self.store, run, "review-report",
                      kr.review_report([ll.candidate(ll.OBJECTIVE)], commit=A))
        kr.add_report(self.store, run, "triage-report", rounds.triages[-1])
        record = self.one("run-claim")
        self.assertEqual(record["strength"], "hypothesis")
        self.assertEqual(self.rules(record), ["claim"])
        self.assertIn("a claim, not a measurement", record["refused_evidence"][0]["reason"])

    def test_a_measured_failure_never_remeasured_is_a_hypothesis(self):
        rounds = self.rounds([(A, ll.blind())])
        self.put("run-open", rounds, [ll.candidate(ll.OBJECTIVE)])
        record = self.one("run-open")
        self.assertEqual(record["basis"], "measured")
        self.assertEqual(record["strength"], "hypothesis")
        self.assertEqual(self.rules(record), ["no-repair"])

    def test_one_fail_pass_pair_is_single_run(self):
        rounds = self.rounds([(A, ll.blind()), (B, ll.well())])
        self.put("run-1", rounds, [ll.candidate(ll.OBJECTIVE)])
        record = self.one("run-1")
        self.assertEqual(record["strength"], "single-run", record["strength_why"])
        source = record["sources"][0]["remeasurement"]
        self.assertEqual((source["before"]["commit"], source["after"]["commit"]), (A, B))
        self.assertEqual((source["class"], source["check"]),
                         ("heuristic", "playability:start.objective"))
        self.assertIn("not repeated", record["strength_why"])

    def test_real_naive_pace_repair_is_single_run(self):
        """REAL bot records: the 3D game's regressed head fails naive.pace, its repair passes
        - one measured pair, never repeated: single-run, however real."""
        run_dir = os.path.join(self.tmp, "real")
        reports = ll.real_naive_pace(run_dir)
        (bad, failing), (good, passing) = sorted(reports.items())
        self.assertIn("desktop:naive.pace", failing["failed_checks"])
        rounds = ll.Rounds(run_dir, ll.tt.DESIGN_3D)
        ledger = rounds.play([(bad, failing), (good, passing)])
        self.assertEqual(ledger[ll.NAIVE_PACE]["verification"]["verdict"], "passed")
        self.put("run-real", rounds, [ll.candidate(ll.NAIVE_PACE)])
        record = self.one("run-real")
        self.assertEqual(record["strength"], "single-run", record["strength_why"])
        snap = record["sources"][0]["remeasurement"]
        self.assertEqual((snap["check"], snap["class"]), ("play-realism:naive.pace", "heuristic"))
        self.assertEqual((snap["before"]["commit"][:7], snap["after"]["commit"][:7]),
                         ("1c6b099", "c340631"))

    def test_a_pass_repeated_in_a_later_report_is_reproduced(self):
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        self.put("run-r", rounds, [ll.candidate(ll.OBJECTIVE)])
        record = self.one("run-r")
        self.assertEqual(record["strength"], "reproduced", record["strength_why"])
        self.assertIn("1 later independent measurement", record["strength_why"])
        self.assertEqual(record["refused_evidence"], [])

    def test_desktop_and_mobile_of_one_run_and_one_build_are_one_context(self):
        """Review r1 finding 4 (was test_reproduced_on_desktop_and_mobile_is_validated):
        desktop and mobile of the same run, failing on A and passing on B and C, are two
        viewports of one repair measured by one bot - not two independent contexts. A
        validated context differs in run or commit; this is reproduced."""
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        self.put("run-v", rounds, [[ll.candidate(ll.OBJECTIVE)],
                                   [ll.candidate(ll.OBJECTIVE_MOBILE)]])
        record = self.one("run-v")
        self.assertEqual(record["strength"], "reproduced", record["strength_why"])
        self.assertIn("one run and build", record["strength_why"])

    def test_desktop_and_mobile_in_two_runs_are_validated(self):
        first = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        second = self.rounds([(C, ll.blind()), (D, ll.well()), (E, ll.well())])
        self.put("run-1", first, [ll.candidate(ll.OBJECTIVE)])
        self.put("run-2", second, [ll.candidate(ll.OBJECTIVE_MOBILE)])
        record = self.one("run-1", "run-2")
        self.assertEqual(record["strength"], "validated", record["strength_why"])
        self.assertIn("start.objective@desktop", record["strength_why"])
        self.assertIn("start.objective@mobile", record["strength_why"])

    def test_reproduced_in_two_runs_is_validated(self):
        first = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        second = self.rounds([(C, ll.blind()), (D, ll.well()), (E, ll.well())])
        self.put("run-1", first, [ll.candidate(ll.OBJECTIVE)])
        self.put("run-2", second, [ll.candidate(ll.OBJECTIVE)])
        record = self.one("run-1", "run-2")
        self.assertEqual(len(record["sources"]), 2)
        self.assertEqual(record["strength"], "validated", record["strength_why"])

    def test_one_context_reproduced_and_another_single_is_not_validated(self):
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        once = self.rounds([(C, ll.blind()), (D, ll.well())])
        self.put("run-1", rounds, [ll.candidate(ll.OBJECTIVE)])
        self.put("run-2", once, [ll.candidate(ll.OBJECTIVE)])
        self.assertEqual(self.one("run-1", "run-2")["strength"], "reproduced")


# --------------------------------------------------------------------------------- caps


class Caps(Base):
    def test_an_unstable_check_is_capped_at_single_run(self):
        """FAIL, PASS, FAIL, PASS, PASS: the pass repeats, but the check alternates - the
        retro's depth.ramp (7 flips in 15 reports) - so it is capped and marked unstable."""
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.blind()),
                              (D, ll.well()), (E, ll.well())])
        self.put("run-u", rounds, [ll.candidate(ll.OBJECTIVE)])
        record = self.one("run-u")
        self.assertEqual(record["unstable"], [ll.OBJECTIVE])
        self.assertEqual(record["strength"], "single-run", record["strength_why"])
        self.assertIn("unstable", record["strength_why"])
        self.assertIn("flipped 3 time(s)", record["strength_why"])

    def test_a_same_commit_fail_and_pass_is_unstable(self):
        """A ledger EDITED to show what the retro saw on the 3D game (v8 and v9 measured one
        build and disagreed): a failure and a pass recorded on the same commit."""
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        record = next(r for r in rounds.triages[-1]["lifecycle"] if r["id"] == ll.OBJECTIVE)
        snap = strength.snapshot(record, None, ingest.default_classifier())
        snap["outcomes"].append({"verdict": "FAIL", "commit": C})
        snap["outcomes"].append({"verdict": "PASS", "commit": C})
        found = strength.derive([{"basis": "measured", "run": "r", "report_hash": "x",
                                  "finding": ll.OBJECTIVE, "commit": A,
                                  "remeasurement": snap}])
        self.assertEqual(found["strength"], "single-run")
        self.assertEqual(found["unstable"], [ll.OBJECTIVE])
        # Without the edit the same ledger is reproduced.
        clean = strength.snapshot(record, None, ingest.default_classifier())
        self.assertEqual(strength.derive([{"basis": "measured", "run": "r",
                                           "report_hash": "x", "finding": ll.OBJECTIVE,
                                           "commit": A, "remeasurement": clean}])["strength"],
                         "reproduced")

    def test_self_reported_only_is_capped_at_single_run(self):
        """restart.works is read from the game's own probe: repeated passes are still the
        game's word."""
        rounds = self.rounds([(A, ll.dead()), (B, ll.well()), (C, ll.well())])
        self.put("run-s", rounds, [ll.candidate(ll.RESTART)])
        record = self.one("run-s")
        snap = record["sources"][0]["remeasurement"]
        self.assertEqual(snap["class"], "self-reported")
        self.assertEqual(len([s for s in snap["samples"]]), 2)
        self.assertEqual(record["strength"], "single-run", record["strength_why"])
        self.assertIn("self-reported", record["strength_why"])

    def test_one_ai_judgment_is_single_run_and_two_on_other_builds_reproduce(self):
        once = self.rounds([(A, ll.judged(2, A, 1)), (B, ll.judged(4, B, 2))],
                           producer="visual-qa-report")
        self.put("run-j1", once, [ll.candidate(ll.ENVIRONMENT)])
        record = self.one("run-j1")
        self.assertEqual(record["sources"][0]["remeasurement"]["class"], "ai-judged")
        self.assertEqual(record["strength"], "single-run")
        self.assertIn("single-judge", record["strength_why"])
        twice = self.rounds([(A, ll.judged(2, A, 1)), (B, ll.judged(4, B, 2)),
                             (C, ll.judged(4, C, 3))], producer="visual-qa-report")
        self.put("run-j2", twice, [ll.candidate(ll.ENVIRONMENT)])
        doc, _ = self.ingest("run-j2")
        self.assertEqual(doc["candidates"][0]["strength"], "reproduced",
                         doc["candidates"][0]["strength_why"])

    def test_a_check_of_no_known_class_is_capped(self):
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        self.put("run-k", rounds, [ll.candidate(ll.OBJECTIVE)])
        state = self.store.load("run-k")
        observations, _ = ingest.extract(state, lambda ref: self.store.read_artifact(
            "run-k", ref), classify=lambda producer, check: (None, None))
        doc, _ = ingest.ingest(ingest.empty_store(), observations, NO_LESSONS)
        record = doc["candidates"][0]
        self.assertEqual(record["strength"], "single-run")
        self.assertIn("unknown-class", record["strength_why"])


# ------------------------------------------------------------------------- circularity


class Circularity(Base):
    def test_a_the_detecting_report_counted_again_is_refused(self):
        """A ledger EDITED so its verification's pass is the report that detected the
        finding (no real ledger does this; the guard must hold if one ever did)."""
        rounds = self.rounds([(A, ll.blind()), (B, ll.well())])
        triage = copy.deepcopy(rounds.triages[-1])
        record = next(r for r in triage["lifecycle"] if r["id"] == ll.OBJECTIVE)
        verification = record["verification"]
        verification["after"]["content_hash"] = verification["before"]["content_hash"]
        self.put("run-a", rounds, [ll.candidate(ll.OBJECTIVE)],
                 triages=rounds.triages[:-1] + [triage])
        record = self.one("run-a")
        self.assertEqual(record["strength"], "hypothesis")
        self.assertEqual(self.rules(record), ["same-report"])
        self.assertIn("detected it", record["refused_evidence"][0]["reason"])

    def test_a_a_sample_that_is_the_detecting_report_is_refused(self):
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        triage = copy.deepcopy(rounds.triages[-1])
        record = next(r for r in triage["lifecycle"] if r["id"] == ll.OBJECTIVE)
        verification = record["verification"]
        verification["samples"][-1]["content_hash"] = verification["before"]["content_hash"]
        self.put("run-a2", rounds, [ll.candidate(ll.OBJECTIVE)],
                 triages=rounds.triages[:-1] + [triage])
        record = self.one("run-a2")
        self.assertEqual(record["strength"], "single-run")
        self.assertEqual(self.rules(record), ["same-report"])

    def test_b_the_lessons_own_check_on_the_build_that_motivated_it_is_refused(self):
        """The candidate came from restart.works failing on A; it proposes start.objective,
        and start.objective measured on that same build A (and its fix) is offered as more
        evidence. It was written from that build: refused. The candidate keeps only the
        raising check's pair (self-reported: single-run)."""
        both = ll.blind()
        both["lose"] = ll.dead()["lose"]
        rounds = self.rounds([(A, both), (B, ll.well()), (C, ll.well())])
        own = "playability:start.objective"
        self.put("run-b", rounds, [[ll.candidate(ll.RESTART, proposed_check=own)],
                                   [ll.candidate(ll.OBJECTIVE, proposed_check=own)]])
        record = self.one("run-b")
        self.assertEqual(self.rules(record), ["own-check"])
        refused = record["refused_evidence"][0]
        self.assertEqual(refused["finding"], ll.OBJECTIVE)
        self.assertIn("the lesson's own proposed check", refused["reason"])
        self.assertEqual(record["strength"], "single-run", record["strength_why"])

    def test_b_the_own_check_on_another_game_counts(self):
        """The same proposed check measured on builds no other source saw the defect on - a
        second game - is independent evidence."""
        first = self.rounds([(A, ll.dead()), (B, ll.well()), (C, ll.well())])
        second = self.rounds([(D, ll.blind()), (E, ll.well()), ("f" * 40, ll.well())])
        own = "playability:start.objective"
        self.put("run-1", first, [ll.candidate(ll.RESTART, proposed_check=own)])
        self.put("run-2", second, [ll.candidate(ll.OBJECTIVE, proposed_check=own)])
        record = self.one("run-1", "run-2")
        self.assertEqual(self.rules(record), [])
        self.assertEqual(record["strength"], "reproduced", record["strength_why"])

    def test_c_a_pass_on_the_failing_commit_is_refused(self):
        rounds = self.rounds([(A, ll.blind()), (A, ll.well())])
        self.put("run-c", rounds, [ll.candidate(ll.OBJECTIVE)])
        record = self.one("run-c")
        snap = record["sources"][0]["remeasurement"]
        self.assertEqual(snap["verdict"], "same-build")
        self.assertEqual((record["strength"], self.rules(record)), ("hypothesis", ["same-build"]))

    def test_c_a_later_replay_of_the_failing_build_does_not_reproduce(self):
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (A, ll.well())])
        self.put("run-c2", rounds, [ll.candidate(ll.OBJECTIVE)])
        record = self.one("run-c2")
        self.assertEqual(record["strength"], "single-run", record["strength_why"])
        self.assertEqual(self.rules(record), ["same-build"])

    def test_c_a_repeat_on_the_build_that_passed_is_not_independent(self):
        """Review r1 finding 4: the pass on B played again on B is a re-play of the same
        build by the same bot - not an independent repeat. It is refused (same-build) and
        the pair stays single-run."""
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (B, ll.well())])
        self.put("run-c3", rounds, [ll.candidate(ll.OBJECTIVE)])
        record = self.one("run-c3")
        samples = record["sources"][0]["remeasurement"]["samples"]
        self.assertEqual([x["commit"] for x in samples], [B, B])
        self.assertEqual(record["strength"], "single-run", record["strength_why"])
        self.assertEqual(self.rules(record), ["same-build"])
        self.assertIn("re-play of the build that passed", record["refused_evidence"][0]["reason"])

    def test_d_a_judge_rereading_a_build_it_judged_is_refused(self):
        """The judge ran again on the build it already passed (another report, another
        hash): its own verdict again, not a second judgment."""
        rounds = self.rounds([(A, ll.judged(2, A, 1)), (B, ll.judged(4, B, 2)),
                              (B, ll.judged(4, B, 3))], producer="visual-qa-report")
        self.put("run-d", rounds, [ll.candidate(ll.ENVIRONMENT)])
        record = self.one("run-d")
        self.assertEqual(self.rules(record), ["self-agreement"])
        self.assertEqual(record["strength"], "single-run")

    def test_d_a_judge_rereading_the_same_frames_on_another_build_is_refused(self):
        """SYNTHETIC: today's ledger keeps no frames for a judge's report (visual-qa is not a
        producer that lists its checks), so a real ledger cannot show this. A real visual-qa
        ledger's re-measurement, EDITED to carry the frame digests each judgment read: a
        second judgment of the same frames on another commit is the first one again."""
        rounds = self.rounds([(A, ll.judged(2, A, 1)), (B, ll.judged(4, B, 2)),
                              (C, ll.judged(4, C, 3))], producer="visual-qa-report")
        record = next(r for r in rounds.triages[-1]["lifecycle"] if r["id"] == ll.ENVIRONMENT)
        snap = strength.snapshot(record, None, ingest.default_classifier())
        source = {"basis": "measured", "run": "r", "report_hash": "x", "commit": A,
                  "finding": ll.ENVIRONMENT, "remeasurement": snap}
        self.assertEqual(strength.derive([source])["strength"], "reproduced")
        for measured in [snap["after"]] + snap["samples"]:
            measured["frames"] = ["sha256:" + "f" * 64]
        found = strength.derive([source])
        self.assertEqual(found["strength"], "single-run")
        self.assertEqual([r["rule"] for r in found["refused"]], ["self-agreement"])

    def test_e_a_claim_restating_the_lesson_does_not_count(self):
        """A reviewer restates the lesson beside a measured single-run pair: the review is a
        claim, recorded refused, and the strength stays the pair's."""
        rounds = self.rounds([(A, ll.blind()), (B, ll.well())])
        run = self.put("run-e", rounds, [ll.candidate(ll.OBJECTIVE)])
        kr.add_report(self.store, run, "review-report",
                      kr.review_report([ll.candidate(ll.OBJECTIVE)], commit=B))
        record = self.one("run-e")
        self.assertEqual(record["strength"], "single-run")
        self.assertEqual(self.rules(record), ["claim"])

    def test_hash_identical_duplicates_count_once(self):
        """The same run's reports copied byte for byte into another run: a second context in
        name only. Counted once - reproduced, never validated."""
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        self.put("run-1", rounds, [ll.candidate(ll.OBJECTIVE)])
        self.put("run-copy", rounds, [ll.candidate(ll.OBJECTIVE)])
        record = self.one("run-1", "run-copy")
        self.assertEqual(len(record["sources"]), 2)
        self.assertEqual(record["sources"][0]["report_hash"],
                         record["sources"][1]["report_hash"])
        self.assertEqual(record["strength"], "reproduced", record["strength_why"])
        self.assertEqual(self.rules(record), ["duplicate"])
        refused = record["refused_evidence"][0]
        self.assertEqual(refused["run"], "run-copy")
        self.assertIn("the same report (digest)", refused["reason"])

    def test_the_same_pair_reported_twice_counts_once(self):
        """Two reports of the same candidate on the same finding of one ledger: the pair is
        one measurement, offered twice."""
        rounds = self.rounds([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        self.put("run-2x", rounds, [[ll.candidate(ll.OBJECTIVE)],
                                    [ll.candidate(ll.OBJECTIVE, evidence_refs=["again"])]])
        record = self.one("run-2x")
        self.assertEqual(record["strength"], "reproduced")
        self.assertEqual(self.rules(record), ["duplicate"])

    def test_reingesting_the_same_report_changes_nothing(self):
        rounds = self.rounds([(A, ll.blind()), (B, ll.well())])
        self.put("run-1", rounds, [ll.candidate(ll.OBJECTIVE)])
        doc, _ = self.ingest("run-1")
        again, summary = self.ingest("run-1", doc=doc)
        self.assertEqual((summary["unchanged"], summary["refreshed"]), (1, []))
        self.assertEqual(again, doc)
        self.assertEqual(again["candidates"][0]["strength"], "single-run")


class ReviewProbe(unittest.TestCase):
    """Review r1's probe_strength.py, as pure derivations: (A) a sample on the commit that
    passed is not an independent repeat; (B) desktop and mobile of one run, one fix and one
    commit are one context; (C) another run is a second context."""

    @staticmethod
    def m(h, commit, seq, status, scenario):
        return {"artifact_id": f"pr-{seq}", "content_hash": "sha256:" + h * 64,
                "commit": commit, "seq": seq, "status": status, "scenario": scenario,
                "frames": []}

    def src(self, project, run="run-1", commits=(A, B), replay=None):
        failed, passed = commits
        before = self.m("1" if run == "run-1" else "4", failed, 8, "FAIL",
                        f"restart@{project}")
        after = self.m("2" if run == "run-1" else "5", passed, 13, "PASS", f"restart@{project}")
        again = self.m("3" if run == "run-1" else "6", replay or passed, 17, "PASS",
                       f"restart@{project}")
        snap = {"ledger": None, "finding": f"playability-report:act.acknowledged@{project}",
                "producer": "playability-report", "check": "playability:act.acknowledged",
                "check_id": "act.acknowledged", "project": project, "class": "deterministic",
                "status": "closed", "verdict": "passed", "before": before, "after": after,
                "same_scenario": True, "differences": [], "samples": [after, again],
                "detected": {"artifact_id": "pr-8", "content_hash": before["content_hash"],
                             "commit": failed},
                "outcomes": [{"verdict": "FAIL", "commit": failed},
                             {"verdict": "PASS", "commit": passed}]}
        return {"basis": "measured", "run": run, "finding": snap["finding"],
                "report_hash": "sha256:" + (project[0] + run[-1]) * 32,
                "artifact_type": "playability-report", "commit": failed,
                "remeasurement": snap}

    def test_a_a_replay_of_the_passing_commit_is_single_run(self):
        out = strength.derive([self.src("desktop")])
        self.assertEqual(out["strength"], "single-run", out["why"])
        self.assertEqual([r["rule"] for r in out["refused"]], ["same-build"])

    def test_a_a_repeat_on_a_later_commit_reproduces(self):
        out = strength.derive([self.src("desktop", replay=C)])
        self.assertEqual(out["strength"], "reproduced", out["why"])

    def test_b_two_viewports_of_one_run_and_commit_are_not_validated(self):
        out = strength.derive([self.src("desktop", replay=C), self.src("mobile", replay=C)])
        self.assertEqual(out["strength"], "reproduced", out["why"])

    def test_c_another_run_is_a_second_context(self):
        out = strength.derive([self.src("desktop", replay=C),
                               self.src("mobile", run="run-2", commits=(C, D), replay=E)])
        self.assertEqual(out["strength"], "validated", out["why"])

    def test_d_two_runs_of_the_identical_builds_are_one_context(self):
        """Review r2 finding 3: a second run that replays the very same failing and passing
        commits measures the same builds again - one context, never `validated`."""
        out = strength.derive([self.src("desktop", replay=C),
                               self.src("desktop", run="run-2", commits=(A, B), replay=C)])
        self.assertEqual(out["strength"], "reproduced", out["why"])


# ----------------------------------------------------------------------- ingest/promote


class IngestRefresh(Base):
    def test_a_run_ingested_again_after_more_measurements_is_refreshed(self):
        rounds = self.rounds([(A, ll.blind()), (B, ll.well())])
        self.put("run-1", rounds, [ll.candidate(ll.OBJECTIVE)])
        doc, _ = self.ingest("run-1")
        self.assertEqual(doc["candidates"][0]["strength"], "single-run")
        # The run goes on: the same gate passes the next build too; triage writes a newer
        # ledger into the same run store.
        later = ll.Rounds(os.path.join(self.tmp, "later"))
        later.play([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        state = self.store.load("run-1")
        kr.add_report(self.store, state, "triage-report", later.triages[-1],
                      artifact_id="triage-report")
        doc, summary = self.ingest("run-1", doc=doc)
        self.assertEqual((summary["unchanged"], summary["refreshed"]), (1, ["C-1"]))
        self.assertEqual(len(doc["candidates"][0]["sources"]), 1)
        self.assertEqual(doc["candidates"][0]["strength"], "reproduced")

    def reopened_by_the_quality_gate(self, run_id):
        """Review r1 finding 3: the last triage closed OBJECTIVE (A FAIL, B PASS); the
        quality gate then advances the run's ledger on a newer playability report that
        fails it again on C (ledger.remeasure: current=[]), and records that ledger in its
        quality-report - newer than every triage-report of the run."""
        from wgf_triage import lifecycle
        rounds = self.rounds([(A, ll.blind()), (B, ll.well())])
        closed = {r["id"]: r for r in rounds.triages[-1]["lifecycle"]}
        self.assertIn(closed[ll.OBJECTIVE]["status"], ("verified", "closed"))
        again = ll.tp.played_report(rounds.run_dir, C, records=ll.blind(), visit=99)
        failing = {f["id"] for f in ll.tt.normalize("playability-report", again, ll.tt.ROUTING)}
        reopened = lifecycle.advance(
            rounds.triages[-1]["lifecycle"], at="2026-10-09T00:00:00Z", current=[],
            failing={"playability-report": failing}, seqs={"playability-report": 40},
            reports={"playability-report": again}, proto=None, proto_seq=15, decision=None,
            decision_seq=-1, human_ids=set(), selected=None, triage_id="quality-gate",
            routing_version="x", build_of=lambda k: {"commit": C, "digest": None})
        record = next(r for r in reopened if r["id"] == ll.OBJECTIVE)
        self.assertEqual(record["status"], "classified")
        run = self.put(run_id, rounds, [ll.candidate(ll.OBJECTIVE)])
        kr.add_report(self.store, run, "quality-report",
                      {"build": {"commit": C}, "findings": [],
                       "ledger": {"lifecycle": reopened}}, artifact_id="quality-report")
        return run

    def test_the_run_ledger_is_the_quality_gates_when_it_is_newer(self):
        """Ingest reads the run's newest ledger as ledger.previous_lifecycle does - the
        quality-report's when it is newer than the last triage-report. The repair the
        quality gate's ledger reopened is not counted: no repair, and the reopen shows."""
        self.reopened_by_the_quality_gate("run-reopened")
        record = self.one("run-reopened")
        snap = record["sources"][0]["remeasurement"]
        self.assertEqual(snap["status"], "classified")
        self.assertEqual(snap["ledger"]["artifact_id"], "quality-report")
        self.assertEqual([o["verdict"] for o in snap["outcomes"]], ["FAIL", "PASS", "FAIL"])
        self.assertEqual(record["strength"], "hypothesis", record["strength_why"])
        self.assertIn("no-repair", self.rules(record))
        self.assertIn(ll.OBJECTIVE, record["unstable"])

    def test_promote_reads_the_quality_gates_newer_ledger_too(self):
        """remeasure_source (promote's re-read of the run store) takes the same ledger."""
        state = self.reopened_by_the_quality_gate("run-reopened")
        state = self.store.load(state.run_id)
        snap = ingest.remeasure_source(
            {"run": state.run_id, "finding": ll.OBJECTIVE}, state,
            lambda ref: self.store.read_artifact(state.run_id, ref))
        self.assertEqual(snap["status"], "classified")
        self.assertEqual(snap["ledger"]["artifact_id"], "quality-report")


class PromoteCeiling(Base):
    def setUp(self):
        super().setUp()
        self.data = registry.load(ROOT)
        self.checks, _ = registry.classify(self.data["tiers"], ROOT)
        self.vocab = model.vocabulary(ROOT)
        with open(os.path.join(ROOT, *promote.LESSONS_PATH.split("/")), encoding="utf-8") as h:
            self.lessons_text = h.read()
        with open(os.path.join(ROOT, *promote.EVIDENCE_PATH.split("/")), encoding="utf-8") as h:
            self.evidence_text = h.read()
        self.verify = ingest.verifier(self.store)
        self.remeasure = ingest.remeasurer(self.store)

    def record(self, builds, *, proposed_check=ll.ADVISORY, groups=None, runs=None):
        runs = runs or [builds]
        names = []
        for n, b in enumerate(runs, 1):
            rounds = self.rounds(b)
            name = f"run-{n}"
            self.put(name, rounds, groups or [[ll.candidate(ll.OBJECTIVE,
                                                            proposed_check=proposed_check)]])
            names.append(name)
        doc, _ = self.ingest(*names, lessons=self.data["lessons"])
        self.assertEqual(len(doc["candidates"]), 1)
        return doc["candidates"][0]

    def draft(self, record, **kw):
        kw.setdefault("verify", self.verify)
        kw.setdefault("remeasure", self.remeasure)
        kw.setdefault("today", "2026-10-09")
        return promote.draft(record, self.data["lessons"], self.lessons_text,
                             self.evidence_text, self.checks, self.vocab,
                             evidence=self.data["evidence"], **kw)

    def test_single_run_on_an_advisory_check_drafts_only_an_experimental_lesson(self):
        record = self.record([(A, ll.blind()), (B, ll.well())])
        self.assertEqual((record["basis"], record["strength"]), ("measured", "single-run"))
        result = self.draft(record)
        lesson = result.lesson
        self.assertEqual((lesson["status"], lesson["lifecycle"], lesson["classification"]),
                         ("gap", "candidate", "OBSERVATION"))
        self.assertEqual(model.level_of(lesson, self.checks), "experimental")
        self.assertIn("single-run", lesson["gap"])
        self.assertEqual(result.evidence["strength"]["level"], "single-run")
        self.assertEqual(self.draft(record, classification="HEURISTIC").lesson["classification"],
                         "HEURISTIC")
        for asked in ("RECOMMENDATION", "VALIDATED_PRINCIPLE"):
            with self.subTest(asked=asked):
                with self.assertRaisesRegex(promote.PromoteRefused, "single-run"):
                    self.draft(record, classification=asked)
        with self.assertRaisesRegex(promote.PromoteRefused, "reproduced"):
            self.draft(record, level="recommended")

    def test_reproduced_drafts_at_most_a_recommendation(self):
        record = self.record([(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        self.assertEqual(record["strength"], "reproduced")
        lesson = self.draft(record).lesson
        self.assertEqual((lesson["status"], lesson["lifecycle"], lesson["classification"]),
                         ("enforced", "active", "RECOMMENDATION"))
        self.assertEqual(model.level_of(lesson, self.checks), "recommended")
        with self.assertRaisesRegex(promote.PromoteRefused, "at most RECOMMENDATION"):
            self.draft(record, classification="VALIDATED_PRINCIPLE")

    def test_validated_may_draft_a_validated_principle_that_holds_the_model(self):
        record = self.record(None, runs=[[(A, ll.blind()), (B, ll.well()), (C, ll.well())],
                                         [(C, ll.blind()), (D, ll.well()), (E, ll.well())]])
        self.assertEqual(record["strength"], "validated", record["strength_why"])
        # Not asked, it stays a recommendation: a VALIDATED_PRINCIPLE is a person's ask.
        self.assertEqual(self.draft(record).lesson["classification"], "RECOMMENDATION")
        result = self.draft(record, classification="VALIDATED_PRINCIPLE")
        lesson = result.lesson
        self.assertEqual((lesson["status"], lesson["lifecycle"], lesson["classification"]),
                         ("enforced", "validated", "VALIDATED_PRINCIPLE"))
        self.assertEqual(sorted(k for k, v in lesson["tests"].items() if v),
                         ["catches", "generalizes", "passes"])
        self.assertEqual(lesson["validated"], {"version": lesson["introduced"]["version"],
                                               "date": "2026-10-09"})
        verified = result.evidence["verified"]
        self.assertEqual((verified["run"], verified["commit"]), ("run-1", B))
        self.assertEqual(result.evidence["strength"]["level"], "validated")
        # The patched files hold the model's rules (the stub tests are a person's to write).
        after = load_yaml(result.files[promote.LESSONS_PATH])
        evidence = load_yaml(result.files[promote.EVIDENCE_PATH])
        problems = [p for p in model.lesson_problems(after, self.checks, self.vocab, evidence)
                    if f" {lesson['id']}:" in p]
        self.assertEqual(problems, [])
        stub = result.files[f"scripts/tests/test_lesson_{lesson['id'].lower()}.py"]
        self.assertIn(f"def test_{lesson['id']}_the_check_generalizes", stub)

    def test_blocking_and_required_stay_the_check_tiers(self):
        """K4 unchanged: a measured single-run candidate on a hard check is drafted BLOCKING
        as before; strength neither raises nor lowers it, and a weaker classification asked
        for is refused."""
        record = self.record([(A, ll.blind()), (B, ll.well())], proposed_check=ll.HARD)
        self.assertEqual(record["strength"], "single-run")
        lesson = self.draft(record).lesson
        self.assertEqual((lesson["status"], lesson["classification"]), ("enforced", "BLOCKING"))
        for asked in ("VALIDATED_PRINCIPLE", "RECOMMENDATION"):
            with self.subTest(asked=asked):
                with self.assertRaisesRegex(promote.PromoteRefused, "single-run"):
                    self.draft(record, classification=asked)
        # What the evidence would allow is still not the rule's: its tier classifies it.
        for asked in ("OBSERVATION", "HEURISTIC"):
            with self.subTest(asked=asked):
                with self.assertRaisesRegex(promote.PromoteRefused,
                                            "neither raises nor lowers it"):
                    self.draft(record, classification=asked)

    def test_promote_derives_strength_again_and_never_trusts_the_record(self):
        record = self.record([(A, ll.blind()), (B, ll.well())])
        forged = copy.deepcopy(record)
        forged.update(strength="validated", strength_why="validated: trust me")
        forged["sources"][0]["remeasurement"]["samples"] *= 3
        with self.assertRaisesRegex(promote.PromoteRefused, "single-run"):
            self.draft(forged, classification="VALIDATED_PRINCIPLE")
        # Without a run store to read it again from, nothing was re-measured.
        with self.assertRaisesRegex(promote.PromoteRefused, "hypothesis"):
            self.draft(record, remeasure=None, classification="RECOMMENDATION")


if __name__ == "__main__":
    unittest.main()
