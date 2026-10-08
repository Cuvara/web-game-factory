"""The regression registry (WS-9): check tiers and lessons as data, held by check-integrity.

core/reference/check-tiers.yaml classifies every check the Factory's reference files and
producer tables declare as a Hard Gate, a Quality Gate or Advisory; core/reference/lessons.yaml
names, for every lesson the validation runs taught, the check that now holds it and the test
that proves it - or says it is a gap. These tests hold:

  * the shipped registry has no problem, and its tier vocabulary is exactly the three tiers;
  * a check added to a source without a tier fails integrity (a content-sufficiency check, a
    producer check, a design rule whose severity the map does not cover), and so does a
    producer check the code never reports, and a check the floor reads that no producer
    table classifies;
  * a producer check a release blocker reads is never advisory;
  * an enforced lesson whose check or test does not exist fails, a gap that says nothing
    fails, a lesson naming a game fails, and evidence for an unknown lesson fails;
  * a finding of a lesson's check carries the lesson as `guarded_by`;
  * every source says where its results are read (`status_at`, 1.1.0), a real report of
    its producer resolves a failing and a passing result through it, a report without the
    check is UNMEASURED, and a locator the producer's schema does not have fails integrity;
  * check-integrity reports registry problems as errors.

    python -m unittest scripts.tests.test_regression_registry
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

from wgf_quality import registry  # noqa: E402
from wgflib.yamllite import load as load_yaml  # noqa: E402

DATA = registry.load(ROOT)
CHECKS, PROBLEMS = registry.classify(DATA["tiers"], ROOT)


def _dump(value, indent=0):
    """A minimal YAML writer for the data these tests round-trip (mappings, lists, scalars)."""
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return pad + "{}\n"
        out = ""
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                out += f"{pad}{key}:\n" + _dump(item, indent + 2)
            else:
                out += f"{pad}{key}: {_scalar(item)}\n"
        return out
    if isinstance(value, list):
        out = ""
        for item in value:
            if isinstance(item, dict) and item:
                body = _dump(item, indent + 2)
                out += pad + "- " + body[indent + 2:]
            else:
                out += f"{pad}- {_scalar(item)}\n"
        return out
    return pad + _scalar(value) + "\n"


def _scalar(value):
    import json
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return json.dumps(str(value))


class Sandbox(unittest.TestCase):
    """A copy of the files the registry reads, to break one at a time."""

    FILES = ("core/reference/check-tiers.yaml", "core/reference/lessons.yaml",
             "core/reference/quality-floor.yaml", "core/reference/content-sufficiency.yaml",
             "core/reference/visual-qa-rubric.yaml", "core/reference/gate-gaming.yaml",
             "core/reference/design-consistency-rules.yaml", "core/reference/browser-qa.yaml",
             "core/reference/quality-policy.yaml", "core/workflows/new-game.workflow.yaml",
             "workspace/lessons/evidence.yaml",
             # The knowledge model's scope vocabularies (wgf_knowledge.model.vocabulary).
             "core/reference/genre-models.yaml", "core/reference/quality-benchmark.yaml",
             "core/reference/visual-quality.yaml")
    TREES = ("scripts/wgf_playability", "scripts/wgf_production", "scripts/wgf_assets",
             "scripts/wgf_verification", "scripts/tests")
    # Copied whole (every file, not only .py): the platform profiles a scope names, and the
    # artifact schemas a check's `status_at` is held against.
    DATA_TREES = ("core/reference/platforms", "core/artifacts")

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wgf-registry-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for relative in self.FILES:
            target = os.path.join(self.root, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(ROOT, *relative.split("/")), target)
        for relative in self.TREES:
            source = os.path.join(ROOT, *relative.split("/"))
            for current, _dirs, files in os.walk(source):
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    rel = os.path.relpath(os.path.join(current, name), ROOT)
                    target = os.path.join(self.root, rel)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copyfile(os.path.join(current, name), target)
        for relative in self.DATA_TREES:
            shutil.copytree(os.path.join(ROOT, *relative.split("/")),
                            os.path.join(self.root, *relative.split("/")))

    def read(self, relative):
        with open(os.path.join(self.root, *relative.split("/")), encoding="utf-8") as handle:
            return load_yaml(handle.read())

    def write(self, relative, data):
        with open(os.path.join(self.root, *relative.split("/")), "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write(_dump(data))

    def edit_text(self, relative, old, new):
        path = os.path.join(self.root, *relative.split("/"))
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.replace(old, new, 1))

    def problems(self):
        return registry.problems(self.root)


class ShippedRegistry(unittest.TestCase):
    def test_the_shipped_registry_has_no_problem(self):
        self.assertEqual(registry.problems(ROOT), [])

    def test_the_vocabulary_is_exactly_the_three_tiers(self):
        self.assertEqual(list(DATA["tiers"]["tiers"]), ["hard", "quality", "advisory"])
        self.assertEqual({e["tier"] for e in CHECKS.values()},
                         {"hard", "quality", "advisory"})

    def test_every_source_is_classified(self):
        sources = {e["source"] for e in CHECKS.values()}
        self.assertEqual(sources, set(DATA["tiers"]["sources"]))
        for name in ("quality-floor", "content-sufficiency", "playability",
                     "production-quality", "visual-qa-blocker", "gate-gaming",
                     "design-consistency", "model-review"):
            self.assertIn(name, sources)

    def test_the_floor_rule_tells_a_pass_fail_blocker_from_a_calibrated_bar(self):
        self.assertEqual(CHECKS["quality-floor:floor.core_loop"]["tier"], "hard")
        self.assertEqual(CHECKS["quality-floor:floor.visual_mean"]["tier"], "quality")
        self.assertEqual(CHECKS["quality-floor:floor.music"]["tier"], "quality")
        self.assertEqual(CHECKS["quality-floor:floor.visual_minor_findings"]["tier"],
                         "advisory")
        self.assertEqual(CHECKS["design-consistency:progression_has_an_end_or_a_loop"]["tier"],
                         "advisory")
        self.assertEqual(CHECKS["quality-dimension:ui"]["tier"], "quality")

    def test_every_lesson_is_l1_to_l28_with_a_check_or_a_gap(self):
        lessons = DATA["lessons"]["lessons"]
        self.assertEqual([l["id"] for l in lessons], [f"L{i}" for i in range(1, 29)])
        for lesson in lessons:
            if lesson["status"] in ("enforced", "partial"):
                self.assertTrue(lesson["checks"] and lesson["tests"], lesson["id"])
                for check in lesson["checks"]:
                    self.assertIn(check, CHECKS, lesson["id"])
            elif lesson["status"] == "gap":
                self.assertTrue(lesson["gap"], lesson["id"])

    def test_no_lesson_names_a_game(self):
        games = DATA["evidence"]["games"]
        self.assertTrue(games)
        with open(os.path.join(ROOT, *registry.LESSONS_FILE.split("/")),
                  encoding="utf-8") as handle:
            text = handle.read().lower()
        for game in games:
            self.assertNotIn(game.lower(), text)


class NewChecksNeedATier(Sandbox):
    def test_a_content_check_without_a_tier_fails(self):
        self.edit_text("core/reference/content-sufficiency.yaml",
                       "  content.drift: {dimension: content",
                       "  content.newcheck: {dimension: content, owner: level-design, "
                       "severity: blocker, route: develop}\n  content.drift: {dimension: content")
        problems = self.problems()
        self.assertTrue(any("'content.newcheck', which has no tier" in p for p in problems),
                        problems)

    def test_a_design_rule_whose_severity_the_map_does_not_cover_fails(self):
        self.edit_text("core/reference/design-consistency-rules.yaml",
                       "    severity: warning\n    when: { left: scope.progression_terminal",
                       "    severity: shrug\n    when: { left: scope.progression_terminal")
        problems = self.problems()
        self.assertTrue(any("progression_has_an_end_or_a_loop" in p and "'shrug'" in p
                            for p in problems), problems)

    def test_a_new_floor_criterion_is_classified_by_its_rule(self):
        floor = self.read("core/reference/quality-floor.yaml")
        new = copy.deepcopy(floor["universal"][0])
        new["id"] = "floor.new_thing"
        floor["universal"].append(new)
        self.write("core/reference/quality-floor.yaml", floor)
        checks, problems = registry.classify(self.read("core/reference/check-tiers.yaml"),
                                             self.root)
        self.assertEqual(problems, [])
        self.assertEqual(checks["quality-floor:floor.new_thing"]["tier"], "hard")

    def test_a_check_the_floor_reads_that_no_producer_table_classifies_fails(self):
        self.edit_text("core/reference/quality-floor.yaml",
                       "checks: [probe.present, start.playable,",
                       "checks: [probe.brand_new, probe.present, start.playable,")
        problems = self.problems()
        self.assertTrue(any("'probe.brand_new', which no source of that producer classifies"
                            in p for p in problems), problems)

    def test_a_producer_check_the_code_never_reports_fails(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["playability"]["checks"]["made.up_check"] = "hard"
        self.write("core/reference/check-tiers.yaml", tiers)
        problems = self.problems()
        self.assertTrue(any("'made.up_check' appears nowhere in scripts/wgf_playability" in p
                            for p in problems), problems)

    def test_an_advisory_check_a_release_blocker_reads_fails(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["playability"]["checks"]["restart.works"] = "advisory"
        self.write("core/reference/check-tiers.yaml", tiers)
        problems = self.problems()
        self.assertTrue(any("playability:restart.works is advisory" in p for p in problems),
                        problems)

    def test_a_tier_outside_the_vocabulary_fails(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["production-quality"]["checks"]["ui.text"] = "nice-to-have"
        self.write("core/reference/check-tiers.yaml", tiers)
        self.assertTrue(any("'nice-to-have'" in p for p in self.problems()))


class Lessons(Sandbox):
    def lessons(self):
        return self.read("core/reference/lessons.yaml")

    def set_lesson(self, lesson_id, **changes):
        data = self.lessons()
        for lesson in data["lessons"]:
            if lesson["id"] == lesson_id:
                lesson.update(changes)
                for key, value in list(changes.items()):
                    if value is None:
                        del lesson[key]
        self.write("core/reference/lessons.yaml", data)

    def test_an_enforced_lesson_whose_check_does_not_exist_fails(self):
        self.set_lesson("L5", checks=["playability:content.units_teleport"])
        self.assertTrue(any("L5: check 'playability:content.units_teleport' is not classified"
                            in p for p in self.problems()))

    def test_an_enforced_lesson_whose_test_does_not_exist_fails(self):
        self.set_lesson("L5", tests=["scripts/tests/test_playability.py::test_never_written"])
        self.assertTrue(any("L5: test scripts/tests/test_playability.py has no test "
                            "test_never_written" in p for p in self.problems()))

    def test_an_enforced_lesson_without_a_test_fails(self):
        self.set_lesson("L20", tests=None)
        self.assertTrue(any("L20: an enforced lesson names the test" in p
                            for p in self.problems()))

    def test_a_gap_that_says_nothing_fails(self):
        self.set_lesson("L8", gap=None)
        self.assertTrue(any("L8: a gap lesson says what is not held yet" in p
                            for p in self.problems()))

    def test_a_lesson_naming_a_game_fails(self):
        game = DATA["evidence"]["games"][0]
        self.set_lesson("L2", lesson=f"Seen in {game}: the ramp flipped.")
        self.assertTrue(any(f"L2: names the game {game!r}" in p for p in self.problems()))

    def test_evidence_for_an_unknown_lesson_fails(self):
        evidence = self.read("workspace/lessons/evidence.yaml")
        evidence["lessons"]["L99"] = {"games": [], "evidence": []}
        self.write("workspace/lessons/evidence.yaml", evidence)
        self.assertTrue(any("'L99'" in p for p in self.problems()))


class GuardedBy(unittest.TestCase):
    def test_a_finding_of_a_lessons_check_carries_the_lesson(self):
        guards = registry.guards(DATA["lessons"], DATA["tiers"], "playability-report",
                                 "content.units_reachable@desktop")
        self.assertEqual([g["lesson"] for g in guards], ["L5"])
        self.assertEqual(guards[0]["check"], "playability:content.units_reachable")
        self.assertTrue(guards[0]["tests"])

    def test_a_split_production_finding_carries_its_checks_lesson(self):
        guards = registry.guards(DATA["lessons"], DATA["tiers"], "production-quality-report",
                                 "assets.runtime/develop@mobile")
        self.assertEqual([g["lesson"] for g in guards], ["L3"])

    def test_a_browser_qa_finding_through_the_qa_report_carries_its_lesson(self):
        guards = registry.guards(DATA["lessons"], DATA["tiers"], "qa-report",
                                 "browser.context-menu:mobile@mobile")
        self.assertEqual([g["lesson"] for g in guards], ["L25"])
        self.assertEqual(guards[0]["check"], "browser-qa:browser.context-menu")

    def test_a_play_realism_finding_carries_its_lesson(self):
        guards = registry.guards(DATA["lessons"], DATA["tiers"], "playability-report",
                                 "naive.clear_rate@desktop")
        self.assertEqual([g["lesson"] for g in guards], ["L23"])

    def test_a_check_no_lesson_names_carries_nothing(self):
        self.assertEqual(registry.guards(DATA["lessons"], DATA["tiers"],
                                         "playability-report", "probe.present"), [])
        self.assertEqual(registry.guards(DATA["lessons"], DATA["tiers"], None, "x"), [])

    def test_triage_marks_the_finding(self):
        from wgf_triage import Routing, normalize
        from wgf_triage.step import _guard
        report = {"title_id": "demo", "commit": "c" * 40, "verdict": "FAIL",
                  "checks": [{"id": "content.units_reachable", "project": "desktop",
                              "status": "FAIL", "required": True, "summary": "late"}]}
        found = normalize("playability-report", report, Routing.load())
        _guard(found)
        self.assertEqual(found[0]["guarded_by"][0]["lesson"], "L5")


# ------------------------------------------------- where each source's results are read

def _fixture(producer):
    from wgflib import paths
    path = os.path.join(paths.WGFLIB, "workflow", "fixtures", f"{producer}.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validator(producer):
    from wgflib import jsonschema_lite as js
    from wgflib import paths
    from wgflib.workflow.contracts import load_registry
    with open(os.path.join(paths.ARTIFACTS, f"{producer}.schema.json"),
              encoding="utf-8") as handle:
        return js.Validator(json.load(handle), load_registry())


def _with_result(source, check, failing):
    """The producer's mock fixture report, carrying one result for `check` of `source` in the
    shape the producer's schema gives it: failing, or passing."""
    producer = DATA["tiers"]["sources"][source]["producer"]
    report = copy.deepcopy(_fixture(producer))
    status = "FAIL" if failing else "PASS"
    # The fixture's own result for the check, if it has one, is replaced.
    if isinstance(report.get("checks"), list):
        report["checks"] = [c for c in report["checks"]
                            if str(c.get("id")).split(":", 1)[0] != check]
    if isinstance(report.get("consistency"), dict):
        report["consistency"]["rule_results"] = [
            r for r in report["consistency"]["rule_results"] if r.get("criterion_id") != check]
    if source == "quality-floor":
        report["criteria"].append({
            "id": check, "layer": "universal", "dimension": "gameplay", "severity": "blocker",
            "status": status, "score": 0 if failing else 100, "owner": "gameplay",
            "route": "develop", "summary": "measured"})
    elif source == "quality-dimension":
        for dimension in report["dimensions"]:
            if dimension["id"] == check:
                dimension["status"] = "BELOW_FLOOR" if failing else "PASS"
    elif source == "visual-qa-blocker":
        report["findings"] = [{"id": check, "severity": "blocker", "category": "assets",
                               "summary": "seen", "route": "assets"}] if failing else []
        report["verdict"] = status
    elif source == "visual-qa-score":
        report["scores"][check] = 1 if failing else 4
    elif source == "gate-gaming":
        report["blockers"] = [{"id": f"gate-gaming-{check}-1", "file": None,
                               "summary": "flagged", "severity": "blocker"}] if failing else []
        report["verdict"] = "request-changes" if failing else "approve"
    elif source == "design-consistency":
        report["consistency"]["rule_results"].append(
            {"criterion_id": check, "breached": failing})
    elif source in ("browser-qa", "browser-qa-run"):
        report["checks"].append({
            "id": check + (":mobile" if source == "browser-qa" else ""), "category": "gameplay",
            "title": check, "status": status, "required": True, "message": "measured",
            "evidence": [{"kind": "observation", "summary": "measured"}]})
    elif source == "content-sufficiency":
        report["checks"].append({"id": check, "status": status, "required": True,
                                 "summary": "measured"})
    elif source in ("playability", "play-realism"):
        report["checks"].append({"id": check, "project": "desktop", "status": status,
                                 "required": True, "summary": "measured"})
    elif source == "production-quality":
        report["checks"].append({"id": check, "status": status, "required": True,
                                 "summary": "measured", "route": "develop"})
    elif source == "model-review":
        report["items"][0]["quality"] = {
            "verdict": "fail" if failing else "pass",
            "checks": [{"id": check, "status": "fail" if failing else "pass",
                        "summary": "measured"}]}
    else:
        raise AssertionError(f"no report shape for source {source}")
    return producer, report


