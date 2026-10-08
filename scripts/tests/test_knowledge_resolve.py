"""The applicability resolver (K1): which rules apply to a run's facets, and why.

These tests hold, each with its negative:

  * a rule without scope applies to every facet set;
  * a family-, platform-, render- or tier-scoped rule applies only where its facet matches,
    and is listed as not applicable with the facet that excluded it;
  * scope keys are AND-ed, values OR-ed; a platform-scoped rule applies when any targeted
    platform is in its scope;
  * an undetermined facet never makes a rule inapplicable;
  * every resolution lists every excluded rule with a reason (process lessons included);
  * the validators a contract needs are the workflow steps that produce the blocking and
    required rules' checks, and a producer no step outputs is a missing validator;
  * a contract built from a resolution is valid against knowledge-contract.schema.json, and
    one with a missing validator is not;
  * exceptions: a person's valid one is listed, an expired, unauthorized or inapplicable one
    is refused with why;
  * `wgf knowledge` validate / show / resolve / contract / table, and their exit codes.

    python -m unittest scripts.tests.test_knowledge_resolve
"""

import copy
import datetime
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

from wgf_knowledge import cli, model, resolve as resolver, versions  # noqa: E402
from wgf_quality import registry  # noqa: E402
from wgflib import jsonschema_lite as js, provenance  # noqa: E402
from wgflib.workflow.contracts import load_registry  # noqa: E402
from wgflib.yamllite import load as load_yaml  # noqa: E402

DATA = registry.load(ROOT)
CHECKS, _ = registry.classify(DATA["tiers"], ROOT)
TIERS = DATA["tiers"]
LESSONS = DATA["lessons"]
with open(os.path.join(ROOT, "core", "workflows", "new-game.workflow.yaml"),
          encoding="utf-8") as _handle:
    WORKFLOW = load_yaml(_handle.read())["workflow"]
WGF = os.path.join(SCRIPTS, "wgf.py")
NOW = datetime.datetime(2026, 10, 8, 12, 0, tzinfo=datetime.timezone.utc)


def rule(lesson_id, scope, checks=("browser-qa:browser.context-menu",)):
    return {"id": lesson_id, "title": lesson_id, "category": "browser", "problem": "p",
            "root_cause": "r", "lesson": "l", "scope": scope, "status": "enforced",
            "lifecycle": "active", "checks": list(checks),
            "tests": {"catches": [f"scripts/tests/test_x.py::test_{lesson_id.lower()}"],
                      "passes": [], "generalizes": []}}


def knowledge(*rules):
    data = copy.deepcopy(LESSONS)
    data["lessons"] = list(rules)
    return data


def resolve(data, **facets):
    return resolver.resolve(data, CHECKS, TIERS, resolver.facets(**facets), workflow=WORKFLOW)


def ids(body):
    return [r["id"] for r in body["rules"]]


def why_not(body, lesson_id):
    return next(e["why_not"] for e in body["not_applicable"] if e["id"] == lesson_id)


