"""K5: cross-session quality transfer - knowledge reaches a fresh session only through the Factory.

Two sessions, each a SEPARATE process (scripts/tests/fixtures/transfer/session.py) with its
own temporary project directory (WGF_PROJECT_DIR) and an environment scrubbed of the other's,
drive the shipped new-game workflow through the real engine and the real gates in the
quality-consistency fixture world (a fixture developer, bot, assets and verify; no agent
host, no network):

  Session A   on the Factory before L29 (fixtures/transfer/prelesson.py): a 2D puzzle-like
              game whose build debuts two never-seen elements in one unit. The fixture bot's
              naive clear rate for that unit falls against the accepted build's -
              `naive.clear_rate` FAILs (a real gate check, on that build) - triage routes it,
              the encounter designer reports the lesson candidate (symptom, root cause,
              systemic, proposed checks and level), and splitting the introductions passes.
              `wgf knowledge ingest` stores a MEASURED candidate; `wgf knowledge promote`
              drafts the patch, whose lesson is the shipped L29 less a person's completion
              (the checks implemented first, the title and problem stated generally, the
              tests written). The clear rate is a FIXTURE measurement: it proves the
              pipeline, not the principle - that rests on the observed real games
              (test_lesson_l29) and the craft.
  Session B   a fresh 3D racer designed by the REAL design step through the `agent` author,
              whose host (fixtures/transfer/designer.py) reads only its request: its own plan
              debuts two elements at once, and it paces its introductions and records its
              decision trace only when the request's knowledge carries the principle. The
              knowledge reaches it through the run's pinned contract and the design request,
              and is enforced on the design, on the built content data and at the quality
              gate. It opens nothing of Session A's.
  Control     Session B on the Factory before L29: the request does not carry the principle,
              the designer ships its naive plan, and nothing holds it.
  Held        a designer that ignores the principle breaches the design rule and is repaired
              in the design step's repair round; a build that breaks a compliant design FAILs
              content-sufficiency (compliance RELEASE_BLOCKED on L29) and is repaired; a
              designer that claims the rule applied while breaking it breaches the trace rule.
  Versions    a run pinned under L29 at its shipped revision keeps it after the Factory
              moves to the next.

    python -m unittest scripts.tests.test_knowledge_transfer
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock as patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_knowledge_run as runs  # noqa: E402
from wgf_knowledge import model  # noqa: E402
from wgf_quality import compliance, registry  # noqa: E402
from wgflib.workflow import references  # noqa: E402
from wgflib.workflow.api import RunRequest  # noqa: E402
from wgflib.yamllite import load as load_yaml  # noqa: E402

SESSION = os.path.join(HERE, "fixtures", "transfer", "session.py")
LESSONS = "core/reference/lessons.yaml"
CHECK = "content.introductions_one_at_a_time"
DESIGN_CHECK = f"design-consistency:{CHECK}"
BUILD_CHECK = f"content-sufficiency:{CHECK}"
SHIPPED = {l["id"]: l for l in registry.load(ROOT)["lessons"]["lessons"]}
TITLE = SHIPPED["L29"]["title"]
# The shipped revision of L29 (r2: its entry changed after it was first committed - the
# transfer tests were added to its tests - so its revision rose, as check-integrity holds).
REVISION = SHIPPED["L29"]["revision"]
VERSION = f"L29@r{REVISION}"
# What a person adds to promote's draft before the pull request merges: the lesson's title
# and problem stated generally (the draft's problem is the run's own symptom), the tests
# written, the date it lands - and the revision its later edits raised (a draft is r1).
COMPLETION = ("title", "problem", "tests", "introduced", "revision")


def scrubbed_env(project, foreign=()):
    """The environment a session runs in: this process's, without any WGF_ variable and
    without anything that names another session's directory, plus its own project."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("WGF_")
           and not any(f and f in v for f in foreign)}
    env["WGF_PROJECT_DIR"] = project
    return env


def session(tmp, name, *args, foreign=()):
    """Run one session in a process of its own; its summary (session.py `run`)."""
    project = os.path.join(tmp, name)
    os.makedirs(project, exist_ok=True)
    out = os.path.join(project, "summary.json")
    command = [sys.executable, SESSION, "run", "--store", os.path.join(project, "work"),
               "--out", out, *args]
    done = subprocess.run(command, cwd=ROOT, env=scrubbed_env(project, foreign),
                          capture_output=True, text=True, timeout=1200)
    if done.returncode != 0 or not os.path.isfile(out):
        raise AssertionError(f"session {name} failed ({done.returncode}):\n"
                             f"{done.stdout[-2000:]}\n{done.stderr[-4000:]}")
    with open(out, encoding="utf-8") as handle:
        summary = json.load(handle)
    summary["project"] = project
    return summary