class StatusAt(unittest.TestCase):
    """check-tiers.yaml 1.1.0 `status_at`: for every source, a report of its producer - the
    engine's fixture of it, schema-valid, carrying a result for one of the source's checks -
    resolves that check's result, failing and passing; and a report without it is
    UNMEASURED, never a pass."""

    def test_every_source_has_a_locator(self):
        for name in DATA["tiers"]["sources"]:
            self.assertIsInstance(registry.status_at(DATA["tiers"], name), dict, name)

    def test_every_source_resolves_a_real_report_of_its_producer(self):
        for name in DATA["tiers"]["sources"]:
            check = next(e["id"] for e in CHECKS.values() if e["source"] == name)
            for failing in (True, False):
                with self.subTest(source=name, check=check, failing=failing):
                    producer, report = _with_result(name, check, failing)
                    errors = [e for e in _validator(producer).iter_errors(report)
                              if "provenance" not in str(e)]  # the engine seals it
                    self.assertEqual(errors, [], f"{producer} fixture is not schema-valid")
                    found = registry.check_status(DATA["tiers"], f"{name}:{check}", report)
                    statuses = {r["status"] for r in found}
                    if name == "visual-qa-score":
                        self.assertEqual(statuses, {"MEASURED"})
                        self.assertEqual(found[0]["value"], 1 if failing else 4)
                    elif name == "visual-qa-blocker":
                        # a blocker finding cannot be attributed to one rubric blocker
                        self.assertEqual(statuses, {"UNMEASURED" if failing else "PASS"})
                    else:
                        self.assertEqual(statuses, {"FAIL" if failing else "PASS"})

    def test_a_check_the_report_does_not_carry_is_unmeasured(self):
        report = _fixture("playability-report")
        report["checks"] = [c for c in report.get("checks") or []
                            if c.get("id") != "depth.ramp"]
        found = registry.check_status(DATA["tiers"], "playability:depth.ramp", report)
        self.assertEqual([r["status"] for r in found], ["UNMEASURED"])
        # No report at all is unmeasured too, whatever the source says of an absent entry.
        found = registry.check_status(DATA["tiers"], "play-realism:naive.clear_rate", {})
        self.assertEqual([r["status"] for r in found], ["UNMEASURED"])
        failed_review = dict(_fixture("review-report"), verdict="request-changes", blockers=[])
        found = registry.check_status(DATA["tiers"], "gate-gaming:play-area-change",
                                      failed_review)
        self.assertEqual([r["status"] for r in found], ["UNMEASURED"])

    def test_a_check_its_producer_reports_only_where_it_applies_is_not_applicable(self):
        # play-realism (1.2.0 not_reported): a finished playability-report on which realism
        # ran, with no physics check, of a 3D run - not applicable, never a pass.
        report = _fixture("playability-report")
        report["verdict"] = "PASS"
        report["checks"] = [c for c in report.get("checks") or []
                            if not str(c.get("id")).startswith(("physics.", "runtime."))]
        report["checks"].append({"id": "runtime.console_errors", "project": "desktop",
                                 "status": "PASS", "required": True, "summary": "clean"})
        cid = "play-realism:physics.collider_size"
        found = registry.check_status(DATA["tiers"], cid, report, {"render": "3d"})
        self.assertEqual([r["status"] for r in found], ["NOT_APPLICABLE"])
        self.assertIn("2D board", found[0]["why"])
        # Without the evidence its group names, the same absence is UNMEASURED: no facts, a
        # 2D run whose design moves a body, realism that never ran, a report that blocked.
        self.assertEqual(registry.check_status(DATA["tiers"], cid, report)[0]["status"],
                         "UNMEASURED")
        design = {"build_spec": {"assets": [{"id": "ball", "role": "projectile"}]}}
        facts = {"render": "2d", "reports": {"game-design": design}}
        self.assertEqual(registry.check_status(DATA["tiers"], cid, report, facts)[0]["status"],
                         "UNMEASURED")
        facts["reports"]["game-design"] = {"build_spec": {"assets": [{"id": "hero",
                                                                      "role": "player"}]}}
        self.assertEqual(registry.check_status(DATA["tiers"], cid, report, facts)[0]["status"],
                         "NOT_APPLICABLE")
        ran_nothing = dict(report, checks=[c for c in report["checks"]
                                           if not c["id"].startswith("runtime.")])
        self.assertEqual(registry.check_status(DATA["tiers"], cid, ran_nothing,
                                               {"render": "3d"})[0]["status"], "UNMEASURED")
        blocked = dict(report, verdict="BLOCKED")
        self.assertEqual(registry.check_status(DATA["tiers"], cid, blocked,
                                               {"render": "3d"})[0]["status"], "UNMEASURED")

    def test_level_checks_absent_only_once_the_content_data_was_read(self):
        report = dict(_fixture("playability-report"), verdict="PASS")
        report["checks"] = [c for c in report.get("checks") or []
                            if not str(c.get("id")).startswith("level.")]
        cid = "play-realism:level.geometry"
        read = {"checks": [{"id": "content.data_present", "status": "PASS"}]}
        self.assertEqual(registry.check_status(DATA["tiers"], cid, report, {"reports": {
            "content-sufficiency-report": read}})[0]["status"], "NOT_APPLICABLE")
        for facts in (None, {"reports": {"content-sufficiency-report": {"checks": [
                {"id": "content.data_present", "status": "FAIL"}]}}}):
            self.assertEqual(registry.check_status(DATA["tiers"], cid, report,
                                                   facts)[0]["status"], "UNMEASURED", facts)

    def test_a_proxy_its_producer_made_advisory_is_covered(self):
        # realism.gate_clearance: level.clearance advisory because the clear rate measured
        # every failing unit - covered; a unit with no clear rate keeps it unmeasured.
        entry = {"id": "level.clearance", "project": "build", "status": "WARNING",
                 "required": False, "summary": "s",
                 "measured": {"gate": {"w3-l7": "advisory"}}}
        report = {"verdict": "PASS", "checks": [entry]}
        found = registry.check_status(DATA["tiers"], "play-realism:level.clearance", report)
        self.assertEqual((found[0]["status"], found[0].get("covered")), ("PASS", True))
        entry["measured"]["gate"]["w4-l7"] = "quality-gate"
        found = registry.check_status(DATA["tiers"], "play-realism:level.clearance", report)
        self.assertEqual(found[0]["status"], "WARNING")

    def test_a_per_viewport_browser_result_reads_as_its_check(self):
        _, report = _with_result("browser-qa", "browser.context-menu", True)
        report["checks"].append(dict(report["checks"][-1], id="browser.context-menu:desktop",
                                     status="PASS"))
        found = registry.check_status(DATA["tiers"], "browser-qa:browser.context-menu", report)
        self.assertEqual(sorted(r["status"] for r in found), ["FAIL", "PASS"])


