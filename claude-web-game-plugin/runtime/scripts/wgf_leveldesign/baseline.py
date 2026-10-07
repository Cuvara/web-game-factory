"""The `baseline` critic: what pixels and the probe's entity boxes can measure, no agent.

    factory:
      leveldesign:
        judge:
          kind: baseline
          baseline_dir: <dir>     # optional: <unit>/<moment>.png approved frames + approved.json
          min_similarity: 0.90    # optional; default the rubric's baseline.min_similarity

It writes the verdict a command critic would (rubric.problems checks it), so the step
decides it the same way (rubric.decide):

    play_space              the share of the field's grid cells (level-design-rubric.yaml
                            baseline.grid) a content entity's box overlaps in any of the
                            unit's frames; the field is the box around every non-ui entity
                            the probe reported in them. No entity boxes (a frame the bot
                            recorded without them): null
    distinct_from_previous  the larger of 1 - the similarity of the unit's first frame to the
                            previous unit's (wgf_visualqa.baseline: palette, detail, layout)
                            and 1 - the Jaccard overlap of their used cells
    the other dimensions    from <baseline_dir>/approved.json ({"<unit id>": {"scores":
                            {...}}}, a person's scores) when every frame of the unit matches
                            its approved frame <baseline_dir>/<unit>/<moment>.png at
                            min_similarity; else null - UNMEASURED, never a pass

Measures map to scores by the rubric's `baseline` ladders. It raises no blocker: a crude
measure that fails is a low score, which fails its unit already.
"""

import json
import os

from wgf_assets.raster import RasterError, decode_png
from wgf_visualqa.baseline import signature, similarity

from .rubric import applicable, dimensions

__all__ = ["BaselineError", "judge", "play_space", "used_cells", "ladder"]

MECHANICAL = ("play_space", "distinct_from_previous")


class BaselineError(ValueError):
    """The baseline directory is unusable."""


def ladder(rungs, value):
    """The highest rung's score whose `at_least` `value` reaches; 0 below the first."""
    score = 0
    for rung in sorted(rungs, key=lambda r: r["at_least"]):
        if value >= rung["at_least"]:
            score = rung["score"]
    return score


def _boxes(frame):
    """[(role, x, y, w, h)] of a level frame's recorded entities ([role, kind, x, y, w, h])."""
    out = []
    for entity in frame.get("entities") or []:
        if isinstance(entity, (list, tuple)) and len(entity) >= 6 and all(
                isinstance(v, (int, float)) for v in entity[2:6]):
            out.append((str(entity[0]), *(float(v) for v in entity[2:6])))
    return out


def used_cells(frames, grid, content_roles):
    """(used cell set, cell count) over the field of `frames`, or (None, 0) without boxes."""
    boxes = [b for f in frames for b in _boxes(f)]
    if not boxes:
        return None, 0
    x0 = min(b[1] for b in boxes)
    y0 = min(b[2] for b in boxes)
    x1 = max(b[1] + b[3] for b in boxes)
    y1 = max(b[2] + b[4] for b in boxes)
    cols, rows = grid
    width, height = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    used = set()
    for role, x, y, w, h in boxes:
        if role not in content_roles:
            continue
        c0 = int((x - x0) / width * cols)
        c1 = int(min(x + w - x0, width - 1e-9) / width * cols)
        r0 = int((y - y0) / height * rows)
        r1 = int(min(y + h - y0, height - 1e-9) / height * rows)
        for c in range(max(c0, 0), min(c1, cols - 1) + 1):
            for r in range(max(r0, 0), min(r1, rows - 1) + 1):
                used.add((c, r))
    return used, cols * rows


def play_space(frames, grid, content_roles):
    used, total = used_cells(frames, grid, content_roles)
    return None if used is None else round(len(used) / total, 4)


def _signature(path):
    try:
        with open(path, "rb") as handle:
            return signature(decode_png(handle.read()))
    except (OSError, RasterError) as exc:
        raise BaselineError(f"cannot read {path}: {exc}")


