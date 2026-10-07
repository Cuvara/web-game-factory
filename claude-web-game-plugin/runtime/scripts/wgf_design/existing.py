"""The existing-content floor: what an adopted game repository already ships.

When a run adopts a repository that exists (factory.init.adopt_existing), the content it
ships is a floor: the design may not plan less (consistency rule existing_content_floor_kept)
and the build may not ship less (content-sufficiency `content.regression`). Observed: a
release-tier design of 3 groups and 12 units passed every rule, G3 and init for a checkout
that already shipped 32 units in 4 worlds with 4 bosses.

    measure(units, data)        units, groups, climax units and elements of a content data
                                file's units, each by the first method of
                                core/reference/brief-commitments.yaml `existing_content`
                                that applies, the method recorded
    read_floor(config, title_id, git=None, run_id=None)
                                (floor, note): the adopted checkout's content at its shipped
                                commit - `game-design.existing_content` - or (None, why none)
    read_adoption(config, title_id, git=None, run_id=None)
                                (floor, note, units): read_floor and the shipped content data
                                file's units themselves (the starting units of an adoption)
    shipped_commit(reader, head, run_id, config=None)
                                the commit the checkout ships: factory.init.accepted_baseline
                                when set, else HEAD less the run's own commits on top of it
    reconcile(previous, current)
                                the floor a design visit records: the previous one while the
                                checkout ships the same commit, else the one measured now -
                                with `supersedes` when its content differs (a person moved
                                the checkout)
    adoption_units(units)       shipped units in the design's unit shape (the starting units)
    floor_view(design)          {"floor": ..., "short": [...]}: rule existing_content_floor_kept
    regression(floor, data)     what a build's content data file drops below the floor

The floor is read from the commit, never the working tree, and records that commit: an
uncommitted edit is not what the repository ships.

Every design visit measures it again. Observed (2026-10-07, the 3D run): a person moved the
adopted checkout to a human-accepted content set (12 courses first-roll..the-summit) and
resumed the run from strategy; the re-entered design kept the floor its earlier visit had
counted at an intermediate commit of the run's own build (meadow-roll..storm-crown), kept
those units, and greybox briefed a developer to rewrite the accepted courses into them. The
shipped commit is HEAD less the commits this run made on top of it (each carries a
`Wgf-<Step>-Key:` trailer naming the run id): the run's own build in progress never moves the
floor, a person's commit always does. When the content measured now differs from the earlier
floor, the new floor records the one it replaces in `supersedes`.

A checkout whose HEAD ships no content data file still has a floor - a null floor never means
no floor. Observed (2026-10-05, the 3D run): the adopted checkout predated the content
contract, its 12 courses lived in source code, and the design, the regression check and
develop's floor check all held it to nothing. Such a floor is recorded `status: unmeasured`
at that commit and measured on the shipped build itself:

    probe_count(records)        units, groups, climax units and element kinds the play probe
                                reached in the playability records of one visit
    probe_floor(floor, records, commit, report=None, step=None)
                                (floor, note): the unmeasured floor measured on the records of
                                a visit that played its commit - or (None, why not)
    effective(design, playability=None)
                                the floor the run holds the build to: the design's when it is
                                measured, else the probe floor a playability-report carries,
                                else the design's unmeasured one (None: the run adopted nothing)
    measured(floor)             whether the floor holds numbers
    content_modules(paths)      the shipped source files of content modules among `paths`: what
                                a commit may not delete while no content data file counts the
                                build (brief-commitments.yaml `existing_content.unmeasured`)

A floor once measured is the run's: a build that gains a content data file is held to the
earlier count, never re-floored on its own file.
"""

import copy
import glob
import json
import os
import re

from wgflib import checkout, mechanics, paths
from wgflib.yamllite import load_file

from . import commitments

