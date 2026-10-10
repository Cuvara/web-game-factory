"""Normalize a producer's failures into quality findings.

Every gate reports what fell short in its own shape: playability and production-quality
checks, visual-qa findings, scores, state answers and a look, review blockers, verification
defects, listing-validation checks, and a person's typed findings at G4. `normalize(kind,
report, ...)` turns one of them into quality findings
(core/artifacts/shared/quality-finding.schema.json); the dimension each failure concerns
comes from core/reference/specialist-routing.yaml `producers`, and its owner and route from
the same file's `specialists` (routing.py). Nothing here knows a game or an engine name:
the only branch is the design's own `engine.dimension` (2d | 3d), through
`by_engine_dimension`.

A finding's id is `<producer>:<check>[@<project>]`, stable across measurements: the next
report of the same producer either fails the same id again or does not, which is how a
specialist visit's findings are said to be resolved (triage's ledger).

A check whose failing items have different owners - production-quality's `assets.runtime`
fails one asset at `exists` (an asset to make again) and another at `visible` (the game's
code) - is split by the producer table's `split` entry for it: one finding per route, each
naming only its own items, id `<producer>:<check>/<route>[@<project>]`. A split check's
findings always carry the route suffix, even when every failing item has one route, so an
id means the same items' route on every measurement and the ledger closes the `assets` part
when its assets are made while the `develop` part stays open until the game draws its own.
The check's verdict and its whole-check route are the producer's and stay as reported.

A finding of a producer that lists its checks (measurement.CHECKED) carries `measurement`: the
report, commit and status it failed on and, for playability, the scenario the bot played for
the check (playability-report 1.4.0) - the `before` a later verification is compared with.

The quality scorecard (WS-7) emits findings in this shape directly; `normalize` accepts its
`findings` list as the `quality-scorecard` producer. The quality gate's quality-report
(scripts/wgf_quality) is read as the `quality-report` producer: its open findings in a
dimension below the floor, each mapped onto a routing dimension by the producer table.
"""

import json
import re

from . import measurement as measurements

__all__ = ["normalize", "from_requests", "NormalizeError", "PRODUCERS", "finding_id",
           "failing_parts"]

# The artifact types a finding can be read from, in the order a build's reports are read.
PRODUCERS = ("playability-report", "production-quality-report", "visual-qa-report",
             "content-sufficiency-report", "review-report", "qa-report",
             "listing-validation-report", "quality-scorecard", "quality-report")

_ID_SAFE = re.compile(r"[^a-z0-9._:/@-]+")


class NormalizeError(ValueError):
    """A report or a typed finding that cannot be normalized."""


def finding_id(producer, check, project=None, part=None):
    """`<producer>:<check>[/<part>][@<project>]`, lower-cased into the schema's id alphabet.
    `part` is a split check's route (see the module docstring)."""
    raw = f"{producer}:{check}" + (f"/{part}" if part else "") \
        + (f"@{project}" if project else "")
    return _ID_SAFE.sub("-", raw.lower()).strip("-") or "finding"


def _inline(value, limit=300):
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True,
                                                          ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " ..."


