"""The criteria-expression evaluator.

Two things are being checked. The unit tests pin the semantics the schema states — in
particular the two readings of `in`, and the rule that an ordering operator on a non-number
is an error rather than a false. The corpus test takes every expression core actually
contains — ten design-consistency rules, four scoring vetoes, and the assertions on all five
platform profiles — and evaluates each one, to prove they are machine-evaluable at all.

That corpus test is the one that would have caught `right: platform.capabilities.ads`: a
dotted path written where the schema says literal, indistinguishable from `right: casual`
until something tries to compute it.

Run from the web-game-factory repository root:

    python -m unittest discover scripts/tests
"""

import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)

sys.path.insert(0, SCRIPTS)

from wgflib.criteria import (  # noqa: E402
    MISSING,
    CriteriaError,
    Unevaluable,
    evaluate,
    evaluate_named,
    resolve,
)
from wgflib.yamllite import load_file  # noqa: E402


def check(expression, context):
    return evaluate(expression, context).value


class Resolve(unittest.TestCase):
    def test_dotted_path(self):
        self.assertEqual(resolve("a.b.c", {"a": {"b": {"c": 1}}}), 1)

    def test_list_index(self):
        self.assertEqual(resolve("a.1", {"a": ["x", "y"]}), "y")

    def test_missing_is_not_none(self):
        # A path that does not exist and a path whose value is null are different facts.
        self.assertIs(resolve("a.z", {"a": {}}), MISSING)
        self.assertIsNone(resolve("a.z", {"a": {"z": None}}))


class Operators(unittest.TestCase):
    context = {"n": 10, "s": "casual", "list": ["ru", "en"], "nothing": None}

    def test_ordering(self):
        self.assertTrue(check({"left": "n", "op": "gt", "right": 5}, self.context))
        self.assertFalse(check({"left": "n", "op": "lt", "right": 5}, self.context))
        self.assertTrue(check({"left": "n", "op": "lte", "right": 10}, self.context))

    def test_ordering_on_a_non_number_is_an_error_not_a_false(self):
        with self.assertRaises(Unevaluable):
            check({"left": "s", "op": "gt", "right": 5}, self.context)
        with self.assertRaises(Unevaluable):
            check({"left": "n", "op": "gt", "right": "five"}, self.context)

    def test_booleans_are_not_numbers(self):
        with self.assertRaises(Unevaluable):
            check({"left": "b", "op": "gt", "right": 0}, {"b": True})

    def test_equality(self):
        self.assertTrue(check({"left": "s", "op": "eq", "right": "casual"}, self.context))
        self.assertTrue(check({"left": "s", "op": "neq", "right": "core"}, self.context))

    def test_in_against_an_array_asks_whether_the_element_is_present(self):
        # The reading platform profiles depend on: does the package ship Russian?
        self.assertTrue(check({"left": "list", "op": "in", "right": ["ru"]}, self.context))
        self.assertFalse(check({"left": "list", "op": "in", "right": ["vi"]}, self.context))
        # Not "does the whole list equal [ru]" - that would pass vacuously almost never,
        # and the locale assertions it guards are blocking on three platforms.
        self.assertTrue(
            check({"left": "list", "op": "in", "right": ["ru", "en"]}, self.context)
        )

    def test_in_against_a_scalar_asks_whether_it_appears(self):
        self.assertTrue(
            check({"left": "s", "op": "in", "right": ["casual", "core"]}, self.context)
        )

    def test_not_in_is_the_negation(self):
        self.assertTrue(check({"left": "list", "op": "not_in", "right": ["vi"]}, self.context))
        self.assertFalse(check({"left": "list", "op": "not_in", "right": ["ru"]}, self.context))

    def test_exists_and_absent_treat_null_as_absent(self):
        self.assertTrue(check({"left": "n", "op": "exists"}, self.context))
        self.assertFalse(check({"left": "nothing", "op": "exists"}, self.context))
        self.assertTrue(check({"left": "nothing", "op": "absent"}, self.context))
        self.assertTrue(check({"left": "gone", "op": "absent"}, self.context))

    def test_a_missing_value_is_unevaluable_not_false(self):
        with self.assertRaises(Unevaluable):
            check({"left": "gone", "op": "eq", "right": 1}, self.context)

    def test_right_path_compares_two_measured_values(self):
        context = {"session": {"target_seconds": 240}, "platform": {"interval": 180}}
        self.assertFalse(
            check(
                {"left": "session.target_seconds", "op": "lt",
                 "right_path": "platform.interval"},
                context,
            )
        )

    def test_right_path_that_does_not_resolve_is_unevaluable(self):
        with self.assertRaises(Unevaluable):
            check({"left": "n", "op": "lt", "right_path": "nowhere"}, self.context)

    def test_both_right_and_right_path_is_malformed(self):
        with self.assertRaises(CriteriaError):
            check({"left": "n", "op": "lt", "right": 1, "right_path": "n"}, self.context)