__all__ = ["measure", "read_floor", "read_adoption", "floor_view", "regression", "QUANTITIES",
           "UNMEASURED", "PROBE", "measured", "method", "probe_count", "probe_floor",
           "effective", "content_modules", "regression_counts", "run_probe_floor",
           "shipped_commit", "run_commit", "reconcile", "adoption_units", "shipped_ids"]

# The quantities a floor holds, in report order, with their design-side reading.
QUANTITIES = ("units", "groups", "climax_units", "elements")
# A floor recorded at a commit whose content data file does not exist: no number yet.
UNMEASURED = "unmeasured"
# How a floor is counted (source.method): on the content data file, or on the played build.
CONTENT_DATA, PROBE = "content-data", "probe"
# The entity roles that carry a content kind, read where the content-sufficiency step reads
# them (its own `probe` block): one vocabulary for the floor and the build it holds.
SUFFICIENCY_PATH = os.path.join(paths.REFERENCE, "content-sufficiency.yaml")


def measured(floor):
    """Whether `floor` holds numbers: a dict that is not `status: unmeasured`."""
    return isinstance(floor, dict) and floor.get("status") != UNMEASURED


def method(floor):
    return ((floor or {}).get("source") or {}).get("method") or CONTENT_DATA


def _units(data):
    return [u for u in (data or {}).get("units") or [] if isinstance(u, dict)]


def measure(units, data=None):
    """{units, groups, climax_units, elements, unit_ids, measured_by}. A quantity no method
    measures is None (and holds nothing)."""
    data = data if data is not None else commitments.load()
    rules = data.get("existing_content") or {}
    units = [u for u in units or [] if isinstance(u, dict)]
    out = {"units": len(units), "unit_ids": [str(u.get("id")) for u in units if u.get("id")],
           "measured_by": {"units": "every unit listed"}}

    group = rules.get("group") or {}
    field = group.get("field")
    groups = None
    if field and units and all(u.get(field) for u in units):
        groups = {str(u[field]) for u in units}
        out["measured_by"]["groups"] = f"units[].{field}"
    elif group.get("id_pattern") and units:
        pattern = re.compile(group["id_pattern"])
        found = [pattern.match(str(u.get("id") or "").lower()) for u in units]
        if all(found) and len({m.group(1) for m in found}) >= 2:
            groups = {m.group(1) for m in found}
            out["measured_by"]["groups"] = f"unit id prefix {group['id_pattern']}"
    out["groups"] = len(groups) if groups is not None else None

    climax = rules.get("climax") or {}
    field, value = climax.get("field"), climax.get("value")
    if field and any(field in u for u in units):
        out["climax_units"] = sum(1 for u in units if u.get(field) == value)
        out["measured_by"]["climax_units"] = f"units[].{field} == {value}"
    elif climax.get("text_fields") and units:
        terms = ((data.get("quantities") or {}).get("climax") or {})
        phrases = list(terms.get("singular") or []) + list(terms.get("plural") or [])
        out["climax_units"] = sum(
            1 for u in units if mechanics.phrases_in(
                " ".join(str(u.get(f) or "") for f in climax["text_fields"]), phrases))
        out["measured_by"]["climax_units"] = (
            f"a climax term in units[].{'/'.join(climax['text_fields'])}")
    else:
        out["climax_units"] = None

    field = (rules.get("elements") or {}).get("field")
    if field and any(isinstance(u.get(field), list) for u in units):
        out["elements"] = len({str(e) for u in units for e in u.get(field) or []})
        out["measured_by"]["elements"] = f"units[].{field}"
    else:
        out["elements"] = None
    return out


class _Git:
    """The commit and file reads, through the develop module's hardened git (wgflib.procs
    owns the process): never a repository-defined command."""

    def __init__(self, root):
        from wgf_develop.repository import GitRepo, Runner
        self.repo = GitRepo(root, Runner())

    def head(self):
        return self.repo.head() if self.repo.is_repository() else None

    def file_at(self, commit, path):
        return self.repo.file_at(commit, path)

    def commits(self, head, depth=200):
        return self.repo.commits(head, depth)

    def resolve(self, ref):
        return self.repo.resolve(ref)