class _Context:
    """What a producer's table resolves against: the routing data, the design's engine
    dimension, the source report's identity, and the run directory frames resolve under."""

    def __init__(self, routing, kind, report, ref=None, dimension_3d=False, rubric=None):
        self.routing = routing
        self.kind = kind
        self.table = routing.producer(kind)
        self.report = report if isinstance(report, dict) else {}
        self.ref = ref
        self.engine_dimension = "3d" if dimension_3d else "2d"
        self.rubric = rubric or {}

    def dimension(self, word):
        """A table's value - a dimension, or a word resolved by the engine dimension - as a
        dimension; the producer's default, then the routing default, when it is neither."""
        resolved = self.routing.resolve_word(word, self.engine_dimension)
        if resolved is None:
            resolved = self.routing.resolve_word(self.table.get("default"),
                                                 self.engine_dimension)
        return resolved or self.routing.default_dimension

    def by_check(self, check_id):
        """The dimension of a check id from the producer's `checks` table: the exact id,
        else the longest prefix ending in '.' that starts it."""
        table = self.table.get("checks") or {}
        if check_id in table:
            return self.dimension(table[check_id])
        best = None
        for key in table:
            if key.endswith(".") and check_id.startswith(key) and (
                    best is None or len(key) > len(best)):
                best = key
        return self.dimension(table[best] if best else None)

    def source(self, check, project=None):
        provenance = self.report.get("provenance") or {}
        return {
            "producer": self.kind,
            "step": self.table.get("step"),
            "check": str(check),
            "project": project,
            "artifact_id": provenance.get("artifact_id"),
            "content_hash": (getattr(self.ref, "content_hash", None)
                             or provenance.get("content_hash")),
        }

    def acceptance(self, check, bar=None):
        template = self.table.get("acceptance") or "{check} no longer fails when measured again."
        clause = f" (bar: {_inline(bar, 200)})" if bar is not None else ""
        return template.replace("{check}", str(check)).replace("{bar_clause}", clause)

    def make(self, *, check, dimension, severity, summary, route, project=None,
             measured=None, bar=None, evidence=(), change=None, assets=None, part=None):
        owner = self.routing.owner(dimension)
        finding = {
            "id": finding_id(self.kind, check, project, part),
            "dimension": dimension,
            "severity": severity,
            "source": self.source(check, project),
            "summary": summary or str(check),
            "evidence_refs": [e for e in evidence if isinstance(e, str) and e],
            "owner": owner,
            "task": {"change": change or f"Make `{check}` pass: {summary or check}",
                     "acceptance": [self.acceptance(check, bar)]},
            "route": route or self.routing.route_of(owner),
        }
        if self.ref is not None and getattr(self.ref, "id", None):
            finding["evidence_refs"].append(f"artifact:{self.ref.id}")
        if measured is not None:
            finding["measured"] = measured
        if bar is not None:
            finding["bar"] = bar
        if assets:
            finding["assets"] = sorted({str(a) for a in assets})
        return finding


def _frames(report, project, frame_ids):
    """Frame paths (run-relative, as the playability-report records them) for frame ids."""
    paths = {(f.get("project"), f.get("id")): f.get("path")
             for f in (report or {}).get("frames") or [] if isinstance(f, dict)}
    return [paths.get((project, f)) or f for f in frame_ids or [] if f]


def _playability(ctx):
    out = []
    for check in ctx.report.get("checks") or []:
        if not isinstance(check, dict) or not check.get("required") \
                or check.get("status") != "FAIL":
            continue
        out.extend(_check_findings(ctx, check, ctx.table.get("route") or "develop",
                                   _frames(ctx.report, check.get("project"),
                                           check.get("frames"))))
    return out


def _split_parts(ctx, check):
    """[(route, [item, ...])] for a check the producer table splits (`split.<check id>`),
    in route order; None for a check it does not split, or one with no failing item to
    split. Each failing item's route is the rule's `routes` entry for the value its
    measurement names (`measured.<item>.<item field>`, e.g. the chain link it failed at),
    else the rule's `default`, else the check's own route."""
    rule = (ctx.table.get("split") or {}).get(check.get("id"))
    measured = check.get("measured")
    if not isinstance(rule, dict) or not isinstance(measured, dict):
        return None
    field = rule.get("item") or "failed_at"
    routes = rule.get("routes") or {}
    default = rule.get("default") or check.get("route") or "develop"
    names = check.get("assets") if isinstance(check.get("assets"), list) else sorted(measured)
    parts = {}
    for name in names:
        entry = measured.get(name)
        value = entry.get(field) if isinstance(entry, dict) else None
        if value:
            parts.setdefault(routes.get(value, default), []).append((str(name), value))
    if not parts:
        return None
    order = list(ctx.routing.route_order)
    return sorted(parts.items(), key=lambda kv: (
        order.index(kv[0]) if kv[0] in order else len(order), kv[0]))


def failing_parts(routing, kind, check):
    """The routes (split parts) `check` of a `kind` report fails, by the same rule that
    splits its findings (`_split_parts`); None when the producer table does not split the
    check, or the check names no failing item to split."""
    ctx = _Context(routing, kind, {})
    parts = _split_parts(ctx, check if isinstance(check, dict) else {})
    return None if parts is None else {route for route, _items in parts}


def _measured(ctx, check, findings):
    """Each finding of `check`, with the measurement it was failed on."""
    taken = measurements.of_check(ctx.kind, ctx.report, check,
                                  content_hash=getattr(ctx.ref, "content_hash", None),
                                  seq=getattr(ctx.ref, "seq", None))
    for finding in findings:
        finding["measurement"] = dict(taken)
    return findings