class Applicability(unittest.TestCase):
    def test_a_lesson_without_scope_applies_to_every_facet_set(self):
        data = knowledge(rule("G1", "global"))
        for facets in ({}, {"family": "puzzle", "render": "3d", "platforms": ["y8"],
                            "tier": "mvp"}, {"family": "racing", "tier": "release"}):
            with self.subTest(facets=facets):
                body = resolve(data, **facets)
                self.assertEqual(ids(body), ["G1"])
                self.assertEqual(body["rules"][0]["why_applicable"], ["global"])

    def test_a_family_scoped_lesson_applies_only_to_that_family(self):
        data = knowledge(rule("F1", {"families": ["platformer", "racing"]}))
        self.assertEqual(ids(resolve(data, family="racing")), ["F1"])
        body = resolve(data, family="puzzle")
        self.assertEqual(ids(body), [])
        self.assertEqual(why_not(body, "F1"),
                         "family puzzle is not in its scope (platformer, racing)")

    def test_a_platform_scoped_lesson_applies_when_any_target_matches(self):
        data = knowledge(rule("P1", {"platforms": ["y8"]}))
        body = resolve(data, platforms=["yandex", "y8"])
        self.assertEqual(ids(body), ["P1"])
        self.assertEqual(body["rules"][0]["why_applicable"], ["platforms y8 in scope"])
        body = resolve(data, platforms=["yandex", "crazygames"])
        self.assertEqual(ids(body), [])
        self.assertIn("none of them is in its scope (y8)", why_not(body, "P1"))

    def test_a_render_scoped_lesson(self):
        body = resolve(LESSONS, render="2d")
        self.assertNotIn("L15", ids(body))
        self.assertEqual(why_not(body, "L15"), "render 2d is not in its scope (3d)")
        self.assertIn("L15", ids(resolve(LESSONS, render="3d")))

    def test_a_release_tier_lesson_is_not_applicable_to_mvp_with_its_reason(self):
        data = knowledge(rule("T1", {"tiers": ["release"]}))
        body = resolve(data, tier="mvp")
        self.assertEqual(ids(body), [])
        self.assertEqual(why_not(body, "T1"), "tier mvp is not in its scope (release)")
        self.assertEqual(ids(resolve(data, tier="release")), ["T1"])
        # the shipped one
        self.assertIn("tier mvp is not in its scope", why_not(resolve(LESSONS, tier="mvp"),
                                                              "L9"))

    def test_scope_keys_are_anded_values_ored(self):
        data = knowledge(rule("C1", {"families": ["arcade", "shooter"], "render": ["2d"],
                                     "tiers": ["release"]}))
        self.assertEqual(ids(resolve(data, family="shooter", render="2d", tier="release")),
                         ["C1"])
        self.assertEqual(ids(resolve(data, family="arcade", render="2d", tier="release")),
                         ["C1"])
        for facets, excluded_by in (({"family": "arcade", "render": "3d", "tier": "release"},
                                     "render 3d"),
                                    ({"family": "puzzle", "render": "2d", "tier": "release"},
                                     "family puzzle"),
                                    ({"family": "arcade", "render": "2d", "tier": "mvp"},
                                     "tier mvp")):
            with self.subTest(facets=facets):
                body = resolve(data, **facets)
                self.assertEqual(ids(body), [])
                self.assertTrue(why_not(body, "C1").startswith(excluded_by))

    def test_an_undetermined_facet_never_makes_a_rule_inapplicable(self):
        data = knowledge(rule("U1", {"families": ["racing"], "render": ["3d"],
                                     "platforms": ["y8"], "tiers": ["release"]}))
        body = resolve(data)
        self.assertEqual(ids(body), ["U1"])
        why = body["rules"][0]["why_applicable"]
        self.assertEqual(len(why), 4)
        self.assertTrue(all("undetermined: applies" in w for w in why), why)
        # one facet determined and matching, the others still undetermined
        body = resolve(data, render="3d")
        self.assertIn("render 3d in scope", body["rules"][0]["why_applicable"])
        # a determined facet that does not match still excludes it
        self.assertEqual(ids(resolve(data, render="2d")), [])

    def test_a_rule_with_no_or_an_unreadable_scope_applies(self):
        legacy = rule("O1", "global")
        del legacy["scope"]
        body = resolve(knowledge(legacy, rule("O2", 42)), render="2d", tier="mvp")
        self.assertEqual(ids(body), ["O1", "O2"])
        self.assertEqual(body["rules"][0]["why_applicable"], ["no scope declared: applies"])
        self.assertIn("unreadable: applies", body["rules"][1]["why_applicable"][0])

    def test_a_run_that_pinned_lessons_1x_resolves_every_rule_as_global(self):
        legacy = copy.deepcopy(LESSONS)
        legacy["version"] = "1.0.0"
        for lesson in legacy["lessons"]:
            for key in ("scope", "lifecycle", "category", "problem", "root_cause"):
                lesson.pop(key, None)
            lesson["tests"] = model.all_tests(lesson)
        body = resolve(legacy, render="2d", tier="mvp")
        self.assertEqual({e["id"] for e in body["not_applicable"]}, {"L6", "L19"})
        self.assertEqual(body["counts"]["blocking"], 6)

    def test_every_resolution_lists_its_excluded_rules_with_reasons(self):
        for facets in ({}, {"render": "2d", "tier": "mvp"}, {"render": "3d", "tier": "release"}):
            with self.subTest(facets=facets):
                body = resolve(LESSONS, **facets)
                listed = ids(body) + [e["id"] for e in body["not_applicable"]]
                self.assertEqual(sorted(listed), sorted(l["id"] for l in LESSONS["lessons"]))
                self.assertTrue(all(e["why_not"] for e in body["not_applicable"]))
                for process in ("L6", "L19"):
                    self.assertIn("a process lesson", why_not(body, process))
                self.assertEqual(body["counts"]["not_applicable"], len(body["not_applicable"]))

    def test_a_deprecated_rule_is_excluded_with_its_successor(self):
        old = dict(rule("D1", "global"), lifecycle="deprecated", superseded_by="D2")
        body = resolve(knowledge(old, rule("D2", "global")))
        self.assertEqual(ids(body), ["D2"])
        self.assertEqual(why_not(body, "D1"), "deprecated: superseded by D2")

    def test_the_rule_carries_its_level_checks_and_tests(self):
        body = resolve(LESSONS, family="arcade", render="2d", platforms=["yandex"],
                       tier="release")
        l23 = next(r for r in body["rules"] if r["id"] == "L23")
        self.assertEqual((l23["level"], l23["derived_level"], l23["category"]),
                         ("required", "required", "level_design"))
        self.assertEqual({c["check"]: (c["tier"], c["producer"], tuple(c["steps"]))
                          for c in l23["checks"]},
                         {"play-realism:level.clearance": (
                             "quality", "playability-report",
                             ("greybox-playability", "playability")),
                          "play-realism:naive.clear_rate": (
                             "quality", "playability-report",
                             ("greybox-playability", "playability"))})
        self.assertTrue(l23["tests"]["catches"] and l23["tests"]["passes"])
        for test in model.all_tests(model_lesson("L23")):
            self.assertIn(test, body["regression_suite"])
        self.assertEqual(body["counts"], {"blocking": 5, "required": 14, "recommended": 0,
                                          "experimental": 6, "not_applicable": 3})
        self.assertEqual({e["id"] for e in body["experimental"]},
                         {"L8", "L9", "L16", "L17", "L18", "L21"})

    def test_facets_from_a_design_and_a_strategy(self):
        design = {"genre": {"family": "racing", "node": "kart"}, "engine": {"dimension": "3d"}}
        strategy = {"platform_set": [{"id": "yandex"}, {"id": "y8"}]}
        self.assertEqual(resolver.facets_from(design, strategy, "release"),
                         {"family": "racing", "genre": "kart", "render": "3d",
                          "platforms": ["y8", "yandex"], "tier": "release", "profile": None,
                          "archetype": None})
        self.assertEqual(resolver.facets_from(None, None, None), resolver.facets())


