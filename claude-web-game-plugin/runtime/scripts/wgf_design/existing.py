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
    read_floor(config, title_id, git=None)
                                (floor, note): the adopted checkout's content at its HEAD
                                commit - `game-design.existing_content` - or (None, why none)
    floor_view(design)          {"floor": ..., "short": [...]}: rule existing_content_floor_kept
    regression(floor, data)     what a build's content data file drops below the floor

The floor is read from the commit, never the working tree, and records that commit: an
uncommitted edit is not what the repository ships.
"""

import json
import os
import re

from wgflib import checkout, mechanics

from . import commitments

__all__ = ["measure", "read_floor", "floor_view", "regression", "QUANTITIES"]

# The quantities a floor holds, in report order, with their design-side reading.
QUANTITIES = ("units", "groups", "climax_units", "elements")


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


def _section(config, name):
    if config is None:
        return {}
    if hasattr(config, "section"):
        return config.section(name) or {}
    return (config.get(name) if isinstance(config, dict) else None) or {}


def read_floor(config, title_id, git=None, data=None, environ=None):
    """(floor, note). The floor is None - and the note says why - when the run adopts nothing
    (factory.init.adopt_existing is not true), there is no checkout yet, or its HEAD ships no
    content data file. `git(root)` builds the reader (tests)."""
    if _section(config, "init").get("adopt_existing") is not True:
        return None, "the run adopts no existing repository (factory.init.adopt_existing)"
    data = data if data is not None else commitments.load()
    path = (data.get("existing_content") or {}).get("path") or "public/content/units.json"
    try:
        root, source = checkout.locate(config, None, "init", None, environ, name=title_id)
    except checkout.CheckoutError as exc:
        return None, f"no checkout to adopt: {exc}"
    if not os.path.isdir(root):
        return None, f"no checkout at {root} ({source}) yet: nothing shipped to floor"
    reader = (git or _Git)(root)
    commit = reader.head()
    if not commit:
        return None, f"{root} has no commit: nothing shipped to floor"
    text = reader.file_at(commit, path)
    if text is None:
        return None, f"{root} at {commit[:12]} ships no {path}: nothing to floor"
    try:
        content = json.loads(text)
    except ValueError as exc:
        # Shipped but unreadable: refusing to count it would wave the floor away.
        raise ValueError(f"{path} at {commit[:12]} of the adopted checkout is not JSON: {exc}")
    if not isinstance(content, dict):
        raise ValueError(f"{path} at {commit[:12]} of the adopted checkout is not an object")
    counted = measure(_units(content), data)
    floor = {"source": {"path": path, "commit": commit,
                        "checkout": root.replace(os.sep, "/"), "located_by": source},
             "ruleset": f"brief-commitments@{data.get('version')}"}
    floor.update({k: counted[k] for k in QUANTITIES if counted.get(k) is not None})
    floor["unit_ids"] = counted["unit_ids"]
    floor["measured_by"] = counted["measured_by"]
    return floor, (f"the adopted checkout ships {counted['units']} unit(s) at "
                   f"{commit[:12]}: the design's floor")


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
    counted = measure(_units(content), data)
    commit = str((floor.get("source") or {}).get("commit") or "")[:12]
    problems = []
    for q in QUANTITIES:
        want = floor.get(q)
        have = counted.get(q)
        if not isinstance(want, int):
            continue
        if have is None:
            problems.append(f"{q}: the build's content data no longer states them "
                            f"({(floor.get('measured_by') or {}).get(q)}); {want} shipped at "
                            f"{commit}")
        elif have < want:
            problems.append(f"{q}: the build ships {have}, {want} shipped at {commit}")
    gone = sorted(set(floor.get("unit_ids") or []) - set(counted["unit_ids"]))
    if gone:
        problems.append(f"shipped units gone: {', '.join(gone[:12])}"
                        + (f" and {len(gone) - 12} more" if len(gone) > 12 else ""))
    measured = {q: counted.get(q) for q in QUANTITIES}
    measured["missing_unit_ids"] = gone[:40]
    return problems, measured