def knowledge_cli(tmp, project, mode, *args):
    """`wgf knowledge ...` in a process of its own against the Factory before L29
    (session.py `knowledge`); (exit code, stdout, stderr)."""
    command = [sys.executable, SESSION, "knowledge", mode, "--tmp",
               os.path.join(tmp, f"factory{mode}"), "--", *args]
    done = subprocess.run(command, cwd=ROOT, env=scrubbed_env(project), capture_output=True,
                          text=True, timeout=600)
    return done.returncode, done.stdout, done.stderr


class Run:
    """A session's run, read from its store."""

    def __init__(self, summary):
        self.summary = summary
        self.dir = os.path.join(summary["store"], "workflows", summary["run_id"])

    def versions(self, artifact_type):
        found = glob.glob(os.path.join(self.dir, "artifacts", artifact_type, "v*.json"))
        found.sort(key=lambda p: int(re.search(r"v(\d+)\.json$", p).group(1)))
        out = []
        for path in found:
            with open(path, encoding="utf-8") as handle:
                out.append(json.load(handle))
        return out

    def newest(self, artifact_type):
        found = self.versions(artifact_type)
        return found[-1] if found else None

    def design_file(self, name):
        path = os.path.join(self.dir, "design", name)
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def steps(self):
        return [(e["step"], e["route"]) for e in self.summary["trail"]]


def check_of(report, check_id):
    return next((c for c in report.get("checks") or () if c.get("id") == check_id), None)


def rule_result(design, rule_id):
    return next(r for r in design["consistency"]["rule_results"]
                if r["criterion_id"] == rule_id)


# ----------------------------------------------------------------------- Session A -> B