class StatusAtIntegrity(Sandbox):
    def test_a_locator_path_the_producer_schema_lacks_fails(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["playability"]["status_at"] = {"list": "results", "id": "id"}
        self.write("core/reference/check-tiers.yaml", tiers)
        problems = self.problems()
        self.assertTrue(any("sources.playability: status_at 'results' is not a property of "
                            "playability-report.schema.json" in p for p in problems), problems)

    def test_a_nested_locator_path_is_followed_into_the_schema(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["model-review"]["status_at"]["list"] = "items[].quality.verdicts"
        self.write("core/reference/check-tiers.yaml", tiers)
        self.assertTrue(any("'items[].quality.verdicts' is not a property" in p
                            for p in self.problems()))

    def test_a_not_reported_group_on_absence_alone_fails(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["play-realism"]["status_at"]["not_reported"].append(
            {"checks": ["naive.pace"], "why": "guessed"})
        self.write("core/reference/check-tiers.yaml", tiers)
        self.assertTrue(any("needs `verdict` or `ran`" in p for p in self.problems()),
                        self.problems())

    def test_a_locator_key_outside_the_vocabulary_fails(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        tiers["sources"]["gate-gaming"]["status_at"]["guess"] = True
        self.write("core/reference/check-tiers.yaml", tiers)
        self.assertTrue(any("status_at has unknown key(s) guess" in p for p in self.problems()))

    def test_a_source_without_a_locator_fails_when_there_is_no_default(self):
        tiers = self.read("core/reference/check-tiers.yaml")
        del tiers["status_at"]
        self.write("core/reference/check-tiers.yaml", tiers)
        self.assertTrue(any("sources.production-quality: no `status_at`" in p
                            for p in self.problems()))


# --------------------------------------------- the producers' own output, read through it


def _real_play_realism():
    """The playability bot's realism judge on the regressed 2D head (68a12b7) and the
    accepted build: real records of a game the Factory built."""
    import test_play_realism as tpr
    head = tpr.real("physics-2d-head-run.json.gz")["visits"]["10-1"]["projects"]["mobile"]
    checks = tpr.realism.judge({"win": head}, tpr.D2, tpr.RULES, "mobile", tpr.RELEASE)
    return {"checks": [dict(c, project="mobile") for c in checks]}


def _real_browser_qa(name=None):
    """Browser QA's judge (wgf_verification.browser_qa.judge) on a replayed fixture of a
    validation game, or on healthy records: the checks verify writes."""
    from browser_qa_fixture import healthy_records
    from wgf_verification import browser_qa
    contract = browser_qa.load_contract()
    if name is None:
        checks = browser_qa.judge(healthy_records(contract), contract, klass="release",
                                  action_audio=["pause", "launch"])
    else:
        with open(os.path.join(HERE, "fixtures", "browser-qa", name),
                  encoding="utf-8") as handle:
            fixture = json.load(handle)
        checks = browser_qa.judge(fixture["records"], contract, klass=fixture["klass"],
                                  action_audio=fixture["action_audio"],
                                  bundle=fixture["bundle"])
    return {"checks": [c.to_dict() for c in checks], "verdict": "FAIL"}


class RealProducerOutput(unittest.TestCase):
    """Each irregular locator read on what its producer actually writes."""

    def statuses(self, check, report):
        return sorted({r["status"] for r in registry.check_status(DATA["tiers"], check,
                                                                  report)})

    def test_browser_qa_from_the_judge_on_a_validation_games_records(self):
        failing = _real_browser_qa("brick-breaker-worlds-894b4b8.json")
        self.assertEqual(self.statuses("browser-qa:browser.context-menu", failing), ["FAIL"])
        self.assertIn("FAIL", self.statuses("browser-qa:browser.ui-covers-play", failing))
        healthy = _real_browser_qa()
        self.assertEqual(self.statuses("browser-qa:browser.context-menu", healthy), ["PASS"])

    def test_play_realism_from_the_bot_on_the_regressed_head(self):
        report = _real_play_realism()
        self.assertEqual(self.statuses("play-realism:physics.undrawn_collision", report),
                         ["FAIL"])

    def test_gate_gaming_from_the_review_precheck(self):
        from wgf_review import gaming
        result = {"commits": [{"commit": "c" * 40, "owner": "level-design",
                               "findings": ["content.units_reachable"],
                               "flags": [{"status": "flagged", "pattern": "play-area-change",
                                          "file": "src/game/level.ts",
                                          "detail": "bounds.height 600 -> 420"}]}]}
        review = {"verdict": "request-changes", "blockers": gaming.blockers(result)}
        self.assertTrue(review["blockers"][0]["id"].startswith("gate-gaming-"))
        self.assertEqual(self.statuses("gate-gaming:play-area-change", review), ["FAIL"])
        self.assertEqual(self.statuses("gate-gaming:sprite-size-without-collider", review),
                         ["UNMEASURED"])
        self.assertEqual(self.statuses("gate-gaming:play-area-change",
                                       {"verdict": "approve", "blockers": []}), ["PASS"])

    def test_design_consistency_from_the_design_steps_evaluator(self):
        from wgf_design import consistency
        from wgflib import paths
        fixtures = os.path.join(paths.WGFLIB, "workflow", "fixtures")
        with open(os.path.join(fixtures, "game-design.json"), encoding="utf-8") as handle:
            design = json.load(handle)
        with open(os.path.join(fixtures, "title-strategy.json"), encoding="utf-8") as handle:
            strategy = json.load(handle)
        block = consistency.evaluate(design, strategy, [], "2026-10-08T00:00:00Z")[0]
        report = {"consistency": block}
        breached = {r["criterion_id"]: r["breached"] for r in block["rule_results"]}
        for rule_id, hit in breached.items():
            with self.subTest(rule=rule_id):
                self.assertEqual(self.statuses(f"design-consistency:{rule_id}", report),
                                 ["FAIL" if hit else "PASS"])

    def test_model_review_from_the_model_checks_on_a_real_glb(self):
        from wgf_assets import model_quality
        with open(os.path.join(HERE, "fixtures", "models", "hover-car.glb"), "rb") as handle:
            quality = model_quality.assess(handle.read(), role="player")["quality"]
        manifest = {"items": [{"id": "car", "quality": quality}]}
        for entry in quality["checks"]:
            with self.subTest(check=entry["id"]):
                self.assertEqual(self.statuses(f"model-review:{entry['id']}", manifest),
                                 [{"pass": "PASS", "fail": "FAIL",
                                   "skipped": "SKIPPED"}[entry["status"]]])

    def test_visual_qa_blockers_from_a_real_judges_verdict(self):
        from wgf_visualqa import rubric
        with open(os.path.join(HERE, "fixtures", "visual-qa", "arena-dodge.judge-verdict.json"),
                  encoding="utf-8") as handle:
            verdict = json.load(handle)
        loaded = rubric.load_rubric()
        decided, _failed, _routes = rubric.decide(verdict, loaded)[:3]
        report = {"findings": verdict["findings"], "verdict": decided}
        # The judge named its blocker "flat-primitive-entities": no rubric blocker id. It is
        # not attributed to one, so every rubric blocker is unmeasured - never a pass.
        self.assertNotIn(verdict["findings"][0]["id"],
                         [b["id"] for b in loaded["blockers"]])
        for blocker in loaded["blockers"]:
            self.assertEqual(self.statuses(f"visual-qa-blocker:{blocker['id']}", report),
                             ["UNMEASURED"])
        clean = dict(verdict, findings=[f for f in verdict["findings"]
                                        if f["severity"] != "blocker"])
        report = {"findings": clean["findings"], "verdict": rubric.decide(clean, loaded)[0]}
        self.assertEqual(self.statuses("visual-qa-blocker:primitive-entity", report), ["PASS"])
        blocked = {"findings": [], "verdict": "BLOCKED"}
        self.assertEqual(self.statuses("visual-qa-blocker:primitive-entity", blocked),
                         ["UNMEASURED"])


class ParityWithScoring(unittest.TestCase):
    """The quality gate reads a producer's checks (wgf_quality.scoring._measure); the registry
    reads them through `status_at`. Two readers of one report must agree: on real producer
    reports, for every check the floor reads by id, the passes and the measured results are
    the same."""

    def reports(self):
        import test_quality_gate as tqg
        docs = tqg.release_build()
        out = [(p, docs[p]) for p in ("playability-report", "production-quality-report",
                                      "content-sufficiency-report")]
        broken = tqg.mobile_40(copy.deepcopy(docs))
        out += [(p, broken[p]) for p in ("playability-report", "production-quality-report")]
        out.append(("playability-report", _real_play_realism()))
        out.append(("verification-report", _real_browser_qa("sky-marble-c340631.json")))
        out.append(("verification-report", _real_browser_qa()))
        return out

    def test_both_readers_agree_on_real_reports(self):
        from wgf_quality import scoring
        compared = 0
        for producer, report in self.reports():
            sources = [n for n, s in DATA["tiers"]["sources"].items()
                       if s.get("producer") == producer]
            ids = sorted({str(c.get("id")).split(":", 1)[0]
                          for c in report.get("checks") or []})
            for check in ids:
                source = next((s for s in sources if f"{s}:{check}" in CHECKS), None)
                if source is None:
                    continue
                with self.subTest(producer=producer, check=check):
                    evaluate = {"kind": "checks", "checks": [check, f"{check}:*"],
                                "required_only": False}
                    observed, _share, measured = scoring._measure(evaluate, report)
                    found = registry.check_status(DATA["tiers"], f"{source}:{check}", report)
                    counted = [r for r in found if r["status"] in scoring.MEASURED]
                    if not measured:
                        self.assertEqual(counted, [])
                        continue
                    self.assertEqual(observed["of"], len(counted))
                    self.assertEqual(observed["passed"],
                                     sum(r["status"] == "PASS" for r in counted))
                    compared += 1
        self.assertGreater(compared, 40)


class Integrity(unittest.TestCase):
    def test_check_integrity_runs_the_registry(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_integrity_registry", os.path.join(SCRIPTS, "check-integrity.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            module.ERRORS.clear()
            checks, lessons = module.check_regression_registry()
        finally:
            os.chdir(cwd)
        self.assertEqual(module.ERRORS, [])
        self.assertGreater(len(checks), 100)
        self.assertEqual(len(lessons), 28)


if __name__ == "__main__":
    unittest.main()
