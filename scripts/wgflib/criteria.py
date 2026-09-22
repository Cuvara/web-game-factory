"""Evaluate criteria-expressions.

One deliberately dumb expression type serves four features - kill criteria, success
criteria, scoring vetoes and platform assertions - and core/artifacts/shared/
criteria-expression.schema.json is its definition. This module computes it.

The rule that shapes the whole module: an expression that cannot be evaluated raises. It
never returns False. A guard reading "the kill criterion was not breached" must mean the
criterion was checked and held, not that the number it needed was missing - those are
opposite conclusions and only one of them is safe to act on.

The game-repo side evaluates the same expressions against platform profiles in
web-game-template/scripts/verify/evaluate-assertions.mjs. Only the literal forms appear
there, so the two stay compatible.
"""

__all__ = [
    "MISSING",
    "CriteriaError",
    "Unevaluable",
    "Outcome",
    "resolve",
    "evaluate",
    "evaluate_named",
]

ORDERING = {"gt", "gte", "lt", "lte"}
COMPARISON = ORDERING | {"eq", "neq", "in", "not_in", "exists", "absent"}
UNARY = {"exists", "absent"}


class _Missing:
    def __repr__(self):
        return "MISSING"

    def __bool__(self):
        return False


MISSING = _Missing()


class CriteriaError(ValueError):
    """The expression is malformed - a bug in the rule, not in the data."""


class Unevaluable(Exception):
    """The expression is well-formed but could not be decided against this data."""


class Outcome:
    """The result of one evaluation, and what it read to get there.

    The measurements are not decoration. A gate presentation has to show which numbers a
    verdict rested on, and a criterion result records its `measured` value so the decision
    can be re-read later against data that has since moved on.
    """

    __slots__ = ("value", "measurements")

    def __init__(self, value, measurements=None):
        self.value = value
        self.measurements = measurements or {}

    def __bool__(self):
        return self.value

    def merge(self, other):
        self.measurements.update(other.measurements)
        return self


def resolve(path, context):
    """Look up a dotted path. Returns MISSING rather than raising, so callers can decide.

    Numeric segments index into lists, which is what makes `suites.0.name` work without a
    second syntax.
    """
    if not isinstance(path, str) or path == "":
        raise CriteriaError(f"expected a dotted path, got {path!r}")

    current = context
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                return MISSING
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                return MISSING
            current = current[index]
        else:
            return MISSING
    return current


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_list(value):
    return value if isinstance(value, list) else [value]


def _contains(measured, wanted, path):
    """`in`, with the reading the schema pins down.

    A measured ARRAY asks whether every element of `right` is present in it - the
    "required element is present" reading platform profiles depend on. A measured SCALAR
    asks whether it appears in `right`. Reading it the other way makes every locale
    assertion pass vacuously, and those are blocking on three platforms.
    """
    if isinstance(measured, list):
        return all(item in measured for item in _as_list(wanted))
    if isinstance(wanted, list):
        return measured in wanted
    raise Unevaluable(
        f"{path}: `in` against a scalar needs a list on the right, got {wanted!r}"
    )


def _comparison(expression, context):
    op = expression["op"]
    if op not in COMPARISON:
        raise CriteriaError(f"unknown operator {op!r}")

    left_path = expression["left"]
    measured = resolve(left_path, context)
    measurements = {left_path: None if measured is MISSING else measured}

    if op == "exists":
        return Outcome(measured is not MISSING and measured is not None, measurements)
    if op == "absent":
        return Outcome(measured is MISSING or measured is None, measurements)

    has_literal = "right" in expression
    has_path = "right_path" in expression
    if has_literal and has_path:
        raise CriteriaError(f"{left_path}: give either `right` or `right_path`, not both")
    if not has_literal and not has_path:
        raise CriteriaError(f"{left_path}: `{op}` needs a right-hand side")

    if has_path:
        wanted = resolve(expression["right_path"], context)
        measurements[expression["right_path"]] = None if wanted is MISSING else wanted
        if wanted is MISSING:
            raise Unevaluable(f"{expression['right_path']} did not resolve")
    else:
        wanted = expression["right"]

    if measured is MISSING:
        raise Unevaluable(f"{left_path} did not resolve")

    if op in ORDERING:
        if not _numeric(measured) or not _numeric(wanted):
            # Stated by the schema: a non-number on either side of an ordering operator is
            # an evaluation error, never a silent false.
            raise Unevaluable(
                f"{left_path}: `{op}` needs numbers on both sides, got "
                f"{measured!r} and {wanted!r}"
            )
        result = {
            "gt": measured > wanted,
            "gte": measured >= wanted,
            "lt": measured < wanted,
            "lte": measured <= wanted,
        }[op]
    elif op == "eq":
        result = measured == wanted
    elif op == "neq":
        result = measured != wanted
    elif op == "in":
        result = _contains(measured, wanted, left_path)
    else:  # not_in
        result = not _contains(measured, wanted, left_path)

    return Outcome(result, measurements)


def evaluate(expression, context):
    """Evaluate one expression against `context`. Returns an Outcome; may raise Unevaluable.

    `all_of` and `any_of` do not short-circuit. Every branch is evaluated so that the
    measurements are complete - a gate presentation that shows only the first failing
    clause makes the other clauses look like they passed.
    """
    if not isinstance(expression, dict):
        raise CriteriaError(f"expected an expression object, got {expression!r}")

    if "all_of" in expression:
        outcome = Outcome(True)
        for branch in expression["all_of"]:
            result = evaluate(branch, context)
            outcome.merge(result)
            outcome.value = outcome.value and result.value
        return outcome

    if "any_of" in expression:
        outcome = Outcome(False)
        for branch in expression["any_of"]:
            result = evaluate(branch, context)
            outcome.merge(result)
            outcome.value = outcome.value or result.value
        return outcome

    if "not" in expression:
        result = evaluate(expression["not"], context)
        return Outcome(not result.value, result.measurements)

    if "op" in expression and "left" in expression:
        return _comparison(expression, context)

    raise CriteriaError(f"not an expression: {sorted(expression)}")


def evaluate_named(criterion, context, evaluated_at=None):
    """Evaluate a namedCriterion into a criterionResult-shaped dict.

    `when` describes the condition that is *wrong*: a fired veto, a breached kill criterion,
    a violated design rule. So `breached` is the expression's own value, not its negation.
    """
    if "id" not in criterion or "when" not in criterion:
        raise CriteriaError(f"named criterion needs `id` and `when`: {sorted(criterion)}")

    outcome = evaluate(criterion["when"], context)

    measured = None
    if len(outcome.measurements) == 1:
        measured = next(iter(outcome.measurements.values()))
    elif outcome.measurements:
        measured = dict(outcome.measurements)

    result = {
        "criterion_id": criterion["id"],
        "measured": measured,
        "breached": outcome.value,
    }
    if evaluated_at:
        result["evaluated_at"] = evaluated_at
    return result