def _approved(baseline_dir):
    if not baseline_dir:
        return {}
    if not os.path.isdir(baseline_dir):
        raise BaselineError(f"baseline_dir {baseline_dir} is not a directory")
    path = os.path.join(baseline_dir, "approved.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise BaselineError(f"{path} cannot be read: {exc}")
    if not isinstance(data, dict):
        raise BaselineError(f"{path} must map unit ids to {{scores}}")
    return data


def judge(rubric, units, baseline_dir=None, min_similarity=None):
    """(verdict, measures): the baseline verdict for staged `units`, and per unit what was
    measured (kept beside the frames, and in the report's units[].measures)."""
    base = rubric["baseline"]
    bar = min_similarity or base.get("min_similarity") or 0.9
    roles = set(base.get("content_roles") or [])
    approved = _approved(baseline_dir)
    verdict = {"units": [], "findings": [],
               "notes": "baseline critic: play_space and distinct_from_previous are measured "
                        "from entity boxes and frame signatures; every other dimension is a "
                        "person's approved score where the frames match, else null "
                        "(unmeasured). No taste is judged."}
    measures = {}
    previous = None
    for position, unit in enumerate(units):
        frames = unit["frames"]
        first = frames[0] if frames else None
        sig = _signature(first["file"]) if first else None
        used, _total = used_cells(frames, base["grid"], roles)
        scores, reasons, measured = {}, {}, {}
        share = play_space(frames, base["grid"], roles)
        measured["play_space"] = share
        if share is None:
            scores["play_space"] = None
            reasons["play_space"] = "no entity boxes were recorded with this unit's frames"
        else:
            scores["play_space"] = ladder(base["play_space"], share)
            reasons["play_space"] = (f"content entities overlap {share:.0%} of the field's "
                                     f"{base['grid'][0]}x{base['grid'][1]} cells")
        if not applicable(rubric, "distinct_from_previous", position):
            scores["distinct_from_previous"] = None
        elif previous is None or sig is None or previous["sig"] is None:
            scores["distinct_from_previous"] = None
            reasons["distinct_from_previous"] = "no frame to compare with the previous unit's"
        else:
            sim, _parts = similarity(sig, previous["sig"])
            parts = [round(1 - sim, 4)]
            if used is not None and previous["used"] is not None and (used | previous["used"]):
                parts.append(round(1 - len(used & previous["used"])
                                   / len(used | previous["used"]), 4))
            difference = max(parts)
            measured["distinct_from_previous"] = {"frame_difference": parts[0],
                                                  "cell_difference": parts[1]
                                                  if len(parts) > 1 else None}
            scores["distinct_from_previous"] = ladder(base["distinct_from_previous"],
                                                      difference)
            reasons["distinct_from_previous"] = (
                f"{difference:.0%} different from {previous['unit_id']} (frame "
                f"{parts[0]:.0%}" + (f", cells {parts[1]:.0%}" if len(parts) > 1 else "")
                + ")")
        matched = _matches(unit, baseline_dir, bar) if approved.get(unit["unit_id"]) else None
        measured["approved_match"] = matched
        approved_scores = ((approved.get(unit["unit_id"]) or {}).get("scores") or {}) \
            if matched and matched["all"] else {}
        for name in dimensions(rubric):
            if name in MECHANICAL:
                continue
            value = approved_scores.get(name)
            scores[name] = value if isinstance(value, (int, float)) and not isinstance(
                value, bool) else None
            reasons[name] = ("a person's approved score; every frame matches its approved "
                             "frame" if scores[name] is not None else
                             "not measurable without a critic: no approved score for frames "
                             "that match")
        verdict["units"].append({"unit_id": unit["unit_id"], "scores": scores,
                                 "score_reasons": reasons,
                                 "comment": "measured, not judged (baseline critic)"})
        measures[unit["unit_id"]] = measured
        previous = {"unit_id": unit["unit_id"], "sig": sig, "used": used}
    return verdict, measures


def _matches(unit, baseline_dir, bar):
    """{all: bool, frames: {moment: similarity | None}}: each frame against its approved one."""
    out, every = {}, bool(unit["frames"])
    for frame in unit["frames"]:
        approved = os.path.join(baseline_dir, unit["unit_id"], frame["moment"] + ".png")
        if not os.path.isfile(approved):
            out[frame["moment"]] = None
            every = False
            continue
        sim, _parts = similarity(_signature(frame["file"]), _signature(approved))
        out[frame["moment"]] = sim
        every = every and sim >= bar
    return {"all": every and not unit.get("missing_moments"), "frames": out}