def model_lesson(lesson_id):
    return next(l for l in LESSONS["lessons"] if l["id"] == lesson_id)


class Validators(unittest.TestCase):
    def test_required_validators_are_the_steps_producing_blocking_and_required_checks(self):
        body = resolve(LESSONS, render="3d", tier="release")
        self.assertEqual(body["missing_validators"], [])
        self.assertEqual(set(body["required_validators"]),
                         {"assets", "content-sufficiency", "design", "greybox-playability",
                          "playability", "production-quality", "quality-gate", "review",
                          "sdk-review", "verify"})

    def test_a_producer_no_step_outputs_is_a_missing_validator(self):
        workflow = copy.deepcopy(WORKFLOW)
        workflow["steps"] = [s for s in workflow["steps"]
                             if "playability-report" not in (s.get("outputs") or ())]
        body = resolver.resolve(LESSONS, CHECKS, TIERS, resolver.facets(), workflow=workflow)
        missing = {(m["rule"], m["check"]) for m in body["missing_validators"]}
        self.assertIn(("L23", "play-realism:naive.clear_rate"), missing)
        self.assertNotIn("playability", body["required_validators"])

    def test_an_experimental_rule_needs_no_validator(self):
        workflow = {"steps": []}
        data = knowledge(dict(rule("E1", "global"), status="gap", lifecycle="candidate",
                              checks=[], gap="nothing holds it"))
        body = resolver.resolve(data, CHECKS, TIERS, resolver.facets(), workflow=workflow)
        self.assertEqual(body["missing_validators"], [])
        self.assertEqual(body["experimental"], [{"id": "E1", "gap": "nothing holds it"}])


def contract(body, title_id="demo"):
    out = dict(body)
    out["title_id"] = title_id
    out["provenance"] = provenance.seal({"provenance": provenance.build(
        "knowledge-contract", artifact_id="wgf:knowledge-contract:demo:20261008-01",
        produced_by=provenance.producer("game-designer"),
        produced_at="2026-10-08T12:00:00Z")})["provenance"]
    return out


