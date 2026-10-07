"""Which units the critic reads, and their frames: from what the playability bot recorded.

The bot's survey (bot.spec.ts, `with: survey`) enters every unit the design lists through the
probe's unit link and, for the level critic, keeps three frames of each - `level/<unit>-
<moment>.png` under the project's records, each with its sha256 and the entities the probe
reported then (`visits[].level_frames`). A build played before the bot captured them (or
whose survey did not run) still has the survey's one-second frame `survey-<unit>-1s`, else
the traverse's `unit-<index>-1s`: the unit is then sampled on its start alone, and the moments
it lacks are listed - the frames check is not passed on them.

`sample(rubric, report, run_dir, design)` returns at most the rubric's `sample.max_units`
units, spread across the sequence, each {unit_id, index, source, project, objective, frames:
[{moment, id, path (run-relative), source (absolute), sha256, entities}], missing_moments}.
`stage(units, workdir)` copies their frames into <workdir>/frames/<unit>/<moment>.png, each
checked against the sha256 recorded for it.
"""

import hashlib
import json
import os
import shutil

from wgf_playability.step import spread

__all__ = ["FrameError", "sample", "stage", "sha256_of", "PROJECT_ORDER"]

# The viewport the critic reads: content is the same on every viewport (the survey runs on
# desktop only), and the first one with records is used.
PROJECT_ORDER = ("desktop", "mobile")


class FrameError(Exception):
    """A frame is missing (`missing`) or not the one recorded (`changed`)."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def sha256_of(path):
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def design_units(design):
    """{unit id: unit} of the design's build_spec.content.units, and their ids in order."""
    content = ((design or {}).get("build_spec") or {}).get("content") or {}
    listed = [u for u in content.get("units") or [] if isinstance(u, dict) and u.get("id")]
    listed.sort(key=lambda u: (u.get("index") if isinstance(u.get("index"), int) else 10 ** 6,
                               str(u.get("id"))))
    return {str(u["id"]): u for u in listed}, [str(u["id"]) for u in listed]


def _report_frames(report, project, run_dir):
    """{frame id: (absolute path, run-relative path, sha256)} the playability-report lists."""
    out = {}
    for frame in (report or {}).get("frames") or []:
        if not isinstance(frame, dict) or frame.get("project") != project:
            continue
        rel = frame.get("path") or ""
        out[frame.get("id")] = (rel if os.path.isabs(rel) else os.path.join(run_dir, rel),
                                rel, frame.get("sha256"))
    return out


def _survey_units(survey, base, run_dir, listed, moments, report_frames):
    out = []
    for visit in survey.get("visits") or []:
        if not isinstance(visit, dict) or not visit.get("entered"):
            continue
        uid = str(visit.get("asked"))
        frames = []
        for entry in visit.get("level_frames") or []:
            if not isinstance(entry, dict) or entry.get("moment") not in moments:
                continue
            source = os.path.join(base, *str(entry.get("file") or "").split("/"))
            frames.append({"moment": entry["moment"], "id": f"level-{uid}-{entry['moment']}",
                           "source": source,
                           "path": os.path.relpath(source, run_dir).replace(os.sep, "/"),
                           "sha256": entry.get("sha256"),
                           "entities": entry.get("entities") or [],
                           "progress": entry.get("progress")})
        if not frames:
            found = report_frames.get(f"survey-{uid}-1s")
            if found:
                frames.append({"moment": moments[0], "id": f"survey-{uid}-1s",
                               "source": found[0], "path": found[1], "sha256": found[2],
                               "entities": [], "progress": None})
        out.append({"unit_id": uid, "index": visit.get("index"), "source": "survey",
                    "frames": frames})
    return out


def _traverse_units(traverse, report_frames, moments):
    out = []
    by_index = {u.get("index"): u for u in traverse.get("per_unit") or [] if isinstance(u, dict)}
    for name in traverse.get("frames") or []:
        if not (isinstance(name, str) and name.startswith("unit-") and name.endswith("-1s")):
            continue
        try:
            index = int(name[len("unit-"):-len("-1s")])
        except ValueError:
            continue
        unit = by_index.get(index) or {}
        found = report_frames.get(name)
        if not unit.get("unit_id") or not found:
            continue
        out.append({"unit_id": str(unit["unit_id"]), "index": index, "source": "traverse",
                    "frames": [{"moment": moments[0], "id": name, "source": found[0],
                                "path": found[1], "sha256": found[2], "entities": [],
                                "progress": None}],
                    "objective": unit.get("objective_texts", [None])[0]
                    if unit.get("objective_texts") else None})
    return out


def sample(rubric, report, run_dir, design):
    """(units, project, why) - the sampled units, the viewport read, and why there are none."""
    moments = [m["id"] for m in rubric["moments"]]
    records = (report or {}).get("records_dir")
    if not records:
        return [], None, "the playability-report names no records directory"
    by_id, order = design_units(design)
    for project in PROJECT_ORDER:
        base = os.path.join(run_dir, *records.split("/"), project)
        if not os.path.isdir(base):
            continue
        report_frames = _report_frames(report, project, run_dir)
        survey = _read(os.path.join(base, "survey.json")) or {}
        units = (_survey_units(survey, base, run_dir, order, moments, report_frames)
                 if survey.get("applies") else [])
        if not units:
            traverse = _read(os.path.join(base, "traverse.json")) or {}
            units = _traverse_units(traverse, report_frames, moments) \
                if traverse.get("applies") else []
        if not units:
            continue
        rank = {uid: i for i, uid in enumerate(order)}
        units.sort(key=lambda u: (rank.get(u["unit_id"], 10 ** 6), u.get("index") or 0))
        units = spread(units, int(rubric["sample"]["max_units"]))
        for unit in units:
            unit["project"] = project
            authored = by_id.get(unit["unit_id"]) or {}
            unit["objective"] = authored.get("objective") or unit.get("objective")
            unit["design"] = authored
            have = {f["moment"] for f in unit["frames"]}
            unit["missing_moments"] = [m for m in moments if m not in have]
        return units, project, None
    return [], None, ("the bot recorded no unit frames (no survey or traverse frames): the "
                      "design authors no units, or the build was not surveyed")


def stage(units, workdir):
    """Copy every unit's frames into <workdir>/frames/<unit>/<moment>.png, each checked against
    its recorded sha256. Returns the frames directory; sets each frame's `file` and `key`."""
    frames_dir = os.path.join(workdir, "frames")
    shutil.rmtree(frames_dir, ignore_errors=True)
    for unit in units:
        for frame in unit["frames"]:
            source = frame["source"]
            if not os.path.isfile(source):
                raise FrameError("missing", f"frame {frame['id']} of unit {unit['unit_id']} is "
                                            f"not at {source}")
            digest = sha256_of(source)
            if frame.get("sha256") and frame["sha256"] != digest:
                raise FrameError("changed", f"frame {frame['id']} at {source} is not the frame "
                                            f"the playability bot recorded ({frame['sha256']}, "
                                            f"now {digest})")
            frame["sha256"] = digest
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in unit["unit_id"])
            target = os.path.join(frames_dir, safe, frame["moment"] + ".png")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
            frame["file"] = target
            frame["key"] = f"{unit['unit_id']}/{frame['moment']}"
    return frames_dir