# A commit a workflow step made carries `Wgf-<Step>-Key: <key>`, and every step key names the
# run id (`<run>:<step>:<visit>`, `wgf-init:<run>:init`).
_KEY_TRAILER = re.compile(r"^Wgf-[A-Za-z-]+-Key:\s*(\S+)\s*$")


def run_commit(message, run_id):
    """Whether the commit `message` was made by a step of the run `run_id`."""
    if not run_id:
        return False
    for line in str(message or "").splitlines():
        found = _KEY_TRAILER.match(line.strip())
        if found and str(run_id) in found.group(1).split(":"):
            return True
    return False


def shipped_commit(reader, head, run_id, config=None):
    """(commit, how): the commit whose content is the floor. factory.init.accepted_baseline
    when set (a ref the checkout must hold); else HEAD less the run's own commits on top of it
    - the newest first-parent ancestor of HEAD this run did not make. A reader that cannot
    list commits (or a history of only the run's commits) gives HEAD."""
    accepted = _section(config, "init").get("accepted_baseline")
    if accepted is not None:
        resolve = getattr(reader, "resolve", None)
        commit = resolve(accepted) if resolve and isinstance(accepted, str) else None
        if not commit:
            raise ValueError(f"factory.init.accepted_baseline {accepted!r} names no commit of "
                             "the adopted checkout")
        return commit, f"factory.init.accepted_baseline {accepted}"
    listing = getattr(reader, "commits", None)
    if not run_id or listing is None:
        return head, "HEAD"
    skipped = 0
    for sha, message in listing(head) or []:
        if not run_commit(message, run_id):
            return sha, ("HEAD" if not skipped else
                         f"HEAD less {skipped} commit(s) this run made on top of it")
        skipped += 1
    return head, "HEAD"


def _section(config, name):
    if config is None:
        return {}
    if hasattr(config, "section"):
        return config.section(name) or {}
    return (config.get(name) if isinstance(config, dict) else None) or {}


def read_floor(config, title_id, git=None, data=None, environ=None, run_id=None):
    """(floor, note). The floor is None - and the note says why - when the run adopts nothing
    (factory.init.adopt_existing is not true), there is no checkout yet, or it has no commit.
    `git(root)` builds the reader (tests); `run_id` names the run whose own commits on top of
    HEAD are not what the checkout ships (shipped_commit)."""
    floor, note, _units = read_adoption(config, title_id, git, data, environ, run_id)
    return floor, note


def read_adoption(config, title_id, git=None, data=None, environ=None, run_id=None):
    """(floor, note, units): read_floor, and the units of the content data file the floor
    was counted on ([] when it is unmeasured or there is none)."""
    if _section(config, "init").get("adopt_existing") is not True:
        return None, "the run adopts no existing repository (factory.init.adopt_existing)", []
    data = data if data is not None else commitments.load()
    path = (data.get("existing_content") or {}).get("path") or "public/content/units.json"
    try:
        root, source = checkout.locate(config, None, "init", None, environ, name=title_id)
    except checkout.CheckoutError as exc:
        return None, f"no checkout to adopt: {exc}", []
    if not os.path.isdir(root):
        return None, f"no checkout at {root} ({source}) yet: nothing shipped to floor", []
    reader = (git or _Git)(root)
    head = reader.head()
    if not head:
        return None, f"{root} has no commit: nothing shipped to floor", []
    commit, how = shipped_commit(reader, head, run_id, config)
    text = reader.file_at(commit, path)
    if text is None:
        # Its content lives somewhere else (source code that predates the content contract):
        # the floor exists and is measured on the shipped build through the probe.
        reason = (f"{root} at {commit[:12]} ships no {path}: the floor is measured on the "
                  f"shipped build through the play probe, by the first greybox-playability "
                  f"visit, which plays this commit before any developer change")
        return ({"status": UNMEASURED,
                 "source": {"method": PROBE, "path": path, "commit": commit,
                            "checkout": root.replace(os.sep, "/"), "located_by": source},
                 "ruleset": f"brief-commitments@{data.get('version')}",
                 "reason": reason}, reason, [])
    try:
        content = json.loads(text)
    except ValueError as exc:
        # Shipped but unreadable: refusing to count it would wave the floor away.
        raise ValueError(f"{path} at {commit[:12]} of the adopted checkout is not JSON: {exc}")
    if not isinstance(content, dict):
        raise ValueError(f"{path} at {commit[:12]} of the adopted checkout is not an object")
    units = _units(content)
    counted = measure(units, data)
    floor = {"source": {"method": CONTENT_DATA, "path": path, "commit": commit,
                        "checkout": root.replace(os.sep, "/"), "located_by": source},
             "ruleset": f"brief-commitments@{data.get('version')}"}
    if commit != head:
        floor["source"]["head"] = head
        floor["source"]["baseline"] = how
    floor.update({k: counted[k] for k in QUANTITIES if counted.get(k) is not None})
    floor["unit_ids"] = counted["unit_ids"]
    floor["measured_by"] = counted["measured_by"]
    return floor, (f"the adopted checkout ships {counted['units']} unit(s) at "
                   f"{commit[:12]} ({how}): the design's floor"), units