def _check_findings(ctx, check, route, evidence, assets=None):
    """The findings of one failed check: one, under the check's own id and route; or, for a
    check the producer table splits, one per route its failing items take."""
    return _measured(ctx, check, _check_parts(ctx, check, route, evidence, assets))


def _check_parts(ctx, check, route, evidence, assets=None):
    cid, project = check.get("id") or "check", check.get("project")
    parts = _split_parts(ctx, check)
    if parts is None:
        return [ctx.make(
            check=cid, project=project, dimension=ctx.by_check(cid), severity="blocker",
            summary=check.get("summary"), route=route,
            measured=check.get("measured"), bar=check.get("expected"),
            evidence=evidence, assets=assets)]
    measured = check.get("measured")
    out = []
    for part_route, items in parts:
        names = [name for name, _value in items]
        summary = "; ".join(f"{name}: fails at {value}" for name, value in items[:12]) \
            + (f" (+{len(items) - 12} more)" if len(items) > 12 else "")
        out.append(ctx.make(
            check=cid, project=project, dimension=ctx.by_check(cid), severity="blocker",
            summary=f"{cid} ({part_route}): {summary}", route=part_route,
            measured={name: measured.get(name) for name in names},
            bar=check.get("expected"), evidence=evidence,
            change=(f"Make `{cid}` pass for {', '.join(names)}: {summary}"),
            assets=names if assets is not None or check.get("assets") else None,
            part=part_route))
    return out


def _production(ctx, playability=None):
    out = []
    for check in ctx.report.get("checks") or []:
        if not isinstance(check, dict) or not check.get("required") \
                or check.get("status") != "FAIL":
            continue
        out.extend(_check_findings(ctx, check, check.get("route") or "develop",
                                   _frames(playability, check.get("project"),
                                           check.get("frames")),
                                   assets=check.get("assets")))
    return out


def _visual_qa(ctx):
    report, table, rubric = ctx.report, ctx.table, ctx.rubric
    failed = [str(f) for f in report.get("failed") or []]
    dimensions = rubric.get("dimensions") or {}
    questions = {q.get("id"): q for q in rubric.get("state_questions") or []
                 if isinstance(q, dict)}
    pass_bar = (report.get("rubric") or {}).get("pass_bar", rubric.get("pass_bar"))
    scores = report.get("scores") or {}
    reasons = report.get("score_reasons") or {}
    states = {(s.get("viewport"), s.get("state")): s for s in report.get("states") or []
              if isinstance(s, dict)}
    out, seen = [], set()

    def add(finding):
        if finding["id"] not in seen:
            seen.add(finding["id"])
            out.append(finding)

    findings = {f.get("id"): f for f in report.get("findings") or [] if isinstance(f, dict)}
    # The judge's own findings: blockers failed the build; majors and minors travel with them.
    for fid, item in findings.items():
        add(ctx.make(
            check=f"finding:{fid}", dimension=ctx.dimension(
                (table.get("findings") or {}).get(item.get("category"))),
            severity=item.get("severity") if item.get("severity") in (
                "blocker", "major", "minor") else "major",
            summary=item.get("summary"), route=item.get("route") or "develop",
            evidence=[item.get("frame")] if item.get("frame") else ()))
    for entry in failed:
        kind, _, rest = entry.partition(":")
        if kind == "score" and rest in scores:
            dim = dimensions.get(rest) or {}
            bar = dim.get("pass_bar", pass_bar)
            add(ctx.make(
                check=entry, dimension=ctx.dimension((table.get("scores") or {}).get(rest)),
                severity="blocker", route=dim.get("route") or "develop",
                summary=f"{rest} scored {scores[rest]}"
                        + (f": {reasons[rest]}" if reasons.get(rest) else ""),
                measured=scores[rest], bar=bar))
        elif kind == "state":
            where, _, qid = rest.rpartition(":")
            viewport, _, state = where.partition("/")
            question = questions.get(qid) or {}
            answered = states.get((viewport, state)) or {}
            summary = (f"{question.get('ask') or qid} - answered "
                       f"{(answered.get('answers') or {}).get(qid)!r} on {viewport}/{state}")
            if answered.get("comment"):
                summary += f": {answered['comment']}"
            add(ctx.make(
                check=f"state:{state}:{qid}", project=viewport,
                dimension=ctx.dimension((table.get("states") or {}).get(qid)),
                severity="blocker", route=question.get("route") or "develop",
                summary=summary, measured=(answered.get("answers") or {}).get(qid),
                bar={"fail_when": question.get("fail_when")} if question else None,
                evidence=answered.get("frames") or ()))
        elif kind == "mean":
            # The mean failed: every dimension below 4 is what dragged it down (the rubric's
            # own rule for the routes a mean failure contributes).
            for name, score in sorted(scores.items()):
                if isinstance(score, (int, float)) and score < 4 \
                        and f"score:{name}" not in failed:
                    dim = dimensions.get(name) or {}
                    add(ctx.make(
                        check=f"score:{name}",
                        dimension=ctx.dimension((table.get("scores") or {}).get(name)),
                        severity="major", route=dim.get("route") or "develop",
                        summary=(f"{name} scored {score}, below 4, and the mean failed "
                                 f"({rest})"
                                 + (f": {reasons[name]}" if reasons.get(name) else "")),
                        measured=score, bar={"mean_pass_bar": rubric.get("mean_pass_bar"),
                                             "dimension": 4}))
        elif kind == "look":
            look = report.get("look") or {}
            add(ctx.make(
                check="look", dimension=ctx.dimension(table.get("look")), severity="blocker",
                route=(rubric.get("look") or {}).get("route") or "assets",
                summary=f"the build looks like a {rest}"
                        + (f": {look.get('reason')}" if look.get("reason") else ""),
                measured=rest, bar={"fail_on": (rubric.get("look") or {}).get("fail_on")}))
        elif kind == "finding":
            continue  # the judge's findings are above
        elif entry not in seen:
            add(ctx.make(check=entry, dimension=ctx.dimension(table.get("default")),
                         severity="blocker", route="develop",
                         summary=f"visual-qa failed `{entry}`"))
    return out


