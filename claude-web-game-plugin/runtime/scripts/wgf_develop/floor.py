"""The existing-content floor, held at the commit: an adopted game is improved, never rebuilt.

Observed (2026-10-04, both validation games): once init adopted the shipped checkouts, the
greybox developer rewrote them to the new design - 12,168 deletions in the 2D game, its
content data cut from 32 units to 12. The design records what the adopted repository ships
(game-design existing_content, wgf_design/existing.py); this module holds a development
commit to it:

    adopted(design)                 whether the run adopted a repository that ships content
    problems(checkout, design, git, findings_visit)
                                    (problems, allowed): what the working tree ships below
                                    the floor - its content data counted by the floor's own
                                    method - and the files the floor's commit shipped under
                                    `public/` that are gone. A visit routed with findings (a
                                    specialist) may remove a shipped file - returned in
                                    `allowed` - never content below the floor.
    shipped_units(checkout, design) the unit ids the checkout's content data lists
"""

import json
import os

from wgf_design import existing

__all__ = ["adopted", "problems", "shipped_units", "SHIPPED_ROOT"]

# The shipped files a commit may not lose: what the game serves.
SHIPPED_ROOT = "public"


def adopted(design):
    return isinstance((design or {}).get("existing_content"), dict)


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


def problems(checkout, design, git, findings_visit=False):
    floor = (design or {}).get("existing_content")
    if not isinstance(floor, dict):
        return [], []
    found = []
    data, problem = _content(checkout, floor)
    if data is None:
        found.append(f"{problem}; the adopted repository shipped {floor.get('units')} unit(s)")
    else:
        regressed, _measured = existing.regression(floor, data)
        found += regressed
    commit = (floor.get("source") or {}).get("commit")
    missing = [path for path in git.files_at(commit, SHIPPED_ROOT)
               if not os.path.lexists(os.path.join(checkout, *path.split("/")))]
    allowed = []
    if missing and findings_visit:
        allowed = missing
    elif missing:
        found.append(f"{len(missing)} file(s) the adopted repository shipped at "
                     f"{str(commit)[:12]} are gone: {', '.join(missing[:8])}"
                     + (f" and {len(missing) - 8} more" if len(missing) > 8 else ""))
    return found, allowed


def shipped_units(checkout, design):
    floor = (design or {}).get("existing_content") or {}
    data, _problem = _content(checkout, floor)
    return [str(u.get("id")) for u in (data or {}).get("units") or []
            if isinstance(u, dict) and u.get("id")]