class Connectives(unittest.TestCase):
    context = {"a": 1, "b": 2}

    def test_all_of(self):
        expression = {"all_of": [
            {"left": "a", "op": "eq", "right": 1},
            {"left": "b", "op": "eq", "right": 2},
        ]}
        self.assertTrue(check(expression, self.context))

    def test_any_of(self):
        expression = {"any_of": [
            {"left": "a", "op": "eq", "right": 99},
            {"left": "b", "op": "eq", "right": 2},
        ]}
        self.assertTrue(check(expression, self.context))

    def test_not(self):
        self.assertTrue(check({"not": {"left": "a", "op": "eq", "right": 99}}, self.context))

    def test_measurements_cover_every_branch(self):
        # A gate presentation that shows only the first failing clause makes the rest look
        # like they passed, so evaluation does not short-circuit.
        outcome = evaluate(
            {"all_of": [
                {"left": "a", "op": "eq", "right": 99},
                {"left": "b", "op": "eq", "right": 2},
            ]},
            self.context,
        )
        self.assertFalse(outcome.value)
        self.assertEqual({"a": 1, "b": 2}, outcome.measurements)


class NamedCriteria(unittest.TestCase):
    def test_breached_is_the_expression_value(self):
        # `when` describes what is wrong: a fired veto, a violated rule, a breached kill
        # criterion. So a true expression means breached.
        criterion = {"id": "too_slow", "when": {"left": "ms", "op": "gt", "right": 60},
                     "rationale": "x"}
        self.assertTrue(evaluate_named(criterion, {"ms": 95})["breached"])
        self.assertFalse(evaluate_named(criterion, {"ms": 40})["breached"])

    def test_result_shape_matches_criterionResult(self):
        criterion = {"id": "too_slow", "when": {"left": "ms", "op": "gt", "right": 60},
                     "rationale": "x"}
        result = evaluate_named(criterion, {"ms": 95}, evaluated_at="2026-09-16T09:30:00Z")
        self.assertEqual(
            {"criterion_id", "measured", "breached", "evaluated_at"}, set(result)
        )
        self.assertEqual(95, result["measured"])


class EveryExpressionInCoreIsEvaluable(unittest.TestCase):
    """Each expression core ships, evaluated against a context that supplies every path.

    The context is built from the paths the expressions themselves name, so this checks
    that they are well-formed and computable - not that any particular design passes.
    """

    def expressions(self):
        found = []

        rules = load_file(os.path.join(ROOT, "core/reference/design-consistency-rules.yaml"))
        for rule in rules["rules"]:
            found.append((f"design-consistency:{rule['id']}", rule["when"]))

        for path in sorted(glob.glob(os.path.join(ROOT, "core/reference/scoring/*.yaml"))):
            model = load_file(path)
            for veto in model.get("vetoes") or []:
                found.append((f"{model['id']}:veto:{veto['id']}", veto["when"]))

        for path in sorted(glob.glob(os.path.join(ROOT, "core/reference/platforms/*.yaml"))):
            profile = load_file(path)
            for assertion in profile.get("assertions") or []:
                found.append((f"{profile['id']}:{assertion['id']}", assertion["check"]))

        return found

    def paths_in(self, expression, out):
        if "all_of" in expression:
            for branch in expression["all_of"]:
                self.paths_in(branch, out)
        elif "any_of" in expression:
            for branch in expression["any_of"]:
                self.paths_in(branch, out)
        elif "not" in expression:
            self.paths_in(expression["not"], out)
        else:
            out.add(expression["left"])
            if "right_path" in expression:
                out.add(expression["right_path"])
        return out

    def context_for(self, expression):
        """Supply every named path with a value of a type the operator can use."""
        context = {}
        needed = self.paths_in(expression, set())
        numeric = self.numeric_paths(expression, set())
        for path in needed:
            node = context
            segments = path.split(".")
            for segment in segments[:-1]:
                node = node.setdefault(segment, {})
            node[segments[-1]] = 1 if path in numeric else ["placeholder"]
        return context

    def numeric_paths(self, expression, out):
        if "all_of" in expression:
            for branch in expression["all_of"]:
                self.numeric_paths(branch, out)
        elif "any_of" in expression:
            for branch in expression["any_of"]:
                self.numeric_paths(branch, out)
        elif "not" in expression:
            self.numeric_paths(expression["not"], out)
        elif expression["op"] in ("gt", "gte", "lt", "lte"):
            out.add(expression["left"])
            if "right_path" in expression:
                out.add(expression["right_path"])
        return out

    def test_every_expression_evaluates(self):
        expressions = self.expressions()
        self.assertGreaterEqual(len(expressions), 25, "expected the full corpus")

        problems = []
        for name, expression in expressions:
            try:
                evaluate(expression, self.context_for(expression))
            except CriteriaError as exc:
                problems.append(f"{name}: malformed: {exc}")
            except Unevaluable as exc:
                problems.append(f"{name}: not computable: {exc}")

        self.assertEqual([], problems, "\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