def _review(ctx):
    out = []
    for blocker in ctx.report.get("blockers") or []:
        if not isinstance(blocker, dict):
            continue
        where = blocker.get("file") or "(whole build)"
        if blocker.get("file") and blocker.get("line"):
            where += f":{blocker['line']}"
        severity = blocker.get("severity")
        # A blocker that names its dimension (review-report 1.2.0: a gate-gaming blocker
        # carries the specialist visit's) goes back to that dimension's owner.
        out.append(ctx.make(
            check=blocker.get("id") or "blocker", dimension=ctx.dimension(blocker.get("dimension")),
            severity="blocker" if severity in ("blocker", "critical") else (
                "minor" if severity == "minor" else "major"),
            summary=f"{where}: {blocker.get('summary')}", route=ctx.table.get("route"),
            evidence=[blocker["file"]] if blocker.get("file") else ()))
    return out


def _defect_check(table, defect_id):
    """(check, viewport) - the verification check a qa-report defect was made from, when the
    producer's `verification_checks` table names it. Verify writes a defect's id as `vr-` +
    the check id with every character outside [a-z0-9-] made `-` (the per-viewport suffix
    `:<viewport>` included); the longest check whose stem the id is, or starts with plus
    `-`, is it, and what follows is the viewport. (None, None) otherwise."""
    defect_id = str(defect_id or "")
    for check in sorted(table or {}, key=len, reverse=True):
        stem = "vr-" + re.sub(r"[^a-z0-9-]+", "-", str(check))
        if defect_id == stem:
            return check, None
        if defect_id.startswith(stem + "-"):
            return check, defect_id[len(stem) + 1:] or None
    return None, None


