"""What a failed gate sends back to the assets step: which requirements to make again, why,
and the frames that show it.

A production-quality-report or visual-qa-report whose routes include `assets` brings the run
back here (core/workflows/new-game.workflow.yaml). `plan` turns it into
{requirement id: {"reasons": [text], "frames": [absolute PNG path]}}:

    production-quality  every failing check routed `assets`: the ids in its `assets`, else
                        the ids and role words its summary names; its frames resolved
                        through the playability-report the gate judged
    visual-qa           every finding routed `assets` (any severity), every failing score,
                        per-state answer and look whose rubric entry routes `assets`

A failure concerns the requirements whose id (or variant id) it names, those of a role whose
word it names, those whose runtime asset the play probe reported drawing an entity of that
role (the playability records), and those of its rubric entry's `rebuild_roles`
(core/reference/visual-qa-rubric.yaml, `rebuild`). Reasons carry the judge's own words - the
finding's summary, the score's reason, the state's comment, the look's reason - and frames
are the ones the failure names, or, for a failure about every frame, a play frame of each
viewport.

An `assets` re-entry from a failed gate never names nothing: when no failure resolves to a
requirement, every requirement of the rubric's `rebuild.fallback` roles (the readable entities
and the scene) is made again with every reason, and `plan` says it fell back. Only the report
of the gate that routed the run here (`context.entered_by`) is read, when that is known: an
older report of the other gate was already acted on.
"""

import json
import os
import re
from collections import namedtuple

from wgflib import paths
from wgflib.yamllite import YamlError, load_file

__all__ = ["plan", "rebuild_list", "load_rules", "Plan", "probe_roles", "MAX_FRAMES"]

RUBRIC_PATH = os.path.join(paths.REFERENCE, "visual-qa-rubric.yaml")
MAX_FRAMES = 12
# The rubric states whose frames stand for "every frame", in the order they are offered.
OVERVIEW_STATES = ("gameplay", "interaction", "initial")
_WORD = re.compile(r"[a-z][a-z0-9]*")
_ID_WORD = re.compile(r"[a-z][a-z0-9-]*")
# Requirement kinds that are heard, not seen (requirements.AUDIO_KINDS).
AUDIO = ("sfx", "music")

# items: {requirement id: {"reasons": [...], "frames": [...]}}; reentry: a failed gate routed
# the run here; fallback: nothing resolved, so `rebuild.fallback` was taken; sources: the
# report kinds read; unresolved: reasons no requirement was named for.
Plan = namedtuple("Plan", "items reentry fallback sources unresolved")


