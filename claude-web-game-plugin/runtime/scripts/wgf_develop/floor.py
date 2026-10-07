"""The existing-content floor, held at the commit: an adopted game is improved, never rebuilt.

Observed (2026-10-04, both validation games): once init adopted the shipped checkouts, the
greybox developer rewrote them to the new design - 12,168 deletions in the 2D game, its
content data cut from 32 units to 12. The design records what the adopted repository ships
(game-design existing_content, wgf_design/existing.py); this module holds a development
commit to it:

    adopted(design)                 whether the run adopted a repository that ships content
    effective(design, playability, run_dir)
                                    the floor this visit is held to: the design's, or - when
                                    the design recorded it unmeasured (the checkout ships no
                                    content data file) - the probe floor the run's playability
                                    measured on the shipped build, else still unmeasured
    problems(checkout, design, git, findings_visit)
                                    (problems, allowed): what the working tree ships below
                                    the floor - its content data counted by the floor's own
                                    method - and the files the floor's commit shipped under
                                    `public/` that are gone. A visit routed with findings (a
                                    specialist) may remove a shipped file - returned in
                                    `allowed` - never content below the floor. While nothing
                                    counts the build (the floor is unmeasured, or measured by
                                    the probe and the tree ships no content data file), no
                                    visit may delete a shipped source file of a content module.
    shipped_units(checkout, design) the unit ids the checkout's content data lists
    replacement(design, git, phase) why a visit may not start a developer: the design drops
                                    units the adopted checkout ships while it lists units the
                                    checkout does not - a rewrite of the shipped game, not an
                                    improvement - or None

Observed (2026-10-07, the 3D run): a person moved the adopted checkout to human-accepted
courses; the design still listed the run's earlier replacement courses, and greybox started a
paid developer session to rewrite the accepted courses into them. The visit is refused first.
"""

import json
import os

from wgf_design import commitments, existing

__all__ = ["adopted", "effective", "problems", "shipped_units", "replacement",
           "SHIPPED_ROOT"]

# The shipped files a commit may not lose: what the game serves.
SHIPPED_ROOT = "public"


def adopted(design):
    return isinstance((design or {}).get("existing_content"), dict)


def effective(design, playability=None, run_dir=None):
    """The floor (game-design existing_content shape) a visit is held to, or None."""
    floor = existing.effective(design, playability)
    if floor is None or existing.measured(floor):
        return floor
    return existing.run_probe_floor(run_dir, floor) or floor