class SessionAToB(unittest.TestCase):
    """Session A learns the lesson through the gates; a fresh Session B is held to it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wgf-k5-")
        cls.a = session(cls.tmp, "session-a", "--session", "a")
        cls.run_a = Run(cls.a)
        project = cls.a["project"]
        cls.ingested = knowledge_cli(cls.tmp, project, "--before-l29", "ingest",
                                     cls.a["run_id"], "--store", cls.a["store"])
        cls.patch_file = os.path.join(project, "L29.patch")
        cls.promoted = knowledge_cli(cls.tmp, project, "--without-l29", "promote", "C-1",
                                     "--store", cls.a["store"], "--title", TITLE,
                                     "--out", cls.patch_file, "--json")
        # Session B: another directory, another process, nothing of A's in its environment.
        cls.b = session(cls.tmp, "session-b", "--session", "b",
                        foreign=(project, cls.a["run_id"]))
        cls.run_b = Run(cls.b)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- Session A ----------------------------------------------------------------------

    def test_session_a_the_double_debut_fails_its_clear_rate(self):
        """The defect is measured by a real gate on the build that carries it, recorded by
        triage, reported as a lesson candidate - and fixed, it passes."""
        unit, _early = self.a["target"]
        plays = self.run_a.versions("playability-report")
        failed = [p for p in plays if "desktop:naive.clear_rate" in (p.get("failed_checks") or [])]
        self.assertTrue(failed, [p.get("failed_checks") for p in plays])
        check = next(c for c in failed[0]["checks"] if c["id"] == "naive.clear_rate")
        regressed = [c for c in check["measured"]["compared"] if c["regressed"]]
        self.assertTrue(regressed and all(c["unit"] == unit for c in regressed), regressed)
        # the content data the failing build shipped: that unit shows the later elements
        # a unit early, its `introduces` as the design states it (untouched)
        designed = next(u for u in self.run_a.newest("game-design")["build_spec"]["content"]
                        ["units"] if u["id"] == unit)
        shipped = []
        for path in glob.glob(os.path.join(self.run_a.dir, "playability", "*", "out",
                                           "content", "units.json")):
            with open(path, encoding="utf-8") as handle:
                built = {u["id"]: u for u in json.load(handle)["units"]}
            shipped.append(built[unit])
        doubled_builds = [u for u in shipped if set(_early) <= set(u.get("elements") or [])]
        self.assertTrue(doubled_builds, shipped)
        for built_unit in doubled_builds:
            self.assertEqual(built_unit.get("introduces"), designed.get("introduces"))
        triage = [t for t in self.run_a.versions("triage-report") if t.get("findings")]
        finding = "playability-report:naive.clear_rate@desktop"
        self.assertIn(finding, [f["id"] for f in triage[0]["findings"]])
        self.assertEqual(triage[0]["commit"], failed[0]["commit"])
        # the specialist reports the systemic candidate on a build the gate failed again
        reported = [p for p in self.run_a.versions("prototype-report")
                    if (p.get("specialist") or {}).get("lesson_candidates")]
        candidate = reported[0]["specialist"]["lesson_candidates"][0]
        self.assertEqual((candidate["finding"], candidate["proposed_level"]),
                         (finding, "blocking"))
        self.assertTrue(candidate["systemic"]["value"])
        self.assertEqual(candidate["proposed_checks"], [DESIGN_CHECK, BUILD_CHECK])
        self.assertIn(unit, candidate["symptom"])
        # the fix: the next build passes the clear rate, and the run reaches G4
        self.assertNotIn("desktop:naive.clear_rate", plays[-1].get("failed_checks") or [])
        self.assertTrue(self.a["waiting_at_g4"], self.a["message"])
        self.assertEqual(self.a["visits"], ["encounter-designer", "encounter-designer"])
        quality = self.run_a.newest("quality-report")
        self.assertTrue(quality["lesson_candidates"])

    def test_session_a_ingest_gives_a_measured_candidate(self):
        code, out, err = self.ingested
        self.assertEqual(code, 0, out + err)
        path = os.path.join(self.a["project"], "workspace", "lessons", "candidates.yaml")
        with open(path, encoding="utf-8") as handle:
            store = load_yaml(handle.read())
        record = store["candidates"][0]
        self.assertEqual((record["id"], record["basis"]), ("C-1", "measured"))
        self.assertEqual(record["proposed_checks"], [DESIGN_CHECK, BUILD_CHECK])
        self.assertEqual(record["domain"], "level-design")
        measured = [s for s in record["sources"] if s["basis"] == "measured"]
        self.assertTrue(any(s["artifact_type"] == "triage-report" for s in measured))

    def test_session_a_promote_drafts_the_shipped_lesson(self):
        code, out, err = self.promoted
        self.assertEqual(code, 0, out + err)
        drafted = json.loads(out)["lesson"]
        shipped = SHIPPED["L29"]
        checks, _ = registry.classify(registry.load(ROOT)["tiers"], ROOT)
        for key in ("id", "category", "checks", "scope"):
            self.assertEqual(drafted[key], shipped[key], key)
        self.assertEqual(model.level_of(drafted, checks), model.level_of(shipped, checks))
        self.assertEqual(model.level_of(shipped, checks), "blocking")
        # the rest of the entry is the draft's too, but for a person's completion
        for key in set(shipped) | set(drafted):
            if key not in COMPLETION:
                self.assertEqual(drafted.get(key), shipped.get(key), key)
        for kind in ("catches", "passes"):
            self.assertTrue(set(drafted["tests"][kind]) <= set(shipped["tests"][kind]), kind)
        # The patch applies to the Factory knowledge files as they were, and adds this entry.
        work = os.path.join(self.tmp, "apply")
        before = os.path.join(self.tmp, "factory--without-l29", "factory-without-L29")
        for relative in (LESSONS, "workspace/lessons/evidence.yaml"):
            target = os.path.join(work, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(before, *relative.split("/")), target)
        done = subprocess.run(["git", "apply", "--unsafe-paths", "--directory=.",
                               os.path.abspath(self.patch_file)], cwd=work,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(work, *LESSONS.split("/")), encoding="utf-8") as handle:
            applied = {l["id"]: l for l in load_yaml(handle.read())["lessons"]}
        self.assertEqual(applied["L29"], drafted)

    # -- Session B ----------------------------------------------------------------------

    def test_session_b_a_fresh_session_applies_the_principle(self):
        """Learned on a 2D puzzle-like game in Session A; held, through the Factory alone, on
        a 3D racer in a fresh Session B - in its contract, its design request, its design's
        trace, its design check, its built content and its quality gate."""
        self.assertTrue(self.b["waiting_at_g4"], self.b["message"])
        contract = self.run_b.newest("knowledge-contract")
        rule = next(r for r in contract["rules"] if r["id"] == "L29")
        self.assertEqual((rule["version"], rule["level"]), (VERSION, "blocking"))
        self.assertEqual(rule["digest"], model.lesson_digest(SHIPPED["L29"]))
        self.assertEqual(rule["why_applicable"], ["global"])
        self.assertEqual(contract["facets"]["render"], "3d")
        self.assertEqual(contract["trace"], {"present": True, "applied": ["L29"],
                                             "contradicted": []})
        # the design request carried it, structured; the designer read it there
        request = self.run_b.design_file("1-1.request.json")
        given = next(r for r in request["knowledge"]["rules"] if r["id"] == "L29")
        self.assertEqual((given["version"], given["domain"], given["trace"]),
                         (VERSION, "level-design", True))
        self.assertEqual(given["principle"], " ".join(SHIPPED["L29"]["principle"].split()))
        seen = self.run_b.design_file("seen-1-1.json")
        self.assertEqual((seen["rule"]["id"], seen["paced"]), ("L29", True))
        # the design's trace names it with units; both design rules hold
        design = self.run_b.newest("game-design")
        trace = design["knowledge_applied"][0]
        unit_ids = {u["id"] for u in design["build_spec"]["content"]["units"]}
        self.assertEqual((trace["rule"], trace["revision"], trace["applied"]),
                         ("L29", REVISION, True))
        self.assertTrue(trace["where"] and set(trace["where"]) <= unit_ids)
        self.assertFalse(rule_result(design, CHECK)["breached"])
        self.assertFalse(rule_result(design, "knowledge.trace_matches_design")["breached"])
        # the fixture developer built units.json from the design: the build check passes
        sufficiency = self.run_b.newest("content-sufficiency-report")
        self.assertEqual(check_of(sufficiency, CHECK)["status"], "PASS")
        # the quality gate: SATISFIED by the checks, with the trace beside it
        quality = self.run_b.newest("quality-report")
        held = next(r for r in quality["compliance"]["rules"] if r["id"] == "L29")
        self.assertEqual(held["status"], "SATISFIED")
        self.assertEqual({c["check"]: c["status"] for c in held["checks"]},
                         {DESIGN_CHECK: "PASS", BUILD_CHECK: "PASS"})
        self.assertEqual(held["trace"]["where"], trace["where"])

    def test_session_b_read_nothing_of_session_a(self):
        foreign = (self.a["project"], self.a["run_id"])
        for path in self.b["opened"]:
            self.assertFalse(any(f in path for f in foreign), path)
        self.assertFalse(any(f in v for v in self.b["env"].values() for f in foreign))
        self.assertFalse(any(f in a for a in self.b["argv"] for f in foreign))
        self.assertNotEqual(self.b["env"]["WGF_PROJECT_DIR"], self.a["project"])
        # nothing in Session B's project names Session A
        for current, _dirs, files in os.walk(self.b["project"]):
            for name in files:
                with open(os.path.join(current, name), "rb") as handle:
                    data = handle.read()
                for f in foreign:
                    self.assertNotIn(f.encode("utf-8"), data, os.path.join(current, name))
        # it opened the Factory's knowledge - the only way the lesson could reach it
        self.assertTrue(any(p.replace("\\", "/").endswith(LESSONS) for p in self.b["opened"]))


# ------------------------------------------------------------- what holds, and what did not


class Control(unittest.TestCase):
    """Session B on the Factory before L29: the designer is never told, ships its naive plan,
    and nothing holds it - the benefit above came from the Factory's knowledge."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wgf-k5-control-")
        cls.control = Run(session(cls.tmp, "control", "--session", "b", "--knowledge", "without"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_without_the_lesson_the_naive_plan_ships_and_nothing_holds_it(self):
        self.assertTrue(self.control.summary["waiting_at_g4"], self.control.summary["message"])
        request = self.control.design_file("1-1.request.json")
        self.assertNotIn("L29", [r["id"] for r in request["knowledge"]["rules"]])
        seen = self.control.design_file("seen-1-1.json")
        self.assertEqual((seen["rule"], seen["paced"]), (None, False))
        design = self.control.newest("game-design")
        from wgf_design import content
        self.assertTrue(content.introductions_view(design)["over_one"])
        self.assertNotIn("knowledge_applied", design)
        self.assertNotIn(CHECK, [r["criterion_id"] for r in design["consistency"]["rule_results"]])
        self.assertNotIn("L29", [r["id"] for r in self.control.newest("knowledge-contract")["rules"]])
        self.assertIsNone(check_of(self.control.newest("content-sufficiency-report"), CHECK))


class PinnedBefore(unittest.TestCase):
    """A run started on the Factory before L29 and resumed on today's code is held to the
    rules it pinned: the design step and content-sufficiency read the run's pinned copies,
    never a rule or check added to the Factory since - on the design and on the build."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wgf-k5-pinned-")
        started = session(cls.tmp, "old-run", "--session", "b", "--knowledge", "pinned-before",
                          "--hold-g2")
        cls.started = started
        # Resumed in another process with nothing filtered: today's code and live files.
        cls.resumed = Run(session(cls.tmp, "old-run", "--session", "b", "--resume",
                                  started["run_id"]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_run_pinned_without_the_checks_never_gets_them_on_resume(self):
        self.assertEqual((self.started["status"], self.started["cursor"]),
                         ("WAITING", "strategy-review"))
        run = self.resumed
        self.assertTrue(run.summary["waiting_at_g4"], run.summary["message"])
        with open(os.path.join(run.dir, references.DIRECTORY, *LESSONS.split("/")),
                  encoding="utf-8") as handle:
            self.assertNotIn("id: L29", handle.read())
        # the designer's own plan debuts two elements at once, and nothing the run pinned
        # holds it: no design rule, no trace rule, no build check, no rule in its contract
        design = run.newest("game-design")
        from wgf_design import content
        self.assertTrue(content.introductions_view(design)["over_one"])
        judged = [r["criterion_id"] for r in design["consistency"]["rule_results"]]
        self.assertNotIn(CHECK, judged)
        # exactly the rules of the file the run pinned, none of the live file's others
        with open(os.path.join(run.dir, references.DIRECTORY, "core", "reference",
                               "design-consistency-rules.yaml"), encoding="utf-8") as handle:
            pinned = [r["id"] for r in load_yaml(handle.read())["rules"]]
        self.assertEqual([r for r in judged if "." not in r or r.startswith("knowledge.")],
                         [r for r in pinned if "." not in r or r.startswith("knowledge.")])
        self.assertTrue(set(pinned) <= set(judged))
        for report in run.versions("content-sufficiency-report"):
            self.assertIsNone(check_of(report, CHECK))
        self.assertNotIn("L29", [r["id"] for r in run.newest("knowledge-contract")["rules"]])


class Held(unittest.TestCase):
    """The lesson present: a designer that ignores it, a build that breaks it, and a false
    claim of applying it are each caught."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wgf-k5-held-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_violating_designer_breaches_and_is_repaired(self):
        run = Run(session(self.tmp, "violate", "--session", "b", "--designer", "violate"))
        first = run.design_file("seen-1-1.json")
        self.assertEqual((first["rule"]["id"], first["paced"], first["repair"]),
                         ("L29", False, False))
        # its naive plan shows the later elements a unit early, `introduces` untouched
        draft = run.design_file("1-1.draft.json")
        moved_unit, moved = first["moved"]
        unit = next(u for u in draft["build_spec"]["content"]["units"] if u["id"] == moved_unit)
        self.assertTrue(set(moved) <= set(unit["elements"]), unit)
        self.assertFalse(set(moved) & set(unit.get("introduces") or []), unit)
        repair = run.design_file("1-1-repair1.request.json")
        self.assertTrue(any(f"consistency {CHECK}" in p for p in repair["repair"]["problems"]),
                        repair["repair"]["problems"])
        self.assertTrue(run.design_file("seen-1-1-repair1.json")["paced"])
        design = run.newest("game-design")
        self.assertFalse(rule_result(design, CHECK)["breached"])
        self.assertTrue(run.summary["waiting_at_g4"], run.summary["message"])

    def test_a_violating_build_fails_content_sufficiency_and_is_repaired(self):
        # two builds: one that shows a later unit's elements a unit early and lists them in
        # `introduces`, one that shows them with `introduces` left as the design states it
        for mode in ("violating", "violating-unlisted"):
            with self.subTest(mode=mode):
                self.violating_build(mode)

    def violating_build(self, mode):
        run = Run(session(self.tmp, f"build-{mode}", "--session", "b", "--developer", mode))
        reports = run.versions("content-sufficiency-report")
        failed = reports[0]
        check = check_of(failed, CHECK)
        self.assertEqual(check["status"], "FAIL", check)
        self.assertEqual(check.get("route"), "develop")
        self.assertFalse(rule_result(run.newest("game-design"), CHECK)["breached"])
        # held to the run's contract on that build: L29 FAILED, the release blocked
        contract = run.newest("knowledge-contract")
        with open(os.path.join(run.dir, references.DIRECTORY, "core", "reference",
                               "check-tiers.yaml"), encoding="utf-8") as handle:
            tiers = load_yaml(handle.read())
        section = compliance.evaluate(contract, tiers, {
            "content-sufficiency-report": failed, "game-design": run.newest("game-design")},
            tier="release", lessons=registry.load(ROOT)["lessons"])
        held = next(r for r in section["rules"] if r["id"] == "L29")
        self.assertEqual((held["status"], section["verdict"]), ("FAILED", "RELEASE_BLOCKED"))
        self.assertIn("L29", section["blocking"])
        # repaired by the level designer's visit, then passed at the gate
        self.assertIn(("triage", "level-designer"), run.steps())
        self.assertEqual(check_of(reports[-1], CHECK)["status"], "PASS")
        quality = run.newest("quality-report")
        self.assertEqual(next(r for r in quality["compliance"]["rules"]
                              if r["id"] == "L29")["status"], "SATISFIED")
        self.assertTrue(run.summary["waiting_at_g4"], run.summary["message"])

    def test_a_claim_the_design_contradicts_is_a_trace_breach(self):
        run = Run(session(self.tmp, "claim", "--session", "b", "--designer", "claim"))
        self.assertEqual(run.summary["status"], "FAILED")
        self.assertIn("knowledge.trace_matches_design", run.summary["message"])
        repair = run.design_file("1-1-repair1.request.json")
        problems = " ".join(repair["repair"]["problems"])
        self.assertIn("consistency knowledge.trace_matches_design", problems)
        self.assertIn("claims the rule applied, and this design breaks it", problems)


# ------------------------------------------------------------------------------- versions


LESSONS_TEXT = "core/reference/lessons.yaml"


def moved_on(text):
    """lessons.yaml with L29 revised in place to its next revision - the Factory moving on
    after a run pinned the shipped one: its lesson text sharpened, its revision raised."""
    head, sep, tail = text.partition("  - id: L29\n")
    assert sep, "L29 is not in lessons.yaml"
    entry, nxt, rest = tail.partition("\n  - id: ")
    entry, count = re.subn(rf"(?m)^    revision: {REVISION}$", f"    revision: {REVISION + 1}",
                           entry)
    assert count == 1
    entry = entry.replace("    lesson: >-\n", "    lesson: >-\n      Revised: ", 1)
    return head + sep + entry + nxt + rest


class Versioning(runs._Case):
    """A run's contract pins each rule by revision and digest: a run pinned under L29 at its
    shipped revision keeps it after the Factory moves to the next; a run started after the
    move gets the next."""

    def rule(self, api, state, rule_id="L29"):
        contract = self.contract(api, state)
        return next(r for r in contract["rules"] if r["id"] == rule_id), contract

    def test_an_old_run_keeps_its_revision_and_a_new_run_gets_the_next(self):
        api, old = self.to_g4()
        first, contract = self.rule(api, old)
        self.assertEqual((first["revision"], first["version"]), (REVISION, VERSION))
        self.assertEqual(first["digest"], model.lesson_digest(SHIPPED["L29"]))
        # every rule, applicable or not, is pinned by digest
        self.assertTrue(all(r.get("digest") for r in contract["rules"]))
        self.assertTrue(all(r.get("digest") for r in contract["not_applicable"]))
        self.assertEqual(contract["trace"], {"present": False, "applied": [],
                                             "contradicted": []})

        real = references.collect

        def collect(relpaths, root=None):
            found = real(relpaths, root)
            if LESSONS_TEXT in found:
                found[LESSONS_TEXT] = moved_on(
                    found[LESSONS_TEXT].decode("utf-8")).encode("utf-8")
            return found

        with patch.patch.object(references, "collect", collect):
            _, new = self.to_g4(api)
            second, _ = self.rule(api, new)
            self.assertEqual((second["revision"], second["version"]),
                             (REVISION + 1, f"L29@r{REVISION + 1}"))
            self.assertNotEqual(second["digest"], first["digest"])
            self.assertTrue(second["lesson"].startswith("Revised:"))
            # The old run's contract made again after the move: still the r1 it pinned.
            again = api.run(RunRequest(resume=old.run_id, from_step=runs.STEP,
                                       decided_by="human"))
            self.assertGreater(self.executed(again).count(runs.STEP),
                               self.executed(old).count(runs.STEP), "not made again")
            kept, _ = self.rule(api, again)
            self.assertEqual((kept["revision"], kept["digest"]), (REVISION, first["digest"]))


if __name__ == "__main__":
    unittest.main()