def load_rules(path=None):
    """The visual-qa rubric (dimensions, blockers, state questions, look, rebuild) as data,
    or {} when it cannot be read - re-entry then resolves by ids alone and falls back."""
    try:
        data = load_file(path or RUBRIC_PATH)
    except (OSError, YamlError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _expand(rules, names):
    groups = ((rules.get("rebuild") or {}).get("groups")) or {}
    out, seen = [], set()

    def add(name):
        if name in seen:
            return
        seen.add(name)
        if name in groups:
            for member in groups[name] or []:
                add(member)
        elif name not in out:
            out.append(name)

    for name in names or ():
        add(name)
    return out


def _forms(word):
    forms = {word}
    if word.endswith("es") and len(word) > 3:
        forms.add(word[:-2])
    if word.endswith("s") and len(word) > 2:
        forms.add(word[:-1])
    return forms


def _role_words(rules):
    """{word: {role}} from rebuild.role_words; each role's own name is a word for it."""
    out = {}
    for role, words in (((rules.get("rebuild") or {}).get("role_words")) or {}).items():
        for word in [role] + list(words or []):
            out.setdefault(str(word).lower(), set()).add(role)
    return out


def probe_roles(playability, run_dir):
    """{role: {runtime asset id}} the play probe reported drawing an entity of that role, read
    from the playability records the report names; {} when there are none to read."""
    if not playability or not run_dir or not playability.get("records_dir"):
        return {}
    try:  # the production gate's own readers: one definition of a record
        from wgf_production.checks import _entity_views
        from wgf_production.step import load_records
        projects = [p.get("id") for p in playability.get("projects") or []
                    if isinstance(p, dict) and p.get("ran")]
        records, _frames = load_records(os.path.join(run_dir, playability["records_dir"]),
                                        projects)
        out = {}
        for tests in records.values():
            for _eid, role, asset, _render, _has in _entity_views(tests):
                if role and asset:
                    out.setdefault(role, set()).add(asset)
        return out
    except Exception:  # evidence that cannot be read narrows nothing; it never fails the step
        return {}


class _Resolver:
    def __init__(self, requirements, rules, probe):
        self.rules = rules
        self.ids = {r.id for r in requirements}
        self.variants = {v: r.id for r in requirements for v in r.variant_ids()}
        self.by_role = {}
        for r in requirements:
            if r.role:
                self.by_role.setdefault(r.role, []).append(r.id)
        for role, assets in (probe or {}).items():
            for asset in assets:
                rid = self.canon(asset)
                if rid and rid not in self.by_role.setdefault(role, []):
                    self.by_role[role].append(rid)
        self.words = _role_words(rules)

    def canon(self, name):
        if name in self.ids:
            return name
        return self.variants.get(name)

    def names(self, names):
        return {rid for rid in (self.canon(n) for n in names or ()) if rid}

    def roles(self, roles):
        out = set()
        for role in _expand(self.rules, roles):
            out.update(self.by_role.get(role, ()))
        return out

    def text(self, *texts):
        """Requirement ids a text names: by id or variant id, or by a word of a role."""
        out = set()
        roles = set()
        for text in texts:
            low = (text or "").lower()
            out |= self.names(_ID_WORD.findall(low))
            for word in _WORD.findall(low):
                for form in _forms(word):
                    roles |= self.words.get(form, set())
                    out |= self.names([form])
        return out | self.roles(sorted(roles))


def _abs(path, run_dir):
    if not path:
        return None
    if os.path.isabs(path) or not run_dir:
        return path
    return os.path.normpath(os.path.join(run_dir, path))


def _inline(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


class _Collector:
    def __init__(self):
        self.items = {}
        self.unresolved = []

    def add(self, rids, reason, frames):
        frames = [f for f in frames or () if f]
        if not rids:
            self.unresolved.append((reason, frames))
            return
        for rid in sorted(rids):
            entry = self.items.setdefault(rid, {"reasons": [], "frames": []})
            if reason not in entry["reasons"]:
                entry["reasons"].append(reason)
            for frame in frames:
                if frame not in entry["frames"]:
                    entry["frames"].append(frame)


def _routes(report):
    """Where a report sends its failures. A triage-report routes one group: its selected
    group's route, while it routes one (docs/specialist-routing.md)."""
    if "selected" in report and "routes" not in report:
        selected = report.get("selected") or {}
        return [selected["route"]] if report.get("verdict") == "routed" and isinstance(
            selected, dict) and selected.get("route") else []
    return report.get("routes") or []


def _failing(report):
    return "assets" in _routes(report) and report.get("verdict") != "PASS"


def _select(reports, entered_by):
    """The reports to read: the one of the step named by `entered_by` (`<step>.<route>`),
    when it is among them, else every gate report routed to assets. A triage-report is read
    only when the triage step itself routed the run here."""
    routed = [(kind, report) for kind, report in reports if isinstance(report, dict)
              and "assets" in _routes(report)]
    if entered_by:
        source = str(entered_by).split(".", 1)[0]
        named = [(k, r) for k, r in routed if k == f"{source}-report"]
        if named:
            return named
    return [(k, r) for k, r in routed if k != "triage-report"]


def _triage(report, resolver, collect):
    """The selected findings of a triage-report that routed `assets`: each one's assets (or
    the requirements its words name), with what to change and the frames that show it."""
    by_id = {f.get("id"): f for f in report.get("findings") or [] if isinstance(f, dict)}
    for fid in (report.get("selected") or {}).get("findings") or []:
        finding = by_id.get(fid)
        if not finding:
            continue
        task = finding.get("task") or {}
        named = resolver.names(finding.get("assets")) or resolver.text(
            finding.get("summary"), task.get("change"))
        reason = f"{fid}: {finding.get('summary')} Change: {task.get('change')}"
        frames = [ref for ref in finding.get("evidence_refs") or []
                  if isinstance(ref, str) and ref.lower().endswith((".png", ".jpg", ".jpeg",
                                                                    ".webp"))]
        collect.add(named, reason, frames)


def _production(report, resolver, collect, run_dir, playability):
    frame_paths = {(f.get("project"), f.get("id")): f.get("path")
                   for f in (playability or {}).get("frames") or [] if isinstance(f, dict)}
    for check in report.get("checks") or []:
        if check.get("route") != "assets" or check.get("status") == "PASS":
            continue
        named = resolver.names(check.get("assets")) or resolver.text(check.get("summary"))
        reason = f"{check.get('id')}: {check.get('summary')}"
        if check.get("project"):
            reason += f" (viewport {check['project']})"
        if check.get("expected") is not None:
            reason += f" Expected: {_inline(check['expected'])}."
        if check.get("measured") is not None:
            reason += f" Measured: {_inline(check['measured'])}."
        frames = []
        for frame in check.get("frames") or []:
            path = frame_paths.get((check.get("project"), frame))
            frames.append(_abs(path, run_dir) if path else None)
        collect.add(named, reason, frames)


def _overview(report, run_dir):
    """One frame per viewport for each overview state: what a failure about every frame
    is shown with."""
    chosen, seen = [], set()
    frames = [f for f in report.get("frames") or [] if isinstance(f, dict)]
    for state in OVERVIEW_STATES:
        for frame in frames:
            key = (frame.get("project"), state)
            if frame.get("state") == state and key not in seen:
                seen.add(key)
                chosen.append(_abs(frame.get("path"), run_dir))
    return chosen


def _visual_qa(report, rules, resolver, collect, run_dir):
    frame_paths = {f.get("id"): _abs(f.get("path"), run_dir)
                   for f in report.get("frames") or [] if isinstance(f, dict)}
    overview = _overview(report, run_dir)
    blockers = {b.get("id"): b for b in rules.get("blockers") or [] if isinstance(b, dict)}
    for finding in report.get("findings") or []:
        if finding.get("route") != "assets":
            continue
        named = resolver.text(finding.get("id"), finding.get("summary"))
        rule = blockers.get(finding.get("id"))
        if rule and rule.get("rebuild_roles"):
            named |= resolver.roles(rule["rebuild_roles"])
        frame = frame_paths.get(finding.get("frame"))
        reason = (f"{finding.get('severity')} {finding.get('category')} finding "
                  f"`{finding.get('id')}`: {finding.get('summary')}")
        collect.add(named, reason, [frame] if frame else overview)

    failed = report.get("failed")
    failed = [str(x) for x in failed] if isinstance(failed, list) else []
    dimensions = rules.get("dimensions") or {}
    reasons = report.get("score_reasons") or {}
    bar = (report.get("rubric") or {}).get("pass_bar", rules.get("pass_bar"))
    for entry in failed:
        kind, _, name = entry.partition(":")
        if kind != "score":
            continue
        dimension = dimensions.get(name) or {}
        if dimension and dimension.get("route") != "assets":
            continue
        why = reasons.get(name) or "the judge gave no reason beyond the score"
        reason = (f"`{name}` scored {(report.get('scores') or {}).get(name)} of 5, below the "
                  f"bar {bar}"
                  + (f" ({dimension['question']})" if dimension.get("question") else "")
                  + f": {why}")
        collect.add(resolver.roles(dimension.get("rebuild_roles")), reason, overview)

    questions = {q.get("id"): q for q in rules.get("state_questions") or []
                 if isinstance(q, dict)}
    states = {(s.get("viewport"), s.get("state")): s for s in report.get("states") or []
              if isinstance(s, dict)}
    by_question = {}
    for entry in failed:
        kind, _, name = entry.partition(":")
        if kind != "state":
            continue
        where, _, qid = name.rpartition(":")
        viewport, _, state = where.partition("/")
        by_question.setdefault(qid, []).append((viewport, state))
    for qid, pairs in by_question.items():
        question = questions.get(qid) or {}
        if question and question.get("route") != "assets":
            continue
        seen = []
        frames = []
        for viewport, state in pairs:
            entry = states.get((viewport, state)) or {}
            if entry.get("comment"):
                seen.append(f"{viewport} {state}: {entry['comment']}")
            frames += [frame_paths.get(k) or k for k in entry.get("frames") or []]
        reason = (f"`{qid}` failed on " + ", ".join(f"{v} {s}" for v, s in pairs)
                  + (f" ({question['ask']})" if question.get("ask") else "")
                  + (". The judge saw - " + " | ".join(seen) if seen else ""))
        collect.add(resolver.roles(question.get("rebuild_roles")), reason, frames)

    look = rules.get("look") or {}
    if any(e.startswith("look:") for e in failed) and look.get("route", "assets") == "assets":
        verdict = (report.get("look") or {})
        reason = (f"the whole build looks like a {verdict.get('verdict') or 'developer-prototype'}"
                  f", not a finished game: "
                  f"{verdict.get('reason') or 'the judge gave no reason'}")
        collect.add(resolver.roles(look.get("rebuild_roles")), reason, overview)


def plan(reports, requirements, *, rules=None, run_dir=None, entered_by=None,
         playability=None, probe=None):
    """The Plan for `reports` ([(kind, report)]) against `requirements`. `rules`: the rubric
    (load_rules()); `run_dir`: what report frame paths are relative to; `entered_by`: the
    entry that brought the run here; `playability`: the playability-report the gate judged
    (production-quality frame ids, the probe's records); `probe`: {role: {asset id}}, read
    from `playability` when not given."""
    rules = load_rules() if rules is None else rules
    candidates = [r for r in requirements
                  if r.generate_now() and not r.placeholder_only and not r.existing]
    if probe is None:
        probe = probe_roles(playability, run_dir)
    resolver = _Resolver(candidates, rules, probe)
    # What a judge sees in frames is never a sound: visual QA and the fallback remake only
    # what is drawn.
    visual = _Resolver([r for r in candidates if r.kind not in AUDIO], rules, probe)
    collect = _Collector()
    selected = _select(reports, entered_by)
    for kind, report in selected:
        if kind == "production-quality-report":
            _production(report, resolver, collect, run_dir, playability)
        elif kind == "triage-report":
            _triage(report, resolver, collect)
        else:
            _visual_qa(report, rules, visual, collect, run_dir)
    reentry = any(_failing(r) for _k, r in selected)
    fallback = False
    if reentry and not collect.items:
        fallback = True
        roles = ((rules.get("rebuild") or {}).get("fallback")) or [
            "player", "threat", "goal", "target", "projectile", "collectible", "hazard",
            "environment", "background", "prop"]
        targets = visual.roles(roles)
        if targets:
            for reason, frames in list(collect.unresolved):
                collect.add(targets, reason, frames)
        if targets and not collect.unresolved:
            collect.add(targets, "the gate sent the build back to make its art again without "
                                 "naming an asset", [])
    elif collect.items:
        # What no requirement was named for still belongs to the art being made again.
        named = set(collect.items)
        for reason, frames in list(collect.unresolved):
            collect.add(named, f"about the build as a whole: {reason}", frames)
    for entry in collect.items.values():
        entry["frames"] = entry["frames"][:MAX_FRAMES]
    return Plan(collect.items, reentry, fallback, [k for k, _r in selected],
                [reason for reason, _f in collect.unresolved])


def rebuild_list(reports, requirements, **kwargs):
    """{requirement id: {"reasons", "frames"}}: `plan(...)`'s items."""
    return plan(reports, requirements, **kwargs).items