def _content(checkout, floor):
    path = (floor.get("source") or {}).get("path") or "public/content/units.json"
    full = os.path.join(checkout, *path.split("/"))
    if not os.path.isfile(full):
        return None, f"{path} is gone"
    try:
        with open(full, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, f"{path} cannot be read: {exc}"
    if not isinstance(data, dict):
        return None, f"{path} is not a JSON object"
    return data, None


def _gone(checkout, files):
    return [path for path in files
            if not os.path.lexists(os.path.join(checkout, *path.split("/")))]


def _listed(paths, limit=8):
    return ", ".join(paths[:limit]) + (f" and {len(paths) - limit} more"
                                       if len(paths) > limit else "")


def problems(checkout, design, git, findings_visit=False):
    floor = (design or {}).get("existing_content")
    if not isinstance(floor, dict):
        return [], []
    found = []
    commit = (floor.get("source") or {}).get("commit")
    counted = False
    deleted = []
    if existing.measured(floor):
        data, problem = _content(checkout, floor)
        if data is not None:
            regressed, _measured = existing.regression(floor, data)
            found += regressed
            counted = True
        elif existing.method(floor) != existing.PROBE:
            found.append(f"{problem}; the adopted repository shipped {floor.get('units')} "
                         f"unit(s)")
            counted = True
    if not counted:
        # Nothing counts this tree's content: the source files the shipped content lives in
        # are what holds it, and none of them may go - not even for a finding.
        rules = (commitments.load().get("existing_content") or {}).get("unmeasured") or {}
        shipped = git.files_at(commit, *(rules.get("roots") or [SHIPPED_ROOT]))
        deleted = _gone(checkout, existing.content_modules(shipped))
        if deleted:
            state = ("the floor is not measured yet" if not existing.measured(floor) else
                     "the floor was measured through the play probe and this tree ships no "
                     "content data file to count it")
            found.append(f"{len(deleted)} shipped source file(s) of content modules the "
                         f"adopted repository shipped at {str(commit)[:12]} are gone while "
                         f"{state}: {_listed(deleted)}")
    missing = [path for path in _gone(checkout, git.files_at(commit, SHIPPED_ROOT))
               if path not in deleted]
    allowed = []
    if missing and findings_visit:
        allowed = missing
    elif missing:
        found.append(f"{len(missing)} file(s) the adopted repository shipped at "
                     f"{str(commit)[:12]} are gone: {_listed(missing)}")
    return found, allowed


def shipped_units(checkout, design):
    floor = (design or {}).get("existing_content") or {}
    data, _problem = _content(checkout, floor)
    if data is None and existing.method(floor) == existing.PROBE:
        return list(floor.get("unit_ids") or [])
    return [str(u.get("id")) for u in (data or {}).get("units") or []
            if isinstance(u, dict) and u.get("id")]


def replacement(design, git, phase=None, run_id=None, config=None):
    """A reason (str) the visit is refused before any developer starts, or None. Read against
    what the checkout ships - its content data at the shipped commit (HEAD less this run's
    own commits: never the run's greybox or develop build) - and the design's floor, the
    design of an adopted run either drops shipped units while listing units the checkout
    does not ship, or keeps the shipped ids for other units (existing.is_rewrite): briefed,
    a developer would replace the shipped game with another one. `phase` is reported only."""
    floor = (design or {}).get("existing_content")
    if not isinstance(floor, dict):
        return None
    planned_units = commitments.planned_units(design)
    planned = [str(u.get("id")) for u in planned_units if u.get("id")]
    shipped = list(existing.shipped_ids(floor) and floor.get("unit_ids") or [])
    at = str((floor.get("source") or {}).get("commit") or "")[:12]
    where = f"the floor at {at}"
    holds = shipped
    units, commit = (existing.shipped_units_at(git, floor, run_id, config)
                     if git is not None else ([], None))
    if units:
        # The design's floor may be stale - counted before a person moved the checkout.
        holds = [str(u.get("id")) for u in units if u.get("id")]
        shipped = list(dict.fromkeys(shipped + holds))
        where = f"the floor at {at} and the content data shipped at {str(commit)[:12]}"
    if not shipped:
        return None
    rerun = (" No developer is started on a rewrite of the shipped game. Run the design "
             "again on this checkout (`wgf resume <run> --from design`): it measures what the "
             "checkout ships now and starts from those units.")
    dropped = [u for u in shipped if u not in set(planned)]
    added = [u for u in planned if u not in set(holds)]
    if dropped and added:
        return (f"the game-design replaces the adopted game's content instead of extending "
                f"it: it drops {len(dropped)} unit(s) the checkout ships ({where}: "
                f"{_listed(dropped)}) and lists {len(added)} the checkout does not "
                f"({_listed(added)})." + rerun)
    rewrite, changed, kept = existing.is_rewrite(units, planned_units)
    if rewrite:
        sample = changed[0]
        fields = existing.unit_changes(
            next(u for u in units if str(u.get("id")) == sample),
            next(u for u in planned_units if str(u.get("id")) == sample))
        return (f"the game-design rewrites the adopted game's content under its own ids: "
                f"{len(changed)} of the {len(kept)} shipped unit(s) it keeps are other units "
                f"now (the content data shipped at {str(commit)[:12]}: {_listed(changed)}; "
                f"{sample} changes its {', '.join(fields)})." + rerun)
    return None