def _qa(ctx):
    out = []
    checks = ctx.table.get("verification_checks") or {}
    for defect in ctx.report.get("blocking_defects") or []:
        if not isinstance(defect, dict):
            continue
        word = ctx.table.get("platform_defect") if defect.get("platform_id") else None
        check, viewport = _defect_check(checks, defect.get("id"))
        if check is not None and word is None:
            out.append(ctx.make(
                check=check, project=viewport, dimension=ctx.dimension(checks[check]),
                severity="blocker", summary=defect.get("summary"),
                route=ctx.table.get("route"),
                change=(f"Fix `{defect.get('id')}`: {defect.get('summary')}"
                        + (f" Repro: {defect['repro']}" if defect.get("repro") else ""))))
            continue
        out.append(ctx.make(
            check=defect.get("id") or "defect", dimension=ctx.dimension(word),
            severity="blocker", summary=defect.get("summary"), route=ctx.table.get("route"),
            change=(f"Fix `{defect.get('id')}`: {defect.get('summary')}"
                    + (f" Repro: {defect['repro']}" if defect.get("repro") else ""))))
    for suite in ctx.report.get("suites") or []:
        if isinstance(suite, dict) and (suite.get("failed") or 0) > 0:
            out.append(ctx.make(
                check=f"suite:{suite.get('name')}", dimension=ctx.dimension(None),
                severity="blocker", route=ctx.table.get("route"),
                summary=f"the {suite.get('name')} suite failed {suite.get('failed')} test(s)",
                measured={"failed": suite.get("failed"), "passed": suite.get("passed")},
                bar={"failed": 0}))
    if not out and ctx.report.get("verdict") not in (None, "pass"):
        out.append(ctx.make(check="verdict", dimension=ctx.dimension(None), severity="blocker",
                            route=ctx.table.get("route"),
                            summary=f"verification's verdict was {ctx.report.get('verdict')}"))
    return out


def _listing(ctx):
    out = []
    sections = ctx.table.get("sections") or {}
    for check in ctx.report.get("checks") or []:
        if not isinstance(check, dict) or not check.get("required") \
                or check.get("status") != "FAIL":
            continue
        cid = check.get("id") or "check"
        project = "/".join(p for p in (check.get("platform_id"), check.get("locale")) if p)
        out.extend(_measured(ctx, check, [ctx.make(
            check=cid, project=project or None,
            dimension=ctx.dimension(sections.get(check.get("section"))), severity="blocker",
            summary=check.get("summary"), route=ctx.table.get("route") or "listing",
            measured=check.get("measured"), bar=check.get("expected"),
            evidence=check.get("files") or ())]))
    return out


def _sufficiency(ctx):
    """A content-sufficiency-report's typed findings (FAIL and WARNING checks), kept as the
    gate stated them - observed against the bar, its evidence - with the owner recomputed
    from the routing data. A `design-gap` finding routes `design`: the design itself is
    short of the tier's bar, and its `design_gap` is what the design step repairs."""
    out = []
    for item in ctx.report.get("findings") or []:
        if not isinstance(item, dict):
            continue
        check = item.get("id") or item.get("check") or "content"
        word = item.get("dimension") if item.get("dimension") in ctx.routing.dimensions \
            else (ctx.table.get("checks") or {}).get(item.get("check"))
        dimension = ctx.dimension(word)
        gap = item.get("design_gap") if isinstance(item.get("design_gap"), dict) else None
        design = item.get("route") == "design-gap"
        finding = ctx.make(
            check=check, dimension=dimension,
            severity=item.get("severity") if item.get("severity") in (
                "blocker", "major", "minor") else "major",
            summary=item.get("summary"),
            route="design" if design else None,
            measured=item.get("observed"), bar=item.get("bar"),
            evidence=item.get("evidence") or (),
            change=((gap or {}).get("question") if design else None))
        if design and gap and gap.get("field"):
            finding["task"]["design_field"] = gap["field"]
        out.append(finding)
    return out


def _scorecard(ctx):
    """A quality scorecard's findings are already in this shape: kept, owner and route
    recomputed from the routing data so the scorecard cannot disagree with it."""
    out = []
    for item in ctx.report.get("findings") or []:
        if not isinstance(item, dict) or item.get("dimension") not in ctx.routing.dimensions:
            continue
        finding = dict(item)
        finding["owner"] = ctx.routing.owner(item["dimension"])
        if finding.get("route") != "design":
            finding["route"] = ctx.routing.route_of(finding["owner"])
        out.append(finding)
    return out