def shipped_ids(floor):
    """The unit ids a measured floor ships, as a set (empty for an unmeasured one)."""
    return {str(u) for u in (floor or {}).get("unit_ids") or []} if measured(floor) else set()


def reconcile(previous, current):
    """The floor this design visit records. `previous`: the floor the run's last design
    recorded, or None; `current`: the one read now (read_floor), or None when nothing could
    be read. The previous floor stands while the checkout ships the same commit - the run's
    own build never re-floors it - and when nothing could be read now. Otherwise the floor is
    the one measured now, and when its units or numbers differ from the previous one it
    records that floor in `supersedes`: a person moved the checkout."""
    if not isinstance(previous, dict):
        return current
    if not isinstance(current, dict):
        return previous
    was = (previous.get("source") or {}).get("commit")
    now = (current.get("source") or {}).get("commit")
    if _same_commit(was, now):
        return previous
    same = (measured(previous) == measured(current)
            and list(previous.get("unit_ids") or []) == list(current.get("unit_ids") or [])
            and all(previous.get(q) == current.get(q) for q in QUANTITIES))
    if same:
        return current
    out = copy.deepcopy(current)
    gone = {"status": "measured" if measured(previous) else UNMEASURED,
            "unit_ids": list(previous.get("unit_ids") or [])}
    if was:
        gone["commit"] = str(was)
    gone.update({q: previous[q] for q in QUANTITIES if isinstance(previous.get(q), int)})
    out["supersedes"] = gone
    return out


# The fields of a shipped unit the design's unit shape holds (game-design
# build_spec.content.units[]); the rest (a layout, a display name) stays in the content data.
_UNIT_FIELDS = ("id", "index", "tier", "purpose", "objective", "objective_kind", "group",
                "structure", "elements", "start_state", "end_state", "mechanics", "introduces",
                "difficulty", "expected_duration_s", "success", "failure", "acceptance", "art",
                "variation_from_previous", "parameters")


def adoption_units(units):
    """The shipped units as the starting units of a design: each unit's design fields, in
    shipped order, under its own id."""
    return [{k: copy.deepcopy(u[k]) for k in _UNIT_FIELDS if k in u}
            for u in units or [] if isinstance(u, dict) and u.get("id")]


def _design_counts(design):
    planned = commitments.design_counts(design)
    spec = (design or {}).get("build_spec") or {}
    content = spec.get("content") if isinstance(spec.get("content"), dict) else {}
    elements = {str(e.get("id") if isinstance(e, dict) else e)
                for e in content.get("elements") or []}
    for unit in content.get("units") or []:
        if isinstance(unit, dict) and unit.get("tier") != "optional":
            elements |= {str(e) for e in unit.get("elements") or []}
    return {"units": planned["units"], "groups": planned["groups"],
            "climax_units": planned["climax"], "elements": len(elements)}


