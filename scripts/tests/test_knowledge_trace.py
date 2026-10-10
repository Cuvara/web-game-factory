"""K5: the design's decision trace, and the knowledge a design author is given.

  * the request    wgf_design/knowledge.py provisional: the resolver's output, structured -
                   each rule's id, revision, domain, principle, anti-pattern, level, checks,
                   and whether the design records a decision for it; never a process lesson
  * the trace      game-design `knowledge_applied` held by design-consistency
                   knowledge.trace_matches_design: a rule the design was not given, a unit it
                   does not have, a check that is not the rule's, a revision it was not
                   given, a claim of `applied` the design's own checks contradict - each a
                   breach; an absent trace is not one
  * compliance     the trace entry beside the measured status: a claim never satisfies a rule

    python -m unittest scripts.tests.test_knowledge_trace
"""

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
for _path in (SCRIPTS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_lesson_l29 as l29  # noqa: E402
from wgf_design import consistency, knowledge as design_knowledge  # noqa: E402
from wgf_quality import compliance, registry  # noqa: E402

TRACE = "knowledge.trace_matches_design"
DATA = registry.load(ROOT)
TIERS = DATA["tiers"]
REVISION = next(l for l in DATA["lessons"]["lessons"] if l["id"] == "L29")["revision"]


def given():
    return design_knowledge.provisional("puzzle", {})


def entry(**changes):
    out = {"rule": "L29", "revision": REVISION, "applied": True, "where": ["u-02", "u-03"],
           "how": "each unit debuts one element", "verified_by": [
               "design-consistency:content.introductions_one_at_a_time"]}
    out.update(changes)
    return out


def traced(units, *entries):
    design = l29.design_with(units)
    design["knowledge_applied"] = list(entries)
    return design


def result(design, knowledge="given"):
    knowledge = given() if knowledge == "given" else knowledge
    block, blocking, _ = consistency.evaluate(design, {}, [], l29.NOW, knowledge=knowledge)
    found = next(r for r in block["rule_results"] if r["criterion_id"] == TRACE)
    return found, blocking


class TheRequest(unittest.TestCase):
    def test_the_rules_are_the_resolvers_output_structured(self):
        knowledge = given()
        self.assertTrue(knowledge["provisional"])
        self.assertIn("knowledge_applied", knowledge["instruction"])
        ids = [r["id"] for r in knowledge["rules"]]
        self.assertNotIn("L6", ids)                      # a process lesson: never in a run
        self.assertNotIn("L19", ids)
        rule = next(r for r in knowledge["rules"] if r["id"] == "L29")
        self.assertEqual((rule["domain"], rule["level"], rule["version"], rule["trace"]),
                         ("level-design", "blocking", f"L29@r{REVISION}", True))
        self.assertEqual(rule["checks"], [
            "design-consistency:content.introductions_one_at_a_time",
            "content-sufficiency:content.introductions_one_at_a_time"])
        self.assertTrue(rule["principle"].startswith("After the opening unit"))
        self.assertIn("debuts two or more", rule["anti_pattern"])
        # a rule outside the design domains is given, and no decision is asked of it
        self.assertFalse(next(r for r in knowledge["rules"] if r["id"] == "L25")["trace"])

    def test_a_scope_the_known_facets_exclude_is_not_given(self):
        rules = {r["id"] for r in design_knowledge.provisional(
            "puzzle", {"platform_set": [{"id": "yandex"}]})["rules"]}
        self.assertIn("L29", rules)


class TheTrace(unittest.TestCase):
    def test_an_absent_trace_is_not_a_breach(self):
        found, blocking = result(l29.design_with(l29.paced()))
        self.assertFalse(found["breached"])
        self.assertIn("no decision trace", found["note"])
        self.assertNotIn(TRACE, blocking)

    def test_a_true_trace_holds(self):
        found, _ = result(traced(l29.paced(), entry(),
                                 entry(rule="L17", revision=1, applied=False, where=[],
                                       verified_by=[],
                                       how="not held by a check yet")))
        self.assertFalse(found["breached"], found)
        self.assertIn("2 trace entr(ies), 1 applied", found["note"])

    def test_a_claim_the_design_contradicts_is_a_breach(self):
        found, blocking = result(traced(l29.doubled(), entry()))
        self.assertTrue(found["breached"])
        self.assertIn(TRACE, blocking)
        self.assertIn("claims the rule applied, and this design breaks it", str(found["measured"]))
        self.assertIn("contradicted: L29", found["note"])

    def test_each_false_statement_is_a_breach(self):
        for bad, text in ((entry(rule="L999"), "names a rule the design was not given"),
                          (entry(where=["u-02", "u-99"]), "unit(s) the design does not have: u-99"),
                          (entry(verified_by=["browser-qa:browser.overflow"]),
                           "not checks of L29"),
                          (entry(revision=REVISION + 1),
                           f"claims revision {REVISION + 1}; the design was given r{REVISION}")):
            with self.subTest(text=text):
                found, _ = result(traced(l29.paced(), bad))
                self.assertTrue(found["breached"])
                self.assertIn(text, str(found["measured"]))

    def test_a_trace_with_no_knowledge_to_check_it_against_is_a_breach(self):
        found, _ = result(traced(l29.paced(), entry()), knowledge=None)
        self.assertTrue(found["breached"])
        self.assertIn("cannot be checked", str(found["measured"]))

    def test_the_trace_summary_the_contract_records(self):
        design = traced(l29.doubled(), entry())
        block, _blocking, _ = consistency.evaluate(design, {}, [], l29.NOW, knowledge=given())
        summary = design_knowledge.trace_summary(design, block)
        self.assertEqual(summary, {"present": True, "applied": ["L29"],
                                   "contradicted": ["L29"]})


class GivenNotReResolved(unittest.TestCase):
    """The trace is held against the knowledge the author was given (its request), not
    against knowledge resolved again from the finished design: a design whose family
    differs from its starting draft's keeps its trace valid."""

    def test_the_knowledge_given_is_what_the_trace_is_checked_against(self):
        from wgf_design.step import DesignStep
        given_for_puzzle = design_knowledge.provisional("puzzle", {})
        # what the request carried: the rules for the starting draft's family, one of them
        # narrowed here to that family so a re-resolution over another family would drop it
        given = dict(given_for_puzzle, rules=list(given_for_puzzle["rules"]) + [{
            "id": "L900", "level": "experimental", "checks": [], "trace": True,
            "revision": 1}])
        author = type("Author", (), {"given_knowledge": given})()
        design = traced(l29.paced(), entry(),
                        {"rule": "L900", "revision": 1, "applied": False,
                         "how": "not applicable to the final game"})
        design["genre"] = dict(design.get("genre") or {}, family="racing")
        chosen = DesignStep.given_knowledge(author, design, {}, None)
        self.assertIs(chosen, given)
        found, _ = result(design, knowledge=chosen)
        self.assertFalse(found["breached"], found)
        # re-resolved from the final design, the same trace would name a rule not given
        found, _ = result(design, knowledge=design_knowledge.provisional("racing", {}))
        self.assertTrue(found["breached"])
        self.assertIn("L900", str(found["measured"]))

    def test_an_author_that_records_none_is_held_against_the_designs_own_family(self):
        from wgf_design.step import DesignStep
        design = l29.design_with(l29.paced())
        chosen = DesignStep.given_knowledge(object(), design, {}, None)
        self.assertEqual(chosen["facets"]["family"], design["genre"]["family"])

    def test_knowledge_that_could_not_be_read_stays_unreadable(self):
        from wgf_design.step import DesignStep
        author = type("Author", (), {"given_knowledge": None})()
        self.assertIsNone(DesignStep.given_knowledge(author, {}, {}, None))


class Compliance(unittest.TestCase):
    """A claim is shown beside the measured status; it never makes a rule satisfied."""

    def test_a_claim_never_satisfies_a_rule(self):
        contract = {"rules": [{"id": "L29", "title": "t", "level": "blocking",
                               "category": "level_design", "checks": [
                                   {"check": "content-sufficiency:content.introductions_one_at_a_time",
                                    "tier": "hard", "producer": "content-sufficiency-report",
                                    "steps": ["content-sufficiency"]}]}],
                    "facets": {"tier": "release"}}
        design = {"provenance": {"artifact_id": "gd-1"}, "knowledge_applied": [entry()]}
        section = compliance.evaluate(contract, TIERS, {"game-design": design}, tier="release",
                                      lessons=DATA["lessons"])
        rule = section["rules"][0]
        self.assertEqual(rule["status"], "UNMEASURED")       # no report measured it
        self.assertTrue(rule["blocks"])
        self.assertEqual(rule["trace"]["applied"], True)
        self.assertEqual(rule["trace"]["design"], "gd-1")
        self.assertEqual(section["verdict"], "RELEASE_BLOCKED")
        self.assertIn("claimed applied at u-02, u-03", compliance.render_markdown(section))


if __name__ == "__main__":
    unittest.main()