class ContractSchema(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "core", "artifacts", "knowledge-contract.schema.json"),
                  encoding="utf-8") as handle:
            self.validator = js.Validator(json.load(handle), load_registry())

    def body(self, **facets):
        found = versions.collect(root=ROOT, workflow=WORKFLOW,
                                 platforms=facets.get("platforms") or ())
        return dict({"versions": found}, **resolver.resolve(
            LESSONS, CHECKS, TIERS, resolver.facets(**facets), workflow=WORKFLOW,
            versions=found))

    def test_a_resolution_is_a_valid_contract(self):
        for facets in ({}, {"family": "arcade", "render": "2d", "platforms": ["yandex"],
                            "tier": "release"}):
            with self.subTest(facets=facets):
                document = contract(self.body(**facets))
                self.assertEqual(self.validator.iter_errors(document), [])

    def test_the_contract_records_the_versioned_constraints(self):
        body = self.body(family="arcade", platforms=["yandex"])
        self.assertRegex(body["constraints"]["genre"], r"^genre-models@[0-9.]+#arcade$")
        self.assertRegex(body["constraints"]["platforms"][0], r"^yandex@[0-9.]+$")

    def test_a_contract_with_a_missing_validator_is_invalid(self):
        document = contract(self.body())
        document["missing_validators"] = [{"rule": "L23", "check": "x", "producer": "y"}]
        self.assertTrue(self.validator.iter_errors(document))

    def test_a_rule_level_outside_the_vocabulary_is_invalid(self):
        document = contract(self.body())
        document["rules"][0]["level"] = "mandatory"
        self.assertTrue(self.validator.iter_errors(document))


def exception(**changes):
    record = {"rule_id": "L26", "reason": "The HUD card overlap on tablet is accepted for "
              "this soft launch; the layout rework lands next release.", "scope": {},
              "approved_by": {"identifier": "a.person", "mode": "human"},
              "created_at": "2026-10-08T09:00:00Z", "expires_at": "2026-10-20T09:00:00Z"}
    record.update(changes)
    return record


class ContractExceptions(unittest.TestCase):
    def run_with(self, *records, now=NOW, **facets):
        return resolver.resolve(LESSONS, CHECKS, TIERS, resolver.facets(**facets),
                                workflow=WORKFLOW, exceptions=records, now=now)

    def test_a_persons_exception_is_listed(self):
        body = self.run_with(exception())
        self.assertEqual(body["exceptions"], [exception()])
        self.assertEqual(body["exceptions_refused"], [])

    def test_an_expired_exception_is_refused(self):
        later = datetime.datetime(2026, 10, 25, tzinfo=datetime.timezone.utc)
        body = self.run_with(exception(), now=later)
        self.assertEqual(body["exceptions"], [])
        self.assertIn("expired at 2026-10-20T09:00:00Z",
                      body["exceptions_refused"][0]["problems"])

    def test_an_unauthorized_exception_is_refused(self):
        body = self.run_with(exception(approved_by={"identifier": "develop",
                                                    "mode": "automation"}))
        self.assertEqual(body["exceptions"], [])
        self.assertTrue(body["exceptions_refused"][0]["problems"][0].startswith(
            "unauthorized"))

    def test_an_exception_for_a_rule_that_does_not_apply_is_refused(self):
        body = self.run_with(exception(rule_id="L15"), render="2d")
        self.assertEqual(body["exceptions"], [])
        self.assertEqual(body["exceptions_refused"][0]["problems"],
                         ["rule L15 does not apply to this run"])