def floor_view(design):
    """{"floor": {quantity: n}, "short": ["<quantity>: the design plans n, the adopted
    checkout ships m at <commit>"]}."""
    floor = (design or {}).get("existing_content")
    if not isinstance(floor, dict):
        return {"floor": {}, "short": []}
    planned = _design_counts(design)
    commit = str((floor.get("source") or {}).get("commit") or "")[:12]
    short = [f"{q}: the design plans {planned[q]}, the adopted checkout ships {floor[q]} at "
             f"{commit} ({(floor.get('measured_by') or {}).get(q, 'counted')})"
             for q in QUANTITIES if isinstance(floor.get(q), int) and planned[q] < floor[q]]
    planned_ids = {str(u.get("id")) for u in commitments.planned_units(design)}
    dropped = sorted(set(floor.get("unit_ids") or []) - planned_ids)
    if dropped:
        short.append(f"unit ids: the design drops {len(dropped)} unit(s) the adopted checkout "
                     f"ships at {commit} ({', '.join(dropped[:8])}"
                     + (f" and {len(dropped) - 8} more" if len(dropped) > 8 else "")
                     + "); keep each shipped unit under its own id")
    return {"floor": {q: floor[q] for q in QUANTITIES if isinstance(floor.get(q), int)},
            "short": short}


def regression(floor, content, data=None):
    """(problems, measured): what the build's content data file ships below the floor, each
    quantity counted on the build by the method the floor was counted by."""
    return regression_counts(floor, measure(_units(content), data))


def regression_counts(floor, counted):
    """(problems, measured): `counted` - measure() of a content data file, or probe_count()
    of a played build - below each quantity and shipped unit of the floor."""
    commit = str((floor.get("source") or {}).get("commit") or "")[:12]
    problems = []
    for q in QUANTITIES:
        want = floor.get(q)
        have = counted.get(q)
        if not isinstance(want, int):
            continue
        if have is None:
            problems.append(f"{q}: the build no longer states them "
                            f"({(floor.get('measured_by') or {}).get(q)}); {want} shipped at "
                            f"{commit}")
        elif have < want:
            problems.append(f"{q}: the build ships {have}, {want} shipped at {commit}")
    gone = sorted(set(floor.get("unit_ids") or []) - set(counted.get("unit_ids") or []))
    if gone:
        problems.append(f"shipped units gone: {', '.join(gone[:12])}"
                        + (f" and {len(gone) - 12} more" if len(gone) > 12 else ""))
    measured_now = {q: counted.get(q) for q in QUANTITIES}
    measured_now["missing_unit_ids"] = gone[:40]
    return problems, measured_now


# -- the floor of a checkout with no content data file: measured on the shipped build -------