def _quality_report(ctx):
    """A quality-report's open findings in the dimensions it held below their floor: the
    quality dimension mapped onto a routing dimension (the producer table's `dimensions`),
    observed against the expected threshold, the asset ids it names; `design-gap` routes
    `design` with its gap, `assets` routes `assets`, anything else its owner's route."""
    below = set(ctx.report.get("failed") or [])
    dims = ctx.table.get("dimensions") or {}
    out = []
    for item in ctx.report.get("findings") or []:
        if not isinstance(item, dict) or item.get("status") != "open" \
                or item.get("dimension") not in below:
            continue
        check = item.get("criterion") or item.get("id") or "quality"
        # A criterion the table names (`criteria`) goes to its own owner whatever the quality
        # dimension it is scored in: a performance criterion of `technical` is the
        # performance engineer's, not the generalist's.
        word = (ctx.table.get("criteria") or {}).get(check) or dims.get(item.get("dimension"))
        dimension = ctx.dimension(word)
        route = {"design-gap": "design", "assets": "assets"}.get(item.get("route"))
        gap = item.get("design_gap") if isinstance(item.get("design_gap"), dict) else None
        finding = ctx.make(
            check=check, dimension=dimension,
            severity=item.get("severity") if item.get("severity") in (
                "blocker", "major", "minor") else "major",
            summary=item.get("summary"), route=route,
            measured=item.get("observed"), bar=item.get("expected"),
            evidence=[f"artifact:{e['artifact_id']}" for e in item.get("evidence") or []
                      if isinstance(e, dict) and e.get("artifact_id")],
            change=(gap or {}).get("question") if route == "design" else None,
            assets=item.get("assets") or None)
        if route == "design" and gap and gap.get("field"):
            finding["task"]["design_field"] = gap["field"]
        out.append(finding)
    return out


_READERS = {
    "playability-report": _playability,
    "visual-qa-report": _visual_qa,
    "content-sufficiency-report": _sufficiency,
    "review-report": _review,
    "qa-report": _qa,
    "listing-validation-report": _listing,
    "quality-scorecard": _scorecard,
    "quality-report": _quality_report,
}


def normalize(kind, report, routing, *, ref=None, dimension_3d=False, playability=None,
              rubric=None):
    """The quality findings of one producer's report. `routing` is a routing.Routing;
    `playability` resolves production-quality's frame ids; `rubric` is the visual-qa
    rubric (scores' and state questions' routes)."""
    if kind not in PRODUCERS:
        raise NormalizeError(f"no producer table for {kind!r}")
    ctx = _Context(routing, kind, report, ref=ref, dimension_3d=dimension_3d, rubric=rubric)
    if kind == "production-quality-report":
        return _production(ctx, playability)
    return _READERS[kind](ctx)


def from_requests(requests, routing, *, source_ref=None, decision=None, dimension_3d=False):
    """A person's typed findings (quality-finding `request`s) at G4, as findings: owner and
    route from the routing data (`design` or `assets` only when the person asks for it)."""
    ctx = _Context(routing, "decision-record", {"provenance": {}}, ref=None,
                   dimension_3d=dimension_3d)
    out = []
    for index, request in enumerate(requests, 1):
        if not isinstance(request, dict) or request.get("dimension") not in routing.dimensions:
            raise NormalizeError(f"typed finding {index}: dimension must be one of "
                                 f"{', '.join(routing.dimensions)}")
        task = request.get("task") or {}
        if not task.get("change") or not task.get("acceptance"):
            raise NormalizeError(f"typed finding {index}: task needs `change` and "
                                 f"`acceptance`")
        check = request.get("id") or f"g4-{index}"
        owner = routing.owner(request["dimension"])
        finding = {
            "id": finding_id("decision-record", check),
            "dimension": request["dimension"],
            "severity": request.get("severity") or "major",
            "source": {"producer": "decision-record", "step": ctx.table.get("step"),
                       "check": str(check), "project": None,
                       "artifact_id": (decision or {}).get("artifact_id"),
                       "content_hash": source_ref},
            "summary": request.get("summary") or str(check),
            "evidence_refs": [e for e in request.get("evidence_refs") or [] if e],
            "owner": owner,
            "task": {k: v for k, v in task.items() if k in ("change", "acceptance",
                                                             "design_field")},
            # A person may ask for the design to change first, or for an asset to be made
            # again; anything else goes where the owner's work is done.
            "route": (request["route"] if request.get("route") in ("design", "assets")
                      else routing.route_of(owner)),
        }
        for key in ("measured", "bar"):
            if key in request:
                finding[key] = request[key]
        if request.get("assets"):
            finding["assets"] = sorted({str(a) for a in request["assets"]})
        out.append(finding)
    return out