class ReviewFixes(unittest.TestCase):
    """The independent review of K1: each loophole, closed and shown closed."""

    def test_an_unclassifiable_check_is_a_missing_validator_never_a_silent_exclusion(self):
        data = knowledge(rule("X1", "global", checks=("playability:no.such.check",)))
        body = resolve(data)
        self.assertEqual(ids(body), [])
        self.assertNotIn("X1", [e["id"] for e in body["not_applicable"]])
        self.assertEqual(body["missing_validators"],
                         [{"check": "playability:no.such.check", "producer": None,
                           "rule": "X1", "why": "no source of check-tiers classifies it"}])
        data = knowledge(dict(rule("X2", "global"), checks=[]))
        self.assertEqual(resolve(data)["missing_validators"][0]["rule"], "X2")

    def test_an_unknown_scope_key_applies_like_an_undetermined_facet(self):
        body = resolve(knowledge(rule("K1", {"engines": ["phaser"]})), render="2d")
        self.assertEqual(ids(body), ["K1"])
        self.assertEqual(body["rules"][0]["why_applicable"],
                         ["scope key 'engines' is not a facet: applies"])

    def test_facets_are_normalised_or_refused(self):
        self.assertEqual(resolver.facets(platforms="y8")["platforms"], ["y8"])
        self.assertEqual(resolver.facets(render="3D", family=" Racing ",
                                         platforms=["Y8", "y8", ""], tier="Release"),
                         {"family": "racing", "genre": None, "render": "3d",
                          "platforms": ["y8"], "tier": "release", "profile": None,
                          "archetype": None})
        for bad in ({"render": "4d"}, {"render": 3}, {"platforms": [7]}, {"family": ["a"]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resolver.facets(**bad)
        # a string platform matches as the platform, never as its letters
        body = resolve(knowledge(rule("P1", {"platforms": ["y8"]})), platforms="y8")
        self.assertEqual(ids(body), ["P1"])
        body = resolve(knowledge(rule("P2", {"platforms": ["y"]})), platforms="y8")
        self.assertEqual(ids(body), [])
        # facets passed to resolve() are normalised too
        self.assertEqual(ids(resolve(LESSONS, render="2D")), ids(resolve(LESSONS, render="2d")))
        self.assertEqual(resolver.facets_from({"engine": {"dimension": "3D"}})["render"], "3d")

    def test_a_lesson_retired_with_only_a_reason_stays_visible_as_advisory(self):
        retired = dict(rule("R1", "global", checks=("playability:probe.present",)),
                       lifecycle="deprecated", reason="replaced by the portal's own probe")
        body = resolve(knowledge(retired))
        self.assertEqual(ids(body), ["R1"])
        self.assertEqual(body["rules"][0]["level"], "recommended")
        self.assertIn("deprecated (replaced by the portal's own probe): reported as "
                      "advisory, never blocks", body["rules"][0]["why_applicable"])
        self.assertEqual(body["required_validators"], [])
        successor = dict(retired, superseded_by="R2")
        body = resolve(knowledge(successor, rule("R2", "global")))
        self.assertEqual(why_not(body, "R1"), "deprecated: superseded by R2")

    def test_no_exception_holds_without_the_time_it_is_read_at(self):
        body = resolver.resolve(LESSONS, CHECKS, TIERS, resolver.facets(), workflow=WORKFLOW,
                                exceptions=[exception()])
        self.assertEqual(body["exceptions"], [])
        self.assertTrue(any("no time was given" in p
                            for p in body["exceptions_refused"][0]["problems"]))

    def test_an_exception_scoped_to_a_platform_the_run_does_not_target_is_refused(self):
        vocabulary = model.vocabulary(ROOT)
        record = exception(scope={"platforms": ["crazygames"]})
        body = resolver.resolve(LESSONS, CHECKS, TIERS, resolver.facets(platforms=["y8"]),
                                workflow=WORKFLOW, exceptions=[record], now=NOW,
                                vocabulary=vocabulary)
        self.assertEqual(body["exceptions"], [])
        self.assertTrue(any("not targeted by this run" in p
                            for p in body["exceptions_refused"][0]["problems"]))
        record = exception(scope={"platforms": ["y8"]})
        body = resolver.resolve(LESSONS, CHECKS, TIERS, resolver.facets(platforms=["y8"]),
                                workflow=WORKFLOW, exceptions=[record], now=NOW,
                                vocabulary=vocabulary)
        self.assertEqual(body["exceptions"], [record])

    def test_platform_profiles_are_the_runs_pins_not_the_live_files(self):
        strategy = {"platform_set": [{"id": "yandex", "profile_version": "1.1.0"},
                                     {"id": "y8"}]}
        pins = resolver.platform_pins(strategy)
        self.assertEqual(pins, {"yandex": "yandex@1.1.0"})
        found = versions.collect(root=ROOT, platforms=["yandex", "y8"], pins=pins)
        self.assertEqual(found["platform_profiles"]["yandex"], "yandex@1.1.0")
        self.assertTrue(found["platform_profiles"]["y8"].startswith("y8@"))

        def read(relpath):
            if relpath == "core/reference/platforms/y8.yaml":
                return b"id: y8\nversion: 9.9.9\n"
            with open(os.path.join(ROOT, *relpath.split("/")), "rb") as handle:
                return handle.read()
        found = versions.collect(read=read, root=ROOT, platforms=["y8"])
        self.assertEqual(found["platform_profiles"]["y8"], "y8@9.9.9")

    def test_pinned_check_tiers_are_classified_against_pinned_files(self):
        live = registry._read(ROOT, "core/reference/browser-qa.yaml")
        pinned = copy.deepcopy(live)
        for check in pinned["checks"]:
            if check["id"] == "context-menu":
                check["tier"] = "hard"

        def reader(relative):
            if relative == "core/reference/browser-qa.yaml":
                return pinned
            return registry._read(ROOT, relative)
        checks, _ = registry.classify(TIERS, ROOT, reader=reader)
        self.assertEqual(checks["browser-qa:browser.context-menu"]["tier"], "hard")
        self.assertEqual(CHECKS["browser-qa:browser.context-menu"]["tier"], "quality")


class Cli(unittest.TestCase):
    def wgf(self, *args, expect=0):
        done = subprocess.run([sys.executable, WGF, *args], cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8",
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(done.returncode, expect, f"{args}\n{done.stdout}\n{done.stderr}")
        return done

    def test_validate_is_clean(self):
        self.assertIn("knowledge: OK", self.wgf("knowledge", "validate").stdout)
        self.assertEqual(json.loads(self.wgf("knowledge", "validate", "--runtime",
                                             "--json").stdout), {"ok": True, "problems": []})

    def test_show_lists_every_rule_and_one_in_full(self):
        rows = json.loads(self.wgf("knowledge", "show", "--json").stdout)["rules"]
        self.assertEqual(len(rows), 28)
        self.assertEqual(next(r for r in rows if r["id"] == "L6")["level"], "process")
        one = json.loads(self.wgf("knowledge", "show", "L25", "--json").stdout)
        self.assertEqual(one["level"], "required")
        self.assertEqual(one["checks"][0]["validators"], ["verify"])
        self.assertEqual(one["checks"][0]["status_at"]["id_split"], ":")
        self.wgf("knowledge", "show", "L99", expect=2)

    def test_resolve_prints_the_contract_body(self):
        out = json.loads(self.wgf("knowledge", "resolve", "--family", "arcade", "--render",
                                  "2d", "--platform", "yandex", "--tier", "release",
                                  "--json").stdout)
        self.assertEqual(out["counts"]["blocking"], 5)
        self.assertEqual(out["versions"]["lessons"]["version"], "2.0.0")
        text = self.wgf("knowledge", "resolve", "--render", "2d").stdout
        self.assertIn("excluded     L15: render 2d is not in its scope (3d)", text)

    def test_table_is_one_dry_row_per_facet_combination(self):
        rows = json.loads(self.wgf("knowledge", "table", "--families", "arcade,racing",
                                   "--render", "2d,3d", "--tiers", "release",
                                   "--json").stdout)["rows"]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["approved_by"] is None for r in rows))

    def test_a_bad_argument_and_an_unknown_run_are_unusable(self):
        self.wgf("knowledge", "frobnicate", expect=2)
        self.wgf("knowledge", "resolve", "--render", "4d", expect=2)
        scratch = tempfile.mkdtemp(prefix="wgf-knowledge-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.wgf("knowledge", "contract", "no-such-run", "--store", scratch, expect=2)

    def test_the_contract_of_a_run_without_one_is_resolved_from_what_it_holds(self):
        scratch = tempfile.mkdtemp(prefix="wgf-knowledge-")
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        config = os.path.join(scratch, "factory.yaml")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write("factory:\n  storage:\n    fsync: false\n")
        store = os.path.join(scratch, "store")
        self.wgf("new-game", "--mock", "--quiet", "--store", store, "--config", config,
                 expect=3)
        run_id = next(n for n in os.listdir(os.path.join(store, "workflows"))
                      if n.startswith("new-game-"))
        out = json.loads(self.wgf("knowledge", "contract", run_id, "--store", store,
                                  "--config", config, "--json").stdout)
        self.assertFalse(out["recorded"])
        self.assertEqual(out["facets"]["family"], "arcade")
        self.assertEqual(out["facets"]["tier"], "release")
        self.assertEqual(out["missing_validators"], [])
        # resolved from the knowledge the run pinned when it started
        self.assertEqual(out["versions"]["lessons"]["version"], "2.0.0")

    def test_the_python_entry_point_matches(self):
        done = subprocess.run([sys.executable, os.path.join(SCRIPTS, "wgf-knowledge.py"),
                               "validate"], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["show", "--json"]), 0)
        self.assertEqual(len(json.loads(out.getvalue())["rules"]), 28)


if __name__ == "__main__":
    unittest.main()