def _kind_roles(path=None):
    probe = (load_file(path or SUFFICIENCY_PATH) or {}).get("probe") or {}
    return set(probe.get("kind_roles") or []), set(probe.get("not_content_roles") or [])


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def probe_count(records, data=None, roles=None):
    """{units, groups, climax_units, elements, unit_ids, reported_unit_count, measured_by} of
    a played build, over the playability records {project: {test: record}}: the distinct
    units the probe reported in play, the largest unit count it stated, groups by the unit id
    pattern, climax units by a climax term in the probe's objective, and the distinct kinds of
    content-role entities drawn while a unit was in play. A quantity nothing showed is None."""
    data = data if data is not None else commitments.load()
    rules = data.get("existing_content") or {}
    kind_roles, not_content = roles if roles is not None else _kind_roles()
    ids, objectives, kinds = [], {}, set()
    reported = 0

    def saw_unit(uid, objective=None):
        if not uid:
            return
        uid = str(uid)
        if uid not in ids:
            ids.append(uid)
        if objective:
            objectives.setdefault(uid, []).append(str(objective))

    def saw_snapshot(snapshot):
        if not isinstance(snapshot, dict):
            return 0
        content = snapshot.get("content") if isinstance(snapshot.get("content"), dict) else {}
        if content.get("unit_id"):
            saw_unit(content["unit_id"], content.get("objective"))
            for entity in snapshot.get("entities") or []:
                if isinstance(entity, dict) and entity.get("role") in kind_roles \
                        and entity.get("kind"):
                    kinds.add(str(entity["kind"]))
        return _number(content.get("unit_count")) or 0

    for record in (records or {}).values():
        record = record or {}
        first = record.get("first-session") or {}
        for sample in first.get("samples") or []:
            reported = max(reported, saw_snapshot(sample))
        for acted in (record.get("act") or {}).get("acted") or []:
            if isinstance(acted, dict):
                reported = max(reported, saw_snapshot(acted.get("before")),
                               saw_snapshot(acted.get("after")))
        traverse = record.get("traverse") or {}
        reported = max(reported, _number(traverse.get("unit_count_reported")) or 0)
        for snapshot in traverse.get("snapshots") or []:
            if isinstance(snapshot, dict) and snapshot.get("unit_id"):
                saw_unit(snapshot["unit_id"])
                kinds.update(str(k) for k in snapshot.get("kinds") or [])
        for played in traverse.get("per_unit") or []:
            if not isinstance(played, dict) or not played.get("unit_id"):
                continue
            saw_unit(played["unit_id"], played.get("objective"))
            kinds.update(str(k) for k in played.get("kinds") or [])
        for visit in (record.get("survey") or {}).get("visits") or []:
            if not isinstance(visit, dict) or not visit.get("entered"):
                continue
            saw_unit(visit.get("unit_id") or visit.get("asked"))
            for role, found in (visit.get("kinds_by_role") or {}).items():
                if role not in not_content:
                    kinds.update(str(k) for k in found or [])

    out = {"unit_ids": ids, "reported_unit_count": reported or None, "measured_by": {}}
    if not ids and not reported:
        out.update({q: None for q in QUANTITIES})
        return out
    out["units"] = max(len(ids), reported)
    out["measured_by"]["units"] = (
        f"the play probe: {len(ids)} distinct content.unit_id reached"
        + (f", content.unit_count {reported} reported by the build" if reported else ""))
    group = rules.get("group") or {}
    out["groups"] = None
    if group.get("id_pattern") and ids:
        pattern = re.compile(group["id_pattern"])
        found = [pattern.match(uid.lower()) for uid in ids]
        if all(found) and len({m.group(1) for m in found}) >= 2:
            out["groups"] = len({m.group(1) for m in found})
            out["measured_by"]["groups"] = (f"the play probe: unit id prefix "
                                            f"{group['id_pattern']} over the units reached")
    terms = (data.get("quantities") or {}).get("climax") or {}
    phrases = list(terms.get("singular") or []) + list(terms.get("plural") or [])
    if objectives and phrases:
        out["climax_units"] = sum(1 for uid in ids if mechanics.phrases_in(
            " ".join(objectives.get(uid) or []), phrases))
        out["measured_by"]["climax_units"] = ("the play probe: a climax term in "
                                              "content.objective of the units reached")
    else:
        out["climax_units"] = None
    if kinds:
        out["elements"] = len(kinds)
        out["measured_by"]["elements"] = ("the play probe: distinct entity kinds of a content "
                                          "role drawn while a unit was in play")
    else:
        out["elements"] = None
    return out


def _same_commit(a, b):
    a, b = str(a or ""), str(b or "")
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def probe_floor(floor, records, commit, report=None, step=None, data=None, roles=None):
    """(floor, note). The unmeasured `floor` counted on `records`, the playability records of
    a visit that played `commit` - which must be the floor's own commit: the shipped build,
    before any developer change. (None, why) when it is not, or the probe reached no unit."""
    if not isinstance(floor, dict) or measured(floor):
        return None, "no unmeasured floor to measure"
    at = str((floor.get("source") or {}).get("commit") or "")
    if not _same_commit(at, commit):
        return None, (f"the visit played {str(commit)[:12]}, not the shipped build "
                      f"{at[:12]}: the floor stays unmeasured")
    data = data if data is not None else commitments.load()
    counted = probe_count(records, data, roles)
    if counted.get("units") is None:
        return None, (f"the shipped build at {at[:12]} reported no content unit through the "
                      "play probe: the floor stays unmeasured")
    source = dict(floor.get("source") or {})
    source.update(method=PROBE, commit=commit)
    if report:
        source["report"] = report
    if step:
        source["step"] = step
    out = {"status": "measured", "source": source,
           "ruleset": f"brief-commitments@{data.get('version')}",
           "reason": (f"the adopted checkout ships no {source.get('path') or 'content data'}: "
                      f"counted on the shipped build at {commit[:12]} through the play probe")}
    out.update({q: counted[q] for q in QUANTITIES if counted.get(q) is not None})
    out["unit_ids"] = counted["unit_ids"]
    out["measured_by"] = counted["measured_by"]
    return out, (f"the shipped build at {commit[:12]} reached {counted['units']} unit(s) "
                 "through the play probe: the floor")


def effective(design, playability=None):
    """The floor the run holds a build to, or None when the run adopted nothing: the design's
    when it holds numbers; else the probe floor `playability` (a playability-report) carries;
    else the design's unmeasured floor."""
    floor = (design or {}).get("existing_content")
    if not isinstance(floor, dict):
        return None
    if measured(floor):
        return floor
    carried = (playability or {}).get("existing_content")
    if measured(carried) and _same_commit(
            (carried.get("source") or {}).get("commit"),
            (floor.get("source") or {}).get("commit")):
        return carried
    return floor


def _words(path):
    return [w for w in re.split(r"[-_./\\\s]+", str(path).lower()) if w]


def content_modules(files, data=None):
    """The files among `files` (repository paths) that are shipped source files of content
    modules: under a root of brief-commitments.yaml `existing_content.unmeasured.roots`, with
    a path word that is a unit, group or climax term, or one of its `terms`."""
    data = data if data is not None else commitments.load()
    rules = (data.get("existing_content") or {}).get("unmeasured") or {}
    roots = [str(r).strip("/") for r in rules.get("roots") or []]
    terms = {str(t).lower() for t in rules.get("terms") or []}
    for quantity in (data.get("quantities") or {}).values():
        if isinstance(quantity, dict):
            for word in list(quantity.get("singular") or []) + list(quantity.get("plural") or []):
                if " " not in str(word):
                    terms.add(str(word).lower())
    out = []
    for path in files or []:
        path = str(path)
        if not any(path == r or path.startswith(r + "/") for r in roots):
            continue
        if terms & set(_words(path)):
            out.append(path)
    return out


def run_probe_floor(run_dir, floor):
    """The earliest probe floor a playability-report of the run at `run_dir` recorded for the
    unmeasured `floor` (the same commit), or None: a floor once measured is the run's, so the
    first measurement wins over any later one."""
    if not run_dir or not isinstance(floor, dict) or measured(floor):
        return None
    at = (floor.get("source") or {}).get("commit")
    found = []
    for path in glob.glob(os.path.join(run_dir, "artifacts", "playability-report", "v*.json")):
        stem = os.path.basename(path)[1:-5]
        try:
            with open(path, encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, ValueError):
            continue
        carried = report.get("existing_content") if isinstance(report, dict) else None
        if measured(carried) and _same_commit((carried.get("source") or {}).get("commit"), at):
            found.append((int(stem) if stem.isdigit() else 10 ** 9, carried))
    return min(found, key=lambda item: item[0])[1] if found else None
